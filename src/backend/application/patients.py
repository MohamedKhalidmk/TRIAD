"""Use cases: find, register, read, change and delete patients (doc/api.md section 3.2)."""
from __future__ import annotations

from datetime import date
from typing import Optional

from domain.access import Actor, permissions
from domain.errors import Conflict, Invalid
from domain.records import Address
from domain.views import PatientSummary, PatientView

from application.context import AppContext
from application.guard import load_patient, on_care_team, require, require_role, subject_of
from application.paging import Page, PageRequest, page_of

SEXES = ("female", "male", "other", "unknown")
SCOPES = ("all", "care-team", "open-visits")
ADDRESS_FIELDS = ("street", "city", "region", "postal_code", "country")


def check_date(value: str, field: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise Invalid("The date is not correct.", {field: "Use the format YYYY-MM-DD."})


def with_permissions(ctx: AppContext, actor: Actor, patient: PatientView) -> PatientView:
    patient.permissions = permissions(actor.role, actor.is_self(patient.id), on_care_team(ctx, actor, patient.id))
    return patient


def search(ctx: AppContext, actor: Actor, q: Optional[str], dob: Optional[str], scope: str,
           page: PageRequest = PageRequest()) -> Page[PatientSummary]:
    """One page of the patients, by name. A patient gets self only."""
    if scope not in SCOPES:
        raise Invalid("The scope is not correct.", {"scope": "Use all, care-team or open-visits."})
    if actor.is_patient:
        own = ctx.patients.get(actor.patient_id)
        return page_of([PatientSummary(own.id, own.name, own.date_of_birth, own.sex, own.phone_number,
                                       own.open_visit_id)] if own else [], page)
    if dob:
        dob = check_date(dob, "dob")
    member = (actor.system, actor.value) if scope == "care-team" else None
    if scope == "care-team" and actor.role not in ("Nurse", "Doctor"):
        return page_of([], page)
    return ctx.patients.search((q or "").strip() or None, dob or None, scope, member, page)


def get(ctx: AppContext, actor: Actor, patient_id: int) -> PatientView:
    patient = load_patient(ctx, patient_id)
    require(ctx, actor, patient, "read_patient", "read", "/api/patients/{patient}")
    return with_permissions(ctx, actor, patient)


def clean_address(address: Optional[dict]) -> Address:
    address = address or {}
    return Address(**{k: (address.get(k) or None) for k in ADDRESS_FIELDS})


def register(ctx: AppContext, actor: Actor, name: str, date_of_birth: str, sex: str, phone: Optional[str],
             address: Optional[dict]) -> PatientView:
    require_role(actor, "register_patient")
    name = (name or "").strip()
    if not name:
        raise Invalid("The name is missing.", {"name": "Give the name of the patient."})
    date_of_birth = check_date(date_of_birth, "dateOfBirth")
    if sex not in SEXES:
        raise Invalid("The sex is not correct.", {"sex": "Use female, male, other or unknown."})
    if ctx.patients.key_exists(name, date_of_birth):
        raise Conflict("A patient with this name and date of birth exists already.",
                       {"name": "This name and date of birth are in use."})
    with ctx.uow.write() as now:
        mrn = ctx.patients.next_identifier(ctx.identity.mrn, "MRN-", 6)
        patient_id = ctx.patients.create(name, date_of_birth, sex, phone or None, clean_address(address),
                                         [(ctx.identity.mrn, mrn)])
        ctx.audit.add(now, "create", "Allowed", actor, (name, date_of_birth), "/api/patients")
    return with_permissions(ctx, actor, load_patient(ctx, patient_id))


def change(ctx: AppContext, actor: Actor, patient_id: int, changes: dict) -> PatientView:
    """Change sex, phone number or address. The name and the date of birth cannot change."""
    patient = load_patient(ctx, patient_id)
    require(ctx, actor, patient, "edit_demographics", "update", "/api/patients/{patient}")
    errors = {}
    if "name" in changes and (changes["name"] or "").strip() != patient.name:
        errors["name"] = "The name cannot change."
    if "date_of_birth" in changes and changes["date_of_birth"] != patient.date_of_birth:
        errors["dateOfBirth"] = "The date of birth cannot change."
    if "sex" in changes and changes["sex"] not in SEXES:
        errors["sex"] = "Use female, male, other or unknown."
    if errors:
        raise Invalid("The name and the date of birth of a patient cannot change.", errors)
    values = {}
    if "sex" in changes:
        values["Sex"] = changes["sex"]
    if "phone_number" in changes:
        values["PhoneNumber"] = changes["phone_number"] or None
    if changes.get("address") is not None:
        current = patient.address
        given = changes["address"]
        for key, column in zip(ADDRESS_FIELDS, ("Street", "City", "Region", "PostalCode", "Country")):
            values[column] = (given[key] or None) if key in given else getattr(current, key)
    with ctx.uow.write() as now:
        if values:
            ctx.patients.update(patient_id, values)
        ctx.audit.add(now, "update", "Allowed", actor, subject_of(patient), "/api/patients/{patient}")
    return with_permissions(ctx, actor, load_patient(ctx, patient_id))


def delete(ctx: AppContext, actor: Actor, patient_id: int) -> None:
    patient = load_patient(ctx, patient_id)
    require(ctx, actor, patient, "delete_patient", "delete", "/api/patients/{patient}")
    if ctx.patients.has_visits(patient_id):
        raise Conflict("The patient has visits. You cannot delete the patient.")
    with ctx.uow.write() as now:
        ctx.patients.delete(patient_id)
        ctx.audit.add(now, "delete", "Allowed", actor, subject_of(patient), "/api/patients/{patient}")
