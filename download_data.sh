#!/usr/bin/env bash
# ==============================================================================
# PFS Target & Spectrum Viewer - Data Downloader
# Automatically creates the project's dedicated virtual environment (.venv_viewer)
# and installs huggingface_hub inside it WITHOUT affecting the host Python environment.
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

REPO_ID="Oakleaf67/pfs-target-data"
VENV_DIR="${SCRIPT_DIR}/pfs_target_viewer/.venv_viewer"
REQUIREMENTS="${SCRIPT_DIR}/pfs_target_viewer/requirements.txt"

echo "============================================================"
echo "  🌌 PFS Target & Spectrum Viewer - Data Downloader"
echo "  📦 Dataset: ${REPO_ID} (Hugging Face Private)"
echo "============================================================"

# 1. Ensure the dedicated virtual environment exists (Zero host pollution)
if [ ! -d "${VENV_DIR}" ]; then
    echo "⚙️  Setting up dedicated virtual environment in pfs_target_viewer/.venv_viewer..."
    if command -v uv &> /dev/null; then
        uv venv "${VENV_DIR}"
        uv pip install -r "${REQUIREMENTS}" --python "${VENV_DIR}"
    elif [ -x "${HOME}/.local/bin/uv" ]; then
        "${HOME}/.local/bin/uv" venv "${VENV_DIR}"
        "${HOME}/.local/bin/uv" pip install -r "${REQUIREMENTS}" --python "${VENV_DIR}"
    else
        python3 -m venv "${VENV_DIR}"
        "${VENV_DIR}/bin/pip" install --upgrade pip
        "${VENV_DIR}/bin/pip" install -r "${REQUIREMENTS}"
    fi
    echo "✅ Dedicated virtual environment ready."
else
    # Ensure huggingface_hub is installed in the existing venv
    if ! "${VENV_DIR}/bin/python" -c "import huggingface_hub" &> /dev/null; then
        echo "⚙️  Updating requirements in .venv_viewer..."
        if command -v uv &> /dev/null; then
            uv pip install -r "${REQUIREMENTS}" --python "${VENV_DIR}"
        elif [ -x "${HOME}/.local/bin/uv" ]; then
            "${HOME}/.local/bin/uv" pip install -r "${REQUIREMENTS}" --python "${VENV_DIR}"
        else
            "${VENV_DIR}/bin/pip" install -r "${REQUIREMENTS}"
        fi
    fi
fi

# 2. Check for Hugging Face Token if private
if [ -z "$HF_TOKEN" ] && [ ! -f "$HOME/.cache/huggingface/token" ]; then
    echo ""
    echo "⚠️  HF_TOKEN environment variable is not set and no cached login was found."
    echo "Please provide your Hugging Face Access Token (Read permission):"
    read -rp "HF Token: " HF_TOKEN_INPUT
    export HF_TOKEN="$HF_TOKEN_INPUT"
fi

# 3. Download files using the isolated venv python
echo "⬇️  Downloading dataset using isolated Python environment..."
"${VENV_DIR}/bin/python" - << EOF
import os
import sys
import tarfile
from huggingface_hub import hf_hub_download

repo_id = "${REPO_ID}"
token = os.environ.get("HF_TOKEN")

print("  -> Downloading pfs_metadata.sqlite3 (157MB)...")
db_path = hf_hub_download(
    repo_id=repo_id,
    filename="pfs_metadata.sqlite3",
    repo_type="dataset",
    token=token,
    local_dir="${SCRIPT_DIR}"
)
print(f"     ✅ Saved: {db_path}")

print("  -> Downloading extracted_targets.tar.gz (7.8GB)...")
tar_path = hf_hub_download(
    repo_id=repo_id,
    filename="extracted_targets.tar.gz",
    repo_type="dataset",
    token=token,
    local_dir="${SCRIPT_DIR}"
)
print(f"     ✅ Saved: {tar_path}")

print("📦 Extracting extracted_targets.tar.gz...")
with tarfile.open(tar_path, "r:gz") as tar:
    tar.extractall(path="${SCRIPT_DIR}")
print("     ✅ Extracted extracted_targets/ successfully!")
EOF

echo "============================================================"
echo "✅ Data download and extraction complete!"
echo "The virtual environment (.venv_viewer) is already configured."
echo "You can now run the web viewer immediately:"
echo "  cd pfs_target_viewer && ./run_viewer.sh"
echo "============================================================"
