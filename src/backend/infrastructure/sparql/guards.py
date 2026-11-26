"""The guards: the rules that SQLite holds in its constraints and triggers, in Python on the buffered change.

Why in Python (plan 5.4): an ASK on the store cannot see the rows of the same unit of work (a new entry, its visit
and its first assertion are written together), and Virtuoso has no transaction over two requests. So the unit of
work runs each guard at the commit, under the write lock, before it sends any update. A guard reads the change
(change.Change) and, when it needs stored facts, reads them with one SELECT (Facts.select). It raises the same
exception class as SQLite, so the API gives the same status and code (plan 1.7):

    SQLite rule          exception                                                    HTTP  code
    UNIQUE               Conflict("A row with the same key exists already.", {"key"})  409   conflict
    FOREIGN KEY          Conflict("The row is in use, or it points to a row that does  409   conflict
                         not exist.")
    CHECK / NOT NULL     Invalid("The input is not correct.", {"database": text})      422   validation
    trigger RAISE        Invalid(<the text of the trigger>)                             422   validation

The helpers unique_conflict(), foreign_key_conflict(), check_failed() and trigger_failed() make these errors.

How to add a guard (see README.md):

    from infrastructure.sparql.guards import Facts, register, trigger_failed
    from infrastructure.sparql.change import Change

    @register("assertion.one-head-per-entry", kinds=("assertion",), owner="B")
    def one_head_per_entry(change: Change, facts: Facts) -> None:
        for new in change.created("assertion"):
            ...                                  # one SELECT for the stored facts, if necessary
            raise trigger_failed("The entry has a current assertion. The new assertion must supersede it.")

`kinds`: the guard runs only when the change touches one of these kinds (new, added to, replaced or deleted).
No kinds: it runs for each change. The guards run in the order of registration: first the guards of this
file, then the files of EXTENSIONS. Each agent has its own file, so no two agents change the same file:

    guards_records.py     agent B   the assertion guards (supersede check, one head per entry, ...)
    guards_chat.py        agent C   the citation check and the audit subject
    guards_directory.py   agent D   the key guards (UNIQUE, Conflict 409)

This file holds the framework and the guards of agent A: the delete allow-list (with the append-only rule), the
foreign keys, and the example guard "the patient key cannot change".
"""
from __future__ import annotations

import importlib
import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional

from domain.errors import Conflict, Invalid

from infrastructure.sparql import terms
from infrastructure.sparql.change import Change
from infrastructure.sparql.terms import Term
from models.semantic import vocabulary as V

EXTENSIONS = ("infrastructure.sparql.guards_records", "infrastructure.sparql.guards_chat",
              "infrastructure.sparql.guards_directory")

# The kinds that delete_subject() can delete (the allow-list, plan 1.7). Assertion and AuditEvent are
# append-only: a refusal has the text of their SQLite trigger.
DELETABLE = frozenset({"patient", "patient-identifier", "department", "location", "staff", "works-in",
                       "medication"})
APPEND_ONLY = {
    "assertion": "Assertion is append-only. Add a new assertion that supersedes it.",
    "audit-event": "AuditEvent is append-only.",
}

# The foreign keys of the relational schema, as object properties (vocabulary.py).
# Stored direction: <row> p <target> (the row holds the FK). Reverse direction: <parent> p <row>.
STORED_FK = frozenset(term for term, kind in V.COLUMNS.values() if kind == V.FK)
REVERSE_FK = frozenset(term for term, kind in V.COLUMNS.values() if kind == V.FK_REVERSE)


# ---------------------------------------------------------------------------------------------
# The errors (the same classes and texts as the SQLite unit of work, infrastructure/sqlite/unit_of_work.py)

def unique_conflict(table: str, columns: Iterable[str]) -> Conflict:
    """The error of a UNIQUE constraint, for example unique_conflict("Medication", ("Code", "CodeSystem"))."""
    return Conflict("A row with the same key exists already.",
                    {"key": ", ".join(f"{table}.{column}" for column in columns)})


def foreign_key_conflict() -> Conflict:
    return Conflict("The row is in use, or it points to a row that does not exist.")


def check_failed(text: str) -> Invalid:
    """The error of a CHECK or NOT NULL constraint. `text` is the SQLite text, for example
    "CHECK constraint failed: SupersedesId IS NULL OR SupersedesId <> Id"."""
    return Invalid("The input is not correct.", {"database": text})


def trigger_failed(text: str) -> Invalid:
    """The error of a trigger (RAISE): the text of the trigger."""
    return Invalid(text)


# ---------------------------------------------------------------------------------------------
# The framework

class Facts:
    """Reads stored facts for the guards: one SELECT (or ASK) under the write lock. The template needs FROM $abox."""

    def __init__(self, client: Any):
        self._client = client

    def select(self, template: str, bindings: Optional[Mapping[str, Any]] = None) -> list[dict]:
        return self._client.select(template, bindings)

    def ask(self, template: str, bindings: Optional[Mapping[str, Any]] = None) -> bool:
        return self._client.ask(template, bindings)

    def existing(self, iris: Iterable[str]) -> set[Term]:
        """The IRIs of the list that are stored individuals (they have a type in the ABox). One SELECT."""
        wanted = sorted({Term(i if i.startswith("<") else f"<{i}>") for i in iris})
        if not wanted:
            return set()
        rows = self._client.select("SELECT DISTINCT ?x FROM $abox WHERE { VALUES ?x { $iris } ?x a ?type }",
                                   {"iris": Term(" ".join(wanted))})
        return {Term(f"<{row['x']}>") for row in rows}


Check = Callable[[Change, Facts], None]


@dataclass(frozen=True)
class Guard:
    name: str
    check: Check
    kinds: frozenset[str]
    owner: str
    module: str

    def applies_to(self, change: Change) -> bool:
        return not self.kinds or bool(self.kinds & change.kinds())


_REGISTRY: dict[str, Guard] = {}
_LOADED = False
_LOAD_LOCK = threading.Lock()


def register(name: str, *, kinds: Iterable[str] = (), owner: str) -> Callable[[Check], Check]:
    """Register a guard function under a unique name. `owner` is the agent (A, B, C or D) that keeps it."""
    unknown = set(kinds) - set(terms.KINDS)
    if unknown:
        raise ValueError(f"The guard {name} names kinds that do not exist: {', '.join(sorted(unknown))}.")

    def add(check: Check) -> Check:
        if name in _REGISTRY and _REGISTRY[name].check is not check:
            raise ValueError(f"Two guards have the name {name}.")
        _REGISTRY[name] = Guard(name, check, frozenset(kinds), owner, check.__module__)
        return check
    return add


def registered() -> list[Guard]:
    """All guards, in the order of registration. The first call imports the files of EXTENSIONS."""
    global _LOADED
    if not _LOADED:
        with _LOAD_LOCK:
            if not _LOADED:
                for module in EXTENSIONS:
                    importlib.import_module(module)
                _LOADED = True
    return list(_REGISTRY.values())


def run_guards(change: Change, facts: Facts) -> None:
    """Run each guard that applies to the change. The first guard that fails raises its error."""
    if change.is_empty():
        return
    for guard in registered():
        if guard.applies_to(change):
            guard.check(change, facts)


# ---------------------------------------------------------------------------------------------
# The guards of agent A

@register("delete.allow-list", owner="A")
def delete_allow_list(change: Change, facts: Facts) -> None:
    """Only the kinds of DELETABLE can be deleted. Assertion and AuditEvent are append-only (no change, no delete).

    SQLite holds the append-only rule in the triggers TR_Assertion_NoUpdate/NoDelete and TR_AuditEvent_NoUpdate/
    NoDelete. In the knowledge graph, this guard holds it: the guarantee moves from the database to the app.
    A kind that is not on the list is an error of the code (ValueError), not of the input.
    """
    for deletion in change.deleted():
        if deletion.kind in APPEND_ONLY:
            raise trigger_failed(APPEND_ONLY[deletion.kind])
        if deletion.kind not in DELETABLE:
            raise ValueError(f"The kind {deletion.kind} is not in the delete allow-list "
                             f"({', '.join(sorted(DELETABLE))}).")
    for replacement in change.replaced():
        if replacement.kind in APPEND_ONLY:
            raise trigger_failed(APPEND_ONLY[replacement.kind])
    for added in change.added():               # a new triple on a stored assertion is a change of it
        kind = terms.kind_of(added.subject)
        if kind in APPEND_ONLY:
            raise trigger_failed(APPEND_ONLY[kind])


IN_USE = """
SELECT ?p ?other FROM $abox WHERE {
  { $s ?p ?other . FILTER (?p IN ($reverse)) }
  UNION
  { ?other ?p $s . FILTER (?p IN ($stored)) }
} LIMIT 50"""


@register("foreign-keys", owner="A")
def foreign_keys(change: Change, facts: Facts) -> None:
    """The FOREIGN KEY rules of SQLite (RESTRICT): Conflict 409.

    - A deleted subject is not in use: no stored row points to it (stored direction, for example
      <assertion> triad:about <entry>), and it has no stored child (reverse direction, for example
      <patient> triad:hasVisit <visit>), except rows that the same change deletes.
    - Each IRI that a new triple names (subject or value) exists: it is new in the change, or stored.
    """
    reverse = terms.term_list(terms.term(p) for p in sorted(REVERSE_FK))
    stored = terms.term_list(terms.term(p) for p in sorted(STORED_FK))
    for deletion in change.deleted():
        for row in facts.select(IN_USE, {"s": deletion.iri, "reverse": reverse, "stored": stored}):
            if not change.is_deleted(row["other"]):
                raise foreign_key_conflict()
    named: set[str] = set()
    for subject in change.created():
        for prop, values in subject.values.items():
            named |= {v for v in values if isinstance(v, Term) and v.startswith("<")}
    for added in change.added():
        named.add(added.subject)
        if isinstance(added.value, Term) and added.value.startswith("<"):
            named.add(added.value)
    for replacement in change.replaced():
        named |= {v for v in replacement.values if isinstance(v, Term) and v.startswith("<")}
    if any(change.is_deleted(iri) for iri in named):
        raise foreign_key_conflict()
    missing = {iri for iri in named if not change.is_new(iri)}
    if missing and facts.existing(missing) != missing:
        raise foreign_key_conflict()


@register("patient.key-is-fixed", kinds=("patient",), owner="A")
def patient_key_is_fixed(change: Change, facts: Facts) -> None:
    """The example guard. SQLite: TR_Patient_Key_NoUpdate. The name and the date of birth of a patient do not
    change, because the logs keep them as values. The use case refuses the change first (patients.change);
    this guard is the second line, under the write lock. The same value again is not a change (as in SQLite).
    """
    for replacement in change.replaced("patient"):
        if replacement.prop not in ("name", "dateOfBirth"):
            continue
        rows = facts.select("SELECT ?old FROM $abox WHERE { $s $p ?old }",
                            {"s": replacement.subject, "p": terms.term(replacement.prop)})
        if {row["old"] for row in rows} != set(replacement.values):
            raise trigger_failed("The name and the date of birth of a patient cannot change.")
