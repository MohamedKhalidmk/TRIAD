"""The knowledge-graph script tools: the split rule of kg.sh sparql, the load check and kg.sh itself.

These tests need no store: a fake replaces the HTTP request. The tests with Virtuoso have the marker "virtuoso".
"""
from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest

from infrastructure import config
from infrastructure.rdf import counts, namespaces, sparql_script
from infrastructure.rdf.protocol import Answer, SparqlError, server_message

KG_SH = config.ROOT_DIR / "src" / "scripts" / "kg.sh"

SCRIPT = """# The header comment is not sent.
PREFIX triad: <https://github.com/MohamedKhalidmk/TRIAD/ontology/triad#>
prefix xsd: <http://www.w3.org/2001/XMLSchema#>

# Q1. The patients.
#     ?name = the name of the patient.
# Note: this line is not a marker.
# A patient line is not a marker either.
SELECT ?p ?name WHERE { ?p a triad:Patient ; triad:name ?name ; triad:x "a; b" }

# QA. An ASK.
ASK { ?s ?p ?o }

# Q14b. A query with a small letter in the ID.
SELECT * WHERE { ?s ?p ?o } LIMIT 1

# U1. UPDATE (DELETE/INSERT ... WHERE) and a second update.
WITH <urn:g> DELETE { ?s triad:phone ?o } INSERT { ?s triad:phone "1" } WHERE { OPTIONAL { ?s triad:phone ?o } } ;
INSERT DATA { GRAPH <urn:g> { <urn:a> <urn:b> "c" } }

# B.1 All graphs (a dot part, no period).
SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s ?p ?o } }

# B.2. All classes (a dot part and a period).
SELECT DISTINCT ?c WHERE { ?s a ?c }
"""


def test_the_split_rule():
    operations = sparql_script.split_operations(SCRIPT)
    assert [op.id for op in operations] == ["Q1", "QA", "Q14b", "U1", "B.1", "B.2"]
    assert operations[0].title == "The patients."
    assert operations[4].title == "All graphs (a dot part, no period)."
    assert operations[0].line == 5
    for op in operations:   # the PREFIX lines of the header go before each operation; the header comment does not
        assert op.text.startswith("PREFIX triad: <https://github.com/MohamedKhalidmk/TRIAD/ontology/triad#>\n"
                                  "prefix xsd: <http://www.w3.org/2001/XMLSchema#>\n# ")
        assert "header comment" not in op.text
    assert "# Note: this line is not a marker." in operations[0].text
    assert '"a; b"' in operations[0].text                    # ";" does not split an operation
    assert "INSERT DATA" in operations[3].text


@pytest.mark.parametrize("line, is_marker", [
    ("# Q1. The current record", True), ("# Q14b. Rank", True), ("# QA. Ask", True), ("# U12. Update", True),
    ("# B.1 All graphs", True), ("# B.2a. Classes", True), ("# C1. Check", True),
    ("# Q1 no period", False), ("# Note: text", False), ("# A patient", False), ("#     ?below = 1", False),
    ("# Q1.title", False), ("## Q1. Two signs", False), ("  # Q1. Indented", False), ("# q1. Small", False),
])
def test_the_marker_line(line, is_marker):
    assert bool(sparql_script.marker(line)) is is_marker


def test_a_file_with_no_marker_is_one_operation():
    [op] = sparql_script.split_operations("PREFIX a: <urn:a#>\nSELECT * { ?s ?p ?o }\n", "x.sparql")
    assert (op.id, op.title, op.line) == ("", "x.sparql", 1)
    assert op.text.startswith("PREFIX a:")


@pytest.mark.parametrize("text, form", [
    ("PREFIX a: <urn:a#>\n# c\nselect * {}", "SELECT"), ("BASE <urn:b>\nASK {}", "ASK"),
    ("# Q1. x\nCONSTRUCT {} WHERE {}", "CONSTRUCT"), ("PREFIX : <urn:x#>\nDESCRIBE <urn:a>", "DESCRIBE"),
    ("WITH <urn:g> DELETE {} WHERE {}", "WITH"), ("  insert data {}", "INSERT"), ("# only a comment\n", ""),
])
def test_the_form_of_an_operation(text, form):
    assert sparql_script.operation_form(text) == form


def test_the_iris_show_with_the_prefixes():
    prefixes = sparql_script.prefixes_of("PREFIX t: <https://github.com/MohamedKhalidmk/TRIAD/ontology/triad#>")
    assert sparql_script.show_iri(namespaces.TRIAD + "Patient", prefixes) == "t:Patient"
    assert sparql_script.show_iri(namespaces.KG + "patient/7", prefixes) == "kg:patient/7"   # a display prefix
    assert sparql_script.show_iri("urn:x", prefixes) == "<urn:x>"
    long = "<https://example.org/" + "a" * 80 + "/end>"
    shown = sparql_script.cell(long)
    assert len(shown) == sparql_script.CELL_WIDTH and shown.endswith("/end>")    # an IRI keeps its end


class FakeEndpoint:
    """Records each request, and answers like Virtuoso."""

    def __init__(self, fail_on: str = ""):
        self.calls = []
        self.fail_on = fail_on

    def __call__(self, url, *, query=None, update=None, accept, user=None, password=None, timeout=0):
        self.calls.append((url, "query" if query is not None else "update", user))
        text = query if query is not None else update
        if self.fail_on and self.fail_on in text:
            raise SparqlError(f"HTTP 400 from {url}: Virtuoso 37000 Error SP030: syntax error", 400)
        if update is not None:
            message = "Insert into <urn:g>, 1 (or less) triples -- done\nCommit -- done\n"
            body = {"head": {"vars": ["callret-0"]},
                    "results": {"bindings": [{"callret-0": {"type": "literal", "value": message}}]}}
        elif sparql_script.operation_form(text) == "ASK":
            body = {"head": {}, "boolean": True}
        else:
            body = {"head": {"vars": ["p", "name"]}, "results": {"bindings": [
                {"p": {"type": "uri", "value": namespaces.KG + "patient/1"},
                 "name": {"type": "literal", "value": "Elena Marsh"}},
                {"p": {"type": "uri", "value": namespaces.KG + "patient/2"}}]}}
        return Answer(200, "application/sparql-results+json", json.dumps(body).encode())


def run(tmp_path, monkeypatch, endpoint, **options):
    path = tmp_path / "t.sparql"
    path.write_text(SCRIPT, encoding="utf-8")
    monkeypatch.setattr(sparql_script, "send", endpoint)
    settings = config.Settings(db_path=tmp_path / "a.db", now="system", llm_mode="fake", llm_model="m",
                               frontend_dist=None)
    out = io.StringIO()
    code = sparql_script.run_file(path, settings, out=out, **options)
    return code, out.getvalue()


def test_the_runner_sends_queries_and_updates_to_their_endpoints(tmp_path, monkeypatch):
    endpoint = FakeEndpoint()
    code, text = run(tmp_path, monkeypatch, endpoint)
    assert code == 0 and "6 of 6 operations passed." in text
    assert [call[1] for call in endpoint.calls] == ["query", "query", "query", "update", "query", "query"]
    query_url = "http://127.0.0.1:8890/sparql"
    assert endpoint.calls[0] == (query_url, "query", None)                          # no login for a query
    assert endpoint.calls[3] == ("http://127.0.0.1:8890/sparql-auth", "update", "triad")   # digest login
    assert "== Q1. The patients. (SELECT, 2 rows," in text
    assert "kg:patient/1 | Elena Marsh" in text
    assert "== QA. An ASK. (ASK," in text and "\ntrue\n" in text
    assert "Insert into <urn:g>, 1 (or less) triples -- done\nCommit -- done" in text


def test_the_runner_stops_at_the_first_error(tmp_path, monkeypatch):
    code, text = run(tmp_path, monkeypatch, FakeEndpoint(fail_on="ASK"))
    assert code == 1
    assert "ERROR: HTTP 400" in text and "Stopped at line 11" in text and "Q14b" not in text
    code, text = run(tmp_path, monkeypatch, FakeEndpoint(fail_on="ASK"), keep_going=True)
    assert code == 1 and "5 of 6 operations passed." in text


def test_the_runner_runs_only_the_operations_that_you_name(tmp_path, monkeypatch):
    endpoint = FakeEndpoint()
    code, text = run(tmp_path, monkeypatch, endpoint, only=["q14B", "b.1"])
    assert code == 0 and len(endpoint.calls) == 2 and "2 of 2 operations passed." in text
    code, text = run(tmp_path, monkeypatch, FakeEndpoint(), only=["Q9"])
    assert code == 2 and "has no operation Q9. It has: Q1, QA, Q14b, U1, B.1, B.2." in text


def test_the_rows_that_do_not_show(tmp_path):
    lines = sparql_script.table(["n"], [[str(i)] for i in range(5)], max_rows=2)
    assert lines[-1] == "... 3 more rows. Use --max-rows 0 to show all rows."
    assert len(sparql_script.table(["n"], [[str(i)] for i in range(5)], max_rows=0)) == 7


def test_the_error_text_of_virtuoso_loses_the_query():
    text = "Virtuoso 37000 Error SP030: SPARQL compiler, line 3: syntax error\n\nSPARQL query:\nSELECT * WHERE { ?s ?p }"
    assert server_message(text) == "Virtuoso 37000 Error SP030: SPARQL compiler, line 3: syntax error"


def write_report(path: Path, total, per_predicate) -> Path:
    path.write_text(json.dumps({"total": total, "per_predicate": per_predicate, "per_class": {}}), encoding="utf-8")
    return path


def test_the_load_check_reads_the_report(tmp_path):
    rdf_type = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    report = write_report(tmp_path / "r.json", 5, {rdf_type: 3, f"<{namespaces.TRIAD}name>": 2})
    assert counts.read_report(report) == (5, {rdf_type: 3, namespaces.TRIAD + "name": 2})
    for total, per_predicate, problem in [(6, {rdf_type: 5}, "is not"), ("5", {rdf_type: 5}, "total"),
                                          (5, {}, "per_predicate"), (5, {rdf_type: 5.0}, "not a number")]:
        with pytest.raises(ValueError, match=problem):
            counts.read_report(write_report(tmp_path / "bad.json", total, per_predicate))
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="Cannot read"):
        counts.read_report(tmp_path / "broken.json")


def test_the_load_check_names_each_predicate_that_differs():
    assert counts.differences({"urn:a": 2, "urn:b": 1}, {"urn:a": 2, "urn:b": 1}) == []
    assert counts.differences({"urn:a": 2, "urn:b": 1}, {"urn:a": 5, "urn:c": 1}) == [
        "urn:a: kg_report.json 2, the graph 5 (+3)",
        "urn:b: kg_report.json 1, the graph 0 (-1)",
        "urn:c: kg_report.json 0, the graph 1 (+1)",
    ]


def test_the_load_check_uses_one_group_by_query(monkeypatch):
    sent = []

    def fake_send(url, *, query=None, accept, **_):
        sent.append(query)
        rows = [{"p": {"type": "uri", "value": "urn:a"}, "n": {"type": "typed-literal", "value": "7"}}]
        return Answer(200, "application/sparql-results+json", json.dumps({"results": {"bindings": rows}}).encode())

    monkeypatch.setattr(counts, "send", fake_send)
    assert counts.predicate_counts("http://kg.test/sparql") == {"urn:a": 7}
    assert sent == [f"SELECT ?p (COUNT(*) AS ?n) FROM <{namespaces.ABOX_GRAPH}> WHERE {{ ?s ?p ?o }} GROUP BY ?p"]


def test_the_graph_iris():
    assert namespaces.GRAPHS == tuple(f"https://github.com/MohamedKhalidmk/TRIAD/graph/{name}"
                                      for name in ("tbox", "abox", "scratch", "meta"))
    assert namespaces.ONTOLOGY_VERSION_IRI == "https://github.com/MohamedKhalidmk/TRIAD/ontology/triad/5.0.0"
    assert namespaces.TRIAD == namespaces.ONTOLOGY_IRI + "#"


def test_kg_sh_is_an_executable_bash_3_script():
    assert KG_SH.stat().st_mode & 0o111
    subprocess.run(["/bin/bash", "-n", str(KG_SH)], check=True)
    help_text = subprocess.run([str(KG_SH), "help"], check=True, capture_output=True, text=True).stdout
    for command in ("up", "init [--strict]", "load [--seed]", "status", "sparql FILE", "open", "down", "reset"):
        assert f"kg.sh {command}" in help_text
    assert KG_SH.read_text(encoding="utf-8").count("@sha256:") == 1          # the image is pinned (decision D3)
