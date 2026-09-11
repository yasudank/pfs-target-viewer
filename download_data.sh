#!/usr/bin/env bash
set -e

REPO_ID="Oakleaf67/pfs-target-data"

echo "============================================================"
echo "  🌌 PFS Target & Spectrum Viewer - Data Downloader"
echo "  📦 Dataset: $REPO_ID (Hugging Face Private)"
echo "============================================================"

# Check for Hugging Face Token if private
if [ -z "$HF_TOKEN" ] && [ ! -f "$HOME/.cache/huggingface/token" ]; then
    echo ""
    echo "⚠️  HF_TOKEN environment variable is not set and no cached login was found."
    echo "Please provide your Hugging Face Access Token (Read permission):"
    read -rp "HF Token: " HF_TOKEN_INPUT
    export HF_TOKEN="$HF_TOKEN_INPUT"
fi

TOKEN_OPT=""
if [ -n "$HF_TOKEN" ]; then
    TOKEN_OPT="--token $HF_TOKEN"
fi

# Ensure hf CLI or python huggingface_hub is available
if command -v hf >/dev/null 2>&1; then
    echo "⬇️  Downloading pfs_metadata.sqlite3..."
    hf download "$REPO_ID" pfs_metadata.sqlite3 --repo-type dataset $TOKEN_OPT --local-dir .

    echo "⬇️  Downloading extracted_targets.tar.gz (7.8 GB)..."
    hf download "$REPO_ID" extracted_targets.tar.gz --repo-type dataset $TOKEN_OPT --local-dir .
elif python3 -c "import huggingface_hub" >/dev/null 2>&1; then
    echo "⬇️  Downloading dataset via python huggingface_hub..."
    python3 -c "
from huggingface_hub import hf_hub_download
import os

token = os.environ.get('HF_TOKEN')
print('Downloading pfs_metadata.sqlite3...')
hf_hub_download(repo_id='$REPO_ID', filename='pfs_metadata.sqlite3', repo_type='dataset', token=token, local_dir='.')
print('Downloading extracted_targets.tar.gz...')
hf_hub_download(repo_id='$REPO_ID', filename='extracted_targets.tar.gz', repo_type='dataset', token=token, local_dir='.')
"
else
    echo "❌ Error: Neither 'hf' CLI nor 'huggingface_hub' Python library was found."
    echo "Please install huggingface_hub: pip install huggingface_hub"
    exit 1
fi

echo "📦 Extracting extracted_targets.tar.gz..."
tar -xzvf extracted_targets.tar.gz

echo "============================================================"
echo "✅ Data download and extraction complete!"
echo "Now you can run the web viewer:"
echo "  cd pfs_target_viewer && ./run_viewer.sh"
echo "============================================================"
