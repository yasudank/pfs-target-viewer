#!/usr/bin/env python3
"""
Extract and store per-target coadd observation metadata (visits, MJD, arms,
per-arm coverage & S/N, fiber offset) in ``pfs_metadata.sqlite3``.

Used both live during ``export_pfs_targets.py`` (from in-memory ``pfsObject``)
and as a standalone backfill tool on existing ``pfs_metadata.sqlite3`` databases
that already have exported ``pfsObject_*.fits`` files.

Usage (backfill existing DB):
    python3 fits_metadata.py --db /path/to/pfs_metadata.sqlite3 [--only-missing] [--workers 8]
"""

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import os
import sqlite3
import sys
import time

import numpy as np

# New columns added to target_summary (all nullable for backward compatibility)
FITS_SUMMARY_COLUMNS = [
    ("mjd_first", "REAL"),
    ("mjd_last", "REAL"),
    ("mjd_mean", "REAL"),
    ("n_nights", "INTEGER"),
    ("arms", "TEXT"),
    ("cov_b", "REAL"),
    ("cov_r", "REAL"),
    ("cov_n", "REAL"),
    ("snr_b", "REAL"),
    ("snr_r", "REAL"),
    ("snr_n", "REAL"),
    ("fiber_offset_mm", "REAL"),
]

FITS_SUMMARY_COL_NAMES = [c for c, _ in FITS_SUMMARY_COLUMNS]

TARGET_VISITS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS target_visits (
    catId INTEGER NOT NULL,
    objId INTEGER NOT NULL,
    combination TEXT NOT NULL,
    visit INTEGER NOT NULL,
    arm TEXT NOT NULL DEFAULT '',
    spectrograph INTEGER,
    fiberId INTEGER,
    obsTime TEXT,
    mjd REAL,
    expTime REAL,
    pfiOffsetMm REAL,
    PRIMARY KEY (catId, objId, combination, visit, arm)
);
CREATE INDEX IF NOT EXISTS idx_target_visits_target ON target_visits (catId, objId, combination);
CREATE INDEX IF NOT EXISTS idx_target_visits_visit ON target_visits (visit);
CREATE INDEX IF NOT EXISTS idx_target_visits_mjd ON target_visits (mjd);
"""

# Nominal PFS arm wavelength windows [nm] (b: 380-650, r/m: 630-970, n: 940-1260)
ARM_BANDS_NM = (
    ("b", 380.0, 650.0),
    ("r", 630.0, 970.0),
    ("n", 940.0, 1260.0),
)


def _iso_to_mjd_utc(ts: str) -> float | None:
    """Fast ISO-8601 UTC string -> MJD (UTC) without astropy overhead."""
    if not ts:
        return None
    s = str(ts).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    # Trim sub-microsecond nanoseconds (e.g. '2026-11-03T12:59:10.854939698')
    if s.endswith("Z"):
        s = s[:-1]
    if "." in s:
        head, frac = s.split(".", 1)
        frac = "".join(ch for ch in frac if ch.isdigit())[:6]
        s = f"{head}.{frac}" if frac else head
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp() / 86400.0 + 40587.0
    except Exception:
        return None


def ensure_fits_metadata_schema(conn: sqlite3.Connection) -> None:
    """Create ``target_visits`` and add missing FITS metadata columns to ``target_summary``."""
    cur = conn.cursor()
    cur.executescript(TARGET_VISITS_SCHEMA_SQL)
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='target_summary'")
    if cur.fetchone() is not None:
        cur.execute("PRAGMA table_info(target_summary)")
        existing = {row[1] for row in cur.fetchall()}
        for col, col_type in FITS_SUMMARY_COLUMNS:
            if col not in existing:
                cur.execute(f"ALTER TABLE target_summary ADD COLUMN {col} {col_type}")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ts_mjd_mean ON target_summary (mjd_mean)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ts_snr_r ON target_summary (snr_r)")
    conn.commit()


def compute_arm_stats(wave_nm: np.ndarray, flux: np.ndarray, variance: np.ndarray,
                      good_mask: np.ndarray) -> dict:
    """Compute per-arm valid pixel fraction (cov_b/r/n) and median S/N (snr_b/r/n)."""
    out = {f"cov_{k}": None for k, _, _ in ARM_BANDS_NM}
    out.update({f"snr_{k}": None for k, _, _ in ARM_BANDS_NM})
    if wave_nm is None or len(wave_nm) == 0:
        return out
    wave = np.asarray(wave_nm, dtype=float)
    flx = np.asarray(flux, dtype=float)
    var = np.asarray(variance, dtype=float)
    good = np.asarray(good_mask, dtype=bool) & np.isfinite(flx) & np.isfinite(var) & (var > 0)
    for k, lo, hi in ARM_BANDS_NM:
        in_band = (wave >= lo) & (wave <= hi)
        n_band = int(in_band.sum())
        if n_band == 0:
            continue
        ok = in_band & good
        n_ok = int(ok.sum())
        out[f"cov_{k}"] = round(n_ok / n_band, 4)
        if n_ok >= 10:
            snr = flx[ok] / np.sqrt(var[ok])
            out[f"snr_{k}"] = round(float(np.median(snr)), 3)
    return out


def _pfi_offset_mm(nom, cen) -> float | None:
    if nom is None or cen is None:
        return None
    try:
        a = np.asarray(nom, dtype=float).ravel()
        b = np.asarray(cen, dtype=float).ravel()
        if a.size >= 2 and b.size >= 2 and np.all(np.isfinite(a[:2])) and np.all(np.isfinite(b[:2])):
            return round(float(np.hypot(b[0] - a[0], b[1] - a[1])), 5)
    except Exception:
        pass
    return None


def summarize_observations(catId: int, objId: int, combination: str, raw_obs: list[dict],
                           visit_exptime: dict | None = None,
                           use_visit_exptime: bool = False) -> tuple[dict, list[dict]]:
    """Summarize observation rows into target_summary fields and target_visits rows."""
    vt = visit_exptime or {}
    # Deduplicate by (visit, arm) keeping earliest obsTime and largest expTime
    dedup = {}
    for row in raw_obs:
        v = int(row["visit"])
        arm = str(row.get("arm") or "").strip()
        key = (v, arm)
        ot = str(row.get("obsTime") or "").strip()
        exp = row.get("expTime")
        if use_visit_exptime and vt.get(v) is not None:
            exp = float(vt[v])
        elif exp is not None:
            try:
                exp = float(exp)
                if not np.isfinite(exp):
                    exp = None
            except Exception:
                exp = None
        spec = row.get("spectrograph")
        spec = int(spec) if spec is not None and np.isfinite(float(spec)) else None
        fid = row.get("fiberId")
        fid = int(fid) if fid is not None and np.isfinite(float(fid)) else None
        off = _pfi_offset_mm(row.get("pfiNominal"), row.get("pfiCenter"))
        mjd = _iso_to_mjd_utc(ot)
        cur = dedup.get(key)
        if cur is None:
            dedup[key] = dict(
                catId=int(catId), objId=int(objId), combination=str(combination),
                visit=v, arm=arm, spectrograph=spec, fiberId=fid,
                obsTime=ot or None, mjd=mjd, expTime=exp, pfiOffsetMm=off,
            )
        else:
            if ot and (not cur["obsTime"] or ot < cur["obsTime"]):
                cur["obsTime"] = ot
                cur["mjd"] = mjd
            if exp is not None and (cur["expTime"] is None or exp > cur["expTime"]):
                cur["expTime"] = exp
            if cur["pfiOffsetMm"] is None and off is not None:
                cur["pfiOffsetMm"] = off

    visit_rows = [dedup[k] for k in sorted(dedup.keys())]

    # Aggregate per unique visit for mjd_first / mjd_last / mjd_mean / n_nights / arms / fiber_offset_mm
    by_visit = {}
    arm_chars = set()
    offsets = []
    for r in visit_rows:
        for ch in r["arm"]:
            if ch.isalpha():
                arm_chars.add(ch)
        if r["pfiOffsetMm"] is not None:
            offsets.append(r["pfiOffsetMm"])
        v = r["visit"]
        bv = by_visit.get(v)
        if bv is None:
            by_visit[v] = dict(obsTime=r["obsTime"], mjd=r["mjd"], expTime=r["expTime"])
        else:
            if r["obsTime"] and (not bv["obsTime"] or r["obsTime"] < bv["obsTime"]):
                bv["obsTime"] = r["obsTime"]
                bv["mjd"] = r["mjd"]
            if r["expTime"] is not None and (bv["expTime"] is None or r["expTime"] > bv["expTime"]):
                bv["expTime"] = r["expTime"]

    mjds = []
    mjd_mids = []
    weights = []
    nights = set()
    for bv in by_visit.values():
        if bv["obsTime"] and len(bv["obsTime"]) >= 10:
            nights.add(bv["obsTime"][:10])
        if bv["mjd"] is not None:
            exp = bv["expTime"] if (bv["expTime"] is not None and bv["expTime"] > 0) else 0.0
            mjds.append(bv["mjd"])
            mjd_mids.append(bv["mjd"] + 0.5 * exp / 86400.0)
            weights.append(exp if exp > 0 else 1.0)

    summary = dict(
        mjd_first=round(min(mjds), 6) if mjds else None,
        mjd_last=round(max(mjds), 6) if mjds else None,
        mjd_mean=round(float(np.average(mjd_mids, weights=weights)), 6) if mjd_mids else None,
        n_nights=len(nights) if nights else None,
        arms="".join(sorted(arm_chars)) if arm_chars else None,
        fiber_offset_mm=round(float(np.median(offsets)), 5) if offsets else None,
    )
    return summary, visit_rows


def extract_from_pfsobject(pfsObj, catId: int, objId: int, combination: str,
                           visit_exptime: dict | None = None,
                           use_visit_exptime: bool = False) -> tuple[dict, list[dict]]:
    """Extract summary metadata + target_visits rows from an in-memory pfsObject."""
    # 1. Per-arm coverage & S/N
    flags = getattr(pfsObj, "flags", None)
    bad_mask = flags.get("BAD", "CR", "NO_DATA", "SAT") if flags is not None else 0
    mask = getattr(pfsObj, "mask", None)
    good = (mask & bad_mask) == 0 if mask is not None else np.ones(len(pfsObj.wavelength), dtype=bool)
    arm_stats = compute_arm_stats(pfsObj.wavelength, pfsObj.flux, pfsObj.variance, good)

    # 2. Observations
    raw_obs = []
    obs = getattr(pfsObj, "observations", None)
    if obs is not None:
        visits = getattr(obs, "visit", None)
        if visits is not None and len(visits) > 0:
            n = len(visits)
            arms = getattr(obs, "arm", [""] * n)
            specs = getattr(obs, "spectrograph", [None] * n)
            fids = getattr(obs, "fiberId", [None] * n)
            ots = getattr(obs, "obsTime", [""] * n)
            exps = getattr(obs, "expTime", [None] * n)
            noms = getattr(obs, "pfiNominal", [None] * n)
            cens = getattr(obs, "pfiCenter", [None] * n)
            for i in range(n):
                raw_obs.append(dict(
                    visit=visits[i],
                    arm=arms[i] if i < len(arms) else "",
                    spectrograph=specs[i] if specs is not None and i < len(specs) else None,
                    fiberId=fids[i] if fids is not None and i < len(fids) else None,
                    obsTime=ots[i] if ots is not None and i < len(ots) else "",
                    expTime=exps[i] if exps is not None and i < len(exps) else None,
                    pfiNominal=noms[i] if noms is not None and i < len(noms) else None,
                    pfiCenter=cens[i] if cens is not None and i < len(cens) else None,
                ))

    obs_summary, visit_rows = summarize_observations(
        catId, objId, combination, raw_obs,
        visit_exptime=visit_exptime, use_visit_exptime=use_visit_exptime,
    )
    return {**obs_summary, **arm_stats}, visit_rows


def extract_from_fits(fits_path: str, catId: int, objId: int, combination: str,
                      visit_exptime: dict | None = None,
                      use_visit_exptime: bool = False) -> tuple[dict, list[dict]]:
    """Extract summary metadata + target_visits rows from an exported pfsObject FITS file."""
    from astropy.io import fits

    with fits.open(fits_path, memmap=False) as hdul:
        wave = hdul["WAVELENGTH"].data
        flux = hdul["FLUX"].data
        covar = hdul["COVAR"].data
        if covar is not None and covar.ndim == 2:
            var = covar[0] if covar.shape[1] == len(wave) else covar[:, 0]
        else:
            var = covar
        mask = hdul["MASK"].data
        # Default PFS bad mask bits: NO_DATA(0), BAD(1), SAT(2), CR(3) -> read from MASK header if available
        mh = hdul["MASK"].header
        bad_bits = 0
        for name in ("NO_DATA", "BAD", "SAT", "CR"):
            for k, v in mh.items():
                if k.startswith("MP_") and str(v).strip() == name:
                    try:
                        bad_bits |= (1 << int(k[3:]))
                    except ValueError:
                        pass
        if bad_bits == 0:
            bad_bits = 0x0F
        good = (mask & bad_bits) == 0 if mask is not None else np.ones(len(wave), dtype=bool)
        arm_stats = compute_arm_stats(wave, flux, var, good)

        raw_obs = []
        if "OBSERVATIONS" in hdul and hdul["OBSERVATIONS"].data is not None:
            otbl = hdul["OBSERVATIONS"].data
            names = set(otbl.columns.names)
            for row in otbl:
                raw_obs.append(dict(
                    visit=row["visit"],
                    arm=row["arm"] if "arm" in names else "",
                    spectrograph=row["spectrograph"] if "spectrograph" in names else None,
                    fiberId=row["fiberId"] if "fiberId" in names else None,
                    obsTime=row["obsTime"] if "obsTime" in names else "",
                    expTime=row["expTime"] if "expTime" in names else None,
                    pfiNominal=row["pfiNominal"] if "pfiNominal" in names else None,
                    pfiCenter=row["pfiCenter"] if "pfiCenter" in names else None,
                ))

    obs_summary, visit_rows = summarize_observations(
        catId, objId, combination, raw_obs,
        visit_exptime=visit_exptime, use_visit_exptime=use_visit_exptime,
    )
    return {**obs_summary, **arm_stats}, visit_rows


def write_target_visits(conn: sqlite3.Connection, target_keys: list[tuple], visit_rows: list[dict]) -> None:
    """Replace target_visits rows for the given (catId, objId, combination) keys."""
    if not target_keys:
        return
    cur = conn.cursor()
    cur.executemany(
        "DELETE FROM target_visits WHERE catId = ? AND objId = ? AND combination = ?",
        target_keys,
    )
    if visit_rows:
        cur.executemany(
            """
            INSERT OR REPLACE INTO target_visits (
                catId, objId, combination, visit, arm, spectrograph, fiberId,
                obsTime, mjd, expTime, pfiOffsetMm
            ) VALUES (
                :catId, :objId, :combination, :visit, :arm, :spectrograph, :fiberId,
                :obsTime, :mjd, :expTime, :pfiOffsetMm
            )
            """,
            visit_rows,
        )


def _backfill_worker(task):
    fits_path, catId, objId, combination, visit_exptime, use_visit_exptime = task
    if not os.path.exists(fits_path):
        return None
    try:
        meta, vrows = extract_from_fits(
            fits_path, catId, objId, combination,
            visit_exptime=visit_exptime, use_visit_exptime=use_visit_exptime,
        )
        rec = dict(catId=catId, objId=objId, combination=combination, **meta)
        return rec, vrows
    except Exception as e:
        return ("error", fits_path, str(e))


def main():
    ap = argparse.ArgumentParser(description="Backfill target_visits and FITS metadata columns in pfs_metadata.sqlite3")
    ap.add_argument("--db", default="pfs_metadata.sqlite3", help="Path to pfs_metadata.sqlite3")
    ap.add_argument("--fits-base", default=None,
                    help="Base directory for relative fits_path entries (default: <db_dir>/extracted_targets)")
    ap.add_argument("--only-missing", action="store_true", help="Only process rows where mjd_mean IS NULL")
    ap.add_argument("--workers", type=int, default=8, help="Parallel worker processes")
    args = ap.parse_args()

    db_path = os.path.abspath(args.db)
    if not os.path.exists(db_path):
        sys.exit(f"Database not found: {db_path}")
    fits_base = args.fits_base or os.path.join(os.path.dirname(db_path), "extracted_targets")

    t0 = time.time()
    conn = sqlite3.connect(db_path)
    ensure_fits_metadata_schema(conn)
    cur = conn.cursor()

    # Load visits.exptime if present (used for QL combination='ql' where FITS expTime sums across cameras)
    cur.execute("PRAGMA table_info(visits)")
    vcols = {r[1] for r in cur.fetchall()}
    visit_exptime = {}
    if "exptime" in vcols:
        visit_exptime = {int(v): float(e) for v, e in cur.execute(
            "SELECT visit, exptime FROM visits WHERE exptime IS NOT NULL")}

    where = "WHERE has_fits = 1 AND fits_path IS NOT NULL"
    if args.only_missing:
        where += " AND mjd_mean IS NULL"
    rows = cur.execute(f"SELECT catId, objId, combination, fits_path FROM target_summary {where}").fetchall()
    print(f"Found {len(rows):,} target(s) with FITS in {db_path}")
    if not rows:
        conn.close()
        return

    tasks = []
    for catId, objId, comb, fpath in rows:
        full = fpath if os.path.isabs(fpath) else os.path.join(fits_base, fpath)
        tasks.append((full, int(catId), int(objId), str(comb), visit_exptime, str(comb) == "ql"))

    recs, all_vrows, keys = [], [], []
    n_err = 0
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as ex:
        for i, res in enumerate(ex.map(_backfill_worker, tasks, chunksize=32), 1):
            if res is None:
                continue
            if isinstance(res, tuple) and len(res) == 3 and res[0] == "error":
                n_err += 1
                if n_err <= 5:
                    print(f"  warning: {res[1]}: {res[2]}", file=sys.stderr)
                continue
            rec, vrows = res
            recs.append(rec)
            all_vrows.extend(vrows)
            keys.append((rec["catId"], rec["objId"], rec["combination"]))
            if i % 5000 == 0 or i == len(tasks):
                print(f"  processed {i:,}/{len(tasks):,} ({len(recs):,} ok, {n_err} errors)", flush=True)

    set_clause = ", ".join(f"{c} = :{c}" for c in FITS_SUMMARY_COL_NAMES)
    cur.executemany(
        f"UPDATE target_summary SET {set_clause} WHERE catId = :catId AND objId = :objId AND combination = :combination",
        recs,
    )
    write_target_visits(conn, keys, all_vrows)
    conn.commit()
    conn.close()
    print(f"Updated {len(recs):,} target_summary rows and {len(all_vrows):,} target_visits rows in {time.time() - t0:.1f}s.")


if __name__ == "__main__":
    main()
