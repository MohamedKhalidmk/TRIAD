"""Shared test fixtures: the scenario database (01 + 02), the full database (onboarding) and the API client.

The store fixtures (Milestone 5; tests/fixtures/stores.py) run one test on each data store:
    store          the scenario data (fast)
    planted_store  the planted data (tests/fixtures/plant.py; fast)
    full_store     the full data (the marker "slow")
Each one is parametrized over TRIAD_TEST_STORES (default: sqlite,oxigraph; add virtuoso for a running Virtuoso).
A test that needs only some stores has @pytest.mark.stores("oxigraph"). The KG parameters have the marker "kg",
so -m "not kg" runs only SQLite. Example (the pattern of tests/integration/test_store_users.py):

    def test_the_demo_users_come_first(store):
        page = store.client().get("/api/users").json()
        assert store.probe.count("patient") == ...
"""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from infrastructure import config
from infrastructure.sqlite.connection import connect
from infrastructure.sqlite.schema import ensure_db
from tests.fixtures.stores import (KG_STORES, StoreHandle, base_settings, cached_oxigraph, oxigraph_handle,
                                   selected_stores, sqlite_handle, virtuoso_answers, virtuoso_handle)


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
    """A FastAPI TestClient on `db_path` (fake chat mode, fixed demo time, no SQL log, no frontend, SQLite).

    The store is SQLite unless the test gives another store, also when the shell sets TRIAD_STORE.
    """
    import main
    from fastapi.testclient import TestClient
    values = dict(db_path=db_path, now=DEMO_NOW, llm_mode="fake", frontend_dist=db_path.parent / "no-frontend",
                  sql_log="off", sparql_log="off", store="sqlite")
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


@pytest.fixture
def planted_db(scenario_db, tmp_path) -> Path:
    """A copy of the scenario database (cheap: no onboarding) with the planted rows of tests/fixtures/plant.py."""
    from tests.fixtures.plant import plant
    path = tmp_path / "planted.db"
    shutil.copy(scenario_db, path)
    plant(path)
    return path


# ----- the store fixtures (Milestone 5; tests/fixtures/stores.py) -----

def store_params(*extra_marks) -> list:
    """The parameters of a store fixture: TRIAD_TEST_STORES, with the markers kg and virtuoso."""
    out = []
    for name in selected_stores():
        marks = list(extra_marks)
        if name in KG_STORES:
            marks.append(pytest.mark.kg)
        if name == "virtuoso":
            marks.append(pytest.mark.virtuoso)
        out.append(pytest.param(name, marks=marks, id=name))
    return out


@pytest.fixture(scope="session")
def kg_cache(request, tmp_path_factory) -> Path:
    """The folder of the built Oxigraph stores: .pytest_cache/d/triad-kg (it stays between test runs)."""
    cache = getattr(request.config, "cache", None)
    return Path(cache.mkdir("triad-kg")) if cache is not None else tmp_path_factory.mktemp("triad-kg")


def built_oxigraph(db: Path, kg_cache: Path, tmp_path_factory) -> Path:
    """The built Oxigraph store of a database (from the cache). Another test run can hold the cached store open:
    then this run builds its own store."""
    pytest.importorskip("pyoxigraph")
    pytest.importorskip("morph_kgc")
    from infrastructure.rdf import oxigraph_store
    try:
        built = cached_oxigraph(db, kg_cache)
        oxigraph_store.open_store(built)
    except OSError:
        built = cached_oxigraph(db, tmp_path_factory.mktemp("triad-kg-private"))
    return built


STORE_FIXTURES = ("store", "planted_store", "full_store")


def pytest_collection_modifyitems(config, items):
    """@pytest.mark.stores("oxigraph", ...): deselect the parameters of the other stores."""
    keep, drop = [], []
    for item in items:
        only = item.get_closest_marker("stores")
        params = getattr(getattr(item, "callspec", None), "params", {})
        names = [params[f] for f in STORE_FIXTURES if f in params]
        (drop if only and any(n not in only.args for n in names) else keep).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = keep


def open_store_handle(request, db_source: Path, tmp_path: Path, kg_cache: Path, tmp_path_factory,
                      seed: bool) -> StoreHandle:
    name = request.param
    copy = tmp_path / f"{name}.db"
    shutil.copy(db_source, copy)
    if name == "sqlite":
        return sqlite_handle(copy)
    if name == "oxigraph":
        return oxigraph_handle(copy, built_oxigraph(db_source, kg_cache, tmp_path_factory), tmp_path / "oxigraph")
    pytest.importorskip("SPARQLWrapper")
    if not virtuoso_answers(base_settings(copy, store="virtuoso")):
        pytest.skip("Virtuoso does not answer on TRIAD_SPARQL_QUERY_URL (start it with: ./src/scripts/kg.sh up).")
    return virtuoso_handle(copy, seed=seed)


@pytest.fixture(params=store_params())
def store(request, scenario_db, tmp_path, kg_cache, tmp_path_factory):
    """The scenario data (01 + 02) on each store of TRIAD_TEST_STORES. A new copy for each test."""
    handle = open_store_handle(request, scenario_db, tmp_path, kg_cache, tmp_path_factory, seed=True)
    yield handle
    handle.close()


@pytest.fixture(params=store_params())
def planted_store(request, planted_db, tmp_path, kg_cache, tmp_path_factory):
    """The planted data (tests/fixtures/plant.py) on each store. On Virtuoso, the export of the planted data."""
    handle = open_store_handle(request, planted_db, tmp_path, kg_cache, tmp_path_factory, seed=False)
    yield handle
    handle.close()


@pytest.fixture(params=store_params(pytest.mark.slow))
def full_store(request, full_db, tmp_path, kg_cache, tmp_path_factory):
    """The full data (the onboarding) on each store ("slow"). The first run builds the full graph (about 15 s)."""
    handle = open_store_handle(request, full_db, tmp_path, kg_cache, tmp_path_factory, seed=False)
    yield handle
    handle.close()
