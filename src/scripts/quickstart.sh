#!/usr/bin/env bash
# TRIAD quickstart: build everything, run the fast tests and serve the app on http://127.0.0.1:8000.
# Use it on macOS or Linux. On Windows, use WSL2.
#
# Usage (from any folder):
#     ./src/scripts/quickstart.sh             build everything, run the fast tests, serve the app
#     ./src/scripts/quickstart.sh --reset-db  the same, but build the database again first
#
# The script:
#   1. checks the prerequisites: uv (or Python 3.12), Node.js 20.19 or later (22.12 or later in version 22), npm,
#      and a free port;
#   2. makes src/backend/.env and src/frontend/.env from their .env.example files, if they are missing;
#   3. makes .venv (Python 3.12) if it is missing, and installs the pinned packages of requirements.txt;
#   4. runs "npm ci" if node_modules is missing or older than package-lock.json, then builds the frontend;
#   5. runs "main.py ensure-db" (it builds the database only if it is missing);
#   6. runs the fast tests (pytest -m "not slow");
#   7. runs "main.py serve": the API and the built frontend on one port.
# The first run downloads Python 3.12 and the packages (about 50 MB). It takes from 15 seconds to some minutes.
# The time changes with the speed of the network. A second run skips the work that is done and takes some seconds.
# The chat uses the fake LLM (no network, no key), unless src/backend/.env sets TRIAD_LLM=llm.
# One Ctrl+C stops the server.
# PORT is a shell variable only (for example: PORT=9000 ./src/scripts/quickstart.sh). The .env files do not set it.
# The script is safe for bash 3.2 (the bash of macOS).
set -euo pipefail

unset CDPATH
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$ROOT/src/scripts/quickstart.sh"
cd "$ROOT"

RESET=""
for arg in "$@"; do
    case "$arg" in
        --reset-db) RESET="yes" ;;
        -h|--help) sed -n '2,7p' "$SCRIPT" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $arg. Use --reset-db or no option." >&2; exit 2 ;;
    esac
done

PORT="${PORT:-8000}"
STEP=""
HINT=""

# On an error, tell the step that stopped. The command above the message tells the cause.
on_exit() {
    status=$?
    if [ "$status" -eq 130 ] && [ -n "$STEP" ]; then
        echo "" >&2
        echo "You stopped the quickstart (Ctrl+C) at step $STEP. Run the script again to continue." >&2
    elif [ "$status" -ne 0 ] && [ -n "$STEP" ]; then
        echo "" >&2
        echo "The quickstart stopped at step $STEP. Read the messages above, correct the problem and run the script again." >&2
        if [ -n "$HINT" ]; then
            echo "$HINT" >&2
        fi
    fi
}
trap on_exit EXIT

step() {
    STEP="$1 of 7 ($2)"
    HINT=""
    echo ""
    echo "== Step $1 of 7: $2 =="
}

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

# at_least VERSION MAJOR MINOR: true if VERSION (for example 3.45.1) is MAJOR.MINOR or later.
at_least() {
    local major minor rest
    major="${1%%.*}"
    rest="${1#*.}"
    minor="${rest%%.*}"
    case "$major.$minor" in
        *[!0-9.]*|.*|*.) return 1 ;;
    esac
    [ "$major" -gt "$2" ] || { [ "$major" -eq "$2" ] && [ "$minor" -ge "$3" ]; }
}

# Vite needs Node.js 20.19 or later in version 20, or 22.12 or later (package.json of vite: "engines").
node_ok() {
    local version="${1#v}" major
    major="${version%%.*}"
    case "$major" in
        ''|*[!0-9]*) return 1 ;;
    esac
    if [ "$major" -eq 20 ]; then
        at_least "$version" 20 19
    elif [ "$major" -eq 22 ]; then
        at_least "$version" 22 12
    else
        [ "$major" -ge 23 ]
    fi
}

# A connection succeeds only if a program listens on the port. Bash makes the connection (/dev/tcp).
port_in_use() {
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

check_port() {
    if port_in_use "$PORT"; then
        fail "Port $PORT is in use. Stop the program that uses it (to find it: lsof -nP -iTCP:$PORT -sTCP:LISTEN),
       or use a different port, for example: PORT=$((PORT + 1)) ./src/scripts/quickstart.sh"
    fi
}

# ---------------------------------------------------------------------------------------------
step 1 "check the prerequisites"

case "$PORT" in
    ''|*[!0-9]*) fail "PORT is \"$PORT\". Use a number from 1024 to 65535, for example PORT=8001." ;;
esac
if [ "$PORT" -lt 1024 ] || [ "$PORT" -gt 65535 ]; then
    fail "PORT is $PORT. Use a number from 1024 to 65535, for example PORT=8001."
fi
check_port
echo "Port $PORT is free."

UV=""
PYTHON312=""
if command -v uv >/dev/null 2>&1; then
    UV="uv"
    echo "$(uv --version) is installed. It makes the Python 3.12 environment (it gets Python 3.12 if it is missing)."
elif [ -x .venv/bin/python ]; then
    echo "uv is not installed. The script uses the .venv that exists, with pip."
else
    for candidate in python3.12 python3; do
        if command -v "$candidate" >/dev/null 2>&1 \
            && "$candidate" -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))' >/dev/null 2>&1; then
            PYTHON312="$candidate"
            break
        fi
    done
    if [ -z "$PYTHON312" ]; then
        fail "uv is not installed, and Python 3.12 is not found.
       Install uv (https://docs.astral.sh/uv/getting-started/installation/), for example:
           curl -LsSf https://astral.sh/uv/install.sh | sh
       Then open a new terminal and run this script again. uv gets Python 3.12 for you."
    fi
    echo "uv is not installed. The script uses $(command -v "$PYTHON312") ($("$PYTHON312" --version 2>&1)) and pip."
    echo "To get the same tools as the team, install uv: https://docs.astral.sh/uv/"
fi

if ! command -v node >/dev/null 2>&1; then
    fail "Node.js is not installed. Install Node.js 22.12 or later (or 20.19 or later) from https://nodejs.org/
       and run this script again."
fi
NODE_VERSION="$(node --version)"
if ! node_ok "$NODE_VERSION"; then
    fail "Node.js $NODE_VERSION is too old for Vite. Install Node.js 22.12 or later (or 20.19 or later in version 20)
       from https://nodejs.org/ and run this script again."
fi
if ! command -v npm >/dev/null 2>&1; then
    fail "npm is not installed. npm comes with Node.js (https://nodejs.org/)."
fi
echo "Node.js $NODE_VERSION and npm $(npm --version) are installed."

# The app uses the sqlite3 module of Python (step 3 checks its SQLite version).
# The sqlite3 command is optional. Only the plain SQL scripts in src/backend/models/relational/sql use it.
if command -v sqlite3 >/dev/null 2>&1; then
    SQLITE_CLI_VERSION="$(sqlite3 --version | cut -d ' ' -f 1)"
    if at_least "$SQLITE_CLI_VERSION" 3 43; then
        echo "The sqlite3 command is SQLite $SQLITE_CLI_VERSION (optional)."
    else
        echo "NOTE: the sqlite3 command is SQLite $SQLITE_CLI_VERSION. The plain SQL scripts need 3.43 or later."
        echo "      The app does not use this command, so the quickstart continues."
    fi
else
    echo "The sqlite3 command is not installed. It is optional: the app uses the sqlite3 module of Python."
fi

# ---------------------------------------------------------------------------------------------
step 2 "the local settings (.env files)"

# Git ignores the .env files. src/backend/.env holds the API keys,
# so only the owner of the file can read it (mode 600). The same rule as dev.sh.
for dir in src/backend src/frontend; do
    if [ ! -f "$dir/.env" ] && [ -f "$dir/.env.example" ]; then
        cp "$dir/.env.example" "$dir/.env"
        chmod 600 "$dir/.env"
        echo "Made $dir/.env from $dir/.env.example."
    elif [ -f "$dir/.env" ]; then
        echo "$dir/.env exists. The script does not change it."
    fi
done

# ---------------------------------------------------------------------------------------------
step 3 "the Python environment (.venv) and requirements.txt"
HINT="If .venv is broken, remove it (rm -rf .venv) and run this script again."

if [ -x .venv/bin/python ]; then
    echo ".venv exists. The script uses it."
elif [ -n "$UV" ]; then
    echo "Making the Python environment .venv (Python 3.12) with uv ..."
    uv venv --python 3.12 .venv
else
    echo "Making the Python environment .venv with $PYTHON312 -m venv ..."
    HINT="On Debian or Ubuntu, install the venv module first (sudo apt install python3.12-venv). Then remove .venv and run this script again."
    "$PYTHON312" -m venv .venv
    HINT="If .venv is broken, remove it (rm -rf .venv) and run this script again."
fi

PYTHON_VERSION="$(.venv/bin/python -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
case "$PYTHON_VERSION" in
    3.12.*) echo ".venv uses Python $PYTHON_VERSION." ;;
    *) fail ".venv uses Python $PYTHON_VERSION, not Python 3.12. Remove .venv (rm -rf .venv) and run this script again." ;;
esac

# requirements.txt pins each package to one version (==). It has no hashes.
echo "Installing the packages of requirements.txt (the installer skips the packages that are current) ..."
if [ -n "$UV" ]; then
    uv pip install --python .venv/bin/python -r requirements.txt
else
    if ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
        fail ".venv has no pip. Install uv (https://docs.astral.sh/uv/), or remove .venv and run this script again."
    fi
    .venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt
fi

if ! .venv/bin/python -c 'import sqlite3, sys; sys.exit(sqlite3.sqlite_version_info < (3, 43))'; then
    fail "The sqlite3 module of Python uses SQLite $(.venv/bin/python -c 'import sqlite3; print(sqlite3.sqlite_version)').
       TRIAD needs SQLite 3.43 or later. Install uv (its Python 3.12 has a new SQLite), remove .venv and run this script again."
fi
echo "The sqlite3 module of Python uses SQLite $(.venv/bin/python -c 'import sqlite3; print(sqlite3.sqlite_version)')."

# ---------------------------------------------------------------------------------------------
step 4 "the frontend packages and the frontend build"

# npm writes node_modules/.package-lock.json at the end of each install.
if [ ! -f src/frontend/node_modules/.package-lock.json ] \
    || [ src/frontend/package-lock.json -nt src/frontend/node_modules/.package-lock.json ]; then
    echo "Installing the frontend packages of package-lock.json (npm ci) ..."
    HINT="npm ci needs the network the first time."
    npm --prefix src/frontend ci --no-audit --no-fund
else
    echo "The frontend packages are current (node_modules is newer than package-lock.json). npm ci is not necessary."
fi
HINT=""
echo "Building the frontend (npm run build) into src/frontend/dist ..."
npm --prefix src/frontend run build

# ---------------------------------------------------------------------------------------------
step 5 "the database (main.py ensure-db${RESET:+ --reset-db})"

.venv/bin/python src/backend/main.py ensure-db ${RESET:+--reset-db}

# ---------------------------------------------------------------------------------------------
step 6 "the fast tests"

.venv/bin/python -m pytest -q -m "not slow"
echo "The fast tests pass. To run all the tests (also the slow tests), run: .venv/bin/python -m pytest -q"

# ---------------------------------------------------------------------------------------------
step 7 "serve the app"

# Make sure again that no program took the port during the steps above.
check_port
export PORT
echo "The chat uses the fake LLM (no network, no key), unless src/backend/.env sets TRIAD_LLM=llm."
echo "TRIAD starts on http://127.0.0.1:${PORT} (API: /api, documentation: /docs)."
echo ""
echo "    Open http://127.0.0.1:${PORT} and select Demo guide."
echo ""
echo "To see the tables of the database (read-only), run ./src/scripts/dbview.sh in another terminal."
echo "Press Ctrl+C to stop the server."

# The server replaces this script (exec). Thus one Ctrl+C stops it, and no process stays.
trap - EXIT
exec .venv/bin/python src/backend/main.py serve
