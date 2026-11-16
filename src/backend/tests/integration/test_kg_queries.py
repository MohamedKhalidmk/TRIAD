"""SQL = SPARQL: the scripts of models/semantic/sparql/ on the knowledge graph (plan 5, sections 4.4 and 4.5).

1. Each query Q1 to Q14b of 03_select_queries.sparql gives the rows of the query with the same number in
   models/relational/sql/dml/03_select_queries.sql, on the graph of the same database:
   - "scenario": the scenario database (01 + 02). Its graph is the seed graph (1,125 triples).
   - "planted": the scenario database with 04_update_delete.sql and the rows of tests/fixtures/plant.py (nurse
     recommendations for Q4, a patient message for the "Patient" branches, mixed time offsets).
   - "full" (marker slow): a new onboarding (main.py ensure-db), 1,298,482 triples.
   - "virtuoso" (marker virtuoso): the graph in Virtuoso (see below).
   "The same rows" (plan 4.5): the SPARQL variables are the SQL column names with a small first letter; Q2, Q4 and
   Q14a compare the order too (a total ORDER BY), the other queries compare the rows as multisets; a time compares
   as its instant; a NULL is an unbound variable; the numbers compare as numbers. No other mapping.
   QA (ASK), QC (CONSTRUCT) and QD (DESCRIBE) have their expected result from SQL.
2. 01 makes the graphs; 02 then 04 run on a copy, and the counts change as the files say; 04 gives the rows and the
   triple counts of 04_update_delete.sql.
3. Each check of 05 gives no row on valid data, and its row when its planted example is in the scratch graph.
4. 06 runs, and its counts equal the SQL counts.

The Oxigraph stores come from tests/fixtures/kg.py: the R2RML mapping runs in this process, and each database gets
one store in the session.

How the Virtuoso tests get their data (marker "virtuoso"; skipped when TRIAD_SPARQL_QUERY_URL does not answer):
- The ABox graph of Virtuoso must hold the graph of one SQLite database. TRIAD_KG_TEST_DB names that database.
  Without it, the tests use a new onboarding (the fixture full_db): "kg.sh load" on a new clone loads exactly that
  graph. A first check compares the triples of each predicate in Virtuoso with the SQL counts of the database.
  If they differ, the tests stop: with TRIAD_KG_TEST_DB they fail, without it they are skipped (the store holds
  another graph, for example the dev database with the writes of the app).
- The tests that write (01, 02 + 04, the planted examples of 05, and the copies of the scenario and planted
  graphs) use only the scratch graph, as the user triad (TRIAD_SPARQL_UPDATE_URL, digest login). They empty it
  before and after. The ABox and TBox graphs do not change.
- A full run (from the root folder of the repository):
      ./src/scripts/kg.sh up && ./src/scripts/kg.sh init && ./src/scripts/kg.sh load
      .venv/bin/python -m pytest -q -m virtuoso src/backend/tests/integration/test_kg_queries.py
  (kg.sh load uses TRIAD_DB_PATH; give the same file in TRIAD_KG_TEST_DB if it is not a new onboarding.)
"""
from __future__ import annotations

import io
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest

ox = pytest.importorskip("pyoxigraph")
pytest.importorskip("morph_kgc")

from infrastructure import config  # noqa: E402
from infrastructure.rdf import counts, kg_export, namespaces, oxigraph_store  # noqa: E402
from infrastructure.rdf.namespaces import ABOX_GRAPH, KG, SCRATCH_GRAPH, TBOX_GRAPH, TRIAD  # noqa: E402
from infrastructure.rdf.protocol import SparqlError, send  # noqa: E402
from tests.fixtures import kg as K  # noqa: E402

QUERY_IDS = list(K.sql_queries())
ORDERED = {"Q2", "Q4", "Q14a"}
CHECK_IDS = list(K.sparql_operations("05_constraint_checks.sparql"))
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
PROV = "http://www.w3.org/ns/prov#"
PREFIXES = ("PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n"
            f"PREFIX triad: <{TRIAD}>\n")
LOAD_URL = "https://raw.githubusercontent.com/MohamedKhalidmk/TRIAD/main/src/backend/models/semantic/triad.owl"
# A small public RDF/XML file for the LOAD test of 01 on Virtuoso (triad.owl is on main only after the merge).
TEST_LOAD_URL = os.environ.get("TRIAD_KG_TEST_LOAD_URL",
                               "https://raw.githubusercontent.com/owlcs/pizza-ontology/master/pizza.owl")

# The rows of each SQL query on each database (the SPARQL query must give the same rows). They show that the
# comparison is not empty, and they are the expected results of the README.
EXPECTED_ROWS = {
    "scenario": {"Q1": 8, "Q2": 3, "Q3": 1, "Q4": 0, "Q5": 3, "Q6": 6, "Q7": 1, "Q8": 13, "Q9a": 1, "Q9b": 1,
                 "Q10": 1, "Q11": 4, "Q12": 7, "Q13": 2, "Q14a": 0, "Q14b": 1},
    "planted": {"Q1": 13, "Q2": 4, "Q3": 1, "Q4": 3, "Q5": 3, "Q6": 15, "Q7": 1, "Q8": 13, "Q9a": 6, "Q9b": 4,
                "Q10": 1, "Q11": 4, "Q12": 9, "Q13": 2, "Q14a": 0, "Q14b": 1},
    "full": {"Q1": 8, "Q2": 3, "Q3": 1, "Q4": 0, "Q5": 3, "Q6": 6, "Q7": 1, "Q8": 17, "Q9a": 10, "Q9b": 5,
             "Q10": 1, "Q11": 4, "Q12": 7, "Q13": 2, "Q14a": 25, "Q14b": 1},
}


def iri(path: str) -> str:
    """The full IRI of an individual, for example iri("patient/1")."""
    return f"<{KG}{path}>"


# ---------------------------------------------------------------------------------------------
# Fixtures

@dataclass
class Data:
    name: str                 # scenario, planted, full or virtuoso
    kg: object                # K.OxigraphKg or K.VirtuosoKg
    db: Path                  # the SQLite database of the graph
    expected: Optional[str]   # the key of EXPECTED_ROWS, or None if the database is not a known one


@pytest.fixture(scope="session")
def planted_kg_db(scenario_db, tmp_path_factory) -> Path:
    """The planted database of conftest.planted_db, but for the whole session (one Oxigraph store)."""
    from tests.fixtures.plant import plant
    path = tmp_path_factory.mktemp("kg-planted") / "planted.db"
    shutil.copy(scenario_db, path)
    plant(path)
    return path


def virtuoso_settings():
    return config.Settings.from_env(db_path=Path("unused.db"), now="system", llm_mode="fake", frontend_dist=None)


@pytest.fixture(scope="session")
def virtuoso_kg() -> K.VirtuosoKg:
    """The Virtuoso client. Skip if the query endpoint does not answer."""
    settings = virtuoso_settings()
    try:
        send(settings.sparql_query_url, query="ASK {}", accept="application/sparql-results+json", timeout=3)
    except SparqlError as error:
        pytest.skip(f"Virtuoso does not answer ({error}). Start it: kg.sh up, kg.sh init, kg.sh load.")
    return K.VirtuosoKg(settings)


@pytest.fixture(scope="session")
def virtuoso(virtuoso_kg, request) -> Data:
    """Virtuoso, with the database whose graph its ABox graph holds (TRIAD_KG_TEST_DB, else a new onboarding)."""
    named = os.environ.get("TRIAD_KG_TEST_DB", "").strip()
    db = Path(named).expanduser().resolve() if named else request.getfixturevalue("full_db")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        expected = counts.expected_counts(conn)["per_predicate"]
    finally:
        conn.close()
    rows = virtuoso_kg.run(f"SELECT ?p (COUNT(*) AS ?n) FROM <{ABOX_GRAPH}> WHERE {{ ?s ?p ?o }} GROUP BY ?p")
    found = {p[1:-1]: n for p, n in rows.rows}
    problems = [f"<{p}>: SQL {expected.get(p, 0)}, Virtuoso {found.get(p, 0)}"
                for p in sorted(set(expected) | set(found)) if expected.get(p, 0) != found.get(p, 0)]
    if problems:
        if named:
            pytest.fail(f"The ABox graph of Virtuoso does not hold the graph of TRIAD_KG_TEST_DB={db} "
                        f"({len(problems)} predicates differ, for example {problems[0]}). "
                        f"Load it: TRIAD_DB_PATH={db} ./src/scripts/kg.sh load")
        pytest.skip(f"The ABox graph of Virtuoso does not hold the graph of a new onboarding ({len(problems)} "
                    f"predicates differ, for example {problems[0]}). Load one (kg.sh load makes the database if it "
                    "does not exist): TRIAD_DB_PATH=/tmp/triad-kg-test.db ./src/scripts/kg.sh load. "
                    "Or set TRIAD_KG_TEST_DB to the database of the loaded graph.")
    return Data("virtuoso", virtuoso_kg, db, None if named else "full")


DATASETS = ["scenario", "planted", pytest.param("full", marks=pytest.mark.slow),
            pytest.param("virtuoso", marks=pytest.mark.virtuoso)]


def oxigraph_data(name: str, request) -> Data:
    db = request.getfixturevalue({"scenario": "scenario_db", "planted": "planted_kg_db", "full": "full_db"}[name])
    folder = None
    if name == "full":   # on disk: the copies are hard links, and the process needs less memory
        folder = request.getfixturevalue("tmp_path_factory").mktemp("kg-full-store") / "store"
    return Data(name, K.oxigraph_for(db, folder), db, name)


@pytest.fixture(scope="session", params=DATASETS)
def data(request) -> Data:
    if request.param == "virtuoso":
        return request.getfixturevalue("virtuoso")
    return oxigraph_data(request.param, request)


@pytest.fixture
def scenario_kg(scenario_db) -> K.OxigraphKg:
    """The Oxigraph store of the scenario database, with an empty scratch graph before and after the test."""
    kg = K.oxigraph_for(scenario_db)
    kg.clear(SCRATCH_GRAPH)
    yield kg
    kg.clear(SCRATCH_GRAPH)


@pytest.fixture
def scratch(virtuoso) -> K.VirtuosoKg:
    """The Virtuoso client, with an empty scratch graph before and after the test."""
    virtuoso.kg.clear(SCRATCH_GRAPH)
    yield virtuoso.kg
    virtuoso.kg.clear(SCRATCH_GRAPH)


# ---------------------------------------------------------------------------------------------
# Helpers

def sparql(name: str, op_id: str, graph: str = ABOX_GRAPH) -> str:
    """The text of one operation of a .sparql file; with graph, the ABox graph IRI changes to that graph."""
    return K.with_graph(K.sparql_operations(name)[op_id].text, graph)


def compare(data: Data, qid: str, graph: str = ABOX_GRAPH, db: Optional[Path] = None) -> list[str]:
    sql = K.sql_rows(db or data.db, K.sql_queries()[qid])
    found = data.kg.run(sparql("03_select_queries.sparql", qid, graph))
    return K.differences(sql, found, qid in ORDERED)


def check_rows(kg, check: str, graph: str = ABOX_GRAPH) -> list[tuple]:
    return kg.run(sparql("05_constraint_checks.sparql", check, graph)).rows


def predicate_counts(kg, graph: str) -> dict[str, int]:
    rows = kg.run(f"SELECT ?p (COUNT(*) AS ?n) FROM <{graph}> WHERE {{ ?s ?p ?o }} GROUP BY ?p")
    return {p[1:-1]: n for p, n in rows.rows}


def sql_predicate_counts(db: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return counts.expected_counts(conn)["per_predicate"]
    finally:
        conn.close()


def nt_lines(db: Optional[Path] = None) -> list[str]:
    """The N-Triples lines of the graph of a database (None: the committed seed graph)."""
    if db is None:
        out = io.BytesIO()
        ox.serialize(ox.parse(kg_export.SEED_PATH.open("rb"), "application/rdf+xml"), out, "application/n-triples")
        return [line for line in out.getvalue().decode("utf-8").splitlines() if line.strip()]
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "copy.db"
        kg_export.copy_database(db, copy)
        return kg_export.materialize(copy)


def load_lines(kg, graph: str, lines: list[str], chunk: int = 400) -> None:
    """Insert N-Triples lines into a graph with INSERT DATA, some hundred triples for each request."""
    for start in range(0, len(lines), chunk):
        kg.insert(graph, "\n".join(lines[start:start + chunk]))


def sql_one(db: Path, sql: str, *params):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------------------------------
# The files

def test_each_sql_query_has_a_sparql_query_with_the_same_number():
    assert QUERY_IDS == ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8", "Q9a", "Q9b", "Q10", "Q11", "Q12", "Q13",
                         "Q14a", "Q14b"]
    assert list(K.sparql_operations("03_select_queries.sparql")) == QUERY_IDS + ["QA", "QC", "QD"]
    assert list(K.sparql_operations("01_create_graphs.sparql")) == ["G1", "G2", "G3", "G4"]
    assert list(K.sparql_operations("02_insert_data.sparql")) == ["I1", "I2"]
    assert list(K.sparql_operations("04_update_delete.sparql")) == [f"U{n}" for n in range(1, 9)]
    assert CHECK_IDS == [f"C{n}" for n in range(1, 25)]
    assert list(K.sparql_operations("06_debug.sparql")) == ["B.1", "B.1a", "B.2", "B.2a", "B.3", "B.3a", "B.4",
                                                           "B.5"]


@pytest.mark.parametrize("name", sorted(p.name for p in K.SPARQL_DIR.glob("*.sparql")))
def test_the_files_follow_the_sparql_writing_rules(name):
    """The writing rules of plan 5 (and the ones that this work found), as text checks of each operation."""
    from infrastructure.rdf import sparql_script
    for op_id, op in K.sparql_operations(name).items():
        lines = op.text.splitlines()
        code = "\n".join(line.split(" #", 1)[0] for line in lines if not line.lstrip().startswith("#"))
        comments = [line for line in lines if line.lstrip().startswith("#")]
        form = sparql_script.operation_form(op.text)
        assert len(op.title.split()) >= 4, f"{name} {op_id}: the marker line says what the operation does"
        assert "^^xsd:string" not in code and "XMLSchema#string" not in code, f"{name} {op_id}: rule 4"
        assert "STRBEFORE" not in code.upper() and "REGEX" not in code.upper(), f"{name} {op_id}: rules 6 and 7"
        assert "sameTerm" not in code, f"{name} {op_id}: sameTerm of two equal IRIs is false on Virtuoso"
        assert " kg:" not in code and "PREFIX kg:" not in code, f"{name} {op_id}: rule 3 (full IRIs)"
        if form in ("SELECT", "ASK", "CONSTRUCT", "DESCRIBE") and name != "06_debug.sparql" and op_id != "G4":
            assert f"FROM <{ABOX_GRAPH}>" in code, f"{name} {op_id}: rule 1 (a dataset clause)"
            assert "GRAPH" not in code.replace("graph/", ""), f"{name} {op_id}: rule 1 (no GRAPH <iri> {{ }})"
        if name == "03_select_queries.sparql" and op_id in QUERY_IDS:
            assert f"SQL: {op_id}" in "\n".join(comments), f"{op_id}: the comment names the SQL query"
        if name == "05_constraint_checks.sparql":
            assert f"FROM <{SCRATCH_GRAPH}>" in code, f"{op_id}: the check reads the scratch graph too"
    if name == "04_update_delete.sparql":
        ops = K.sparql_operations(name)
        for op_id in ("U1", "U2"):
            assert ops[op_id].title.startswith("UPDATE (SPARQL 1.1 has no UPDATE keyword: DELETE/INSERT ... WHERE)")


def test_the_sql_markers_split_the_sql_file():
    queries = K.sql_queries()
    assert all(text.rstrip().endswith(";") for text in queries.values())
    assert all(text.count(";") == 1 for text in queries.values())   # one statement for each query


# ---------------------------------------------------------------------------------------------
# 03: SQL = SPARQL

@pytest.mark.parametrize("qid", QUERY_IDS)
def test_the_sparql_query_gives_the_rows_of_the_sql_query(data, qid):
    sql = K.sql_rows(data.db, K.sql_queries()[qid])
    if data.expected:
        assert len(sql.rows) == EXPECTED_ROWS[data.expected][qid], "the test data changed"
    found = data.kg.run(sparql("03_select_queries.sparql", qid))
    assert K.differences(sql, found, qid in ORDERED) == []


QA_SQL = """
SELECT EXISTS (
    SELECT 1 FROM Patient p
    JOIN Visit v ON v.PatientId = p.Id
    JOIN ClinicalEntry e ON e.VisitId = v.Id
    JOIN Allergy al ON al.ClinicalEntryId = e.Id
    JOIN Assertion a ON a.ClinicalEntryId = e.Id
    WHERE p.Name = 'Elena Marsh' AND p.DateOfBirth = '1971-05-14' AND lower(al.Substance) LIKE '%penicillin%'
      AND a.Verification NOT IN ('Refuted', 'EnteredInError')
      AND NOT EXISTS (SELECT 1 FROM Assertion n WHERE n.SupersedesId = a.Id))
"""

PENICILLIN_SQL = """
SELECT a.Id, a.AssertedAt, a.Statement, a.SupersedesId, m.StaffId, s.Name,
       NOT EXISTS (SELECT 1 FROM Assertion n WHERE n.SupersedesId = a.Id) AS IsCurrent
FROM Patient p
JOIN Visit v ON v.PatientId = p.Id
JOIN ClinicalEntry e ON e.VisitId = v.Id
JOIN Allergy al ON al.ClinicalEntryId = e.Id
JOIN Assertion a ON a.ClinicalEntryId = e.Id
JOIN Message m ON m.Id = a.MessageId
LEFT JOIN Staff s ON s.Id = m.StaffId
WHERE p.Name = 'Elena Marsh' AND p.DateOfBirth = '1971-05-14' AND lower(al.Substance) LIKE '%penicillin%'
"""


def test_qa_asks_if_patient_a_is_allergic_to_penicillin_now(data):
    (expected,) = sql_one(data.db, QA_SQL)[0]
    assert data.kg.run(sparql("03_select_queries.sparql", "QA")) is bool(expected)
    if data.expected:   # the slide answer: no (Refuted); the planted patient message makes it "possibly"
        assert bool(expected) is (data.name == "planted")


def test_qc_constructs_the_prov_o_view_of_the_slide_chain(data):
    expected = set()
    for row_id, at, statement, supersedes, staff, name, _ in sql_one(data.db, PENICILLIN_SQL):
        a = f"<{KG}assertion/{row_id}>"
        expected |= {(a, f"<{RDF_TYPE}>", f"<{PROV}Entity>"), (a, f"<{PROV}generatedAtTime>", K.instant(at)),
                     (a, f"<{PROV}value>", statement)}
        if supersedes is not None:
            expected.add((a, f"<{PROV}wasRevisionOf>", f"<{KG}assertion/{supersedes}>"))
        if staff is not None:
            person = f"<{KG}staff/{staff}>"
            expected |= {(a, f"<{PROV}wasAttributedTo>", person), (person, f"<{RDF_TYPE}>", f"<{PROV}Person>"),
                         (person, "<http://www.w3.org/2000/01/rdf-schema#label>", name)}
    assert len(expected) > 10
    assert data.kg.run(sparql("03_select_queries.sparql", "QC")) == expected


def test_qd_describes_the_current_penicillin_assertion(data):
    (current,) = [row[0] for row in sql_one(data.db, PENICILLIN_SQL) if row[6]]
    subject = f"<{KG}assertion/{current}>"
    stored = {(subject, p, o) for p, o in data.kg.run(
        f"SELECT ?p ?o FROM <{ABOX_GRAPH}> WHERE {{ {subject} ?p ?o }}").rows}
    described = data.kg.run(sparql("03_select_queries.sparql", "QD"))
    assert len(stored) >= 9
    assert {t for t in described if t[0] == subject} == stored
    assert all(subject in (t[0], t[2]) for t in described)   # Virtuoso also gives the links to the assertion


# ---------------------------------------------------------------------------------------------
# 01: the graphs

def test_01_makes_the_graphs_clears_the_tbox_and_counts_the_triples(scenario_db):
    kg = K.copy_of(K.oxigraph_for(scenario_db))
    for graph in (SCRATCH_GRAPH, namespaces.META_GRAPH):
        kg.store.remove_graph(ox.NamedNode(graph))
    ops = K.sparql_operations("01_create_graphs.sparql")
    abox = kg.count(ABOX_GRAPH)
    kg.update(ops["G1"].text)
    assert {g.value for g in kg.store.named_graphs()} == set(namespaces.GRAPHS)
    kg.update(ops["G1"].text)   # SILENT: a second run is not an error
    kg.update(ops["G2"].text)
    assert (kg.count(TBOX_GRAPH), kg.count(ABOX_GRAPH)) == (0, abox)
    # G3 reads triad.owl from GitHub (the network, and the main branch after the merge). The Virtuoso test runs
    # the LOAD form; here the store API loads the same file into the TBox graph.
    assert f"LOAD <{LOAD_URL}>\nINTO GRAPH <{TBOX_GRAPH}>" in ops["G3"].text
    owl = ox.parse(oxigraph_store.OWL_PATH.open("rb"), "application/rdf+xml")
    kg.store.bulk_extend(ox.Quad(t.subject, t.predicate, t.object, ox.NamedNode(TBOX_GRAPH)) for t in owl)
    tbox = kg.count(TBOX_GRAPH)
    rows = kg.run(ops["G4"].text).rows
    assert rows == sorted([(f"<{TBOX_GRAPH}>", tbox), (f"<{ABOX_GRAPH}>", abox), (f"<{SCRATCH_GRAPH}>", 0),
                           (f"<{namespaces.META_GRAPH}>", 0)])
    assert tbox > 1900 and abox == 1125


# ---------------------------------------------------------------------------------------------
# 02 and 04

def count_of(kg, graph: str, pattern: str) -> int:
    rows = kg.run(f"{PREFIXES}SELECT (COUNT(*) AS ?n) FROM <{graph}> WHERE {{ {pattern} }}").rows
    return rows[0][0]


def run_02_then_04(kg, graph: str, checks_after_02: bool = True) -> None:
    """Run 02 and 04 on a copy in `graph`, and check the count and the result of each operation.
    checks_after_02: also run the checks of 05 between 02 and 04 (about 18 s on the full graph in Oxigraph)."""
    insert = K.sparql_operations("02_insert_data.sparql")
    update = K.sparql_operations("04_update_delete.sparql")
    noah = f'?s triad:name "Noah Fielding" ; triad:dateOfBirth "1990-03-14"^^xsd:date . ?s ?p ?o'
    elena = 'triad:name "Elena Marsh" ; triad:dateOfBirth "1971-05-14"^^xsd:date'
    q1 = len(kg.run(sparql("03_select_queries.sparql", "Q1", graph)).rows)
    assert count_of(kg, graph, noah) == 0

    start = kg.count(graph)
    kg.update(K.with_graph(insert["I1"].text, graph))
    assert kg.count(graph) == start + K.data_triples(insert["I1"].text) == start + 8
    assert count_of(kg, graph, noah) == 8
    kg.update(K.with_graph(insert["I2"].text, graph))
    assert kg.count(graph) == start + 8 + K.data_triples(insert["I2"].text) == start + 8 + 46
    q1_rows = kg.run(sparql("03_select_queries.sparql", "Q1", graph)).rows
    assert len(q1_rows) == q1 + 1 and ("Allergy", "Latex allergy", "Unconfirmed", "Report", "Sofia Alvarez",
                                       "Patient", "2026-11-02", "Patient report: hives after contact with latex "
                                       "gloves.") in q1_rows
    for check in CHECK_IDS if checks_after_02 else []:   # "all constraints are respected when triples are entered"
        assert check_rows(kg, check, graph) == [], f"{check} after 02"

    after_02 = kg.count(graph)
    kg.update(K.with_graph(update["U1"].text, graph))
    phones = kg.run(f"{PREFIXES}SELECT ?phone FROM <{graph}> WHERE {{ ?p {elena} ; triad:phoneNumber ?phone }}")
    assert phones.rows == [("+1-508-555-0199",)] and kg.count(graph) == after_02
    kg.update(K.with_graph(update["U2"].text, graph))
    phones = kg.run(f"{PREFIXES}SELECT ?phone FROM <{graph}> WHERE {{ ?s triad:identifierValue \"E1001\" ; "
                    "triad:phoneNumber ?phone }")
    assert phones.rows == [("+1-508-555-2999",)]
    old_room = count_of(kg, graph, '?l triad:identifierValue "STORE-OLD" ; ?p ?o')
    assert old_room >= 4
    kg.update(K.with_graph(update["U3"].text, graph))
    assert count_of(kg, graph, '?l triad:identifierValue "STORE-OLD" ; ?p ?o') == 0
    assert kg.count(graph) == after_02 - old_room
    kg.update(K.with_graph(update["U4"].text, graph))
    assert count_of(kg, graph, noah) == 0, "the person of 02 is gone"
    assert kg.count(graph) == after_02 - old_room - 8
    before_u5 = kg.count(graph)
    kg.update(K.with_graph(update["U5"].text, graph))
    assert count_of(kg, graph, '?m triad:code "00000000" ; ?p ?o') == 0
    assert kg.count(graph) == before_u5
    kg.update(K.with_graph(update["U6"].text, graph))
    assert kg.count(graph) == before_u5 + 17
    chain = kg.run(sparql("04_update_delete.sparql", "U7", graph))
    assert [row[chain.names.index("author")] for row in chain.rows] == ["Lucas Brennan", "Patient"]
    assert chain.rows[1][chain.names.index("supersedes")] == chain.rows[0][0]
    kg.update(K.with_graph(update["U6"].text, graph))   # a second run adds nothing
    assert kg.count(graph) == before_u5 + 17
    for check in CHECK_IDS:
        assert check_rows(kg, check, graph) == [], f"{check} after 04"


@pytest.mark.parametrize("name", ["scenario", pytest.param("full", marks=pytest.mark.slow)])
def test_02_then_04_on_a_copy(name, request, tmp_path):
    """02 then 04 on a copy of the store. (The planted database has the changes of 04_update_delete.sql already.)"""
    original = oxigraph_data(name, request).kg
    kg = K.copy_of(original, tmp_path / "copy" if original.folder else None)
    run_02_then_04(kg, ABOX_GRAPH, checks_after_02=(name == "scenario"))
    kg.update(sparql("04_update_delete.sparql", "U8"))
    assert kg.count(SCRATCH_GRAPH) == 0


def run_04_like_sql_04(kg, graph: str, db: Path) -> None:
    for op_id, op in K.sparql_operations("04_update_delete.sparql").items():
        if op_id != "U8":
            run = kg.run if op_id == "U7" else kg.update
            run(K.with_graph(op.text, graph))
    assert predicate_counts(kg, graph) == sql_predicate_counts(db)
    for qid in QUERY_IDS:
        sql = K.sql_rows(db, K.sql_queries()[qid])
        found = kg.run(sparql("03_select_queries.sparql", qid, graph))
        assert K.differences(sql, found, qid in ORDERED) == [], qid


@pytest.fixture
def scenario_after_sql_04(scenario_db, tmp_path) -> Path:
    path = tmp_path / "after-04.db"
    shutil.copy(scenario_db, path)
    conn = sqlite3.connect(path)
    conn.executescript(K.SQL_UPDATE_FILE.read_text(encoding="utf-8"))
    conn.commit()
    conn.close()
    return path


def test_04_does_what_the_sql_04_does(scenario_db, scenario_after_sql_04):
    """04_update_delete.sparql on the seed graph = the graph of 04_update_delete.sql on the scenario database:
    the same triples of each predicate, and the same rows of Q1 to Q14b."""
    kg = K.copy_of(K.oxigraph_for(scenario_db))
    run_04_like_sql_04(kg, ABOX_GRAPH, scenario_after_sql_04)


# ---------------------------------------------------------------------------------------------
# 05: the constraint checks

N = iri
PLANTED = {
    # check: (the bad triples, a value that a row of the check must hold)
    "C1": (f'{N("patient/990001")} a triad:Patient ; triad:dateOfBirth "1980-01-01"^^xsd:date ; '
           'triad:patientSex "male" .', N("patient/990001")),
    "C2": (f'{N("visit/990001")} a triad:Visit ; triad:identifierSystem "https://triad.example/fhir/sid/encounter" ; '
           'triad:identifierValue "ENC-NO-PATIENT" ; triad:visitClass "AMB" ; '
           'triad:startDate "2026-10-30T08:00:00-04:00"^^xsd:dateTime .', N("visit/990001")),
    "C3": (f'{N("works-in/990001")} a triad:WorksIn ; triad:ofStaff {N("staff/2")} ; '
           f'triad:atDepartment {N("department/99999")} ; triad:roleCode "nurse" .', N("works-in/990001")),
    "C4": (f'{N("staff/2")} a triad:Doctor .', N("staff/2")),
    "C5": (f'{N("staff/990001")} a triad:Nurse ; triad:designation "RN" .', N("staff/990001")),
    "C6": (f'{N("visit/1")} a triad:Location .', N("visit/1")),
    "C7": (f'{N("staff/1")} triad:designation "Chief" .', "Chief"),
    "C8": (f'{N("patient/990002")} a triad:Patient ; triad:name "Test Patient Date" ; '
           'triad:dateOfBirth "not a date" ; triad:patientSex "female" .', N("patient/990002")),
    "C9": (f'{N("patient/1")} triad:hasVisit {N("visit/990003")} . '
           f'{N("visit/990003")} a triad:Visit ; triad:identifierSystem "https://triad.example/fhir" ; '
           'triad:identifierValue "Encounter/bad-dates" ; triad:visitClass "AMB" ; '
           'triad:startDate "2026-10-30T10:00:00-04:00"^^xsd:dateTime ; '
           'triad:endDate "2026-10-30T09:00:00-04:00"^^xsd:dateTime .', N("visit/990003")),
    "C10": (f'{N("message/990001")} a triad:Message ; '
            'triad:identifierSystem "https://triad.example/fhir/sid/message" ; triad:identifierValue "MSG-NO-ISSUER" ; '
            'triad:channel "Phone" ; triad:origin "Staff" ; '
            'triad:sentAt "2026-10-30T08:00:00-04:00"^^xsd:dateTime ; triad:text "No issuer." .',
            N("message/990001")),
    "C11": (f'{N("patient/1")} triad:identifier {N("patient-identifier/990001")} . '
            f'{N("patient-identifier/990001")} a triad:PatientIdentifier ; '
            'triad:identifierSystem "https://triad.example/fhir/sid/mrn" ; triad:identifierValue "MRN-000001" .',
            "MRN-000001"),
    "C12": (f'{N("patient/990003")} a triad:Patient ; triad:name "Elena Marsh" ; '
            'triad:dateOfBirth "1971-05-14"^^xsd:date ; triad:patientSex "female" .', "Elena Marsh"),
    "C13": (f'{N("visit-location/990001")} a triad:VisitLocation ; triad:ofVisit {N("visit/1")} ; '
            f'triad:atLocation {N("location/14")} ; triad:startDate "2019-06-12T10:10:00-04:00"^^xsd:dateTime .',
            N("visit/1")),
    "C14": (f'{N("assertion/1")} triad:supersedes {N("assertion/3")} .', N("assertion/1")),
    "C15": (f'{N("patient/1")} triad:dateOfBirth "1971-05-15"^^xsd:date .', N("patient/1")),
    "C16": (f'{N("assertion/10")} triad:supersedes {N("assertion/1")} .', N("assertion/10")),
    "C17": (f'{N("message/5")} triad:contains {N("assertion/990003")} . '
            f'{N("assertion/990003")} a triad:Assertion ; triad:seq 99 ; triad:about {N("clinical-entry/1")} ; '
            'triad:assertedAt "2026-10-30T08:00:00-04:00"^^xsd:dateTime ; triad:intent "Report" ; '
            'triad:source "Human" ; triad:verification "Unconfirmed" ; triad:statement "Rash again." .',
            N("clinical-entry/1")),
    "C18": (f'{N("message/5")} triad:contains {N("assertion/990004")} . '
            f'{N("assertion/990004")} a triad:Assertion ; triad:seq 98 ; triad:about {N("clinical-entry/1")} ; '
            f'triad:supersedes {N("assertion/3")} ; triad:assertedAt "2020-01-01T08:00:00-05:00"^^xsd:dateTime ; '
            'triad:intent "Report" ; triad:source "Human" ; triad:verification "Unconfirmed" ; '
            'triad:statement "Old claim." .', N("assertion/990004")),
    "C19": (f'{N("patient/990004")} a triad:Patient ; triad:name "Test Patient One" ; '
            'triad:dateOfBirth "1980-01-01"^^xsd:date ; triad:patientSex "male" ; '
            f'triad:hasVisit {N("visit/990004")} . '
            f'{N("clinical-entry/990004")} a triad:ClinicalEntry , triad:Observation ; '
            f'triad:during {N("visit/990004")} . '
            f'{N("assertion/990005")} triad:about {N("clinical-entry/990004")} ; '
            f'triad:supersedes {N("assertion/3")} .',
            N("assertion/990005")),
    "C20": (f'{N("patient/990005")} triad:hasVisit {N("visit/990005")} . '
            f'{N("clinical-entry/990005")} triad:during {N("visit/990005")} . '
            f'{N("message/5")} triad:contains {N("assertion/990006")} . '
            f'{N("assertion/990006")} triad:about {N("clinical-entry/990005")} .', N("message/5")),
    "C21": (f'{N("clinical-entry/8")} triad:member {N("care-team-member/990001")} . '
            f'{N("care-team-member/990001")} a triad:CareTeamMember ; '
            'triad:memberSystem "https://triad.example/fhir/sid/employee" ; triad:memberValue "E0000" ; '
            'triad:memberRole "Nurse" .', N("care-team-member/990001")),
    "C22": (f'{N("citation/990001")} a triad:Citation ; triad:byTurn {N("chat-turn/1")} ; '
            f'triad:citedAssertion {N("assertion/1")} ; triad:rank 1 .', N("citation/990001")),
    "C23": (f'{N("chat-session/990001")} triad:subjectName "Someone Else" ; '
            f'triad:subjectDateOfBirth "1990-01-01"^^xsd:date ; triad:includes {N("chat-turn/990001")} . '
            f'{N("chat-turn/990001")} triad:speaker "Assistant" . '
            f'{N("citation/990002")} triad:byTurn {N("chat-turn/990001")} ; '
            f'triad:citedAssertion {N("assertion/3")} .',
            N("citation/990002")),
    "C24": (f'{N("audit-event/990001")} a triad:AuditEvent ; triad:inTurn {N("chat-turn/2")} ; '
            'triad:subjectName "Someone Else" ; triad:subjectDateOfBirth "1990-01-01"^^xsd:date .',
            N("audit-event/990001")),
}


def test_each_check_has_a_planted_example():
    assert sorted(PLANTED, key=lambda c: int(c[1:])) == CHECK_IDS


@pytest.mark.parametrize("check", CHECK_IDS)
def test_the_check_gives_no_row_on_valid_data(data, check):
    assert check_rows(data.kg, check) == []


@pytest.mark.parametrize("check", CHECK_IDS)
def test_the_check_finds_its_planted_example(scenario_kg, check):
    triples, value = PLANTED[check]
    assert check_rows(scenario_kg, check) == []
    scenario_kg.insert(SCRATCH_GRAPH, triples, PREFIXES)
    rows = check_rows(scenario_kg, check)
    assert rows and any(value in row for row in rows), rows


# ---------------------------------------------------------------------------------------------
# 06: the debug queries

def test_06_runs_and_its_counts_equal_the_sql_counts(data):
    ops = K.sparql_operations("06_debug.sparql")
    results = {op_id: data.kg.run(op.text) for op_id, op in ops.items()}
    conn = sqlite3.connect(f"file:{data.db}?mode=ro", uri=True)
    try:
        expected = counts.expected_counts(conn)
    finally:
        conn.close()
    assert {(f"<{TBOX_GRAPH}>",), (f"<{ABOX_GRAPH}>",)} <= set(results["B.1"].rows)
    graphs = dict(results["B.1a"].rows)
    assert graphs[f"<{ABOX_GRAPH}>"] == expected["total"] and graphs[f"<{TBOX_GRAPH}>"] == len(results["B.2"].rows)
    assert graphs[f"<{SCRATCH_GRAPH}>"] == 0
    assert len(results["B.2a"].rows) == 100
    assert {c[1:-1] for (c,) in results["B.3"].rows} == set(expected["per_class"])
    assert len([c for c, _ in results["B.3a"].rows if c.startswith(f"<{TRIAD}")]) == 28
    assert {(f"<{ABOX_GRAPH}>", f"<{c}>") for c in expected["per_class"]} <= set(results["B.4"].rows)
    assert {c[1:-1]: n for c, n in results["B.5"].rows} == expected["per_class"]


# ---------------------------------------------------------------------------------------------
# Virtuoso: the tests that write (scratch graph only)

@pytest.mark.virtuoso
@pytest.mark.parametrize("copy", ["scenario", "planted"])
def test_virtuoso_gives_the_rows_of_sql_on_a_copy_in_the_scratch_graph(scratch, copy, request):
    """The scenario and the planted graphs in the scratch graph of Virtuoso: Q1 to Q14b, QA (Q4 and the
    "Patient" branches need the planted rows; the full graph has none)."""
    db = request.getfixturevalue({"scenario": "scenario_db", "planted": "planted_kg_db"}[copy])
    load_lines(scratch, SCRATCH_GRAPH, nt_lines(db))
    assert scratch.count(SCRATCH_GRAPH) == sum(sql_predicate_counts(db).values())
    problems = {}
    for qid in QUERY_IDS:
        sql = K.sql_rows(db, K.sql_queries()[qid])
        assert len(sql.rows) == EXPECTED_ROWS[copy][qid]
        found = scratch.run(sparql("03_select_queries.sparql", qid, SCRATCH_GRAPH))
        if K.differences(sql, found, qid in ORDERED):
            problems[qid] = K.differences(sql, found, qid in ORDERED)
    (asked,) = sql_one(db, QA_SQL)[0]
    assert scratch.run(sparql("03_select_queries.sparql", "QA", SCRATCH_GRAPH)) is bool(asked)
    for check in CHECK_IDS:
        if check_rows(scratch, check, SCRATCH_GRAPH):
            problems[check] = "a row on valid data"
    assert problems == {}


@pytest.mark.virtuoso
def test_virtuoso_runs_02_then_04_on_a_copy_of_the_seed_graph(scratch):
    load_lines(scratch, SCRATCH_GRAPH, nt_lines())
    assert scratch.count(SCRATCH_GRAPH) == 1125
    run_02_then_04(scratch, SCRATCH_GRAPH)
    scratch.update(sparql("04_update_delete.sparql", "U8"))
    assert scratch.count(SCRATCH_GRAPH) == 0


@pytest.mark.virtuoso
def test_virtuoso_04_does_what_the_sql_04_does(scratch, scenario_after_sql_04):
    load_lines(scratch, SCRATCH_GRAPH, nt_lines())
    run_04_like_sql_04(scratch, SCRATCH_GRAPH, scenario_after_sql_04)


@pytest.mark.virtuoso
@pytest.mark.parametrize("check", CHECK_IDS)
def test_virtuoso_check_finds_its_planted_example_in_the_full_graph(scratch, virtuoso, check):
    triples, value = PLANTED[check]
    scratch.insert(SCRATCH_GRAPH, triples, PREFIXES)
    rows = check_rows(scratch, check)
    assert rows and any(value in row for row in rows), rows


@pytest.mark.virtuoso
def test_virtuoso_runs_01_with_the_scratch_graph_for_the_tbox(scratch):
    """01 on Virtuoso. G1 runs as it is. G2 and G3 run with the scratch graph in place of the TBox graph and with a
    small public RDF/XML file in place of triad.owl (TRIAD_KG_TEST_LOAD_URL), so the loaded TBox does not change.
    G3 itself (the GitHub main URL of triad.owl) works only after the merge of Milestone 5."""
    ops = K.sparql_operations("01_create_graphs.sparql")
    scratch.update(ops["G1"].text)
    scratch.update(K.with_graph(ops["G2"].text, SCRATCH_GRAPH, TBOX_GRAPH))
    load = K.with_graph(ops["G3"].text, SCRATCH_GRAPH, TBOX_GRAPH).replace(f"<{LOAD_URL}>", f"<{TEST_LOAD_URL}>")
    assert f"<{TEST_LOAD_URL}>" in load
    try:
        scratch.update(load)
    except SparqlError as error:
        pytest.skip(f"Virtuoso cannot read {TEST_LOAD_URL} ({error}). Is the network on?")
    rows = dict(scratch.run(ops["G4"].text).rows)
    assert rows[f"<{SCRATCH_GRAPH}>"] > 100
    assert rows[f"<{TBOX_GRAPH}>"] > 1900 and rows[f"<{ABOX_GRAPH}>"] > 0
