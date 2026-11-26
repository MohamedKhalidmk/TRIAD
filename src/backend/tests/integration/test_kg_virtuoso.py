"""The SPARQL client on a running Virtuoso 7.2 (the marker "virtuoso").

The tests run only with TRIAD_TEST_STORES=...,virtuoso (a test run must not change a Virtuoso that only happens to
run), and they are skipped when TRIAD_SPARQL_QUERY_URL does not answer. The client tests change only the scratch
graph, and they delete their triples again. The journal test loads the seed graph (as the fixture `store`). The full
API tests on Virtuoso run with the store fixtures:
    TRIAD_TEST_STORES=virtuoso .venv/bin/python -m pytest -q -m virtuoso
(those REPLACE the TRIAD graphs of the container; see infrastructure/sparql/README.md, section 6).
"""
from __future__ import annotations

import pytest

from infrastructure import config
from infrastructure.sparql import terms

from tests.fixtures.stores import selected_stores  # noqa: E402

pytestmark = pytest.mark.virtuoso
if "virtuoso" not in selected_stores():
    pytest.skip("Add virtuoso to TRIAD_TEST_STORES to run the tests on Virtuoso.", allow_module_level=True)
pytest.importorskip("SPARQLWrapper")


@pytest.fixture(scope="module")
def virtuoso():
    from infrastructure.sparql.client import HttpSparqlClient
    from tests.fixtures.stores import virtuoso_answers
    settings = config.Settings.from_env(store="virtuoso")
    if not virtuoso_answers(settings):
        pytest.skip("Virtuoso does not answer on TRIAD_SPARQL_QUERY_URL (start it with: ./src/scripts/kg.sh up).")
    return HttpSparqlClient(settings.sparql_query_url, settings.sparql_update_url, settings.sparql_user,
                            settings.sparql_password)


def test_a_round_trip_on_the_scratch_graph_with_the_digest_login(virtuoso):
    subject = terms.iri("patient", 999999)
    text = '" } ; DROP ALL ; # \\u0022 é'
    virtuoso.update("WITH $scratch DELETE { $s ?p ?o } WHERE { $s ?p ?o }", {"s": subject})
    virtuoso.update("INSERT DATA { GRAPH $scratch { $s triad:name $t ; triad:assertedAt $at ; triad:seq 3 } }",
                    {"s": subject, "t": text, "at": terms.date_time("2026-10-30T13:00:00+00:00")})
    rows = virtuoso.select("SELECT ?name ?at ?seq FROM $scratch WHERE { $s triad:name ?name ; triad:assertedAt ?at ; "
                           "triad:seq ?seq }", {"s": subject})
    assert rows == [{"name": text, "at": "2026-10-30T13:00:00+00:00", "seq": 3}]          # D11: Z -> +00:00
    assert virtuoso.ask("ASK FROM $scratch WHERE { ?s triad:name $t }", {"t": text})
    virtuoso.update("WITH $scratch DELETE { $s ?p ?o } WHERE { $s ?p ?o }", {"s": subject})
    assert not virtuoso.ask("ASK FROM $scratch WHERE { $s ?p ?o }", {"s": subject})


def graph_dump(client) -> tuple[list, list]:
    """All triples of the ABox and the meta graph, in the SPARQL form of the store."""
    def triples(graph: str) -> list[str]:
        rows = client.select(f"SELECT ?s ?p ?o FROM {graph} WHERE {{ ?s ?p ?o }}", raw=True)
        return sorted(f"{r['s']} {r['p']} {r['o']}" for r in rows)
    return triples("$abox"), triples("$meta")


def test_the_store_fixture_undoes_the_writes_of_a_test(virtuoso, scenario_db, kg_cache, tmp_path):
    """The journal of tests/fixtures/stores.py: after the writes of each form, the graphs are the loaded graphs
    again, with no new load (the next test uses them as they are)."""
    import shutil

    from infrastructure.clock import DemoClock
    from infrastructure.sparql import ids
    from infrastructure.sparql.client import HttpSparqlClient
    from infrastructure.sparql.unit_of_work import KgSession, SparqlUnitOfWork
    from tests.fixtures.stores import DEMO_NOW, VIRTUOSO_SESSIONS, virtuoso_handle

    copy = tmp_path / "copy.db"
    shutil.copy(scenario_db, copy)
    handle = virtuoso_handle(copy, scenario_db, seed=True, export_cache=kg_cache / "virtuoso-export")
    session_state = None
    try:
        before = graph_dump(virtuoso)
        api = handle.client()
        response = api.post("/api/messages", headers={"X-Triad-User": "Doctor:E1005"}, json={
            "patientId": 1, "visitId": 3, "text": "Heart rate 72.", "assertions": [{"newEntry": {
                "category": "Observation", "code": "8867-4", "codeSystem": "http://loinc.org", "display": "Heart rate",
                "details": {"value": "72", "unit": "/min"}}, "intent": "Report", "verification": "Confirmed",
                "statement": "Heart rate 72."}]})
        assert response.status_code == 201, response.text
        s = handle.settings      # a new client object: the journal sees all HttpSparqlClient objects of the store
        session = KgSession(HttpSparqlClient(s.sparql_query_url, s.sparql_update_url, s.sparql_user,
                                             s.sparql_password))
        uow = SparqlUnitOfWork(session, DemoClock(DEMO_NOW))
        with uow.write():
            buf = session.write_buffer()
            buf.replace(terms.iri("patient", 1), "phoneNumber", '+1 "555" \\ é\nline')       # a replace
            buf.delete_subject("location", 19)                                              # a delete
            buf.create("medication", {"code": "T-1", "codeSystem": "urn:test", "name": "Test"})   # an append
        virtuoso.update("INSERT DATA { GRAPH $meta { $c triad:issued 0 } }", {"c": ids.counter_iri("medication")})
        assert graph_dump(virtuoso) != before
        session_state = VIRTUOSO_SESSIONS[virtuoso.key]
    finally:
        handle.close()
    assert graph_dump(virtuoso) == before
    assert session_state.loaded is not None                  # undone, so the next test needs no load


def test_a_replace_with_no_old_value_inserts_the_value(virtuoso):
    """The U1 form: the old value in OPTIONAL, so a subject with no value gets the new one (plan 4.4)."""
    subject = terms.iri("patient", 999998)
    virtuoso.update("INSERT DATA { GRAPH $scratch { $s a triad:Patient } }", {"s": subject})
    for value in ("+1-555-0100", "+1-555-0101"):
        virtuoso.update("WITH $scratch DELETE { $s triad:phoneNumber ?old } INSERT { $s triad:phoneNumber $v } "
                        "WHERE { $s a ?type . OPTIONAL { $s triad:phoneNumber ?old } }", {"s": subject, "v": value})
    rows = virtuoso.select("SELECT ?v FROM $scratch WHERE { $s triad:phoneNumber ?v }", {"s": subject})
    assert rows == [{"v": "+1-555-0101"}]
    virtuoso.update("WITH $scratch DELETE { $s ?p ?o } WHERE { $s ?p ?o }", {"s": subject})
