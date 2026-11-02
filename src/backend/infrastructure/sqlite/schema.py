"""Create the schema, and build a complete database in one atomic step (ensure-db)."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Callable

from infrastructure.config import SCHEMA_VERSION, SQL_DIR
from infrastructure.sqlite.connection import connect


def run_script(conn: sqlite3.Connection, path: Path) -> None:
    conn.executescript(Path(path).read_text(encoding="utf-8"))


def init_db(conn: sqlite3.Connection) -> None:
    """Run 01_create_tables.sql. It sets PRAGMA user_version to the schema version."""
    run_script(conn, SQL_DIR / "01_create_tables.sql")


def schema_version(path: Path) -> int:
    conn = connect(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def ensure_db(path: Path, build: Callable[[sqlite3.Connection], None], reset: bool = False) -> str:
    """Make sure that a current database exists at `path`.

    If the file is missing (or `reset` is true), build a new database in `<path>.tmp` and then
    move it to `path`. A stop during the build leaves no half-built database.
    Returns "built" or "current". Stops with an error when the schema version does not match.
    """
    path = Path(path)
    if path.exists() and not reset:
        version = schema_version(path)
        if version != SCHEMA_VERSION:
            raise SystemExit(f"The database {path} has schema version {version}, not {SCHEMA_VERSION}. "
                             f"Run the command again with --reset-db.")
        return "current"
    tmp = path.with_name(path.name + ".tmp")
    for p in (tmp, Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm")):
        if p.exists():
            p.unlink()
    conn = connect(tmp)
    try:
        init_db(conn)
        build(conn)
        conn.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        conn.close()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(tmp, path)
    return "built"
