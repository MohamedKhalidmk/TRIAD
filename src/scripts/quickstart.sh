#!/usr/bin/env bash
# TRIAD quickstart: build everything, run the fast tests and serve the app on http://127.0.0.1:8000.
# Use it on macOS or Linux. On Windows, use WSL2.
#
# Usage (from any folder):
#     ./src/scripts/quickstart.sh                  build everything, run the fast tests, serve the app
#     ./src/scripts/quickstart.sh --store STORE    choose the data store of the app (see below)
#     ./src/scripts/quickstart.sh --reset-db       build the SQLite database again first
#     ./src/scripts/quickstart.sh --reset-kg       build the knowledge graph again (this deletes the writes of KG mode)
#     ./src/scripts/quickstart.sh --check          do all the steps, start the server, check GET /api/health, stop it
#     ./src/scripts/quickstart.sh --help           show this help
#
# The stores (--store):
#     virtuoso   the knowledge graph in Virtuoso 7.2 in Docker (the default when Docker runs)
#     oxigraph   the knowledge graph in Oxigraph, inside the Python process (no Docker; the default when Docker does not run)
#     sqlite     the relational database of Milestone 4 (the same app, with no knowledge graph)
# With no --store, the script uses virtuoso if "docker info" works. If not, it uses oxigraph and says why.
#
# The script:
#   1. checks the prerequisites: uv (or Python 3.12), Node.js 20.19 or later (22.12 or later in version 22), npm,
#      a free port, and Docker (for virtuoso); the store is chosen before this step;
#   2. makes src/backend/.env and src/frontend/.env from their .env.example files, if they are missing;
#   3. makes .venv (Python 3.12) if it is missing, and installs the pinned packages of requirements.txt
#      (it includes requirements-kg.txt);
#   4. runs "npm ci" if node_modules is missing or older than package-lock.json, then builds the frontend;
#   5. runs "main.py ensure-db" (it builds the database only if it is missing);
#   6. virtuoso only: runs "kg.sh up" and "kg.sh init" (start Virtuoso, make its user and its permissions);
#   7. virtuoso and oxigraph: runs "main.py ensure-kg --store STORE". It builds the knowledge graph from the
#      database only if the build marker of the store is not current, so a second run is fast;
#   8. runs the fast tests (pytest -m "not slow");
#   9. runs "main.py serve --store STORE": the API and the built frontend on one port.
# The number of steps is 7 for sqlite, 8 for oxigraph and 9 for virtuoso.
# The first run downloads Python 3.12 and the packages (about 50 MB). With virtuoso it also pulls the Docker image.
# It takes from some minutes to more minutes, with the speed of the network.
# A second run skips the work that is done. The fast tests (about 1.5 minutes) are then most of the time.
# A rebuild of the knowledge graph (the first run, a changed database, or --reset-kg) deletes the writes that
# the app made in KG mode. A second run with no change does not rebuild it.
# The chat uses the fake LLM (no network, no key), unless src/backend/.env sets TRIAD_LLM=llm.
# One Ctrl+C stops the server. Virtuoso keeps running: stop it with ./src/scripts/kg.sh down.
# PORT is a shell variable only (for example: PORT=9000 ./src/scripts/quickstart.sh). The .env files do not set it.
# KG_HTTP_PORT (the port of Virtuoso) and KG_PYTHON are settings of kg.sh. See: ./src/scripts/kg.sh help
# The script is safe for bash 3.2 (the bash of macOS).
set -euo pipefail

unset CDPATH
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$ROOT/src/scripts/quickstart.sh"
cd "$ROOT"

RESET=""
RESET_KG=""
STORE=""
CHECK=""

usage() {
    awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$SCRIPT"
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --reset-db) RESET="yes" ;;
        --reset-kg) RESET_KG="yes" ;;
        --check) CHECK="yes" ;;
        --store)
            if [ "$#" -lt 2 ]; then
                echo "--store needs a value: sqlite, oxigraph or virtuoso." >&2
                exit 2
            fi
            STORE="$2"
            shift ;;
        --store=*) STORE="${1#--store=}" ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1. Use --store, --reset-db, --reset-kg, --check or --help." >&2; exit 2 ;;
    esac
    shift
done
case "$STORE" in
    ''|sqlite|oxigraph|virtuoso) ;;
    *) echo "Unknown store: $STORE. Use --store sqlite, --store oxigraph or --store virtuoso." >&2; exit 2 ;;
esac
if [ "$STORE" = sqlite ] && [ -n "$RESET_KG" ]; then
    echo "--reset-kg does not work with --store sqlite (SQLite has no knowledge graph)." >&2
    exit 2
fi

PORT="${PORT:-8000}"
STEP=""
HINT=""
STEPS=7
N=0

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
    N=$((N + 1))
    STEP="$N of $STEPS ($1)"
    HINT=""
    echo ""
    echo "== Step $N of $STEPS: $1 =="
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

# True if "docker info" works within 20 seconds (macOS has no timeout command).
docker_ok() {
    command -v docker >/dev/null 2>&1 || return 1
    docker info >/dev/null 2>&1 &
    local pid=$! waited=0
    while kill -0 "$pid" 2>/dev/null; do
        if [ "$waited" -ge 20 ]; then
            kill "$pid" 2>/dev/null || true
            return 1
        fi
        sleep 1
        waited=$((waited + 1))
    done
    wait "$pid"
}

# Choose the store before step 1, so that the step count is known. Step 1 prints STORE_NOTE.
# KG_ISQL means that Virtuoso runs without Docker (see kg.sh help). Then the script does not use "kg.sh up".
STORE_NOTE=""
HAVE_DOCKER=""
if [ -n "${KG_ISQL:-}" ] || docker_ok; then
    HAVE_DOCKER="yes"
fi
if [ -z "$STORE" ]; then
    if [ -n "$HAVE_DOCKER" ]; then
        STORE="virtuoso"
        STORE_NOTE="Docker runs, so the store is virtuoso (the knowledge graph in Virtuoso 7.2)."
    else
        STORE="oxigraph"
        if command -v docker >/dev/null 2>&1; then
            WHY="Docker is installed, but it does not run"
        else
            WHY="Docker is not installed"
        fi
        STORE_NOTE="$WHY, so the store is oxigraph (the knowledge graph inside the Python process, no Docker).
To use Virtuoso: install and start Docker Desktop (https://docs.docker.com/get-docker/) and run this script again.
To use the SQLite database of Milestone 4: run this script with --store sqlite."
    fi
elif [ "$STORE" = virtuoso ] && [ -z "$HAVE_DOCKER" ]; then
    fail "--store virtuoso needs Docker, but Docker does not run (or it is not installed).
       Install and start Docker Desktop (https://docs.docker.com/get-docker/) and run this script again,
       or use --store oxigraph (no Docker) or --store sqlite."
fi
case "$STORE" in
    sqlite) STEPS=7 ;;
    oxigraph) STEPS=8 ;;
    virtuoso) STEPS=9 ;;
esac

# ---------------------------------------------------------------------------------------------
step "check the prerequisites"

echo "Data store: $STORE."
if [ -n "$STORE_NOTE" ]; then
    echo "$STORE_NOTE"
fi
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
step "the local settings (.env files)"

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
step "the Python environment (.venv) and requirements.txt"
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

# requirements.txt pins each package to one version (==). It has no hashes. It includes requirements-kg.txt.
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
step "the frontend packages and the frontend build"

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
step "the database (main.py ensure-db${RESET:+ --reset-db})"

.venv/bin/python src/backend/main.py ensure-db ${RESET:+--reset-db}

# ---------------------------------------------------------------------------------------------
if [ "$STORE" = virtuoso ]; then
    step "Virtuoso (kg.sh up, kg.sh init)"
    if [ -n "${KG_ISQL:-}" ]; then
        echo "KG_ISQL is set: Virtuoso runs without Docker. The script does not run \"kg.sh up\"."
    else
        HINT="The first run pulls the Virtuoso image. It needs the network and some minutes. To see the container: docker ps -a"
        ./src/scripts/kg.sh up
    fi
    HINT="To start again from an empty Virtuoso: ./src/scripts/kg.sh reset (this deletes all its data)."
    ./src/scripts/kg.sh init
fi

if [ "$STORE" != sqlite ]; then
    step "the knowledge graph (main.py ensure-kg --store $STORE${RESET_KG:+ --reset-kg})"
    if [ "$STORE" = virtuoso ]; then
        # ensure-kg exports the database, runs "kg.sh load --no-export" and writes the build marker.
        # A plain "kg.sh load" writes no marker, so the script does not use it.
        HINT="To see the state of Virtuoso: ./src/scripts/kg.sh status"
    fi
    echo "The first build exports the database and loads it (some seconds). If the build marker is current, nothing changes."
    .venv/bin/python src/backend/main.py ensure-kg --store "$STORE" ${RESET_KG:+--reset-kg}
fi

# ---------------------------------------------------------------------------------------------
step "the fast tests"

# The tests make their own settings. The store of the shell must not change them.
TRIAD_STORE=sqlite .venv/bin/python -m pytest -q -m "not slow"
echo "The fast tests pass. To run all the tests (also the slow tests), run: .venv/bin/python -m pytest -q"

# ---------------------------------------------------------------------------------------------
step "serve the app"

# Make sure again that no program took the port during the steps above.
check_port
export PORT
echo "Data store: $STORE."
echo "The chat uses the fake LLM (no network, no key), unless src/backend/.env sets TRIAD_LLM=llm."

if [ -n "$CHECK" ]; then
    echo "Check mode: the script starts the server, asks GET /api/health, and stops the server."
    HINT="The server log is above."
    .venv/bin/python src/backend/main.py serve --store "$STORE" &
    SERVER_PID=$!
    trap 'kill "$SERVER_PID" 2>/dev/null || true' INT TERM
    HEALTH=""
    waited=0
    while [ "$waited" -lt 120 ]; do
        if ! kill -0 "$SERVER_PID" 2>/dev/null; then
            fail "The server stopped before it answered. Read the messages above."
        fi
        if HEALTH="$(curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/api/health" 2>/dev/null)"; then
            break
        fi
        HEALTH=""
        sleep 1
        waited=$((waited + 1))
    done
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
    [ -n "$HEALTH" ] || fail "The server did not answer GET /api/health in 120 seconds."
    echo "GET /api/health: $HEALTH"
    REPORTED="$(printf '%s' "$HEALTH" | .venv/bin/python -c 'import json, sys; print(json.load(sys.stdin).get("store"))')"
    [ "$REPORTED" = "$STORE" ] || fail "The health check reports the store \"$REPORTED\", not \"$STORE\"."
    echo "Check passed: the server answers and its store is $REPORTED."
    trap - EXIT
    exit 0
fi

echo "TRIAD starts on http://127.0.0.1:${PORT} (API: /api, documentation: /docs)."
echo ""
echo "    Open http://127.0.0.1:${PORT} and select Demo guide."
echo ""
echo "Data store: $STORE."
if [ "$STORE" = virtuoso ]; then
    ./src/scripts/kg.sh open
    echo ""
fi
if [ "$STORE" != sqlite ]; then
    echo "NOTE: a rebuild of the knowledge graph (a changed database, or --reset-kg) deletes the writes that the app made in KG mode."
    echo ""
fi
echo "To see the tables of the SQLite database (read-only), run ./src/scripts/dbview.sh in another terminal."
echo "Press Ctrl+C to stop the server."

# The server replaces this script (exec). Thus one Ctrl+C stops it, and no process stays.
trap - EXIT
exec .venv/bin/python src/backend/main.py serve --store "$STORE"
