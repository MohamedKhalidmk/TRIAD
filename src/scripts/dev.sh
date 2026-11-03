#!/usr/bin/env bash
# TRIAD development mode: the API with hot reload on port 8000, and the frontend (Vite) on port 5173.
#
# Usage (from any folder):
#     ./src/scripts/dev.sh              start the API and the frontend
#     ./src/scripts/dev.sh --reset-db   build the database again first
#
# The script:
#   1. makes .venv with uv and installs requirements.txt, if this is necessary;
#   2. runs "main.py ensure-db" (it builds the database only if it is missing);
#   3. starts uvicorn with --reload on src/backend (log prefix [api]);
#   4. if src/frontend/package.json exists: runs npm install if node_modules is missing,
#      then starts the Vite dev server (log prefix [web]).
# One Ctrl+C stops the API and the frontend.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

RESET=""
for arg in "$@"; do
    case "$arg" in
        --reset-db) RESET="yes" ;;
        *) echo "Unknown option: $arg. Use --reset-db or no option." >&2; exit 2 ;;
    esac
done

# Stop all child processes on Ctrl+C, on an error and at the end.
trap 'trap - INT TERM EXIT; kill 0' INT TERM EXIT

prefix() {
    while IFS= read -r line || [ -n "$line" ]; do
        printf '%s %s\n' "$1" "$line"
    done
}

if [ ! -x .venv/bin/uvicorn ]; then
    if ! command -v uv >/dev/null 2>&1; then
        echo "uv is not installed. Install it from https://docs.astral.sh/uv/ and run this script again." >&2
        exit 1
    fi
    if [ ! -x .venv/bin/python ]; then
        echo "Making the Python environment .venv (Python 3.12) ..."
        uv venv --python 3.12 .venv
    fi
    echo "Installing the Python packages of requirements.txt ..."
    uv pip install --python .venv/bin/python -r requirements.txt
fi

.venv/bin/python src/backend/main.py ensure-db ${RESET:+--reset-db}

export PYTHONUNBUFFERED=1
PORT="${PORT:-8000}"
echo "The API starts on http://127.0.0.1:${PORT} (documentation: http://127.0.0.1:${PORT}/docs)."
.venv/bin/uvicorn main:create_app --factory --app-dir src/backend --host 127.0.0.1 --port "$PORT" \
    --reload --reload-dir src/backend 2>&1 | prefix "[api]" &

if [ -f src/frontend/package.json ]; then
    if [ ! -d src/frontend/node_modules ]; then
        echo "Installing the frontend packages (npm install) ..."
        npm --prefix src/frontend install 2>&1 | prefix "[web]"
    fi
    echo "The frontend starts on http://127.0.0.1:5173."
    npm --prefix src/frontend run dev 2>&1 | prefix "[web]" &
else
    echo "src/frontend/package.json does not exist. Only the API starts."
fi

wait
