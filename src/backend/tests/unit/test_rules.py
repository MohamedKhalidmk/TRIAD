"""The domain rules (domain/rules.py) and the demo clock (infrastructure/clock.py)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from domain.errors import Conflict
from domain.rules import (author_label, check_head, is_patient_visible, next_write_time, parse_time, plan_visit,
                          short_date)
from infrastructure.clock import DemoClock


@pytest.mark.parametrize("source,origin,staff_id,role,label", [
    ("Human", "Staff", 5, "Doctor", "Physician"),
    ("Human", "Staff", 2, "Nurse", "Nurse"),
    ("Human", "Patient", 1, "MOA", "Front desk"),          # the 2019 phone report on the 3MT slide
    ("Human", "OtherClinic", 1, "MOA", "Other clinic"),
    ("Human", "Patient", None, None, "Patient"),
    ("Agent", "Staff", 5, "Doctor", "Agent"),
    ("Human", "PharmaNet", 1, "MOA", "PharmaNet"),
])
def test_the_author_label_of_the_slide(source, origin, staff_id, role, label):
    assert author_label(source, origin, staff_id, role) == label


def visible(**changes) -> bool:
    values = dict(is_current=True, verification="Confirmed", intent="Report", source="Human", author_role="Nurse",
                  staff_id=2, origin="Staff", category="Diagnosis")
    values.update(changes)
    return is_patient_visible(**values)


def test_the_patient_visible_rule():
    assert visible(intent="Decision", author_role="Doctor")                          # a doctor decision
    assert not visible(intent="Decision", author_role="Doctor", source="Agent")      # ... by the agent: no
    assert not visible(intent="Decision", author_role="Nurse")
    assert visible(category="Observation")                                          # a confirmed observation
    assert visible(category="LabReport")
    assert not visible(category="Observation", verification="Unconfirmed")
    assert visible(staff_id=None, origin="Patient", verification="Unconfirmed")      # the patient's report
    assert not visible(intent="Recommendation", verification="Provisional")
    assert not visible(intent="Decision", author_role="Doctor", is_current=False)    # superseded: no
    assert not visible(intent="Decision", author_role="Doctor", verification="EnteredInError")


def test_the_head_check():
    check_head(entry_head_id=7, supersedes_id=7, entry_exists=True, supersedes_is_current=True)
    check_head(entry_head_id=None, supersedes_id=None, entry_exists=False, supersedes_is_current=False)
    check_head(entry_head_id=None, supersedes_id=9, entry_exists=False, supersedes_is_current=True)
    with pytest.raises(Conflict):
        check_head(entry_head_id=7, supersedes_id=6, entry_exists=True, supersedes_is_current=False)
    with pytest.raises(Conflict):
        check_head(entry_head_id=7, supersedes_id=None, entry_exists=True, supersedes_is_current=False)
    with pytest.raises(Conflict):
        check_head(entry_head_id=None, supersedes_id=3, entry_exists=True, supersedes_is_current=False)
    with pytest.raises(Conflict):
        check_head(entry_head_id=None, supersedes_id=3, entry_exists=False, supersedes_is_current=False)


def test_the_plan_visit_is_the_open_visit_else_the_latest_visit_that_is_not_virtual():
    visits = [(1, "AMB", "2026-01-01T10:00:00+00:00", "2026-01-01T11:00:00+00:00"),
              (2, "VR", "2026-05-01T10:00:00+00:00", "2026-05-01T10:00:00+00:00"),
              (3, "EMER", "2025-01-01T10:00:00+00:00", "2025-01-01T12:00:00+00:00")]
    assert plan_visit(visits) == 1
    assert plan_visit(visits + [(4, "EMER", "2024-01-01T10:00:00+00:00", None)]) == 4
    assert plan_visit([(2, "VR", "2026-05-01T10:00:00+00:00", "2026-05-01T10:00:00+00:00")]) is None
    assert plan_visit([]) is None


def test_times():
    assert short_date("2026-10-02T11:40:00-04:00") == "Oct 2, 2026"
    assert short_date("1966-02-18") == "Feb 18, 1966"
    assert parse_time("2026-10-30T13:00:00Z") == parse_time("2026-10-30T09:00:00-04:00")


def test_each_write_is_one_minute_after_the_latest_time():
    base = parse_time("2026-10-30T09:00:00-04:00")
    assert next_write_time(base, None).isoformat() == "2026-10-30T09:01:00-04:00"
    older = parse_time("2026-10-29T18:00:00-04:00")
    assert next_write_time(base, older).isoformat() == "2026-10-30T09:01:00-04:00"
    later = parse_time("2026-10-30T14:05:00+00:00")                  # 10:05 in Worcester
    assert next_write_time(base, later).isoformat() == "2026-10-30T10:06:00-04:00"


def test_the_demo_clock():
    clock = DemoClock("2026-10-30T09:00:00-04:00")
    assert clock.current(None) == "2026-10-30T09:00:00-04:00"
    assert clock.write_time(None) == "2026-10-30T09:01:00-04:00"
    latest = datetime(2026, 10, 30, 13, 1, tzinfo=timezone.utc)
    assert clock.write_time(latest) == "2026-10-30T09:02:00-04:00"
    assert clock.current(latest) == "2026-10-30T09:01:00-04:00"
    system = DemoClock("system")
    written = parse_time(system.write_time(None))
    assert abs(written - datetime.now(timezone.utc) - timedelta(minutes=1)) < timedelta(seconds=5)
