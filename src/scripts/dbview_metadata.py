#!/usr/bin/env python3
"""Write the Datasette metadata of the TRIAD database viewer (src/scripts/dbview.sh).

The metadata gives the viewer a title, links to the model documents, the queries Q1 to Q14b of
dml/03_select_queries.sql and the schema queries (tables, columns, foreign keys, triggers, indexes).
The queries come from the SQL file each time, so the viewer and the file always agree.

Usage:
    python src/scripts/dbview_metadata.py --db PATH          write the metadata (JSON) to stdout
    python src/scripts/dbview_metadata.py --print-db-path    write the database path of the app to stdout
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "src" / "backend"
SELECT_QUERIES = BACKEND / "models" / "relational" / "sql" / "dml" / "03_select_queries.sql"
REPO_URL = "https://github.com/MohamedKhalidmk/TRIAD/blob/main"

QUERY_START = re.compile(r"^-- (Q\d+[a-z]?)\. (.*)$")

# The schema of the database. SQLite gives it through sqlite_master and the pragma table functions.
SCHEMA_QUERIES = {
    "schema_tables": {
        "title": "Schema: tables",
        "description": "Each table, with its number of columns and rows. The database has 29 relations.",
        "sql": "SELECT m.name AS table_name,\n"
               "       (SELECT COUNT(*) FROM pragma_table_info(m.name)) AS columns,\n"
               "       (SELECT COUNT(*) FROM pragma_foreign_key_list(m.name)) AS foreign_keys\n"
               "FROM sqlite_master m\n"
               "WHERE m.type = 'table' AND m.name NOT LIKE 'sqlite_%'\n"
               "ORDER BY m.name",
    },
    "schema_columns": {
        "title": "Schema: columns",
        "description": "The columns of each table: the type, NOT NULL, the default value and the primary key.",
        "sql": "SELECT m.name AS table_name, c.cid AS position, c.name AS column_name, c.type,\n"
               "       c.\"notnull\" AS not_null, c.dflt_value AS default_value, c.pk AS primary_key\n"
               "FROM sqlite_master m JOIN pragma_table_info(m.name) c\n"
               "WHERE m.type = 'table' AND m.name NOT LIKE 'sqlite_%'\n"
               "ORDER BY m.name, c.cid",
    },
    "schema_foreign_keys": {
        "title": "Schema: foreign keys",
        "description": "Each foreign key: the column of the table and the column that it points to. "
                       "These are the relationships of the ER diagram in the relational form.",
        "sql": "SELECT m.name AS table_name, f.\"from\" AS column_name, f.\"table\" AS refers_to_table,\n"
               "       f.\"to\" AS refers_to_column, f.on_delete, f.id AS key_id, f.seq AS key_position\n"
               "FROM sqlite_master m JOIN pragma_foreign_key_list(m.name) f\n"
               "WHERE m.type = 'table'\n"
               "ORDER BY m.name, f.id, f.seq",
    },
    "schema_triggers": {
        "title": "Schema: triggers",
        "description": "The triggers and their SQL: for example, the append-only assertions and the supersede rules.",
        "sql": "SELECT name AS trigger_name, tbl_name AS table_name, sql\n"
               "FROM sqlite_master\n"
               "WHERE type = 'trigger'\n"
               "ORDER BY tbl_name, name",
    },
    "schema_indexes": {
        "title": "Schema: indexes",
        "description": "The indexes and their SQL. SQLite makes the indexes of the UNIQUE keys itself (no SQL).",
        "sql": "SELECT name AS index_name, tbl_name AS table_name, sql\n"
               "FROM sqlite_master\n"
               "WHERE type = 'index'\n"
               "ORDER BY tbl_name, name",
    },
}


def select_queries(path: Path = SELECT_QUERIES) -> dict[str, dict]:
    """The queries Q1 to Q14b of the SQL file: {"Q1": {"title", "description", "sql"}, ...}.

    A query starts at a comment line "-- Qn. text" and ends before the next one. The comment lines at
    the start of a query are its description. The statement is the rest, without the last semicolon.
    """
    queries: dict[str, dict] = {}
    name, comments, lines = None, [], []

    def close() -> None:
        if name is None:
            return
        sql = "\n".join(lines).strip().rstrip(";").strip()
        if ";" in sql:
            raise ValueError(f"{name} has more than one statement. Datasette needs one statement for each query.")
        description = " ".join(comments)
        first_sentence = re.split(r"(?<=\.)\s", description, maxsplit=1)[0]
        queries[name] = {"title": f"{name}. {first_sentence}", "description": description, "sql": sql}

    for raw in path.read_text(encoding="utf-8").splitlines():
        start = QUERY_START.match(raw)
        if start:
            close()
            name, comments, lines = start.group(1), [start.group(2).strip()], []
        elif name is not None and raw.startswith("--") and not lines:
            comments.append(raw.lstrip("-").strip())
        elif name is not None:
            lines.append(raw)
    close()
    return queries


def metadata(db_name: str) -> dict:
    links = (f'<a href="{REPO_URL}/src/backend/models/er/TRIAD_ERD.png">the ER diagram</a>, '
             f'<a href="{REPO_URL}/src/backend/models/relational/relations.md">relations.md</a> '
             f'(the ER diagram as 29 relations) and '
             f'<a href="{REPO_URL}/src/backend/models/relational/sql/ddl/01_create_tables.sql">01_create_tables.sql</a>')
    queries = {**select_queries(), **SCHEMA_QUERIES}
    description = (
        "<p>The SQLite database of the TRIAD prototype. All data is synthetic. The viewer cannot change it. "
        "It shows all rows: it does not use the access rules of the app.</p>"
        "<p>Select a table to see its rows, its foreign keys and its <code>CREATE TABLE</code> statement. "
        "The queries Q1 to Q14b come from <code>dml/03_select_queries.sql</code>. The schema queries show "
        f"the tables, the columns, the foreign keys, the triggers and the indexes. See also {links}.</p>")
    return {
        "title": "TRIAD database (read-only)",
        "description_html": description,
        "license": "CC BY-NC-SA 4.0",
        "license_url": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
        "source": "Synthea FHIR R4 sample (commit 84f5980) and the curated TRIAD FHIR bundle",
        "source_url": f"{REPO_URL}/src/backend/data/raw/README.md",
        "databases": {db_name: {"description_html": description, "queries": queries}},
    }


def app_db_path() -> Path:
    """The database path of the app: TRIAD_DB_PATH (the shell or src/backend/.env), or the default."""
    sys.path.insert(0, str(BACKEND))
    from infrastructure import config  # noqa: E402 - the backend settings, the same as main.py
    config.load_env_file()
    return config.env_db_path()


def main() -> None:
    parser = argparse.ArgumentParser(description="Write the Datasette metadata of the TRIAD database viewer.")
    parser.add_argument("--db", type=Path, help="the database file (its name is the database name in Datasette)")
    parser.add_argument("--print-db-path", action="store_true", help="write the database path of the app and stop")
    args = parser.parse_args()
    if args.print_db_path:
        print(app_db_path())
        return
    db = args.db or app_db_path()
    json.dump(metadata(db.stem), sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
