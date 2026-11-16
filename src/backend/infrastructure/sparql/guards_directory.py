"""The key guards (agent D): the UNIQUE constraints of SQLite, as Conflict (409) in the knowledge graph.

`owl:hasKey` infers owl:sameAs and gives no error (plan 1.5), so the app holds each key. A key guard looks at the
new subjects and the replaced values of a change, and finds a duplicate with one SELECT on the stored facts (and
in the change itself: two new rows with the same key). Error: unique_conflict(table, columns), the same text and
`fields.key` as SQLite, for example unique_conflict("Medication", ("Code", "CodeSystem")) gives
{"key": "Medication.Code, Medication.CodeSystem"}.

STUB: agent D writes the bodies. Each guard is registered already, so the unit of work runs it at each commit
that touches its kinds. A stub body does nothing. Two of these keys only the database enforces today (the
Medication key and the client-given identifiers): test_api.py expects 409 for them.

Do not edit guards.py: add a guard here with @register(..., owner="D").
"""
from __future__ import annotations

from infrastructure.sparql.change import Change
from infrastructure.sparql.guards import Facts, register


@register("key.medication", kinds=("medication",), owner="D")
def medication_key(change: Change, facts: Facts) -> None:
    """UK_Medication_Code_CodeSystem: (code, codeSystem). unique_conflict("Medication", ("Code", "CodeSystem"))."""


@register("key.identifier", kinds=("department", "location", "staff", "visit", "clinical-entry", "message",
                                   "chat-session", "audit-event", "patient-identifier"), owner="D")
def identifier_key(change: Change, facts: Facts) -> None:
    """UK_<Table>_Identifier: (identifierSystem, identifierValue) of each kind of the list. The client gives the
    identifiers of a department, a location and a staff member; the app makes the others (ids.next_identifier).
    The table of a kind is ids.KIND_TABLE[kind]; PatientIdentifier has the columns (System, Value)."""


@register("key.patient", kinds=("patient",), owner="D")
def patient_key(change: Change, facts: Facts) -> None:
    """UK_Patient_Name_DateOfBirth: (name, dateOfBirth). unique_conflict("Patient", ("Name", "DateOfBirth"))."""


@register("key.assertion", kinds=("assertion",), owner="D")
def assertion_keys(change: Change, facts: Facts) -> None:
    """UK_Assertion_SupersedesId (one new assertion for each old one) and UK_Assertion_MessageId_Seq
    (message, seq)."""


@register("key.chat-turn", kinds=("chat-turn",), owner="D")
def chat_turn_keys(change: Change, facts: Facts) -> None:
    """The keys of ChatTurn: (session, seq) and (session, clientTurnId)."""


@register("key.association", kinds=("works-in", "visit-location", "citation", "care-team-member"), owner="D")
def association_keys(change: Change, facts: Facts) -> None:
    """The keys of the association classes: WorksIn (staff, department, roleCode), VisitLocation (visit,
    location, startDate), Citation (turn, assertion), CareTeamMember (care team, memberSystem, memberValue);
    and StaffLanguage (staff, language) for triad:language."""
