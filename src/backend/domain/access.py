"""The access policy of TRIAD (USER_FLOWS.md section 2). Pure functions; no I/O.

The policy needs three facts: the role of the user, whether the patient is the user (self),
and whether the user is on a current care team of the patient. The application finds these facts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from domain.enums import INTENTS
from domain.views import AssertionView, Permissions

CARE_TEAM_DENIED = "You are not on this patient's care team. This attempt is in the audit log."
NOT_SELF_DENIED = "You can see only your own record. This attempt is in the audit log."
ROLE_DENIED = "Your role cannot do this action. This attempt is in the audit log."

# The actions that the policy knows. Each one has one rule in `allowed`.
ACTIONS = (
    "read_patient", "search_patients", "register_patient", "edit_demographics", "delete_patient",
    "view_chart", "view_chain", "view_visits", "view_care_team", "check_in", "end_visit", "move_location",
    "manage_care_team", "record", "chat", "tell", "view_audit", "read_directory", "manage_directory", "read_codes",
)


@dataclass(frozen=True)
class Actor:
    """The current user. The key is `<Role>:<identifier value>` (doc/api.md section 1.1)."""
    role: str
    key: str
    name: str
    system: str
    value: str
    staff_id: Optional[int] = None
    patient_id: Optional[int] = None

    @property
    def is_patient(self) -> bool:
        return self.role == "Patient"

    @property
    def is_staff(self) -> bool:
        return self.role != "Patient"

    def is_self(self, patient_id: Optional[int]) -> bool:
        return self.is_patient and patient_id is not None and self.patient_id == patient_id


def allowed(action: str, role: str, is_self: bool, on_care_team: bool) -> bool:
    """True if the permission matrix of USER_FLOWS.md section 2 allows the action."""
    patient_self = role == "Patient" and is_self
    clinician_on_team = role in ("Nurse", "Doctor") and on_care_team
    doctor_on_team = role == "Doctor" and on_care_team
    moa = role == "MOA"
    staff = role in ("Doctor", "Nurse", "MOA")
    rules = {
        "read_patient": patient_self or staff,
        "search_patients": True,                       # a patient gets self only
        "register_patient": moa,
        "edit_demographics": moa,
        "delete_patient": moa,
        "view_chart": patient_self or clinician_on_team,
        "view_chain": patient_self or clinician_on_team,
        "view_visits": patient_self or moa or clinician_on_team,
        "view_care_team": patient_self or moa or clinician_on_team,
        "check_in": moa,
        "end_visit": moa or doctor_on_team,
        "move_location": moa or clinician_on_team,
        "manage_care_team": moa or doctor_on_team,
        "record": patient_self or moa or clinician_on_team,
        "chat": patient_self or clinician_on_team,
        "tell": patient_self or clinician_on_team,
        "view_audit": patient_self or doctor_on_team,
        "read_directory": staff,
        "manage_directory": moa,
        "read_codes": staff,
    }
    if action not in rules:
        raise ValueError(f"Unknown action: {action}")
    return rules[action]


def record_intents(role: str, is_self: bool, on_care_team: bool) -> list[str]:
    """The intents that the user can record for this patient."""
    if role == "Patient":
        return ["Report"] if is_self else []
    if role == "MOA":
        return ["Report"]
    if role == "Nurse":
        return ["Report", "Recommendation"] if on_care_team else []
    if role == "Doctor":
        return list(INTENTS) if on_care_team else []
    return []


def permissions(role: str, is_self: bool, on_care_team: bool) -> Permissions:
    """The Permissions object of doc/api.md. The UI uses it to show buttons."""
    def ok(action: str) -> bool:
        return allowed(action, role, is_self, on_care_team)
    return Permissions(
        view_chart=ok("view_chart"), chat=ok("chat"), tell=ok("tell"),
        edit_demographics=ok("edit_demographics"), check_in=ok("check_in"), end_visit=ok("end_visit"),
        move_location=ok("move_location"), manage_care_team=ok("manage_care_team"), view_audit=ok("view_audit"),
        record_intents=record_intents(role, is_self, on_care_team))


def denial_message(action: str, role: str, is_self: bool) -> str:
    """The message of the 403 for a denied action about one patient."""
    if role == "Patient" and not is_self:
        return NOT_SELF_DENIED
    if role in ("Nurse", "Doctor") and allowed(action, role, is_self, True):
        return CARE_TEAM_DENIED           # the action needs the care team
    if role == "MOA" and action in ("view_chart", "view_chain", "chat", "tell", "view_audit"):
        return "An MOA cannot open the clinical chart, the chat or the audit log. This attempt is in the audit log."
    return ROLE_DENIED


def supersede_denial(role: str, target: AssertionView, new_intent: str) -> Optional[str]:
    """None if the user can supersede `target` with an assertion of `new_intent`. Else the reason.

    The supersede guard comes first: when the current item is visible to the patient, only a doctor
    decision or the patient's own report can supersede it.
    """
    if target.patient_visible:
        doctor_decision = role == "Doctor" and new_intent == "Decision"
        patient_report = role == "Patient" and new_intent == "Report"
        if not (doctor_decision or patient_report):
            return ("The patient can see this item. Only a doctor decision or the patient's own report "
                    "can supersede it.")
    if role == "Doctor":
        return None
    if role == "Nurse":
        if target.intent in ("Report", "Recommendation"):
            return None
        return "A nurse can supersede only reports and recommendations."
    if role == "MOA":
        if target.category == "CareTeam":
            return None
        return "An MOA can supersede only care-team entries."
    if role == "Patient":
        own_report = target.author.staff_id is None and target.origin == "Patient"
        if own_report or target.patient_visible:
            return None
        return "You can supersede only your own reports and the items in your record."
    return ROLE_DENIED
