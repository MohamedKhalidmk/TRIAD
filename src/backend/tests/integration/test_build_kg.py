"""The knowledge-graph build (plan 3.5): ensure-kg, load-kg, the marker, the start check and the store adapters.

The use case runs with fake ports (the order of the steps) and with the real adapters on Oxigraph: the export of a
copy of the scenario database, the bulk load, the counts, the counters and the marker.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import types
from pathlib import Path

import pytest

from application.semantic import build_kg
from application.semantic.build_kg import KgBuildError, KgExport, KgMarker
from infrastructure import config

pytest.importorskip("pyoxigraph")


# ---------------------------------------------------------------------------------------------
# The use case with fake ports

class FakeSource:
    def __init__(self, data_hash="d1"):
        self.data_hash = data_hash

    def fingerprint(self):
        return self.data_hash

    def sequences(self):
        return {"Patient": 3, "Assertion": 10}


class FakeExporter:
    def __init__(self):
        self.exports = 0

    def mapping_fingerprint(self):
        return "m1", "5.0.0"

    def export(self, scope, marker):
        self.exports += 1
        return KgExport(Path("tbox.owl"), Path("abox.nt.gz"), {"p": 2, "q": 1})


class FakeStore:
    name = "Fake"

    def __init__(self, marker=None, counts=None):
        self._marker = marker
        self.counts = counts or {"p": 2, "q": 1}
        self.steps = []

    def marker(self):
        return self._marker

    def set_marker(self, marker):
        self.steps.append("set_marker")
        self._marker = marker

    def clear(self, graph):
        self.steps.append(f"clear {graph}")

    def load(self, files):
        self.steps.append("load " + ",".join(sorted(files)))

    def predicate_counts(self):
        self.steps.append("counts")
        return self.counts

    def seed_counters(self, sequences):
        self.steps.append("counters")
        return dict(sequences)


def test_a_current_marker_does_nothing():
    marker = KgMarker("d1", "m1", "5.0.0", "all")
    store, exporter = FakeStore(marker), FakeExporter()
    result = build_kg.ensure_kg(FakeSource(), exporter, store)
    assert result.state == "current" and exporter.exports == 0 and store.steps == []


def test_a_build_writes_the_marker_last():
    store, exporter = FakeStore(), FakeExporter()
    result = build_kg.ensure_kg(FakeSource(), exporter, store)
    assert result.state == "built" and result.reason == "the store has no build marker"
    assert store.steps == ["clear meta", "load abox,tbox", "counts", "counters", "set_marker"]
    assert store.marker() == KgMarker("d1", "m1", "5.0.0", "all") and result.triples == 3


@pytest.mark.parametrize("found, reason", [
    (KgMarker("d0", "m1", "5.0.0", "all"), "the relational data changed"),
    (KgMarker("d1", "m0", "5.0.0", "all"), "the R2RML mapping changed"),
    (KgMarker("d1", "m1", "4.9.0", "all"), "the ontology version changed (4.9.0 -> 5.0.0)"),
    (KgMarker("d1", "m1", "5.0.0", "scenarios"), "the scope changed (scenarios -> all)"),
])
def test_each_change_of_the_marker_gives_a_build(found, reason):
    result = build_kg.ensure_kg(FakeSource(), FakeExporter(), FakeStore(found))
    assert result.state == "built" and result.reason == reason


def test_reset_builds_also_with_a_current_marker():
    store = FakeStore(KgMarker("d1", "m1", "5.0.0", "all"))
    assert build_kg.ensure_kg(FakeSource(), FakeExporter(), store, reset=True).reason == "--reset-kg"


def test_wrong_counts_stop_the_build_with_no_marker():
    store = FakeStore(counts={"p": 1})
    with pytest.raises(KgBuildError, match="p: the export 2, the store 1"):
        build_kg.ensure_kg(FakeSource(), FakeExporter(), store)
    assert "set_marker" not in store.steps and store.marker() is None


# ---------------------------------------------------------------------------------------------
# The real adapters on Oxigraph

@pytest.fixture
def kg(scenario_db, tmp_path):
    """A copy of the scenario database, an empty Oxigraph folder and the adapters on them."""
    pytest.importorskip("morph_kgc")
    from infrastructure.rdf import oxigraph_store
    from infrastructure.rdf.kg_store import MorphKgcExporter, OxigraphTripleStore, SqliteKgSource
    from infrastructure.sparql.client import EmbeddedSparqlClient
    db = tmp_path / "copy.db"
    shutil.copy(scenario_db, db)
    path = tmp_path / "oxigraph"

    class Counting(MorphKgcExporter):
        exports = 0

        def export(self, scope, marker):
            Counting.exports += 1
            return super().export(scope, marker)

    client = EmbeddedSparqlClient(path)
    parts = types.SimpleNamespace(db=db, path=path, client=client, source=SqliteKgSource(db),
                                  exporter=Counting(db, tmp_path / "kg"), store=OxigraphTripleStore(client),
                                  kg_dir=tmp_path / "kg")
    parts.ensure = lambda **kw: build_kg.ensure_kg(parts.source, parts.exporter, parts.store, **kw)
    yield parts
    oxigraph_store.close_store(path)


def test_ensure_kg_builds_once_and_keeps_the_writes_of_kg_mode(kg):
    from infrastructure.clock import DemoClock
    from infrastructure.rdf.logical_hash import sequences
    from infrastructure.sparql import ids
    from infrastructure.sparql.unit_of_work import KgSession, SparqlUnitOfWork
    first = kg.ensure()
    assert first.state == "built" and first.triples == 1125 and kg.exporter.exports == 1
    assert json.loads((kg.kg_dir / "kg_report.json").read_text())["marker"]["data_hash"] == first.marker.data_hash
    assert ids.read_counters(kg.client) == ids.seed_values(sequences(kg.db))
    session = KgSession(kg.client)                          # a write in KG mode
    with SparqlUnitOfWork(session, DemoClock("2026-10-30T09:00:00-04:00")).write():
        medication = session.write_buffer().create("medication", {"code": "K", "codeSystem": "urn:k", "name": "K"})
    second = kg.ensure()
    assert second.state == "current" and kg.exporter.exports == 1
    ask = "ASK FROM $abox WHERE { $m triad:name \"K\" }"
    from infrastructure.sparql.terms import iri
    assert kg.client.ask(ask, {"m": iri("medication", medication)})


def test_a_journal_mode_change_does_not_build_again(kg):
    kg.ensure()
    conn = sqlite3.connect(kg.db)
    assert conn.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
    conn.close()
    assert kg.ensure().state == "current" and kg.exporter.exports == 1


def test_a_data_change_builds_again_and_a_rebuild_deletes_the_kg_writes(kg):
    from infrastructure.sparql.terms import iri
    kg.ensure()
    kg.client.update("INSERT DATA { GRAPH $abox { $s triad:city \"Written in KG mode\" } }", {"s": iri("patient", 1)})
    conn = sqlite3.connect(kg.db)
    conn.execute("UPDATE Patient SET PhoneNumber = '+1-555-0000' WHERE Id = 1")
    conn.commit()
    conn.close()
    result = kg.ensure()
    assert result.state == "built" and result.reason == "the relational data changed" and kg.exporter.exports == 2
    assert not kg.client.ask("ASK FROM $abox WHERE { ?s triad:city \"Written in KG mode\" }")
    assert kg.client.ask("ASK FROM $abox WHERE { ?s triad:phoneNumber \"+1-555-0000\" }")


# ---------------------------------------------------------------------------------------------
# The commands of main.py and the start check

@pytest.fixture
def no_env(monkeypatch, tmp_path):
    """The commands do not read the .env file of the developer; the KG files go into tmp_path."""
    monkeypatch.setattr(config, "load_env_file", lambda *args, **kwargs: [])
    for name in ("TRIAD_STORE", "TRIAD_SPARQL_LOG", "TRIAD_SQL_LOG", "TRIAD_NOW"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TRIAD_KG_DIR", str(tmp_path / "kg"))
    monkeypatch.setenv("TRIAD_KG_OXIGRAPH_PATH", str(tmp_path / "oxigraph"))
    yield tmp_path
    from infrastructure.rdf import oxigraph_store
    oxigraph_store.close_store(tmp_path / "oxigraph")


def test_the_kg_commands_need_a_kg_store(no_env, scenario_copy):
    import main
    with pytest.raises(SystemExit, match="--store oxigraph"):
        main.main(["ensure-kg", "--db", str(scenario_copy)])


def test_ensure_kg_and_serve_on_oxigraph(no_env, scenario_copy, capsys):
    pytest.importorskip("morph_kgc")
    import main
    from fastapi.testclient import TestClient
    main.main(["ensure-kg", "--db", str(scenario_copy), "--store", "oxigraph"])
    assert "Built the knowledge graph of the oxigraph store" in capsys.readouterr().out
    main.main(["ensure-kg", "--db", str(scenario_copy), "--store", "oxigraph"])
    assert "is current" in capsys.readouterr().out
    settings = config.Settings.from_env(db_path=scenario_copy, store="oxigraph", sparql_log="off",
                                        frontend_dist=no_env / "none")
    health = TestClient(main.create_app(settings)).get("/api/health").json()
    assert health["store"] == "oxigraph" and health["ontologyVersion"] == "5.0.0"


def test_load_kg_of_the_seed_graph_needs_no_export(no_env, scenario_copy, capsys, monkeypatch):
    import main
    from infrastructure.rdf import kg_export
    with monkeypatch.context() as patch:                     # only this block: the env of no_env stays
        patch.setattr(kg_export, "_morph_kgc", lambda: pytest.fail("load-kg --seed runs no export"))
        main.main(["load-kg", "--seed", "--store", "oxigraph"])
    assert "1,125 triples" in capsys.readouterr().out
    settings = config.Settings.from_env(db_path=scenario_copy, store="oxigraph", sparql_log="off",
                                        frontend_dist=no_env / "none")
    from fastapi.testclient import TestClient
    users = TestClient(main.create_app(settings)).get("/api/users").json()
    assert users["total"] == 26
    # The seed graph is the scenario data (01 + 02): ensure-kg on the same data finds the marker current.
    main.main(["ensure-kg", "--db", str(scenario_copy), "--store", "oxigraph"])
    assert "is current" in capsys.readouterr().out
    assert not (config.DEFAULT_KG_DIR / "oxigraph").exists() or config.env_kg_dir() != config.DEFAULT_KG_DIR


def test_the_start_check_needs_a_current_marker(no_env, scenario_copy):
    import main
    from infrastructure.rdf.kg_store import MARKER, OxigraphTripleStore
    from infrastructure.sparql.client import EmbeddedSparqlClient
    settings = config.Settings.from_env(db_path=scenario_copy, store="oxigraph", sparql_log="off")
    with pytest.raises(SystemExit, match=r"no build marker\). Run: python src/backend/main.py ensure-kg --store oxi"):
        main.create_app(settings)
    store = OxigraphTripleStore(EmbeddedSparqlClient(no_env / "oxigraph"))
    store.set_marker(KgMarker("d", "m", "4.0.0", "all"))
    with pytest.raises(SystemExit, match="another ontology or mapping"):
        main.create_app(settings)
    assert MARKER.startswith("<https://github.com/MohamedKhalidmk/TRIAD/kg/")


def test_validate_kg_calls_the_shacl_module(no_env, monkeypatch, capsys):
    import main
    from infrastructure.rdf.kg_store import SEED_PATH
    calls = []
    fake = types.ModuleType("infrastructure.rdf.shacl")
    fake.main = lambda argv: calls.append(argv) or 0
    monkeypatch.setitem(sys.modules, "infrastructure.rdf.shacl", fake)
    import infrastructure.rdf as rdf_package
    monkeypatch.setattr(rdf_package, "shacl", fake, raising=False)          # an earlier import set this name
    with pytest.raises(SystemExit) as stop:
        main.main(["validate-kg"])
    assert stop.value.code == 0 and calls == [[str(SEED_PATH)]]
    fake.main = lambda argv: calls.append(argv) or 1
    with pytest.raises(SystemExit) as stop:
        main.main(["validate-kg", "--file", "x.rdf"])
    assert stop.value.code == 1 and calls[-1] == ["x.rdf"]


def test_validate_kg_without_the_shacl_module(no_env, monkeypatch):
    import main
    monkeypatch.setitem(sys.modules, "infrastructure.rdf.shacl", None)     # an import of it fails
    import infrastructure.rdf as rdf_package
    monkeypatch.delattr(rdf_package, "shacl", raising=False)                # an earlier import set this name
    with pytest.raises(SystemExit, match="SHACL check is not available"):
        main.main(["validate-kg"])


# ---------------------------------------------------------------------------------------------
# The Virtuoso adapter (no Docker: a fake runner records the command)

def test_virtuoso_loads_the_files_with_kg_sh(tmp_path):
    import subprocess
    from infrastructure.rdf.kg_store import NT_FILE, OWL_PATH, SEED_PATH, VirtuosoTripleStore
    runs = []

    def run(command, env, cwd):
        runs.append((command[1:], env["TRIAD_KG_DIR"]))
        return subprocess.CompletedProcess(command, 0)

    store = VirtuosoTripleStore(client=None, kg_dir=tmp_path, run=run)
    store.forget_state = lambda: None
    store.load({"tbox": OWL_PATH, "abox": tmp_path / NT_FILE})
    store.load({"tbox": OWL_PATH, "abox": SEED_PATH})
    assert runs == [(["load", "--no-export"], str(tmp_path)), (["load", "--seed"], str(tmp_path))]
    with pytest.raises(KgBuildError, match="mounts only"):
        store.load({"tbox": OWL_PATH, "abox": tmp_path / "other.nt.gz"})
    with pytest.raises(KgBuildError, match="TBox"):
        store.load({"tbox": tmp_path / "x.owl", "abox": SEED_PATH})
    failing = VirtuosoTripleStore(None, tmp_path, run=lambda c, env, cwd: subprocess.CompletedProcess(c, 1))
    with pytest.raises(KgBuildError, match="exit code 1"):
        failing.load({"tbox": OWL_PATH, "abox": SEED_PATH})
