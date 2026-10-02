#!/usr/bin/env python3
"""
Create and populate the `target_summary` materialized table in pfs_metadata.sqlite3.
This replaces the heavy dynamic view `v_target_summary` with a high-performance indexed table.
Also updates `v_target_summary` to point to `target_summary` for 100% backward compatibility.

Usage:
    python3 create_target_summary.py [--db pfs_metadata.sqlite3] [--force]
"""
import argparse
import os
import sqlite3
import sys
import time


def main():
    parser = argparse.ArgumentParser(description="Create target_summary materialized table.")
    parser.add_argument(
        "--db",
        default="pfs_metadata.sqlite3",
        help="Path to pfs_metadata.sqlite3 (default: pfs_metadata.sqlite3)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Drop and recreate target_summary table if it already exists",
    )
    args = parser.parse_args()

    db_path = os.path.abspath(args.db)
    if not os.path.exists(db_path):
        print(f"❌ Error: Database file not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    print("=" * 70)
    print("  🚀 PFS Target Summary Table Materialization")
    print(f"  📂 Target Database: {db_path}")
    print("=" * 70)

    t_start = time.time()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Optimization pragmas for batch building
    cur.execute("PRAGMA synchronous = NORMAL;")
    cur.execute("PRAGMA temp_store = MEMORY;")
    cur.execute("PRAGMA cache_size = -256000;")  # 256MB in-memory cache

    # Check if target_summary already exists
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='target_summary'")
    table_exists = cur.fetchone() is not None

    if table_exists:
        if args.force:
            print("⚠️  Existing 'target_summary' table found. Dropping (--force specified)...")
            cur.execute("DROP TABLE target_summary")
        else:
            cur.execute("SELECT count(*) FROM target_summary")
            cnt = cur.fetchone()[0]
            print(f"ℹ️  'target_summary' table already exists with {cnt:,} rows.")
            print("   Use --force to drop and rebuild. Exiting.")
            conn.close()
            return

    # Check row counts in source tables
    cur.execute("SELECT count(*) FROM targets")
    targets_count = cur.fetchone()[0]
    print(f"📊 Source 'targets' row count: {targets_count:,}", flush=True)

    cur.execute("SELECT count(*) FROM fiber_configs")
    fc_count = cur.fetchone()[0]
    print(f"📊 Source 'fiber_configs' row count: {fc_count:,}", flush=True)

    # Check if target_summary exists and has existing file path entries to preserve
    cur.execute("PRAGMA table_info(target_summary)")
    existing_cols = {row[1] for row in cur.fetchall()}
    has_file_cols = "has_fits" in existing_cols and "fits_path" in existing_cols

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
            print(f"ℹ️  Preserving {preserved:,} existing file path records...")

    # Check columns in source 'targets' table
    cur.execute("PRAGMA table_info(targets)")
    target_cols = {row[1] for row in cur.fetchall()}
    has_target_nvisit = "nvisit" in target_cols
    has_target_exptime = "exptime" in target_cols

    # 1. Create table schema without secondary indexes (faster bulk insert)
    print("\n1️⃣  Creating table schema 'target_summary'...", flush=True)
    cur.execute("""
    CREATE TABLE target_summary (
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
    """)

    # 2. Populate target_summary from targets and latest fiber_configs
    print("2️⃣  Populating 'target_summary' from targets and latest fiber_configs...", flush=True)
    print("    (Sorting 2.7M+ fiber_configs by visit DESC to pick latest observation per target)...", flush=True)
    t_pop_start = time.time()

    nvisit_src = "t.nvisit" if has_target_nvisit else "NULL"
    exptime_src = "t.exptime" if has_target_exptime else "NULL"
    fits_src = "COALESCE(tf.has_fits, 0)" if has_file_cols else "0"
    fits_path_src = "tf.fits_path" if has_file_cols else "NULL"
    png_src = "COALESCE(tf.has_png, 0)" if has_file_cols else "0"
    png_path_src = "tf.png_path" if has_file_cols else "NULL"
    join_tf = "LEFT JOIN _temp_target_files tf ON t.catId = tf.catId AND t.objId = tf.objId AND t.combination = tf.combination" if has_file_cols else ""

    insert_sql = f"""
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
        t.catId,
        t.objId,
        t.combination,
        t.objGroup,
        fc.obCode,
        fc.targetTypeName,
        fc.fiberStatusName,
        fc.ra,
        fc.dec,
        t.classificationName,
        t.probaGalaxy,
        t.probaStar,
        t.probaQSO,
        t.bestRedshift,
        t.bestRedshiftError,
        t.bestVelocity,
        t.bestVelocityError,
        t.bestSubClass,
        t.hasSolution,
        {nvisit_src},
        {exptime_src},
        {fits_src},
        {fits_path_src},
        {png_src},
        {png_path_src}
    FROM targets t
    LEFT JOIN (
        SELECT catId, objId, obCode, targetTypeName, fiberStatusName, ra, dec,
               ROW_NUMBER() OVER (PARTITION BY catId, objId ORDER BY visit DESC) as rn
        FROM fiber_configs
    ) fc ON t.catId = fc.catId AND t.objId = fc.objId AND fc.rn = 1
    {join_tf};
    """
    cur.execute(insert_sql)
    if has_file_cols:
        cur.execute("DROP TABLE IF EXISTS _temp_target_files")
    conn.commit()
    t_pop = time.time() - t_pop_start
    print(f"    ✅ Populated in {t_pop:.2f}s", flush=True)

    # 3. Create secondary indexes
    print("\n3️⃣  Building indexes on 'target_summary'...", flush=True)
    indexes = [
        ("idx_ts_classification", "classificationName"),
        ("idx_ts_best_redshift", "bestRedshift"),
        ("idx_ts_obcode", "obCode"),
        ("idx_ts_catid", "catId"),
        ("idx_ts_coords", "ra, dec"),
        ("idx_ts_nvisit", "nvisit"),
        ("idx_ts_exptime", "exptime"),
        ("idx_ts_has_fits", "has_fits"),
        ("idx_ts_has_png", "has_png"),
    ]
    for idx_name, cols in indexes:
        t_idx_start = time.time()
        cur.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON target_summary ({cols});")
        conn.commit()
        print(f"    ✅ Index {idx_name} ({cols}) built in {time.time() - t_idx_start:.2f}s", flush=True)

    # 4. Update view v_target_summary for 100% backward compatibility
    print("\n4️⃣  Updating view 'v_target_summary' to reference 'target_summary'...", flush=True)
    cur.execute("DROP VIEW IF EXISTS v_target_summary;")
    cur.execute("CREATE VIEW v_target_summary AS SELECT * FROM target_summary;")
    conn.commit()
    print("    ✅ View 'v_target_summary' successfully updated.", flush=True)

    # 5. Verification
    print("\n5️⃣  Verifying row count and query performance...", flush=True)
    t_verify = time.time()
    cur.execute("SELECT count(*) FROM target_summary")
    summary_count = cur.fetchone()[0]
    verify_duration = time.time() - t_verify

    print(f"    Count: {summary_count:,} rows (Query took {verify_duration:.4f}s)", flush=True)
    if summary_count != targets_count:
        print(f"    ⚠️  Warning: summary count ({summary_count}) differs from targets count ({targets_count})", flush=True)
    else:
        print("    ✨ Verified: Row count perfectly matches source targets table!", flush=True)

    conn.close()
    total_time = time.time() - t_start
    print("\n" + "=" * 70, flush=True)
    print(f"  🎉 Materialization completed successfully in {total_time:.2f}s!", flush=True)
    print("=" * 70, flush=True)


if __name__ == "__main__":
    main()
