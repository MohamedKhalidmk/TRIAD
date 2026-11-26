"""The fingerprint of the relational data for the build marker of the knowledge graph (plan 3.5).

logical_hash() is the SHA-256 of a logical dump of a SQLite database: each table in the order of its name, its
column names, then its rows ORDER BY Id, each row as JSON. It does not read the file bytes: they change when only
the journal mode changes (serve sets WAL), and a false rebuild deletes the writes that the app made in KG mode.
The table sqlite_sequence is not in the dump; sequences() gives it (the seed of the id counters).
This module uses only the Python standard library.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from infrastructure import config

MAPPING_PATH = config.SEMANTIC_DIR / "mapping" / "triad.r2rml.ttl"


def _connect(db_path: Path) -> sqlite3.Connection:
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"The database {path} does not exist. Run: python src/backend/main.py ensure-db")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def logical_hash(db_path: Path) -> str:
    """The SHA-256 (hex) of the rows of all tables of a database (see the module text)."""
    digest = hashlib.sha256()
    conn = _connect(db_path)
    try:
        tables = [name for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for table in tables:
            columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
            digest.update(json.dumps(["table", table, columns]).encode("utf-8") + b"\n")
            order = '"Id"' if "Id" in columns else "rowid"
            for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY {order}'):
                digest.update(json.dumps(list(row), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                              + b"\n")
    finally:
        conn.close()
    return digest.hexdigest()


def sequences(db_path: Path) -> dict[str, int]:
    """The last id of each table (sqlite_sequence), and MAX(Id) for a table that is not in it."""
    conn = _connect(db_path)
    try:
        found = {name: int(seq) for name, seq in conn.execute("SELECT name, seq FROM sqlite_sequence")}
        tables = [name for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
            if "Id" in columns:
                (largest,) = conn.execute(f'SELECT COALESCE(MAX("Id"), 0) FROM "{table}"').fetchone()
                found[table] = max(found.get(table, 0), int(largest))
        return found
    finally:
        conn.close()


def file_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def mapping_hash(path: Path = MAPPING_PATH) -> str:
    """The SHA-256 of the R2RML mapping file."""
    return file_hash(path)
