"""The orders by time are by the instant on each store, also for two times whose text order is the other order.

Virtuoso 7.2 orders a STORED xsd:dateTime by its text (its local time), not by the instant (plan D11). The KG
adapters order by the instant (fragments.instant, or Python), as SQLite (julianday). The two times of this test:
    2026-10-02T16:05:30-04:00  = 20:05:30 UTC   (the text order puts it first)
    2026-10-02T14:30:45-07:00  = 21:30:45 UTC   (the instant order puts it first)
They go in through the ports of each store (the same rows on SQLite and on the knowledge graph).
Run with Virtuoso: TRIAD_TEST_STORES=sqlite,oxigraph,virtuoso .venv/bin/python -m pytest -q -m virtuoso ...
"""
from __future__ import annotations

from application.paging import PageRequest
from application.ports import NewEntryRow

VISIT = 3                                   # ENC-ELENA-2026-10-02, a visit of patient 1 (Elena Marsh)
EARLIER, LATER = "2026-10-02T16:05:30-04:00", "2026-10-02T14:30:45-07:00"
EMPLOYEE = "https://triad.example/fhir/sid/employee"
MESSAGE = "https://triad.example/fhir/sid/message"
ENTRY = "https://triad.example/fhir/sid/clinical-entry"


def write_pair(ctx, category: str, code: str, members=()) -> list[int]:
    """Two entries of one message, with one assertion each: the first at EARLIER, the second at LATER."""
    out = []
    with ctx.uow.write() as now:
        message = ctx.records.add_message((MESSAGE, "MSG-TIME-ORDER"), 5, "InPerson", "Staff", now, "Two times.")
        for seq, (value, at) in enumerate((("ENTRY-T1", EARLIER), ("ENTRY-T2", LATER)), start=1):
            entry = ctx.records.add_entry((ENTRY, value), NewEntryRow(
                visit_id=VISIT, category=category, code=code, code_system="http://loinc.org", display="Heart rate",
                text=None, recorded_at=at, details={"Value": "72", "Unit": "/min"} if category == "Observation"
                else {"Name": f"Team {seq}", "Status": "active"}, members=list(members)))
            out.append(ctx.records.add_assertion(message, seq, entry, None, at, "Report", "Human", "Confirmed",
                                                 f"Item {seq}."))
    return out


def test_the_chart_and_the_latest_observation_are_by_the_instant(store):
    ctx = store.open_ctx()
    try:
        earlier, later = write_pair(ctx, "Observation", "8867-4")
        page = ctx.records.items_page(1, category="Observation", page=PageRequest(50, 0))
        ids = [a.id for a in page.items]
        assert ids.index(later) < ids.index(earlier)                         # newest (instant) first
        latest = ctx.records.latest_observations(1, ["8867-4"], visible_only=False, limit=5)
        assert [a.id for a in latest] == [later]
    finally:
        ctx.close()


def test_the_head_of_the_care_teams_of_a_visit_is_the_latest_instant(store):
    ctx = store.open_ctx()
    try:
        _, later = write_pair(ctx, "CareTeam", "care-team", members=[(EMPLOYEE, "E1006", "attender")])
        versions = ctx.records.care_team_versions(VISIT)
        assert versions[0].assertion_id == later
    finally:
        ctx.close()
