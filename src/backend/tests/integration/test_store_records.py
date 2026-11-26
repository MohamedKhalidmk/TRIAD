"""The record port (RecordRepository) on each store: the same results as SQLite on the same data (plan 5.5, 5.6).

Each test runs a port method on the store (`store.open_ctx().records`) and on `store.reference()` (SQLite on the
same data) and compares the results: the same domain objects in the same order. Times are compared as instants
(D11: the stores write "+00:00" as "Z" and drop the trailing zeros of the seconds).

The planted data (tests/fixtures/plant.py) has the cases that the scenario data does not have: the nurse
recommendations (open, accepted, revised), a patient message with no issuer, and times with mixed offsets.
The writes and the guards are in test_store_records_writes.py.
"""
from __future__ import annotations

import dataclasses
import itertools
from typing import Any

import pytest

from domain.rules import parse_time

from application.paging import PageRequest

TIME_DETAILS = ("onsetDate", "abatementDate", "performedDate", "issuedDate")
VITAL_SIGNS = ("8867-4", "85354-9", "8480-6", "8462-4", "2708-6", "59408-5", "8310-5", "9279-1", "29463-7",
               "8302-2", "39156-5", "72514-3")
PLAN_ORDER = ("Diagnosis", "LabOrder", "LabReport", "Prescription", "Procedure")


# ----- the comparison helpers (also used by the other record tests) -----

def instant(value):
    return parse_time(value) if isinstance(value, str) and value else value


def same_view(view) -> dict:
    """A view as a dict with each time as an instant."""
    out = dataclasses.asdict(view)
    for key in ("asserted_at",):
        if key in out:
            out[key] = instant(out[key])
    if isinstance(out.get("details"), dict):
        out["details"] = {k: instant(v) if k in TIME_DETAILS else v for k, v in out["details"].items()}
    return out


def same(value: Any) -> Any:
    """The comparable form of a port result: a view, a list, a dict, a page or None."""
    if value is None or isinstance(value, (int, str, bool)):
        return value
    if isinstance(value, list):
        return [same(v) for v in value]
    if isinstance(value, dict):
        return {k: same(v) for k, v in value.items()}
    if hasattr(value, "items") and hasattr(value, "total"):            # a Page
        return {"items": same(value.items), "total": value.total, "limit": value.limit, "offset": value.offset}
    return same_view(value)


@pytest.fixture
def both(planted_store):
    """The record port of the store and of the SQLite reference, on the planted data."""
    ctx, ref = planted_store.open_ctx(), planted_store.reference()
    yield ctx.records, ref.records, planted_store
    ctx.close()
    ref.close()


def assertion_ids(planted_store) -> list[int]:
    return [r["id"] for r in planted_store.probe.rows("assertion")]


# ----- the chart: a page and the category counts -----

CHART_FILTERS = [
    dict(),
    dict(current_only=False),
    dict(visible_only=True),
    dict(category="Allergy"),
    dict(category="Allergy", current_only=False),
    dict(category="Diagnosis", visible_only=True),
    dict(category="CareTeam"),
    dict(category="Nothing"),
    dict(text="penicillin"),
    dict(text="PENICILLIN", current_only=False),
    dict(text="okafor"),
    dict(text="elena", current_only=False),        # the author name of the patient message
    dict(text="no such text"),
    dict(visit_id=2),
    dict(visit_id=3, current_only=False),
    dict(visit_id=3, visible_only=True),
    dict(visit_id=999),
    dict(date_from="2026-10-02", date_to="2026-10-02"),
    dict(date_from="2026-10-03", current_only=False),
    dict(date_to="2025-12-31", current_only=False),
    dict(date_from="2026-10-02", date_to="2026-10-02", visible_only=True, text="a"),
    dict(date_from="2030-01-01"),
    dict(category="Diagnosis", current_only=False, date_from="2026-10-02", text="recommend"),
]


def chart_case_id(case: dict) -> str:
    return ",".join(f"{k}={v}" for k, v in case.items()) or "none"


@pytest.mark.parametrize("case", CHART_FILTERS, ids=chart_case_id)
def test_the_chart_pages_are_the_same(both, case):
    kg, ref, _ = both
    full = ref.items_page(1, page=PageRequest(200, 0), **case)
    assert same(kg.items_page(1, page=PageRequest(200, 0), **case)) == same(full)
    for offset in sorted({0, 1, 2, 5, full.total - 1, full.total, full.total + 3} - {-1}):
        page = PageRequest(3, offset)
        assert same(kg.items_page(1, page=page, **case)) == same(ref.items_page(1, page=page, **case)), offset
    counts = {k: v for k, v in case.items() if k != "category"}
    found = kg.category_counts(1, **counts)
    expected = ref.category_counts(1, **counts)
    assert found == expected and list(found) == list(expected)


def test_each_filter_combination_of_the_chart(both):
    """All combinations of the flags with a category, a visit, a text and a date range."""
    kg, ref, _ = both
    flags = [dict(current_only=c, visible_only=v) for c, v in itertools.product((True, False), (True, False))]
    totals = []
    for flag, category, visit, text, dates in itertools.product(
            flags, (None, "Diagnosis", "Allergy"), (None, 3), (None, "a"),
            ((None, None), ("2026-10-02", "2026-10-02"), ("2025-01-01", None))):
        args = dict(flag, category=category, visit_id=visit, text=text, date_from=dates[0], date_to=dates[1])
        page = PageRequest(4, 1)
        expected = ref.items_page(1, page=page, **args)
        assert same(kg.items_page(1, page=page, **args)) == same(expected), args
        totals.append(expected.total)
        args.pop("category")
        assert kg.category_counts(1, **args) == ref.category_counts(1, **args), args
    assert sum(1 for t in totals if t > 1) > len(totals) // 3       # most cases have items on the page


INJECTIONS = ('" } ; DROP ALL ; #', '"', "\\", "\\u0022 } ; CLEAR ALL ; #", "'; DROP", "$q", "a\nb")


@pytest.mark.parametrize("text", INJECTIONS)
def test_a_search_text_cannot_change_the_chart_query(both, text):
    """Plan 5.2: the escape function. The search runs, finds no item, and no graph changes."""
    kg, ref, store = both
    before = store.probe.count("assertion")
    assert kg.items_page(1, text=text, page=PageRequest(5, 0)).total == 0
    assert kg.category_counts(1, text=text) == {}
    assert kg.allergies(1, words=(text,), visible_only=False, limit=12) == []
    assert store.probe.count("assertion") == before


def test_a_search_text_is_literal_on_the_knowledge_graph(both):
    """A known difference (README.md, section 8): SQLite LIKE reads "%" and "_" as wildcards; CONTAINS does not."""
    kg, ref, store = both
    every = ref.items_page(1, page=PageRequest(200, 0)).total
    assert ref.items_page(1, text="%", page=PageRequest(200, 0)).total == every
    assert kg.items_page(1, text="%", page=PageRequest(200, 0)).total == (every if not store.is_kg else 0)
    assert kg.items_page(1, text="peni", page=PageRequest(200, 0)).total == \
           ref.items_page(1, text="peni", page=PageRequest(200, 0)).total > 0


# ----- one assertion, a list, the chain, an entry -----

def test_one_assertion_and_a_list_of_assertions(both):
    kg, ref, store = both
    known = assertion_ids(store)
    assert len(known) > 15
    for assertion_id in [*known, 0, 9999]:
        assert same(kg.assertion(assertion_id)) == same(ref.assertion(assertion_id)), assertion_id
    wanted = [*reversed(known), 9999, known[0], known[3]]
    assert same(kg.assertions_by_id(wanted)) == same(ref.assertions_by_id(wanted))
    assert kg.assertions_by_id([]) == ref.assertions_by_id([]) == {}


def test_the_chain_the_head_and_the_chain_pages(both):
    kg, ref, store = both
    for assertion_id in [*assertion_ids(store), 9999]:
        chain = ref.chain(assertion_id)
        assert same(kg.chain(assertion_id)) == same(chain), assertion_id
        assert same(kg.chain_head(assertion_id)) == same(ref.chain_head(assertion_id)), assertion_id
        for offset, limit in ((0, 1), (1, 1), (0, 2), (1, 5), (len(chain), 2), (len(chain) + 1, 2)):
            page = PageRequest(limit, offset)
            assert same(kg.chain_page(assertion_id, page)) == same(ref.chain_page(assertion_id, page))
    assert [a.id for a in kg.chain(1)][-1] == 1 and len(kg.chain(1)) >= 3      # the penicillin chain


def test_an_entry_and_its_current_assertion(both):
    kg, ref, store = both
    for entry_id in [*[r["id"] for r in store.probe.rows("clinical-entry")], 9999]:
        assert kg.entry(entry_id) == ref.entry(entry_id), entry_id


def test_the_care_team_versions_of_each_visit(both):
    kg, ref, store = both
    visits = [r["id"] for r in store.probe.rows("visit")]
    found_one = False
    for visit_id in [*visits, 9999]:
        versions = ref.care_team_versions(visit_id)
        found_one = found_one or bool(versions)
        assert same(kg.care_team_versions(visit_id)) == same(versions), visit_id
    assert found_one


# ----- the lookups of the Care Assistant tools -----

@pytest.mark.parametrize("visible_only", (False, True))
@pytest.mark.parametrize("limit", (12, 2, 1))
def test_the_assistant_lookups(both, visible_only, limit):
    kg, ref, store = both
    args = dict(visible_only=visible_only, limit=limit)
    for words in ((), ("penicillin",), ("PENICILLIN", "allergy"), ("no-such-word",)):
        assert same(kg.allergies(1, words=words, **args)) == same(ref.allergies(1, words=words, **args)), words
        assert same(kg.lab_items(1, words=words, **args)) == same(ref.lab_items(1, words=words, **args)), words
    for flag in (True, False):
        assert same(kg.prescriptions(1, current_status=flag, **args)) == \
               same(ref.prescriptions(1, current_status=flag, **args))
        assert same(kg.diagnoses(1, active_only=flag, **args)) == same(ref.diagnoses(1, active_only=flag, **args))
    for visit in [r["id"] for r in store.probe.rows("visit")]:
        for categories in (PLAN_ORDER, ("Allergy",), ("CareTeam", "Allergy", "Procedure"), ("Nothing",), ()):
            assert same(kg.visit_items(1, visit, categories, **args)) == \
                   same(ref.visit_items(1, visit, categories, **args)), (visit, categories)
        assert kg.visit_items(1, visit, (), **args) == ref.visit_items(1, visit, (), **args) == []   # no category
        for role in (None, "Nurse", "Doctor", "MOA", "Admin"):
            assert same(kg.recommendations(1, visit, author_role=role, **args)) == \
                   same(ref.recommendations(1, visit, author_role=role, **args)), (visit, role)
    for codes in (VITAL_SIGNS, ("8867-4",), (), ("no-code",)):
        assert same(kg.latest_observations(1, codes, **args)) == same(ref.latest_observations(1, codes, **args))


def test_the_recommendations_keep_the_text_order_of_sqlite(both):
    """SQLite orders the recommendations by the text of AssertedAt; the planted times have mixed offsets."""
    kg, ref, store = both
    visit = next(r["id"] for r in store.probe.rows("visit") if r["identifierValue"] == "ENC-ELENA-2026-10-02")
    expected = ref.recommendations(1, visit, author_role=None, visible_only=False, limit=12)
    assert len(expected) >= 5
    assert [a.id for a in kg.recommendations(1, visit, author_role=None, visible_only=False, limit=12)] == \
           [a.id for a in expected]
    nurses = kg.recommendations(1, visit, author_role="Nurse", visible_only=False, limit=12)
    assert nurses and {a.author.role for a in nurses} == {"Nurse"}


# ----- the full data (slow): the largest chart, the longest chain, each query once (plan 5.5, 5.6) -----

def full_facts(db_path) -> dict:
    """The patient of the largest chart, the longest chain and some visits, from the SQLite data."""
    import sqlite3
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        largest = conn.execute("SELECT v.PatientId FROM Assertion a JOIN ClinicalEntry e ON e.Id = a.ClinicalEntryId "
                               "JOIN Visit v ON v.Id = e.VisitId GROUP BY v.PatientId ORDER BY COUNT(*) DESC "
                               "LIMIT 1").fetchone()[0]
        tail = conn.execute("""
            WITH RECURSIVE up (Id, Start, Depth) AS (
                SELECT Id, Id, 0 FROM Assertion WHERE SupersedesId IS NULL
                UNION ALL SELECT n.Id, u.Start, u.Depth + 1 FROM Assertion n JOIN up u ON n.SupersedesId = u.Id)
            SELECT Start FROM up ORDER BY Depth DESC LIMIT 1""").fetchone()[0]
        teams = [r[0] for r in conn.execute("SELECT DISTINCT e.VisitId FROM ClinicalEntry e "
                                            "WHERE e.Category = 'CareTeam' ORDER BY e.VisitId LIMIT 3")]
        visits = [r[0] for r in conn.execute("SELECT Id FROM Visit WHERE PatientId = ? ORDER BY StartDate DESC "
                                             "LIMIT 2", (largest,))]
        return {"largest": largest, "tail": tail, "team_visits": teams, "visits": visits}
    finally:
        conn.close()


def timed(call):
    import time
    start = time.perf_counter()
    result = call()
    return result, time.perf_counter() - start


def test_the_largest_chart_and_patient_b_on_the_full_data(full_store):
    """12,471 current items: the same total, counts and pages, and a chart page within the time limit."""
    facts = full_facts(full_store.db_path)
    kg, ref = full_store.open_ctx().records, full_store.reference().records
    largest = facts["largest"]
    assert ref.items_page(largest, page=PageRequest(1, 0)).total == 12471
    for flags in (dict(), dict(current_only=False), dict(visible_only=True), dict(text="blood"), dict(text="an"),
                  dict(text="park", visible_only=True, date_from="2015-01-01")):
        expected = ref.items_page(largest, page=PageRequest(50, 0), **flags)
        kg.items_page(largest, page=PageRequest(50, 0), **flags)                      # warm the store
        found, seconds = timed(lambda: (kg.items_page(largest, page=PageRequest(50, 0), **flags),
                                        kg.category_counts(largest, **flags)))
        assert same(found[0]) == same(expected) and found[1] == ref.category_counts(largest, **flags), flags
        assert seconds < full_store.time_limit(0.3), f"a chart page took {seconds:.3f} s ({flags})"
        for offset in (expected.total // 2, max(0, expected.total - 7)):
            page = PageRequest(50, offset)
            assert same(kg.items_page(largest, page=page, **flags)) == \
                   same(ref.items_page(largest, page=page, **flags))
    for category in ("Observation", "Procedure", "CareTeam"):
        page = PageRequest(20, 30)
        assert same(kg.items_page(largest, category=category, page=page)) == \
               same(ref.items_page(largest, category=category, page=page))
    for flags in (dict(), dict(current_only=False), dict(visible_only=True)):   # patient B: all pages
        items, offset, total = [], 0, 1
        while offset < total:
            page = kg.items_page(81, page=PageRequest(200, offset), **flags)
            items, offset, total = items + page.items, offset + 200, page.total
        assert same(items) == same(ref.items_page(81, page=PageRequest(1000, 0), **flags).items)


def test_the_longest_chain_on_the_full_data(full_store):
    facts = full_facts(full_store.db_path)
    kg, ref = full_store.open_ctx().records, full_store.reference().records
    tail = facts["tail"]
    expected = ref.chain(tail)
    assert len(expected) == 222
    kg.chain(tail)
    found, seconds = timed(lambda: kg.chain(tail))
    assert same(found) == same(expected)
    assert seconds < full_store.time_limit(0.3), f"the chain took {seconds:.3f} s"
    for start in (tail, expected[0].id, expected[100].id):
        for page in (PageRequest(50, 0), PageRequest(50, 200), PageRequest(10, 222)):
            assert same(kg.chain_page(start, page)) == same(ref.chain_page(start, page))
        assert same(kg.chain_head(start)) == same(ref.chain_head(start))
    assert kg.entry(expected[0].entry_id) == ref.entry(expected[0].entry_id)


def test_each_lookup_and_the_care_teams_on_the_full_data(full_store):
    """Each assistant read once on the full graph, within the time limit of a chart page."""
    facts = full_facts(full_store.db_path)
    kg, ref = full_store.open_ctx().records, full_store.reference().records
    slowest = (0.0, "")
    calls = [("allergies", dict(words=())), ("allergies", dict(words=("penicillin",))),
             ("prescriptions", dict(current_status=True)), ("prescriptions", dict(current_status=False)),
             ("diagnoses", dict(active_only=True)), ("diagnoses", dict(active_only=False)),
             ("lab_items", dict(words=())), ("lab_items", dict(words=("lipid",)))]
    for patient in (facts["largest"], 81, 1):
        for visible in (False, True):
            for name, args in calls:
                found, seconds = timed(lambda: getattr(kg, name)(patient, visible_only=visible, limit=12, **args))
                slowest = max(slowest, (seconds, name))
                assert same(found) == same(getattr(ref, name)(patient, visible_only=visible, limit=12, **args))
            found, seconds = timed(lambda: kg.latest_observations(patient, VITAL_SIGNS, visible_only=visible,
                                                                  limit=12))
            slowest = max(slowest, (seconds, "latest_observations"))
            assert same(found) == same(ref.latest_observations(patient, VITAL_SIGNS, visible_only=visible, limit=12))
    for visit in facts["visits"]:
        for visible in (False, True):
            for name, call in (
                    ("visit_items", lambda r: r.visit_items(facts["largest"], visit, PLAN_ORDER,
                                                            visible_only=visible, limit=12)),
                    ("recommendations", lambda r: r.recommendations(facts["largest"], visit, author_role=None,
                                                                    visible_only=visible, limit=12))):
                found, seconds = timed(lambda: call(kg))
                slowest = max(slowest, (seconds, name))
                assert same(found) == same(call(ref))
    assert slowest[0] < full_store.time_limit(0.3), f"the slowest lookup ({slowest[1]}) took {slowest[0]:.3f} s"
    for visit in facts["team_visits"]:
        assert same(kg.care_team_versions(visit)) == same(ref.care_team_versions(visit))
