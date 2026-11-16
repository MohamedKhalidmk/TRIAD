"""The stores of the tests: the same API test on SQLite and on the knowledge graph (plan 5, section 5.6).

conftest.py makes the fixtures `store` (the scenario data), `planted_store` (the planted data) and `full_store`
(the full data, "slow") from these parts. Each one is a StoreHandle:

    store.name          "sqlite", "oxigraph" or "virtuoso"
    store.is_kg         True for a knowledge-graph store
    store.client()      a FastAPI TestClient on the store (the same object for each call in a test)
    store.open_ctx()    an AppContext of the store (the adapters of main.context_factory)
    store.reference()   an AppContext on the SQLite copy of the same data (the reference of a KG test)
    store.probe         reads the stored rows: count(), rows(), row(), last() (see Probe)
    store.db_path       the SQLite copy: the store itself for "sqlite", the source of the graph for a KG store
    store.time_limit(s) a time limit of a SQLite test for this store

A test on Oxigraph gets a new copy of a built store (pyoxigraph backup(): hard links, some milliseconds).
The built store stays on disk (.pytest_cache/d/triad-kg/<marker>/), keyed by the build marker of its data, so a
test run does not export and load the triples each time. The first run makes it (Morph-KGC and the bulk load).
Virtuoso is one store: the fixture loads the data again only when the marker differs or when the last test wrote.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from infrastructure import config

DEMO_NOW = "2026-10-30T09:00:00-04:00"
DEFAULT_STORES = ("sqlite", "oxigraph")
KG_STORES = ("oxigraph", "virtuoso")
# How much slower a KG store can be than SQLite in a test with a time limit (test_api.py has 300 ms for a page).
TIME_FACTOR = {"sqlite": 1.0, "oxigraph": 3.0, "virtuoso": 10.0}


def selected_stores() -> tuple[str, ...]:
    """The stores of the parametrized fixtures: TRIAD_TEST_STORES (comma-separated), else sqlite and oxigraph."""
    text = os.environ.get("TRIAD_TEST_STORES", "").strip()
    names = tuple(n.strip().lower() for n in text.split(",") if n.strip()) if text else DEFAULT_STORES
    unknown = set(names) - set(config.STORES)
    if unknown:
        raise ValueError(f"TRIAD_TEST_STORES names unknown stores: {', '.join(sorted(unknown))}.")
    return names


def base_settings(db_path: Path, **values: Any) -> config.Settings:
    """The settings of a test app: fake chat, the fixed demo time, no log, no frontend, the SQLite store."""
    defaults = dict(db_path=db_path, now=DEMO_NOW, llm_mode="fake", frontend_dist=Path(db_path).parent / "no-frontend",
                    sql_log="off", sparql_log="off", store="sqlite")
    defaults.update(values)
    return config.Settings.from_env(**defaults)


# ---------------------------------------------------------------------------------------------
# The built Oxigraph stores (cached on disk, keyed by the marker)

def marker_key(db_path: Path, scope: str = "all") -> str:
    """A short key of the build marker of a database (the data, the mapping, the ontology version, the scope)."""
    from application.semantic.build_kg import wanted_marker
    from infrastructure.rdf.kg_store import MorphKgcExporter, SqliteKgSource
    marker = wanted_marker(SqliteKgSource(db_path), MorphKgcExporter(db_path, Path(".")), scope)
    text = json.dumps([marker.data_hash, marker.mapping_hash, marker.ontology_version, marker.scope])
    return hashlib.sha256(text.encode()).hexdigest()[:20]


def build_oxigraph(db_path: Path, folder: Path) -> None:
    """Build the knowledge graph of a database into folder/oxigraph with the use case of ensure-kg."""
    from application.semantic.build_kg import ensure_kg
    from infrastructure.rdf import oxigraph_store
    from infrastructure.rdf.kg_store import MorphKgcExporter, OxigraphTripleStore, SqliteKgSource
    from infrastructure.sparql.client import EmbeddedSparqlClient
    path = folder / "oxigraph"
    client = EmbeddedSparqlClient(path)
    try:
        ensure_kg(SqliteKgSource(db_path), MorphKgcExporter(db_path, folder / "kg"), OxigraphTripleStore(client))
    finally:
        del client
        oxigraph_store.close_store(path)
    shutil.rmtree(folder / "kg", ignore_errors=True)


def cached_oxigraph(db_path: Path, cache_root: Path) -> Path:
    """The folder of the built Oxigraph store of a database. It is built once for each marker."""
    final = cache_root / marker_key(db_path)
    if (final / "BUILT").is_file():
        return final / "oxigraph"
    cache_root.mkdir(parents=True, exist_ok=True)
    work = cache_root / f".build-{uuid.uuid4().hex[:8]}"
    build_oxigraph(db_path, work)
    (work / "BUILT").write_text("built by tests/fixtures/stores.py\n", encoding="utf-8")
    if final.exists():
        shutil.rmtree(work, ignore_errors=True)   # another run built it first
    else:
        os.replace(work, final)
    return final / "oxigraph"


def copy_oxigraph(source: Path, target: Path) -> Path:
    """A new copy of a built store (pyoxigraph backup). The source stays open in this process (one Store)."""
    from infrastructure.rdf import oxigraph_store
    return oxigraph_store.backup_store(oxigraph_store.open_store(source), target)


# ---------------------------------------------------------------------------------------------
# The probe: the stored rows, the same on each store

def _ddl_foreign_keys() -> dict[tuple[str, str], str]:
    """(table, FK column) -> the table of the target row, from the DDL."""
    from models.semantic.mapping.build_mapping import ddl_connection, ddl_tables
    conn = ddl_connection()
    try:
        return {(table, row[3]): row[2] for table in ddl_tables(conn)
                for row in conn.execute(f'PRAGMA foreign_key_list("{table}")')}
    finally:
        conn.close()


@dataclass
class Vocabulary:
    """The map between the SQLite columns and the ontology terms of one kind (from vocabulary.py)."""
    columns: dict[str, str] = field(default_factory=dict)       # term -> column
    fk_kind: dict[str, str] = field(default_factory=dict)        # FK term -> kind of the target (or of the parent)
    reverse: set[str] = field(default_factory=set)               # the FK terms of the reverse direction


def vocabulary_of(kind: str) -> Vocabulary:
    from infrastructure.sparql.ids import KIND_TABLE, TABLE_KIND
    from models.semantic import vocabulary as V
    table = KIND_TABLE[kind]
    targets = _ddl_foreign_keys()
    out = Vocabulary()
    for (t, column), (term, sort) in V.COLUMNS.items():
        if t != table:
            continue
        out.columns[term] = column
        if sort in (V.FK, V.FK_REVERSE):
            target = targets[(t, column)]
            out.fk_kind[term] = "clinical-entry" if (t, column) in V.FK_JOINS else TABLE_KIND[target]
            if sort == V.FK_REVERSE:
                out.reverse.add(term)
    return out


class Probe:
    """Reads stored rows by the ontology terms, for a test that read them with SQL before.

    - count(kind, **match): the number of rows of a kind whose values equal `match`;
    - rows(kind, **match): the rows (dicts term -> value, with "id"), by id;
    - row(kind, id), last(kind): one row, or None.
    A value of an FK term is the integer id of the target (the parent for a reverse-direction term, for example
    "issues" of a message is the staff id). A time is the text of the store (compare times as instants).
    Example: store.probe.count("audit-event", auditOutcome="Denied").
    count(kind) with no match is one COUNT, and row(kind, id) reads one subject: use them on the full data.
    """

    def rows(self, kind: str, **match: Any) -> list[dict]:
        return [row for row in self._rows(kind) if all(row.get(term) == value for term, value in match.items())]

    def count(self, kind: str, **match: Any) -> int:
        return len(self.rows(kind, **match)) if match else self._count(kind)

    def row(self, kind: str, id_: int) -> Optional[dict]:
        found = self._rows(kind, id_)
        return found[0] if found else None

    def last(self, kind: str) -> Optional[dict]:
        found = self.rows(kind)
        return found[-1] if found else None

    def _rows(self, kind: str, id_: Optional[int] = None) -> list[dict]:
        """All rows of a kind by id, or only the row with this id."""
        raise NotImplementedError

    def _count(self, kind: str) -> int:
        return len(self._rows(kind))


class SqliteProbe(Probe):
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _rows(self, kind: str, id_: Optional[int] = None) -> list[dict]:
        from infrastructure.sparql.ids import KIND_TABLE
        from models.semantic import vocabulary as V
        table, voc = KIND_TABLE[kind], vocabulary_of(kind)
        conn = self._connect()
        try:
            out = []
            where, args = ("WHERE Id = ?", (id_,)) if id_ is not None else ("", ())
            for r in conn.execute(f'SELECT * FROM "{table}" {where} ORDER BY Id', args):
                row = {"id": r["Id"]}
                for term, column in voc.columns.items():
                    value = r[column]
                    if (table, column) in V.FK_JOINS and value is not None:
                        join_table, join_column, subject_column = V.FK_JOINS[(table, column)]
                        value = conn.execute(f'SELECT "{subject_column}" FROM "{join_table}" WHERE "{join_column}" = ?',
                                             (value,)).fetchone()[0]
                    if isinstance(value, int) and term == "active":
                        value = bool(value)
                    row[term] = value
                out.append(row)
            return out
        finally:
            conn.close()

    def _count(self, kind: str) -> int:
        from infrastructure.sparql.ids import KIND_TABLE
        conn = self._connect()
        try:
            return conn.execute(f'SELECT COUNT(*) FROM "{KIND_TABLE[kind]}"').fetchone()[0]
        finally:
            conn.close()


class KgProbe(Probe):
    def __init__(self, client: Any):
        self.client = client

    ROWS = "SELECT ?x ?p ?o ?in FROM $abox WHERE { ?x a $class . { ?x ?p ?o } UNION { ?o ?p ?x . BIND (1 AS ?in) } }"
    ONE = ("SELECT ?x ?p ?o ?in FROM $abox WHERE { VALUES ?x { $x } ?x a $class . "
           "{ ?x ?p ?o } UNION { ?o ?p ?x . BIND (1 AS ?in) } }")
    COUNT = "SELECT (COUNT(?x) AS ?n) FROM $abox WHERE { ?x a $class }"

    def _rows(self, kind: str, id_: Optional[int] = None) -> list[dict]:
        from infrastructure.sparql import terms
        voc = vocabulary_of(kind)
        bindings = {"class": terms.class_term(terms.CLASS_OF_KIND[kind])}
        if id_ is not None:
            bindings["x"] = terms.iri(kind, id_)
        rows = self.client.select(self.ROWS if id_ is None else self.ONE, bindings)
        found: dict[str, dict] = {}
        for r in rows:
            row = found.setdefault(r["x"], {"id": terms.id_of(r["x"]), **dict.fromkeys(voc.columns)})
            if not str(r["p"]).startswith(terms.TRIAD):
                continue
            term = terms.name_of(r["p"])
            if term not in voc.columns or (r["in"] is not None) != (term in voc.reverse):
                continue
            value = r["o"]
            if term in voc.fk_kind:
                value = terms.id_of(value)
            row[term] = value
        return [row for _, row in sorted(found.items(), key=lambda item: item[1]["id"])]

    def _count(self, kind: str) -> int:
        from infrastructure.sparql import terms
        rows = self.client.select(self.COUNT, {"class": terms.class_term(terms.CLASS_OF_KIND[kind])})
        return int(rows[0]["n"])


# ---------------------------------------------------------------------------------------------
# The handle of one store in one test

@dataclass
class StoreHandle:
    name: str
    db_path: Path
    settings: config.Settings
    probe: Probe
    cleanup: list[Callable[[], None]] = field(default_factory=list)
    _client: Any = None

    @property
    def is_kg(self) -> bool:
        return self.name != "sqlite"

    def client(self, **settings: Any):
        """A TestClient on the store. With no settings, the same client for each call of the test."""
        import main
        from fastapi.testclient import TestClient
        if settings:
            return TestClient(main.create_app(base_settings(**{**self._values(), **settings})))
        if self._client is None:
            self._client = TestClient(main.create_app(self.settings))
        return self._client

    def _values(self) -> dict:
        s = self.settings
        return dict(db_path=s.db_path, store=s.store, kg_oxigraph_path=s.kg_oxigraph_path, kg_dir=s.kg_dir)

    def open_ctx(self):
        import main
        return main.context_factory(self.settings)()

    def reference(self):
        """An AppContext on the SQLite copy of the same data (for example the reference of a tool test)."""
        import main
        return main.context_factory(base_settings(self.db_path))()

    def time_limit(self, sqlite_seconds: float) -> float:
        return sqlite_seconds * TIME_FACTOR[self.name]

    def close(self) -> None:
        for step in reversed(self.cleanup):
            step()
        self.cleanup.clear()


def sqlite_handle(db_copy: Path) -> StoreHandle:
    return StoreHandle("sqlite", db_copy, base_settings(db_copy), SqliteProbe(db_copy))


def oxigraph_handle(db_copy: Path, built: Path, target: Path) -> StoreHandle:
    """A handle on a new copy of a built Oxigraph store. close() releases the copy."""
    from infrastructure.rdf import oxigraph_store
    from infrastructure.sparql.client import EmbeddedSparqlClient
    copy_oxigraph(built, target)
    settings = base_settings(db_copy, store="oxigraph", kg_oxigraph_path=target, kg_dir=target.parent / "kg")
    handle = StoreHandle("oxigraph", db_copy, settings, KgProbe(EmbeddedSparqlClient(target)))

    def release() -> None:
        import gc
        from infrastructure.sparql.unit_of_work import StoreState
        handle._client = None
        handle.probe = None
        StoreState.forget(f"oxigraph:{target.resolve()}")
        oxigraph_store.close_store(target)
        gc.collect()   # the app objects of the test hold the Store of the copy; free it (and its files) now
    handle.cleanup.append(release)
    return handle


def virtuoso_answers(settings: config.Settings) -> bool:
    from infrastructure.sparql.client import HttpSparqlClient, SparqlStoreError
    client = HttpSparqlClient(settings.sparql_query_url, settings.sparql_update_url, settings.sparql_user,
                              settings.sparql_password, timeout=3)
    try:
        client.ask("ASK FROM $abox WHERE { ?s ?p ?o }")
        return True
    except SparqlStoreError:
        return False


def virtuoso_handle(db_copy: Path, seed: bool) -> StoreHandle:
    """A handle on the one Virtuoso store. This REPLACES the TRIAD graphs of the container (see the module text).

    seed=True: the scenario data (kg.sh load --seed). seed=False: the export of db_copy (ensure-kg, which writes
    the export files into TRIAD_KG_DIR, the folder that the container mounts).
    """
    from application.semantic.build_kg import ensure_kg, load_kg, wanted_marker
    from infrastructure.rdf.kg_store import MorphKgcExporter, SeedSource, SqliteKgSource, VirtuosoTripleStore
    from infrastructure.sparql.client import HttpSparqlClient
    from infrastructure.sparql.unit_of_work import StoreState
    settings = base_settings(db_copy, store="virtuoso", kg_dir=config.env_kg_dir())
    client = HttpSparqlClient(settings.sparql_query_url, settings.sparql_update_url, settings.sparql_user,
                              settings.sparql_password)
    store = VirtuosoTripleStore(client, settings.kg_dir)
    state = StoreState.of(client.key)
    if seed:
        source = SeedSource()
        try:
            if store.marker() != source.marker() or state.last_write is not None:
                load_kg(source, source.export(), source.marker(), store, "the tests")
        finally:
            source.close()
    else:
        source = SqliteKgSource(db_copy)
        exporter = MorphKgcExporter(db_copy, settings.kg_dir)
        reset = state.last_write is not None and store.marker() == wanted_marker(source, exporter, "all")
        ensure_kg(source, exporter, store, reset=reset)
    StoreState.forget(client.key)
    return StoreHandle("virtuoso", db_copy, settings, KgProbe(client))
