"""The templates of the fake model: they write the answer of an "ask" turn from one tool result.

The tool selects the evidence with a targeted query (tools.py). A template uses only the items of that
result, and the turn cites only these items. `you` is True when the user is the patient.
"""
from __future__ import annotations

from typing import Callable

from domain.rules import short_date
from domain.views import AssertionView

from application.assistant.tools import CLASS_LABEL, MAX_ITEMS, ToolResult

HELP_TEXT = ("I can answer questions about allergies, medications, the plan, lab results, vital signs, diagnoses, "
             "visits and nurse recommendations.")


def who(label: str, you: bool) -> str:
    return {"Physician": "A physician", "Nurse": "A nurse", "Front desk": "The front desk",
            "Other clinic": "Another clinic", "Agent": "The assistant",
            "Patient": "You" if you else "The patient"}.get(label, label)


def where(you: bool) -> str:
    return "in your record" if you else "for this patient"


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def medication_name(a: AssertionView) -> str:
    return str(a.details.get("medication") or a.display)


# ----- allergies -----

def allergy_status(a: AssertionView, you: bool) -> str:
    by, date = who(a.author.label, you), short_date(a.asserted_at)
    if a.verification == "Refuted":
        method = " with an allergy test" if "test" in a.statement.lower() else ""
        return f"{by} ruled it out{method} on {date}."
    if a.verification == "Confirmed":
        return f"{by} confirmed it on {date}."
    return f"{by} reported it on {date}. Nobody confirmed it yet."


def yes_no(a: AssertionView) -> str:
    return {"Refuted": "No.", "Confirmed": "Yes."}.get(a.verification, "Possibly.")


def allergies(r: ToolResult) -> str:
    found, you, term = r.items, r.for_patient, r.arguments.get("substance")
    if term:
        if not found:
            return f"No {term} allergy is recorded {where(you)}."
        if len(found) == 1:
            return f"{yes_no(found[0])} {allergy_status(found[0], you)}"
    if not found:
        return f"No allergy is recorded {where(you)}."
    if len(found) == 1:
        a = found[0]
        return f"One allergy item is recorded: {a.display}. {allergy_status(a, you)}"
    found = found[:MAX_ITEMS]
    lines = [f"- {a.display}: {allergy_status(a, you)}" for a in found]
    return f"{len(found)} allergy items are recorded:\n" + "\n".join(lines)


# ----- medications -----

def medications(r: ToolResult) -> str:
    meds, you = r.items, r.for_patient
    if not meds:
        return f"No current medication is recorded {where(you)}."
    lines = []
    for a in meds:
        line = f"- {medication_name(a)}"
        if a.details.get("dosage"):
            line += f", {a.details['dosage']}"
        if a.details.get("status") == "draft":
            line += " (proposed)"
        if a.intent == "Report" and a.author.label == "Patient":
            line += f". {'You' if you else 'The patient'} reported: \"{a.statement}\""
        lines.append(line)
    head = "You have" if you else "The patient has"
    return f"{head} {plural(len(meds), 'current medication')}:\n" + "\n".join(lines)


# ----- the plan -----

def plan_line(a: AssertionView) -> str:
    if a.category == "Diagnosis":
        note = "" if a.verification == "Confirmed" else f" ({a.verification.lower()})"
        extra = "" if a.statement.rstrip(".").lower() == a.display.lower() else f" {a.statement}"
        return f"- Assessment: {a.display}{note}.{extra}"
    if a.category == "LabOrder":
        return f"- Test ordered: {a.details.get('testName') or a.display}."
    if a.category == "LabReport":
        return f"- Test result: {a.display}: {a.details.get('conclusion') or a.statement}"
    if a.category == "Prescription":
        label = {"active": "Medication", "stopped": "Stopped medication", "draft": "Proposed medication",
                 "completed": "Completed medication"}.get(str(a.details.get("status")), "Medication")
        parts = [medication_name(a)] + [str(a.details[k]) for k in ("dosage", "frequency") if a.details.get(k)]
        return f"- {label}: {', '.join(parts)}."
    return f"- Procedure: {a.display}."


def plan(r: ToolResult) -> str:
    visit = r.visit
    if visit is None:
        return "There is no visit to make a plan from."
    label = CLASS_LABEL.get(visit.visit_class, visit.visit_class)
    when = f"{label} visit of {short_date(visit.start_date)}{' (open)' if visit.is_open else ''}"
    if not r.items:
        return f"The {when} has no plan items yet."
    whose = "Your plan" if r.for_patient else "The plan"
    return f"{whose} for the {when}:\n" + "\n".join(plan_line(a) for a in r.items)


# ----- labs, vital signs, diagnoses and visits -----

def labs(r: ToolResult) -> str:
    if not r.items:
        return f"No lab order or lab result is recorded {where(r.for_patient)}."
    lines = []
    for a in r.items:
        kind = "ordered" if a.category == "LabOrder" else "result"
        detail = a.details.get("conclusion") if a.category == "LabReport" else None
        lines.append(f"- {short_date(a.asserted_at)}: {a.display} ({kind}){': ' + str(detail) if detail else ''}")
    return f"The latest {plural(len(r.items), 'lab item')}:\n" + "\n".join(lines)


def vitals(r: ToolResult) -> str:
    """The latest value of each vital sign."""
    if not r.items:
        return f"No vital sign is recorded {where(r.for_patient)}."
    lines = [f"- {a.display}: {a.details.get('value')}{' ' + str(a.details['unit']) if a.details.get('unit') else ''}"
             f" ({short_date(a.asserted_at)})" for a in r.items]
    return "The latest vital signs:\n" + "\n".join(lines)


def diagnoses(r: ToolResult) -> str:
    if not r.items:
        return f"No current diagnosis is recorded {where(r.for_patient)}."
    lines = [f"- {a.display} ({a.verification.lower()}, {short_date(a.asserted_at)})" for a in r.items]
    count = f"{len(r.items)} current {'diagnosis' if len(r.items) == 1 else 'diagnoses'}"
    return f"{count}:\n" + "\n".join(lines)


def visits(r: ToolResult) -> str:
    if not r.visits:
        return "No visit is recorded."
    lines = []
    for v in r.visits:
        label = CLASS_LABEL.get(v.visit_class, v.visit_class)
        reason = f": {v.reason}" if v.reason else ""
        place = f" ({v.department})" if v.department else ""
        state = " (open)" if v.is_open else ""
        lines.append(f"- {short_date(v.start_date)}: {label} visit{reason}{place}{state}")
    return "The latest visits:\n" + "\n".join(lines)


# ----- recommendations -----

def recommendations(r: ToolResult) -> str:
    role = r.arguments.get("role")
    visit = r.visit
    if visit is None:
        return "There is no visit with recommendations."
    when = f"{CLASS_LABEL.get(visit.visit_class, visit.visit_class)} visit of {short_date(visit.start_date)}"
    found = r.items
    kind = f"{role.lower()} recommendation" if role else "recommendation"
    if not found:
        return f"No {kind} is recorded for the {when}."
    authors = {(a.author.name, a.author.role) for a in found}
    by = (f"{found[0].author.name} ({found[0].author.role})" if len(authors) == 1
          else (f"The {role.lower()}s" if role else "The care team"))
    lines = []
    for a in found:
        state = "still current" if a.is_current else "revised later"
        lines.append(f"- {a.display}: {a.statement} ({state})")
    return f"{by} recommended {plural(len(found), 'item')} in the {when}:\n" + "\n".join(lines)


TEMPLATES: dict[str, Callable[[ToolResult], str]] = {
    "get_allergies": allergies, "get_medications": medications, "get_plan": plan, "get_lab_results": labs,
    "get_vital_signs": vitals, "get_diagnoses": diagnoses, "get_visits": visits,
    "get_recommendations": recommendations,
}


def answer_text(result: ToolResult) -> str:
    """The answer of the fake model from the result of its one tool call."""
    return TEMPLATES[result.name](result)
