"""The citation and audit guards (agent C): the rules of the Citation and AuditEvent triggers of SQLite.

The unit of work runs each guard at the commit, under the write lock, on the buffered change (guards.py). The
rows of a rule can be new in the same change: a "tell" turn writes the reply turn, its citations, the new
assertions, their entries (and a new report visit) and the audit record in one write. So the guards first read
the change, and read only the stored rest with one SELECT for each kind of start (see Subjects below):

    citation  --byTurn-->  turn  <--includes--  session (subjectName, subjectDateOfBirth)
    citation  --citedAssertion-->  assertion --about--> entry --during--> visit <--hasVisit-- patient
    audit event  --inTurn-->  turn  <--includes--  session

(The append-only rule of AuditEvent is in guards.py already: the guard delete.allow-list.)
A turn or an assertion that does not exist is a foreign-key error first (the guard foreign-keys of guards.py:
Conflict 409). SQLite runs its triggers before the foreign-key check, so it gives the text of the trigger.
No use case can write such a row.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from infrastructure.sparql.change import Change
from infrastructure.sparql import terms
from infrastructure.sparql.guards import Facts, register, trigger_failed
from infrastructure.sparql.terms import Term, kind_of

ASSISTANT_ONLY = "Only an assistant turn can cite an assertion."
NOT_THE_PATIENT = "The cited assertion is not about the patient of the chat session."
NOT_THE_SUBJECT = "The audit subject is not the patient of the chat session."

# The stored turns: the speaker and the subject of the session.
STORED_TURNS = """
SELECT ?x ?speaker ?name ?dob FROM $abox WHERE {
  VALUES ?x { $nodes }
  ?x triad:speaker ?speaker .
  OPTIONAL { ?session triad:includes ?x ; triad:subjectName ?name ; triad:subjectDateOfBirth ?dob . }
}"""

STORED_SESSIONS = """
SELECT ?x ?name ?dob FROM $abox WHERE {
  VALUES ?x { $nodes }
  ?x triad:subjectName ?name ; triad:subjectDateOfBirth ?dob .
}"""

# The patient (name, date of birth) of a stored assertion, entry, visit or patient.
UP_TO_PATIENT = {
    "assertion": "?x triad:about ?entry . ?entry triad:during ?visit . ?p triad:hasVisit ?visit .",
    "clinical-entry": "?x triad:during ?visit . ?p triad:hasVisit ?visit .",
    "visit": "?p triad:hasVisit ?x .",
}
STORED_PATIENTS = """
SELECT ?x ?name ?dob FROM $abox WHERE {{
  VALUES ?x {{ $nodes }}
  {path}
  {patient} triad:name ?name ; triad:dateOfBirth ?dob .
}}"""


def node_list(nodes: Iterable[Term]) -> Term:
    """The IRIs for a VALUES block, each one made again from its kind and id (only TRIAD individuals go in)."""
    return Term(" ".join(sorted({terms.iri(*terms.split_iri(n)) for n in nodes})))


def same_day(a: Any, b: Any) -> bool:
    """A date of birth of the change (text) and of the store (the text of the xsd:date) are the same date."""
    return a is not None and b is not None and str(a).strip() == str(b).strip()


class Subjects:
    """The facts of the two rules: the speaker of a turn, the subject of the session of a turn, and the patient of
    an assertion. Each value comes from the change first, else from the store (one SELECT for each kind)."""

    def __init__(self, change: Change, facts: Facts):
        self.change = change
        self.facts = facts

    # ----- the turns and their sessions -----

    def turns(self, turns: Iterable[Term]) -> dict[Term, tuple[Optional[str], Optional[tuple]]]:
        """turn -> (speaker, (subjectName, subjectDateOfBirth) of its session, or None)."""
        out: dict[Term, tuple[Optional[str], Optional[tuple]]] = {}
        stored_turns, sessions = set(), {}
        for turn in set(turns):
            new = self.change.new_subject(turn)
            if new is None:
                stored_turns.add(turn)
                continue
            links = self.change.links_to(turn, "includes")
            sessions[turn] = links[0][0] if links else None
            out[turn] = (new.get("speaker"), None)
        if stored_turns:
            for r in self.facts.select(STORED_TURNS, {"nodes": node_list(stored_turns)}):
                out[Term(f"<{r['x']}>")] = (r["speaker"], (r["name"], r["dob"]) if r["name"] is not None else None)
        stored_sessions = set()
        for turn, session in sessions.items():
            if session is None:
                continue
            new = self.change.new_subject(session)
            if new is not None:
                out[turn] = (out[turn][0], (new.get("subjectName"), new.get("subjectDateOfBirth")))
            else:
                stored_sessions.add(session)
        if stored_sessions:
            subjects = {Term(f"<{r['x']}>"): (r["name"], r["dob"])
                        for r in self.facts.select(STORED_SESSIONS, {"nodes": node_list(stored_sessions)})}
            for turn, session in sessions.items():
                if session in subjects:
                    out[turn] = (out[turn][0], subjects[session])
        return out

    # ----- the patient of an assertion -----

    def _step(self, node: Term) -> tuple[Optional[Term], Optional[tuple]]:
        """For a new node: (the next node up, None), or (None, (name, dateOfBirth)) for a new patient."""
        new = self.change.new_subject(node)
        kind = kind_of(node)
        if kind == "patient":
            return None, (new.get("name"), new.get("dateOfBirth"))
        if kind == "assertion":
            return new.get("about"), None
        if kind == "clinical-entry":
            return new.get("during"), None
        links = self.change.links_to(node, "hasVisit")      # a visit: <patient> triad:hasVisit <visit>
        return (links[0][0] if links else None), None

    def patients(self, assertions: Iterable[Term]) -> dict[Term, Optional[tuple]]:
        """assertion -> (name, dateOfBirth) of its patient, or None."""
        out: dict[Term, Optional[tuple]] = {}
        start: dict[Term, Term] = {}                        # assertion -> the first stored node up its path
        for assertion in set(assertions):
            node: Optional[Term] = assertion
            out[assertion] = None
            while node is not None and self.change.is_new(node):
                node, found = self._step(node)
                if found is not None:
                    out[assertion] = found
            if node is not None:
                start[assertion] = node
        by_kind: dict[str, set[Term]] = {}
        for node in start.values():
            by_kind.setdefault(kind_of(node), set()).add(node)
        stored: dict[Term, tuple] = {}
        for kind, nodes in sorted(by_kind.items()):
            if kind not in UP_TO_PATIENT and kind != "patient":
                continue
            template = STORED_PATIENTS.format(path=UP_TO_PATIENT.get(kind, ""),
                                              patient="?x" if kind == "patient" else "?p")
            for r in self.facts.select(template, {"nodes": node_list(nodes)}):
                stored[Term(f"<{r['x']}>")] = (r["name"], r["dob"])
        for assertion, node in start.items():
            out[assertion] = stored.get(node)
        return out


def matches(patient: Optional[tuple], subject: Optional[tuple]) -> bool:
    """The patient (name, date of birth) is the subject (subjectName, subjectDateOfBirth) of the session."""
    return (patient is not None and subject is not None and patient[0] == subject[0]
            and same_day(patient[1], subject[1]))


@register("citation.check", kinds=("citation",), owner="C")
def citation_check(change: Change, facts: Facts) -> None:
    """SQLite: TR_Citation_Check. For a new citation (triad:byTurn, triad:citedAssertion):

    - the turn is an assistant turn: trigger_failed("Only an assistant turn can cite an assertion.");
    - the cited assertion is about the patient of the session of the turn (the patient name and date of birth
      equal subjectName and subjectDateOfBirth of the session):
      trigger_failed("The cited assertion is not about the patient of the chat session.").
    The turn can be new in the same change (a reply turn and its citations are written together).
    The citations are checked in the order of their ids (SQLite checks each row of the INSERT in order).
    """
    citations = sorted(change.created("citation"), key=lambda c: c.id)
    if not citations:
        return
    subjects = Subjects(change, facts)
    turns = subjects.turns(c.get("byTurn") for c in citations if c.get("byTurn") is not None)
    patients = subjects.patients(c.get("citedAssertion") for c in citations if c.get("citedAssertion") is not None)
    for citation in citations:
        speaker, subject = turns.get(citation.get("byTurn"), (None, None))
        if speaker is not None and speaker != "Assistant":     # SQLite: NULL <> 'Assistant' is not true
            raise trigger_failed(ASSISTANT_ONLY)
        if not matches(patients.get(citation.get("citedAssertion")), subject):
            raise trigger_failed(NOT_THE_PATIENT)


@register("audit-event.subject-check", kinds=("audit-event",), owner="C")
def audit_subject_check(change: Change, facts: Facts) -> None:
    """SQLite: TR_AuditEvent_Subject_Check. An audit record of a chat turn (triad:inTurn) has the patient of the
    session of that turn (subjectName and subjectDateOfBirth are the same).

    Error: trigger_failed("The audit subject is not the patient of the chat session.").
    An audit record with no turn (nearly all of them) needs no read.
    """
    events = sorted((e for e in change.created("audit-event") if e.get("inTurn") is not None), key=lambda e: e.id)
    if not events:
        return
    turns = Subjects(change, facts).turns(e.get("inTurn") for e in events)
    for event in events:
        _, subject = turns.get(event.get("inTurn"), (None, None))
        if not matches((event.get("subjectName"), event.get("subjectDateOfBirth")), subject):
            raise trigger_failed(NOT_THE_SUBJECT)
