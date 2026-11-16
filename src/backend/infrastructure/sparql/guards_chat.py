"""The citation and audit guards (agent C): the rules of the Citation and AuditEvent triggers of SQLite.

STUB: agent C writes the bodies. Each guard is registered already (guards.register), so the unit of work runs it
at each commit that touches its kinds. A stub body does nothing. Each docstring gives the SQLite rule and the
exact error. See guards.py and README.md. (The append-only rule of AuditEvent is in guards.py already.)

Do not edit guards.py: add a guard here with @register(..., owner="C").
"""
from __future__ import annotations

from infrastructure.sparql.change import Change
from infrastructure.sparql.guards import Facts, register


@register("citation.check", kinds=("citation",), owner="C")
def citation_check(change: Change, facts: Facts) -> None:
    """SQLite: TR_Citation_Check. For a new citation (triad:byTurn, triad:citedAssertion):

    - the turn is an assistant turn: trigger_failed("Only an assistant turn can cite an assertion.");
    - the cited assertion is about the patient of the session of the turn (the patient name and date of birth
      equal subjectName and subjectDateOfBirth of the session):
      trigger_failed("The cited assertion is not about the patient of the chat session.").
    The turn can be new in the same change (a reply turn and its citations are written together).
    """


@register("audit-event.subject-check", kinds=("audit-event",), owner="C")
def audit_subject_check(change: Change, facts: Facts) -> None:
    """SQLite: TR_AuditEvent_Subject_Check. An audit record of a chat turn (triad:inTurn) has the patient of the
    session of that turn (subjectName and subjectDateOfBirth are the same).

    Error: trigger_failed("The audit subject is not the patient of the chat session.").
    """
