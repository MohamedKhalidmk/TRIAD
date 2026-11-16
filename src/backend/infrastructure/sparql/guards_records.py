"""The assertion guards (agent B): the rules of the Assertion and CareTeamMember triggers of SQLite.

Each guard runs at the commit of a unit of work, under the write lock, on the buffered change (guards.py). It reads
stored facts with one SELECT (facts.select) and the new subjects of the change with change.created(...). It raises
the same exception class and text as SQLite, so the API gives the same status and code (plan 1.7).

SQLite checks the rows one at a time, in the order of the inserts. The buffer gives the new ids in the order of
its create() calls, which is the order of the SQLite inserts. So each guard checks the new rows in the order of
their ids, and a row sees the stored rows and the new rows before it (as a BEFORE INSERT trigger does).

The order of the guards in this file is the order in which SQLite checks one row: the CareTeamMember trigger
(the members are inserted before the assertion), then the BEFORE INSERT triggers of Assertion (SQLite runs the
last one made first: one patient per message, one head per entry, the supersede check), then the CHECK
constraint (not itself). The guards of agent A (the foreign keys) run before these, and the key guards of agent D
(UNIQUE, for example one new assertion for each old one) after them.

Do not edit guards.py: add a guard here with @register(..., owner="B").
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from domain.rules import parse_time

from infrastructure.sparql import fragments, terms
from infrastructure.sparql.change import Change, NewSubject
from infrastructure.sparql.guards import Facts, check_failed, foreign_key_conflict, register, trigger_failed
from infrastructure.sparql.terms import Term


def _key(value: str) -> Term:
    """An IRI in the form of the change (with the angle brackets)."""
    return Term(value if value.startswith("<") else f"<{value}>")


def _iris(values: Iterable[str]) -> Term:
    return Term(" ".join(sorted({_key(v) for v in values})))


def _new_assertions(change: Change) -> list[NewSubject]:
    """The new assertions, in the order of the SQLite inserts (their ids)."""
    return sorted(change.created("assertion"), key=lambda s: s.id)


def _message_of(change: Change, assertion: Term) -> Optional[Term]:
    """The message that contains the assertion (Contains: <message> triad:contains <assertion>)."""
    found = [subject for subject, _ in change.links_to(assertion, "contains")]
    return _key(found[0]) if found else None


class _Patients:
    """The patient (and the time) of assertions, and the patient of entries and visits: from the change first,
    then from the stored facts.

    A new entry can be in a new visit of a stored patient (<patient> triad:hasVisit <visit> is an added triple),
    so each step looks in the change first. load() reads the stored links of all IRIs that need them with one
    SELECT.
    """

    STORED = """
SELECT ?x ?at ?e ?v ?p FROM $abox WHERE {
  $parts
}"""
    PARTS = {
        "assertions": "{ VALUES ?x { $assertions } ?x triad:assertedAt ?at ; triad:about ?e . ?e triad:during ?v . "
                      "OPTIONAL { ?p triad:hasVisit ?v } }",
        "entries": "{ VALUES ?e { $entries } ?e triad:during ?v . OPTIONAL { ?p triad:hasVisit ?v } }",
        "visits": "{ VALUES ?v { $visits } ?p triad:hasVisit ?v }",
    }

    def __init__(self, change: Change, facts: Facts):
        self.change, self.facts = change, facts
        self.time_of_assertion: dict[Term, str] = {}
        self.entry_of_assertion: dict[Term, Term] = {}
        self.visit_of_entry: dict[Term, Term] = {}
        self.patient_of_stored_visit: dict[Term, Term] = {}

    def entry_of(self, assertion: Term) -> Optional[Term]:
        new = self.change.new_subject(assertion)
        if new is not None:
            value = new.get("about")
            return _key(value) if value else None
        return self.entry_of_assertion.get(_key(assertion))

    def visit_of(self, entry: Optional[Term]) -> Optional[Term]:
        if entry is None:
            return None
        new = self.change.new_subject(entry)
        if new is not None:
            value = new.get("during")
            return _key(value) if value else None
        return self.visit_of_entry.get(_key(entry))

    def patient_of_visit(self, visit: Optional[Term]) -> Optional[Term]:
        if visit is None:
            return None
        found = [subject for subject, _ in self.change.links_to(visit, "hasVisit")]
        if found:
            return _key(found[0])
        return self.patient_of_stored_visit.get(_key(visit))

    def patient_of(self, assertion: Term) -> Optional[Term]:
        return self.patient_of_visit(self.visit_of(self.entry_of(assertion)))

    def time_of(self, assertion: Term) -> Optional[str]:
        new = self.change.new_subject(assertion)
        return new.get("assertedAt") if new is not None else self.time_of_assertion.get(_key(assertion))

    def load(self, assertions: Iterable[str]) -> "_Patients":
        """Read the stored links that the patients of these assertions need (one SELECT, or none)."""
        wanted = {_key(a) for a in assertions}
        stored_assertions = sorted(a for a in wanted if not self.change.is_new(a))
        entries = {self.entry_of(a) for a in wanted if self.change.is_new(a)} - {None}
        stored_entries = sorted(e for e in entries if not self.change.is_new(e))
        visits = {self.visit_of(e) for e in entries if self.change.is_new(e)} - {None}
        stored_visits = sorted(v for v in visits if not self.change.is_new(v)
                               and not self.change.links_to(v, "hasVisit"))
        lists = {"assertions": stored_assertions, "entries": stored_entries, "visits": stored_visits}
        parts = [self.PARTS[name] for name, items in lists.items() if items]
        if not parts:
            return self
        text = self.STORED.replace("$parts", "\n  UNION\n  ".join(parts))
        bindings = {name: _iris(items) for name, items in lists.items() if items}
        for row in self.facts.select(text, bindings):
            x, e, v, p = (_key(row[k]) if row.get(k) else None for k in ("x", "e", "v", "p"))
            if x and e:
                self.entry_of_assertion[x] = e
                self.time_of_assertion[x] = row.get("at")
            if e and v:
                self.visit_of_entry[e] = v
            if v and p:
                self.patient_of_stored_visit[v] = p
        return self


# ---------------------------------------------------------------------------------------------
# CareTeamMember

STAFF_IDENTIFIERS = """
SELECT ?s ?system ?value FROM $abox WHERE {
  VALUES ?value { $values }
  ?s triad:identifierValue ?value ; triad:identifierSystem ?system ; a ?class .
  FILTER (?class = triad:Staff)
}"""


@register("care-team-member.is-staff", kinds=("care-team-member",), owner="B")
def care_team_member_is_staff(change: Change, facts: Facts) -> None:
    """SQLite: TR_CareTeamMember_Staff_Check. (memberSystem, memberValue) is the identifier of a staff member.

    Error: trigger_failed("The care-team member is not a staff member.").
    A staff member counts if it is stored (and the change does not delete it) or new in the change.
    """
    members = sorted(change.created("care-team-member"), key=lambda s: s.id)
    if not members:
        return
    error = trigger_failed("The care-team member is not a staff member.")
    pairs = [(m.get("memberSystem"), m.get("memberValue")) for m in members]
    if any(system is None or value is None for system, value in pairs):
        raise error
    staff = {(s.get("identifierSystem"), s.get("identifierValue")) for s in change.created("staff")}
    values = Term(" ".join(terms.literal(value) for value in sorted({value for _, value in pairs})))
    rows = facts.select(STAFF_IDENTIFIERS, {"values": values})
    staff |= {(r["system"], r["value"]) for r in rows if not change.is_deleted(r["s"])}
    if any(pair not in staff for pair in pairs):
        raise error


# ---------------------------------------------------------------------------------------------
# Assertion

MESSAGE_PATIENTS = """
SELECT ?m ?p FROM $abox WHERE {
  VALUES ?m { $messages }
  ?m triad:contains ?x .
  ?x triad:about ?e .
  ?e triad:during ?v .
  ?p triad:hasVisit ?v .
}"""


@register("assertion.one-patient-per-message", kinds=("assertion", "message"), owner="B")
def one_patient_per_message(change: Change, facts: Facts) -> None:
    """SQLite: TR_Assertion_One_Patient_Per_Message. All assertions of a message are about one patient.

    Error: trigger_failed("All assertions of a message must be about one patient.").
    A new assertion sees the stored assertions of its message and the new ones before it.
    """
    new = _new_assertions(change)
    if not new:
        return
    messages = {a.iri: _message_of(change, a.iri) for a in new}
    patients = _Patients(change, facts).load([a.iri for a in new])
    seen: dict[Term, set[Term]] = {}
    stored = sorted({m for m in messages.values() if m is not None and not change.is_new(m)})
    if stored:
        for row in facts.select(MESSAGE_PATIENTS, {"messages": _iris(stored)}):
            seen.setdefault(_key(row["m"]), set()).add(_key(row["p"]))
    for a in new:
        message = messages[a.iri]
        if message is None:
            continue
        patient = patients.patient_of(a.iri)
        others = seen.setdefault(message, set())
        if patient is not None and any(other != patient for other in others):
            raise trigger_failed("All assertions of a message must be about one patient.")
        if patient is not None:
            others.add(patient)


STORED_HEADS = f"""
SELECT ?e ?head FROM $abox WHERE {{
  VALUES ?e {{ $entries }}
  ?head triad:about ?e .
  {fragments.current("?head")}
}}"""


@register("assertion.one-head-per-entry", kinds=("assertion",), owner="B")
def one_head_per_entry(change: Change, facts: Facts) -> None:
    """SQLite: TR_Assertion_One_Head_Per_Entry. A new assertion about an entry that has a current assertion
    must supersede that assertion.

    Error: trigger_failed("The entry has a current assertion. The new assertion must supersede it.").
    The use case checks this first (409); this guard is the second line, under the write lock.
    The current assertions of an entry: the stored ones and the new ones before this one that no assertion
    (stored, or new before this one) supersedes.
    """
    new = _new_assertions(change)
    if not new:
        return
    entries = {a.iri: _key(a.get("about")) if a.get("about") else None for a in new}
    heads: dict[Term, set[Term]] = {}
    stored = sorted({e for e in entries.values() if e is not None and not change.is_new(e)})
    if stored:
        for row in facts.select(STORED_HEADS, {"entries": _iris(stored)}):
            heads.setdefault(_key(row["e"]), set()).add(_key(row["head"]))
    superseded: set[Term] = set()
    for a in new:
        entry = entries[a.iri]
        if entry is None:
            continue
        target = _key(a.get("supersedes")) if a.get("supersedes") else None
        known = heads.setdefault(entry, set())
        if any(head != target for head in known - superseded):
            raise trigger_failed("The entry has a current assertion. The new assertion must supersede it.")
        known.add(a.iri)
        if target is not None:
            superseded.add(target)


def _instant(value) -> Optional[datetime]:
    try:
        return parse_time(str(value)) if value is not None else None
    except ValueError:
        return None


@register("assertion.supersede-check", kinds=("assertion",), owner="B")
def supersede_check(change: Change, facts: Facts) -> None:
    """SQLite: TR_Assertion_Supersede_Check. For a new assertion with triad:supersedes:

    - the superseded assertion is not newer (compare the instants of assertedAt, not the text):
      trigger_failed("The superseded assertion is newer than the new assertion.");
    - it is about the same patient: trigger_failed("The superseded assertion is about another patient.");
    - new in Milestone 5 (plan 1.7): the supersedes chain has no cycle.
    The superseded assertion can be stored, or new in the same change.

    The cycle: in SQLite the superseded row must exist before the insert (FOREIGN KEY), and a stored assertion
    cannot change, so a chain can never close. In the buffer, an assertion can name a new assertion that comes
    after it (a larger id). That is the only way to make a cycle, so the guard refuses it with the error of
    SQLite for this write: foreign_key_conflict() (409). An assertion that supersedes itself is the CHECK
    constraint of the next guard.
    """
    new = [a for a in _new_assertions(change) if a.get("supersedes")]
    if not new:
        return
    targets = {a.iri: _key(a.get("supersedes")) for a in new}
    patients = _Patients(change, facts).load([*targets.values(), *[a.iri for a in new]])
    for a in new:
        target = targets[a.iri]
        if target == a.iri:                         # the CHECK constraint (the next guard)
            continue
        target_new = change.new_subject(target)
        if target_new is not None and target_new.id > a.id:     # SQLite: the row does not exist yet
            raise foreign_key_conflict()
        own, old = _instant(a.get("assertedAt")), _instant(patients.time_of(target))
        if own is not None and old is not None and old > own:
            raise trigger_failed("The superseded assertion is newer than the new assertion.")
        own_patient, old_patient = patients.patient_of(a.iri), patients.patient_of(target)
        if own_patient is not None and old_patient is not None and own_patient != old_patient:
            raise trigger_failed("The superseded assertion is about another patient.")


@register("assertion.supersedes-not-itself", kinds=("assertion",), owner="B")
def supersedes_not_itself(change: Change, facts: Facts) -> None:
    """SQLite: CHECK (SupersedesId IS NULL OR SupersedesId <> Id).

    Error: check_failed("CHECK constraint failed: SupersedesId IS NULL OR SupersedesId <> Id").
    """
    for a in _new_assertions(change):
        target = a.get("supersedes")
        if target is not None and _key(target) == a.iri:
            raise check_failed("CHECK constraint failed: SupersedesId IS NULL OR SupersedesId <> Id")

