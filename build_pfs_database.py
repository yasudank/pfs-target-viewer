#!/usr/bin/env python
"""
Expand ``pfsConfig`` and ``pfsCoZCandidates`` datasets from a Gen3 Butler
repository into a relational SQLite database.

Tables & Views created
----------------------
visits              one row per visit (design-level pfsConfig metadata)
fiber_configs       one row per (visit, fiberId) (per-fiber pfsConfig entry: ra, dec, obCode, targetType, fiberStatus)
coadd_groups        one row per (catId, combination, objGroup) coadd group
targets             one row per (catId, objId, combination): classification result, proba, bestRedshift, bestVelocity
solver_results      one row per (catId, objId, combination, objectType): solver
                     warnings/errors for the galaxy/qso/star redshift solvers
redshift_candidates one row per (catId, objId, combination, objectType, cRank):
                     the fitted parameters for each candidate solution
line_measurements   one row per (catId, objId, combination, objectType, lineName):
                     emission/absorption line measurements
v_target_summary    VIEW combining target classification, best-fit redshift/velocity, and fiber coordinates/obCode

Usage
-----
Must be run inside the PFS pipeline environment, e.g.:

    .venv/bin/python run_pfs.py build_pfs_database.py \\
        --repo /mnt/ugnas/work/LSST/PFS/S26A-104/2d \\
        --collections run28_August2026 run28_August2026/lam1d_modified \\
        --db pfs_metadata.sqlite3
"""
import argparse
import sqlite3

import numpy as np
from astropy.table import Row
from lsst.daf.butler import Butler
from pfs.datamodel import TargetType, FiberStatus


SCHEMA = """
CREATE TABLE IF NOT EXISTS visits (
    visit INTEGER PRIMARY KEY,
    pfsDesignId INTEGER,
    designName TEXT,
    raBoresight REAL,
    decBoresight REAL,
    posAng REAL,
    arms TEXT,
    obstime TEXT,
    obstimeDesign TEXT,
    camMask INTEGER,
    instStatusFlag INTEGER,
    visit0 INTEGER
);

CREATE TABLE IF NOT EXISTS fiber_configs (
    visit INTEGER NOT NULL,
    fiberId INTEGER NOT NULL,
    cobraId INTEGER,
    tract INTEGER,
    patch TEXT,
    ra REAL,
    dec REAL,
    catId INTEGER,
    objId INTEGER,
    targetType INTEGER,
    targetTypeName TEXT,
    fiberStatus INTEGER,
    fiberStatusName TEXT,
    epoch TEXT,
    pmRa REAL,
    pmDec REAL,
    parallax REAL,
    proposalId TEXT,
    obCode TEXT,
    pfiNominalX REAL,
    pfiNominalY REAL,
    pfiCenterX REAL,
    pfiCenterY REAL,
    cobraTheta REAL,
    cobraPhi REAL,
    PRIMARY KEY (visit, fiberId),
    FOREIGN KEY (visit) REFERENCES visits (visit)
);
CREATE INDEX IF NOT EXISTS idx_fiber_configs_catid_objid ON fiber_configs (catId, objId);

CREATE TABLE IF NOT EXISTS coadd_groups (
    catId INTEGER NOT NULL,
    combination TEXT NOT NULL,
    objGroup INTEGER NOT NULL,
    nTargets INTEGER,
    PRIMARY KEY (catId, combination, objGroup)
);

CREATE TABLE IF NOT EXISTS targets (
    catId INTEGER NOT NULL,
    objId INTEGER NOT NULL,
    combination TEXT NOT NULL,
    objGroup INTEGER,
    tract INTEGER,
    patch TEXT,
    hasSolution INTEGER,
    initErrorCode TEXT,
    initErrorMessage TEXT,
    initWarningValue INTEGER,
    initWarningName TEXT,
    classificationName TEXT,
    probaGalaxy REAL,
    probaStar REAL,
    probaQSO REAL,
    classificationErrorCode TEXT,
    classificationWarningValue INTEGER,
    classificationWarningName TEXT,
    bestRedshift REAL,
    bestRedshiftError REAL,
    bestVelocity REAL,
    bestVelocityError REAL,
    bestSubClass TEXT,
    nvisit INTEGER,
    exptime REAL,
    PRIMARY KEY (catId, objId, combination),
    FOREIGN KEY (catId, combination, objGroup) REFERENCES coadd_groups (catId, combination, objGroup)
);
CREATE INDEX IF NOT EXISTS idx_targets_classification ON targets (classificationName);
CREATE INDEX IF NOT EXISTS idx_targets_best_redshift ON targets (bestRedshift);
CREATE INDEX IF NOT EXISTS idx_targets_nvisit ON targets (nvisit);
CREATE INDEX IF NOT EXISTS idx_targets_exptime ON targets (exptime);
CREATE INDEX IF NOT EXISTS idx_fiber_configs_obcode ON fiber_configs (obCode);

CREATE TABLE IF NOT EXISTS solver_results (
    catId INTEGER NOT NULL,
    objId INTEGER NOT NULL,
    combination TEXT NOT NULL,
    objectType TEXT NOT NULL,
    nCandidates INTEGER,
    zWarningValue INTEGER,
    zWarningName TEXT,
    zErrorCode TEXT,
    zErrorMessage TEXT,
    lWarningValue INTEGER,
    lWarningName TEXT,
    lErrorCode TEXT,
    lErrorMessage TEXT,
    PRIMARY KEY (catId, objId, combination, objectType),
    FOREIGN KEY (catId, objId, combination) REFERENCES targets (catId, objId, combination)
);

CREATE TABLE IF NOT EXISTS redshift_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    catId INTEGER NOT NULL,
    objId INTEGER NOT NULL,
    combination TEXT NOT NULL,
    objectType TEXT NOT NULL,
    cRank INTEGER,
    targetId INTEGER,
    modelId INTEGER,
    redshift REAL,
    redshiftError REAL,
    redshiftProba REAL,
    velocity REAL,
    velocityError REAL,
    velocityProba REAL,
    subClass TEXT,
    continuumFile TEXT,
    templateFile TEXT,
    lineCatalogRatioFile TEXT,
    emissionVelocity REAL,
    absorptionVelocity REAL,
    continuumReducedLeastSquare REAL,
    continuumPValue REAL,
    continuumResidualsMean REAL,
    continuumResidualsStd REAL,
    continuumResidualsSkewness REAL,
    continuumResidualsKurtosis REAL,
    continuumResidualsKs REAL,
    continuumResidualsKsStd REAL,
    continuumResidualsKsStdMean REAL,
    continuumResidualsAnderson REAL,
    reducedLeastSquare REAL,
    pValue REAL,
    residualsMean REAL,
    residualsStd REAL,
    residualsSkewness REAL,
    residualsKurtosis REAL,
    residualsKs REAL,
    residualsKsStd REAL,
    residualsKsStdMean REAL,
    residualsAnderson REAL,
    UNIQUE (catId, objId, combination, objectType, cRank),
    FOREIGN KEY (catId, objId, combination) REFERENCES targets (catId, objId, combination)
);
CREATE INDEX IF NOT EXISTS idx_redshift_candidates_target
    ON redshift_candidates (catId, objId, combination);

CREATE TABLE IF NOT EXISTS line_measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    catId INTEGER NOT NULL,
    objId INTEGER NOT NULL,
    combination TEXT NOT NULL,
    objectType TEXT NOT NULL,
    lineName TEXT,
    lineWave REAL,
    lineZ REAL,
    lineZError REAL,
    lineSigma REAL,
    lineSigmaError REAL,
    lineVelocity REAL,
    lineVelocityError REAL,
    lineFlux REAL,
    lineFluxError REAL,
    lineEW REAL,
    lineEWError REAL,
    lineContinuumLevel REAL,
    lineContinuumLevelError REAL,
    UNIQUE (catId, objId, combination, objectType, lineName),
    FOREIGN KEY (catId, objId, combination) REFERENCES targets (catId, objId, combination)
);
CREATE INDEX IF NOT EXISTS idx_line_measurements_target
    ON line_measurements (catId, objId, combination);
CREATE INDEX IF NOT EXISTS idx_line_measurements_lineName
    ON line_measurements (lineName);

CREATE TABLE IF NOT EXISTS target_summary (
    catId INTEGER NOT NULL,
    objId INTEGER NOT NULL,
    combination TEXT NOT NULL,
    objGroup INTEGER,
    obCode TEXT,
    targetTypeName TEXT,
    fiberStatusName TEXT,
    ra REAL,
    dec REAL,
    classificationName TEXT,
    probaGalaxy REAL,
    probaStar REAL,
    probaQSO REAL,
    bestRedshift REAL,
    bestRedshiftError REAL,
    bestVelocity REAL,
    bestVelocityError REAL,
    bestSubClass TEXT,
    hasSolution INTEGER,
    nvisit INTEGER,
    exptime REAL,
    has_fits INTEGER DEFAULT 0,
    fits_path TEXT,
    has_png INTEGER DEFAULT 0,
    png_path TEXT,
    PRIMARY KEY (catId, objId, combination)
);
CREATE INDEX IF NOT EXISTS idx_ts_classification ON target_summary (classificationName);
CREATE INDEX IF NOT EXISTS idx_ts_best_redshift ON target_summary (bestRedshift);
CREATE INDEX IF NOT EXISTS idx_ts_obcode ON target_summary (obCode);
CREATE INDEX IF NOT EXISTS idx_ts_catid ON target_summary (catId);
CREATE INDEX IF NOT EXISTS idx_ts_coords ON target_summary (ra, dec);
CREATE INDEX IF NOT EXISTS idx_ts_nvisit ON target_summary (nvisit);
CREATE INDEX IF NOT EXISTS idx_ts_exptime ON target_summary (exptime);
CREATE INDEX IF NOT EXISTS idx_ts_has_fits ON target_summary (has_fits);
CREATE INDEX IF NOT EXISTS idx_ts_has_png ON target_summary (has_png);

CREATE VIEW IF NOT EXISTS v_target_summary AS SELECT * FROM target_summary;
"""


def _pyval(value):
    """Convert a numpy scalar (and NaN) to a plain Python value usable by sqlite3."""
    if value is None:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and np.isnan(value):
        return None
    return value


def _clean_ob_code(ob_code):
    """Strip everything after the last underscore (inclusive) from obCode."""
    if ob_code is None:
        return None
    s = str(ob_code)
    if '_' in s:
        return s[:s.rindex('_')]
    return s


def load_fiber_configs(butler, conn, limit=None):
    """Read every ``pfsConfig`` dataset and populate the visits/fiber_configs tables."""
    refs = list(butler.registry.queryDatasets('pfsConfig'))
    if limit is not None:
        refs = refs[:limit]
    print(f"Processing {len(refs)} pfsConfig datasets")

    cur = conn.cursor()
    for i, ref in enumerate(refs):
        visit = ref.dataId['visit']
        pfsConfig = butler.get('pfsConfig', ref.dataId)

        cur.execute(
            """
            INSERT OR REPLACE INTO visits
                (visit, pfsDesignId, designName, raBoresight, decBoresight, posAng,
                 arms, obstime, obstimeDesign, camMask, instStatusFlag, visit0)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                visit, _pyval(pfsConfig.pfsDesignId), pfsConfig.designName,
                _pyval(pfsConfig.raBoresight), _pyval(pfsConfig.decBoresight),
                _pyval(pfsConfig.posAng), pfsConfig.arms,
                pfsConfig.obstime, pfsConfig.obstimeDesign,
                _pyval(pfsConfig.camMask), _pyval(pfsConfig.instStatusFlag),
                _pyval(pfsConfig.visit0),
            ),
        )

        rows = []
        for j in range(len(pfsConfig)):
            targetType = int(pfsConfig.targetType[j])
            fiberStatus = int(pfsConfig.fiberStatus[j])
            rows.append((
                visit, int(pfsConfig.fiberId[j]), int(pfsConfig.cobraId[j]),
                int(pfsConfig.tract[j]), str(pfsConfig.patch[j]),
                _pyval(pfsConfig.ra[j]), _pyval(pfsConfig.dec[j]),
                int(pfsConfig.catId[j]), int(pfsConfig.objId[j]),
                targetType, TargetType(targetType).name,
                fiberStatus, FiberStatus(fiberStatus).name,
                str(pfsConfig.epoch[j]),
                _pyval(pfsConfig.pmRa[j]), _pyval(pfsConfig.pmDec[j]),
                _pyval(pfsConfig.parallax[j]),
                str(pfsConfig.proposalId[j]), _clean_ob_code(pfsConfig.obCode[j]),
                _pyval(pfsConfig.pfiNominal[j][0]), _pyval(pfsConfig.pfiNominal[j][1]),
                _pyval(pfsConfig.pfiCenter[j][0]), _pyval(pfsConfig.pfiCenter[j][1]),
                _pyval(pfsConfig.cobraTheta[j]), _pyval(pfsConfig.cobraPhi[j]),
            ))
        cur.executemany(
            """
            INSERT OR REPLACE INTO fiber_configs
                (visit, fiberId, cobraId, tract, patch, ra, dec, catId, objId,
                 targetType, targetTypeName, fiberStatus, fiberStatusName, epoch,
                 pmRa, pmDec, parallax, proposalId, obCode,
                 pfiNominalX, pfiNominalY, pfiCenterX, pfiCenterY, cobraTheta, cobraPhi)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
        print(f"  [{i + 1}/{len(refs)}] visit={visit}: {len(rows)} fibers")


def load_redshift_candidates(butler, conn, limit=None):
    """Read every ``pfsCoZCandidates`` dataset and populate the target/candidate tables."""
    refs = list(butler.registry.queryDatasets('pfsCoadd'))
    if limit is not None:
        refs = refs[:limit]
    print(f"Processing {len(refs)} pfsCoadd/pfsCoZCandidates groups")

    cur = conn.cursor()
    for i, ref in enumerate(refs):
        dataId = ref.dataId
        catId = dataId['cat_id']
        combination = dataId['combination']
        objGroup = dataId['obj_group']

        coZCands = butler.get('pfsCoZCandidates', dataId)
        targets = list(coZCands.keys())

        # Load pfsCoadd for this group to extract nvisit and exptime per target
        pfsCoadd = None
        try:
            pfsCoadd = butler.get('pfsCoadd', dataId)
        except Exception as e:
            print(f"  Warning: Failed to load pfsCoadd for {dataId}: {e}")

        cur.execute(
            "INSERT OR REPLACE INTO coadd_groups (catId, combination, objGroup, nTargets) "
            "VALUES (?, ?, ?, ?)",
            (catId, combination, objGroup, len(targets)),
        )

        targetRows = []
        solverRows = []
        candidateRows = []
        lineRows = []

        for target in targets:
            zCand = coZCands[target]
            objId = int(target.objId)
            cls = zCand.classification

            bestParams = {}
            if zCand.has_solution():
                try:
                    bestParams = zCand.get_classified_parameters() or {}
                except Exception:
                    bestParams = {}

            bestRedshift = _pyval(bestParams.get("redshift"))
            bestRedshiftError = _pyval(bestParams.get("redshiftError"))
            bestVelocity = _pyval(bestParams.get("velocity"))
            bestVelocityError = _pyval(bestParams.get("velocityError"))
            bestSubClass = bestParams.get("subClass")

            # Extract nvisit and exptime from pfsCoadd observations
            nvisit = None
            exptime = None
            if pfsCoadd is not None:
                pfsObj = None
                try:
                    if target in pfsCoadd:
                        pfsObj = pfsCoadd[target]
                except Exception:
                    pass
                if pfsObj is not None and getattr(pfsObj, 'observations', None) is not None:
                    obs = pfsObj.observations
                    visits = getattr(obs, 'visit', None)
                    exp_times = getattr(obs, 'expTime', None)
                    if visits is not None and len(visits) > 0:
                        nvisit = len(set(visits))
                        if exp_times is not None and len(exp_times) == len(visits):
                            visit_exptimes = {}
                            for v, exp in zip(visits, exp_times):
                                if exp is not None and not np.isnan(exp):
                                    exp_val = float(exp)
                                    if v not in visit_exptimes or exp_val > visit_exptimes[v]:
                                        visit_exptimes[v] = exp_val
                            if visit_exptimes:
                                exptime = round(sum(visit_exptimes.values()), 3)

            targetRows.append((
                catId, objId, combination, objGroup,
                int(target.tract), str(target.patch),
                int(zCand.has_solution()),
                zCand.init_error["code"].name, zCand.init_error["message"],
                zCand.init_warning.value, str(zCand.init_warning),
                cls.name,
                _pyval(cls.probabilities.get("galaxy")),
                _pyval(cls.probabilities.get("star")),
                _pyval(cls.probabilities.get("QSO")),
                cls.error["code"].name,
                cls.warning.value, str(cls.warning),
                bestRedshift, bestRedshiftError,
                bestVelocity, bestVelocityError,
                bestSubClass,
                nvisit, exptime,
            ))

            for objectType in ("galaxy", "qso", "star"):
                obj = getattr(zCand, objectType)
                objectTypeName = objectType.upper()

                solverRows.append((
                    catId, objId, combination, objectTypeName, len(obj.parameters),
                    obj.ZWarning.value, str(obj.ZWarning),
                    obj.ZError["code"].name, obj.ZError["message"],
                    obj.LWarning.value if objectType != "star" else None,
                    str(obj.LWarning) if objectType != "star" else None,
                    obj.LError["code"].name if objectType != "star" else None,
                    obj.LError["message"] if objectType != "star" else None,
                ))

                for params in obj.parameters:
                    candidateRows.append((
                        catId, objId, combination, objectTypeName,
                        _pyval(params.get("cRank")),
                        _pyval(params.get("targetId")), _pyval(params.get("modelId")),
                        _pyval(params.get("redshift")), _pyval(params.get("redshiftError")),
                        _pyval(params.get("redshiftProba")),
                        _pyval(params.get("velocity")), _pyval(params.get("velocityError")),
                        _pyval(params.get("velocityProba")),
                        params.get("subClass"), params.get("continuumFile"),
                        params.get("templateFile"), params.get("lineCatalogRatioFile"),
                        _pyval(params.get("emissionVelocity")), _pyval(params.get("absorptionVelocity")),
                        _pyval(params.get("continuumReducedLeastSquare")), _pyval(params.get("continuumPValue")),
                        _pyval(params.get("continuumResidualsMean")), _pyval(params.get("continuumResidualsStd")),
                        _pyval(params.get("continuumResidualsSkewness")),
                        _pyval(params.get("continuumResidualsKurtosis")),
                        _pyval(params.get("continuumResidualsKs")), _pyval(params.get("continuumResidualsKsStd")),
                        _pyval(params.get("continuumResidualsKsStdMean")),
                        _pyval(params.get("continuumResidualsAnderson")),
                        _pyval(params.get("reducedLeastSquare")), _pyval(params.get("pValue")),
                        _pyval(params.get("residualsMean")), _pyval(params.get("residualsStd")),
                        _pyval(params.get("residualsSkewness")), _pyval(params.get("residualsKurtosis")),
                        _pyval(params.get("residualsKs")), _pyval(params.get("residualsKsStd")),
                        _pyval(params.get("residualsKsStdMean")), _pyval(params.get("residualsAnderson")),
                    ))

                if objectType != "star" and obj.lines is not None:
                    lines = obj.lines
                    if isinstance(lines, Row) or (isinstance(lines, np.ndarray) and lines.ndim == 0):
                        lines = [lines]
                    for line in lines:
                        try:
                            line_name = str(line["lineName"])
                        except (IndexError, TypeError, KeyError):
                            continue
                        lineRows.append((
                            catId, objId, combination, objectTypeName,
                            line_name, _pyval(line["lineWave"]),
                            _pyval(line["lineZ"]), _pyval(line["lineZError"]),
                            _pyval(line["lineSigma"]), _pyval(line["lineSigmaError"]),
                            _pyval(line["lineVelocity"]), _pyval(line["lineVelocityError"]),
                            _pyval(line["lineFlux"]), _pyval(line["lineFluxError"]),
                            _pyval(line["lineEW"]), _pyval(line["lineEWError"]),
                            _pyval(line["lineContinuumLevel"]), _pyval(line["lineContinuumLevelError"]),
                        ))

        cur.executemany(
            """
            INSERT OR REPLACE INTO targets
                (catId, objId, combination, objGroup, tract, patch, hasSolution,
                 initErrorCode, initErrorMessage, initWarningValue, initWarningName,
                 classificationName, probaGalaxy, probaStar, probaQSO,
                 classificationErrorCode, classificationWarningValue, classificationWarningName,
                 bestRedshift, bestRedshiftError, bestVelocity, bestVelocityError, bestSubClass,
                 nvisit, exptime)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            targetRows,
        )
        cur.executemany(
            """
            INSERT OR REPLACE INTO solver_results
                (catId, objId, combination, objectType, nCandidates,
                 zWarningValue, zWarningName, zErrorCode, zErrorMessage,
                 lWarningValue, lWarningName, lErrorCode, lErrorMessage)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            solverRows,
        )
        cur.executemany(
            """
            INSERT OR REPLACE INTO redshift_candidates
                (catId, objId, combination, objectType, cRank, targetId, modelId,
                 redshift, redshiftError, redshiftProba,
                 velocity, velocityError, velocityProba,
                 subClass, continuumFile, templateFile, lineCatalogRatioFile,
                 emissionVelocity, absorptionVelocity,
                 continuumReducedLeastSquare, continuumPValue,
                 continuumResidualsMean, continuumResidualsStd,
                 continuumResidualsSkewness, continuumResidualsKurtosis,
                 continuumResidualsKs, continuumResidualsKsStd,
                 continuumResidualsKsStdMean, continuumResidualsAnderson,
                 reducedLeastSquare, pValue,
                 residualsMean, residualsStd, residualsSkewness, residualsKurtosis,
                 residualsKs, residualsKsStd, residualsKsStdMean, residualsAnderson)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            candidateRows,
        )
        cur.executemany(
            """
            INSERT OR REPLACE INTO line_measurements
                (catId, objId, combination, objectType, lineName, lineWave,
                 lineZ, lineZError, lineSigma, lineSigmaError,
                 lineVelocity, lineVelocityError, lineFlux, lineFluxError,
                 lineEW, lineEWError, lineContinuumLevel, lineContinuumLevelError)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            lineRows,
        )
        conn.commit()
        print(f"  [{i + 1}/{len(refs)}] catId={catId} combination={combination} "
              f"objGroup={objGroup}: {len(targets)} targets, {len(candidateRows)} candidates, "
              f"{len(lineRows)} line measurements")


def populate_target_summary(conn):
    """Populate target_summary materialized table from targets and latest fiber_configs while preserving file paths."""
    print("\nPopulating target_summary materialized table...")
    cur = conn.cursor()

    # Check if target_summary exists and has existing file path entries to preserve
    cur.execute("PRAGMA table_info(target_summary)")
    cols = {row[1] for row in cur.fetchall()}
    has_file_cols = "has_fits" in cols and "fits_path" in cols

    cur.execute("DROP TABLE IF EXISTS _temp_target_files")
    if has_file_cols:
        cur.execute("""
            CREATE TEMP TABLE _temp_target_files AS
            SELECT catId, objId, combination, has_fits, fits_path, has_png, png_path
            FROM target_summary
            WHERE has_fits = 1 OR has_png = 1
        """)
        cur.execute("SELECT count(*) FROM _temp_target_files")
        preserved = cur.fetchone()[0]
        if preserved > 0:
            print(f"  Preserving {preserved:,} existing file path records...")

    cur.execute("DELETE FROM target_summary")
    cur.execute("""
        INSERT INTO target_summary (
            catId, objId, combination, objGroup,
            obCode, targetTypeName, fiberStatusName, ra, dec,
            classificationName, probaGalaxy, probaStar, probaQSO,
            bestRedshift, bestRedshiftError, bestVelocity, bestVelocityError,
            bestSubClass, hasSolution,
            nvisit, exptime,
            has_fits, fits_path, has_png, png_path
        )
        SELECT 
            t.catId, t.objId, t.combination, t.objGroup,
            fc.obCode, fc.targetTypeName, fc.fiberStatusName, fc.ra, fc.dec,
            t.classificationName, t.probaGalaxy, t.probaStar, t.probaQSO,
            t.bestRedshift, t.bestRedshiftError, t.bestVelocity, t.bestVelocityError,
            t.bestSubClass, t.hasSolution,
            t.nvisit, t.exptime,
            COALESCE(tf.has_fits, 0), tf.fits_path, COALESCE(tf.has_png, 0), tf.png_path
        FROM targets t
        LEFT JOIN (
            SELECT catId, objId, obCode, targetTypeName, fiberStatusName, ra, dec,
                   ROW_NUMBER() OVER (PARTITION BY catId, objId ORDER BY visit DESC) as rn
            FROM fiber_configs
        ) fc ON t.catId = fc.catId AND t.objId = fc.objId AND fc.rn = 1
        LEFT JOIN _temp_target_files tf ON t.catId = tf.catId AND t.objId = tf.objId AND t.combination = tf.combination;
    """)
    cur.execute("DROP TABLE IF EXISTS _temp_target_files")
    conn.commit()
    cur.execute("SELECT count(*) FROM target_summary")
    cnt = cur.fetchone()[0]
    print(f"target_summary populated successfully with {cnt:,} rows.")


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


def export_spectral_lines_cache(conn: sqlite3.Connection, db_path: str):
    """Aggregate spectral line counts from line_measurements and export spectral_lines_cache.json."""
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
    for name, cnt in rows:
        rest_nm = KNOWN_SPECTRAL_REST_WAVELENGTHS.get(name)
        rest_A = round(rest_nm * 10.0, 1) if rest_nm is not None else None
        lines.append({
            "lineName": name,
            "count": cnt,
            "restWave_nm": rest_nm,
            "restWave_A": rest_A,
        })
    catalog = {
        "total_lines": len(lines),
        "lines": lines,
    }

    cache_dir = os.path.dirname(os.path.abspath(db_path))
    cache_path = os.path.join(cache_dir, "spectral_lines_cache.json")
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(catalog, f, indent=2)
        print(f"Exported spectral lines catalog ({len(lines)} lines) to {cache_path}")
    except Exception as e:
        print(f"Warning: Failed to export spectral lines cache: {e}")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default="/mnt/ugnas/work/LSST/PFS/S26A-104/2d",
                         help="Butler repository root")
    parser.add_argument("--collections", nargs="+",
                         default=["run28_August2026", "run28_August2026/lam1d_modified"],
                         help="Butler collections to search")
    parser.add_argument("--db", default="pfs_metadata.sqlite3",
                         help="Output SQLite database file")
    parser.add_argument("--limit-visits", type=int, default=None,
                         help="Limit number of pfsConfig visits to process")
    parser.add_argument("--limit-groups", type=int, default=None,
                         help="Limit number of pfsCoZCandidates groups to process")
    parser.add_argument("--skip-fiber-configs", action="store_true",
                         help="Do not (re-)populate the visits/fiber_configs tables")
    parser.add_argument("--skip-candidates", action="store_true",
                         help="Do not (re-)populate the target/candidate tables")
    parser.add_argument("--skip-target-summary", action="store_true",
                         help="Do not (re-)populate the target_summary table")
    args = parser.parse_args()

    butler = Butler(args.repo, collections=args.collections)

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)

    if not args.skip_fiber_configs:
        load_fiber_configs(butler, conn, limit=args.limit_visits)
    if not args.skip_candidates:
        load_redshift_candidates(butler, conn, limit=args.limit_groups)
        export_spectral_lines_cache(conn, args.db)
    if not args.skip_target_summary:
        populate_target_summary(conn)

    conn.close()
    print(f"Done. Database written to {args.db}")


if __name__ == "__main__":
    main()
