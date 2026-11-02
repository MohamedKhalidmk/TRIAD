"""Shared test fixtures: the scenario database (01 + 02) and the full database (onboarding)."""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from infrastructure import config
from infrastructure.sqlite.connection import connect
from infrastructure.sqlite.schema import ensure_db


def run_sql_file(conn: sqlite3.Connection, name: str) -> None:
    conn.executescript((config.SQL_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def scenario_db(tmp_path_factory) -> Path:
    """A database made only from the SQL scripts 01 and 02 (no Python onboarding)."""
    path = tmp_path_factory.mktemp("scenario") / "scenario.db"
    conn = connect(path)
    run_sql_file(conn, "01_create_tables.sql")
    run_sql_file(conn, "02_insert_seed.sql")
    conn.close()
    return path


@pytest.fixture
def scenario_copy(scenario_db, tmp_path) -> Path:
    """A new copy of the scenario database for a test that changes data."""
    path = tmp_path / "copy.db"
    shutil.copy(scenario_db, path)
    return path


@pytest.fixture(scope="session")
def full_db(tmp_path_factory) -> Path:
    """The full database: the schema and the onboarded FHIR data (Synthea + scenarios)."""
    import main
    path = tmp_path_factory.mktemp("full") / "triad.db"
    ensure_db(path, lambda conn: main.onboard(conn, report_path=None), reset=True)
    return path


@pytest.fixture
def db(full_db) -> sqlite3.Connection:
    conn = connect(full_db)
    yield conn
    conn.close()
