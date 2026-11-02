"""Use case: the audit log of one patient (doc/api.md section 3.6)."""
from __future__ import annotations

from domain.access import Actor
from domain.views import AuditEventView

from application.context import AppContext
from application.guard import load_patient, require, subject_of


def patient_audit(ctx: AppContext, actor: Actor, patient_id: int) -> list[AuditEventView]:
    """The audit records of the patient, newest first. The read itself is the first record."""
    patient = load_patient(ctx, patient_id)
    path = "/api/patients/{patient}/audit"
    require(ctx, actor, patient, "view_audit", "read", path)
    with ctx.uow.write() as now:
        ctx.audit.add(now, "read", "Allowed", actor, subject_of(patient), path)
    return ctx.audit.for_subject(subject_of(patient))
