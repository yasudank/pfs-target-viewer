#!/usr/bin/env python3
"""
Import Machine Learning (pfs_specClass2) survey predictions into pfs_metadata.sqlite3.

Source: /mnt/ugnas/work/PFS/pfs_specClass2/results/pfs_full_survey_predictions.sqlite3
Target: pfs_metadata.sqlite3 (table: survey_predictions)
"""
import argparse
import os
import sqlite3
import sys
import time

DEFAULT_SRC = "/mnt/ugnas/work/PFS/pfs_specClass2/results/pfs_full_survey_predictions.sqlite3"
DEFAULT_DB = "pfs_metadata.sqlite3"


def import_predictions(src_path: str, db_path: str):
    if not os.path.exists(src_path):
        print(f"❌ Error: Source predictions database not found at {src_path}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(db_path):
        print(f"❌ Error: Target database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    print("=" * 70)
    print("  🚀 Importing ML Survey Predictions (pfs_specClass2)")
    print(f"  📥 Source: {src_path}")
    print(f"  📂 Target: {db_path}")
    print("=" * 70)

    t0 = time.time()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("PRAGMA synchronous = NORMAL;")
    cur.execute("PRAGMA cache_size = -128000;")  # 128MB cache

    # Check source row count
    src_conn = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    src_cur = src_conn.cursor()
    src_cur.execute("SELECT count(*) FROM survey_predictions")
    src_count = src_cur.fetchone()[0]
    src_conn.close()
    print(f"Found {src_count:,} rows in source 'survey_predictions'.")

    # Attach and copy table
    print("Creating 'survey_predictions' table and transferring data...")
    cur.execute(f"ATTACH DATABASE ? AS src", (src_path,))

    cur.execute("""
        CREATE TABLE IF NOT EXISTS survey_predictions (
            catId INTEGER NOT NULL,
            objId INTEGER NOT NULL,
            combination TEXT NOT NULL,
            pred_class TEXT,
            prob_star REAL,
            prob_galaxy REAL,
            prob_qso REAL,
            pred_confidence REAL,
            pred_redshift REAL,
            redshift_quality REAL,
            z_galaxy_candidate REAL,
            z_qso_candidate REAL,
            PRIMARY KEY (catId, objId, combination)
        )
    """)

    # Delete existing rows if table had data, then bulk copy
    cur.execute("DELETE FROM survey_predictions")
    cur.execute("""
        INSERT INTO survey_predictions (
            catId, objId, combination,
            pred_class, prob_star, prob_galaxy, prob_qso,
            pred_confidence, pred_redshift, redshift_quality,
            z_galaxy_candidate, z_qso_candidate
        )
        SELECT 
            catId, objId, combination,
            pred_class, prob_star, prob_galaxy, prob_qso,
            pred_confidence, pred_redshift, redshift_quality,
            z_galaxy_candidate, z_qso_candidate
        FROM src.survey_predictions
    """)
    conn.commit()
    cur.execute("DETACH DATABASE src")

    # Create indexes for fast JOINs and filtering
    print("Building performance indexes...")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_survey_predictions_catid_objid ON survey_predictions(catId, objId);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_survey_predictions_pred_class ON survey_predictions(pred_class);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_survey_predictions_pred_redshift ON survey_predictions(pred_redshift);")
    # Create convenience view
    print("Creating convenience view 'v_target_predictions' (target_summary LEFT JOIN survey_predictions)...")
    cur.execute("DROP VIEW IF EXISTS v_target_predictions")
    cur.execute("""
        CREATE VIEW v_target_predictions AS
        SELECT 
            ts.*,
            sp.pred_class,
            sp.prob_galaxy,
            sp.prob_qso,
            sp.prob_star,
            sp.pred_confidence,
            sp.pred_redshift,
            sp.redshift_quality,
            sp.z_galaxy_candidate,
            sp.z_qso_candidate
        FROM target_summary ts
        LEFT JOIN survey_predictions sp
          ON ts.catId = sp.catId AND ts.objId = sp.objId AND ts.combination = sp.combination
    """)
    conn.commit()

    # Verification
    cur.execute("SELECT count(*) FROM survey_predictions")
    imported_cnt = cur.fetchone()[0]

    # Check join match with target_summary
    cur.execute("""
        SELECT count(*)
        FROM target_summary ts
        JOIN survey_predictions sp
          ON ts.catId = sp.catId AND ts.objId = sp.objId AND ts.combination = sp.combination
    """)
    matched_ts = cur.fetchone()[0]

    cur.execute("""
        SELECT pred_class, count(*), round(avg(pred_confidence), 3)
        FROM survey_predictions
        GROUP BY pred_class
    """)
    class_stats = cur.fetchall()

    conn.close()
    elapsed = round(time.time() - t0, 2)

    print("\n" + "=" * 70)
    print(f"✅ Successfully imported {imported_cnt:,} rows in {elapsed}s.")
    print(f"🔗 Matched with target_summary: {matched_ts:,} rows.")
    print("\n📊 Prediction Breakdown by Class:")
    for cname, cnt, avg_conf in class_stats:
        print(f"   • {cname or 'NULL':<10}: {cnt:>8,} targets (Avg Confidence: {avg_conf})")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", default=DEFAULT_SRC, help="Path to source predictions SQLite database")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to target pfs_metadata.sqlite3")
    args = parser.parse_args()

    import_predictions(args.src, args.db)


if __name__ == "__main__":
    main()
