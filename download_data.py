#!/usr/bin/env python3
"""
PFS Target & Spectrum Viewer - Data Downloader
Downloads pfs_metadata.sqlite3 and extracted_targets.tar.gz from Hugging Face.
Automatically uses the project's dedicated virtual environment (.venv_viewer)
without affecting the host/system Python environment.
"""

import os
import sys
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(SCRIPT_DIR, "pfs_target_viewer", ".venv_viewer", "bin", "python")

# If huggingface_hub is not available in current python, transparently delegate to download_data.sh
try:
    import huggingface_hub
except ImportError:
    if os.path.exists(VENV_PYTHON):
        # Re-execute with venv python
        os.execv(VENV_PYTHON, [VENV_PYTHON] + sys.argv)
    else:
        # Launch download_data.sh to automatically create venv and run
        sh_script = os.path.join(SCRIPT_DIR, "download_data.sh")
        if os.path.exists(sh_script):
            res = subprocess.run(["bash", sh_script] + sys.argv[1:])
            sys.exit(res.returncode)
        else:
            print("❌ Error: 'huggingface_hub' is not installed, and download_data.sh was not found.")
            sys.exit(1)

import tarfile
import getpass
from huggingface_hub import hf_hub_download

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
        local_dir=SCRIPT_DIR,
    )
    print(f"  ✅ Saved: {db_file}")

    print("\n⬇️  Downloading extracted_targets.tar.gz (7.8GB)...")
    tar_file = hf_hub_download(
        repo_id=REPO_ID,
        filename="extracted_targets.tar.gz",
        repo_type="dataset",
        token=token,
        local_dir=SCRIPT_DIR,
    )
    print(f"  ✅ Saved: {tar_file}")

    print("\n📦 Extracting extracted_targets.tar.gz...")
    with tarfile.open(tar_file, "r:gz") as tar:
        tar.extractall(path=SCRIPT_DIR)
    print("  ✅ Extracted extracted_targets/ successfully!")

    print("\n" + "=" * 60)
    print("🎉 All datasets downloaded and extracted successfully!")
    print("The dedicated virtual environment is already prepared.")
    print("You can now start the web viewer immediately:")
    print("  cd pfs_target_viewer && ./run_viewer.sh")
    print("=" * 60)

if __name__ == "__main__":
    main()
