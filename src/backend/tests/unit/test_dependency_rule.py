"""The dependency rule of the backend (plan 5, "Repository layout"; README "Architecture").

- The RDF packages (rdflib, pyoxigraph, SPARQLWrapper, morph_kgc, pyshacl, owlrl) are imported only in
  infrastructure/, models/semantic/ and the tests.
- api, application and domain do not import infrastructure; only main.py knows the adapters.
- The SQLite path (TRIAD_STORE=sqlite) loads no RDF package, so the Milestone 4 app does not need them.
"""
from __future__ import annotations

import ast
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


def imported_modules(text: str) -> list[str]:
    """The modules of each import of a Python text (also the imports inside a function), as "a.b" or "a.b.name"."""
    found = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            found += [f"{node.module}.{alias.name}" for alias in node.names]
    return found


def test_the_adapters_of_one_store_do_not_use_the_other_store():
    """The KG adapters (infrastructure/sparql/) take from the SQLite adapters only the log middleware (sql_log), and
    the SQLite adapters (infrastructure/sqlite/) import no KG module. So a KG store needs no SQLite repository, and
    the Milestone 4 path needs no RDF module. Only main.py (context_factory) knows both."""
    found = []
    for relative, text in python_files():
        for module in imported_modules(text):
            if relative.startswith("infrastructure/sparql/") and module.startswith("infrastructure.sqlite") \
                    and not module.startswith("infrastructure.sqlite.sql_log"):
                found.append((relative, module))
            if relative.startswith("infrastructure/sqlite/") and module.startswith(("infrastructure.sparql",
                                                                                     "infrastructure.rdf")):
                found.append((relative, module))
    assert found == []
    users = {relative for relative, text in python_files()
             if any(m.startswith("infrastructure.sparql") for m in imported_modules(text))}
    assert {u for u in users if not u.startswith(("infrastructure/", "tests/"))} == {"main.py"}


def sparql_texts(text: str) -> list[str]:
    """The string constants of a Python text that are not docstrings (the templates and their parts)."""
    tree = ast.parse(text)
    docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                  and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings]


def test_the_sparql_templates_of_the_adapters_follow_the_writing_rules():
    """The text checks of the writing rules (plan 5; models/semantic/sparql/README.md) on the templates of
    infrastructure/sparql/, as test_kg_queries.py checks them on the script files."""
    found = []
    for relative, text in python_files():
        if not relative.startswith("infrastructure/sparql/"):
            continue
        for value in sparql_texts(text):
            upper = value.upper()
            for broken, rule in (("REGEX(" in upper, "rule 7: CONTAINS(LCASE(...)), not REGEX"),
                                 ("STRBEFORE(" in upper, "rule 6: SUBSTR(STR(?t), 1, 10), not STRBEFORE"),
                                 ("^^xsd:string" in value or "XMLSchema#string>" in value, "rule 4: simple literals"),
                                 ("sameTerm(" in value, "rule 11: compare two IRIs with ="),
                                 (re.search(r"(?<![\w/#])kg:[\w-]+/", value) is not None, "rule 3: full IRIs")):
                if broken:
                    found.append((relative, rule, value.strip()[:60]))
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
