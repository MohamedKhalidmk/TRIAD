"""Business rules of TRIAD that do not need the database. Pure functions; no I/O.

- the author label of the 3MT slide,
- the patient-visible rule (USER_FLOWS.md section 2.1; the same rule as query Q12 in dml/03),
- the entry and version rule (doc/api.md section 3.4),
- the visit of "What is my plan?",
- the clock rule: each write is one step (1 minute or 1 second) after the latest time (doc/api.md section 1.3).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from domain.errors import Conflict

ONE_MINUTE = timedelta(minutes=1)


# ----- authors -----

def author_label(source: str, origin: str, staff_id: Optional[int], staff_role: Optional[str]) -> str:
    """The short label of the 3MT slide. The order follows query Q3; the agent comes first."""
    if source == "Agent":
        return "Agent"
    if origin == "OtherClinic":
        return "Other clinic"
    if origin == "PharmaNet":
        return "PharmaNet"
    if staff_id is None:
        return "Patient"
    if staff_role == "Doctor":
        return "Physician"
    if staff_role == "MOA":
        return "Front desk"
    return staff_role or "Staff"


# ----- the patient-visible rule -----

def is_patient_visible(*, is_current: bool, verification: str, intent: str, source: str,
                       author_role: Optional[str], staff_id: Optional[int], origin: str, category: str) -> bool:
    """A patient sees an item only if it is current, it is not entered in error, and it is
    a doctor decision by a person, a confirmed observation or lab result, or a report that the patient sent."""
    if not is_current or verification == "EnteredInError":
        return False
    doctor_decision = intent == "Decision" and source == "Human" and author_role == "Doctor"
    confirmed_result = category in ("Observation", "LabReport") and verification == "Confirmed"
    patient_report = staff_id is None and origin == "Patient"
    return doctor_decision or confirmed_result or patient_report


# ----- the entry and version rule -----

def check_head(entry_head_id: Optional[int], supersedes_id: Optional[int], entry_exists: bool,
               supersedes_is_current: bool) -> None:
    """Raise Conflict if the new assertion does not supersede the current assertion of its chain.

    - An assertion about an entry that exists must supersede the current assertion of that entry.
    - An assertion about a new entry can supersede one current assertion (a new version with new content).
    """
    if entry_exists:
        if entry_head_id is None:
            raise Conflict("A newer item supersedes this item. Use the current item.",
                           {"entryId": "The item is not current."})
        if supersedes_id != entry_head_id:
            raise Conflict("The item changed. The new assertion must supersede the current assertion.",
                           {"supersedesId": f"The current assertion is {entry_head_id}."})
        return
    if supersedes_id is not None and not supersedes_is_current:
        raise Conflict("The item changed. You can supersede only the current assertion.",
                       {"supersedesId": "This assertion is not current."})


# ----- the plan visit -----

def plan_visit(visits: Sequence[tuple[int, str, str, Optional[str]]]) -> Optional[int]:
    """The visit of "What is my plan?": the open visit; else the latest visit that is not a virtual report visit.

    `visits` holds (id, class, start, end) rows.
    """
    open_visits = [v for v in visits if v[3] is None]
    if open_visits:
        return max(open_visits, key=lambda v: parse_time(v[2]))[0]
    closed = [v for v in visits if v[1] != "VR"]
    if not closed:
        return None
    return max(closed, key=lambda v: parse_time(v[2]))[0]


# ----- times -----

def parse_time(value: str) -> datetime:
    """Parse an ISO 8601 time. A time without an offset is UTC. A date is midnight UTC."""
    text = value.strip().replace("Z", "+00:00")
    if len(text) == 10:
        text += "T00:00:00+00:00"
    moment = datetime.fromisoformat(text)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def next_write_time(base: datetime, latest: Optional[datetime], step: timedelta = ONE_MINUTE) -> datetime:
    """The time of a new write: max(base, latest) + step (default 1 minute), in the offset of `base`."""
    start = base if latest is None or base >= latest else latest
    return (start + step).astimezone(base.tzinfo)


def format_time(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def short_date(value: str) -> str:
    """'2026-10-02T11:40:00-04:00' -> 'Oct 2, 2026' (the date in the offset of the value)."""
    moment = parse_time(value) if len(value) > 10 else datetime.fromisoformat(value)
    return f"{moment:%b} {moment.day}, {moment.year}"
