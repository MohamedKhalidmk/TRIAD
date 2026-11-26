"""The visits and their locations on each store (the VisitRepository port; plan 5.5 and 5.6).

Each test runs on SQLite and on the knowledge graph (Oxigraph; Virtuoso with TRIAD_TEST_STORES). The reads are
compared with `store.reference()`, the writes with the `twin` (tests/integration/kg_compare.py).

The check-in and the move read the location in the directory (agent D). Until the merge, the fixture
`directory_reads` makes that stub read the SQLite copy of the store (the tests do not change the locations).

The order of the visits uses the instant of the start (SQLite: julianday). The test with mixed offsets has times
whose text order is not their instant order (D11: Virtuoso orders xsd:dateTime by the text); the repository sorts
them in Python, so the order is the same on each store.
"""
from __future__ import annotations

import time

import pytest

from application.paging import PageRequest
from tests.conftest import all_items, as_user, make_client
from tests.fixtures.stores import SqliteProbe
from tests.integration.kg_compare import (BRENNAN, ELENA, MOA, OKAFOR, PARK, both, directory_reads,  # noqa: F401
                                          instants, response, twin)

ER_WAIT, ER_BED_1, CARD_WARD, VIRTUAL = 2, 3, 7, 14
ENCOUNTER = "https://triad.example/fhir/sid/encounter"


@pytest.fixture
def reference(store):
    return make_client(store.db_path)


def pages(repository_method, *args, total: int, limit: int = 2):
    """All page slices of a port list (limit `limit`), with the slices after the end."""
    out = []
    for offset in list(range(0, total + 1, limit)) + [total + 3]:
        page = repository_method(*args, PageRequest(limit=limit, offset=offset))
        out.append((page.total, page.items))
    return out


# ----- reads -----

@pytest.mark.parametrize("user", [MOA, OKAFOR, BRENNAN, ELENA, PARK])
def test_the_visits_of_a_patient_are_the_same(store, reference, user):
    url = "/api/patients/1/visits"
    found = store.client().get(url, headers=as_user(user))
    assert response(found) == response(reference.get(url, headers=as_user(user)))
    assert found.status_code == (403 if user == PARK else 200)
    if found.status_code == 200:
        assert [v["identifier"]["value"] for v in found.json()["items"]] == [
            "ENC-ELENA-2026-10-02", "ENC-ELENA-2025-08-20", "ENC-ELENA-2019-06-12"]
        for offset in (0, 1, 2, 3, 5):
            params = {"limit": 1, "offset": offset}
            assert response(store.client().get(url, headers=as_user(user), params=params)) == \
                   response(reference.get(url, headers=as_user(user), params=params))


def test_the_visit_port_reads(store):
    ctx, ref = store.open_ctx(), store.reference()
    assert pages(ctx.visits.for_patient_page, 1, total=3) == pages(ref.visits.for_patient_page, 1, total=3)
    assert ctx.visits.for_patient_page(99999, PageRequest()) == ref.visits.for_patient_page(99999, PageRequest())
    for visit_id in (1, 2, 3, 99999, -1, 0):
        assert ctx.visits.get(visit_id) == ref.visits.get(visit_id), visit_id
    assert ctx.visits.visit_rows(1) == ref.visits.visit_rows(1)
    assert ctx.visits.open_visit_id(1) is ref.visits.open_visit_id(1) is None
    assert ctx.visits.get(3).department == "Family Medicine" and ctx.visits.get(1).locations[0].location_id == VIRTUAL


# ----- writes -----

def test_check_in_move_and_end_on_each_store(store, twin, directory_reads):
    visits = "/api/patients/1/visits"
    status, visit = both(store, twin, "post", visits, MOA,
                         json={"class": "EMER", "reason": "Chest pain", "type": "Emergency", "locationId": ER_WAIT})
    assert status == 201 and visit["isOpen"] and visit["identifier"]["value"] == "ENC-000001"
    v = f"/api/visits/{visit['id']}"
    assert both(store, twin, "post", visits, MOA, json={"class": "AMB", "locationId": ER_WAIT})[0] == 409
    assert both(store, twin, "post", visits, PARK, json={"class": "AMB", "locationId": ER_WAIT})[0] == 403
    assert both(store, twin, "post", visits, MOA, json={"class": "XYZ", "locationId": ER_WAIT})[0] == 422
    assert both(store, twin, "get", "/api/patients/1", MOA)[1]["openVisitId"] == visit["id"]
    assert both(store, twin, "post", f"{v}/locations", MOA, json={"locationId": ER_BED_1})[0] == 200
    assert both(store, twin, "post", f"{v}/locations", MOA, json={"locationId": ER_BED_1})[0] == 422   # the same room
    assert both(store, twin, "post", f"{v}/locations", MOA, json={"locationId": 99999})[0] == 422
    status, moved = both(store, twin, "post", f"{v}/locations", OKAFOR, json={"locationId": CARD_WARD})
    assert status == 200 and [loc["locationId"] for loc in moved["locations"]] == [ER_WAIT, ER_BED_1, CARD_WARD]
    assert [loc["endDate"] is None for loc in moved["locations"]] == [False, False, True]
    assert moved["department"] == "Cardiology"
    assert both(store, twin, "post", f"{v}/end", PARK)[0] == 403
    status, ended = both(store, twin, "post", f"{v}/end", OKAFOR)
    assert status == 200 and not ended["isOpen"] and all(loc["endDate"] for loc in ended["locations"])
    assert ended["endDate"] == ended["locations"][-1]["endDate"]            # instants (both() gives instants)
    assert both(store, twin, "post", f"{v}/end", OKAFOR)[0] == 422
    assert both(store, twin, "post", f"{v}/locations", MOA, json={"locationId": ER_WAIT})[0] == 422
    for missing in ("/api/visits/99999/end", "/api/visits/-1/end"):
        assert both(store, twin, "post", missing, MOA)[0] == 404
    status, again = both(store, twin, "post", visits, MOA, json={"class": "AMB", "locationId": VIRTUAL})
    assert status == 201 and again["identifier"]["value"] == "ENC-000002" and again["type"] is None
    assert all_items(store.client(), visits, MOA) == all_items(twin.client(), visits, MOA)
    reference = SqliteProbe(twin.path)
    for kind in ("visit", "visit-location", "audit-event"):
        assert instants(store.probe.rows(kind)) == instants(reference.rows(kind)), kind


def test_a_report_visit_and_a_visit_with_no_location(store, twin):
    """The port writes of records.add_report_visit (end = start) and of a visit with no location."""
    found = {}
    for name, ctx in (("store", store.open_ctx()), ("twin", twin.ctx())):
        with ctx.uow.write() as now:
            first = ctx.visits.create(1, (ENCOUNTER, ctx.visits.next_identifier(ENCOUNTER, "ENC-", 6)), "VR",
                                      "Patient report", "Patient report", now, VIRTUAL, end=now)
            second = ctx.visits.create(1, (ENCOUNTER, ctx.visits.next_identifier(ENCOUNTER, "ENC-", 6)), "HH", None,
                                       None, now, None)
        found[name] = ([ctx.visits.get(first), ctx.visits.get(second)], ctx.visits.open_visit_id(1),
                       ctx.visits.visit_rows(1))
    assert instants(found["store"]) == instants(found["twin"])
    (report, home), open_id, _ = found["store"]
    assert report.identifier.value == "ENC-000001" and home.identifier.value == "ENC-000002"   # the buffer counts
    assert not report.is_open and report.locations[0].end_date is not None
    assert home.is_open and home.locations == [] and home.department is None and open_id == home.id


def test_two_moves_of_a_stored_visit_in_one_write(store, twin):
    """The second move ends only the open location (the store does not see the first move of the write)."""
    found = {}
    for name, ctx in (("store", store.open_ctx()), ("twin", twin.ctx())):
        with ctx.uow.write() as now:
            visit = ctx.visits.create(1, (ENCOUNTER, "ENC-TWO-MOVES"), "EMER", None, None, now, ER_WAIT)
        with ctx.uow.write():
            ctx.visits.move(visit, ER_BED_1, "2026-11-01T10:00:00-04:00")
            ctx.visits.move(visit, CARD_WARD, "2026-11-01T11:00:00-04:00")
        with ctx.uow.write():
            ctx.visits.move(visit, ER_WAIT, "2026-11-01T12:00:00-04:00")
        found[name] = ctx.visits.get(visit)
    assert instants(found["store"]) == instants(found["twin"])
    ends = [loc.end_date[11:16] if loc.end_date else None for loc in found["store"].locations]
    assert ends == ["10:00", "11:00", "12:00", None]


# Start times whose text order is not their instant order (UTC in the comment), and one tie of instants.
MIXED = [
    ("2026-10-31T10:00:00-04:00", "2026-10-31T11:00:00-04:00"),     # 14:00Z
    ("2026-10-31T09:30:00-07:00", None),                            # 16:30Z (the latest open visit)
    ("2026-10-31T15:00:00+00:00", "2026-10-31T15:10:00Z"),          # 15:00Z
    ("2026-10-31T20:15:00+05:30", None),                            # 14:45Z
    ("2026-10-31T12:00:00-04:00", "2026-10-31T12:30:00-04:00"),     # 16:00Z
    ("2026-10-31T16:00:00Z", "2026-10-31T16:05:00Z"),               # 16:00Z: the same instant, a larger id
]


def test_the_order_of_visits_with_mixed_offsets(store, twin):
    found = {}
    for name, ctx in (("store", store.open_ctx()), ("twin", twin.ctx())):
        with ctx.uow.write():
            for n, (start, end) in enumerate(MIXED, 1):
                visit = ctx.visits.create(1, (ENCOUNTER, f"ENC-MIXED-{n}"), "AMB", None, None, start, ER_WAIT, end)
                if end is None:          # two more locations: the text order is not the instant order
                    ctx.visits.move(visit, ER_BED_1, "2026-11-01T00:00:00+05:30")    # 18:30Z
                    ctx.visits.move(visit, CARD_WARD, "2026-10-31T12:00:00-07:00")   # 19:00Z
        found[name] = (pages(ctx.visits.for_patient_page, 1, total=len(MIXED) + 3, limit=2),
                       ctx.visits.open_visit_id(1), ctx.visits.visit_rows(1))
    assert instants(found["store"]) == instants(found["twin"])
    first_page = found["store"][0][0][1]
    assert [v.identifier.value for v in first_page] == ["ENC-MIXED-2", "ENC-MIXED-6"]
    newest = found["store"][0][1][1][0]
    assert newest.identifier.value == "ENC-MIXED-5"                      # the tie: the larger id first
    assert found["store"][1] == first_page[0].id
    open_visit = first_page[0]
    assert [loc.location_id for loc in open_visit.locations] == [ER_WAIT, ER_BED_1, CARD_WARD]
    assert [loc.end_date is None for loc in open_visit.locations] == [False, False, True]


# ----- the full data -----

def timed(fn, *args):
    start = time.perf_counter()
    out = fn(*args)
    return out, time.perf_counter() - start


def test_the_visit_lists_of_the_full_data(full_store):
    """The patients with the most visits (382, 216 and 112 in the full data) and two small ones."""
    import sqlite3
    ctx, ref = full_store.open_ctx(), full_store.reference()
    conn = sqlite3.connect(full_store.db_path)
    patients = [r[0] for r in conn.execute("SELECT PatientId FROM Visit GROUP BY 1 ORDER BY COUNT(*) DESC, 1 LIMIT 3")]
    patients += [r[0] for r in conn.execute("SELECT PatientId FROM Visit GROUP BY 1 ORDER BY COUNT(*), 1 LIMIT 2")]
    conn.close()
    timings = {}
    for patient_id in patients:
        expected = ref.visits.for_patient_page(patient_id, PageRequest(limit=1000))
        for offset in (0, 25, 100, expected.total - 3, expected.total):
            page = PageRequest(limit=25, offset=max(offset, 0))
            found, seconds = timed(ctx.visits.for_patient_page, patient_id, page)
            assert found == ref.visits.for_patient_page(patient_id, page), (patient_id, offset)
            timings[f"page {patient_id}"] = max(seconds, timings.get(f"page {patient_id}", 0))
        assert ctx.visits.visit_rows(patient_id) == ref.visits.visit_rows(patient_id)
        found_open, timings[f"open {patient_id}"] = timed(ctx.visits.open_visit_id, patient_id)
        assert found_open == ref.visits.open_visit_id(patient_id)
        first = expected.items[0].id
        visit, timings[f"get {patient_id}"] = timed(ctx.visits.get, first)
        assert visit == ref.visits.get(first)
    with ctx.uow.write():
        value, timings["next ENC"] = timed(ctx.visits.next_identifier, ENCOUNTER, "ENC-", 6)
    assert value == "ENC-000001"
    print("\n[visits, full data]", {k: f"{v * 1000:.1f} ms" for k, v in timings.items()})
    assert max(timings.values()) < full_store.time_limit(0.3), timings


def test_the_visit_api_of_the_full_data(full_store):
    api, reference = full_store.client(), make_client(full_store.db_path)
    url = "/api/patients/61/visits"
    full = all_items(reference, url, MOA)
    assert all_items(api, url, MOA) == full
    for offset in (0, 7, 200, len(full) - 1, len(full)):
        start = time.perf_counter()
        page = api.get(url, headers=as_user(MOA), params={"limit": 25, "offset": offset}).json()
        assert time.perf_counter() - start < full_store.time_limit(0.3)
        assert page["total"] == len(full) and page["items"] == full[offset:offset + 25]
