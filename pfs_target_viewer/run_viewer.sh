#!/usr/bin/env bash
# ==============================================================================
# PFS Target & Spectrum Viewer - Launcher Script
# Automatically creates isolated venv and starts the web application.
# Does NOT depend on the PFS pipeline environment.
#
# Usage:
#   ./run_viewer.sh [TARGET_DIR] [OPTIONS]
#
# Examples:
#   ./run_viewer.sh /path/to/dataset
#   ./run_viewer.sh --dir /path/to/dataset
#   ./run_viewer.sh /path/to/dataset --port 8080
#   ./run_viewer.sh --help
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

VENV_DIR="${SCRIPT_DIR}/.venv_viewer"
PORT="${PORT:-8090}"
HOST="${HOST:-0.0.0.0}"

# 1. Check or create virtual environment
if [ ! -d "${VENV_DIR}" ]; then
    echo "============================================================"
    echo "  🌌 PFS Target & Spectrum Viewer Launcher"
    echo "============================================================"
    echo "Creating dedicated virtual environment in ${VENV_DIR}..."
    if command -v uv &> /dev/null; then
        uv venv "${VENV_DIR}"
        uv pip install -r "${SCRIPT_DIR}/requirements.txt" --python "${VENV_DIR}"
    elif [ -x "${HOME}/.local/bin/uv" ]; then
        "${HOME}/.local/bin/uv" venv "${VENV_DIR}"
        "${HOME}/.local/bin/uv" pip install -r "${SCRIPT_DIR}/requirements.txt" --python "${VENV_DIR}"
    else
        python3 -m venv "${VENV_DIR}"
        "${VENV_DIR}/bin/pip" install --upgrade pip
        "${VENV_DIR}/bin/pip" install -r "${SCRIPT_DIR}/requirements.txt"
    fi
    echo "Virtual environment ready."
fi

# 2. Check if help is requested
for arg in "$@"; do
    if [ "$arg" == "-h" ] || [ "$arg" == "--help" ]; then
        exec "${VENV_DIR}/bin/python" "${SCRIPT_DIR}/app.py" "$@"
    fi
done

# 3. Start application
echo "============================================================"
echo "  🌌 PFS Target & Spectrum Viewer Launcher"
echo "============================================================"
echo "Starting server on http://${HOST}:${PORT}..."
echo "Press Ctrl+C to stop the server."
echo "============================================================"

exec "${VENV_DIR}/bin/python" "${SCRIPT_DIR}/app.py" --host "${HOST}" --port "${PORT}" "$@"
