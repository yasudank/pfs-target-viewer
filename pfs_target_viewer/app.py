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
import os
import sqlite3
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Set
import numpy as np
try:
    from PIL import Image, ImageStat
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from astropy.io import fits
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
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
    global DB_PATH, DATA_DIR, FITS_DIR, PNG_DIR, CUTOUT_CACHE_DIR, _FILES_INDEXED
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
    index_extracted_files()
    cleanup_blank_cutout_cache()


# Initialize defaults
configure_paths()

app = FastAPI(
    title="PFS Target & Spectrum Viewer",
    description="Interactive Web Dashboard for PFS Targets & Coadded Spectra",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static & Template files
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


def get_db():
    """Connect to SQLite database in read-only mode."""
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=500, detail=f"Database file not found at {DB_PATH}")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
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
    known_fits_path: Optional[str] = None,
    known_png_path: Optional[str] = None,
):
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

    # Candidate basenames
    candidates_base = []
    if ob_code:
        candidates_base.append(clean_str_name(f"{ob_code}_{cat_id}_{obj_id}"))
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


@app.get("/api/targets")
def get_targets(
    q: Optional[str] = Query(None, description="Search query in obCode, objId, or catId"),
    classification: Optional[str] = Query(None, description="Filter by classification (GALAXY, QSO, STAR)"),
    min_z: Optional[float] = Query(None, description="Minimum redshift"),
    max_z: Optional[float] = Query(None, description="Maximum redshift"),
    cat_id: Optional[int] = Query(None, description="Filter by catId"),
    combination: Optional[str] = Query(None, description="Filter by combination"),
    has_fits: Optional[bool] = Query(None, description="Filter targets that have FITS files"),
    has_png: Optional[bool] = Query(None, description="Filter targets that have PNG spectra"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    limit: int = Query(25, ge=5, le=100, description="Items per page"),
    sort_by: str = Query("objId", description="Sort field"),
    order: str = Query("asc", description="Sort order (asc, desc)"),
):
    """Search and paginate targets from target_summary / v_target_summary."""
    allowed_sort_fields = {
        "objId": "t.objId",
        "catId": "t.catId",
        "obCode": "t.obCode",
        "classification": "t.classificationName",
        "redshift": "t.bestRedshift",
        "velocity": "t.bestVelocity",
        "probaGalaxy": "t.probaGalaxy",
        "probaQSO": "t.probaQSO",
        "probaStar": "t.probaStar",
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
    q: Optional[str] = Query(None, description="Search query in obCode, objId, or catId"),
    classification: Optional[str] = Query(None, description="Filter by classification (GALAXY, QSO, STAR)"),
    min_z: Optional[float] = Query(None, description="Minimum redshift"),
    max_z: Optional[float] = Query(None, description="Maximum redshift"),
    cat_id: Optional[int] = Query(None, description="Filter by catId"),
    combination: Optional[str] = Query(None, description="Filter by combination"),
    limit: int = Query(25000, description="Max coordinates to return"),
):
    """Retrieve lightweight celestial coordinates for all filtered targets (for full sky map display)."""
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

    where_sql = "WHERE " + " AND ".join(where_clauses)

    conn = get_db()
    cur = conn.cursor()
    try:
        tbl = get_summary_table(conn)
        sql = f"""
            SELECT 
                t.catId, t.objId, t.obCode, t.ra, t.dec,
                t.classificationName, t.bestRedshift, t.bestVelocity
            FROM {tbl} t
            {where_sql}
            ORDER BY t.objId ASC
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
    cur.execute(f"SELECT obCode {file_cols_sql} FROM {tbl} WHERE catId = ? AND objId = ?", (catId, obj_id_int))
    row = cur.fetchone()
    conn.close()

    ob_code = row["obCode"] if row else None
    known_fits = row["fits_path"] if (row and has_file_cols and "fits_path" in row.keys()) else None

    fits_file, _ = find_files(catId, obj_id_int, ob_code, known_fits_path=known_fits)
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
    cur.execute(f"SELECT obCode {file_cols_sql} FROM {tbl} WHERE catId = ? AND objId = ?", (catId, obj_id_int))
    row = cur.fetchone()
    conn.close()

    ob_code = row["obCode"] if row else None
    known_fits = row["fits_path"] if (row and has_file_cols and "fits_path" in row.keys()) else None

    fits_file, _ = find_files(catId, obj_id_int, ob_code, known_fits_path=known_fits)
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
