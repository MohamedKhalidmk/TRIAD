"""The permission matrix of USER_FLOWS.md section 2 (domain/access.py)."""
from __future__ import annotations

import pytest

from domain.access import (CARE_TEAM_DENIED, NOT_SELF_DENIED, allowed, denial_message, permissions, record_intents,
                           supersede_denial)
from domain.views import AssertionView, Author

# The user kinds: (role, is_self, on_care_team)
KINDS = {
    "patient-self": ("Patient", True, False),
    "patient-other": ("Patient", False, False),
    "moa": ("MOA", False, False),
    "nurse-team": ("Nurse", False, True),
    "nurse-off": ("Nurse", False, False),
    "doctor-team": ("Doctor", False, True),
    "doctor-off": ("Doctor", False, False),
}

# action -> the user kinds that the matrix allows
MATRIX = {
    "read_patient": {"patient-self", "moa", "nurse-team", "nurse-off", "doctor-team", "doctor-off"},
    "register_patient": {"moa"},
    "edit_demographics": {"moa"},
    "delete_patient": {"moa"},
    "view_chart": {"patient-self", "nurse-team", "doctor-team"},
    "view_chain": {"patient-self", "nurse-team", "doctor-team"},
    "view_visits": {"patient-self", "moa", "nurse-team", "doctor-team"},
    "view_care_team": {"patient-self", "moa", "nurse-team", "doctor-team"},
    "check_in": {"moa"},
    "end_visit": {"moa", "doctor-team"},
    "move_location": {"moa", "nurse-team", "doctor-team"},
    "manage_care_team": {"moa", "doctor-team"},
    "record": {"patient-self", "moa", "nurse-team", "doctor-team"},
    "chat": {"patient-self", "nurse-team", "doctor-team"},
    "tell": {"patient-self", "nurse-team", "doctor-team"},
    "view_audit": {"patient-self", "doctor-team"},
    "read_directory": {"moa", "nurse-team", "nurse-off", "doctor-team", "doctor-off"},
    "manage_directory": {"moa"},
    "read_codes": {"moa", "nurse-team", "nurse-off", "doctor-team", "doctor-off"},
}


@pytest.mark.parametrize("action,kind", [(a, k) for a in MATRIX for k in KINDS])
def test_the_permission_matrix(action, kind):
    role, is_self, team = KINDS[kind]
    assert allowed(action, role, is_self, team) == (kind in MATRIX[action])


@pytest.mark.parametrize("kind,intents", [
    ("patient-self", ["Report"]), ("patient-other", []), ("moa", ["Report"]),
    ("nurse-team", ["Report", "Recommendation"]), ("nurse-off", []),
    ("doctor-team", ["Report", "Recommendation", "Decision"]), ("doctor-off", []),
])
def test_the_intents_that_each_user_can_record(kind, intents):
    assert record_intents(*KINDS[kind]) == intents


def test_the_permissions_object_follows_the_matrix():
    p = permissions("Nurse", False, True)
    assert p.view_chart and p.chat and p.tell and p.move_location
    assert not (p.check_in or p.end_visit or p.manage_care_team or p.view_audit or p.edit_demographics)
    assert p.record_intents == ["Report", "Recommendation"]
    moa = permissions("MOA", False, False)
    assert moa.check_in and moa.end_visit and moa.manage_care_team and moa.edit_demographics
    assert not (moa.view_chart or moa.chat or moa.view_audit)


def test_the_denial_messages():
    assert denial_message("view_chart", "Nurse", False) == CARE_TEAM_DENIED
    assert denial_message("view_chart", "Doctor", False) == CARE_TEAM_DENIED
    assert denial_message("view_chart", "Patient", False) == NOT_SELF_DENIED
    assert "MOA" in denial_message("chat", "MOA", False)
    assert denial_message("check_in", "Nurse", False) != CARE_TEAM_DENIED


def item(intent="Report", verification="Confirmed", category="Observation", visible=False, staff_id=7,
         origin="Staff") -> AssertionView:
    return AssertionView(id=1, entry_id=1, message_id=1, seq=1, visit_id=1, category=category, code="x",
                         code_system="y", display="z", details={}, statement="s", intent=intent, source="Human",
                         verification=verification, asserted_at="2026-10-30T09:00:00-04:00",
                         author=Author("A", "Nurse" if staff_id else "Patient", staff_id, "Nurse"),
                         channel="InPerson", origin=origin, supersedes_id=None, superseded_by_id=None,
                         is_current=True, patient_visible=visible)


@pytest.mark.parametrize("role,target,intent,ok", [
    # the supersede guard: an item that the patient can see
    ("Doctor", item("Decision", visible=True), "Decision", True),
    ("Doctor", item("Decision", visible=True), "Report", False),
    ("Nurse", item("Report", visible=True), "Report", False),
    ("Patient", item("Decision", visible=True), "Report", True),
    ("MOA", item("Report", visible=True), "Report", False),
    # the matrix: who can supersede what
    ("Doctor", item("Recommendation", "Provisional"), "Decision", True),
    ("Nurse", item("Recommendation", "Provisional"), "Recommendation", True),
    ("Nurse", item("Report", "Unconfirmed"), "Report", True),
    ("Nurse", item("Decision", "Provisional"), "Recommendation", False),
    ("MOA", item("Report", category="CareTeam"), "Report", True),
    ("MOA", item("Report", "Unconfirmed"), "Report", False),
    ("Patient", item("Report", "Unconfirmed", staff_id=None, origin="Patient"), "Report", True),
    ("Patient", item("Recommendation", "Provisional"), "Report", False),
])
def test_who_can_supersede_an_item(role, target, intent, ok):
    assert (supersede_denial(role, target, intent) is None) == ok
