"""Use case: the audit log of one patient (doc/api.md section 3.6)."""
from __future__ import annotations

from dataclasses import dataclass

from domain.access import Actor
from domain.views import AuditEventView

from application.context import AppContext
from application.guard import load_patient, require, subject_of
from application.paging import Page, PageRequest


@dataclass
class AuditPage(Page[AuditEventView]):
    denied: int                  # the number of Denied records of the patient, on all pages


def patient_audit(ctx: AppContext, actor: Actor, patient_id: int, page: PageRequest = PageRequest()) -> AuditPage:
    """One page of the audit records of the patient, newest first. The read itself is the first record."""
    patient = load_patient(ctx, patient_id)
    path = "/api/patients/{patient}/audit"
    require(ctx, actor, patient, "view_audit", "read", path)
    with ctx.uow.write() as now:
        ctx.audit.add(now, "read", "Allowed", actor, subject_of(patient), path)
    found = ctx.audit.for_subject(subject_of(patient), page)
    return AuditPage(items=found.items, total=found.total, limit=found.limit, offset=found.offset,
                     denied=ctx.audit.denied_count(subject_of(patient)))
