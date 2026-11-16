"""The SPARQL client on a running Virtuoso 7.2 (the marker "virtuoso").

The tests run only with TRIAD_TEST_STORES=...,virtuoso (a test run must not change a Virtuoso that only happens to
run), and they are skipped when TRIAD_SPARQL_QUERY_URL does not answer. They change only the scratch graph, and
they delete their triples again. The full API tests on Virtuoso run with the store fixtures:
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
