#!/usr/bin/env python3
"""
PFS Target & Spectrum Viewer - Backend Application
Provides REST API and static web dashboard for inspecting PFS target metadata,
PNG spectra, and interactive FITS spectra from pfs_metadata.sqlite3 and extracted_targets.
"""
import glob
import os
import sqlite3
from typing import Any, Dict, List, Optional
import numpy as np

from astropy.io import fits
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Base directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "pfs_metadata.sqlite3"))
DEFAULT_DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "extracted_targets"))

DB_PATH = os.getenv("PFS_DB_PATH", DEFAULT_DB_PATH)
DATA_DIR = os.getenv("PFS_DATA_DIR", DEFAULT_DATA_DIR)
FITS_DIR = os.path.join(DATA_DIR, "fits")
PNG_DIR = os.path.join(DATA_DIR, "png")

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


def clean_str_name(name: str) -> str:
    """Sanitize filename component."""
    return "".join(c if (c.isalnum() or c in "._-") else "_" for c in name)


def find_files(cat_id: int, obj_id: int, ob_code: Optional[str] = None):
    """Locate matching FITS and PNG files for a given target."""
    fits_path = None
    png_path = None

    candidates_base = []
    if ob_code:
        candidates_base.append(clean_str_name(f"{ob_code}_{cat_id}_{obj_id}"))
    candidates_base.append(f"{cat_id}_{obj_id}")

    for base in candidates_base:
        f_cand = os.path.join(FITS_DIR, f"pfsObject_{base}.fits")
        if not fits_path and os.path.exists(f_cand):
            fits_path = f_cand

        p_cand = os.path.join(PNG_DIR, f"spec_{base}.png")
        if not png_path and os.path.exists(p_cand):
            png_path = p_cand

    # Glob fallback if not found directly
    if not fits_path:
        pattern = os.path.join(FITS_DIR, f"pfsObject_*{cat_id}_{obj_id}.fits")
        matches = glob.glob(pattern)
        if matches:
            fits_path = matches[0]

    if not png_path:
        pattern = os.path.join(PNG_DIR, f"spec_*{cat_id}_{obj_id}.png")
        matches = glob.glob(pattern)
        if matches:
            png_path = matches[0]

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
@app.get("/api/stats")
def get_stats():
    """Get repository overview statistics."""
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT count(*) FROM v_target_summary")
        total = cur.fetchone()[0]

        cur.execute("SELECT classificationName, count(*) FROM v_target_summary GROUP BY classificationName")
        class_counts = {row[0] or "UNKNOWN": row[1] for row in cur.fetchall()}

        cur.execute("SELECT count(DISTINCT catId) FROM v_target_summary")
        cat_count = cur.fetchone()[0]

        cur.execute("SELECT catId, count(*) FROM v_target_summary GROUP BY catId ORDER BY catId ASC")
        cat_counts = {int(row[0]): row[1] for row in cur.fetchall()}

        cur.execute("SELECT count(DISTINCT combination) FROM v_target_summary")
        comb_count = cur.fetchone()[0]

        return {
            "total_targets": total,
            "classification_counts": class_counts,
            "catalogs_count": cat_count,
            "cat_ids": cat_counts,
            "combinations_count": comb_count,
            "db_path": DB_PATH,
            "data_dir": DATA_DIR,
        }
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
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    limit: int = Query(25, ge=5, le=100, description="Items per page"),
    sort_by: str = Query("objId", description="Sort field"),
    order: str = Query("asc", description="Sort order (asc, desc)"),
):
    """Search and paginate targets from v_target_summary."""
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

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    conn = get_db()
    cur = conn.cursor()
    try:
        # Count total
        count_sql = f"SELECT count(*) FROM v_target_summary t {where_sql}"
        cur.execute(count_sql, params)
        total = cur.fetchone()[0]

        # Fetch page items
        offset = (page - 1) * limit
        data_sql = f"""
            SELECT 
                t.catId, t.objId, t.combination, t.objGroup,
                t.obCode, t.targetTypeName, t.fiberStatusName, t.ra, t.dec,
                t.classificationName, t.probaGalaxy, t.probaStar, t.probaQSO,
                t.bestRedshift, t.bestRedshiftError, t.bestVelocity, t.bestVelocityError,
                t.bestSubClass, t.hasSolution
            FROM v_target_summary t
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
            fits_file, png_file = find_files(cat_val, obj_val, ob_val)

            d["objId"] = str(d["objId"])
            d["has_fits"] = fits_file is not None
            d["has_png"] = png_file is not None
            d["ra"] = sanitize_val(d.get("ra"))
            d["dec"] = sanitize_val(d.get("dec"))
            d["bestRedshift"] = sanitize_val(d.get("bestRedshift"))
            d["bestRedshiftError"] = sanitize_val(d.get("bestRedshiftError"))
            d["bestVelocity"] = sanitize_val(d.get("bestVelocity"))
            d["bestVelocityError"] = sanitize_val(d.get("bestVelocityError"))
            d["probaGalaxy"] = sanitize_val(d.get("probaGalaxy"))
            d["probaStar"] = sanitize_val(d.get("probaStar"))
            d["probaQSO"] = sanitize_val(d.get("probaQSO"))
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


@app.get("/api/targets/{catId}/{objId}/details")
def get_target_details(catId: int, objId: str):
    """Retrieve full solver, candidate, and line measurement details for a target."""
    conn = get_db()
    cur = conn.cursor()
    try:
        obj_id_int = int(objId)
        # Target summary info
        cur.execute("SELECT * FROM v_target_summary WHERE catId = ? AND objId = ?", (catId, obj_id_int))
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

        fits_file, png_file = find_files(catId, obj_id_int, target_info.get("obCode"))

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
    cur.execute("SELECT obCode FROM v_target_summary WHERE catId = ? AND objId = ?", (catId, obj_id_int))
    row = cur.fetchone()
    conn.close()
    ob_code = row[0] if row else None

    fits_file, _ = find_files(catId, obj_id_int, ob_code)
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
    cur.execute("SELECT obCode FROM v_target_summary WHERE catId = ? AND objId = ?", (catId, obj_id_int))
    row = cur.fetchone()
    conn.close()
    ob_code = row[0] if row else None

    _, png_file = find_files(catId, obj_id_int, ob_code)
    if not png_file or not os.path.exists(png_file):
        raise HTTPException(status_code=404, detail="Spectrum PNG image not found")
    return FileResponse(png_file, media_type="image/png")


@app.get("/api/targets/{catId}/{objId}/fits")
def download_fits(catId: int, objId: str):
    """Download raw FITS file."""
    obj_id_int = int(objId)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT obCode FROM v_target_summary WHERE catId = ? AND objId = ?", (catId, obj_id_int))
    row = cur.fetchone()
    conn.close()
    ob_code = row[0] if row else None

    fits_file, _ = find_files(catId, obj_id_int, ob_code)
    if not fits_file or not os.path.exists(fits_file):
        raise HTTPException(status_code=404, detail="FITS file not found")
    filename = os.path.basename(fits_file)
    return FileResponse(fits_file, media_type="application/fits", filename=filename)


# -----------------------------------------------------------------------------
# Main entry point
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="PFS Target & Spectrum Viewer Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8090, help="Port to listen on (default: 8090)")
    parser.add_argument("--db", default=None, help="Path to pfs_metadata.sqlite3")
    parser.add_argument("--data-dir", default=None, help="Path to extracted_targets directory")
    args = parser.parse_args()

    if args.db:
        DB_PATH = os.path.abspath(args.db)
    if args.data_dir:
        DATA_DIR = os.path.abspath(args.data_dir)
        FITS_DIR = os.path.join(DATA_DIR, "fits")
        PNG_DIR = os.path.join(DATA_DIR, "png")

    print("=" * 65)
    print("  🌌 Starting PFS Target & Spectrum Viewer")
    print(f"  📂 Database: {DB_PATH}")
    print(f"  📁 Data dir: {DATA_DIR}")
    print(f"  🌐 URL:      http://{args.host}:{args.port}")
    print("=" * 65)

    uvicorn.run(app, host=args.host, port=args.port)
