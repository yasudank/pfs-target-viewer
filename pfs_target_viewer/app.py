#!/usr/bin/env python3
"""
PFS Target & Spectrum Viewer - Backend Application
Provides REST API and static web dashboard for inspecting PFS target metadata,
PNG spectra, and interactive FITS spectra from pfs_metadata.sqlite3 and extracted_targets.
"""
import glob
import hashlib
import io
import json
import gzip
import os
import sqlite3
import time
import urllib.parse
import math
import re
import threading
import urllib.request
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Set, Tuple
import numpy as np
from pydantic import BaseModel
try:
    from PIL import Image, ImageStat
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from astropy.io import fits
from fastapi import FastAPI, HTTPException, Query, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Base directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BASE_DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))

DB_PATH = ""
DATA_DIR = ""
FITS_DIR = ""
PNG_DIR = ""
CUTOUT_CACHE_DIR = ""


def resolve_paths(
    target_dir: Optional[str] = None,
    db_path: Optional[str] = None,
    data_dir: Optional[str] = None,
) -> tuple[str, str]:
    """Resolve database path and data directory from user inputs, environment variables, or defaults."""
    # 1. Determine base dataset directory
    raw_dir = (
        target_dir
        or os.getenv("PFS_DATA_ROOT")
        or os.getenv("PFS_DIR")
        or os.getenv("PFS_DATASET_DIR")
    )

    if raw_dir:
        resolved_base = os.path.abspath(os.path.expanduser(raw_dir))
    else:
        resolved_base = DEFAULT_BASE_DATA_DIR

    # Candidate defaults based on resolved_base
    if resolved_base.endswith((".sqlite3", ".db")) or os.path.isfile(resolved_base):
        candidate_db = resolved_base
        parent_dir = os.path.dirname(resolved_base)
        candidate_data_dir = os.path.join(parent_dir, "extracted_targets")
    else:
        candidate_db = os.path.join(resolved_base, "pfs_metadata.sqlite3")
        # Check if candidate_db exists; if not, check common alternative database names
        if not os.path.exists(candidate_db):
            for alt_name in ["pfs_targets.db", "pfs_catalog.db", "targets.sqlite3", "metadata.sqlite3"]:
                alt_path = os.path.join(resolved_base, alt_name)
                if os.path.exists(alt_path):
                    candidate_db = alt_path
                    break
            else:
                db_files = [f for f in glob.glob(os.path.join(resolved_base, "*.sqlite3")) if not os.path.basename(f).startswith(".")]
                if db_files:
                    candidate_db = sorted(db_files)[0]

        # Check if resolved_base directly contains extracted_targets or is extracted_targets itself
        if os.path.isdir(os.path.join(resolved_base, "extracted_targets")):
            candidate_data_dir = os.path.join(resolved_base, "extracted_targets")
        elif os.path.isdir(os.path.join(resolved_base, "fits")):
            candidate_data_dir = resolved_base
        else:
            candidate_data_dir = os.path.join(resolved_base, "extracted_targets")

    # 2. Explicit overrides (cmdline or specific env vars) take precedence
    final_db = db_path or os.getenv("PFS_DB_PATH") or candidate_db
    final_data = data_dir or os.getenv("PFS_DATA_DIR") or candidate_data_dir

    return os.path.abspath(os.path.expanduser(final_db)), os.path.abspath(os.path.expanduser(final_data))


# In-memory file index caches for ultra-fast O(1) lookups without disk/NFS I/O
FITS_FILE_SET: Set[str] = set()
PNG_FILE_SET: Set[str] = set()
_FILES_INDEXED: bool = False


def index_extracted_files(force: bool = False):
    """Index FITS and PNG filenames once into memory sets for instant O(1) lookups."""
    global FITS_FILE_SET, PNG_FILE_SET, _FILES_INDEXED
    if _FILES_INDEXED and not force:
        return

    t0 = time.time()
    fits_count = 0
    png_count = 0

    if os.path.exists(FITS_DIR):
        try:
            FITS_FILE_SET = set(os.listdir(FITS_DIR))
            fits_count = len(FITS_FILE_SET)
        except Exception as e:
            print(f"Warning: Failed reading FITS dir {FITS_DIR}: {e}")

    if os.path.exists(PNG_DIR):
        try:
            PNG_FILE_SET = set(os.listdir(PNG_DIR))
            png_count = len(PNG_FILE_SET)
        except Exception as e:
            print(f"Warning: Failed reading PNG dir {PNG_DIR}: {e}")

    _FILES_INDEXED = True
    print(f"  ⚡ In-memory file index built in {time.time()-t0:.3f}s: {fits_count:,} FITS, {png_count:,} PNG files.")


def is_blank_or_out_of_coverage(data: bytes) -> bool:
    """
    Check if returned image is an empty/blank/constant-value frame generated
    when target coordinates are outside astronomical survey coverage
    (e.g., pure white dummy frames of ~4955 bytes from HSC, or pure black frames).
    """
    if not data or len(data) < 100:
        return True
    if len(data) < 2000:
        return True

    if HAS_PIL:
        try:
            with Image.open(io.BytesIO(data)) as img:
                gray = img.convert("L")
                stat = ImageStat.Stat(gray)
                min_val, max_val = stat.extrema[0]
                # 1. Pure constant pixel value (min == max)
                if min_val == max_val:
                    return True
                # 2. Negligible dynamic range (compression noise on constant background)
                if (max_val - min_val) < 5:
                    return True
                # 3. Standard deviation check (real sky cutouts have stddev > 2.0 due to noise/stars)
                std_val = stat.stddev[0]
                if std_val < 1.0:
                    return True
                # 4. Extreme uniform backgrounds (almost pure white > 250 or pure black < 1.0)
                mean_val = stat.mean[0]
                if mean_val > 250.0 or mean_val < 1.0:
                    return True
        except Exception:
            return True
    else:
        # Fallback if PIL is not installed: catch known HSC/CDS placeholder byte signatures
        if 4900 <= len(data) <= 5000:
            return True

    return False


def cleanup_blank_cutout_cache():
    """Scan cutout_cache directory and purge previously cached blank/dummy frames."""
    if not os.path.exists(CUTOUT_CACHE_DIR):
        return
    removed = 0
    for img_path in glob.glob(os.path.join(CUTOUT_CACHE_DIR, "*.jpg")):
        try:
            with open(img_path, "rb") as f:
                data = f.read()
            if is_blank_or_out_of_coverage(data):
                meta_path = img_path.replace(".jpg", ".json")
                if os.path.exists(img_path):
                    os.remove(img_path)
                if os.path.exists(meta_path):
                    os.remove(meta_path)
                removed += 1
        except Exception:
            pass
    if removed > 0:
        print(f"  🧹 Cleaned up {removed} blank/dummy cutout image(s) from cache.")


def configure_paths(
    target_dir: Optional[str] = None,
    db_path: Optional[str] = None,
    data_dir: Optional[str] = None,
):
    """Configure global path variables, cache directories, and build file index."""
    global DB_PATH, DATA_DIR, FITS_DIR, PNG_DIR, CUTOUT_CACHE_DIR, _FILES_INDEXED, _DB_HAS_FILE_COLS
    old_db = DB_PATH
    DB_PATH, DATA_DIR = resolve_paths(target_dir=target_dir, db_path=db_path, data_dir=data_dir)
    FITS_DIR = os.path.join(DATA_DIR, "fits")
    PNG_DIR = os.path.join(DATA_DIR, "png")
    CUTOUT_CACHE_DIR = os.path.join(DATA_DIR, "cutout_cache")
    if os.path.exists(DATA_DIR):
        try:
            os.makedirs(CUTOUT_CACHE_DIR, exist_ok=True)
        except OSError:
            pass
    _FILES_INDEXED = False
    _DB_HAS_FILE_COLS = None
    index_extracted_files()
    cleanup_blank_cutout_cache()

    # Clear query cache and pre-warm master sky cache when switching datasets
    if old_db and old_db != DB_PATH:
        if "SQL_CACHE" in globals() and SQL_CACHE is not None:
            SQL_CACHE.clear()
        if "load_or_build_master_sky_cache" in globals() and os.path.exists(DB_PATH):
            threading.Thread(
                target=load_or_build_master_sky_cache,
                kwargs={"force": False, "db_path": DB_PATH},
                daemon=True,
            ).start()


# Initialize defaults
configure_paths()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-warm master sky cache in background thread when server starts
    if os.path.exists(DB_PATH):
        threading.Thread(
            target=load_or_build_master_sky_cache,
            kwargs={"db_path": DB_PATH},
            daemon=True,
        ).start()
    yield


app = FastAPI(
    title="PFS Target & Spectrum Viewer",
    description="Interactive Web Dashboard for PFS Targets & Coadded Spectra",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Static & Template files
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


def register_sql_functions(conn: sqlite3.Connection):
    """Register custom astronomical and spatial functions into SQLite."""
    deg2rad = math.pi / 180.0
    rad2deg = 180.0 / math.pi

    def _cone_dist_deg(ra1, dec1, ra2, dec2):
        if ra1 is None or dec1 is None or ra2 is None or dec2 is None:
            return None
        try:
            r1, d1 = float(ra1) * deg2rad, float(dec1) * deg2rad
            r2, d2 = float(ra2) * deg2rad, float(dec2) * deg2rad
            dlat = d2 - d1
            dlon = r2 - r1
            a = (math.sin(dlat * 0.5) ** 2) + math.cos(d1) * math.cos(d2) * (math.sin(dlon * 0.5) ** 2)
            return 2.0 * math.asin(math.sqrt(min(1.0, max(0.0, a)))) * rad2deg
        except Exception:
            return None

    def _cone_dist_arcsec(ra1, dec1, ra2, dec2):
        d = _cone_dist_deg(ra1, dec1, ra2, dec2)
        return (d * 3600.0) if d is not None else None

    def _cone_search(ra, dec, c_ra, c_dec, radius_arcsec):
        d = _cone_dist_arcsec(ra, dec, c_ra, c_dec)
        if d is None:
            return 0
        return 1 if d <= float(radius_arcsec) else 0

    conn.create_function("CONE_DIST_DEG", 4, _cone_dist_deg)
    conn.create_function("CONE_DIST_ARCSEC", 4, _cone_dist_arcsec)
    conn.create_function("CONE_SEARCH", 5, _cone_search)


def set_query_timeout(conn: sqlite3.Connection, timeout_sec: float = 6.0):
    """Interrupt queries that exceed execution time limit to prevent server stalls."""
    start_time = time.time()

    def _progress():
        if time.time() - start_time > timeout_sec:
            return 1  # non-zero interrupts SQLite query execution
        return 0

    conn.set_progress_handler(_progress, 20000)


def get_db():
    """Connect to SQLite database in read-only mode with custom functions registered."""
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=500, detail=f"Database file not found at {DB_PATH}")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    register_sql_functions(conn)
    return conn


_DB_HAS_FILE_COLS: Optional[bool] = None


def check_db_file_columns(conn: sqlite3.Connection) -> bool:
    """Check if target_summary has has_fits, fits_path, has_png, png_path columns."""
    global _DB_HAS_FILE_COLS
    if _DB_HAS_FILE_COLS is not None:
        return _DB_HAS_FILE_COLS
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(target_summary)")
        cols = {row[1] for row in cur.fetchall()}
        _DB_HAS_FILE_COLS = "has_fits" in cols and "fits_path" in cols
    except Exception:
        _DB_HAS_FILE_COLS = False
    return _DB_HAS_FILE_COLS


def get_summary_table(conn: sqlite3.Connection) -> str:
    """Return target_summary if materialized table exists, otherwise fallback to v_target_summary."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='target_summary'")
    if cur.fetchone():
        return "target_summary"
    return "v_target_summary"


def clean_str_name(name: str) -> str:
    """Sanitize filename component."""
    return "".join(c if (c.isalnum() or c in "._-") else "_" for c in name)


def find_files(
    cat_id: int,
    obj_id: int,
    ob_code: Optional[str] = None,
    combination: Optional[Union[str, int]] = None,
    known_fits_path: Optional[str] = None,
    known_png_path: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Locate matching FITS and PNG files.
    Priority:
    1. Direct DB recorded relative path (known_fits_path, known_png_path)
    2. Sharded location: fits/{catId}/{slot:03d}/pfsObject_{base}.fits
    3. Flat location: fits/pfsObject_{base}.fits (checked via in-memory set)
    """
    fits_path = None
    png_path = None

    # 1. Use known DB paths if provided and existing
    if known_fits_path:
        p = os.path.join(DATA_DIR, known_fits_path) if not os.path.isabs(known_fits_path) else known_fits_path
        if os.path.exists(p):
            fits_path = p
    if known_png_path:
        p = os.path.join(DATA_DIR, known_png_path) if not os.path.isabs(known_png_path) else known_png_path
        if os.path.exists(p):
            png_path = p

    if fits_path and png_path:
        return fits_path, png_path

    # Candidate basenames (both with combination suffix and without)
    candidates_base = []
    comb_str = str(combination).strip() if (combination is not None and str(combination).strip() != "") else None
    if ob_code and comb_str:
        candidates_base.append(clean_str_name(f"{ob_code}_{cat_id}_{obj_id}_{comb_str}"))
    if ob_code:
        candidates_base.append(clean_str_name(f"{ob_code}_{cat_id}_{obj_id}"))
    if comb_str:
        candidates_base.append(f"{cat_id}_{obj_id}_{comb_str}")
    candidates_base.append(f"{cat_id}_{obj_id}")

    shard_slot = f"{int(obj_id) % 1000:03d}"
    shard_sub = os.path.join(str(cat_id), shard_slot)

    # 2. Check sharded location on disk
    if not fits_path:
        shard_fits_dir = os.path.join(FITS_DIR, shard_sub)
        for base in candidates_base:
            fn = f"pfsObject_{base}.fits"
            p = os.path.join(shard_fits_dir, fn)
            if os.path.exists(p):
                fits_path = p
                break

    if not png_path:
        shard_png_dir = os.path.join(PNG_DIR, shard_sub)
        for base in candidates_base:
            pn = f"spec_{base}.png"
            p = os.path.join(shard_png_dir, pn)
            if os.path.exists(p):
                png_path = p
                break

    if fits_path and png_path:
        return fits_path, png_path

    # 3. Fallback to flat directory via in-memory set
    if not _FILES_INDEXED:
        index_extracted_files()

    if not fits_path:
        for base in candidates_base:
            fn = f"pfsObject_{base}.fits"
            if fn in FITS_FILE_SET:
                fits_path = os.path.join(FITS_DIR, fn)
                break

    if not png_path:
        for base in candidates_base:
            pn = f"spec_{base}.png"
            if pn in PNG_FILE_SET:
                png_path = os.path.join(PNG_DIR, pn)
                break

    return fits_path, png_path


def sanitize_val(v: Any) -> Any:
    """Convert NaN/Inf and numpy numbers to JSON-compliant types."""
    if v is None:
        return None
    if isinstance(v, (np.floating, float)):
        if np.isnan(v) or np.isinf(v):
            return None
        return float(v)
    if isinstance(v, (np.integer, int)):
        return int(v)
    if isinstance(v, (np.str_, str)):
        return str(v)
    return v


# -----------------------------------------------------------------------------
# Precomputed Full-Sky Celestial Coordinates In-Memory & Disk Cache
# -----------------------------------------------------------------------------
_CURRENT_CACHED_DB_PATH: Optional[str] = None
_MASTER_SKY_LOCK = threading.Lock()
_MASTER_SKY_GZIP_BYTES: Optional[bytes] = None
_MASTER_SKY_JSON_BYTES: Optional[bytes] = None
_MASTER_SKY_ETAG: Optional[str] = None


def get_sky_cache_file_path(db_path: Optional[str] = None) -> str:
    """Return path to persistent disk cache for full sky celestial coordinates for given database."""
    target_db = db_path or DB_PATH
    if not target_db:
        base_dir = DEFAULT_BASE_DATA_DIR
        prefix = "pfs_metadata"
    else:
        base_dir = os.path.dirname(os.path.abspath(target_db))
        base_name = os.path.splitext(os.path.basename(target_db))[0]
        prefix = base_name
    return os.path.join(base_dir, f".{prefix}_sky_cache.json.gz")


def load_or_build_master_sky_cache(force: bool = False, db_path: Optional[str] = None) -> Tuple[Optional[bytes], Optional[bytes], Optional[str]]:
    """
    Ensure the full celestial sky coordinates are cached in memory (both gzip and raw json bytes)
    for the currently active database (DB_PATH or specified db_path).
    1. Loads from persistent .{dbname}_sky_cache.json.gz (or legacy .sky_positions_cache.json.gz) in ~2ms.
    2. Otherwise queries the active SQLite database, serializes, compresses, and saves disk cache.
    """
    global _MASTER_SKY_GZIP_BYTES, _MASTER_SKY_JSON_BYTES, _MASTER_SKY_ETAG, _CURRENT_CACHED_DB_PATH

    active_db = os.path.abspath(db_path or DB_PATH) if (db_path or DB_PATH) else ""
    if not active_db or not os.path.exists(active_db):
        return None, None, None

    # If active database changed since last cache load, memory cache must be updated
    db_changed = (_CURRENT_CACHED_DB_PATH != active_db)

    if not force and not db_changed and _MASTER_SKY_GZIP_BYTES is not None and _MASTER_SKY_JSON_BYTES is not None:
        return _MASTER_SKY_GZIP_BYTES, _MASTER_SKY_JSON_BYTES, _MASTER_SKY_ETAG

    with _MASTER_SKY_LOCK:
        db_changed = (_CURRENT_CACHED_DB_PATH != active_db)
        if not force and not db_changed and _MASTER_SKY_GZIP_BYTES is not None and _MASTER_SKY_JSON_BYTES is not None:
            return _MASTER_SKY_GZIP_BYTES, _MASTER_SKY_JSON_BYTES, _MASTER_SKY_ETAG

        cache_file = get_sky_cache_file_path(active_db)
        legacy_cache_file = os.path.join(os.path.dirname(active_db), ".sky_positions_cache.json.gz")
        chosen_cache_file = cache_file if os.path.exists(cache_file) else (legacy_cache_file if os.path.exists(legacy_cache_file) else cache_file)

        db_mtime = os.path.getmtime(active_db)

        # 1. Try reading from disk cache if valid and newer than database (even after db switch, disk cache is preferred over rebuilding)
        if not force and os.path.exists(chosen_cache_file) and os.path.getmtime(chosen_cache_file) >= db_mtime:
            try:
                t0 = time.time()
                with open(chosen_cache_file, "rb") as f:
                    gz_data = f.read()
                raw_data = gzip.decompress(gz_data)
                etag = f'W/"sky-{len(gz_data)}-{int(db_mtime)}"'
                _MASTER_SKY_GZIP_BYTES = gz_data
                _MASTER_SKY_JSON_BYTES = raw_data
                _MASTER_SKY_ETAG = etag
                _CURRENT_CACHED_DB_PATH = active_db
                print(f"  ⚡ Loaded master sky coordinates cache ({len(gz_data)/1024/1024:.2f} MB gzip) for {active_db} in {(time.time()-t0)*1000:.1f} ms")
                return _MASTER_SKY_GZIP_BYTES, _MASTER_SKY_JSON_BYTES, _MASTER_SKY_ETAG
            except Exception as e:
                print(f"Warning: Failed reading sky disk cache: {e}. Rebuilding from database...")

        # 2. Build from active SQLite database
        try:
            t0 = time.time()
            conn = sqlite3.connect(f"file:{active_db}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            register_sql_functions(conn)
            cur = conn.cursor()
            tbl = get_summary_table(conn)
            has_file_cols = check_db_file_columns(conn)
            file_select = ", t.has_fits, t.has_png" if has_file_cols else ""
            sql = f"""
                SELECT 
                    t.catId, t.objId, t.obCode, t.ra, t.dec,
                    t.classificationName, t.bestRedshift, t.bestVelocity
                    {file_select}
                FROM {tbl} t
                WHERE t.ra IS NOT NULL AND t.dec IS NOT NULL
            """
            cur.execute(sql)
            rows = cur.fetchall()
            results = []
            for r in rows:
                results.append({
                    "catId": r["catId"],
                    "objId": str(r["objId"]),
                    "obCode": r["obCode"] or "",
                    "ra": sanitize_val(r["ra"]),
                    "dec": sanitize_val(r["dec"]),
                    "classificationName": r["classificationName"] or "UNKNOWN",
                    "bestRedshift": sanitize_val(r["bestRedshift"]),
                    "bestVelocity": sanitize_val(r["bestVelocity"]),
                    "has_fits": bool(r["has_fits"]) if has_file_cols else True,
                    "has_png": bool(r["has_png"]) if has_file_cols else True,
                })
            conn.close()

            raw_bytes = json.dumps({"total": len(results), "targets": results}).encode("utf-8")
            gz_bytes = gzip.compress(raw_bytes, compresslevel=6)
            etag = f'W/"sky-{len(gz_bytes)}-{int(db_mtime)}"'

            _MASTER_SKY_GZIP_BYTES = gz_bytes
            _MASTER_SKY_JSON_BYTES = raw_bytes
            _MASTER_SKY_ETAG = etag
            _CURRENT_CACHED_DB_PATH = active_db

            try:
                with open(cache_file, "wb") as f:
                    f.write(gz_bytes)
            except Exception as e:
                print(f"Warning: Could not save sky disk cache: {e}")

            print(f"  ⚡ Built master sky coordinates cache ({len(results):,} targets, {len(gz_bytes)/1024/1024:.2f} MB gzip) for {active_db} in {time.time()-t0:.2f}s")
            return _MASTER_SKY_GZIP_BYTES, _MASTER_SKY_JSON_BYTES, _MASTER_SKY_ETAG
        except Exception as e:
            print(f"Error building master sky coordinates cache for {active_db}: {e}")
            return None, None, None


# -----------------------------------------------------------------------------
# Frontend Route
# -----------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    """Render the main dashboard interface."""
    return templates.TemplateResponse(request=request, name="index.html")


# -----------------------------------------------------------------------------
# API Routes
# -----------------------------------------------------------------------------
_STATS_CACHE: Optional[Dict[str, Any]] = None


@app.get("/api/stats")
def get_stats(refresh: bool = Query(False, description="Force refresh statistics cache")):
    """Get repository overview statistics (cached in memory for instant response)."""
    global _STATS_CACHE
    if _STATS_CACHE is not None and not refresh:
        return _STATS_CACHE

    conn = get_db()
    cur = conn.cursor()
    try:
        tbl = get_summary_table(conn)
        cur.execute(f"SELECT count(*) FROM {tbl}")
        total = cur.fetchone()[0]

        cur.execute(f"SELECT classificationName, count(*) FROM {tbl} GROUP BY classificationName")
        class_counts = {row[0] or "UNKNOWN": row[1] for row in cur.fetchall()}

        cur.execute(f"SELECT count(DISTINCT catId) FROM {tbl}")
        cat_count = cur.fetchone()[0]

        cur.execute(f"SELECT catId, count(*) FROM {tbl} GROUP BY catId ORDER BY catId ASC")
        cat_counts = {int(row[0]): row[1] for row in cur.fetchall()}

        cur.execute(f"SELECT count(DISTINCT combination) FROM {tbl}")
        comb_count = cur.fetchone()[0]

        result = {
            "total_targets": total,
            "classification_counts": class_counts,
            "catalogs_count": cat_count,
            "cat_ids": cat_counts,
            "combinations_count": comb_count,
            "db_path": DB_PATH,
            "data_dir": DATA_DIR,
            "table_used": tbl,
        }
        _STATS_CACHE = result
        return result
    finally:
        conn.close()


def build_spatial_clauses(
    min_ra: Optional[float],
    max_ra: Optional[float],
    min_dec: Optional[float],
    max_dec: Optional[float],
) -> Tuple[List[str], List[Any]]:
    clauses: List[str] = []
    params: List[Any] = []

    if min_dec is not None:
        clauses.append("t.dec >= ?")
        params.append(min_dec)
    if max_dec is not None:
        clauses.append("t.dec <= ?")
        params.append(max_dec)

    if min_ra is not None and max_ra is not None:
        if min_ra <= max_ra:
            clauses.append("t.ra >= ? AND t.ra <= ?")
            params.extend([min_ra, max_ra])
        else:
            # RA wraps around 360 / 0 deg (e.g. 350 to 20)
            clauses.append("(t.ra >= ? OR t.ra <= ?)")
            params.extend([min_ra, max_ra])
    elif min_ra is not None:
        clauses.append("t.ra >= ?")
        params.append(min_ra)
    elif max_ra is not None:
        clauses.append("t.ra <= ?")
        params.append(max_ra)

    return clauses, params


@app.get("/api/targets")
def get_targets(
    q: Optional[str] = Query(None, description="Search query in obCode, objId, or catId"),
    classification: Optional[str] = Query(None, description="Filter by classification (GALAXY, QSO, STAR)"),
    min_z: Optional[float] = Query(None, description="Minimum redshift"),
    max_z: Optional[float] = Query(None, description="Maximum redshift"),
    cat_id: Optional[int] = Query(None, description="Filter by catId"),
    combination: Optional[str] = Query(None, description="Filter by combination"),
    min_ra: Optional[float] = Query(None, description="Minimum Right Ascension (deg)"),
    max_ra: Optional[float] = Query(None, description="Maximum Right Ascension (deg)"),
    min_dec: Optional[float] = Query(None, description="Minimum Declination (deg)"),
    max_dec: Optional[float] = Query(None, description="Maximum Declination (deg)"),
    has_fits: Optional[bool] = Query(None, description="Filter targets that have FITS files"),
    has_png: Optional[bool] = Query(None, description="Filter targets that have PNG spectra"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    limit: int = Query(25, ge=5, le=100, description="Items per page"),
    sort_by: str = Query("redshift", description="Sort field"),
    order: str = Query("asc", description="Sort order (asc, desc)"),
):
    """Search and paginate targets from target_summary / v_target_summary."""
    allowed_sort_fields = {
        "objId": "t.objId",
        "catId": "t.catId",
        "obCode": "t.obCode",
        "ra": "t.ra",
        "dec": "t.dec",
        "coords_ra": "t.ra",
        "coords_dec": "t.dec",
        "classification": "t.classificationName",
        "classificationName": "t.classificationName",
        "redshift": "t.bestRedshift",
        "bestRedshift": "t.bestRedshift",
        "velocity": "t.bestVelocity",
        "bestVelocity": "t.bestVelocity",
        "subclass": "t.bestSubClass",
        "bestSubClass": "t.bestSubClass",
        "probaGalaxy": "t.probaGalaxy",
        "probaQSO": "t.probaQSO",
        "probaStar": "t.probaStar",
        "nvisit": "t.nvisit",
        "exptime": "t.exptime",
    }
    sort_col = allowed_sort_fields.get(sort_by, "t.objId")
    sort_order = "DESC" if order.lower() == "desc" else "ASC"

    where_clauses = []
    params: List[Any] = []

    if q:
        q_clean = q.strip()
        if q_clean.isdigit():
            where_clauses.append("(t.objId = ? OR t.obCode LIKE ? OR t.catId = ?)")
            params.extend([int(q_clean), f"%{q_clean}%", int(q_clean)])
        else:
            where_clauses.append("t.obCode LIKE ?")
            params.append(f"%{q_clean}%")

    if classification and classification.upper() != "ALL":
        where_clauses.append("t.classificationName = ?")
        params.append(classification.upper())

    if min_z is not None:
        where_clauses.append("t.bestRedshift >= ?")
        params.append(min_z)

    if max_z is not None:
        where_clauses.append("t.bestRedshift <= ?")
        params.append(max_z)

    if cat_id is not None:
        where_clauses.append("t.catId = ?")
        params.append(cat_id)

    if combination:
        where_clauses.append("t.combination = ?")
        params.append(combination)

    # Spatial box filter (RA / Dec)
    spatial_clauses, spatial_params = build_spatial_clauses(min_ra, max_ra, min_dec, max_dec)
    where_clauses.extend(spatial_clauses)
    params.extend(spatial_params)

    conn = get_db()
    cur = conn.cursor()
    try:
        tbl = get_summary_table(conn)
        cur.execute(f"PRAGMA table_info({tbl})")
        tbl_cols = {row[1] for row in cur.fetchall()}
        has_file_cols = "has_fits" in tbl_cols and "fits_path" in tbl_cols
        extra_cols = []
        if "nvisit" in tbl_cols:
            extra_cols.append("t.nvisit")
        if "exptime" in tbl_cols:
            extra_cols.append("t.exptime")
        extra_select = (", ".join(extra_cols) + ",") if extra_cols else ""

        if has_file_cols:
            if has_fits is not None:
                where_clauses.append("t.has_fits = ?")
                params.append(1 if has_fits else 0)
            if has_png is not None:
                where_clauses.append("t.has_png = ?")
                params.append(1 if has_png else 0)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        # Count total
        count_sql = f"SELECT count(*) FROM {tbl} t {where_sql}"
        cur.execute(count_sql, params)
        total = cur.fetchone()[0]

        # Fetch page items
        offset = (page - 1) * limit
        file_select = "t.has_fits, t.fits_path, t.has_png, t.png_path," if has_file_cols else ""
        data_sql = f"""
            SELECT 
                t.catId, t.objId, t.combination, t.objGroup,
                t.obCode, t.targetTypeName, t.fiberStatusName, t.ra, t.dec,
                t.classificationName, t.probaGalaxy, t.probaStar, t.probaQSO,
                t.bestRedshift, t.bestRedshiftError, t.bestVelocity, t.bestVelocityError,
                t.bestSubClass, t.hasSolution,
                {extra_select}
                {file_select}
                1 AS _dummy
            FROM {tbl} t
            {where_sql}
            ORDER BY {sort_col} {sort_order} NULLS LAST, t.objId ASC
            LIMIT ? OFFSET ?
        """
        cur.execute(data_sql, params + [limit, offset])
        rows = cur.fetchall()

        results = []
        for r in rows:
            d = dict(r)
            cat_val = d["catId"]
            obj_val = d["objId"]
            ob_val = d["obCode"]

            # Check if file presence already resolved by DB
            rec_has_fits = bool(d.get("has_fits")) if has_file_cols else False
            rec_fits_path = d.get("fits_path") if has_file_cols else None
            rec_has_png = bool(d.get("has_png")) if has_file_cols else False
            rec_png_path = d.get("png_path") if has_file_cols else None

            if rec_has_fits and rec_has_png:
                # 100% resolved from DB, zero filesystem check!
                final_has_fits = True
                final_has_png = True
            else:
                # Fallback to filesystem lookup
                f_path, p_path = find_files(
                    cat_val,
                    obj_val,
                    ob_val,
                    combination=d.get("combination"),
                    known_fits_path=rec_fits_path if rec_has_fits else None,
                    known_png_path=rec_png_path if rec_has_png else None,
                )
                final_has_fits = rec_has_fits or (f_path is not None)
                final_has_png = rec_has_png or (p_path is not None)

            d["objId"] = str(d["objId"])
            d["has_fits"] = final_has_fits
            d["has_png"] = final_has_png
            d["ra"] = sanitize_val(d.get("ra"))
            d["dec"] = sanitize_val(d.get("dec"))
            d["bestRedshift"] = sanitize_val(d.get("bestRedshift"))
            d["bestRedshiftError"] = sanitize_val(d.get("bestRedshiftError"))
            d["bestVelocity"] = sanitize_val(d.get("bestVelocity"))
            d["bestVelocityError"] = sanitize_val(d.get("bestVelocityError"))
            d["probaGalaxy"] = sanitize_val(d.get("probaGalaxy"))
            d["probaStar"] = sanitize_val(d.get("probaStar"))
            d["probaQSO"] = sanitize_val(d.get("probaQSO"))
            d.pop("_dummy", None)
            results.append(d)

        pages = (total + limit - 1) // limit if limit > 0 else 1

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "pages": pages,
            "targets": results,
        }
    finally:
        conn.close()


@app.get("/api/targets/sky_positions")
def get_sky_positions(
    request: Request,
    q: Optional[str] = Query(None, description="Search query in obCode, objId, or catId"),
    classification: Optional[str] = Query(None, description="Filter by classification (GALAXY, QSO, STAR)"),
    min_z: Optional[float] = Query(None, description="Minimum redshift"),
    max_z: Optional[float] = Query(None, description="Maximum redshift"),
    cat_id: Optional[int] = Query(None, description="Filter by catId"),
    combination: Optional[str] = Query(None, description="Filter by combination"),
    min_ra: Optional[float] = Query(None, description="Minimum Right Ascension (deg)"),
    max_ra: Optional[float] = Query(None, description="Maximum Right Ascension (deg)"),
    min_dec: Optional[float] = Query(None, description="Minimum Declination (deg)"),
    max_dec: Optional[float] = Query(None, description="Maximum Declination (deg)"),
    has_fits: Optional[bool] = Query(None, description="Filter targets that have FITS spectra"),
    has_png: Optional[bool] = Query(None, description="Filter targets that have PNG spectra"),
    limit: int = Query(500000, description="Max coordinates to return"),
):
    """Retrieve lightweight celestial coordinates for all filtered targets (for full sky map display)."""
    # Fast-path: Unconditional master celestial coordinates query (pre-computed in-memory cache)
    is_unfiltered = (
        not q and not classification and min_z is None and max_z is None
        and cat_id is None and not combination and min_ra is None and max_ra is None
        and min_dec is None and max_dec is None and has_fits is None and has_png is None
        and (limit is None or limit >= 210000)
    )
    if is_unfiltered:
        gz_data, raw_data, etag = load_or_build_master_sky_cache(db_path=DB_PATH)
        if etag and request.headers.get("if-none-match") == etag:
            return Response(status_code=304)

        accept_encoding = request.headers.get("accept-encoding", "").lower()
        if "gzip" in accept_encoding and gz_data:
            return Response(
                content=gz_data,
                media_type="application/json",
                headers={
                    "Content-Encoding": "gzip",
                    "Cache-Control": "public, max-age=86400",
                    "ETag": etag or 'W/"sky-cache"',
                },
            )
        if raw_data:
            return Response(
                content=raw_data,
                media_type="application/json",
                headers={
                    "Cache-Control": "public, max-age=86400",
                    "ETag": etag or 'W/"sky-cache"',
                },
            )

    where_clauses = ["t.ra IS NOT NULL", "t.dec IS NOT NULL"]
    params: List[Any] = []

    if q:
        q_clean = q.strip()
        if q_clean.isdigit():
            where_clauses.append("(t.objId = ? OR t.obCode LIKE ? OR t.catId = ?)")
            params.extend([int(q_clean), f"%{q_clean}%", int(q_clean)])
        else:
            where_clauses.append("t.obCode LIKE ?")
            params.append(f"%{q_clean}%")

    if classification and classification.upper() != "ALL":
        where_clauses.append("t.classificationName = ?")
        params.append(classification.upper())

    if min_z is not None:
        where_clauses.append("t.bestRedshift >= ?")
        params.append(min_z)

    if max_z is not None:
        where_clauses.append("t.bestRedshift <= ?")
        params.append(max_z)

    if cat_id is not None:
        where_clauses.append("t.catId = ?")
        params.append(cat_id)

    if combination:
        where_clauses.append("t.combination = ?")
        params.append(combination)

    # Spatial box filter (RA / Dec)
    spatial_clauses, spatial_params = build_spatial_clauses(min_ra, max_ra, min_dec, max_dec)
    where_clauses.extend(spatial_clauses)
    params.extend(spatial_params)

    conn = get_db()
    cur = conn.cursor()
    try:
        tbl = get_summary_table(conn)
        has_file_cols = check_db_file_columns(conn)

        if has_file_cols:
            if has_fits is not None:
                where_clauses.append("t.has_fits = ?")
                params.append(1 if has_fits else 0)
            if has_png is not None:
                where_clauses.append("t.has_png = ?")
                params.append(1 if has_png else 0)

        where_sql = "WHERE " + " AND ".join(where_clauses)
        file_select = ", t.has_fits, t.has_png" if has_file_cols else ""
        sql = f"""
            SELECT 
                t.catId, t.objId, t.obCode, t.ra, t.dec,
                t.classificationName, t.bestRedshift, t.bestVelocity
                {file_select}
            FROM {tbl} t
            {where_sql}
            LIMIT ?
        """
        cur.execute(sql, params + [limit])
        rows = cur.fetchall()

        results = []
        for r in rows:
            results.append({
                "catId": r["catId"],
                "objId": str(r["objId"]),
                "obCode": r["obCode"] or "",
                "ra": sanitize_val(r["ra"]),
                "dec": sanitize_val(r["dec"]),
                "classificationName": r["classificationName"] or "UNKNOWN",
                "bestRedshift": sanitize_val(r["bestRedshift"]),
                "bestVelocity": sanitize_val(r["bestVelocity"]),
                "has_fits": bool(r["has_fits"]) if has_file_cols else True,
                "has_png": bool(r["has_png"]) if has_file_cols else True,
            })

        return {
            "total": len(results),
            "targets": results,
        }
    finally:
        conn.close()


@app.get("/api/targets/{catId}/{objId}/details")
def get_target_details(catId: int, objId: str):
    """Retrieve full solver, candidate, and line measurement details for a target."""
    conn = get_db()
    cur = conn.cursor()
    try:
        tbl = get_summary_table(conn)
        obj_id_int = int(objId)
        # Target summary info
        cur.execute(f"SELECT * FROM {tbl} WHERE catId = ? AND objId = ?", (catId, obj_id_int))
        target_row = cur.fetchone()
        if not target_row:
            raise HTTPException(status_code=404, detail="Target not found in database")
        target_info = {k: sanitize_val(v) for k, v in dict(target_row).items()}
        target_info["objId"] = str(target_info["objId"])

        # Solver results
        cur.execute("SELECT * FROM solver_results WHERE catId = ? AND objId = ?", (catId, obj_id_int))
        solver_rows = []
        for r in cur.fetchall():
            rd = {k: sanitize_val(v) for k, v in dict(r).items()}
            rd["objId"] = str(rd.get("objId", ""))
            solver_rows.append(rd)

        # Redshift candidates
        cur.execute(
            """
            SELECT * FROM redshift_candidates 
            WHERE catId = ? AND objId = ? 
            ORDER BY objectType, cRank ASC
            """,
            (catId, obj_id_int),
        )
        candidate_rows = []
        for r in cur.fetchall():
            rd = {k: sanitize_val(v) for k, v in dict(r).items()}
            rd["objId"] = str(rd.get("objId", ""))
            candidate_rows.append(rd)

        # Line measurements
        cur.execute(
            """
            SELECT * FROM line_measurements 
            WHERE catId = ? AND objId = ? 
            ORDER BY objectType, lineWave ASC
            """,
            (catId, obj_id_int),
        )
        line_rows = []
        for r in cur.fetchall():
            rd = {k: sanitize_val(v) for k, v in dict(r).items()}
            rd["objId"] = str(rd.get("objId", ""))
            line_rows.append(rd)

        fits_file, png_file = find_files(
            catId,
            obj_id_int,
            target_info.get("obCode"),
            combination=target_info.get("combination"),
            known_fits_path=target_info.get("fits_path"),
            known_png_path=target_info.get("png_path"),
        )

        return {
            "target": target_info,
            "solver_results": solver_rows,
            "redshift_candidates": candidate_rows,
            "line_measurements": line_rows,
            "files": {
                "fits": fits_file is not None,
                "png": png_file is not None,
                "fits_filename": os.path.basename(fits_file) if fits_file else None,
                "png_filename": os.path.basename(png_file) if png_file else None,
            },
        }
    finally:
        conn.close()


@app.get("/api/targets/{catId}/{objId}/spectrum")
def get_spectrum_data(catId: int, objId: str):
    """
    Parse FITS raw data (WAVELENGTH, FLUX, COVAR, MASK, OBSERVATIONS)
    and return JSON array for interactive Plotly rendering.
    """
    obj_id_int = int(objId)
    conn = get_db()
    cur = conn.cursor()
    tbl = get_summary_table(conn)
    has_file_cols = check_db_file_columns(conn)
    file_cols_sql = ", fits_path, png_path" if has_file_cols else ""
    cur.execute(f"SELECT obCode, combination {file_cols_sql} FROM {tbl} WHERE catId = ? AND objId = ?", (catId, obj_id_int))
    row = cur.fetchone()
    conn.close()

    ob_code = row["obCode"] if row else None
    comb_val = row["combination"] if (row and "combination" in row.keys()) else None
    known_fits = row["fits_path"] if (row and has_file_cols and "fits_path" in row.keys()) else None

    fits_file, _ = find_files(catId, obj_id_int, ob_code, combination=comb_val, known_fits_path=known_fits)
    if not fits_file or not os.path.exists(fits_file):
        raise HTTPException(status_code=404, detail=f"FITS file for target catId={catId}, objId={objId} not found")

    try:
        with fits.open(fits_file) as hdul:
            wave = hdul["WAVELENGTH"].data
            flux = hdul["FLUX"].data

            # Variance from covariance matrix row 0
            variance = None
            if "COVAR" in hdul:
                covar = hdul["COVAR"].data
                if covar is not None and covar.ndim >= 2:
                    variance = covar[0]

            # Mask array
            mask = None
            if "MASK" in hdul:
                mask = hdul["MASK"].data

            # Observations table
            observations = []
            if "OBSERVATIONS" in hdul and hdul["OBSERVATIONS"].data is not None:
                obs_table = hdul["OBSERVATIONS"].data
                for r in obs_table:
                    observations.append({
                        "visit": int(r["visit"]) if "visit" in r.array.names else None,
                        "arm": str(r["arm"]) if "arm" in r.array.names else "",
                        "spectrograph": int(r["spectrograph"]) if "spectrograph" in r.array.names else None,
                        "fiberId": int(r["fiberId"]) if "fiberId" in r.array.names else None,
                        "expTime": float(r["expTime"]) if "expTime" in r.array.names else None,
                        "obsTime": str(r["obsTime"]) if "obsTime" in r.array.names else "",
                    })

            # Clean float arrays for JSON compliance
            def sanitize_list(arr):
                if arr is None:
                    return None
                cleaned = []
                for x in arr:
                    if np.isnan(x) or np.isinf(x):
                        cleaned.append(None)
                    else:
                        cleaned.append(float(x))
                return cleaned

            wave_list = sanitize_list(wave)
            flux_list = sanitize_list(flux)
            var_list = sanitize_list(variance)
            mask_list = [int(m) for m in mask] if mask is not None else None

            # Calculate 1-sigma noise (sqrt of variance)
            noise_list = None
            if var_list:
                noise_list = [
                    float(np.sqrt(v)) if (v is not None and v > 0) else None
                    for v in var_list
                ]

            return {
                "catId": catId,
                "objId": str(objId),
                "wavelength": wave_list,
                "flux": flux_list,
                "variance": var_list,
                "noise": noise_list,
                "mask": mask_list,
                "observations": observations,
                "points_count": len(wave_list) if wave_list else 0,
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read FITS file: {str(e)}")


@app.get("/api/targets/{catId}/{objId}/image")
def get_spectrum_image(catId: int, objId: str):
    """Return PNG spectrum plot image."""
    obj_id_int = int(objId)
    conn = get_db()
    cur = conn.cursor()
    tbl = get_summary_table(conn)
    has_file_cols = check_db_file_columns(conn)
    file_cols_sql = ", png_path" if has_file_cols else ""
    cur.execute(f"SELECT obCode {file_cols_sql} FROM {tbl} WHERE catId = ? AND objId = ?", (catId, obj_id_int))
    row = cur.fetchone()
    conn.close()

    ob_code = row["obCode"] if row else None
    known_png = row["png_path"] if (row and has_file_cols and "png_path" in row.keys()) else None

    _, png_file = find_files(catId, obj_id_int, ob_code, known_png_path=known_png)
    if not png_file or not os.path.exists(png_file):
        raise HTTPException(status_code=404, detail="Spectrum PNG image not found")
    return FileResponse(png_file, media_type="image/png")


@app.get("/api/targets/{catId}/{objId}/fits")
def download_fits(catId: int, objId: str):
    """Download raw FITS file."""
    obj_id_int = int(objId)
    conn = get_db()
    cur = conn.cursor()
    tbl = get_summary_table(conn)
    has_file_cols = check_db_file_columns(conn)
    file_cols_sql = ", fits_path" if has_file_cols else ""
    cur.execute(f"SELECT obCode, combination {file_cols_sql} FROM {tbl} WHERE catId = ? AND objId = ?", (catId, obj_id_int))
    row = cur.fetchone()
    conn.close()

    ob_code = row["obCode"] if row else None
    comb_val = row["combination"] if (row and "combination" in row.keys()) else None
    known_fits = row["fits_path"] if (row and has_file_cols and "fits_path" in row.keys()) else None

    fits_file, _ = find_files(catId, obj_id_int, ob_code, combination=comb_val, known_fits_path=known_fits)
    if not fits_file or not os.path.exists(fits_file):
        raise HTTPException(status_code=404, detail="FITS file not found")
    filename = os.path.basename(fits_file)
    return FileResponse(fits_file, media_type="application/fits", filename=filename)


# -----------------------------------------------------------------------------
# Sky Cutout API (Subaru HSC & Pan-STARRS Fallback)
# -----------------------------------------------------------------------------
SURVEY_HIPS_MAP = {
    "hsc_wide": {
        "id": "CDS/P/HSC/DR2/wide/color-i-r-g",
        "name": "Subaru HSC DR2 (Wide)",
        "badge": "Subaru HSC",
    },
    "hsc_deep": {
        "id": "CDS/P/HSC/DR2/deep/color-i-r-g",
        "name": "Subaru HSC DR2 (Deep)",
        "badge": "Subaru HSC Deep",
    },
    "panstarrs": {
        "id": "CDS/P/PanSTARRS/DR1/color-z-zg-g",
        "name": "Pan-STARRS DR1",
        "badge": "Pan-STARRS DR1",
    },
    "dss": {
        "id": "CDS/P/DSS2/color",
        "name": "DSS2 Color",
        "badge": "DSS2 Color",
    },
}


def fetch_hips_cutout_raw(hips_id: str, ra: float, dec: float, fov: float, width: int = 300, height: int = 300, timeout: int = 8) -> Optional[bytes]:
    """Fetch raw JPEG cutout from CDS hips2fits service."""
    encoded_hips = urllib.parse.quote(hips_id, safe="")
    url = (
        f"https://alasky.cds.unistra.fr/hips-image-services/hips2fits"
        f"?hips={encoded_hips}&ra={ra}&dec={dec}&fov={fov}&width={width}&height={height}&format=jpg"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "PFSTargetViewer/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = resp.read()
                return data
    except Exception:
        return None
    return None


@app.get("/api/targets/cutout")
def get_target_cutout(
    ra: float = Query(..., description="Target Right Ascension in degrees"),
    dec: float = Query(..., description="Target Declination in degrees"),
    fov: float = Query(0.008333, description="Field of view in degrees (default ~30 arcsec)"),
    width: int = Query(300, ge=100, le=800, description="Image width in pixels"),
    height: int = Query(300, ge=100, le=800, description="Image height in pixels"),
    survey: str = Query("auto", description="Survey: auto, hsc_wide, hsc_deep, panstarrs, dss"),
):
    """
    Retrieve or cache a sky cutout image for a target coordinate.
    If survey is 'auto', automatically tries Subaru HSC DR2 wide, and if outside
    HSC coverage (or dummy blank white image returned), falls back to Pan-STARRS DR1 (or DSS2).
    """
    survey_key = survey.lower().strip()
    if survey_key != "auto" and survey_key not in SURVEY_HIPS_MAP:
        raise HTTPException(status_code=400, detail=f"Unsupported survey: {survey}")
    cache_prefix = f"cutout_{survey_key}_{ra:.5f}_{dec:+.5f}_{fov:.5f}_{width}x{height}"
    cache_img = os.path.join(CUTOUT_CACHE_DIR, f"{cache_prefix}.jpg")
    cache_meta = os.path.join(CUTOUT_CACHE_DIR, f"{cache_prefix}.json")

    # 1. Check local cache (with blank detection to prevent serving stale white frames)
    if os.path.exists(cache_img) and os.path.exists(cache_meta):
        try:
            with open(cache_img, "rb") as f_img:
                cached_bytes = f_img.read()
            if not is_blank_or_out_of_coverage(cached_bytes):
                with open(cache_meta, "r", encoding="utf-8") as f_meta:
                    meta = json.load(f_meta)
                return FileResponse(
                    cache_img,
                    media_type="image/jpeg",
                    headers={
                        "X-Survey-Used": meta.get("survey_used", survey_key),
                        "X-Survey-Name": meta.get("survey_name", "Sky Cutout"),
                        "X-Is-Fallback": str(meta.get("is_fallback", False)).lower(),
                        "Cache-Control": "public, max-age=86400",
                    },
                )
            else:
                # Stale blank cache detected: delete and re-fetch properly
                os.remove(cache_img)
                if os.path.exists(cache_meta):
                    os.remove(cache_meta)
        except Exception:
            pass

    # 2. Fetch from HiPS services
    survey_used = ""
    survey_name = ""
    is_fallback = False
    img_data = None

    if survey_key == "auto":
        # First attempt: Subaru HSC DR2 Wide
        hsc_conf = SURVEY_HIPS_MAP["hsc_wide"]
        img_data = fetch_hips_cutout_raw(hsc_conf["id"], ra, dec, fov, width, height)
        if img_data and not is_blank_or_out_of_coverage(img_data):
            survey_used = "hsc_wide"
            survey_name = hsc_conf["name"]
            is_fallback = False
        else:
            # Fallback 1: Pan-STARRS DR1
            ps_conf = SURVEY_HIPS_MAP["panstarrs"]
            img_data = fetch_hips_cutout_raw(ps_conf["id"], ra, dec, fov, width, height)
            if img_data and not is_blank_or_out_of_coverage(img_data):
                survey_used = "panstarrs"
                survey_name = ps_conf["name"]
                is_fallback = True
            else:
                # Fallback 2: DSS2
                dss_conf = SURVEY_HIPS_MAP["dss"]
                img_data = fetch_hips_cutout_raw(dss_conf["id"], ra, dec, fov, width, height)
                if img_data:
                    survey_used = "dss"
                    survey_name = dss_conf["name"]
                    is_fallback = True
    elif survey_key in SURVEY_HIPS_MAP:
        conf = SURVEY_HIPS_MAP[survey_key]
        img_data = fetch_hips_cutout_raw(conf["id"], ra, dec, fov, width, height)
        survey_used = survey_key
        survey_name = conf["name"]
        is_fallback = False
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported survey: {survey}")

    if not img_data:
        raise HTTPException(status_code=502, detail="Unable to fetch cutout image from astronomical image services.")

    # 3. Save to cache
    try:
        with open(cache_img, "wb") as f:
            f.write(img_data)
        with open(cache_meta, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "survey_used": survey_used,
                    "survey_name": survey_name,
                    "is_fallback": is_fallback,
                    "ra": ra,
                    "dec": dec,
                    "fov": fov,
                    "width": width,
                    "height": height,
                },
                f,
            )
    except Exception:
        pass

    return Response(
        content=img_data,
        media_type="image/jpeg",
        headers={
            "X-Survey-Used": survey_used,
            "X-Survey-Name": survey_name,
            "X-Is-Fallback": str(is_fallback).lower(),
            "Cache-Control": "public, max-age=86400",
        },
    )


# -----------------------------------------------------------------------------
# Custom SQL Query & Schema APIs
# -----------------------------------------------------------------------------
class SqlValidateRequest(BaseModel):
    sql: Optional[str] = None
    query: Optional[str] = None

    def get_sql(self) -> str:
        val = self.sql or self.query or ""
        return val.strip()


class SqlQueryRequest(BaseModel):
    sql: Optional[str] = None
    query: Optional[str] = None
    page: int = 1
    limit: int = 25
    sort_by: Optional[str] = None
    order: Optional[str] = "asc"
    skip_sky: Optional[bool] = False
    force_refresh: Optional[bool] = False

    def get_sql(self) -> str:
        val = self.sql or self.query or ""
        return val.strip()


class SqlQueryCache:
    """In-memory LRU cache for SQL query results to enable instant pagination and whole-dataset sorting."""
    def __init__(self, max_entries: int = 8, ttl_sec: float = 1800.0):
        self.max_entries = max_entries
        self.ttl_sec = ttl_sec
        self.cache: OrderedDict[str, dict] = OrderedDict()
        self.lock = threading.Lock()

    def _normalize_key(self, sql: str) -> str:
        # Strip comments and whitespace to form a stable cache key
        clean = re.sub(r"--[^\n]*\n?", " ", sql)
        clean = re.sub(r"/\*.*?\*/", " ", clean, flags=re.DOTALL)
        clean = " ".join(clean.strip().split())
        return hashlib.sha256(clean.encode("utf-8")).hexdigest()

    def get(self, sql: str) -> Optional[dict]:
        key = self._normalize_key(sql)
        with self.lock:
            if key not in self.cache:
                return None
            entry = self.cache[key]
            if time.time() - entry["timestamp"] > self.ttl_sec:
                del self.cache[key]
                return None
            self.cache.move_to_end(key)
            return entry

    def put(self, sql: str, data: dict):
        key = self._normalize_key(sql)
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
            self.cache[key] = {
                **data,
                "timestamp": time.time(),
            }
            while len(self.cache) > self.max_entries:
                self.cache.popitem(last=False)

    def clear(self):
        with self.lock:
            self.cache.clear()


SQL_CACHE = SqlQueryCache(max_entries=8, ttl_sec=1800.0)
MAX_SQL_CACHE_ROWS = 300_000


def sort_cached_rows(rows: List[dict], sort_by: Optional[str], order: Optional[str]) -> List[dict]:
    """Sort list of target dictionaries by a given column with NULLs placed at the end."""
    if not sort_by:
        return rows

    is_desc = (order or "asc").lower() == "desc"

    valid = []
    nulls = []
    for r in rows:
        v = r.get(sort_by)
        if v is None or v == "":
            nulls.append(r)
        else:
            valid.append(r)

    def val_key(r):
        v = r.get(sort_by)
        if isinstance(v, (int, float)):
            return (0, v)
        return (1, str(v).lower())

    valid.sort(key=val_key, reverse=is_desc)
    return valid + nulls


def strip_trailing_order_by(sql: str) -> str:
    """Strip the outermost top-level ORDER BY clause while preserving any trailing LIMIT/OFFSET.

    Uses backward scanning and parenthesis/quote depth tracking to safely avoid stripping
    ORDER BY inside subqueries or string literals.
    """
    clean = sql.strip().rstrip(";").rstrip()
    upper = clean.upper()

    # Find the last top-level ORDER BY
    search_from = len(upper)
    while True:
        pos = upper.rfind("ORDER", 0, search_from)
        if pos < 0:
            return clean

        # Check word boundary before ORDER
        if pos > 0 and (upper[pos - 1].isalnum() or upper[pos - 1] == "_"):
            search_from = pos
            continue

        # Check followed by BY
        rest = upper[pos + 5:].lstrip()
        if not rest.startswith("BY"):
            search_from = pos
            continue

        # Check word boundary after BY
        by_idx = upper.find("BY", pos + 5)
        after_by = by_idx + 2
        if after_by < len(upper) and (upper[after_by].isalnum() or upper[after_by] == "_"):
            search_from = pos
            continue

        # Check parenthesis depth and quotes up to pos
        depth = 0
        in_quote = False
        quote_char = ""
        for ch in clean[:pos]:
            if in_quote:
                if ch == quote_char:
                    in_quote = False
            elif ch in ("'", '"', '`'):
                in_quote = True
                quote_char = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)

        if depth != 0 or in_quote:
            search_from = pos
            continue

        # Top-level ORDER BY found at pos! Now scan forward to find any top-level LIMIT clause
        limit_pos = -1
        depth = 0
        in_quote = False
        quote_char = ""
        idx = after_by
        clean_len = len(clean)

        while idx < clean_len:
            ch = clean[idx]
            if in_quote:
                if ch == quote_char:
                    in_quote = False
            elif ch in ("'", '"', '`'):
                in_quote = True
                quote_char = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            elif depth == 0:
                if upper[idx : idx + 5] == "LIMIT":
                    prev_ok = (idx == 0 or not (upper[idx - 1].isalnum() or upper[idx - 1] == "_"))
                    next_ok = (idx + 5 >= clean_len or not (upper[idx + 5].isalnum() or upper[idx + 5] == "_"))
                    if prev_ok and next_ok:
                        limit_pos = idx
                        break
            idx += 1

        prefix = clean[:pos].rstrip()
        if limit_pos >= 0:
            limit_clause = clean[limit_pos:].strip()
            return f"{prefix} {limit_clause}"
        else:
            return prefix


DISALLOWED_SQL_PATTERNS = [
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|PRAGMA|VACUUM|REINDEX)\b",
    r"\b(BEGIN|COMMIT|ROLLBACK|SAVEPOINT|RELEASE)\b",
]

KNOWN_COLUMN_DESCRIPTIONS = {
    "catId": "PFS Catalog Identifier",
    "objId": "PFS Object Identifier",
    "obCode": "Observing Target Code Name",
    "ra": "Right Ascension in degrees (J2000)",
    "dec": "Declination in degrees (J2000)",
    "classificationName": "Target classification (GALAXY, STAR, QSO, UNKNOWN)",
    "probaGalaxy": "Posterior probability of being a Galaxy [0-1]",
    "probaStar": "Posterior probability of being a Star [0-1]",
    "probaQSO": "Posterior probability of being a QSO [0-1]",
    "bestRedshift": "Best-fit redshift z",
    "bestRedshiftError": "1-sigma uncertainty of best-fit redshift",
    "bestVelocity": "Best-fit radial velocity (km/s)",
    "bestVelocityError": "Uncertainty of radial velocity (km/s)",
    "bestSubClass": "Best-fit spectral template subclass",
    "hasSolution": "1 if a valid redshift solver solution was found, 0 otherwise",
    "targetTypeName": "Target type designation (SCIENCE, SKY, FLUXSTD)",
    "fiberStatusName": "Status of observing fiber (GOOD, BROKEN, UNILLUMINATED)",
    "has_fits": "1 if 1D coadded FITS spectrum file is available",
    "has_png": "1 if PNG preview spectrum thumbnail is available",
    "fits_path": "Relative path to FITS spectrum file",
    "png_path": "Relative path to PNG spectrum image",
    "combination": "Coadd combination key (e.g. brn_run28)",
    "objGroup": "Object group ID within coadd",
    "nvisit": "Number of coadded observation visits for this target",
    "exptime": "Total on-sky exposure time in seconds across coadded visits",
    "visit": "Observation Visit ID",
    "fiberId": "Spectrograph Fiber ID (1-2394)",
    "lineName": "Emission / absorption line identifier (e.g. [OII]3727, Halpha)",
    "wavelength": "Measured central line wavelength (Angstrom)",
    "flux": "Integrated line flux (erg/s/cm^2)",
    "fluxError": "1-sigma uncertainty of line flux",
    "ew": "Equivalent width (Angstrom)",
    "ewError": "Uncertainty of equivalent width",
    "snr": "Signal-to-noise ratio of detected line",
    "zWarningValue": "Bitmask of redshift solver warnings (0 = clean)",
    "zWarningName": "Human-readable solver warning string",
    "zErrorCode": "Solver error code if failed",
    "zErrorMessage": "Solver error description",
    "cRank": "Candidate solution rank (1 = best candidate)",
    "redshift": "Candidate solution redshift",
    "redshiftProba": "Candidate probability",
}

KNOWN_TABLE_DESCRIPTIONS = {
    "target_summary": "High-performance materialized summary table with coordinates, classification, redshift, and spectrum files.",
    "v_target_summary": "View of target summary combining targets, classifications, and latest fiber coordinates.",
    "targets": "Classification results, template probabilities, and best-fit redshifts per target.",
    "fiber_configs": "Per-visit fiber coordinates (ra, dec), PFI positions, and target configurations.",
    "visits": "Visit metadata, design ID, pointing boresight, and observation timestamps.",
    "solver_results": "Redshift solver warnings, errors, and candidate counts for galaxy/qso/star pipelines.",
    "redshift_candidates": "Fitted candidate redshift and velocity solutions ranked by probability.",
    "line_measurements": "Fitted emission and absorption line measurements (wavelength, flux, SNR, EW).",
    "coadd_groups": "Coadd group combinations and target counts.",
}


def strip_sql_comments(sql: str) -> str:
    """
    Remove single-line comments (-- ...) and multi-line comments (/* ... */)
    while preserving regular SQL text.
    """
    # Remove multi-line comments /* ... */
    cleaned = re.sub(r"/\*[\s\S]*?\*/", " ", sql)
    # Remove single-line comments -- ...
    lines = []
    for line in cleaned.splitlines():
        line_no_comment = re.sub(r"--.*$", "", line)
        lines.append(line_no_comment)
    return "\n".join(lines).strip()


def sanitize_and_prepare_sql(raw_sql: str) -> str:
    """Validate query safety, expand shorthand, and verify read-only statement type."""
    sql = raw_sql.strip()
    if sql.endswith(";"):
        sql = sql[:-1].strip()

    # Get SQL stripped of comments to evaluate the effective query statement
    effective_sql = strip_sql_comments(sql)
    if not effective_sql:
        raise ValueError("SQL query cannot be empty.")

    # Check for multiple statements separated by semicolon
    cleaned_no_quotes = re.sub(r"'[^']*'", "", effective_sql)
    cleaned_no_quotes = re.sub(r'"[^"]*"', "", cleaned_no_quotes)
    if ";" in cleaned_no_quotes:
        raise ValueError("Multiple SQL statements separated by ';' are not permitted.")

    # Check for disallowed keywords in comment-free and quote-free SQL
    for pattern in DISALLOWED_SQL_PATTERNS:
        m = re.search(pattern, cleaned_no_quotes, re.IGNORECASE)
        if m:
            raise ValueError(
                f"Disallowed SQL keyword or operation detected: '{m.group(0).upper()}'. "
                f"Only read-only queries (SELECT / WITH) are allowed."
            )

    # Shorthand support: "WHERE ..." expands to "SELECT * FROM target_summary WHERE ..."
    if re.match(r"^WHERE\b", effective_sql, re.IGNORECASE):
        sql = f"SELECT * FROM target_summary {sql}"
        effective_sql = f"SELECT * FROM target_summary {effective_sql}"

    # Must start with SELECT or WITH (ignoring any comments before it)
    if not re.match(r"^(SELECT|WITH)\b", effective_sql, re.IGNORECASE):
        raise ValueError("Query must begin with 'SELECT' or 'WITH'.")

    return sql


def optimize_cone_search(sql: str) -> str:
    """
    Detect CONE_SEARCH(ra, dec, c_ra, c_dec, radius_arcsec) in queries
    and automatically inject a bounding-box range check to utilize the (ra, dec) index.
    """
    pattern = re.compile(
        r"CONE_SEARCH\s*\(\s*([a-zA-Z0-9_\.]+)\s*,\s*([a-zA-Z0-9_\.]+)\s*,\s*([0-9\.\-\+]+)\s*,\s*([0-9\.\-\+]+)\s*,\s*([0-9\.\-\+]+)\s*\)",
        re.IGNORECASE,
    )

    def _replacer(m):
        ra_col = m.group(1)
        dec_col = m.group(2)
        try:
            c_ra = float(m.group(3))
            c_dec = float(m.group(4))
            r_arcsec = float(m.group(5))
        except ValueError:
            return m.group(0)

        r_deg = r_arcsec / 3600.0
        d_dec = r_deg
        cos_dec = max(0.01, math.cos(c_dec * math.pi / 180.0))
        d_ra = r_deg / cos_dec

        min_dec = max(-90.0, c_dec - d_dec)
        max_dec = min(90.0, c_dec + d_dec)
        min_ra = c_ra - d_ra
        max_ra = c_ra + d_ra

        if min_ra < 0:
            ra_box = f"({ra_col} >= {min_ra + 360.0:.6f} OR {ra_col} <= {max_ra:.6f})"
        elif max_ra > 360:
            ra_box = f"({ra_col} >= {min_ra:.6f} OR {ra_col} <= {max_ra - 360.0:.6f})"
        else:
            ra_box = f"({ra_col} BETWEEN {min_ra:.6f} AND {max_ra:.6f})"

        dec_box = f"({dec_col} BETWEEN {min_dec:.6f} AND {max_dec:.6f})"

        return f"({ra_box} AND {dec_box} AND {m.group(0)})"

    return pattern.sub(_replacer, sql)


def wrap_query_with_target_summary(conn: sqlite3.Connection, sql: str) -> Tuple[str, List[str], bool]:
    """
    Wrap user query to ensure catId, objId, obCode, ra, dec, classificationName, bestRedshift, etc.
    are always available for plotting and spectrum viewer.
    Returns (executable_sql, user_custom_columns, has_identity).
    """
    tbl = get_summary_table(conn)
    has_file_cols = check_db_file_columns(conn)

    # Probe query structure with LIMIT 0
    test_cur = conn.cursor()
    test_sql = f"SELECT * FROM (\n{sql}\n) AS _probe LIMIT 0"
    test_cur.execute(test_sql)
    out_cols = [desc[0] for desc in test_cur.description] if test_cur.description else []

    has_cat = "catId" in out_cols
    has_obj = "objId" in out_cols

    if not (has_cat and has_obj):
        return sql, out_cols, False

    # Check if core columns are already present in query output
    core_cols = {"ra", "dec", "classificationName", "bestRedshift", "bestVelocity"}
    missing_core = core_cols - set(out_cols)

    # If all core columns are already projected, NO wrapping or joining is needed!
    if not missing_core:
        return sql, out_cols, True

    # User query has catId/objId but is missing some core columns (e.g. from line_measurements)
    # Project user_query.* first, then ONLY add missing core columns with no duplicate names!
    extra_selects = []
    if "ra" not in out_cols:
        extra_selects.append("_ts.ra AS ra")
    if "dec" not in out_cols:
        extra_selects.append("_ts.dec AS dec")
    if "obCode" not in out_cols:
        extra_selects.append("COALESCE(_ts.obCode, '') AS obCode")
    if "classificationName" not in out_cols:
        extra_selects.append("COALESCE(_ts.classificationName, 'UNKNOWN') AS classificationName")
    if "bestRedshift" not in out_cols:
        extra_selects.append("_ts.bestRedshift AS bestRedshift")
    if "bestVelocity" not in out_cols:
        extra_selects.append("_ts.bestVelocity AS bestVelocity")
    if has_file_cols:
        if "has_fits" not in out_cols:
            extra_selects.append("_ts.has_fits AS has_fits")
        if "has_png" not in out_cols:
            extra_selects.append("_ts.has_png AS has_png")

    extra_str = (", " + ", ".join(extra_selects)) if extra_selects else ""

    wrapped_sql = f"""
        WITH _user_query AS (
            {sql}
        )
        SELECT 
            _user_query.*
            {extra_str}
        FROM _user_query
        LEFT JOIN {tbl} _ts 
          ON _ts.catId = _user_query.catId AND _ts.objId = _user_query.objId
    """
    return wrapped_sql, out_cols, True


@app.get("/api/sql/schema")
def get_database_schema():
    """Retrieve database schema metadata including tables, columns, types, and descriptions."""
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') ORDER BY type, name")
        tables_meta = []
        for row in cur.fetchall():
            tbl_name = row["name"]
            tbl_type = row["type"]
            if tbl_name.startswith("sqlite_"):
                continue

            cur.execute(f"PRAGMA table_info({tbl_name})")
            columns = []
            for col_row in cur.fetchall():
                c_name = col_row["name"]
                c_type = col_row["type"] or "TEXT"
                is_pk = bool(col_row["pk"])
                desc = KNOWN_COLUMN_DESCRIPTIONS.get(c_name, "")
                columns.append({
                    "name": c_name,
                    "type": c_type,
                    "pk": is_pk,
                    "primary_key": is_pk,
                    "description": desc,
                })

            tables_meta.append({
                "name": tbl_name,
                "type": tbl_type,
                "description": KNOWN_TABLE_DESCRIPTIONS.get(tbl_name, ""),
                "columns": columns,
            })

        return {"tables": tables_meta}
    finally:
        conn.close()


@app.post("/api/sql/validate")
def validate_sql(req: SqlValidateRequest):
    """Validate SQL syntax and safety without executing the full query."""
    raw_query = req.get_sql()
    if not raw_query:
        return {"valid": False, "error": "Query is empty."}
    try:
        prepared_sql = sanitize_and_prepare_sql(raw_query)
        optimized_sql = optimize_cone_search(prepared_sql)
    except ValueError as e:
        return {"valid": False, "error": str(e)}

    conn = get_db()
    set_query_timeout(conn, timeout_sec=3.0)
    cur = conn.cursor()
    try:
        cur.execute(f"EXPLAIN QUERY PLAN {optimized_sql}")
        plan_rows = [dict(r) for r in cur.fetchall()]
        return {
            "valid": True,
            "message": "SQL syntax is valid.",
            "query_plan": plan_rows,
            "optimized_sql": optimized_sql,
        }
    except Exception as e:
        return {
            "valid": False,
            "error": str(e),
        }
    finally:
        conn.close()


@app.post("/api/sql/query")
def execute_sql_query(req: SqlQueryRequest):
    """Execute a custom SQL query with memory caching, full-dataset sorting, and pagination."""
    t_start = time.time()
    raw_query = req.get_sql()
    if not raw_query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
    try:
        prepared_sql = sanitize_and_prepare_sql(raw_query)
        optimized_sql = optimize_cone_search(prepared_sql)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    limit = max(1, min(100, req.limit))
    page = max(1, req.page)
    offset = (page - 1) * limit

    # Check cache first if not explicitly forced to refresh
    cache_key_source = strip_trailing_order_by(optimized_sql)
    if not req.force_refresh:
        cached = SQL_CACHE.get(cache_key_source)
        if cached:
            all_rows = cached["all_rows"]
            total = cached["total"]
            pages = max(1, math.ceil(total / limit)) if total > 0 else 1

            # Sort full dataset in memory
            sorted_rows = sort_cached_rows(all_rows, req.sort_by, req.order)
            page_rows = sorted_rows[offset : offset + limit]

            # Send sky targets only if requested (skip on page flip / sort to save bandwidth)
            sky_targets = None if req.skip_sky else cached.get("sky_targets", [])
            duration_ms = round((time.time() - t_start) * 1000.0, 1)

            return {
                "total": total,
                "page": page,
                "limit": limit,
                "pages": pages,
                "duration_ms": duration_ms,
                "execution_time_ms": duration_ms,
                "has_identity": cached["has_identity"],
                "user_columns": cached["user_columns"],
                "columns": cached["columns"],
                "targets": page_rows,
                "sky_targets": sky_targets,
                "cached": True,
            }

    # Cache miss: execute query on database
    conn = get_db()
    set_query_timeout(conn, timeout_sec=15.0)
    cur = conn.cursor()
    try:
        # Wrap query with target_summary for identity auto-projection if applicable
        try:
            executable_sql, user_cols, has_identity = wrap_query_with_target_summary(conn, optimized_sql)
        except Exception as wrap_err:
            executable_sql = optimized_sql
            user_cols = []
            has_identity = False

        # Execute base query with ORDER BY stripped (preserving LIMIT/OFFSET) to cache result set
        unordered_sql = strip_trailing_order_by(executable_sql)
        try:
            cur.execute(unordered_sql)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Query Execution Error: {e}")

        raw_rows = cur.fetchall()
        total = len(raw_rows)

        # Enforce memory safety cap on cached SQL results (300,000 rows accommodates full survey while protecting against runaway queries)
        MAX_SQL_CACHE_ROWS = 300_000
        if total > MAX_SQL_CACHE_ROWS:
            raise HTTPException(
                status_code=400,
                detail=f"Query returned {total:,} rows, exceeding the in-memory cache safety limit of {MAX_SQL_CACHE_ROWS:,} rows. "
                       f"Please add a WHERE clause or LIMIT to restrict your query results."
            )

        pages = max(1, math.ceil(total / limit)) if total > 0 else 1

        # Format and sanitize all rows
        all_clean_rows = []
        sky_targets = []
        for r in raw_rows:
            d = dict(r)
            clean_item = {}
            for k, v in d.items():
                clean_item[k] = sanitize_val(v)
            if "catId" in clean_item and clean_item["catId"] is not None:
                clean_item["catId"] = int(clean_item["catId"])
            if "objId" in clean_item and clean_item["objId"] is not None:
                clean_item["objId"] = str(clean_item["objId"])
            all_clean_rows.append(clean_item)

            if has_identity and not req.skip_sky:
                ra_val = clean_item.get("ra")
                dec_val = clean_item.get("dec")
                if ra_val is not None and dec_val is not None:
                    sky_targets.append({
                        "catId": clean_item.get("catId"),
                        "objId": clean_item.get("objId"),
                        "obCode": clean_item.get("obCode", ""),
                        "ra": ra_val,
                        "dec": dec_val,
                        "classificationName": clean_item.get("classificationName", "UNKNOWN"),
                        "bestRedshift": clean_item.get("bestRedshift"),
                        "bestVelocity": clean_item.get("bestVelocity"),
                    })

        # Store in LRU cache
        SQL_CACHE.put(cache_key_source, {
            "total": total,
            "has_identity": has_identity,
            "user_columns": user_cols,
            "columns": user_cols,
            "all_rows": all_clean_rows,
            "sky_targets": sky_targets,
        })

        # Sort full dataset by requested column if specified
        sorted_rows = sort_cached_rows(all_clean_rows, req.sort_by, req.order)
        page_rows = sorted_rows[offset : offset + limit]

        duration_ms = round((time.time() - t_start) * 1000.0, 1)

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "pages": pages,
            "duration_ms": duration_ms,
            "execution_time_ms": duration_ms,
            "has_identity": has_identity,
            "user_columns": user_cols,
            "columns": user_cols,
            "targets": page_rows,
            "sky_targets": None if req.skip_sky else sky_targets,
            "cached": False,
        }
    finally:
        conn.close()


# -----------------------------------------------------------------------------
# Main entry point
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(
        description="PFS Target & Spectrum Viewer Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 1. Specify directory containing pfs_metadata.sqlite3 and extracted_targets/ (Positional):
  python app.py /path/to/dataset
  ./run_viewer.sh /path/to/dataset

  # 2. Specify directory via flag (-d / --dir / --dataset-dir):
  python app.py -d /path/to/dataset
  ./run_viewer.sh --dir /path/to/dataset

  # 3. Specify custom host or port:
  python app.py /path/to/dataset --port 8080 --host 0.0.0.0

  # 4. Explicitly specify database and extracted_targets directory separately:
  python app.py --db /path/to/pfs_metadata.sqlite3 --data-dir /path/to/extracted_targets
"""
    )
    parser.add_argument("target_dir", nargs="?", default=None,
                        help="Directory containing pfs_metadata.sqlite3 and extracted_targets/ (optional)")
    parser.add_argument("-d", "--dir", "--dataset-dir", dest="opt_dir", default=None,
                        help="Directory containing pfs_metadata.sqlite3 and extracted_targets/")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8090, help="Port to listen on (default: 8090)")
    parser.add_argument("--db", default=None, help="Explicit path to pfs_metadata.sqlite3")
    parser.add_argument("--data-dir", default=None, help="Explicit path to extracted_targets directory")
    args = parser.parse_args()

    chosen_dir = args.opt_dir or args.target_dir
    configure_paths(target_dir=chosen_dir, db_path=args.db, data_dir=args.data_dir)

    # Status check for logging
    if os.path.exists(DB_PATH):
        db_size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
        db_size_str = f"{db_size_mb / 1024:.2f} GB" if db_size_mb >= 1024 else f"{db_size_mb:.1f} MB"
        db_status = f"✅ Found ({db_size_str})"
    else:
        db_status = "⚠️  NOT FOUND"

    if os.path.exists(DATA_DIR):
        fits_count = len(glob.glob(os.path.join(FITS_DIR, "*.fits"))) if os.path.exists(FITS_DIR) else 0
        png_count = len(glob.glob(os.path.join(PNG_DIR, "*.png"))) if os.path.exists(PNG_DIR) else 0
        data_status = f"✅ Found ({fits_count:,} FITS, {png_count:,} PNG)"
    else:
        data_status = "⚠️  NOT FOUND"

    print("=" * 70)
    print("  🌌 Starting PFS Target & Spectrum Viewer")
    if chosen_dir:
        print(f"  📍 Specified Dir: {os.path.abspath(chosen_dir)}")
    print(f"  📂 Database:      {DB_PATH} [{db_status}]")
    print(f"  📁 Data Dir:      {DATA_DIR} [{data_status}]")
    print(f"  🌐 URL:           http://{args.host}:{args.port}")
    if not os.path.exists(DB_PATH) or not os.path.exists(DATA_DIR):
        print("-" * 70)
        print("  ⚠️  Notice: One or more data targets were not found.")
        print("     Please ensure the directory contains 'pfs_metadata.sqlite3'")
        print("     and 'extracted_targets/' (or run download_data.sh).")
    print("=" * 70)

    uvicorn.run(app, host=args.host, port=args.port)
