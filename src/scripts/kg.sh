#!/usr/bin/env bash
# TRIAD knowledge graph: Virtuoso 7.2 in Docker, with the TRIAD graphs, the user triad and the permissions.
#
# Usage (from any folder):
#     ./src/scripts/kg.sh up               start Virtuoso (the first run makes the container and its volume)
#     ./src/scripts/kg.sh init [--strict]  make the user triad, and set the roles and the graph permissions
#     ./src/scripts/kg.sh load [--seed] [--no-export]
#                                          load the ontology into the TBox graph and the data into the ABox graph
#     ./src/scripts/kg.sh status           show the container, the triples of each graph and the access rules
#     ./src/scripts/kg.sh sparql FILE [--only ID[,ID...]] [--max-rows N] [--keep-going]
#                                          run the queries and the updates of a .sparql file
#     ./src/scripts/kg.sh open             show the URLs of Conductor and of the SPARQL endpoint
#     ./src/scripts/kg.sh down             stop the container (the data stays in the volume)
#     ./src/scripts/kg.sh reset            remove the container and its volume (this deletes all the data)
#     ./src/scripts/kg.sh help             show this help
#
# The usual order: up, init, load. Then: status, sparql FILE, open. At the end: down.
# up: the container triad-virtuoso listens on 127.0.0.1 only. The volume triad-virtuoso-db keeps the data.
# init (manual 5.2.3): the account SPARQL (the user of /sparql, no login) gets SPARQL_SELECT and SPARQL_UPDATE.
#     Graph permissions let it write only the ABox and the scratch graphs. The user triad (/sparql-auth,
#     digest login) can write the four TRIAD graphs, and LOAD into the TBox and the scratch graphs.
#     "init --strict" removes SPARQL_UPDATE from the account SPARQL and the write permissions of the users
#     with no login. You can run "init" and "init --strict" again.
# load: if main.py has the command export-kg, load first runs "main.py ensure-db" and "main.py export-kg".
#     Then it clears the TBox and ABox graphs, loads models/semantic/triad.owl and TRIAD_KG_DIR/triad_kg.nt.gz
#     with the bulk loader, and checks the result (the load list, and the counts of kg_report.json).
#     "load --seed" loads the scenario graph models/semantic/kg/triad_kg_seed.rdf into the ABox graph.
#     "load --no-export" loads the export that is in TRIAD_KG_DIR, with no ensure-db and no export-kg
#     ("main.py ensure-kg --store virtuoso" runs it after its own export).
# sparql FILE: a marker line "# ID. Title" (Q1, U1, QA, B.1, ...) starts each operation. Queries go to
#     TRIAD_SPARQL_QUERY_URL; updates go to TRIAD_SPARQL_UPDATE_URL as TRIAD_SPARQL_USER. FILE can also be
#     the name of a file in src/backend/models/semantic/sparql/. See infrastructure/rdf/sparql_script.py.
# The settings come from the shell, else from src/backend/.env, else the defaults (see .env.example):
#     KG_HTTP_PORT (8890), TRIAD_VIRTUOSO_DBA_PASSWORD (dba), TRIAD_SPARQL_USER (triad),
#     TRIAD_SPARQL_PASSWORD (triad), TRIAD_SPARQL_QUERY_URL, TRIAD_SPARQL_UPDATE_URL, TRIAD_KG_DIR.
#     The image uses TRIAD_VIRTUOSO_DBA_PASSWORD and its other settings only at the first start of an empty
#     volume. After a change, run "kg.sh reset" (this deletes all the data) and "kg.sh up".
#     "up" uses KG_HTTP_PORT when it makes the container. After a change, run "docker rm -f triad-virtuoso"
#     and "kg.sh up" (the data stays). After a change of TRIAD_SPARQL_PASSWORD, run "kg.sh init".
# Other shell variables: KG_PYTHON (the Python of the helpers, default .venv/bin/python);
#     KG_ISQL (an isql command, for example isql-vt, for a Virtuoso without Docker on port 1111).
#     With KG_ISQL, init, load and status use that isql, and load uses the folders of this computer:
#     add them to DirsAllowed in virtuoso.ini. up, down and reset are then not available.
# The script is safe for bash 3.2 (the bash of macOS).
set -euo pipefail

unset CDPATH
CALLER_DIR="$(pwd)"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$ROOT/src/scripts/kg.sh"
cd "$ROOT"

PY="${KG_PYTHON:-.venv/bin/python}"
CONTAINER="triad-virtuoso"
VOLUME="triad-virtuoso-db"
# Virtuoso Open Source 7.2 (decision D3). The digest pins the image; the tag is for people.
IMAGE="openlink/virtuoso-opensource-7:7.2.17-r25.1-g2850f18-ubuntu@sha256:0dbe1ab4fa0cb7bbafc1f6c0c2b0a5d6f22d918dbd17672f2ddb24580aa6756a"
WAIT_SECONDS=60
COMMAND=""

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

usage() {
    awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$SCRIPT"
}

# Run a Python module of src/backend (for example infrastructure.rdf.counts).
pymod() {
    PYTHONPATH="$ROOT/src/backend${PYTHONPATH:+:$PYTHONPATH}" "$PY" -m "$@"
}

# ---------------------------------------------------------------------------------------------
# Settings

# Read the settings through the backend config (src/scripts/kg_settings.py). Each line is NAME=value.
# The lines are values only: the script does not run them as shell code.
load_settings() {
    local lines line name value
    if [ ! -x "$PY" ]; then
        fail "$PY does not exist. Run ./src/scripts/quickstart.sh once (it makes .venv), or set KG_PYTHON."
    fi
    lines="$("$PY" src/scripts/kg_settings.py)" || fail "kg_settings.py cannot read the settings (see the message above)."
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        name="${line%%=*}"
        value="${line#*=}"
        case "$name" in
            KG_HTTP_PORT|KG_DIR|KG_SEMANTIC_DIR|KG_QUERY_URL|KG_UPDATE_URL|KG_SPARQL_USER|KG_SPARQL_PASSWORD|\
            KG_DBA_PASSWORD|KG_DBA_PASSWORD_IS_DEFAULT|KG_TBOX|KG_ABOX|KG_SCRATCH|KG_META)
                printf -v "$name" '%s' "$value" ;;
            *) fail "kg_settings.py wrote an unknown setting: $name" ;;
        esac
    done <<EOF
$lines
EOF
    if [ -n "${KG_ISQL:-}" ]; then
        IMPORT_KG="$KG_DIR"
        IMPORT_SEMANTIC="$KG_SEMANTIC_DIR"
    else
        IMPORT_KG="/import/kg"
        IMPORT_SEMANTIC="/import/semantic"
    fi
}

# ---------------------------------------------------------------------------------------------
# Docker and the container

need_docker() {
    if [ -n "${KG_ISQL:-}" ]; then
        fail "KG_ISQL is set, so Virtuoso runs without Docker, and \"kg.sh $COMMAND\" is not available.
       Start and stop that Virtuoso with its own tools."
    fi
    command -v docker >/dev/null 2>&1 || fail "Docker is not installed. Install Docker Desktop (https://docs.docker.com/get-docker/),
       or use Virtuoso without Docker (see the README) with KG_ISQL=isql-vt."
    docker info >/dev/null 2>&1 || fail "Docker does not run. Start Docker Desktop (or the Docker service) and run the command again."
}

# The state of the container: running, exited, created, ..., or "missing".
container_state() {
    local state
    if state="$(docker container inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null)" && [ -n "$state" ]; then
        echo "$state"
    else
        echo "missing"
    fi
}

# A label of the container ("" if it has no such label).
container_label() {
    docker container inspect -f "{{index .Config.Labels \"$1\"}}" "$CONTAINER" 2>/dev/null || true
}

# A connection succeeds only if a program listens on the port. Bash makes the connection (/dev/tcp).
port_in_use() {
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

# The HTTP status of ASK {} on /sparql ("000" if no server answers in 2 seconds).
endpoint_code() {
    curl -s -o /dev/null --max-time 2 -w '%{http_code}' "http://127.0.0.1:$KG_HTTP_PORT/sparql?query=ASK%7B%7D" 2>/dev/null || true
}

# Wait until /sparql answers. macOS has no "timeout" command, so the loop counts the seconds.
wait_ready() {
    local start=$SECONDS state code
    while [ $((SECONDS - start)) -lt "$WAIT_SECONDS" ]; do
        code="$(endpoint_code)"
        if [ "$code" = "200" ]; then
            echo "Virtuoso answers on http://127.0.0.1:$KG_HTTP_PORT/sparql (after $((SECONDS - start)) s)."
            return 0
        fi
        state="$(container_state)"
        if [ "$state" != "running" ]; then
            docker logs --tail 30 "$CONTAINER" >&2 || true
            fail "The container $CONTAINER stopped (state: $state). Read the log above."
        fi
        sleep 1
    done
    docker logs --tail 30 "$CONTAINER" >&2 || true
    fail "Virtuoso does not answer on http://127.0.0.1:$KG_HTTP_PORT/sparql after $WAIT_SECONDS seconds. Read the log above."
}

need_running() {
    if [ -z "${KG_ISQL:-}" ]; then
        need_docker
        [ "$(container_state)" = "running" ] || fail "The container $CONTAINER does not run. Start it with: ./src/scripts/kg.sh up"
    fi
}

# ---------------------------------------------------------------------------------------------
# isql

# Send the SQL of stdin to isql as the user dba, and write the output. Fail if the output has an error.
# isql gives the exit code 0 also when a statement fails, so the function looks for "*** Error".
isql_run() {
    local out status=0
    if [ -n "${KG_ISQL:-}" ]; then
        # KG_ISQL can be a command with arguments, so it has no quotes here.
        out="$($KG_ISQL 1111 dba "$KG_DBA_PASSWORD" VERBOSE=OFF BANNER=OFF PROMPT=OFF ECHO=OFF ERRORS=STDOUT 2>&1)" || status=$?
    else
        out="$(docker exec -i "$CONTAINER" isql 1111 dba "$KG_DBA_PASSWORD" \
            VERBOSE=OFF BANNER=OFF PROMPT=OFF ECHO=OFF ERRORS=STDOUT 2>&1)" || status=$?
    fi
    case "$out" in
        *"Error 28000"*|*"Bad login"*)
            echo "$out" >&2
            fail "Virtuoso refuses the password of dba. TRIAD_VIRTUOSO_DBA_PASSWORD applies only at the first
       start of an empty volume. Use the password of that first start, or run \"kg.sh reset\"
       (this deletes all the data) and \"kg.sh up\" again." ;;
        *"*** Error"*)
            echo "$out" >&2
            return 1 ;;
    esac
    if [ "$status" -ne 0 ]; then
        echo "$out" >&2
        return "$status"
    fi
    printf '%s\n' "$out"
}

# An SQL string literal. Virtuoso reads a backslash as an escape, so the function doubles it, and it
# writes each single quote two times.
sql_text() {
    printf "'%s'" "$(printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e "s/'/''/g")"
}

# Show the roles of the account SPARQL and of the user triad, and the graph permissions.
show_access() {
    local out
    out="$(isql_run <<EOF
SELECT concat ('enabled|', U_NAME, '|', cast (U_ACCOUNT_DISABLED AS varchar)) FROM DB.DBA.SYS_USERS
 WHERE U_NAME IN ('SPARQL', $(sql_text "$KG_SPARQL_USER"));
SELECT concat ('role|', u.U_NAME, '|', r.U_NAME) FROM DB.DBA.SYS_ROLE_GRANTS g, DB.DBA.SYS_USERS u, DB.DBA.SYS_USERS r
 WHERE g.GI_SUPER = u.U_ID AND g.GI_SUB = r.U_ID AND g.GI_DIRECT = 1 AND u.U_NAME IN ('SPARQL', $(sql_text "$KG_SPARQL_USER"))
 ORDER BY 1;
SELECT concat ('perm|', u.U_NAME, '|',
  CASE WHEN iri_id_num (p.RGU_GRAPH_IID) = 0 THEN 'all graphs (the default)' ELSE id_to_iri (p.RGU_GRAPH_IID) END,
  '|', cast (p.RGU_PERMISSIONS AS varchar))
 FROM DB.DBA.RDF_GRAPH_USER p, DB.DBA.SYS_USERS u
 WHERE p.RGU_USER_ID = u.U_ID AND u.U_NAME IN ('nobody', 'SPARQL', $(sql_text "$KG_SPARQL_USER")) ORDER BY 1;
EOF
)" || fail "Cannot read the users and the permissions (see the message above)."
    printf '%s\n' "$out" | sed 's/[[:space:]]*$//' | awk -F'|' -v user="$KG_SPARQL_USER" -v base="${KG_TBOX%tbox}" '
        $1 == "enabled" { state[$2] = ($3 == "0" ? "enabled" : "disabled") }
        $1 == "role" { roles[$2] = (roles[$2] == "" ? $3 : roles[$2] ", " $3) }
        $1 == "perm" { g = $3; if (index(g, base) == 1) g = "graph/" substr(g, length(base) + 1)
                       perms = perms sprintf("    %-8s %-26s %s\n", $2, g, $4) }
        END {
            printf "The account SPARQL (/sparql, no login): %s; roles: %s\n", \
                (state["SPARQL"] == "" ? "missing" : state["SPARQL"]), (roles["SPARQL"] == "" ? "none" : roles["SPARQL"])
            if (index(roles["SPARQL"], "SPARQL_UPDATE") > 0)
                print "    Mode: the manual (5.2.3). /sparql and the Conductor SPARQL page can also run updates."
            else
                print "    Mode: strict. An update on /sparql (also from the Conductor SPARQL page) gives HTTP 500 SR186."
            printf "The user %s (/sparql-auth, digest login): %s; roles: %s\n", user, \
                (state[user] == "" ? "missing (run: kg.sh init)" : state[user]), (roles[user] == "" ? "none" : roles[user])
            print "Graph permissions (1 = read, 3 = read and write, 7 = read, write and LOAD; nobody = all users"
            print "with no permission of their own, also the account SPARQL; dba can do all):"
            printf "%s", perms
        }'
}

# The triples of each TRIAD graph, one line for each graph: "IRI COUNT".
graph_counts() {
    local g sql=""
    for g in "$KG_TBOX" "$KG_ABOX" "$KG_SCRATCH" "$KG_META"; do
        sql="${sql}SELECT concat ('count|', $(sql_text "$g"), '|', cast (count (*) AS varchar)) FROM DB.DBA.RDF_QUAD WHERE G = iri_to_id ($(sql_text "$g"), 0);
"
    done
    printf '%s' "$sql" | isql_run | sed 's/[[:space:]]*$//' | awk -F'|' '$1 == "count" { print $2, $3 }'
}

# ---------------------------------------------------------------------------------------------
# Commands

cmd_up() {
    need_docker
    load_settings
    local state item label next="The volume $VOLUME keeps the graphs, the users and the permissions."
    state="$(container_state)"
    case "$state" in
        running)
            echo "The container $CONTAINER runs already." ;;
        missing)
            if port_in_use "$KG_HTTP_PORT"; then
                fail "Port $KG_HTTP_PORT is in use. Stop the program that uses it (to find it: lsof -nP -iTCP:$KG_HTTP_PORT -sTCP:LISTEN),
       or set another port, for example KG_HTTP_PORT=$((KG_HTTP_PORT + 1)), and run the command again."
            fi
            mkdir -p "$KG_DIR" "$KG_SEMANTIC_DIR"
            if ! docker volume inspect "$VOLUME" >/dev/null 2>&1; then
                next="Next: ./src/scripts/kg.sh init, then ./src/scripts/kg.sh load."
            fi
            echo "Making the container $CONTAINER (Virtuoso 7.2) with the volume $VOLUME ..."
            # The VIRT_ settings go into virtuoso.ini only at the first start of an empty volume.
            # Do not set ResultSetMaxRows or MaxQueryExecutionTime: they cut the results with no error.
            # MaxSortedTopRows is the row limit of ORDER BY with OFFSET and LIMIT.
            # The labels keep the host folders, so a later "up" can see a change of TRIAD_KG_DIR.
            docker run -d --name "$CONTAINER" -p "127.0.0.1:$KG_HTTP_PORT:8890" \
                -v "$VOLUME:/database" \
                -v "$KG_DIR:/import/kg:ro" -v "$KG_SEMANTIC_DIR:/import/semantic:ro" \
                --label "triad.kg-dir=$KG_DIR" --label "triad.semantic-dir=$KG_SEMANTIC_DIR" \
                -e DBA_PASSWORD="$KG_DBA_PASSWORD" \
                -e "VIRT_Parameters_DirsAllowed=., ../vad, /usr/share/proj, /import" \
                -e VIRT_Parameters_NumberOfBuffers=170000 -e VIRT_Parameters_MaxDirtyBuffers=130000 \
                -e VIRT_Parameters_MaxSortedTopRows=100000 \
                "$IMAGE" >/dev/null ;;
        *)
            echo "Starting the container $CONTAINER (its state was: $state) ..."
            docker start "$CONTAINER" >/dev/null ;;
    esac
    for item in "triad.kg-dir:$KG_DIR" "triad.semantic-dir:$KG_SEMANTIC_DIR"; do
        label="$(container_label "${item%%:*}")"
        if [ -n "$label" ] && [ "$label" != "${item#*:}" ]; then
            echo "NOTE: the container mounts $label, not ${item#*:}."
            echo "      To use the new folder: docker rm -f $CONTAINER, then kg.sh up (the data stays in the volume)."
        fi
    done
    wait_ready
    echo "$next"
}

cmd_init() {
    local strict="$1"
    load_settings
    need_running
    case "$KG_SPARQL_USER" in
        dba|dav|nobody|SPARQL|SPARQL_*) fail "TRIAD_SPARQL_USER is $KG_SPARQL_USER. Use a user of its own, for example triad." ;;
    esac
    # The procedure is safe to run again: USER_CREATE of a user that exists sets its password again, and the
    # procedure grants a role only if the user does not have it (a second GRANT gives the error U0013).
    # Graph permissions: 1 = read, 2 = write, 4 = sponge (LOAD). The permissions of nobody apply to each user
    # with no permission of its own, thus also to the account SPARQL (the user of /sparql).
    isql_run >/dev/null <<EOF || fail "The init stopped (see the message above)."
create procedure DB.DBA.TRIAD_HAS_ROLE (in uname varchar, in rname varchar)
{
  return (select count (*) from DB.DBA.SYS_ROLE_GRANTS g, DB.DBA.SYS_USERS u, DB.DBA.SYS_USERS r
          where g.GI_SUPER = u.U_ID and g.GI_SUB = r.U_ID and g.GI_DIRECT = 1
            and u.U_NAME = uname and r.U_NAME = rname);
};
create procedure DB.DBA.TRIAD_INIT (in uname varchar, in pw varchar, in strict integer)
{
  DB.DBA.USER_CREATE (uname, pw);
  if (DB.DBA.TRIAD_HAS_ROLE (uname, 'SPARQL_UPDATE') = 0)
    DB.DBA.USER_GRANT_ROLE (uname, 'SPARQL_UPDATE');
  DB.DBA.USER_SET_OPTION ('SPARQL', 'DISABLED', 0);
  if (DB.DBA.TRIAD_HAS_ROLE ('SPARQL', 'SPARQL_SELECT') = 0)
    DB.DBA.USER_GRANT_ROLE ('SPARQL', 'SPARQL_SELECT');
  if (strict <> 0 and DB.DBA.TRIAD_HAS_ROLE ('SPARQL', 'SPARQL_UPDATE') > 0)
    DB.DBA.USER_REVOKE_ROLE ('SPARQL', 'SPARQL_UPDATE');
  if (strict = 0 and DB.DBA.TRIAD_HAS_ROLE ('SPARQL', 'SPARQL_UPDATE') = 0)
    DB.DBA.USER_GRANT_ROLE ('SPARQL', 'SPARQL_UPDATE');
  DB.DBA.RDF_DEFAULT_USER_PERMS_SET ('nobody', 1);
  DB.DBA.RDF_DEFAULT_USER_PERMS_SET (uname, 1);
  DB.DBA.RDF_GRAPH_USER_PERMS_SET ($(sql_text "$KG_TBOX"), uname, 7);
  DB.DBA.RDF_GRAPH_USER_PERMS_SET ($(sql_text "$KG_ABOX"), uname, 3);
  DB.DBA.RDF_GRAPH_USER_PERMS_SET ($(sql_text "$KG_SCRATCH"), uname, 7);
  DB.DBA.RDF_GRAPH_USER_PERMS_SET ($(sql_text "$KG_META"), uname, 3);
  if (strict <> 0)
    {
      DB.DBA.RDF_GRAPH_USER_PERMS_DEL ($(sql_text "$KG_ABOX"), 'nobody');
      DB.DBA.RDF_GRAPH_USER_PERMS_DEL ($(sql_text "$KG_SCRATCH"), 'nobody');
    }
  else
    {
      DB.DBA.RDF_GRAPH_USER_PERMS_SET ($(sql_text "$KG_ABOX"), 'nobody', 3);
      DB.DBA.RDF_GRAPH_USER_PERMS_SET ($(sql_text "$KG_SCRATCH"), 'nobody', 3);
    }
};
DB.DBA.TRIAD_INIT ($(sql_text "$KG_SPARQL_USER"), $(sql_text "$KG_SPARQL_PASSWORD"), $strict);
EOF
    if [ "$strict" = 1 ]; then
        echo "The init is done (strict). The users with no login can only read."
    else
        echo "The init is done (the account step of the manual, 5.2.3)."
    fi
    show_access
}

cmd_load() {
    local seed="$1" export="${2:-yes}" owl data data_name import_dir started out file line rest state error ok=yes tbox_count abox_count
    load_settings
    need_running
    owl="$KG_SEMANTIC_DIR/triad.owl"
    if [ "$seed" = yes ]; then
        data="$KG_SEMANTIC_DIR/kg/triad_kg_seed.rdf"
        import_dir="$IMPORT_SEMANTIC/kg"
    else
        if [ "$export" = yes ] && main_has_export_kg; then
            echo "Making the knowledge graph from the database (main.py ensure-db, then main.py export-kg) ..."
            "$PY" src/backend/main.py ensure-db
            "$PY" src/backend/main.py export-kg --scope all --out "$KG_DIR"
        fi
        data="$KG_DIR/triad_kg.nt.gz"
        import_dir="$IMPORT_KG"
    fi
    data_name="$(basename "$data")"
    [ -f "$owl" ] || fail "The ontology $owl does not exist. Build it first (models/semantic/build_ontology.py)."
    if [ ! -f "$data" ]; then
        if [ "$seed" = yes ]; then
            fail "The seed graph $data does not exist."
        fi
        fail "The knowledge graph $data does not exist. Make it with:
       $PY src/backend/main.py export-kg --scope all --out $KG_DIR"
    fi
    if [ -z "${KG_ISQL:-}" ]; then
        for file in "$IMPORT_SEMANTIC/triad.owl" "$import_dir/$data_name"; do
            docker exec "$CONTAINER" test -r "$file" || fail "The container does not see $file.
       The container mounts the folders of the first \"kg.sh up\". To mount the folders again:
       docker rm -f $CONTAINER, then kg.sh up (the data stays in the volume)."
        done
    fi

    echo "Loading into <$KG_TBOX>: $owl"
    echo "Loading into <$KG_ABOX>: $data"
    started=$SECONDS
    # Step 1: register the two files. The bulk loader skips a file name that is in DB.DBA.LOAD_LIST,
    # so the old rows go first. isql runs the next statement also after an error, so the graphs are
    # cleared only in step 2, after step 1 has no error.
    isql_run >/dev/null <<EOF || fail "Virtuoso cannot read the files. The graphs did not change."
DELETE FROM DB.DBA.LOAD_LIST WHERE ll_file LIKE $(sql_text "$IMPORT_KG/%") OR ll_file LIKE $(sql_text "$IMPORT_SEMANTIC/%");
ld_dir ($(sql_text "$IMPORT_SEMANTIC"), 'triad.owl', $(sql_text "$KG_TBOX"));
ld_dir ($(sql_text "$import_dir"), $(sql_text "$data_name"), $(sql_text "$KG_ABOX"));
EOF
    # Step 2: clear the two graphs and run the bulk loader.
    # log_enable (3, 1): commit each row and keep no log, so CLEAR of a large graph does not fill the log.
    isql_run >/dev/null <<EOF || fail "The load stopped (see the message above)."
log_enable (3, 1);
SPARQL CLEAR GRAPH <$KG_TBOX>;
SPARQL CLEAR GRAPH <$KG_ABOX>;
rdf_loader_run ();
checkpoint;
EOF

    # isql gives the exit code 0 also when the loader fails, so check the load list (state 2 = done).
    out="$(isql_run <<EOF
SELECT concat ('load|', ll_file, '|', cast (ll_state AS varchar), '|', coalesce (ll_error, '')) FROM DB.DBA.LOAD_LIST
 WHERE ll_file IN ($(sql_text "$IMPORT_SEMANTIC/triad.owl"), $(sql_text "$import_dir/$data_name"));
EOF
)" || fail "Cannot read the load list (see the message above)."
    for file in "$IMPORT_SEMANTIC/triad.owl" "$import_dir/$data_name"; do
        line="$(printf '%s\n' "$out" | sed 's/[[:space:]]*$//' | grep -F "load|$file|" | head -n 1 || true)"
        if [ -z "$line" ]; then
            echo "ERROR: the bulk loader did not find $file (DirsAllowed in virtuoso.ini must hold its folder)." >&2
            ok=no
            continue
        fi
        rest="${line#load|"$file"|}"
        state="${rest%%|*}"
        error="${rest#*|}"
        if [ "$state" != "2" ] || [ -n "$error" ]; then
            echo "ERROR: the bulk loader did not load $file (state $state): $error" >&2
            ok=no
        fi
    done
    [ "$ok" = yes ] || fail "The load failed. Correct the file, then run kg.sh load again."

    out="$(graph_counts)"
    tbox_count="$(printf '%s\n' "$out" | awk -v g="$KG_TBOX" '$1 == g { print $2 }')"
    abox_count="$(printf '%s\n' "$out" | awk -v g="$KG_ABOX" '$1 == g { print $2 }')"
    echo "Loaded in $((SECONDS - started)) s: <$KG_TBOX> has ${tbox_count:-0} triples, <$KG_ABOX> has ${abox_count:-0} triples."
    [ "${tbox_count:-0}" != "0" ] || fail "The TBox graph is empty after the load. Check $owl."
    [ "${abox_count:-0}" != "0" ] || fail "The ABox graph is empty after the load. Check $data."

    if [ "$seed" = yes ]; then
        echo "The seed graph is loaded. kg_report.json is for the full graph, so the count check does not apply."
    elif [ -f "$KG_DIR/kg_report.json" ]; then
        pymod infrastructure.rdf.counts --report "$KG_DIR/kg_report.json" \
            || fail "The ABox graph does not agree with $KG_DIR/kg_report.json (see above)."
    else
        echo "NOTE: $KG_DIR/kg_report.json does not exist, so the counts per predicate are not checked."
    fi
}

# True if main.py has the command export-kg (the export of the knowledge graph).
main_has_export_kg() {
    local help
    help="$("$PY" src/backend/main.py --help 2>/dev/null || true)"
    case "$help" in
        *export-kg*) return 0 ;;
    esac
    return 1
}

cmd_status() {
    load_settings
    local state code
    if [ -n "${KG_ISQL:-}" ]; then
        echo "Virtuoso without Docker (KG_ISQL=$KG_ISQL)."
    else
        need_docker
        state="$(container_state)"
        echo "The container $CONTAINER: $state."
        if [ "$state" = "missing" ]; then
            echo "Make it with: ./src/scripts/kg.sh up"
            return 0
        fi
        echo "The image: $(docker container inspect -f '{{.Config.Image}}' "$CONTAINER")"
        if [ "$state" != "running" ]; then
            echo "Start it with: ./src/scripts/kg.sh up"
            return 0
        fi
    fi
    code="$(endpoint_code)"
    if [ "$code" = "200" ]; then
        echo "The endpoint http://127.0.0.1:$KG_HTTP_PORT/sparql answers."
    else
        echo "The endpoint http://127.0.0.1:$KG_HTTP_PORT/sparql does not answer (HTTP $code)."
    fi
    echo "The triples of each graph:"
    graph_counts | awk '{ printf "    %-60s %s\n", "<" $1 ">", $2 }'
    show_access
}

cmd_sparql() {
    [ "$#" -ge 1 ] || fail "Give a .sparql file: kg.sh sparql FILE [--only ID[,ID...]] [--max-rows N] [--keep-going]"
    local file="$1" path
    shift
    load_settings
    case "$file" in
        /*) path="$file" ;;
        *)
            if [ -f "$CALLER_DIR/$file" ]; then
                path="$CALLER_DIR/$file"
            elif [ -f "$KG_SEMANTIC_DIR/sparql/$file" ]; then
                path="$KG_SEMANTIC_DIR/sparql/$file"
            else
                path="$CALLER_DIR/$file"
            fi ;;
    esac
    [ -f "$path" ] || fail "The file $file does not exist (also not in $KG_SEMANTIC_DIR/sparql)."
    pymod infrastructure.rdf.sparql_script "$path" "$@"
}

cmd_open() {
    load_settings
    local base="http://127.0.0.1:$KG_HTTP_PORT"
    if [ -z "${KG_ISQL:-}" ] && command -v docker >/dev/null 2>&1 && [ "$(container_state)" != "running" ]; then
        echo "NOTE: the container $CONTAINER does not run. Start it with: ./src/scripts/kg.sh up"
        echo ""
    fi
    echo "Conductor (the admin pages of Virtuoso): $base/conductor"
    if [ "$KG_DBA_PASSWORD_IS_DEFAULT" = yes ]; then
        echo "    Log in as dba with the password dba (the default of TRIAD_VIRTUOSO_DBA_PASSWORD)."
    else
        echo "    Log in as dba with the password of TRIAD_VIRTUOSO_DBA_PASSWORD (src/backend/.env or the shell)."
    fi
    echo "The SPARQL query page (no login): $base/sparql"
    echo "The update endpoint of the app: $KG_UPDATE_URL (digest login as $KG_SPARQL_USER)"
    echo "The graphs:"
    echo "    <$KG_TBOX>      the ontology (TBox)"
    echo "    <$KG_ABOX>      the data (ABox)"
    echo "    <$KG_SCRATCH>   the scratch graph of the SPARQL scripts"
    echo "    <$KG_META>      the id counters and the build marker"
    echo ""
    echo "When you are done: ./src/scripts/kg.sh down (the data stays in the volume)."
}

cmd_down() {
    need_docker
    case "$(container_state)" in
        running)
            docker stop "$CONTAINER" >/dev/null
            echo "Stopped the container $CONTAINER. The data stays in the volume $VOLUME. To start it again: kg.sh up" ;;
        missing) echo "The container $CONTAINER does not exist. Nothing to stop." ;;
        *) echo "The container $CONTAINER does not run. Nothing to stop." ;;
    esac
}

cmd_reset() {
    need_docker
    if [ "$(container_state)" != "missing" ]; then
        docker rm -f "$CONTAINER" >/dev/null
        echo "Removed the container $CONTAINER."
    fi
    if docker volume inspect "$VOLUME" >/dev/null 2>&1; then
        docker volume rm "$VOLUME" >/dev/null
        echo "Removed the volume $VOLUME (all the data of Virtuoso)."
    fi
    echo "Virtuoso is reset. To start again: kg.sh up, kg.sh init, kg.sh load."
}

# ---------------------------------------------------------------------------------------------

COMMAND="${1:-help}"
if [ "$#" -gt 0 ]; then
    shift
fi
case "$COMMAND" in
    up|down|reset|status|open)
        [ "$#" -eq 0 ] || fail "\"$COMMAND\" has no options. See: kg.sh help"
        "cmd_$COMMAND" ;;
    init)
        STRICT=0
        for arg in "$@"; do
            case "$arg" in
                --strict) STRICT=1 ;;
                *) fail "Unknown option of init: $arg. Use --strict or no option." ;;
            esac
        done
        cmd_init "$STRICT" ;;
    load)
        SEED=no
        EXPORT=yes
        for arg in "$@"; do
            case "$arg" in
                --seed) SEED=yes ;;
                --no-export) EXPORT=no ;;
                *) fail "Unknown option of load: $arg. Use --seed, --no-export or no option." ;;
            esac
        done
        cmd_load "$SEED" "$EXPORT" ;;
    sparql) cmd_sparql "$@" ;;
    help|-h|--help) usage ;;
    *) usage >&2; echo "" >&2; fail "Unknown command: $COMMAND. See the list above." ;;
esac
