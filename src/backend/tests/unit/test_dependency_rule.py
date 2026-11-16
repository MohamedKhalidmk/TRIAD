"""The dependency rule of the backend (plan 5, "Repository layout"; README "Architecture").

- The RDF packages (rdflib, pyoxigraph, SPARQLWrapper, morph_kgc, pyshacl, owlrl) are imported only in
  infrastructure/, models/semantic/ and the tests.
- api, application and domain do not import infrastructure; only main.py knows the adapters.
- The SQLite path (TRIAD_STORE=sqlite) loads no RDF package, so the Milestone 4 app does not need them.
"""
from __future__ import annotations

import re
import subprocess
import sys

from infrastructure import config

BACKEND = config.BACKEND_DIR
RDF_PACKAGES = ("rdflib", "pyoxigraph", "SPARQLWrapper", "morph_kgc", "pyshacl", "owlrl")
IMPORT = re.compile(r"^\s*(?:from|import)\s+(" + "|".join(RDF_PACKAGES) + r")\b", re.M)
ALLOWED = ("infrastructure", "models/semantic", "tests")


def python_files():
    for path in sorted(BACKEND.rglob("*.py")):
        relative = path.relative_to(BACKEND).as_posix()
        if "/__pycache__/" not in relative and not relative.startswith("data/"):
            yield relative, path.read_text(encoding="utf-8")


def test_the_rdf_packages_are_imported_only_in_infrastructure_models_semantic_and_tests():
    found = [(relative, match.group(1)) for relative, text in python_files() for match in IMPORT.finditer(text)
             if not relative.startswith(ALLOWED)]
    assert found == []
    assert any(IMPORT.search(text) for relative, text in python_files() if relative.startswith("infrastructure/"))


def test_the_inner_layers_do_not_import_the_adapters():
    pattern = re.compile(r"^\s*(?:from|import)\s+(infrastructure|api|main)\b", re.M)
    for layer in ("domain/", "application/"):
        found = [(relative, m.group(1)) for relative, text in python_files() if relative.startswith(layer)
                 for m in pattern.finditer(text)]
        assert found == [], layer
    found = [relative for relative, text in python_files() if relative.startswith("api/")
             and re.search(r"^\s*(?:from|import)\s+(infrastructure|main)\b", text, re.M)]
    assert found == []


def test_the_sqlite_path_loads_no_rdf_package(scenario_db, tmp_path):
    script = f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(BACKEND)!r})
import main
from infrastructure import config
from fastapi.testclient import TestClient
settings = config.Settings.from_env(db_path={str(scenario_db)!r}, store="sqlite", sql_log="off", now="system",
                                    frontend_dist=Path({str(tmp_path / "none")!r}))
client = TestClient(main.create_app(settings))
assert client.get("/api/health").json()["store"] == "sqlite"
assert client.get("/api/users").status_code == 200
loaded = sorted(name for name in sys.modules if name.split(".")[0] in {RDF_PACKAGES!r})
loaded += sorted(name for name in sys.modules
                 if name.startswith("infrastructure.sparql") or name == "infrastructure.rdf.kg_store")
print(loaded)
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=str(tmp_path))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"
