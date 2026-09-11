#!/usr/bin/env python
"""
Extract pfsObject raw data as FITS and plot coadded spectra with
spectral lines (emission / absorption) as PNG for targets in ``v_target_summary``.

Usage
-----
Run via run_pfs.py in the PFS pipeline environment:

    .venv/bin/python run_pfs.py export_pfs_targets.py \\
        --db pfs_metadata.sqlite3 \\
        --outdir ./extracted_targets \\
        --limit 5
"""
import argparse
import os
import sqlite3
import sys
import numpy as np

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from lsst.daf.butler import Butler

# Speed of light in km/s for Doppler conversion of stellar radial velocity
C_KMS = 299792.458

# Rest-frame wavelengths [nm] of commonly used emission/absorption lines
SPECTRAL_LINES = [
    # name, rest wavelength [nm], kind
    ("Ly$\\beta$",      102.57,  "emission"),
    ("Ly$\\alpha$",     121.567, "emission"),
    ("N V",             124.0,   "emission"),
    ("Si IV",           139.7,   "emission"),
    ("C IV",            154.9,   "emission"),
    ("He II",           164.0,   "emission"),
    ("C III]",          190.9,   "emission"),
    ("Mg II",           279.8,   "emission"),
    ("[O II]",          372.7,   "emission"),
    ("Ca II K",         393.4,   "absorption"),
    ("Ca II H",         396.8,   "absorption"),
    ("[Ne III]",        386.9,   "emission"),
    ("H$\\delta$",      410.2,   "emission"),
    ("G-band",          430.5,   "absorption"),
    ("H$\\gamma$",      434.0,   "emission"),
    ("H$\\beta$",       486.1,   "emission"),
    ("[O III]",         495.9,   "emission"),
    ("[O III]",         500.7,   "emission"),
    ("Mg I b",          517.5,   "absorption"),
    ("Na I D",          589.0,   "absorption"),
    ("[O I]",           630.0,   "emission"),
    ("[N II]",          654.8,   "emission"),
    ("H$\\alpha$",      656.3,   "emission"),
    ("[N II]",          658.4,   "emission"),
    ("[S II]",          671.6,   "emission"),
    ("[S II]",          673.1,   "emission"),
    ("Ca II triplet",   849.8,   "absorption"),
    ("Ca II triplet",   854.2,   "absorption"),
    ("Ca II triplet",   866.2,   "absorption"),
]


def bin_spectrum(wavelength, flux, variance, bin_width):
    """
    Bin (wavelength, flux, variance) onto a uniform wavelength grid.
    Points falling in the same bin are combined with inverse-variance weighting.
    """
    wavelength = np.asarray(wavelength)
    flux = np.asarray(flux)
    variance = np.asarray(variance)
    waveMin = np.nanmin(wavelength)
    waveMax = np.nanmax(wavelength)
    edges = np.arange(waveMin, waveMax + bin_width, bin_width)
    binIndex = np.digitize(wavelength, edges) - 1
    nBins = len(edges) - 1
    binWave = np.full(nBins, np.nan)
    binFlux = np.full(nBins, np.nan)
    binVariance = np.full(nBins, np.nan)

    finite = np.isfinite(flux) & np.isfinite(variance) & (variance > 0)
    for i in range(nBins):
        sel = finite & (binIndex == i)
        if not np.any(sel):
            continue
        weight = 1.0 / variance[sel]
        wsum = np.sum(weight)
        binFlux[i] = np.sum(flux[sel] * weight) / wsum
        binVariance[i] = 1.0 / wsum
        binWave[i] = 0.5 * (edges[i] + edges[i + 1])

    valid = np.isfinite(binWave)
    return binWave[valid], binFlux[valid], binVariance[valid]


def plot_spectrum_with_lines(pfsObject, redshift, title=None, out_png=None,
                              bin_width=0.5, label_top_frac=0.92, label_stagger_frac=0.08):
    """
    Plot a PFS coadded spectrum and overlay expected positions of common lines.
    """
    fig, ax = plt.subplots(figsize=(12, 5), dpi=150)
    flags = pfsObject.flags
    bad_mask = flags.get('BAD', 'CR', 'NO_DATA', 'SAT')
    good = ~(pfsObject.mask & bad_mask != 0)

    if bin_width is not None and bin_width > 0:
        waveArr, fluxArr, varArr = bin_spectrum(
            pfsObject.wavelength[good], pfsObject.flux[good], pfsObject.variance[good], bin_width)
        fluxLabel = f'flux (binned {bin_width:g} nm)'
    else:
        waveArr, fluxArr, varArr = pfsObject.wavelength[good], pfsObject.flux[good], pfsObject.variance[good]
        fluxLabel = 'flux'

    ax.plot(waveArr, fluxArr, '-', linewidth=0.6, color='black', label=fluxLabel)
    ax.plot(waveArr, np.sqrt(varArr), '-', linewidth=0.4, color='gray', alpha=0.5, label='noise (1$\\sigma$)')
    if np.any(~good):
        ax.plot(pfsObject.wavelength[~good], pfsObject.flux[~good], '.',
                color='red', alpha=0.3, markersize=2, label='bad pixels')

    if len(fluxArr) > 0 and np.any(np.isfinite(fluxArr)):
        fluxRange = np.nanpercentile(fluxArr[np.isfinite(fluxArr)], (5, 95.))
        ymax = max(fluxRange[1] * 1.5, 1.0)
        ymin = min(fluxRange[0] * 1.1, -ymax * 0.1)
        ax.set_ylim(ymin, ymax)
    else:
        ymax = 100.0
        ax.set_ylim(-10.0, ymax)

    waveMin = np.nanmin(pfsObject.wavelength)
    waveMax = np.nanmax(pfsObject.wavelength)

    if redshift is not None and np.isfinite(redshift):
        for i, (name, restWave, kind) in enumerate(SPECTRAL_LINES):
            obsWave = restWave * (1.0 + redshift)
            if not (waveMin <= obsWave <= waveMax):
                continue
            color = 'tab:blue' if kind == 'emission' else 'tab:red'
            ax.axvline(obsWave, color=color, linewidth=0.8, linestyle='--', alpha=0.7)
            yText = ymax * (label_top_frac if i % 2 == 0 else label_top_frac - label_stagger_frac)
            ax.text(obsWave, yText, name, rotation=90, fontsize=7,
                    color=color, ha='right', va='top',
                    bbox=dict(boxstyle='square,pad=0.1', fc='white', ec='none', alpha=0.6))

    ax.set_xlim(waveMin, waveMax)
    ax.set_xlabel('Wavelength [nm]', fontsize=10)
    ax.set_ylabel('Flux [nJy]', fontsize=10)
    if title:
        ax.set_title(title, fontsize=11)
    ax.grid(True, linestyle=':', alpha=0.4)

    legend_elements = [
        Line2D([0], [0], color='black', lw=1, label=fluxLabel),
        Line2D([0], [0], color='gray', lw=1, alpha=0.5, label='noise (1$\\sigma$)'),
        Line2D([0], [0], marker='.', color='red', lw=0, label='bad pixels'),
        Line2D([0], [0], color='tab:blue', lw=1, linestyle='--', label='emission line'),
        Line2D([0], [0], color='tab:red', lw=1, linestyle='--', label='absorption line'),
    ]
    ax.legend(handles=legend_elements, loc='upper right', fontsize=8, framealpha=0.8)
    plt.tight_layout()

    if out_png:
        plt.savefig(out_png)
    plt.close(fig)


def fetch_targets_from_db(conn, args):
    """
    Query target rows from v_target_summary or fallback to targets table.
    """
    cur = conn.cursor()

    # Check if v_target_summary exists
    cur.execute("SELECT name FROM sqlite_master WHERE type='view' AND name='v_target_summary'")
    has_view = cur.fetchone() is not None

    where_clauses = []
    params = []

    if args.cat_id is not None:
        where_clauses.append("t.catId = ?")
        params.append(args.cat_id)
    if args.obj_id is not None:
        where_clauses.append("t.objId = ?")
        params.append(args.obj_id)
    if args.combination is not None:
        where_clauses.append("t.combination = ?")
        params.append(args.combination)
    if args.classification is not None:
        where_clauses.append("t.classificationName = ?")
        params.append(args.classification.upper())
    if args.min_z is not None:
        where_clauses.append("t.bestRedshift >= ?")
        params.append(args.min_z)
    if args.max_z is not None:
        where_clauses.append("t.bestRedshift <= ?")
        params.append(args.max_z)

    if has_view:
        if args.ob_code is not None:
            where_clauses.append("t.obCode LIKE ?")
            params.append(args.ob_code)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        query = f"""
        SELECT 
            t.catId, t.objId, t.combination, t.objGroup,
            t.obCode, t.targetTypeName, t.fiberStatusName, t.ra, t.dec,
            t.classificationName, t.probaGalaxy, t.probaStar, t.probaQSO,
            t.bestRedshift, t.bestRedshiftError, t.bestVelocity, t.bestVelocityError,
            t.bestSubClass, t.hasSolution
        FROM v_target_summary t
        {where_sql}
        ORDER BY t.catId, t.combination, t.objGroup, t.objId
        """
    else:
        # Fallback if view does not exist
        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        query = f"""
        SELECT 
            t.catId, t.objId, t.combination, t.objGroup,
            NULL AS obCode, NULL AS targetTypeName, NULL AS fiberStatusName, NULL AS ra, NULL AS dec,
            t.classificationName, t.probaGalaxy, t.probaStar, t.probaQSO,
            NULL AS bestRedshift, NULL AS bestRedshiftError, NULL AS bestVelocity, NULL AS bestVelocityError,
            NULL AS bestSubClass, t.hasSolution
        FROM targets t
        {where_sql}
        ORDER BY t.catId, t.combination, t.objGroup, t.objId
        """

    if args.limit is not None:
        query += f" LIMIT {args.limit}"

    cur.execute(query, params)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in rows]


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default="/mnt/ugnas/work/LSST/PFS/S26A-104/2d",
                        help="Butler repository root")
    parser.add_argument("--collections", nargs="+",
                        default=["run28_August2026", "run28_August2026/lam1d_modified"],
                        help="Butler collections to search")
    parser.add_argument("--db", default="pfs_metadata.sqlite3",
                        help="SQLite database file")
    parser.add_argument("--outdir", default="./extracted_targets",
                        help="Output directory for FITS and PNG files")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit number of targets to process")
    parser.add_argument("--cat-id", type=int, default=None,
                        help="Filter by catId")
    parser.add_argument("--obj-id", type=int, default=None,
                        help="Filter by objId")
    parser.add_argument("--ob-code", default=None,
                        help="Filter by obCode (supports SQL LIKE patterns, e.g. 'rubin_%%')")
    parser.add_argument("--combination", default=None,
                        help="Filter by combination")
    parser.add_argument("--classification", default=None,
                        help="Filter by classificationName (GALAXY, QSO, STAR)")
    parser.add_argument("--min-z", type=float, default=None,
                        help="Filter by minimum bestRedshift")
    parser.add_argument("--max-z", type=float, default=None,
                        help="Filter by maximum bestRedshift")
    parser.add_argument("--bin-width", type=float, default=0.5,
                        help="Wavelength bin width [nm] for plot (0 to disable binning)")
    parser.add_argument("--skip-fits", action="store_true",
                        help="Skip saving FITS raw data")
    parser.add_argument("--skip-png", action="store_true",
                        help="Skip generating PNG spectrum plots")
    parser.add_argument("--fits-naming", choices=["custom", "standard"], default="custom",
                        help="FITS filename format: 'custom' (pfsObject_{catId}_{objId}.fits) or 'standard' (pfsObject-10356-00001-...)")
    parser.add_argument("--overwrite", action="store_true",
                        help="Overwrite existing output files")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    fits_dir = os.path.join(args.outdir, "fits")
    png_dir = os.path.join(args.outdir, "png")
    if not args.skip_fits:
        os.makedirs(fits_dir, exist_ok=True)
    if not args.skip_png:
        os.makedirs(png_dir, exist_ok=True)

    if not os.path.exists(args.db):
        print(f"Error: Database {args.db} not found.", file=sys.stderr)
        sys.exit(1)

    print(f"Connecting to database: {args.db}")
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    targets = fetch_targets_from_db(conn, args)
    conn.close()

    print(f"Found {len(targets)} targets matching criteria.")
    if len(targets) == 0:
        print("No targets to process. Exiting.")
        return

    print(f"Initializing Butler: repo={args.repo}, collections={args.collections}")
    butler = Butler(args.repo, collections=args.collections)

    current_group_key = None
    pfsCoadd = None
    target_map = {}

    processed_count = 0
    fits_count = 0
    png_count = 0

    for i, tinfo in enumerate(targets):
        catId = tinfo["catId"]
        objId = tinfo["objId"]
        combination = tinfo["combination"]
        objGroup = tinfo["objGroup"]
        obCode = tinfo.get("obCode") or ""
        cname = tinfo.get("classificationName") or "UNKNOWN"
        bestZ = tinfo.get("bestRedshift")
        bestV = tinfo.get("bestVelocity")
        bestSubClass = tinfo.get("bestSubClass") or ""

        # Determine effective redshift for line plotting
        if cname == "STAR" and bestV is not None and np.isfinite(bestV):
            eff_z = bestV / C_KMS
            z_label = f"v={bestV:.1f} km/s (z={eff_z:.5f})"
        elif bestZ is not None and np.isfinite(bestZ):
            eff_z = bestZ
            z_label = f"z={bestZ:.4f}"
        else:
            eff_z = None
            z_label = "z=N/A"

        # Load pfsCoadd for this group if changed
        group_key = (catId, combination, objGroup)
        if group_key != current_group_key:
            current_group_key = group_key
            dataId = {"cat_id": catId, "combination": combination, "obj_group": objGroup}
            print(f"\nLoading pfsCoadd for group: {dataId}")
            try:
                pfsCoadd = butler.get("pfsCoadd", dataId)
                target_map = {t.objId: t for t in pfsCoadd.keys()}
            except Exception as e:
                print(f"  Warning: Failed to load pfsCoadd for {dataId}: {e}", file=sys.stderr)
                pfsCoadd = None
                target_map = {}

        if pfsCoadd is None or objId not in target_map:
            print(f"  [{i + 1}/{len(targets)}] objId={objId} not found in pfsCoadd group {group_key}. Skipping.")
            continue

        target = target_map[objId]
        pfsObj = pfsCoadd[target]

        base_name = f"{obCode}_{catId}_{objId}" if obCode else f"{catId}_{objId}"
        # Sanitize filename
        safe_base_name = "".join(c if (c.isalnum() or c in "._-") else "_" for c in base_name)

        # 1. Save FITS
        if not args.skip_fits:
            if args.fits_naming == "standard":
                pfsObj.write(fits_dir)
                fits_count += 1
            else:
                fits_path = os.path.join(fits_dir, f"pfsObject_{safe_base_name}.fits")
                if args.overwrite or not os.path.exists(fits_path):
                    pfsObj.writeFits(fits_path)
                    fits_count += 1

        # 2. Save PNG
        if not args.skip_png:
            png_path = os.path.join(png_dir, f"spec_{safe_base_name}.png")
            if args.overwrite or not os.path.exists(png_path):
                title_parts = [f"objId: {objId}"]
                if obCode:
                    title_parts.append(f"obCode: {obCode}")
                title_parts.append(f"catId: {catId}")
                title_parts.append(f"class: {cname}")
                title_parts.append(z_label)
                if bestSubClass:
                    title_parts.append(f"subClass: {bestSubClass}")
                title = " | ".join(title_parts)

                plot_spectrum_with_lines(
                    pfsObj,
                    redshift=eff_z,
                    title=title,
                    out_png=png_path,
                    bin_width=args.bin_width if args.bin_width > 0 else None,
                )
                png_count += 1

        processed_count += 1
        if (i + 1) % 10 == 0 or (i + 1) == len(targets):
            print(f"  Processed [{i + 1}/{len(targets)}] targets (FITS: {fits_count}, PNG: {png_count})")

    print("\n" + "=" * 60)
    print(f"Finished. Total processed: {processed_count} targets")
    if not args.skip_fits:
        print(f"  FITS files saved to: {fits_dir} ({fits_count} files)")
    if not args.skip_png:
        print(f"  PNG spectra saved to: {png_dir} ({png_count} files)")
    print("=" * 60)


if __name__ == "__main__":
    main()
