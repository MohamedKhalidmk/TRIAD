"""The times of the details of a new entry (onsetDate, abatementDate, performedDate, issuedDate) on each store.

The record form sends a date (YYYY-MM-DD). The ontology range of these four properties is xsd:dateTime (the data has
a time in each row), and a date is not an xsd:dateTime. So the use case keeps each of these values in the full ISO
8601 form (domain.rules.full_time): a date becomes midnight UTC, a time with no seconds gets ":00", a time with no
offset is UTC; a text in the full form does not change. Both stores then keep the same text, the knowledge graph
types it as xsd:dateTime, and the export of SQLite and the graph of the store conform to the SHACL shapes.

The known limit: a SQLite row with a date that an earlier version wrote gives an ill-typed literal in the export,
and the shapes do not report it (the last test records this).
"""
from __future__ import annotations

import shutil

import pytest

from domain.errors import Invalid
from domain.rules import parse_time
from tests.conftest import as_user, make_client

OKAFOR, VISIT = "Doctor:E1005", 3            # ENC-ELENA-2026-10-02
SNOMED, LOINC = "http://snomed.info/sct", "http://loinc.org"
FIELDS = ("onsetDate", "abatementDate", "performedDate", "issuedDate")

# (the value of the request, the stored text)
FORMS = [
    ("2026-09-01", "2026-09-01T00:00:00+00:00"),                         # the date of the record form
    ("2026-09-01T10:30-04:00", "2026-09-01T10:30:00-04:00"),             # no seconds
    ("2026-09-01T10:30:00", "2026-09-01T10:30:00+00:00"),                # no offset: UTC
    ("2026-09-01 10:30:00-04:00", "2026-09-01T10:30:00-04:00"),          # a space for the "T"
    ("2026-09-01T10:30:15.250-07:00", "2026-09-01T10:30:15.250-07:00"),  # the full form does not change
    ("2026-09-01T14:30:00Z", "2026-09-01T14:30:00Z"),
]
WRONG = ("2026-1-5", "05/10/2026", "2026-02-30", "yesterday")


@pytest.fixture
def twin(store, tmp_path):
    """A SQLite client on a copy of the data of the store, made before the test writes."""
    path = tmp_path / "twin.db"
    shutil.copy(store.db_path, path)
    client = make_client(path)
    client.db_path = path
    return client


def entries(value: str) -> list[dict]:
    def new(category, code, system, display, details):
        return {"newEntry": {"category": category, "code": code, "codeSystem": system, "display": display,
                             "details": details},
                "intent": "Decision", "verification": "Confirmed", "statement": f"{display}."}
    return [new("Diagnosis", "195967001", SNOMED, "Asthma", {"onsetDate": value, "abatementDate": value}),
            new("Procedure", "127783003", SNOMED, "Spirometry", {"performedDate": value}),
            new("LabReport", "24331-1", LOINC, "Lipid panel", {"issuedDate": value})]


def post(client, value: str):
    return client.post("/api/messages", headers=as_user(OKAFOR),
                       json={"patientId": 1, "visitId": VISIT, "text": "A note.", "assertions": entries(value)})


SQL_TIMES = ("SELECT OnsetDate FROM Diagnosis WHERE ClinicalEntryId = ? UNION ALL "
             "SELECT AbatementDate FROM Diagnosis WHERE ClinicalEntryId = ? UNION ALL "
             "SELECT PerformedDate FROM Procedure WHERE ClinicalEntryId = ? UNION ALL "
             "SELECT IssuedDate FROM LabReport WHERE ClinicalEntryId = ?")
KG_TIMES = """
SELECT ?e ?p ?t (DATATYPE(?t) AS ?type) FROM $abox WHERE {
  VALUES ?e { $entries }
  ?e ?p ?t .
  FILTER (?p IN (triad:onsetDate, triad:abatementDate, triad:performedDate, triad:issuedDate))
}"""
DATE_TIME = "http://www.w3.org/2001/XMLSchema#dateTime"


def sql_times(path, entry_ids) -> list[str]:
    """The stored text of the four times of the new entries (Diagnosis, Diagnosis, Procedure, LabReport)."""
    import sqlite3
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        diagnosis, procedure, report = entry_ids
        return [r[0] for r in conn.execute(SQL_TIMES, (diagnosis, diagnosis, procedure, report))]
    finally:
        conn.close()


def kg_times(store, entry_ids) -> list[tuple[str, str]]:
    """(the time as the store gives it, its datatype) of the four times of the new entries."""
    from infrastructure.sparql.terms import Term, iri
    rows = store.probe.client.select(KG_TIMES, {"entries": Term(" ".join(iri("clinical-entry", i)
                                                                         for i in entry_ids))})
    return [(r["t"], r["type"]) for r in rows]


@pytest.mark.parametrize("value, stored", FORMS)
def test_each_form_of_a_time_gives_the_same_text_on_each_store(store, twin, value, stored):
    found, expected = post(store.client(), value), post(twin, value)
    assert found.status_code == expected.status_code == 201, (found.text, expected.text)
    made = found.json()["assertions"]
    assert [a["entryId"] for a in made] == [a["entryId"] for a in expected.json()["assertions"]]
    for a, b in zip(made, expected.json()["assertions"]):
        for field in FIELDS:
            if field in b["details"]:
                assert parse_time(a["details"][field]) == parse_time(b["details"][field]) == parse_time(stored)
    entry_ids = [a["entryId"] for a in made]
    assert sql_times(twin.db_path, entry_ids) == [stored] * 4                     # the text of SQLite
    if store.is_kg:                       # each one is an xsd:dateTime of the same instant (D11: the text can differ)
        found_times = kg_times(store, entry_ids)
        assert len(found_times) == 4 and {datatype for _, datatype in found_times} == {DATE_TIME}
        assert {parse_time(t) for t, _ in found_times} == {parse_time(stored)}
    else:
        assert sql_times(store.db_path, entry_ids) == [stored] * 4


@pytest.mark.parametrize("value", WRONG)
def test_a_wrong_time_gives_422_on_each_store(store, twin, value):
    found, expected = post(store.client(), value), post(twin, value)
    assert found.status_code == expected.status_code == 422
    assert found.json() == expected.json() and found.json()["code"] == "validation"
    assert any(key.endswith("details.onsetDate") for key in found.json()["fields"]), found.json()


def graph_of(store):
    """The data graph of the store as an rdflib graph: the export of the SQLite file (the R2RML mapping), or the
    ABox of the knowledge graph."""
    pytest.importorskip("pyshacl")
    pytest.importorskip("morph_kgc")
    from rdflib import Graph
    if not store.is_kg:
        from infrastructure.rdf import kg_export
        return Graph().parse(data="\n".join(kg_export.materialize(store.db_path)), format="nt")
    rows = store.probe.client.select("SELECT ?s ?p ?o FROM $abox WHERE { ?s ?p ?o }", raw=True)
    return Graph().parse(data="\n".join(f"{r['s']} {r['p']} {r['o']} ." for r in rows), format="nt")


def test_the_graph_after_the_record_form_writes_conforms_to_the_shapes(store):
    """A date of the record form, written on each store: the export of SQLite and the graph of the knowledge graph
    conform to the SHACL shapes (the four properties have the range xsd:dateTime)."""
    from infrastructure.rdf import shacl
    response = post(store.client(), "2026-09-01")
    assert response.status_code == 201, response.text
    result = shacl.validate(graph_of(store))
    assert result.conforms, result.summary()


def test_a_short_form_of_an_earlier_version_is_a_known_limit(store):
    """The known limit (infrastructure/sparql/README.md, section 8). An earlier version of the use case kept the
    text of the record form, so a SQLite database that it changed can hold a date in a time column. The export then
    writes "2026-09-01"^^xsd:dateTime: the text is not an xsd:dateTime (the XSD form needs the time). rdflib reads it
    with Python's fromisoformat, so the shapes (pyshacl) do not report it, and check C8 of 05_constraint_checks
    looks only at the datatype IRI. The KG repository does not write such a value: the port refuses it (422)."""
    import sqlite3
    from infrastructure.rdf import kg_export, shacl
    if not store.is_kg:
        pytest.importorskip("pyshacl")
        pytest.importorskip("morph_kgc")
        assert post(store.client(), "2026-09-01").status_code == 201
        conn = sqlite3.connect(store.db_path)
        conn.execute("UPDATE Diagnosis SET OnsetDate = '2026-09-01' WHERE OnsetDate = '2026-09-01T00:00:00+00:00'")
        conn.commit()
        conn.close()
        text = "\n".join(kg_export.materialize(store.db_path))
        assert f'"2026-09-01"^^<{DATE_TIME}>' in text                 # the ill-typed literal of the old row
        assert shacl.validate(graph_of(store)).conforms                   # the shapes do not see it
        return
    from application.ports import NewEntryRow
    ctx = store.open_ctx()
    try:
        with pytest.raises(Invalid):
            with ctx.uow.write() as now:
                value = ctx.records.next_identifier("ClinicalEntry", ctx.identity.entry, "ENTRY-", 6)
                ctx.records.add_entry((ctx.identity.entry, value), NewEntryRow(
                    visit_id=VISIT, category="Diagnosis", code="195967001", code_system=SNOMED, display="Asthma",
                    text=None, recorded_at=now, details={"OnsetDate": "2026-09-01", "ClinicalStatus": "active"}))
    finally:
        ctx.close()
