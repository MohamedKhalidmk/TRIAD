"""Shared test fixtures: the scenario database (01 + 02), the full database (onboarding) and the API client."""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from infrastructure import config
from infrastructure.sqlite.connection import connect
from infrastructure.sqlite.schema import ensure_db


def run_sql_file(conn: sqlite3.Connection, path: Path) -> None:
    conn.executescript(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def scenario_db(tmp_path_factory) -> Path:
    """A database made only from the SQL scripts 01 and 02 (no Python onboarding)."""
    path = tmp_path_factory.mktemp("scenario") / "scenario.db"
    conn = connect(path)
    run_sql_file(conn, config.DDL_DIR / "01_create_tables.sql")
    run_sql_file(conn, config.DML_DIR / "02_insert_seed.sql")
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


DEMO_NOW = "2026-10-30T09:00:00-04:00"


def make_client(db_path: Path, **settings):
    """A FastAPI TestClient on `db_path` (fake chat mode, fixed demo time, no SQL log, no frontend)."""
    import main
    from fastapi.testclient import TestClient
    values = dict(db_path=db_path, now=DEMO_NOW, llm_mode="fake", frontend_dist=db_path.parent / "no-frontend",
                  sql_log="off")
    values.update(settings)
    return TestClient(main.create_app(config.Settings.from_env(**values)))


@pytest.fixture
def full_copy(full_db, tmp_path) -> Path:
    """A new copy of the full database for a test that changes data."""
    path = tmp_path / "full-copy.db"
    shutil.copy(full_db, path)
    return path


@pytest.fixture
def client(full_copy):
    """An API client on a new copy of the full database."""
    return make_client(full_copy)


def as_user(key: str) -> dict:
    """The header of the current user."""
    return {"X-Triad-User": key}


def all_items(client, url: str, user: str | None = None, **params) -> list[dict]:
    """All rows of a paged list endpoint: read the pages of 200 rows until the end (doc/api.md section 1.5)."""
    items: list[dict] = []
    while True:
        response = client.get(url, headers=as_user(user) if user else {},
                              params={**params, "limit": 200, "offset": len(items)})
        assert response.status_code == 200, response.text
        page = response.json()
        items += page["items"]
        if not page["items"] or len(items) >= page["total"]:
            assert len(items) == page["total"]
            return items
