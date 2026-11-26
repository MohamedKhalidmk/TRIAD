"""The date filter of the chart (doc/api.md section 3.4): `from` and `to`, date-only, both days included.

Each test runs on each store (the `store` fixture: SQLite and the knowledge graph) with the scenario data.
The filter compares the local date of assertedAt (the first 10 characters, as written) on both stores.
"""
from __future__ import annotations

import pytest

from domain.rules import parse_time
from tests.conftest import as_user, make_client

OKAFOR, ELENA = "Doctor:E1005", 1


@pytest.fixture
def api(store):
    return store.client()


def chart(api, **params):
    return api.get(f"/api/patients/{ELENA}/chart", headers=as_user(OKAFOR), params={"history": "true", **params})


def ids(response) -> set[int]:
    assert response.status_code == 200, response.text
    return {item["id"] for item in response.json()["items"]}


def test_no_date_gives_the_full_chart(api):
    assert ids(chart(api)) == set(range(1, 11))


def test_both_days_are_included(api):
    assert ids(chart(api, **{"from": "2025-08-20", "to": "2025-08-22"})) == {4, 5, 6, 7, 8}
    assert ids(chart(api, **{"from": "2025-08-22", "to": "2025-08-22"})) == {8}
    assert ids(chart(api, **{"from": "2025-08-21"})) == {8, 3, 9, 10}
    assert ids(chart(api, **{"to": "2024-03-05"})) == {1, 2}


def test_a_range_with_no_item_gives_an_empty_page(api):
    body = chart(api, **{"from": "2030-01-01"}).json()
    assert body["items"] == [] and body["total"] == 0 and body["counts"] == {}


def test_the_total_and_the_counts_use_the_dates(api):
    body = chart(api, **{"from": "2026-10-02", "to": "2026-10-02"}).json()
    assert body["total"] == 3
    assert body["counts"] == {"Allergy": 1, "Procedure": 1, "CareTeam": 1}
    paged = chart(api, **{"from": "2026-10-02", "to": "2026-10-02", "limit": 1, "offset": 1}).json()
    assert paged["total"] == 3 and len(paged["items"]) == 1


def test_the_dates_work_with_the_search_the_category_and_the_current_rule(api):
    assert ids(chart(api, q="penicillin", **{"from": "2026-01-01"})) == {3, 9}
    assert ids(chart(api, category="Allergy", **{"to": "2025-01-01"})) == {1, 2}
    current = api.get(f"/api/patients/{ELENA}/chart", headers=as_user(OKAFOR), params={"to": "2025-12-31"})
    assert ids(current) == {4, 5, 6, 7, 8}     # the allergy items before 2026 are superseded


def test_a_blank_date_is_no_filter(api):
    assert ids(chart(api, **{"from": "", "to": ""})) == set(range(1, 11))


@pytest.mark.parametrize("name, value", [("from", "2026-1-5"), ("to", "05/10/2026"), ("from", "2026-02-30"),
                                         ("to", "2026-10-02T10:00:00"), ("from", "yesterday")])
def test_a_wrong_date_gives_422_for_that_field(api, name, value):
    response = chart(api, **{name: value})
    assert response.status_code == 422
    assert response.json()["code"] == "validation" and name in response.json()["fields"]


def test_from_after_to_gives_422(api):
    response = chart(api, **{"from": "2026-10-03", "to": "2026-10-02"})
    assert response.status_code == 422 and "from" in response.json()["fields"]


def test_the_local_date_decides_with_mixed_offsets(planted_store):
    """The planted times have mixed offsets. The local date (as written) decides, not the UTC date."""
    api = planted_store.client()
    times = {row["id"]: parse_time(row["assertedAt"]) for row in planted_store.probe.rows("assertion")}
    late = next(i for i, t in times.items() if t == parse_time("2026-10-02T21:30:00.100-04:00"))   # UTC: Oct 3
    early = next(i for i, t in times.items() if t == parse_time("2026-10-03T01:10:00+05:30"))      # UTC: Oct 2
    second = ids(chart(api, **{"from": "2026-10-02", "to": "2026-10-02"}))
    third = ids(chart(api, **{"from": "2026-10-03", "to": "2026-10-03"}))
    assert late in second and late not in third
    assert early in third and early not in second
    reference = make_client(planted_store.db_path)          # SQLite on the same data
    for params in ({"from": "2026-10-02", "to": "2026-10-02"}, {"from": "2026-10-03"}, {"to": "2026-10-02"},
                   {"from": "2026-10-02", "to": "2026-10-30", "q": "penicillin"}):
        found, expected = chart(api, **params).json(), chart(reference, **params).json()
        assert ids(chart(api, **params)) == ids(chart(reference, **params)), params
        assert (found["total"], found["counts"]) == (expected["total"], expected["counts"]), params
