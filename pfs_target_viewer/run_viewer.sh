#!/usr/bin/env bash
# ==============================================================================
# PFS Target & Spectrum Viewer - Launcher Script
# Automatically creates isolated venv and starts the web application.
# Does NOT depend on the PFS pipeline environment.
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

VENV_DIR="${SCRIPT_DIR}/.venv_viewer"
PORT="${PORT:-8090}"
HOST="${HOST:-0.0.0.0}"

echo "============================================================"
echo "  🌌 PFS Target & Spectrum Viewer Launcher"
echo "============================================================"

# 1. Check or create virtual environment
if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating dedicated virtual environment in ${VENV_DIR}..."
    if command -v /home/yasuda/.local/bin/uv &> /dev/null; then
        /home/yasuda/.local/bin/uv venv "${VENV_DIR}"
        /home/yasuda/.local/bin/uv pip install -r "${SCRIPT_DIR}/requirements.txt" --python "${VENV_DIR}"
    elif command -v uv &> /dev/null; then
        uv venv "${VENV_DIR}"
        uv pip install -r "${SCRIPT_DIR}/requirements.txt" --python "${VENV_DIR}"
    else
        python3 -m venv "${VENV_DIR}"
        "${VENV_DIR}/bin/pip" install --upgrade pip
        "${VENV_DIR}/bin/pip" install -r "${SCRIPT_DIR}/requirements.txt"
    fi
    echo "Virtual environment ready."
fi

# 2. Start application
echo "Starting server on http://${HOST}:${PORT}..."
echo "Press Ctrl+C to stop the server."
echo "============================================================"

exec "${VENV_DIR}/bin/python" "${SCRIPT_DIR}/app.py" --host "${HOST}" --port "${PORT}" "$@"
