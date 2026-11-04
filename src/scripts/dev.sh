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
# PORT (the API, default 8000) and VITE_PORT (the frontend, default 5173) are shell variables only
# (for example: PORT=9000 VITE_PORT=5200 ./src/scripts/dev.sh). The .env files do not set them.
# The script stops at the start if a port is in use.
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

PORT="${PORT:-8000}"
VITE_PORT="${VITE_PORT:-5173}"

# A connection succeeds only if a program listens on the port. Bash makes the connection (/dev/tcp).
port_in_use() {
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

for item in "PORT:$PORT" "VITE_PORT:$VITE_PORT"; do
    name="${item%%:*}"
    port="${item#*:}"
    case "$port" in
        ''|*[!0-9]*) echo "$name is \"$port\". Use a port number, for example $name=9000." >&2; exit 2 ;;
    esac
    if [ "$name" = VITE_PORT ] && [ ! -f src/frontend/package.json ]; then
        continue
    fi
    if port_in_use "$port"; then
        echo "Port $port ($name) is in use. Stop the program that uses it (to find it: lsof -nP -iTCP:$port -sTCP:LISTEN)," >&2
        echo "or use a different port, for example: $name=$((port + 1)) ./src/scripts/dev.sh" >&2
        exit 1
    fi
done
if [ "$PORT" = "$VITE_PORT" ]; then
    echo "PORT and VITE_PORT are both $PORT. Use two different ports." >&2
    exit 2
fi

# Stop all child processes on Ctrl+C, on an error and at the end (kill 0 sends SIGTERM to all of them).
# Ctrl+C also sends SIGINT to uvicorn. If the reloader of uvicorn gets a second signal at the same time,
# it can stop forever and keep the port. Thus, after Ctrl+C, the script waits 1 second before kill 0.
trap 'trap - TERM EXIT; trap "" INT; sleep 1; kill 0' INT TERM
trap 'trap - INT TERM EXIT; kill 0' EXIT

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
    echo "The frontend starts on http://127.0.0.1:${VITE_PORT}. It sends /api to ${TRIAD_API_URL}."
    npm --prefix src/frontend run dev -- --port "$VITE_PORT" 2>&1 | prefix "[web]" &
else
    echo "src/frontend/package.json does not exist. Only the API starts."
fi

wait
