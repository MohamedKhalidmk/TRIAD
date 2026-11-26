"""Helpers of the store tests of the patients, the visits, the audit log and the chat (plan 5.6).

A KG store must give the same results as SQLite on the same data:
- For a read, `store.reference()` is a SQLite context on the same data (for the sqlite store, the store itself).
- For a write, the `twin` fixture is a SQLite copy of the data that the test makes BEFORE it writes. The test sends
  each write to the store and to the twin, then compares the responses and the reads after the write. (A KG write
  does not change the SQLite copy of a KG store, and the reference of the sqlite store is the store itself.)
- `instants(value)` gives each time as an instant: the stores can give another text of the same time (D11:
  "Z" becomes "+00:00", no trailing zeros of the seconds).

The repositories of the agents B (records) and D (directory) are stubs in this worktree. `borrow_stub_reads`
makes each stub READ method of the KG store read the SQLite copy of the store (the data that the test does not
change: the locations, the assertions). A method that is not a stub (after the merge) is not changed.
"""
from __future__ import annotations

import dataclasses
import re
import shutil
from pathlib import Path
from typing import Any, Iterable

import pytest

from domain.rules import parse_time
from tests.conftest import as_user, make_client
from tests.fixtures.stores import base_settings

TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
MOA, PARK, OKAFOR, BRENNAN, ELENA = "MOA:E1001", "Nurse:E1004", "Doctor:E1005", "Doctor:E1006", "Patient:MRN-000001"
EMPLOYEE = "https://triad.example/fhir/sid/employee"
SUBJECT = ("Elena Marsh", "1971-05-14")


def instants(value: Any) -> Any:
    """The value with each ISO 8601 time (a text with a "T") as an aware datetime, for a comparison."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = dataclasses.asdict(value)
    if isinstance(value, dict):
        return {k: instants(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(instants(v) for v in value)
    if isinstance(value, str) and TIME.match(value):
        return parse_time(value)
    return value


def same(left: Any, right: Any) -> bool:
    return instants(left) == instants(right)


def response(r) -> tuple[int, Any]:
    """The status and the body of a response (None for no body), with the times as instants."""
    return r.status_code, instants(r.json()) if r.content else None


class Twin:
    """A SQLite copy of the data of a store, made before the test writes."""

    def __init__(self, path: Path):
        self.path = path
        self._client = None

    def client(self):
        if self._client is None:
            self._client = make_client(self.path)
        return self._client

    def ctx(self):
        import main
        return main.context_factory(base_settings(self.path))()


@pytest.fixture
def twin(store, tmp_path) -> Twin:
    path = tmp_path / "twin.db"
    shutil.copy(store.db_path, path)
    return Twin(path)


def both(store, twin: Twin, method: str, url: str, user: str, **kwargs) -> tuple[int, Any]:
    """Send one request to the store and to the twin. They must give the same response. Return it."""
    found = response(getattr(store.client(), method)(url, headers=as_user(user), **kwargs))
    expected = response(getattr(twin.client(), method)(url, headers=as_user(user), **kwargs))
    assert found == expected, f"{method.upper()} {url} as {user}"
    return found


def rows_without(rows: Iterable[dict], *names: str) -> list[dict]:
    return [{k: v for k, v in r.items() if k not in names} for r in rows]


# ---------------------------------------------------------------------------------------------
# The stub reads of the other agents (until the merge)

def is_stub(cls: type, name: str) -> bool:
    """True if the method of the KG repository is still a stub of another agent (it raises NotImplementedError
    before it reads the store)."""
    import ast
    import inspect
    import textwrap
    function = ast.parse(textwrap.dedent(inspect.getsource(getattr(cls, name)))).body[0]
    body = [s for s in function.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
    return (len(body) == 1 and isinstance(body[0], ast.Raise) and isinstance(body[0].exc, ast.Call)
            and getattr(body[0].exc.func, "id", None) == "NotImplementedError")


def borrow_stub_reads(monkeypatch, store, kg_class: type, sqlite_class: type, names: Iterable[str]) -> list[str]:
    """Each stub method of `names` reads the SQLite copy of the store. Return the names that it changed."""
    if not store.is_kg:
        return []
    from infrastructure.sqlite.connection import connect
    conn = connect(store.db_path)
    reader = sqlite_class(conn)
    changed = []
    for name in names:
        if is_stub(kg_class, name):
            target = getattr(reader, name)
            monkeypatch.setattr(kg_class, name, lambda self, *args, _target=target, **kw: _target(*args, **kw))
            changed.append(name)
    return changed


DIRECTORY_READS = ("location", "location_by_identifier", "staff_by_identifier")
RECORD_READS = ("items_page", "category_counts", "allergies", "prescriptions", "diagnoses", "lab_items",
                "visit_items", "latest_observations", "recommendations", "assertion", "assertions_by_id", "chain",
                "chain_page", "chain_head", "entry", "care_team_versions")


@pytest.fixture
def directory_reads(store, monkeypatch) -> list[str]:
    from infrastructure.sparql.directory_repository import SparqlDirectoryRepository
    from infrastructure.sqlite.directory_repository import SqliteDirectoryRepository
    return borrow_stub_reads(monkeypatch, store, SparqlDirectoryRepository, SqliteDirectoryRepository,
                             DIRECTORY_READS)


@pytest.fixture
def record_reads(store, monkeypatch) -> list[str]:
    from infrastructure.sparql.records_repository import SparqlRecordRepository
    from infrastructure.sqlite.records_repository import SqliteRecordRepository
    return borrow_stub_reads(monkeypatch, store, SparqlRecordRepository, SqliteRecordRepository, RECORD_READS)


# ---------------------------------------------------------------------------------------------
# A recorder of the update requests of a KG context

class Recorder:
    """A SPARQL client between a KG unit of work and its store: it records the templates of the updates."""

    def __init__(self, client):
        self.client = client
        self.updates: list[str] = []

    @property
    def store(self):
        return self.client.store

    @property
    def key(self):
        return self.client.key

    def select(self, template, bindings=None, *, raw=False):
        return self.client.select(template, bindings, raw=raw)

    def ask(self, template, bindings=None):
        return self.client.ask(template, bindings)

    def update(self, template, bindings=None):
        self.updates.append(template)
        self.client.update(template, bindings)
