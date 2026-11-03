"""Use cases: visits, locations and care teams (doc/api.md section 3.3)."""
from __future__ import annotations

from typing import Optional

from domain.access import Actor
from domain.enums import VISIT_CLASSES
from domain.errors import Conflict, Invalid, NotFound
from domain.views import CareTeamView, VisitView

from application.context import AppContext
from application.guard import load_patient, require, subject_of
from application.ports import NewEntryRow


def load_visit(ctx: AppContext, visit_id: int) -> VisitView:
    visit = ctx.visits.get(visit_id)
    if visit is None:
        raise NotFound(f"Visit {visit_id} does not exist.")
    return visit


def check_location(ctx: AppContext, location_id: int) -> None:
    if ctx.directory.location(location_id) is None:
        raise Invalid("The location does not exist.", {"locationId": f"Location {location_id} does not exist."})


def list_visits(ctx: AppContext, actor: Actor, patient_id: int) -> list[VisitView]:
    patient = load_patient(ctx, patient_id)
    require(ctx, actor, patient, "view_visits", "read", "/api/patients/{patient}/visits")
    return ctx.visits.for_patient(patient_id)


def check_in(ctx: AppContext, actor: Actor, patient_id: int, visit_class: str, reason: Optional[str],
             type_: Optional[str], location_id: int) -> VisitView:
    patient = load_patient(ctx, patient_id)
    path = "/api/patients/{patient}/visits"
    require(ctx, actor, patient, "check_in", "create", path)
    if visit_class not in VISIT_CLASSES:
        raise Invalid("The visit class is not correct.", {"class": f"Use one of {', '.join(VISIT_CLASSES)}."})
    check_location(ctx, location_id)
    if ctx.visits.open_visit_id(patient_id) is not None:
        raise Conflict("The patient has an open visit already. End it first.")
    with ctx.uow.write() as now:
        ident = (ctx.identity.encounter, ctx.visits.next_identifier(ctx.identity.encounter, "ENC-", 6))
        visit_id = ctx.visits.create(patient_id, ident, visit_class, type_ or None, reason or None, now, location_id)
        ctx.audit.add(now, "create", "Allowed", actor, subject_of(patient), path)
    return load_visit(ctx, visit_id)


def move(ctx: AppContext, actor: Actor, visit_id: int, location_id: int) -> VisitView:
    """End the current location of the visit and add the new one."""
    visit = load_visit(ctx, visit_id)
    patient = load_patient(ctx, visit.patient_id)
    path = "/api/visits/{visit}/locations"
    require(ctx, actor, patient, "move_location", "update", path)
    if not visit.is_open:
        raise Invalid("The visit has ended. You cannot move the patient.", {"visitId": "The visit is closed."})
    check_location(ctx, location_id)
    current = next((loc for loc in reversed(visit.locations) if loc.end_date is None), None)
    if current is not None and current.location_id == location_id:
        raise Invalid("The patient is in this location already.", {"locationId": "Select another location."})
    with ctx.uow.write() as now:
        ctx.visits.move(visit_id, location_id, now)
        ctx.audit.add(now, "update", "Allowed", actor, subject_of(patient), path)
    return load_visit(ctx, visit_id)


def end(ctx: AppContext, actor: Actor, visit_id: int) -> VisitView:
    """Set the end time on the visit and on its open location."""
    visit = load_visit(ctx, visit_id)
    patient = load_patient(ctx, visit.patient_id)
    path = "/api/visits/{visit}/end"
    require(ctx, actor, patient, "end_visit", "update", path)
    if not visit.is_open:
        raise Invalid("The visit has ended already.", {"visitId": "The visit is closed."})
    with ctx.uow.write() as now:
        ctx.visits.end(visit_id, now)
        ctx.audit.add(now, "update", "Allowed", actor, subject_of(patient), path)
    return load_visit(ctx, visit_id)


# ----- care teams -----

def care_team_view(ctx: AppContext, visit_id: int) -> CareTeamView:
    chain = ctx.records.care_team_versions(visit_id)
    current = chain[0] if chain and chain[0].is_current else None
    return CareTeamView(visit_id=visit_id, current=current, chain=chain)


def get_care_team(ctx: AppContext, actor: Actor, visit_id: int) -> CareTeamView:
    visit = load_visit(ctx, visit_id)
    patient = load_patient(ctx, visit.patient_id)
    require(ctx, actor, patient, "view_care_team", "read", "/api/visits/{visit}/care-team")
    return care_team_view(ctx, visit_id)


def set_care_team(ctx: AppContext, actor: Actor, visit_id: int, members: list[dict],
                  name: Optional[str]) -> CareTeamView:
    """Make a new CareTeam entry that supersedes the current care team of the visit (one message, one assertion)."""
    visit = load_visit(ctx, visit_id)
    patient = load_patient(ctx, visit.patient_id)
    path = "/api/visits/{visit}/care-team"
    require(ctx, actor, patient, "manage_care_team", "update", path)
    if not members:
        raise Invalid("A care team needs one or more members.", {"members": "Add one or more members."})
    rows, names, errors, seen = [], [], {}, set()
    for index, member in enumerate(members):
        system, value = (member.get("system") or "").strip(), (member.get("value") or "").strip()
        staff = ctx.directory.staff_by_identifier(system, value) if system and value else None
        if staff is None:
            errors[f"members[{index}]"] = f"{system}|{value} is not a staff identifier."
            continue
        if (system, value) in seen:
            continue
        seen.add((system, value))
        rows.append((system, value, member.get("role") or staff.role))
        names.append(staff.name)
    if errors:
        raise Invalid("Each member must be a staff identifier.", errors)
    previous = ctx.records.care_team_versions(visit_id)
    head = previous[0] if previous else None
    team_name = name if name is not None else (head.name if head else None)
    member_text = ", ".join(names)
    with ctx.uow.write() as now:
        entry_ident = (ctx.identity.entry, ctx.records.next_identifier("ClinicalEntry", ctx.identity.entry,
                                                                       "ENTRY-", 6))
        entry_id = ctx.records.add_entry(entry_ident, NewEntryRow(
            visit_id=visit_id, category="CareTeam", code="care-team", code_system=ctx.identity.local_codes,
            display=team_name or "Care team", text=None, recorded_at=now,
            details={"Name": team_name, "Status": "active"}, members=rows))
        message_ident = (ctx.identity.message, ctx.records.next_identifier("Message", ctx.identity.message,
                                                                           "MSG-", 6))
        message_id = ctx.records.add_message(message_ident, actor.staff_id, "InPerson", "Staff", now,
                                             f"Care team change: {member_text}.")
        ctx.records.add_assertion(message_id, 1, entry_id, head.assertion_id if head else None, now, "Report",
                                  "Human", "Confirmed", f"Care team: {member_text}.")
        ctx.audit.add(now, "update", "Allowed", actor, subject_of(patient), path)
    return care_team_view(ctx, visit_id)
