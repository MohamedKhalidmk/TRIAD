"""The audit log on the knowledge graph (the AuditRepository port).

The same results as SqliteAuditRepository (infrastructure/sqlite/chat_repository.py), on the terms of the
ontology (models/semantic/vocabulary.py):

    SQLite                                     knowledge graph
    AuditEvent.IdentifierSystem, ...Value      ?e triad:identifierSystem, triad:identifierValue
    At, Action, Outcome                        ?e triad:at (xsd:dateTime), triad:action, triad:auditOutcome
    ActorRole, ActorSystem, ActorValue         ?e triad:actorRole, triad:actorSystem, triad:actorValue
    SubjectName, SubjectDateOfBirth, Path      ?e triad:subjectName, triad:subjectDateOfBirth (xsd:date), triad:path
    ChatTurnId                                 ?e triad:inTurn ?turn

The rules of the SQLite repository:
- An audit record keeps the user and the patient (the subject) as values, not as links. AuditEvent is
  append-only: the guard delete.allow-list (guards.py) refuses a change or a delete.
- add() writes one new individual: one INSERT DATA at the commit. The denial audit (application/guard.deny)
  opens its own write, so a 403 writes exactly one audit record in its own INSERT DATA (plan 5.3).
- The identifier value is the next AUDIT-nnnn (ids.next_identifier also looks in the write buffer).
- The actor name is the name of the staff member with the identifier (actorSystem, actorValue), else the name
  of the patient with that identifier.
- for_subject(): the newest record first (the instant of `at`, then the largest id). Python makes this order,
  so it is the same on each store: Virtuoso orders xsd:dateTime by the text (D11), and the records of the app
  can have another offset than the scenario records (the offset of the clock). One query gives the (record, at)
  pairs of the subject; Python sorts them and cuts the page; a second query reads the page.
"""
from __future__ import annotations

from typing import Optional

from domain.access import Actor
from domain.views import AuditEventView

from application.paging import Page, PageRequest
from infrastructure.config import AUDIT_EVENT_SYSTEM
from infrastructure.sparql import ids, terms
from infrastructure.sparql.terms import id_of, iri
from infrastructure.sparql.unit_of_work import KgSession
from infrastructure.sparql.visits_repository import iri_list, newest_first, page_slice

# The records of one subject (the name and the date of birth of a patient).
EVENTS_OF_SUBJECT = """
SELECT ?e ?at FROM $abox WHERE {
  ?e triad:subjectName $name ; triad:subjectDateOfBirth $dob ; a triad:AuditEvent ; triad:at ?at .
}"""

DENIED_COUNT = """
SELECT (COUNT(?e) AS ?n) FROM $abox WHERE {
  ?e triad:subjectName $name ; triad:subjectDateOfBirth $dob ; a triad:AuditEvent ; triad:auditOutcome ?outcome .
  FILTER (?outcome = "Denied")
}"""

# The page: the values of the records.
EVENTS = """
SELECT ?e ?value ?at ?action ?outcome ?role ?actorSystem ?actorValue ?path ?turn FROM $abox WHERE {
  VALUES ?e { $events }
  ?e triad:identifierValue ?value ; triad:at ?at ; triad:action ?action ; triad:auditOutcome ?outcome ;
     triad:actorRole ?role ; triad:actorSystem ?actorSystem ; triad:actorValue ?actorValue ; triad:path ?path .
  OPTIONAL { ?e triad:inTurn ?turn }
}"""

# The name of one actor (?n is its place in the list): a staff member, or the patient of a patient identifier.
# The value is a constant of the pattern ($value<n>): an identifier value is selective, so the store starts there.
# (Measured on the full graph, Oxigraph: 0.2 ms; an OPTIONAL that joins ?actorValue of the records takes 10 ms.)
# The system filter compares STR(?system): with "?system = $system<n>" in a UNION branch with these OPTIONALs,
# Virtuoso 7.2 stops with "SP031: SPARQL compiler: Internal error: sparp_gp_deprecate(): equiv replaces filter but
# under deprecation" (it puts the constant in place of the variable, and then cannot keep the FILTER).
ACTOR_NAME = """
  {{ ?x triad:identifierValue $value{n} ; triad:identifierSystem ?system .
    FILTER (STR(?system) = $system{n})
    OPTIONAL {{ ?x a ?staffType ; triad:name ?staffName . FILTER (?staffType = triad:Staff) }}
    OPTIONAL {{ ?x a ?identifierType . FILTER (?identifierType = triad:PatientIdentifier)
               ?patient triad:identifier ?x ; triad:name ?patientName . }}
    BIND ({n} AS ?n) }}"""


def actor_names_query(count: int) -> str:
    """The names of `count` actors: one UNION branch for each (bindings $system<n>, $value<n>)."""
    return ("SELECT ?n ?staffName ?patientName FROM $abox WHERE {"
            + "\n  UNION".join(ACTOR_NAME.format(n=n) for n in range(count)) + "\n}")


def subject_bindings(subject: tuple[str, str]) -> dict:
    name, date_of_birth = subject
    return {"name": name, "dob": terms.date(date_of_birth)}


class SparqlAuditRepository:
    """The AuditRepository port on SPARQL."""

    def __init__(self, session: KgSession):
        self.session = session

    def add(self, at: str, action: str, outcome: str, actor: Actor, subject: tuple[str, str], path: str,
            chat_turn_id: Optional[int] = None) -> int:
        buf = self.session.write_buffer()
        value = ids.next_identifier(self.session, "audit-event", AUDIT_EVENT_SYSTEM, "AUDIT-", 4)
        name, date_of_birth = subject
        return buf.create("audit-event", {
            "identifierSystem": AUDIT_EVENT_SYSTEM, "identifierValue": value, "at": at, "action": action,
            "auditOutcome": outcome, "actorRole": actor.role, "actorSystem": actor.system, "actorValue": actor.value,
            "subjectName": name, "subjectDateOfBirth": date_of_birth, "path": path,
            "inTurn": iri("chat-turn", chat_turn_id) if chat_turn_id is not None else None})

    def _views(self, event_iris: list[str]) -> list[AuditEventView]:
        if not event_iris:
            return []
        rows = {r["e"]: r for r in self.session.select(EVENTS, {"events": iri_list(event_iris)})}
        names = self._actor_names(sorted({(r["actorSystem"], r["actorValue"]) for r in rows.values()}))
        out = []
        for e in event_iris:
            r = rows.get(e)
            if r is None:
                continue
            out.append(AuditEventView(id=id_of(e, "audit-event"), identifier=r["value"], at=r["at"],
                                      action=r["action"], outcome=r["outcome"], actor_role=r["role"],
                                      actor_key=f"{r['role']}:{r['actorValue']}",
                                      actor_name=names.get((r["actorSystem"], r["actorValue"])),
                                      path=r["path"], chat_turn_id=id_of(r["turn"], "chat-turn")))
        return out

    def _actor_names(self, actors: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
        """(system, value) -> the name of the staff member with this identifier, else the name of the patient
        (SQLite: COALESCE(Staff.Name, the name of the patient of the PatientIdentifier))."""
        if not actors:
            return {}
        bindings = {}
        for n, (system, value) in enumerate(actors):
            bindings[f"system{n}"], bindings[f"value{n}"] = system, value
        staff: dict[int, str] = {}
        patients: dict[int, str] = {}
        for r in self.session.select(actor_names_query(len(actors)), bindings):
            if r["staffName"] is not None:
                staff[r["n"]] = r["staffName"]
            if r["patientName"] is not None:
                patients.setdefault(r["n"], r["patientName"])
        return {actor: staff.get(n, patients.get(n)) for n, actor in enumerate(actors)
                if staff.get(n, patients.get(n)) is not None}

    def for_subject(self, subject: tuple[str, str], page: PageRequest) -> Page[AuditEventView]:
        """One page of the audit records of the patient, newest first."""
        rows = self.session.select(EVENTS_OF_SUBJECT, subject_bindings(subject))
        events = [r["e"] for r in newest_first(rows, lambda r: r["at"], lambda r: id_of(r["e"], "audit-event"))]
        return Page(items=self._views(page_slice(events, page)), total=len(events), limit=page.limit,
                    offset=page.offset)

    def denied_count(self, subject: tuple[str, str]) -> int:
        """The number of Denied records of the patient (all pages)."""
        rows = self.session.select(DENIED_COUNT, subject_bindings(subject))
        return int(rows[0]["n"]) if rows and rows[0].get("n") is not None else 0
