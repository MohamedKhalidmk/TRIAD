#!/usr/bin/env bash
# TRIAD development mode: the API with hot reload on port 8000, and the frontend (Vite) on port 5173.
#
# Usage (from any folder):
#     ./src/scripts/dev.sh              start the API and the frontend
#     ./src/scripts/dev.sh --reset-db   build the database again first
#
# The script:
#   1. makes src/backend/.env and src/frontend/.env from their .env.example files, if they are missing;
#   2. makes .venv with uv if it is missing, and installs requirements.txt (uv skips the packages that are current);
#   3. runs "main.py ensure-db" (it builds the database only if it is missing);
#   4. starts uvicorn with --reload on src/backend (log prefix [api]);
#   5. if src/frontend/package.json exists: runs npm install if node_modules is missing,
#      then starts the Vite dev server (log prefix [web]). Vite sends /api to the API (TRIAD_API_URL).
# One Ctrl+C stops the API and the frontend.
# The API key of the LLM mode goes in src/backend/.env. After you change a .env file, start the script again.
# PORT is a shell variable only (for example: PORT=9000 ./src/scripts/dev.sh). The .env files do not set it.
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

# The local settings. Git ignores the .env files. src/backend/.env holds the API keys,
# so only the owner of the file can read it (mode 600).
for dir in src/backend src/frontend; do
    if [ ! -f "$dir/.env" ] && [ -f "$dir/.env.example" ]; then
        cp "$dir/.env.example" "$dir/.env"
        chmod 600 "$dir/.env"
        echo "Made $dir/.env from $dir/.env.example."
        if [ "$dir" = src/backend ]; then
            echo "To use the LLM mode, set TRIAD_LLM=llm and your API key in src/backend/.env."
        fi
    fi
done

if command -v uv >/dev/null 2>&1; then
    if [ ! -x .venv/bin/python ]; then
        echo "Making the Python environment .venv (Python 3.12) ..."
        uv venv --python 3.12 .venv
    fi
    echo "Checking the Python packages of requirements.txt ..."
    uv pip install --quiet --python .venv/bin/python -r requirements.txt
elif [ ! -x .venv/bin/uvicorn ]; then
    echo "uv is not installed. Install it from https://docs.astral.sh/uv/ and run this script again." >&2
    exit 1
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
    # Vite sends /api to the API that this script starts. The shell value wins over src/frontend/.env.
    export TRIAD_API_URL="http://127.0.0.1:${PORT}"
    echo "The frontend starts on http://127.0.0.1:5173. It sends /api to ${TRIAD_API_URL}."
    npm --prefix src/frontend run dev 2>&1 | prefix "[web]" &
else
    echo "src/frontend/package.json does not exist. Only the API starts."
fi

wait
