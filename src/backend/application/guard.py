"""Access checks about one patient. A denied action writes an audit record (Outcome = Denied), then stops."""
from __future__ import annotations

from domain.access import Actor, allowed, denial_message
from domain.errors import Forbidden, NotFound
from domain.views import PatientView

from application.context import AppContext


def load_patient(ctx: AppContext, patient_id: int) -> PatientView:
    patient = ctx.patients.get(patient_id)
    if patient is None:
        raise NotFound(f"Patient {patient_id} does not exist.")
    return patient


def on_care_team(ctx: AppContext, actor: Actor, patient_id: int) -> bool:
    """True if the user is a member of a current care-team entry of the patient (query Q13)."""
    if actor.role not in ("Nurse", "Doctor"):
        return False
    return ctx.patients.on_care_team(patient_id, actor.system, actor.value)


def subject_of(patient: PatientView) -> tuple[str, str]:
    return (patient.name, patient.date_of_birth)


def deny(ctx: AppContext, actor: Actor, patient: PatientView, audit_action: str, path: str, message: str) -> None:
    """Write the Denied audit record in its own transaction, then raise the 403."""
    with ctx.uow.write() as now:
        ctx.audit.add(now, audit_action, "Denied", actor, subject_of(patient), path)
    raise Forbidden(message)


def require(ctx: AppContext, actor: Actor, patient: PatientView, action: str, audit_action: str, path: str) -> bool:
    """Check the access before any write. Return True if the user is on the care team."""
    is_self = actor.is_self(patient.id)
    team = on_care_team(ctx, actor, patient.id)
    if not allowed(action, actor.role, is_self, team):
        deny(ctx, actor, patient, audit_action, path, denial_message(action, actor.role, is_self))
    return team


def require_role(actor: Actor, action: str) -> None:
    """Check an action that is not about one patient (no audit record)."""
    if not allowed(action, actor.role, False, False):
        raise Forbidden("Your role cannot do this action.")
