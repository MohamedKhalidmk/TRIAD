"""Use cases: the chart, the chains and new records (doc/api.md section 3.4).

A new record is one message with one or more assertions (each message has at least one fact).
The entry and version rule:
- a new claim about the same fact (confirm, refute, a report on an item) is a new assertion on the same entry;
- a claim with new content (a new code, a new status) is a new entry whose assertion supersedes the old one.
The backend never changes a ClinicalEntry row or a subtype row after the insert.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from domain.access import Actor, record_intents, supersede_denial
from domain.enums import CHANNELS, ENTRY_CATEGORIES, INTENTS, VERIFICATIONS
from domain.errors import Invalid, NotFound
from domain.rules import check_head, parse_time
from domain.views import AssertionView, PatientView, RecordResult

from application.context import AppContext
from application.guard import deny, load_patient, require, subject_of
from application.paging import Page, PageRequest, page_of
from application.ports import NewEntryRow

PRIORITIES = ("routine", "urgent", "asap", "stat")
PRESCRIPTION_STATUSES = ("active", "draft", "stopped", "completed")
NEW_ENTRY_CATEGORIES = tuple(c for c in ENTRY_CATEGORIES if c != "CareTeam")
MESSAGES_PATH = "/api/messages"


@dataclass
class NewEntryCmd:
    category: str
    code: str
    code_system: str
    display: str
    text: Optional[str] = None
    details: dict = field(default_factory=dict)


@dataclass
class NewAssertionCmd:
    intent: str
    verification: str
    statement: str
    entry_id: Optional[int] = None
    new_entry: Optional[NewEntryCmd] = None
    supersedes_id: Optional[int] = None


@dataclass
class NewMessageCmd:
    patient_id: int
    text: str
    assertions: list[NewAssertionCmd]
    visit_id: Optional[int] = None
    channel: Optional[str] = None


@dataclass
class PreparedAssertion:
    """One checked assertion, ready to write."""
    cmd: NewAssertionCmd
    entry_id: Optional[int]
    entry: Optional[NewEntryRow]
    medication: Optional[tuple[str, str, str]]
    date_fields: tuple[str, ...]


# ----- the chart and the chains -----

@dataclass
class Chart(Page[AssertionView]):
    patient_id: int
    counts: dict[str, int]       # the items of each category for the same filters, without the category filter


@dataclass
class Chain(Page[AssertionView]):
    head_id: int                 # the current assertion of the chain


def chart(ctx: AppContext, actor: Actor, patient_id: int, visit_id: Optional[int], category: Optional[str],
          history: bool, text: Optional[str] = None, page: PageRequest = PageRequest()) -> Chart:
    """One page of the chart, in the order of the chart. A patient gets the patient-visible items only.

    `text` searches the display, the statement and the author name. Each page read writes one audit record.
    """
    patient = load_patient(ctx, patient_id)
    path = "/api/patients/{patient}/chart"
    require(ctx, actor, patient, "view_chart", "read", path)
    if category and category not in ENTRY_CATEGORIES:
        raise Invalid("The category is not correct.", {"category": f"Use one of {', '.join(ENTRY_CATEGORIES)}."})
    filters = dict(current_only=actor.is_patient or not history, visit_id=visit_id,
                   text=(text or "").strip() or None, visible_only=actor.is_patient)
    found = ctx.records.items_page(patient.id, category=category or None, page=page, **filters)
    counts = ctx.records.category_counts(patient.id, **filters)
    with ctx.uow.write() as now:
        ctx.audit.add(now, "read", "Allowed", actor, subject_of(patient), path)
    return Chart(items=found.items, total=found.total, limit=found.limit, offset=found.offset,
                 patient_id=patient.id, counts=counts)


def chain(ctx: AppContext, actor: Actor, assertion_id: int, page: PageRequest = PageRequest()) -> Chain:
    """One page of the chain of an assertion, newest first. A patient gets the current item only."""
    found = ctx.records.assertion(assertion_id)
    if found is None:
        raise NotFound(f"Assertion {assertion_id} does not exist.")
    patient = load_patient(ctx, found.patient_id)
    path = "/api/assertions/{assertion}/chain"
    require(ctx, actor, patient, "view_chain", "read", path)
    head = found if found.is_current else ctx.records.chain_head(assertion_id)
    if actor.is_patient:
        if not head.patient_visible:
            deny(ctx, actor, patient, "read", path,
                 "This item is not in your record. This attempt is in the audit log.")
        items = page_of([head], page)
    else:
        items = ctx.records.chain_page(assertion_id, page)
    with ctx.uow.write() as now:
        ctx.audit.add(now, "read", "Allowed", actor, subject_of(patient), path)
    return Chain(items=items.items, total=items.total, limit=items.limit, offset=items.offset, head_id=head.id)


def supersedes_for(ctx: AppContext, actor: Actor, assertion: AssertionView) -> list[AssertionView]:
    """The assertions that `assertion` supersedes, oldest first (the order of the 3MT slide).

    A patient gets none (the chain view rule). The chain itself (Chain.items) stays newest first.
    """
    if actor.is_patient:
        return []
    items = ctx.records.chain(assertion.id)
    index = next((i for i, a in enumerate(items) if a.id == assertion.id), None)
    return list(reversed(items[index + 1:])) if index is not None else []


# ----- new records -----

def post_message(ctx: AppContext, actor: Actor, cmd: NewMessageCmd) -> RecordResult:
    patient = load_patient(ctx, cmd.patient_id)
    team = require(ctx, actor, patient, "record", "create", MESSAGES_PATH)
    intents = record_intents(actor.role, actor.is_self(patient.id), team)
    if not (cmd.text or "").strip():
        raise Invalid("The message text is missing.", {"text": "Write the note of the message."})
    if cmd.channel is not None and cmd.channel not in CHANNELS:
        raise Invalid("The channel is not correct.", {"channel": f"Use one of {', '.join(CHANNELS)}."})
    prepared, visit_id, needs_visit = prepare(ctx, actor, patient, cmd.assertions, cmd.visit_id, intents,
                                              MESSAGES_PATH)
    channel = "App" if actor.is_patient else (cmd.channel or "InPerson")
    with ctx.uow.write() as now:
        message_id, ids = write(ctx, actor, patient, prepared, visit_id, needs_visit, channel, cmd.text.strip(),
                                "Human", now)
        ctx.audit.add(now, "create", "Allowed", actor, subject_of(patient), MESSAGES_PATH)
    views = ctx.records.assertions_by_id(ids)
    return RecordResult(message_id=message_id, assertions=[views[i] for i in ids])


def prepare(ctx: AppContext, actor: Actor, patient: PatientView, assertions: list[NewAssertionCmd],
            visit_id: Optional[int], intents: list[str],
            path: str) -> tuple[list[PreparedAssertion], Optional[int], bool]:
    """Check each assertion before the write. Return the checked assertions and the visit of new entries."""
    if not assertions:
        raise Invalid("A message needs one or more assertions.", {"assertions": "Add one or more assertions."})
    errors: dict[str, str] = {}
    prepared: list[PreparedAssertion] = []
    targets: set[int] = set()
    for index, a in enumerate(assertions):
        where = f"assertions[{index}]"
        if (a.entry_id is None) == (a.new_entry is None):
            errors[where] = "Give exactly one of entryId and newEntry."
            continue
        if a.intent not in INTENTS:
            errors[f"{where}.intent"] = f"Use one of {', '.join(INTENTS)}."
            continue
        if a.verification not in VERIFICATIONS:
            errors[f"{where}.verification"] = f"Use one of {', '.join(VERIFICATIONS)}."
            continue
        if not (a.statement or "").strip():
            errors[f"{where}.statement"] = "Write the statement of the assertion."
            continue
        if a.intent not in intents:
            deny(ctx, actor, patient, "create", path,
                 f"Your role cannot record a {a.intent.lower()} for this patient. This attempt is in the audit log.")
        if a.entry_id is not None:
            entry = ctx.records.entry(a.entry_id)
            if entry is None or entry.patient_id != patient.id:
                errors[f"{where}.entryId"] = "The item does not exist for this patient."
                continue
            check_head(entry.head_id, a.supersedes_id, True, False)
            target = ctx.records.assertion(entry.head_id)
            check_supersede(ctx, actor, patient, target, a.intent, path)
            targets_add(targets, entry.head_id, errors, where)
            prepared.append(PreparedAssertion(a, entry.id, None, None, ()))
            continue
        try:
            row, medication, date_fields = new_entry_row(a.new_entry, a.statement)
        except Invalid as error:
            errors.update({f"{where}.newEntry.{k}": v for k, v in (error.fields or {}).items()})
            continue
        if a.supersedes_id is not None:
            target = ctx.records.assertion(a.supersedes_id)
            if target is None or target.patient_id != patient.id:
                errors[f"{where}.supersedesId"] = "The assertion does not exist for this patient."
                continue
            check_head(None, a.supersedes_id, False, target.is_current)
            check_supersede(ctx, actor, patient, target, a.intent, path)
            targets_add(targets, a.supersedes_id, errors, where)
        prepared.append(PreparedAssertion(a, None, row, medication, date_fields))
    if errors:
        raise Invalid("The input is not correct.", errors)
    target_visit, needs_visit = None, False
    if any(p.entry is not None for p in prepared):
        target_visit, needs_visit = visit_for_new_entries(ctx, actor, patient, visit_id)
    return prepared, target_visit, needs_visit


def targets_add(targets: set[int], target: Optional[int], errors: dict, where: str) -> None:
    if target is None:
        return
    if target in targets:
        errors[f"{where}.supersedesId"] = "Two assertions of the message supersede the same assertion."
    targets.add(target)


def check_supersede(ctx: AppContext, actor: Actor, patient: PatientView, target: AssertionView, intent: str,
                    path: str) -> None:
    reason = supersede_denial(actor.role, target, intent)
    if reason:
        deny(ctx, actor, patient, "create", path, f"{reason} This attempt is in the audit log.")


def visit_for_new_entries(ctx: AppContext, actor: Actor, patient: PatientView,
                          visit_id: Optional[int]) -> tuple[Optional[int], bool]:
    """The visit of new entries: the given visit, else the open visit.

    With no open visit, a staff user gets 422. A patient report makes a virtual visit that ends at once.
    """
    if visit_id is not None:
        visit = ctx.visits.get(visit_id)
        if visit is None or visit.patient_id != patient.id:
            raise Invalid("The visit does not exist for this patient.", {"visitId": "Select a visit of the patient."})
        return visit_id, False
    open_id = ctx.visits.open_visit_id(patient.id)
    if open_id is not None:
        return open_id, False
    if actor.is_patient:
        return None, True
    raise Invalid("The patient has no open visit. Check in a visit first.", {"visitId": "No visit is open."})


def write(ctx: AppContext, actor: Actor, patient: PatientView, prepared: list[PreparedAssertion],
          visit_id: Optional[int], needs_visit: bool, channel: str, text: str, source: str,
          now: str) -> tuple[int, list[int]]:
    """Write one message and its assertions in the open transaction. Return the message id and assertion ids."""
    if needs_visit:
        visit_id = add_report_visit(ctx, patient.id, now)
    staff_id = None if actor.is_patient else actor.staff_id
    origin = "Patient" if actor.is_patient else "Staff"
    message_ident = (ctx.identity.message, ctx.records.next_identifier("Message", ctx.identity.message, "MSG-", 6))
    message_id = ctx.records.add_message(message_ident, staff_id, channel, origin, now, text)
    ids = []
    for seq, p in enumerate(prepared, start=1):
        entry_id = p.entry_id
        if p.entry is not None:
            row = p.entry
            row.visit_id = visit_id
            row.recorded_at = now
            for name in p.date_fields:
                row.details[name] = row.details.get(name) or now
            if p.medication:
                row.medication_id = ctx.records.medication_for(*p.medication)
            entry_ident = (ctx.identity.entry, ctx.records.next_identifier("ClinicalEntry", ctx.identity.entry,
                                                                           "ENTRY-", 6))
            entry_id = ctx.records.add_entry(entry_ident, row)
        a = p.cmd
        ids.append(ctx.records.add_assertion(message_id, seq, entry_id, a.supersedes_id, now, a.intent, source,
                                             a.verification, a.statement.strip()))
    return message_id, ids


def add_report_visit(ctx: AppContext, patient_id: int, now: str) -> int:
    """A virtual visit (class VR) for a patient report with no open visit. It ends at once."""
    found = ctx.directory.location_by_identifier(ctx.identity.location, "VIRTUAL-VISIT")
    location = found.id if found else None
    ident = (ctx.identity.encounter, ctx.visits.next_identifier(ctx.identity.encounter, "ENC-", 6))
    return ctx.visits.create(patient_id, ident, "VR", "Patient report", "Patient report", now, location, end=now)


# ----- new entries -----

def text_value(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def check_time(details: dict, key: str, errors: dict) -> Optional[str]:
    value = text_value(details.get(key))
    if value is None:
        return None
    try:
        parse_time(value)
    except ValueError:
        errors[f"details.{key}"] = "Use an ISO 8601 date or time."
    return value


def new_entry_row(entry: NewEntryCmd, statement: str) -> tuple[NewEntryRow, Optional[tuple[str, str, str]],
                                                               tuple[str, ...]]:
    """Check a new entry. Return its row, the medication (code, system, name) and the date columns to fill."""
    errors: dict[str, str] = {}
    if entry.category not in NEW_ENTRY_CATEGORIES:
        errors["category"] = f"Use one of {', '.join(NEW_ENTRY_CATEGORIES)}."
    for key in ("code", "code_system", "display"):
        if not (getattr(entry, key) or "").strip():
            errors[{"code_system": "codeSystem"}.get(key, key)] = "This value is missing."
    if errors:
        raise Invalid("The new entry is not correct.", errors)
    d = entry.details or {}
    display = entry.display.strip()
    medication = None
    dates: tuple[str, ...] = ()
    if entry.category == "Diagnosis":
        values = {"OnsetDate": check_time(d, "onsetDate", errors),
                  "AbatementDate": check_time(d, "abatementDate", errors),
                  "ClinicalStatus": text_value(d.get("clinicalStatus")) or "active",
                  "Severity": text_value(d.get("severity"))}
        dates = ("OnsetDate",)
    elif entry.category == "Procedure":
        values = {"PerformedDate": check_time(d, "performedDate", errors), "Outcome": text_value(d.get("outcome"))}
        dates = ("PerformedDate",)
    elif entry.category == "Allergy":
        values = {"Substance": text_value(d.get("substance")) or display, "Type": text_value(d.get("type")),
                  "AllergyCategory": text_value(d.get("allergyCategory")),
                  "Criticality": text_value(d.get("criticality")),
                  "ClinicalStatus": text_value(d.get("clinicalStatus")) or "active"}
    elif entry.category == "Observation":
        values = {"Value": text_value(d.get("value")) or text_value(entry.text) or statement.strip(),
                  "Unit": text_value(d.get("unit"))}
    elif entry.category == "LabOrder":
        priority = text_value(d.get("priority")) or "routine"
        if priority not in PRIORITIES:
            errors["details.priority"] = f"Use one of {', '.join(PRIORITIES)}."
        values = {"TestName": text_value(d.get("testName")) or display, "Priority": priority,
                  "Specimen": text_value(d.get("specimen"))}
    elif entry.category == "LabReport":
        values = {"IssuedDate": check_time(d, "issuedDate", errors), "Conclusion": text_value(d.get("conclusion"))}
        dates = ("IssuedDate",)
    else:  # Prescription
        status = text_value(d.get("status")) or "active"
        if status not in PRESCRIPTION_STATUSES:
            errors["details.status"] = f"Use one of {', '.join(PRESCRIPTION_STATUSES)}."
        values = {"Dosage": text_value(d.get("dosage")), "Frequency": text_value(d.get("frequency")),
                  "Status": status}
        medication = (text_value(d.get("medicationCode")) or entry.code.strip(),
                      text_value(d.get("medicationSystem")) or entry.code_system.strip(),
                      text_value(d.get("medicationName")) or display)
    if errors:
        raise Invalid("The new entry is not correct.", errors)
    row = NewEntryRow(visit_id=0, category=entry.category, code=entry.code.strip(),
                      code_system=entry.code_system.strip(), display=display, text=text_value(entry.text),
                      recorded_at="", details=values)
    return row, medication, dates
