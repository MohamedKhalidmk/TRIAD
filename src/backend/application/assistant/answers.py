"""The rule-based answers of the Care Assistant.

The rules select the evidence: the current assertions that the user can see (a patient sees the
patient-visible items only). The draft text uses only that evidence. The assistant cites only these assertions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from domain.access import Actor
from domain.rules import plan_visit, short_date
from domain.views import AssertionView, PatientView

from application.assistant.intents import allergy_term, asks_about_nurse, intent_of
from application.context import AppContext

CLASS_LABEL = {"EMER": "emergency", "AMB": "ambulatory", "IMP": "inpatient", "HH": "home health", "VR": "virtual"}
PLAN_ORDER = ("Diagnosis", "LabOrder", "LabReport", "Prescription", "Procedure")
MAX_ITEMS = 12
# LOINC codes of vital signs (the FHIR vital-signs profile and the codes of the record form).
VITAL_SIGNS = ("8867-4", "85354-9", "8480-6", "8462-4", "2708-6", "59408-5", "8310-5", "9279-1", "29463-7",
               "8302-2", "39156-5", "72514-3")


@dataclass
class Answer:
    intent: str
    text: str
    evidence: list[AssertionView] = field(default_factory=list)


def who(label: str, actor: Actor) -> str:
    return {"Physician": "A physician", "Nurse": "A nurse", "Front desk": "The front desk",
            "Other clinic": "Another clinic", "Agent": "The assistant",
            "Patient": "You" if actor.is_patient else "The patient"}.get(label, label)


def where(actor: Actor) -> str:
    return "in your record" if actor.is_patient else "for this patient"


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def medication_name(a: AssertionView) -> str:
    return str(a.details.get("medication") or a.display)


# ----- allergies -----

def allergy_status(a: AssertionView, actor: Actor) -> str:
    by, date = who(a.author.label, actor), short_date(a.asserted_at)
    if a.verification == "Refuted":
        method = " with an allergy test" if "test" in a.statement.lower() else ""
        return f"{by} ruled it out{method} on {date}."
    if a.verification == "Confirmed":
        return f"{by} confirmed it on {date}."
    return f"{by} reported it on {date}. Nobody confirmed it yet."


def yes_no(a: AssertionView) -> str:
    return {"Refuted": "No.", "Confirmed": "Yes."}.get(a.verification, "Possibly.")


def term_matches(term: str, a: AssertionView) -> bool:
    words = [w for w in term.split() if len(w) >= 3]
    text = f"{a.display} {a.details.get('substance') or ''}".lower()
    return bool(words) and all(w in text for w in words)


def allergies(ctx: AppContext, actor: Actor, patient: PatientView, question: str,
              items: list[AssertionView]) -> Answer:
    found = [a for a in items if a.category == "Allergy"]
    term = allergy_term(question)
    if term:
        found = [a for a in found if term_matches(term, a)]
        if not found:
            return Answer("allergy", f"No {term} allergy is recorded {where(actor)}.")
        if len(found) == 1:
            return Answer("allergy", f"{yes_no(found[0])} {allergy_status(found[0], actor)}", found)
    if not found:
        return Answer("allergy", f"No allergy is recorded {where(actor)}.")
    if len(found) == 1:
        a = found[0]
        return Answer("allergy", f"One allergy item is recorded: {a.display}. {allergy_status(a, actor)}", found)
    found = found[:MAX_ITEMS]
    lines = [f"- {a.display}: {allergy_status(a, actor)}" for a in found]
    return Answer("allergy", f"{len(found)} allergy items are recorded:\n" + "\n".join(lines), found)


# ----- medications -----

def medications(ctx: AppContext, actor: Actor, patient: PatientView, question: str,
                items: list[AssertionView]) -> Answer:
    meds = [a for a in items if a.category == "Prescription" and a.details.get("status") in ("active", "draft")
            and a.verification not in ("Refuted", "EnteredInError")][:MAX_ITEMS]
    if not meds:
        return Answer("medications", f"No current medication is recorded {where(actor)}.")
    lines = []
    for a in meds:
        line = f"- {medication_name(a)}"
        if a.details.get("dosage"):
            line += f", {a.details['dosage']}"
        if a.details.get("status") == "draft":
            line += " (proposed)"
        if a.intent == "Report" and a.author.label == "Patient":
            line += f". {'You' if actor.is_patient else 'The patient'} reported: \"{a.statement}\""
        lines.append(line)
    head = "You have" if actor.is_patient else "The patient has"
    return Answer("medications", f"{head} {plural(len(meds), 'current medication')}:\n" + "\n".join(lines), meds)


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


def plan(ctx: AppContext, actor: Actor, patient: PatientView, question: str, items: list[AssertionView]) -> Answer:
    visit_id = plan_visit(ctx.visits.visit_rows(patient.id))
    if visit_id is None:
        return Answer("plan", "There is no visit to make a plan from.")
    visit = ctx.visits.get(visit_id)
    label = CLASS_LABEL.get(visit.visit_class, visit.visit_class)
    when = f"{label} visit of {short_date(visit.start_date)}{' (open)' if visit.is_open else ''}"
    chosen = [a for a in items if a.visit_id == visit_id and a.category in PLAN_ORDER]
    chosen.sort(key=lambda a: PLAN_ORDER.index(a.category))
    chosen = chosen[:MAX_ITEMS]
    if not chosen:
        return Answer("plan", f"The {when} has no plan items yet.")
    whose = "Your plan" if actor.is_patient else "The plan"
    return Answer("plan", f"{whose} for the {when}:\n" + "\n".join(plan_line(a) for a in chosen), chosen)


# ----- labs, vital signs, diagnoses and visits -----

def labs(ctx: AppContext, actor: Actor, patient: PatientView, question: str, items: list[AssertionView]) -> Answer:
    found = [a for a in items if a.category in ("LabOrder", "LabReport")][:MAX_ITEMS]
    if not found:
        return Answer("labs", f"No lab order or lab result is recorded {where(actor)}.")
    lines = []
    for a in found:
        kind = "ordered" if a.category == "LabOrder" else "result"
        detail = a.details.get("conclusion") if a.category == "LabReport" else None
        lines.append(f"- {short_date(a.asserted_at)}: {a.display} ({kind}){': ' + str(detail) if detail else ''}")
    return Answer("labs", f"The latest {plural(len(found), 'lab item')}:\n" + "\n".join(lines), found)


def vitals(ctx: AppContext, actor: Actor, patient: PatientView, question: str, items: list[AssertionView]) -> Answer:
    """The latest value of each vital sign."""
    seen, found = set(), []
    for a in items:
        if a.category != "Observation" or a.code not in VITAL_SIGNS or a.code in seen:
            continue
        seen.add(a.code)
        found.append(a)
    if not found:
        return Answer("vitals", f"No vital sign is recorded {where(actor)}.")
    lines = [f"- {a.display}: {a.details.get('value')}{' ' + str(a.details['unit']) if a.details.get('unit') else ''}"
             f" ({short_date(a.asserted_at)})" for a in found]
    return Answer("vitals", "The latest vital signs:\n" + "\n".join(lines), found)


def diagnoses(ctx: AppContext, actor: Actor, patient: PatientView, question: str,
              items: list[AssertionView]) -> Answer:
    found = [a for a in items if a.category == "Diagnosis"
             and a.details.get("clinicalStatus") in (None, "active", "recurrence", "relapse")
             and a.verification not in ("Refuted", "EnteredInError")][:MAX_ITEMS]
    if not found:
        return Answer("diagnoses", f"No current diagnosis is recorded {where(actor)}.")
    lines = [f"- {a.display} ({a.verification.lower()}, {short_date(a.asserted_at)})" for a in found]
    count = f"{len(found)} current {'diagnosis' if len(found) == 1 else 'diagnoses'}"
    return Answer("diagnoses", f"{count}:\n" + "\n".join(lines), found)


def visits(ctx: AppContext, actor: Actor, patient: PatientView, question: str, items: list[AssertionView]) -> Answer:
    rows = ctx.visits.for_patient(patient.id)[:5]
    if not rows:
        return Answer("visits", "No visit is recorded.")
    lines = []
    for v in rows:
        label = CLASS_LABEL.get(v.visit_class, v.visit_class)
        reason = f": {v.reason}" if v.reason else ""
        place = f" ({v.department})" if v.department else ""
        state = " (open)" if v.is_open else ""
        lines.append(f"- {short_date(v.start_date)}: {label} visit{reason}{place}{state}")
    return Answer("visits", "The latest visits:\n" + "\n".join(lines))


# ----- recommendations -----

def recommendations(ctx: AppContext, actor: Actor, patient: PatientView, question: str,
                    items: list[AssertionView]) -> Answer:
    nurse_only = asks_about_nurse(question)
    visit_id = plan_visit(ctx.visits.visit_rows(patient.id))
    if visit_id is None:
        return Answer("recommendations", "There is no visit with recommendations.")
    visit = ctx.visits.get(visit_id)
    when = f"{CLASS_LABEL.get(visit.visit_class, visit.visit_class)} visit of {short_date(visit.start_date)}"
    found = ctx.records.assertions(patient.id, current_only=False, visit_id=visit_id)
    if actor.is_patient:
        found = [a for a in found if a.patient_visible]
    found = [a for a in found if a.intent == "Recommendation" and (not nurse_only or a.author.role == "Nurse")]
    found.sort(key=lambda a: (a.asserted_at, a.seq))
    found = found[:MAX_ITEMS]
    kind = "nurse recommendation" if nurse_only else "recommendation"
    if not found:
        return Answer("recommendations", f"No {kind} is recorded for the {when}.")
    authors = {(a.author.name, a.author.role) for a in found}
    by = (f"{found[0].author.name} ({found[0].author.role})" if len(authors) == 1
          else ("The nurses" if nurse_only else "The care team"))
    lines = []
    for a in found:
        state = "still current" if a.is_current else "revised later"
        lines.append(f"- {a.display}: {a.statement} ({state})")
    return Answer("recommendations", f"{by} recommended {plural(len(found), 'item')} in the {when}:\n"
                  + "\n".join(lines), found)


def unknown(ctx: AppContext, actor: Actor, patient: PatientView, question: str, items: list[AssertionView]) -> Answer:
    return Answer("unknown", "I can answer questions about allergies, medications, the plan, lab results, "
                             "vital signs, diagnoses, visits and nurse recommendations.")


HANDLERS: dict[str, Callable[..., Answer]] = {
    "allergy": allergies, "medications": medications, "plan": plan, "labs": labs, "vitals": vitals,
    "diagnoses": diagnoses, "visits": visits, "recommendations": recommendations, "unknown": unknown,
}


def answer_question(ctx: AppContext, actor: Actor, patient: PatientView, question: str,
                    items: Optional[list[AssertionView]] = None) -> Answer:
    """Select the evidence with the rules and make the draft answer."""
    if items is None:
        items = ctx.records.assertions(patient.id, current_only=True)
        if actor.is_patient:
            items = [a for a in items if a.patient_visible]
    return HANDLERS[intent_of(question)](ctx, actor, patient, question, items)
