#!/usr/bin/env python3
"""
PFS Target & Spectrum Viewer - Data Downloader
Downloads pfs_metadata.sqlite3 and extracted_targets.tar.gz from Hugging Face.
"""

import os
import sys
import tarfile
import getpass

try:
    from huggingface_hub import hf_hub_download
except ImportError:
    print("❌ Error: 'huggingface_hub' is not installed.")
    print("Please install it by running: pip install huggingface_hub")
    sys.exit(1)

REPO_ID = "Oakleaf67/pfs-target-data"

def main():
    print("=" * 60)
    print("  🌌 PFS Target & Spectrum Viewer - Data Downloader")
    print(f"  📦 Dataset: {REPO_ID} (Hugging Face Private)")
    print("=" * 60)

    token = os.environ.get("HF_TOKEN")
    token_path = os.path.expanduser("~/.cache/huggingface/token")
    if not token and not os.path.exists(token_path):
        print("\n⚠️  No Hugging Face token detected in environment or cache.")
        token = getpass.getpass("Enter your Hugging Face Access Token (Read): ").strip()

    print("\n⬇️  Downloading pfs_metadata.sqlite3 (157MB)...")
    db_file = hf_hub_download(
        repo_id=REPO_ID,
        filename="pfs_metadata.sqlite3",
        repo_type="dataset",
        token=token,
        local_dir=".",
    )
    print(f"  ✅ Saved: {db_file}")

    print("\n⬇️  Downloading extracted_targets.tar.gz (7.8GB)...")
    tar_file = hf_hub_download(
        repo_id=REPO_ID,
        filename="extracted_targets.tar.gz",
        repo_type="dataset",
        token=token,
        local_dir=".",
    )
    print(f"  ✅ Saved: {tar_file}")

    print("\n📦 Extracting extracted_targets.tar.gz...")
    with tarfile.open(tar_file, "r:gz") as tar:
        tar.extractall(path=".")
    print("  ✅ Extracted extracted_targets/ successfully!")

    print("\n" + "=" * 60)
    print("🎉 All datasets downloaded and extracted successfully!")
    print("You can now start the web viewer:")
    print("  cd pfs_target_viewer && ./run_viewer.sh")
    print("=" * 60)

if __name__ == "__main__":
    main()
