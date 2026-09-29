#!/usr/bin/env python3
"""
PFS Target & Spectrum Viewer - File Sharding & DB Indexing Tool (Phase 2)

Features:
1. Reorganize flat fits/ and png/ directories into a 2-level sharded hierarchy:
       extracted_targets/fits/{catId}/{objId % 1000:03d}/pfsObject_...fits
       extracted_targets/png/{catId}/{objId % 1000:03d}/spec_...png
   This avoids storing 100k+ files in a single flat directory, greatly accelerating
   directory traversal and caching on both NFS and local filesystems.

2. Update `target_summary` in `pfs_metadata.sqlite3` with columns:
       has_fits (INTEGER), fits_path (TEXT)
       has_png  (INTEGER), png_path  (TEXT)
   This eliminates all filesystem lookups during viewer table queries.

Usage:
    # 1. Preview changes (Dry-run):
    python3 shard_and_index_targets.py --dry-run

    # 2. Perform file sharding (move) and update database:
    python3 shard_and_index_targets.py

    # 3. Only update DB from already sharded/flat files:
    python3 shard_and_index_targets.py --skip-move

    # 4. Custom data directory and database:
    python3 shard_and_index_targets.py --data-dir ./extracted_targets --db ./pfs_metadata.sqlite3
"""
import argparse
import os
import shutil
import sqlite3
import sys
import time
from typing import Dict, Optional, Tuple


def parse_cat_obj_id(filename: str) -> Optional[Tuple[int, int]]:
    """Extract (catId, objId) from standard PFS extracted target filenames."""
    # Strip extension
    stem = filename
    if stem.endswith(".fits"):
        stem = stem[:-5]
    elif stem.endswith(".png"):
        stem = stem[:-4]

    # Patterns:
    #   pfsObject_{obCode}_{catId}_{objId}
    #   spec_{obCode}_{catId}_{objId}
    #   pfsObject_{catId}_{objId}
    #   spec_{catId}_{objId}
    idx2 = stem.rfind("_")
    if idx2 != -1:
        idx1 = stem.rfind("_", 0, idx2)
        if idx1 != -1:
            try:
                cid = int(stem[idx1 + 1 : idx2])
                oid = int(stem[idx2 + 1 :])
                return (cid, oid)
            except ValueError:
                pass

    # Fallback for hyphen pattern: pfsObject-{catId}-{combination}-{tract}-{patch}-{objId}
    if "-" in stem:
        parts = stem.split("-")
        if len(parts) >= 3:
            try:
                cid = int(parts[1])
                oid = int(parts[-1])
                return (cid, oid)
            except ValueError:
                pass

    return None


def get_shard_subdir(cat_id: int, obj_id: int) -> str:
    """Return 2-level shard subdirectory component: {catId}/{objId % 1000:03d}"""
    shard = int(obj_id) % 1000
    return os.path.join(str(cat_id), f"{shard:03d}")


def ensure_db_columns(conn: sqlite3.Connection):
    """Ensure has_fits, fits_path, has_png, png_path columns and indexes exist in target_summary."""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(target_summary)")
    cols = {row[1] for row in cur.fetchall()}

    added = []
    if "has_fits" not in cols:
        cur.execute("ALTER TABLE target_summary ADD COLUMN has_fits INTEGER DEFAULT 0;")
        added.append("has_fits")
    if "fits_path" not in cols:
        cur.execute("ALTER TABLE target_summary ADD COLUMN fits_path TEXT DEFAULT NULL;")
        added.append("fits_path")
    if "has_png" not in cols:
        cur.execute("ALTER TABLE target_summary ADD COLUMN has_png INTEGER DEFAULT 0;")
        added.append("has_png")
    if "png_path" not in cols:
        cur.execute("ALTER TABLE target_summary ADD COLUMN png_path TEXT DEFAULT NULL;")
        added.append("png_path")

    if added:
        print(f"  🔧 Added columns to 'target_summary': {', '.join(added)}")

    # Secondary indexes for fast filtering
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ts_has_fits ON target_summary (has_fits);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ts_has_png ON target_summary (has_png);")

    # Update view v_target_summary
    cur.execute("DROP VIEW IF EXISTS v_target_summary;")
    cur.execute("CREATE VIEW v_target_summary AS SELECT * FROM target_summary;")
    conn.commit()


def process_directory(
    base_dir: str,
    sub_name: str,
    ext: str,
    dry_run: bool = False,
    skip_move: bool = False,
    copy_files: bool = False,
) -> Dict[Tuple[int, int], str]:
    """
    Scan files in directory (flat or already sharded), reorganize flat ones into shards,
    and return mapping (catId, objId) -> relative_path_from_data_dir.
    """
    target_dir = os.path.join(base_dir, sub_name)
    if not os.path.exists(target_dir):
        print(f"  ⚠️  Directory {target_dir} not found. Skipping.")
        return {}

    print(f"\n📂 Processing {sub_name.upper()} files in {target_dir}...")
    t0 = time.time()
    file_map: Dict[Tuple[int, int], str] = {}
    moved_count = 0
    already_sharded_count = 0
    unrecognized_count = 0

    # 1. Walk through the directory (handles both flat and sharded structures)
    for root, dirs, files in os.walk(target_dir):
        rel_root = os.path.relpath(root, target_dir)
        is_top_level = (rel_root == ".")

        for fname in files:
            if not fname.endswith(ext):
                continue

            ids = parse_cat_obj_id(fname)
            if not ids:
                unrecognized_count += 1
                continue

            cat_id, obj_id = ids
            shard_sub = get_shard_subdir(cat_id, obj_id)
            current_path = os.path.join(root, fname)

            if is_top_level:
                # Flat file that needs to be moved to its shard
                dest_dir = os.path.join(target_dir, shard_sub)
                dest_path = os.path.join(dest_dir, fname)
                rel_dest = os.path.join(sub_name, shard_sub, fname)

                if not skip_move and not dry_run:
                    os.makedirs(dest_dir, exist_ok=True)
                    if copy_files:
                        shutil.copy2(current_path, dest_path)
                    else:
                        os.rename(current_path, dest_path)

                file_map[(cat_id, obj_id)] = rel_dest
                moved_count += 1
            else:
                # Already in a subdirectory
                rel_path = os.path.join(sub_name, rel_root, fname)
                file_map[(cat_id, obj_id)] = rel_path
                already_sharded_count += 1

    dur = time.time() - t0
    action_label = "Would move" if dry_run else ("Copied" if copy_files else "Moved")
    print(f"  ✅ {sub_name.upper()} finished in {dur:.2f}s:")
    print(f"     - Total indexed:        {len(file_map):,}")
    print(f"     - {action_label} into shards: {moved_count:,}")
    print(f"     - Already sharded:      {already_sharded_count:,}")
    if unrecognized_count > 0:
        print(f"     - Unrecognized format:  {unrecognized_count:,}")

    return file_map


def main():
    parser = argparse.ArgumentParser(
        description="PFS Target Viewer - Shard extracted files and update database index."
    )
    parser.add_argument(
        "--data-dir",
        default="./extracted_targets",
        help="Path to extracted_targets directory (default: ./extracted_targets)",
    )
    parser.add_argument(
        "--db",
        default="./pfs_metadata.sqlite3",
        help="Path to pfs_metadata.sqlite3 (default: ./pfs_metadata.sqlite3)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview operations without moving files or modifying database",
    )
    parser.add_argument(
        "--skip-move",
        action="store_true",
        help="Do not move files on disk; only scan and update database paths",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Do not update database; only shard files on disk",
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Copy files instead of moving (requires double disk space)",
    )
    args = parser.parse_args()

    data_dir = os.path.abspath(args.data_dir)
    db_path = os.path.abspath(args.db)

    print("=" * 70)
    print("  🌌 PFS Target Viewer - Sharding & DB Indexing Tool (Phase 2)")
    print(f"  📁 Data Dir:  {data_dir}")
    print(f"  📂 Database:  {db_path}")
    if args.dry_run:
        print("  ⚠️  MODE:      DRY-RUN (No files will be moved or database modified)")
    print("=" * 70)

    if not os.path.exists(data_dir):
        print(f"❌ Error: Data directory {data_dir} does not exist.", file=sys.stderr)
        sys.exit(1)

    # 1. Process FITS and PNG directories
    fits_map = process_directory(
        data_dir,
        "fits",
        ".fits",
        dry_run=args.dry_run,
        skip_move=args.skip_move,
        copy_files=args.copy,
    )
    png_map = process_directory(
        data_dir,
        "png",
        ".png",
        dry_run=args.dry_run,
        skip_move=args.skip_move,
        copy_files=args.copy,
    )

    # 2. Update database
    if args.skip_db:
        print("\n⏭️  Skipping database update (--skip-db specified).")
        return

    if not os.path.exists(db_path):
        print(f"⚠️  Database {db_path} not found. Skipping DB indexing.")
        return

    if args.dry_run:
        print("\n[Dry-run] Would update target_summary table with file paths.")
        return

    print("\n💾 Updating 'target_summary' table in database...")
    t_db_start = time.time()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Optimization pragmas
    cur.execute("PRAGMA synchronous = NORMAL;")
    cur.execute("PRAGMA cache_size = -128000;")
    cur.execute("PRAGMA temp_store = MEMORY;")

    ensure_db_columns(conn)

    # Combine all target keys
    all_keys = set(fits_map.keys()) | set(png_map.keys())
    print(f"  Building updates for {len(all_keys):,} unique targets...")

    update_rows = []
    for cat_id, obj_id in all_keys:
        f_path = fits_map.get((cat_id, obj_id))
        p_path = png_map.get((cat_id, obj_id))
        has_f = 1 if f_path else 0
        has_p = 1 if p_path else 0
        update_rows.append((has_f, f_path, has_p, p_path, cat_id, obj_id))

    update_sql = """
    UPDATE target_summary
    SET has_fits = ?, fits_path = ?, has_png = ?, png_path = ?
    WHERE catId = ? AND objId = ?;
    """

    print("  Executing bulk update...")
    cur.executemany(update_sql, update_rows)
    conn.commit()

    # Verify counts in DB
    cur.execute("SELECT count(*) FROM target_summary WHERE has_fits = 1")
    db_fits_count = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM target_summary WHERE has_png = 1")
    db_png_count = cur.fetchone()[0]
    conn.close()

    t_db = time.time() - t_db_start
    print(f"  ✅ Database updated in {t_db:.2f}s:")
    print(f"     - Targets with FITS recorded in DB: {db_fits_count:,}")
    print(f"     - Targets with PNG recorded in DB:  {db_png_count:,}")

    print("\n" + "=" * 70)
    print("  🎉 Sharding & DB Indexing completed successfully!")
    print("=" * 70)


if __name__ == "__main__":
    main()
