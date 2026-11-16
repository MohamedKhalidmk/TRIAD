"""The shared SPARQL fragments (infrastructure/sparql/fragments.py) give the rows of the shared SQL fragments
(infrastructure/sqlite/records_repository.py), on the planted data: the nurse recommendations, the patient message
with no issuer, and the times with mixed offsets and milliseconds (tests/fixtures/plant.py).

The SQL side is the reference. Times are compared as instants (D11).
"""
from __future__ import annotations

import pytest

from domain.rules import parse_time

from infrastructure.sparql import fragments, paging
from infrastructure.sparql.terms import id_of, iri
from infrastructure.sqlite.connection import connect
from infrastructure.sqlite.records_repository import (ASSERTION_FROM, ASSERTION_SELECT, CHART_ORDER, CURRENT,
                                                      DETAIL_KEYS, PATIENT_VISIBLE)
from application.paging import PageRequest

pytestmark = pytest.mark.stores("oxigraph", "virtuoso")

VIEW = f"SELECT {fragments.ASSERTION_SELECT} {fragments.DETAIL_SELECT} FROM $abox WHERE {{" \
       f"{fragments.assertion_view()}{fragments.detail_optionals()}\n"


def sql_rows(db, where: str = "", order: str = "a.Id") -> list:
    conn = connect(db)
    try:
        return conn.execute(f"{ASSERTION_SELECT} {where} ORDER BY {order}").fetchall()
    finally:
        conn.close()


def kg_rows(store, extra: str = "") -> dict[int, dict]:
    import main
    rows = main.kg_client(store.settings).select(VIEW + extra + "\n}")
    return {id_of(r["a"]): r for r in rows}


def same_time(a, b) -> bool:
    return (a is None and b is None) or (a is not None and b is not None and parse_time(a) == parse_time(b))


def test_the_assertion_view_gives_the_columns_of_the_sql_view(planted_store):
    expected = sql_rows(planted_store.db_path)
    found = kg_rows(planted_store)
    assert sorted(found) == [r["Id"] for r in expected] and len(expected) > 15
    for r in expected:
        k = found[r["Id"]]
        assert (id_of(k["e"]), id_of(k["m"]), id_of(k["v"]), id_of(k["p"])) == \
               (r["EntryId"], r["MessageId"], r["VisitId"], r["PatientId"])
        assert fragments.category_of(k["type"]) == r["Category"]
        assert (k["patientName"], k["code"], k["codeSystem"], k["display"], k["seq"]) == \
               (r["PatientName"], r["Code"], r["CodeSystem"], r["Display"], r["Seq"])
        assert (k["intent"], k["source"], k["verification"], k["statement"], k["channel"], k["origin"]) == \
               (r["Intent"], r["Source"], r["Verification"], r["Statement"], r["Channel"], r["Origin"])
        assert same_time(k["at"], r["AssertedAt"]), (k["at"], r["AssertedAt"])
        assert id_of(k["s"]) == r["StaffId"] and k["staffName"] == r["StaffName"]
        assert (fragments.category_of(k["staffRole"]) if k["staffRole"] else None) == r["StaffRole"]
        assert (id_of(k["supersedes"]), id_of(k["supersededBy"])) == (r["SupersedesId"], r["SupersededById"])
        details = fragments.details_of(r["Category"], k)
        for column, key in DETAIL_KEYS[r["Category"]]:
            if key == "members":
                continue
            if key in ("onsetDate", "abatementDate", "performedDate", "issuedDate"):
                assert same_time(details[key], r[column]), key
            else:
                assert details[key] == r[column], (r["Category"], key)
    assert any(r["StaffId"] is None for r in expected)        # the patient report of the planted data


def test_current_and_patient_visible_give_the_rows_of_the_sql_predicates(planted_store):
    db = planted_store.db_path
    current = {r["Id"] for r in sql_rows(db, f"WHERE {CURRENT}")}
    visible = {r["Id"] for r in sql_rows(db, f"WHERE {PATIENT_VISIBLE}")}
    assert set(kg_rows(planted_store, fragments.CURRENT)) == current
    assert set(kg_rows(planted_store, fragments.PATIENT_VISIBLE)) == visible
    assert visible and visible < current < {r["Id"] for r in sql_rows(db)}


def test_the_chart_order_and_the_page_slices_are_the_sql_order(planted_store):
    import main
    db = planted_store.db_path
    expected = [r["Id"] for r in sql_rows(db, "WHERE v.PatientId = 1", CHART_ORDER)]
    client = main.kg_client(planted_store.settings)
    where = fragments.assertion_view("$patient")
    order = [fragments.CHART_RANK, "DESC(?at)", f"DESC({fragments.id_order('?a', 'assertion')})"]
    found = []
    for offset in range(0, len(expected) + 4, 4):
        page = paging.fetch_page(client, "?a", where, {"patient": iri("patient", 1)}, order, PageRequest(4, offset),
                                 paging.each_row(lambda r: id_of(r["a"])))
        assert page.total == len(expected)
        found += page.items
    if planted_store.name == "virtuoso":   # D11: Virtuoso orders dateTimes by the text
        assert sorted(found) == sorted(expected)
    else:
        assert found == expected


def test_the_local_date_and_the_text_search(planted_store):
    import main
    client = main.kg_client(planted_store.settings)
    rows = client.select(f"SELECT ?a ?day FROM $abox WHERE {{{fragments.assertion_view()}\n"
                         f"  FILTER ({fragments.contains('?statement', 'q')})\n"
                         f"  BIND ({fragments.local_date('?at')} AS ?day)\n}}", {"q": "penicillin"})
    conn = connect(planted_store.db_path)
    try:
        expected = {r[0]: r[1] for r in conn.execute(
            f"SELECT a.Id, substr(a.AssertedAt, 1, 10) {ASSERTION_FROM} WHERE instr(lower(a.Statement), 'penicillin')")}
    finally:
        conn.close()
    assert {id_of(r["a"]): r["day"] for r in rows} == expected and expected
