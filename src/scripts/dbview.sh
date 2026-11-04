#!/usr/bin/env bash
# TRIAD database viewer: Datasette shows the SQLite database of the app in the browser. It is read-only.
#
# Usage (from any folder):
#     ./src/scripts/dbview.sh              open the viewer on http://127.0.0.1:8001
#     DBVIEW_PORT=8002 ./src/scripts/dbview.sh
#     DBVIEW_OPEN=no ./src/scripts/dbview.sh   do not open the browser
#
# The script:
#   1. makes .venv with uv if it is missing, and installs requirements.txt and requirements-dbview.txt;
#   2. runs "main.py ensure-db" (it builds the database only if it is missing);
#   3. writes the metadata of the viewer: the queries Q1 to Q14b of dml/03_select_queries.sql and the
#      schema queries (tables, columns, foreign keys, triggers, indexes);
#   4. starts Datasette on 127.0.0.1 and opens the browser. Ctrl+C stops it.
# The viewer reads the same database as the app (TRIAD_DB_PATH, or src/backend/data/triad.db).
# The app can run at the same time. Refresh a page to see new rows.
# The viewer shows all rows. It does not use the access rules of the app. This is correct only for synthetic data.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PORT="${DBVIEW_PORT:-8001}"
PY=.venv/bin/python

# The Python environment and the packages. uv skips the packages that are current.
if command -v uv >/dev/null 2>&1; then
    if [ ! -x "$PY" ]; then
        echo "Making the Python environment (.venv) with uv ..."
        uv venv --python 3.12 .venv
    fi
    uv pip install --quiet --python "$PY" -r requirements.txt -r requirements-dbview.txt
elif [ ! -x .venv/bin/datasette ]; then
    if [ ! -x "$PY" ]; then
        echo "uv is not installed and .venv does not exist. Install uv (https://docs.astral.sh/uv/) and run the script again." >&2
        exit 1
    fi
    "$PY" -m pip install --quiet -r requirements.txt -r requirements-dbview.txt
fi

# The port must be free.
if ! "$PY" -c "import socket, sys; s = socket.socket(); s.bind(('127.0.0.1', int(sys.argv[1])))" "$PORT" 2>/dev/null; then
    echo "Port $PORT is in use. Stop the other program, or use another port: DBVIEW_PORT=8002 ./src/scripts/dbview.sh" >&2
    exit 1
fi

"$PY" src/backend/main.py ensure-db
DB="$("$PY" src/scripts/dbview_metadata.py --print-db-path)"

TMPBASE="${TMPDIR:-/tmp}"
TMP="$(mktemp -d "${TMPBASE%/}/triad-dbview.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
"$PY" src/scripts/dbview_metadata.py --db "$DB" > "$TMP/metadata.json"

OPEN="--open"
case "${DBVIEW_OPEN:-yes}" in
    no|0|false) OPEN="" ;;
esac

echo "The database viewer starts on http://127.0.0.1:${PORT} (read-only). Ctrl+C stops it."
echo "Database: $DB"
# No exec: the trap must remove the metadata folder when Datasette stops.
.venv/bin/datasette serve "$DB" --host 127.0.0.1 --port "$PORT" --metadata "$TMP/metadata.json" \
    --setting sql_time_limit_ms 5000 --setting default_page_size 50 --setting max_returned_rows 2000 $OPEN
