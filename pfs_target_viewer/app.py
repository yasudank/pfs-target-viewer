#!/usr/bin/env python3
"""
PFS Target & Spectrum Viewer - Backend Application
Provides REST API and static web dashboard for inspecting PFS target metadata,
PNG spectra, and interactive FITS spectra from pfs_metadata.sqlite3 and extracted_targets.
"""
import base64
import contextvars
import glob
import hashlib
import hmac
import io
import json
import gzip
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import math
import re
import secrets
import threading
import tomllib
import urllib.request
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Set, Tuple, Union
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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from fastapi.templating import Jinja2Templates

# Base directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BASE_DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))

def resolve_paths(
    target_dir: Optional[str] = None,
    db_path: Optional[str] = None,
    data_dir: Optional[str] = None,
    use_env: bool = True,
) -> tuple[str, str]:
    """Resolve database path and data directory from user inputs, environment variables, or defaults."""
    env = os.getenv if use_env else (lambda _key: None)
    # 1. Determine base dataset directory
    raw_dir = (
        target_dir
        or env("PFS_DATA_ROOT")
        or env("PFS_DIR")
        or env("PFS_DATASET_DIR")
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
    final_db = db_path or env("PFS_DB_PATH") or candidate_db
    final_data = data_dir or env("PFS_DATA_DIR") or candidate_data_dir

    return os.path.abspath(os.path.expanduser(final_db)), os.path.abspath(os.path.expanduser(final_data))


def _scan_dir_count(base_dir: str, ext: str) -> int:
    """Count files with ``ext`` in a flat or (up to 2-level) sharded directory."""
    if not os.path.exists(base_dir):
        return 0
    total = 0
    try:
        with os.scandir(base_dir) as it:
            for entry in it:
                if entry.is_file() and entry.name.endswith(ext):
                    total += 1
                elif entry.is_dir():
                    try:
                        with os.scandir(entry.path) as sub_it:
                            for sub_entry in sub_it:
                                if sub_entry.is_file() and sub_entry.name.endswith(ext):
                                    total += 1
                                elif sub_entry.is_dir():
                                    try:
                                        with os.scandir(sub_entry.path) as slot_it:
                                            for f in slot_it:
                                                if f.is_file() and f.name.endswith(ext):
                                                    total += 1
                                    except OSError:
                                        pass
                    except OSError:
                        pass
    except OSError:
        pass
    return total


class Dataset:
    """One viewable dataset: database + extracted_targets directory, with its own caches."""

    def __init__(self, ds_id: str, name: str, db_path: str, data_dir: str,
                 password: Optional[str] = None, description: str = ""):
        self.id = ds_id
        self.name = name
        self.description = description
        self.password = password or None
        self.db_path = db_path
        self.data_dir = data_dir
        self.fits_dir = os.path.join(data_dir, "fits")
        self.png_dir = os.path.join(data_dir, "png")
        self.cutout_cache_dir = os.path.join(data_dir, "cutout_cache")

        # In-memory file index caches for O(1) lookups of flat directories without disk/NFS I/O
        self.fits_file_set: Set[str] = set()
        self.png_file_set: Set[str] = set()
        self.files_indexed = False

        self.stats_cache: Optional[Dict[str, Any]] = None

        # Full-sky coordinates cache
        self.sky_lock = threading.Lock()
        self.sky_gzip_bytes: Optional[bytes] = None
        self.sky_json_bytes: Optional[bytes] = None
        self.sky_etag: Optional[str] = None

        # Spectral lines catalog cache
        self.lines_lock = threading.Lock()
        self.lines_cache: Optional[dict] = None
        self.lines_db_mtime: float = 0.0

        self._ready = False
        self._ready_lock = threading.Lock()

    def same_source(self, other: "Dataset") -> bool:
        return self.db_path == other.db_path and self.data_dir == other.data_dir

    def ensure_ready(self):
        """Index files, prepare cutout cache and pre-warm caches on first use."""
        if self._ready:
            return
        with self._ready_lock:
            if self._ready:
                return
            if os.path.exists(self.data_dir):
                try:
                    os.makedirs(self.cutout_cache_dir, exist_ok=True)
                except OSError:
                    pass
            index_extracted_files(self)
            cleanup_blank_cutout_cache(self)
            if os.path.exists(self.db_path):
                threading.Thread(target=load_or_build_master_sky_cache, args=(self,), daemon=True).start()
                threading.Thread(target=load_or_build_spectral_lines_cache, args=(self,), daemon=True).start()
            self._ready = True

    def count_extracted_files(self) -> Tuple[int, int]:
        """Count available FITS and PNG files (from the DB index if available, otherwise by scanning)."""
        if os.path.exists(self.db_path):
            try:
                conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
                cur = conn.cursor()
                cur.execute("PRAGMA table_info(target_summary)")
                cols = {row[1] for row in cur.fetchall()}
                if "fits_path" in cols and "png_path" in cols:
                    cur.execute("SELECT COUNT(fits_path), COUNT(png_path) FROM target_summary "
                                "WHERE fits_path IS NOT NULL OR png_path IS NOT NULL")
                    row = cur.fetchone()
                    conn.close()
                    if row and (row[0] > 0 or row[1] > 0):
                        return int(row[0]), int(row[1])
                conn.close()
            except Exception:
                pass
        return _scan_dir_count(self.fits_dir, ".fits"), _scan_dir_count(self.png_dir, ".png")


def index_extracted_files(ds: Dataset, force: bool = False):
    """Index FITS and PNG filenames if flat directory, or detect sharded structure."""
    if ds.files_indexed and not force:
        return

    t0 = time.time()
    fits_count = 0
    png_count = 0
    is_sharded = False

    if os.path.exists(ds.fits_dir):
        try:
            entries = os.listdir(ds.fits_dir)
            fits_files = [f for f in entries if f.endswith(".fits")]
            if fits_files:
                ds.fits_file_set = set(fits_files)
                fits_count = len(ds.fits_file_set)
            elif any(os.path.isdir(os.path.join(ds.fits_dir, e)) for e in entries):
                is_sharded = True
        except Exception as e:
            print(f"Warning: Failed reading FITS dir {ds.fits_dir}: {e}")

    if os.path.exists(ds.png_dir):
        try:
            entries = os.listdir(ds.png_dir)
            png_files = [p for p in entries if p.endswith(".png")]
            if png_files:
                ds.png_file_set = set(png_files)
                png_count = len(ds.png_file_set)
            elif any(os.path.isdir(os.path.join(ds.png_dir, e)) for e in entries):
                is_sharded = True
        except Exception as e:
            print(f"Warning: Failed reading PNG dir {ds.png_dir}: {e}")

    ds.files_indexed = True
    if is_sharded:
        pass
    elif fits_count > 0 or png_count > 0:
        print(f"  ⚡ [{ds.id}] In-memory flat file index built in {time.time()-t0:.3f}s: {fits_count:,} FITS, {png_count:,} PNG files.")


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


def cleanup_blank_cutout_cache(ds: Dataset):
    """Scan the dataset's cutout_cache directory and purge previously cached blank/dummy frames."""
    if not os.path.exists(ds.cutout_cache_dir):
        return
    removed = 0
    for img_path in glob.glob(os.path.join(ds.cutout_cache_dir, "*.jpg")):
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
        print(f"  🧹 [{ds.id}] Cleaned up {removed} blank/dummy cutout image(s) from cache.")


# -----------------------------------------------------------------------------
# Dataset Registry (datasets.toml) & Per-Browser Dataset Sessions
# -----------------------------------------------------------------------------
DEFAULT_CONFIG_PATH = os.path.join(BASE_DIR, "datasets.toml")
SESSION_COOKIE = "pfs_viewer_session"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", text.strip()).strip("-")
    return slug or "dataset"


class DatasetRegistry:
    """Datasets from the config file (reloaded when it changes) plus an optional command-line dataset."""

    def __init__(self):
        self.lock = threading.Lock()
        self.datasets: "OrderedDict[str, Dataset]" = OrderedDict()
        self.config_path: Optional[str] = None
        self.config_mtime: Optional[float] = None
        self.cli_dataset: Optional[Dataset] = None
        self.secret_key: bytes = secrets.token_bytes(32)
        self.session_max_age = 7 * 24 * 3600

    def configure(self, config_path: Optional[str], cli_dataset: Optional[Dataset]):
        with self.lock:
            self.config_path = os.path.abspath(config_path) if config_path else None
            self.config_mtime = None
            self.cli_dataset = cli_dataset
            self._load_locked()

    def _read_config(self) -> Tuple[List[Dataset], dict]:
        with open(self.config_path, "rb") as f:
            conf = tomllib.load(f)
        entries = conf.get("datasets") or conf.get("dataset") or []
        result: List[Dataset] = []
        seen: Set[str] = set()
        for i, e in enumerate(entries, 1):
            name = str(e.get("name") or e.get("id") or f"Dataset {i}")
            ds_id = _slugify(str(e.get("id") or name))
            if ds_id in seen:
                print(f"  ⚠️ datasets config: duplicate id '{ds_id}' ignored ({name})")
                continue
            if not (e.get("dir") or e.get("db")):
                print(f"  ⚠️ datasets config: '{ds_id}' has neither 'dir' nor 'db'; ignored")
                continue
            db_path, data_dir = resolve_paths(target_dir=e.get("dir"), db_path=e.get("db"),
                                              data_dir=e.get("data_dir"), use_env=False)
            password = e.get("password")
            result.append(Dataset(ds_id, name, db_path, data_dir,
                                  password=str(password) if password else None,
                                  description=str(e.get("description") or "")))
            seen.add(ds_id)
        return result, conf

    def _load_locked(self):
        new_list: List[Dataset] = []
        if self.cli_dataset is not None:
            new_list.append(self.cli_dataset)
        if self.config_path and os.path.exists(self.config_path):
            try:
                mtime = os.path.getmtime(self.config_path)
                conf_list, conf = self._read_config()
                self.config_mtime = mtime
                if conf.get("secret_key"):
                    self.secret_key = hashlib.sha256(str(conf["secret_key"]).encode("utf-8")).digest()
                if conf.get("session_days"):
                    self.session_max_age = int(float(conf["session_days"]) * 24 * 3600)
                cli_id = self.cli_dataset.id if self.cli_dataset else None
                new_list.extend(d for d in conf_list if d.id != cli_id)
            except Exception as e:
                print(f"  ⚠️ Failed to load datasets config {self.config_path}: {e}")
                if self.datasets:
                    return  # keep the previous datasets on a broken config
        elif self.config_path:
            print(f"  ⚠️ Datasets config not found: {self.config_path}")

        # Keep existing Dataset objects (and their caches) when the source paths are unchanged
        merged: "OrderedDict[str, Dataset]" = OrderedDict()
        for d in new_list:
            old = self.datasets.get(d.id)
            if old is not None and old.same_source(d):
                old.name, old.description, old.password = d.name, d.description, d.password
                d = old
            merged[d.id] = d
        self.datasets = merged

    def reload_if_changed(self):
        if not self.config_path:
            return
        try:
            mtime = os.path.getmtime(self.config_path)
        except OSError:
            return
        if mtime != self.config_mtime:
            with self.lock:
                if mtime != self.config_mtime:
                    print(f"  🔄 Reloading datasets config: {self.config_path}")
                    self._load_locked()

    def get(self, ds_id: Optional[str]) -> Optional[Dataset]:
        return self.datasets.get(ds_id) if ds_id else None

    def all(self) -> List[Dataset]:
        return list(self.datasets.values())

    def default_open_dataset(self) -> Optional[Dataset]:
        """The only dataset, if there is exactly one and it has no password (no selection needed)."""
        if len(self.datasets) == 1:
            d = next(iter(self.datasets.values()))
            if not d.password:
                return d
        return None

    # --- Signed session cookie: {"ds": current dataset id, "auth": {id: password fingerprint}} ---
    def _sign(self, data: bytes) -> str:
        return hmac.new(self.secret_key, data, hashlib.sha256).hexdigest()

    def encode_session(self, session: dict) -> str:
        data = base64.urlsafe_b64encode(json.dumps(session, separators=(",", ":")).encode("utf-8"))
        return f"{data.decode('ascii')}.{self._sign(data)}"

    def decode_session(self, value: Optional[str]) -> dict:
        if not value or "." not in value:
            return {}
        data, sig = value.rsplit(".", 1)
        if not hmac.compare_digest(sig, self._sign(data.encode("ascii"))):
            return {}
        try:
            session = json.loads(base64.urlsafe_b64decode(data.encode("ascii")))
            return session if isinstance(session, dict) else {}
        except Exception:
            return {}

    def password_fingerprint(self, ds: Dataset) -> str:
        # Changing a dataset's password in the config invalidates existing sessions for it
        return self._sign(f"{ds.id}\0{ds.password or ''}".encode("utf-8"))[:24]

    def is_authorized(self, ds: Dataset, session: dict) -> bool:
        if not ds.password:
            return True
        auth = session.get("auth") or {}
        fp = auth.get(ds.id) if isinstance(auth, dict) else None
        return isinstance(fp, str) and hmac.compare_digest(fp, self.password_fingerprint(ds))


REGISTRY = DatasetRegistry()
_CURRENT_DATASET: contextvars.ContextVar[Optional[Dataset]] = contextvars.ContextVar("pfs_current_dataset", default=None)


def cur_ds() -> Dataset:
    """Dataset selected for the current request (set by dataset_middleware)."""
    ds = _CURRENT_DATASET.get()
    if ds is None:
        raise HTTPException(status_code=401, detail="No dataset selected")
    return ds


def init_registry_from_env():
    """Configure datasets from environment variables (also used by uvicorn --reload workers).

    PFS_VIEWER_CONFIG: datasets config file (default: datasets.toml next to app.py if present)
    PFS_DATA_ROOT / PFS_DB_PATH / PFS_DATA_DIR: an additional command-line dataset
    """
    config_path = os.getenv("PFS_VIEWER_CONFIG") or (DEFAULT_CONFIG_PATH if os.path.exists(DEFAULT_CONFIG_PATH) else None)
    has_cli = any(os.getenv(k) for k in ("PFS_DATA_ROOT", "PFS_DIR", "PFS_DATASET_DIR", "PFS_DB_PATH", "PFS_DATA_DIR"))
    cli_dataset = None
    if has_cli or not config_path:
        db_path, data_dir = resolve_paths()
        base = os.path.dirname(db_path) if os.path.basename(data_dir) == "extracted_targets" else data_dir
        name = os.getenv("PFS_DATASET_NAME") or os.path.basename(os.path.normpath(base)) or "default"
        cli_dataset = Dataset("default", name, db_path, data_dir)
    REGISTRY.configure(config_path, cli_dataset)


init_registry_from_env()


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
    db_path = cur_ds().db_path
    if not os.path.exists(db_path):
        raise HTTPException(status_code=500, detail=f"Database file not found at {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    register_sql_functions(conn)
    return conn


_DB_HAS_FILE_COLS: Dict[str, bool] = {}


def check_db_file_columns(conn: sqlite3.Connection) -> bool:
    """Check if target_summary has has_fits, fits_path, has_png, png_path columns (cached per database file)."""
    try:
        db_file = conn.execute("PRAGMA database_list").fetchone()[2] or ""
    except Exception:
        db_file = ""
    if db_file in _DB_HAS_FILE_COLS:
        return _DB_HAS_FILE_COLS[db_file]
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(target_summary)")
        cols = {row[1] for row in cur.fetchall()}
        result = "has_fits" in cols and "fits_path" in cols
    except Exception:
        result = False
    _DB_HAS_FILE_COLS[db_file] = result
    return result


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
    ds = cur_ds()
    fits_path = None
    png_path = None

    # 1. Use known DB paths if provided and existing
    if known_fits_path:
        p = os.path.join(ds.data_dir, known_fits_path) if not os.path.isabs(known_fits_path) else known_fits_path
        if os.path.exists(p):
            fits_path = p
    if known_png_path:
        p = os.path.join(ds.data_dir, known_png_path) if not os.path.isabs(known_png_path) else known_png_path
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

    # 2. Check sharded location on disk (2-level catId/slot/ and 1-level catId/)
    if not fits_path:
        shard_fits_dir = os.path.join(ds.fits_dir, shard_sub)
        for base in candidates_base:
            fn = f"pfsObject_{base}.fits"
            p = os.path.join(shard_fits_dir, fn)
            if os.path.exists(p):
                fits_path = p
                break
        if not fits_path:
            cat_fits_dir = os.path.join(ds.fits_dir, str(cat_id))
            for base in candidates_base:
                fn = f"pfsObject_{base}.fits"
                p = os.path.join(cat_fits_dir, fn)
                if os.path.exists(p):
                    fits_path = p
                    break

    if not png_path:
        shard_png_dir = os.path.join(ds.png_dir, shard_sub)
        for base in candidates_base:
            pn = f"spec_{base}.png"
            p = os.path.join(shard_png_dir, pn)
            if os.path.exists(p):
                png_path = p
                break
        if not png_path:
            cat_png_dir = os.path.join(ds.png_dir, str(cat_id))
            for base in candidates_base:
                pn = f"spec_{base}.png"
                p = os.path.join(cat_png_dir, pn)
                if os.path.exists(p):
                    png_path = p
                    break

    if fits_path and png_path:
        return fits_path, png_path

    # 3. Fallback to flat directory via in-memory set
    if not ds.files_indexed:
        index_extracted_files(ds)

    if not fits_path:
        for base in candidates_base:
            fn = f"pfsObject_{base}.fits"
            if fn in ds.fits_file_set:
                fits_path = os.path.join(ds.fits_dir, fn)
                break

    if not png_path:
        for base in candidates_base:
            pn = f"spec_{base}.png"
            if pn in ds.png_file_set:
                png_path = os.path.join(ds.png_dir, pn)
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
def get_sky_cache_file_path(db_path: Optional[str] = None) -> str:
    """Return path to persistent disk cache for full sky celestial coordinates for given database."""
    target_db = db_path
    if not target_db:
        base_dir = DEFAULT_BASE_DATA_DIR
        prefix = "pfs_metadata"
    else:
        base_dir = os.path.dirname(os.path.abspath(target_db))
        base_name = os.path.splitext(os.path.basename(target_db))[0]
        prefix = base_name
    return os.path.join(base_dir, f".{prefix}_sky_cache.json.gz")


def load_or_build_master_sky_cache(ds: Dataset, force: bool = False) -> Tuple[Optional[bytes], Optional[bytes], Optional[str]]:
    """
    Ensure the full celestial sky coordinates are cached in memory (both gzip and raw json bytes)
    for the database of dataset ``ds``.
    1. Loads from persistent .{dbname}_sky_cache.json.gz (or legacy .sky_positions_cache.json.gz) in ~2ms.
    2. Otherwise queries the active SQLite database, serializes, compresses, and saves disk cache.
    """
    active_db = os.path.abspath(ds.db_path) if ds.db_path else ""
    if not active_db or not os.path.exists(active_db):
        return None, None, None

    if not force and ds.sky_gzip_bytes is not None and ds.sky_json_bytes is not None:
        return ds.sky_gzip_bytes, ds.sky_json_bytes, ds.sky_etag

    with ds.sky_lock:
        if not force and ds.sky_gzip_bytes is not None and ds.sky_json_bytes is not None:
            return ds.sky_gzip_bytes, ds.sky_json_bytes, ds.sky_etag

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
                ds.sky_gzip_bytes = gz_data
                ds.sky_json_bytes = raw_data
                ds.sky_etag = etag
                print(f"  ⚡ Loaded master sky coordinates cache ({len(gz_data)/1024/1024:.2f} MB gzip) for {active_db} in {(time.time()-t0)*1000:.1f} ms")
                return ds.sky_gzip_bytes, ds.sky_json_bytes, ds.sky_etag
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

            ds.sky_gzip_bytes = gz_bytes
            ds.sky_json_bytes = raw_bytes
            ds.sky_etag = etag

            try:
                with open(cache_file, "wb") as f:
                    f.write(gz_bytes)
            except Exception as e:
                print(f"Warning: Could not save sky disk cache: {e}")

            print(f"  ⚡ Built master sky coordinates cache ({len(results):,} targets, {len(gz_bytes)/1024/1024:.2f} MB gzip) for {active_db} in {time.time()-t0:.2f}s")
            return ds.sky_gzip_bytes, ds.sky_json_bytes, ds.sky_etag
        except Exception as e:
            print(f"Error building master sky coordinates cache for {active_db}: {e}")
            return None, None, None


# -----------------------------------------------------------------------------
# Frontend Route
# -----------------------------------------------------------------------------
PUBLIC_PATHS = {"/datasets", "/api/datasets", "/api/datasets/select", "/favicon.ico"}


@app.middleware("http")
async def dataset_middleware(request: Request, call_next):
    """Select the dataset for this request and check that the browser is authorized for it.

    Dataset id priority: X-PFS-Dataset header (fetch calls) > ?ds= query (images/links, page URL)
    > the browser's current dataset in the session cookie. Using the explicit id lets browser tabs
    showing different datasets coexist.
    """
    path = request.url.path
    if path.startswith("/static/") or path in PUBLIC_PATHS:
        return await call_next(request)

    REGISTRY.reload_if_changed()
    session = REGISTRY.decode_session(request.cookies.get(SESSION_COOKIE))
    ds_id = (request.headers.get("x-pfs-dataset") or request.query_params.get("ds")
             or session.get("ds"))
    ds = REGISTRY.get(ds_id)
    if ds is None and not request.headers.get("x-pfs-dataset") and not request.query_params.get("ds"):
        ds = REGISTRY.default_open_dataset()

    if ds is None or not REGISTRY.is_authorized(ds, session):
        if path == "/":
            return RedirectResponse("/datasets", status_code=303)
        return JSONResponse(
            {"detail": "Dataset not selected or not authorized", "code": "dataset_required"},
            status_code=401,
        )

    if not ds._ready:
        await run_in_threadpool(ds.ensure_ready)
    token = _CURRENT_DATASET.set(ds)
    try:
        response = await call_next(request)
    finally:
        _CURRENT_DATASET.reset(token)

    # Opening the dashboard makes this the browser's current dataset
    if path == "/" and session.get("ds") != ds.id:
        session["ds"] = ds.id
        set_session_cookie(response, session)
    return response


def set_session_cookie(response: Response, session: dict):
    response.set_cookie(
        SESSION_COOKIE,
        REGISTRY.encode_session(session),
        max_age=REGISTRY.session_max_age,
        httponly=True,
        samesite="lax",
        path="/",
    )


def dataset_listing(session: dict) -> List[dict]:
    current = session.get("ds")
    return [
        {
            "id": d.id,
            "name": d.name,
            "description": d.description,
            "locked": bool(d.password),
            "authorized": REGISTRY.is_authorized(d, session),
            "current": d.id == current,
        }
        for d in REGISTRY.all()
    ]


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    """Render the main dashboard interface for the selected dataset."""
    ds = cur_ds()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "dataset_id": ds.id,
            "dataset_name": ds.name,
            "can_switch": len(REGISTRY.all()) > 1 or bool(ds.password),
        },
    )


@app.get("/datasets", response_class=HTMLResponse)
async def serve_dataset_selector(request: Request):
    """Render the dataset selection page."""
    REGISTRY.reload_if_changed()
    session = REGISTRY.decode_session(request.cookies.get(SESSION_COOKIE))
    return templates.TemplateResponse(
        request=request,
        name="datasets.html",
        context={"datasets": dataset_listing(session)},
    )


@app.get("/api/datasets")
def list_datasets(request: Request):
    """List configured datasets (names only; paths are not exposed)."""
    REGISTRY.reload_if_changed()
    session = REGISTRY.decode_session(request.cookies.get(SESSION_COOKIE))
    return {"datasets": dataset_listing(session)}


class DatasetSelectRequest(BaseModel):
    id: str
    password: Optional[str] = None


@app.post("/api/datasets/select")
def select_dataset(req: DatasetSelectRequest, request: Request):
    """Make a dataset this browser's current dataset, checking its password if it has one."""
    REGISTRY.reload_if_changed()
    ds = REGISTRY.get(req.id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Unknown dataset")
    session = REGISTRY.decode_session(request.cookies.get(SESSION_COOKIE))
    if ds.password and not REGISTRY.is_authorized(ds, session):
        if not hmac.compare_digest((req.password or "").encode("utf-8"), ds.password.encode("utf-8")):
            time.sleep(0.5)  # slow down password guessing
            raise HTTPException(status_code=403, detail="Incorrect password")
        auth = session.get("auth") if isinstance(session.get("auth"), dict) else {}
        auth[ds.id] = REGISTRY.password_fingerprint(ds)
        session["auth"] = auth
    session["ds"] = ds.id
    response = JSONResponse({"ok": True, "id": ds.id, "redirect": f"/?ds={urllib.parse.quote(ds.id)}"})
    set_session_cookie(response, session)
    return response


# -----------------------------------------------------------------------------
# API Routes
# -----------------------------------------------------------------------------
def check_has_ml_predictions(conn: sqlite3.Connection) -> Tuple[bool, int]:
    """Check if survey_predictions table exists and has rows."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='survey_predictions'")
        if cur.fetchone()[0] == 0:
            return False, 0
        cur.execute("SELECT count(*) FROM survey_predictions")
        cnt = cur.fetchone()[0]
        return (cnt > 0), cnt
    except Exception:
        return False, 0


@app.get("/api/stats")
def get_stats(refresh: bool = Query(False, description="Force refresh statistics cache")):
    """Get repository overview statistics (cached in memory for instant response)."""
    ds = cur_ds()
    if ds.stats_cache is not None and not refresh:
        return ds.stats_cache

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

        has_ml, ml_count = check_has_ml_predictions(conn)

        result = {
            "total_targets": total,
            "classification_counts": class_counts,
            "catalogs_count": cat_count,
            "cat_ids": cat_counts,
            "combinations_count": comb_count,
            "has_ml_predictions": has_ml,
            "ml_predictions_count": ml_count,
            "db_path": ds.db_path,
            "data_dir": ds.data_dir,
            "dataset_id": ds.id,
            "dataset_name": ds.name,
            "table_used": tbl,
        }
        ds.stats_cache = result
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

        has_ml, _ = check_has_ml_predictions(conn)
        ml_select = "sp.pred_class, sp.pred_redshift, sp.pred_confidence," if has_ml else ""
        ml_join = "LEFT JOIN survey_predictions sp ON t.catId = sp.catId AND t.objId = sp.objId AND t.combination = sp.combination" if has_ml else ""

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
                {ml_select}
                1 AS _dummy
            FROM {tbl} t
            {ml_join}
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
            if has_ml:
                d["pred_class"] = d.get("pred_class")
                d["pred_redshift"] = sanitize_val(d.get("pred_redshift"))
                d["pred_confidence"] = sanitize_val(d.get("pred_confidence"))
            d.pop("_dummy", None)
            results.append(d)

        pages = (total + limit - 1) // limit if limit > 0 else 1

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "pages": pages,
            "has_ml_predictions": has_ml,
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
        gz_data, raw_data, etag = load_or_build_master_sky_cache(cur_ds())
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
def get_target_details(catId: int, objId: str, combination: Optional[str] = Query(None)):
    """Retrieve full solver, candidate, and line measurement details for a target."""
    conn = get_db()
    cur = conn.cursor()
    try:
        tbl = get_summary_table(conn)
        obj_id_int = int(objId)
        # Target summary info
        if combination:
            cur.execute(f"SELECT * FROM {tbl} WHERE catId = ? AND objId = ? AND combination = ?", (catId, obj_id_int, combination))
        else:
            cur.execute(f"SELECT * FROM {tbl} WHERE catId = ? AND objId = ?", (catId, obj_id_int))
        target_row = cur.fetchone()
        if not target_row:
            raise HTTPException(status_code=404, detail="Target not found in database")
        target_info = {k: sanitize_val(v) for k, v in dict(target_row).items()}
        target_info["objId"] = str(target_info["objId"])

        # Determine target combination to filter child tables accurately
        comb = target_info.get("combination")
        comb_filter_sql = " AND combination = ?" if comb else ""
        comb_params = (catId, obj_id_int, comb) if comb else (catId, obj_id_int)

        # Solver results
        cur.execute(f"SELECT * FROM solver_results WHERE catId = ? AND objId = ?{comb_filter_sql}", comb_params)
        solver_rows = []
        for r in cur.fetchall():
            rd = {k: sanitize_val(v) for k, v in dict(r).items()}
            rd["objId"] = str(rd.get("objId", ""))
            solver_rows.append(rd)

        # Redshift candidates
        cur.execute(
            f"""
            SELECT * FROM redshift_candidates 
            WHERE catId = ? AND objId = ?{comb_filter_sql}
            ORDER BY objectType, cRank ASC
            """,
            comb_params,
        )
        candidate_rows = []
        for r in cur.fetchall():
            rd = {k: sanitize_val(v) for k, v in dict(r).items()}
            rd["objId"] = str(rd.get("objId", ""))
            candidate_rows.append(rd)

        # Line measurements
        cur.execute(
            f"""
            SELECT * FROM line_measurements 
            WHERE catId = ? AND objId = ?{comb_filter_sql}
            ORDER BY objectType, lineWave ASC
            """,
            comb_params,
        )
        line_rows = []
        for r in cur.fetchall():
            rd = {k: sanitize_val(v) for k, v in dict(r).items()}
            rd["objId"] = str(rd.get("objId", ""))
            line_rows.append(rd)

        # Machine learning survey prediction (pfs_specClass2)
        ml_prediction = None
        try:
            cur.execute(
                f"SELECT * FROM survey_predictions WHERE catId = ? AND objId = ?{comb_filter_sql} LIMIT 1",
                comb_params,
            )
            sp_row = cur.fetchone()
            if sp_row:
                ml_prediction = {k: sanitize_val(v) for k, v in dict(sp_row).items()}
                ml_prediction["objId"] = str(ml_prediction.get("objId", ""))
        except Exception:
            pass

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
            "ml_prediction": ml_prediction,
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
def get_spectrum_data(
    catId: int,
    objId: str,
    combination: Optional[str] = Query(None),
    format: Optional[str] = Query(None, description="Output format: 'binary' (default) or 'json'"),
    request: Request = None,
):
    """
    Parse FITS raw data (WAVELENGTH, FLUX, COVAR, MASK, OBSERVATIONS)
    and return binary Float32Array stream or JSON for interactive Plotly rendering.
    """
    obj_id_int = int(objId)
    conn = get_db()
    cur = conn.cursor()
    tbl = get_summary_table(conn)
    has_file_cols = check_db_file_columns(conn)
    file_cols_sql = ", fits_path, png_path" if has_file_cols else ""
    if combination:
        cur.execute(f"SELECT obCode, combination {file_cols_sql} FROM {tbl} WHERE catId = ? AND objId = ? AND combination = ?", (catId, obj_id_int, combination))
    else:
        cur.execute(f"SELECT obCode, combination {file_cols_sql} FROM {tbl} WHERE catId = ? AND objId = ?", (catId, obj_id_int))
    row = cur.fetchone()
    conn.close()

    ob_code = row["obCode"] if row else None
    comb_val = row["combination"] if (row and "combination" in row.keys()) else combination
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

            points_count = len(wave) if wave is not None else 0

            accept = request.headers.get("accept", "") if request else ""
            use_binary = (format == "binary") or (format != "json" and ("application/octet-stream" in accept or "application/json" not in accept))

            if use_binary:
                wave_bytes = np.ascontiguousarray(wave, dtype="<f4").tobytes() if wave is not None else b""
                flux_bytes = np.ascontiguousarray(flux, dtype="<f4").tobytes() if flux is not None else b""

                byte_offset = 0
                arrays_meta = {
                    "wavelength": {"offset": byte_offset, "dtype": "float32"},
                }
                byte_offset += len(wave_bytes)

                arrays_meta["flux"] = {"offset": byte_offset, "dtype": "float32"}
                byte_offset += len(flux_bytes)

                binary_chunks = [wave_bytes, flux_bytes]

                if variance is not None:
                    var_bytes = np.ascontiguousarray(variance, dtype="<f4").tobytes()
                    arrays_meta["variance"] = {"offset": byte_offset, "dtype": "float32"}
                    byte_offset += len(var_bytes)
                    binary_chunks.append(var_bytes)

                    with np.errstate(invalid="ignore"):
                        noise_arr = np.sqrt(np.where(variance > 0, variance, np.nan))
                    noise_bytes = np.ascontiguousarray(noise_arr, dtype="<f4").tobytes()
                    arrays_meta["noise"] = {"offset": byte_offset, "dtype": "float32"}
                    byte_offset += len(noise_bytes)
                    binary_chunks.append(noise_bytes)
                else:
                    arrays_meta["variance"] = None
                    arrays_meta["noise"] = None

                if mask is not None:
                    mask_bytes = np.ascontiguousarray(mask, dtype="<i4").tobytes()
                    arrays_meta["mask"] = {"offset": byte_offset, "dtype": "int32"}
                    byte_offset += len(mask_bytes)
                    binary_chunks.append(mask_bytes)
                else:
                    arrays_meta["mask"] = None

                header_data = {
                    "catId": catId,
                    "objId": str(objId),
                    "points_count": points_count,
                    "observations": observations,
                    "arrays": arrays_meta,
                }
                header_json_bytes = json.dumps(header_data).encode("utf-8")
                header_len = len(header_json_bytes)
                pad_len = (4 - ((8 + header_len) % 4)) % 4
                pad_bytes = b"\x00" * pad_len

                payload = b"".join([
                    b"PFSS",
                    header_len.to_bytes(4, byteorder="little"),
                    header_json_bytes,
                    pad_bytes,
                    *binary_chunks
                ])

                return Response(content=payload, media_type="application/octet-stream")

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
                "points_count": points_count,
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read FITS file: {str(e)}")


@app.get("/api/targets/{catId}/{objId}/image")
def get_spectrum_image(catId: int, objId: str, combination: Optional[str] = Query(None)):
    """Return PNG spectrum plot image."""
    obj_id_int = int(objId)
    conn = get_db()
    cur = conn.cursor()
    tbl = get_summary_table(conn)
    has_file_cols = check_db_file_columns(conn)
    file_cols_sql = ", png_path" if has_file_cols else ""
    if combination:
        cur.execute(f"SELECT obCode, combination {file_cols_sql} FROM {tbl} WHERE catId = ? AND objId = ? AND combination = ?", (catId, obj_id_int, combination))
    else:
        cur.execute(f"SELECT obCode, combination {file_cols_sql} FROM {tbl} WHERE catId = ? AND objId = ?", (catId, obj_id_int))
    row = cur.fetchone()
    conn.close()

    ob_code = row["obCode"] if row else None
    comb_val = row["combination"] if (row and "combination" in row.keys()) else combination
    known_png = row["png_path"] if (row and has_file_cols and "png_path" in row.keys()) else None

    _, png_file = find_files(catId, obj_id_int, ob_code, combination=comb_val, known_png_path=known_png)
    if not png_file or not os.path.exists(png_file):
        raise HTTPException(status_code=404, detail="Spectrum PNG image not found")
    return FileResponse(png_file, media_type="image/png")


@app.get("/api/targets/{catId}/{objId}/fits")
def download_fits(catId: int, objId: str, combination: Optional[str] = Query(None)):
    """Download raw FITS file."""
    obj_id_int = int(objId)
    conn = get_db()
    cur = conn.cursor()
    tbl = get_summary_table(conn)
    has_file_cols = check_db_file_columns(conn)
    file_cols_sql = ", fits_path" if has_file_cols else ""
    if combination:
        cur.execute(f"SELECT obCode, combination {file_cols_sql} FROM {tbl} WHERE catId = ? AND objId = ? AND combination = ?", (catId, obj_id_int, combination))
    else:
        cur.execute(f"SELECT obCode, combination {file_cols_sql} FROM {tbl} WHERE catId = ? AND objId = ?", (catId, obj_id_int))
    row = cur.fetchone()
    conn.close()

    ob_code = row["obCode"] if row else None
    comb_val = row["combination"] if (row and "combination" in row.keys()) else combination
    known_fits = row["fits_path"] if (row and has_file_cols and "fits_path" in row.keys()) else None

    fits_file, _ = find_files(catId, obj_id_int, ob_code, combination=comb_val, known_fits_path=known_fits)
    if not fits_file or not os.path.exists(fits_file):
        raise HTTPException(status_code=404, detail="FITS file not found")
    filename = os.path.basename(fits_file)
    return FileResponse(fits_file, media_type="application/fits", filename=filename)


# -----------------------------------------------------------------------------
# Sky Cutout API (Subaru HSC with Pan-STARRS / DSS2 Fallback)
# -----------------------------------------------------------------------------
SURVEY_HIPS_MAP = {
    # HSC-SSP PDR3 color images served by the Legacy Survey viewer (does not depend on CDS)
    "hsc_dr3": {
        "source": "legacysurvey",
        "layer": "hsc-dr3",
        "name": "Subaru HSC PDR3 (Legacy Survey)",
        "badge": "Subaru HSC",
    },
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


# Surveys that are not a fallback from the HSC point of view
HSC_SURVEYS = {"hsc_dr3", "hsc_wide", "hsc_deep"}
# Order tried by survey=auto
AUTO_SURVEY_ORDER = ["hsc_dr3", "hsc_wide", "panstarrs", "dss"]

# Skip a host for a while after a connection-level failure (timeout, refused,
# DNS) so that every cutout request does not wait for the full timeout again.
HOST_RETRY_INTERVAL_SEC = 300
_host_down_until: Dict[str, float] = {}
_host_down_lock = threading.Lock()


def _fetch_url_bytes(url: str, timeout: int = 8) -> Optional[bytes]:
    """GET ``url`` and return the body, or None on failure (with the reason logged)."""
    host = urllib.parse.urlsplit(url).hostname or ""
    with _host_down_lock:
        down_until = _host_down_until.get(host, 0.0)
    if time.time() < down_until:
        return None
    req = urllib.request.Request(url, headers={"User-Agent": "PFSTargetViewer/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return resp.read()
            print(f"  ⚠️ Cutout fetch from {host} returned HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        print(f"  ⚠️ Cutout fetch from {host} failed: HTTP {e.code} {e.reason}")
    except Exception as e:
        # Connection-level failure: mark the host as down for a while
        with _host_down_lock:
            _host_down_until[host] = time.time() + HOST_RETRY_INTERVAL_SEC
        print(f"  ⚠️ Cutout fetch from {host} failed ({type(e).__name__}: {e}); "
              f"skipping this host for {HOST_RETRY_INTERVAL_SEC} s")
    return None


def fetch_hips_cutout_raw(hips_id: str, ra: float, dec: float, fov: float, width: int = 300, height: int = 300, timeout: int = 8) -> Optional[bytes]:
    """Fetch raw JPEG cutout from CDS hips2fits service."""
    encoded_hips = urllib.parse.quote(hips_id, safe="")
    url = (
        f"https://alasky.cds.unistra.fr/hips-image-services/hips2fits"
        f"?hips={encoded_hips}&ra={ra}&dec={dec}&fov={fov}&width={width}&height={height}&format=jpg"
    )
    return _fetch_url_bytes(url, timeout=timeout)


def fetch_legacysurvey_cutout_raw(layer: str, ra: float, dec: float, fov: float, width: int = 300, height: int = 300, timeout: int = 8) -> Optional[bytes]:
    """Fetch raw JPEG cutout from the Legacy Survey viewer (fov in degrees spans the image width)."""
    pixscale = fov * 3600.0 / width  # arcsec / pixel
    url = (
        f"https://www.legacysurvey.org/viewer/cutout.jpg"
        f"?ra={ra}&dec={dec}&layer={urllib.parse.quote(layer)}"
        f"&pixscale={pixscale:.6f}&width={width}&height={height}"
    )
    return _fetch_url_bytes(url, timeout=timeout)


def fetch_survey_cutout(survey_key: str, ra: float, dec: float, fov: float, width: int, height: int) -> Optional[bytes]:
    """Fetch a cutout for one entry of SURVEY_HIPS_MAP."""
    conf = SURVEY_HIPS_MAP[survey_key]
    if conf.get("source") == "legacysurvey":
        return fetch_legacysurvey_cutout_raw(conf["layer"], ra, dec, fov, width, height)
    return fetch_hips_cutout_raw(conf["id"], ra, dec, fov, width, height)


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
    If survey is 'auto', tries Subaru HSC PDR3 (Legacy Survey viewer, independent of CDS),
    then HSC DR2 wide via CDS hips2fits, and if outside HSC coverage (blank image) or the
    services are unreachable, falls back to Pan-STARRS DR1 and DSS2 (CDS hips2fits).
    """
    survey_key = survey.lower().strip()
    if survey_key != "auto" and survey_key not in SURVEY_HIPS_MAP:
        raise HTTPException(status_code=400, detail=f"Unsupported survey: {survey}")
    cache_prefix = f"cutout_{survey_key}_{ra:.5f}_{dec:+.5f}_{fov:.5f}_{width}x{height}"
    cutout_cache_dir = cur_ds().cutout_cache_dir
    cache_img = os.path.join(cutout_cache_dir, f"{cache_prefix}.jpg")
    cache_meta = os.path.join(cutout_cache_dir, f"{cache_prefix}.json")

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
        # HSC PDR3 (Legacy Survey) -> HSC DR2 (CDS) -> Pan-STARRS DR1 (CDS) -> DSS2 (CDS)
        for i, key in enumerate(AUTO_SURVEY_ORDER):
            data = fetch_survey_cutout(key, ra, dec, fov, width, height)
            is_last = i == len(AUTO_SURVEY_ORDER) - 1
            if data and (is_last or not is_blank_or_out_of_coverage(data)):
                img_data = data
                survey_used = key
                break
    else:
        img_data = fetch_survey_cutout(survey_key, ra, dec, fov, width, height)
        survey_used = survey_key

    if img_data:
        survey_name = SURVEY_HIPS_MAP[survey_used]["name"]
        is_fallback = survey_used not in HSC_SURVEYS

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
    min_ra: Optional[float] = None
    max_ra: Optional[float] = None
    min_dec: Optional[float] = None
    max_dec: Optional[float] = None

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


def filter_rows_spatially(
    rows: List[dict],
    min_ra: Optional[float],
    max_ra: Optional[float],
    min_dec: Optional[float],
    max_dec: Optional[float],
) -> List[dict]:
    """Filter list of target dictionaries by spatial bounding box (RA / Dec)."""
    if min_ra is None and max_ra is None and min_dec is None and max_dec is None:
        return rows

    filtered = []
    for r in rows:
        ra = r.get("ra") if "ra" in r else r.get("RA", r.get("coords_ra"))
        dec = r.get("dec") if "dec" in r else r.get("DEC", r.get("coords_dec"))
        if ra is None or dec is None:
            continue
        try:
            ra_f = float(ra)
            dec_f = float(dec)
        except (ValueError, TypeError):
            continue

        if min_dec is not None and dec_f < min_dec:
            continue
        if max_dec is not None and dec_f > max_dec:
            continue
        if min_ra is not None and max_ra is not None:
            if min_ra <= max_ra:
                if ra_f < min_ra or ra_f > max_ra:
                    continue
            else:
                # Wraps around RA 0 deg (e.g. 350 to 20)
                if ra_f < min_ra and ra_f > max_ra:
                    continue
        elif min_ra is not None and ra_f < min_ra:
            continue
        elif max_ra is not None and ra_f > max_ra:
            continue
        filtered.append(r)
    return filtered


def has_top_level_limit(sql: str) -> bool:
    """Check if the SQL query contains a top-level LIMIT clause (outside subqueries and string literals)."""
    clean = sql.strip().rstrip(";").rstrip()
    upper = clean.upper()
    depth = 0
    in_quote = False
    quote_char = ""
    idx = 0
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
                    return True
        idx += 1
    return False


def extract_trailing_order_by(sql: str) -> Optional[Tuple[str, str]]:
    """Extract (column_name, direction) from a top-level trailing ORDER BY clause if present."""
    clean = sql.strip().rstrip(";").rstrip()
    upper = clean.upper()
    search_from = len(upper)
    while True:
        pos = upper.rfind("ORDER", 0, search_from)
        if pos < 0:
            return None

        if pos > 0 and (upper[pos - 1].isalnum() or upper[pos - 1] == "_"):
            search_from = pos
            continue

        rest = upper[pos + 5:].lstrip()
        if not rest.startswith("BY"):
            search_from = pos
            continue

        by_idx = upper.find("BY", pos + 5)
        after_by = by_idx + 2
        if after_by < len(upper) and (upper[after_by].isalnum() or upper[after_by] == "_"):
            search_from = pos
            continue

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

        order_part = clean[after_by:].strip()
        m = re.match(r"^([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)?)(?:\s+(ASC|DESC))?", order_part, re.IGNORECASE)
        if m:
            col = m.group(1).split(".")[-1]
            direction = (m.group(2) or "asc").lower()
            return col, direction
        return None


def strip_trailing_order_by(sql: str) -> str:
    """Strip the outermost top-level ORDER BY clause ONLY when there is no top-level LIMIT.

    If a top-level LIMIT is present, ORDER BY must be preserved because it determines
    which rows are selected by the LIMIT clause.
    """
    clean = sql.strip().rstrip(";").rstrip()
    if has_top_level_limit(clean):
        return clean

    upper = clean.upper()
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

        return clean[:pos].rstrip()


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
    "pred_class": "Machine learning predicted target classification (GALAXY, QSO, STAR)",
    "prob_star": "ML posterior probability of being a Star [0-1]",
    "prob_galaxy": "ML posterior probability of being a Galaxy [0-1]",
    "prob_qso": "ML posterior probability of being a QSO [0-1]",
    "pred_confidence": "ML classification confidence score [0-1]",
    "pred_redshift": "ML predicted redshift for Galaxies and QSOs (0.0 for Stars)",
    "redshift_quality": "ML redshift prediction quality / confidence metric",
    "z_galaxy_candidate": "ML candidate redshift if evaluated as Galaxy",
    "z_qso_candidate": "ML candidate redshift if evaluated as QSO",
}

KNOWN_TABLE_DESCRIPTIONS = {
    "target_summary": "High-performance materialized summary table with coordinates, classification, redshift, and spectrum files.",
    "v_target_summary": "View of target summary combining targets, classifications, and latest fiber coordinates.",
    "survey_predictions": "Machine learning survey predictions (pfs_specClass2) with predicted classes, template probabilities, and ML redshifts.",
    "v_target_predictions": "Convenience view combining target_summary with machine learning predictions (survey_predictions).",
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

    has_comb = "combination" in out_cols
    if has_comb:
        join_clause = f"""
        LEFT JOIN {tbl} _ts 
          ON _ts.catId = _user_query.catId 
         AND _ts.objId = _user_query.objId 
         AND _ts.combination = _user_query.combination
        """
    else:
        # Guarantee strictly 1-to-1 matching via rowid lookup to prevent Cartesian row multiplication
        # when a target has multiple coadd combinations in target_summary
        join_clause = f"""
        LEFT JOIN {tbl} _ts 
          ON _ts.rowid = (
              SELECT rowid FROM {tbl} 
              WHERE catId = _user_query.catId AND objId = _user_query.objId 
              LIMIT 1
          )
        """

    wrapped_sql = f"""
        WITH _user_query AS (
            {sql}
        )
        SELECT 
            _user_query.*
            {extra_str}
        FROM _user_query
        {join_clause}
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


KNOWN_SPECTRAL_REST_WAVELENGTHS = {
    'AlII1670': 167.08, 'AlIII1854': 185.47, 'AlIII1862': 186.28, 'ArIII7136': 713.87, 'ArIII7751': 775.32,
    'CI': 156.07, 'CII': 133.45, 'CIII1176a': 117.57, 'CIII1176b': 117.64, 'CIV1548': 154.82,
    'CIV1548A': 154.82, 'CIV1550': 155.08, 'CIV1550A': 155.08, 'CaII_H': 396.95, 'CaII_K': 393.47,
    'CaII_t1A': 850.04, 'CaII_t2A': 854.44, 'CaII_t3A': 866.45, 'FeI': 358.22, 'FeI6494': 649.68,
    'FeII1608': 160.84, 'FeII2249': 225.05, 'FeII2260': 226.14, 'FeII2324': 232.46, 'FeII2344': 234.48,
    'FeII2374': 237.51, 'FeII2382': 238.34, 'FeII2586': 258.73, 'FeII2600': 260.09, 'FeII2964': 296.82,
    'FeII3785': 378.55, 'FeII4564': 457.08, 'FeII5305': 530.60, 'FeIII': 207.66, 'FeVII': 375.85,
    'GBand': 430.46, 'H10': 379.89, 'H10A': 379.89, 'H11': 377.16, 'H11A': 377.16,
    'H8': 389.01, 'H8A': 389.01, 'H9': 383.64, 'H9A': 383.64, 'Halpha': 656.46,
    'HalphaA': 656.46, 'Hbeta': 486.27, 'HbetaA': 486.27, 'Hdelta': 410.28, 'HdeltaA': 410.28,
    'HeI3190': 319.18, 'HeI5876': 587.74, 'HeII_d': 164.04, 'HeIIa': 164.05, 'HeIIb': 164.03,
    'Hepsilon': 397.12, 'Hgamma': 434.16, 'HgammaA': 434.16, 'LyAA': 121.57, 'LyAE': 121.57,
    'LyBA': 102.57, 'LyBE': 102.57, 'LyGA': 97.25, 'LyGE': 97.25, 'MgI2852': 285.37,
    'MgII2796': 279.71, 'MgII2796E': 279.71, 'MgII2803': 280.43, 'MgII2803E': 280.43, 'MgI_t1A': 516.88,
    'MgI_t2A': 517.41, 'MgI_t3A': 518.51, 'NII1084a': 108.40, 'NII1084b': 108.46, 'NV_d': 124.08,
    'Na_D1': 589.16, 'Na_D2': 589.76, 'NeIII': 386.90, 'NiII': 137.05, 'OI': 844.88,
    'OI-SiII': 130.54, 'OI1302': 130.22, 'OII7319': 732.10, 'OII7330': 733.22, 'OIII1661': 166.13,
    'OIII1666': 166.66, 'OIII_d': 166.39, 'OVI1031A': 103.19, 'OVI1031E': 103.19, 'OVI1037A': 103.76,
    'OVI1037E': 103.76, 'P10': 901.74, 'P10A': 901.74, 'P11': 886.52, 'P11A': 886.52,
    'P9': 923.16, 'P9A': 923.16, 'SIII9068': 907.11, 'SiII1190': 119.04, 'SiII1193': 119.33,
    'SiII1260': 126.04, 'SiII1526': 152.67, 'SiIII1206': 120.65, 'SiIV1393': 139.37, 'SiIV1398_d': 139.82,
    'SiIV1402': 140.28, '[CIII]1907': 190.67, '[CIII]1909': 190.87, '[NII]a': 658.53, '[NII]b': 654.99,
    '[NeVa]': 342.67, '[NeVb]': 334.68, '[OIII]a': 500.82, '[OIII]b': 496.03, '[OII]3726': 372.71,
    '[OII]3729': 372.99, '[OI]6301': 630.21, '[SII]6716': 671.83, '[SII]6731': 673.27
}

def load_or_build_spectral_lines_cache(ds: Dataset, force: bool = False) -> Optional[dict]:
    """
    Ensure the spectral lines catalog is cached and up-to-date with the database.
    - If spectral_lines_cache.json exists and mtime >= db_mtime, load it (<1ms).
    - If DB is newer than cache (or cache is missing or force=True), re-aggregate from DB and save cache.
    """
    active_db = os.path.abspath(ds.db_path) if ds.db_path else ""
    if not active_db or not os.path.exists(active_db):
        return ds.lines_cache

    db_mtime = os.path.getmtime(active_db)

    # In-memory fast path: DB hasn't been modified since we cached it
    if not force and ds.lines_cache is not None and ds.lines_db_mtime >= db_mtime:
        return ds.lines_cache

    with ds.lines_lock:
        if not force and ds.lines_cache is not None and ds.lines_db_mtime >= db_mtime:
            return ds.lines_cache

        candidate_cache_paths = [
            os.path.join(os.path.dirname(active_db), "spectral_lines_cache.json"),
            os.path.join(ds.data_dir, "spectral_lines_cache.json"),
            os.path.join(os.path.dirname(__file__), "..", "extracted_targets", "spectral_lines_cache.json"),
            os.path.join(os.path.dirname(__file__), "..", "spectral_lines_cache.json"),
        ]

        # 1. Try reading disk cache if valid and newer than or equal to DB modification time
        if not force:
            for p in candidate_cache_paths:
                if p and os.path.exists(p) and os.path.getmtime(p) >= db_mtime:
                    try:
                        with open(p, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            if data.get("lines") and "restWave_nm" in data["lines"][0]:
                                ds.lines_cache = data
                                ds.lines_db_mtime = db_mtime
                                return ds.lines_cache
                    except Exception:
                        pass

        # 2. Re-aggregate from active database
        try:
            conn = sqlite3.connect(f"file:{active_db}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT lineName, count(*) as count
                FROM line_measurements
                WHERE lineName IS NOT NULL AND lineName != ''
                GROUP BY lineName
                ORDER BY count DESC
            """)
            rows = cur.fetchall()
            lines = []
            for r in rows:
                name = r["lineName"]
                cnt = r["count"]
                rest_nm = KNOWN_SPECTRAL_REST_WAVELENGTHS.get(name)
                rest_A = round(rest_nm * 10.0, 1) if rest_nm is not None else None
                lines.append({
                    "lineName": name,
                    "count": cnt,
                    "restWave_nm": rest_nm,
                    "restWave_A": rest_A,
                })
            ds.lines_cache = {
                "total_lines": len(lines),
                "lines": lines,
            }
            ds.lines_db_mtime = db_mtime
            conn.close()

            # Save updated cache to disk
            for save_p in [candidate_cache_paths[0], candidate_cache_paths[1], candidate_cache_paths[2]]:
                if save_p and os.path.dirname(save_p) and os.path.exists(os.path.dirname(save_p)):
                    try:
                        with open(save_p, "w", encoding="utf-8") as f:
                            json.dump(ds.lines_cache, f, indent=2)
                    except Exception:
                        pass

            print(f"  ⚡ Updated spectral lines catalog cache ({len(lines)} lines) for {active_db}")
            return ds.lines_cache
        except Exception as e:
            print(f"Warning: Failed to re-aggregate spectral lines from database: {e}")
            # Fallback to existing disk cache if available
            for p in candidate_cache_paths:
                if p and os.path.exists(p):
                    try:
                        with open(p, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            if data.get("lines") and "restWave_nm" in data["lines"][0]:
                                ds.lines_cache = data
                                return ds.lines_cache
                    except Exception:
                        pass
            return ds.lines_cache


@app.get("/api/sql/lines")
def get_spectral_lines():
    """Retrieve metadata catalog of measured spectral lines in line_measurements with rest-frame wavelengths."""
    catalog = load_or_build_spectral_lines_cache(cur_ds())
    if catalog is not None:
        return catalog
    raise HTTPException(status_code=500, detail="Failed to load spectral lines catalog")


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

    has_limit = has_top_level_limit(optimized_sql)
    # Cache key is per dataset (database file) + normalized SQL
    cache_key_source = f"{cur_ds().db_path}\n" + strip_trailing_order_by(optimized_sql)

    # For queries without top-level LIMIT, extract user-written ORDER BY if client did not supply sort_by
    initial_sort = extract_trailing_order_by(optimized_sql) if not has_limit else None
    effective_sort_by = req.sort_by or (initial_sort[0] if initial_sort else None)
    effective_order = req.order if req.sort_by else (initial_sort[1] if initial_sort else (req.order or "asc"))

    # Check cache first if not explicitly forced to refresh
    if not req.force_refresh:
        cached = SQL_CACHE.get(cache_key_source)
        if cached:
            all_rows = cached["all_rows"]
            effective_rows = filter_rows_spatially(all_rows, req.min_ra, req.max_ra, req.min_dec, req.max_dec)
            total = len(effective_rows)
            pages = max(1, math.ceil(total / limit)) if total > 0 else 1

            # When top-level LIMIT is present, keep exact database-returned order.
            # Otherwise, sort full dataset in memory.
            if has_limit:
                sorted_rows = effective_rows
            else:
                sorted_rows = sort_cached_rows(effective_rows, effective_sort_by, effective_order)
            page_rows = sorted_rows[offset : offset + limit]

            # Send sky targets only if requested (skip on page flip / sort to save bandwidth)
            sky_targets = None if req.skip_sky else filter_rows_spatially(cached.get("sky_targets", []), req.min_ra, req.max_ra, req.min_dec, req.max_dec)
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
                "master_sky_targets": None if req.skip_sky else cached.get("sky_targets", []),
                "cached": True,
            }

    # Cache miss: execute query on database
    conn = get_db()
    set_query_timeout(conn, timeout_sec=15.0)
    cur = conn.cursor()
    try:
        # If top-level LIMIT is present, strip_trailing_order_by preserves ORDER BY so LIMIT selects the correct ordered rows.
        # Otherwise, ORDER BY is stripped before wrapping so the full unordered query is executed and cached.
        query_for_exec = strip_trailing_order_by(optimized_sql)
        try:
            executable_sql, user_cols, has_identity = wrap_query_with_target_summary(conn, query_for_exec)
        except Exception as wrap_err:
            executable_sql = query_for_exec
            user_cols = []
            has_identity = False

        try:
            cur.execute(executable_sql)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Query Execution Error: {e}")

        # Enforce memory safety cap on cached SQL results (fetch up to MAX_SQL_CACHE_ROWS + 1 to avoid loading unbounded rows)
        raw_rows = cur.fetchmany(MAX_SQL_CACHE_ROWS + 1)
        if len(raw_rows) > MAX_SQL_CACHE_ROWS:
            del raw_rows
            raise HTTPException(
                status_code=400,
                detail=f"Query returned more than {MAX_SQL_CACHE_ROWS:,} rows, exceeding the in-memory cache safety limit. "
                       f"Please add a WHERE clause or LIMIT to restrict your query results."
            )
        total = len(raw_rows)

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

            if has_identity:
                ra_val = clean_item.get("ra") if "ra" in clean_item else clean_item.get("RA", clean_item.get("coords_ra"))
                dec_val = clean_item.get("dec") if "dec" in clean_item else clean_item.get("DEC", clean_item.get("coords_dec"))
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

        # When top-level LIMIT is present, keep exact database-returned order.
        # Otherwise, sort full dataset in memory.
        effective_rows = filter_rows_spatially(all_clean_rows, req.min_ra, req.max_ra, req.min_dec, req.max_dec)
        eff_total = len(effective_rows)
        eff_pages = max(1, math.ceil(eff_total / limit)) if eff_total > 0 else 1

        if has_limit:
            sorted_rows = effective_rows
        else:
            sorted_rows = sort_cached_rows(effective_rows, effective_sort_by, effective_order)
        page_rows = sorted_rows[offset : offset + limit]

        effective_sky = None if req.skip_sky else filter_rows_spatially(sky_targets, req.min_ra, req.max_ra, req.min_dec, req.max_dec)
        duration_ms = round((time.time() - t_start) * 1000.0, 1)

        return {
            "total": eff_total,
            "page": page,
            "limit": limit,
            "pages": eff_pages,
            "duration_ms": duration_ms,
            "execution_time_ms": duration_ms,
            "has_identity": has_identity,
            "user_columns": user_cols,
            "columns": user_cols,
            "targets": page_rows,
            "sky_targets": effective_sky,
            "master_sky_targets": None if req.skip_sky else sky_targets,
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

  # 5. Serve several datasets selectable in the browser (optionally password-protected):
  python app.py --config datasets.toml
  ./run_viewer.sh --config datasets.toml
  (datasets.toml next to app.py is used automatically; see datasets.example.toml)
"""
    )
    parser.add_argument("target_dir", nargs="?", default=None,
                        help="Directory containing pfs_metadata.sqlite3 and extracted_targets/ (optional)")
    parser.add_argument("-d", "--dir", "--dataset-dir", dest="opt_dir", default=None,
                        help="Directory containing pfs_metadata.sqlite3 and extracted_targets/")
    parser.add_argument("-c", "--config", default=None,
                        help=f"Datasets config file (TOML) listing selectable datasets "
                             f"(default: {DEFAULT_CONFIG_PATH} if it exists)")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8090, help="Port to listen on (default: 8090)")
    parser.add_argument("--db", default=None, help="Explicit path to pfs_metadata.sqlite3")
    parser.add_argument("--data-dir", default=None, help="Explicit path to extracted_targets directory")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload on code changes")
    args = parser.parse_args()

    # Pass settings through environment variables so that --reload workers see them too
    chosen_dir = args.opt_dir or args.target_dir
    if args.config:
        os.environ["PFS_VIEWER_CONFIG"] = os.path.abspath(os.path.expanduser(args.config))
    if chosen_dir:
        os.environ["PFS_DATA_ROOT"] = os.path.abspath(os.path.expanduser(chosen_dir))
    if args.db:
        os.environ["PFS_DB_PATH"] = os.path.abspath(os.path.expanduser(args.db))
    if args.data_dir:
        os.environ["PFS_DATA_DIR"] = os.path.abspath(os.path.expanduser(args.data_dir))
    init_registry_from_env()

    print("=" * 70)
    print("  🌌 Starting PFS Target & Spectrum Viewer")
    if REGISTRY.config_path:
        print(f"  ⚙️  Config:        {REGISTRY.config_path}")
    missing = False
    for d in REGISTRY.all():
        if os.path.exists(d.db_path):
            db_size_mb = os.path.getsize(d.db_path) / (1024 * 1024)
            db_size_str = f"{db_size_mb / 1024:.2f} GB" if db_size_mb >= 1024 else f"{db_size_mb:.1f} MB"
            db_status = f"✅ Found ({db_size_str})"
        else:
            db_status = "⚠️  NOT FOUND"
            missing = True
        if os.path.exists(d.data_dir):
            fits_count, png_count = d.count_extracted_files()
            data_status = f"✅ Found ({fits_count:,} FITS, {png_count:,} PNG)"
        else:
            data_status = "⚠️  NOT FOUND"
            missing = True
        lock = " 🔒" if d.password else ""
        print(f"  📚 Dataset [{d.id}] {d.name}{lock}")
        print(f"     📂 Database:  {d.db_path} [{db_status}]")
        print(f"     📁 Data Dir:  {d.data_dir} [{data_status}]")
    if not REGISTRY.all():
        print("  ⚠️  No datasets configured.")
    print(f"  🌐 URL:           http://{args.host}:{args.port}")
    if missing:
        print("-" * 70)
        print("  ⚠️  Notice: One or more data targets were not found.")
        print("     Please ensure the directory contains 'pfs_metadata.sqlite3'")
        print("     and 'extracted_targets/' (or run download_data.sh).")
    print("=" * 70)

    if args.reload:
        app_dir = os.path.dirname(os.path.abspath(__file__))
        uvicorn.run("app:app", host=args.host, port=args.port, reload=True, app_dir=app_dir)
    else:
        uvicorn.run(app, host=args.host, port=args.port)
