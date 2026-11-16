"""The unit of work of the knowledge graph: the write lock, the write buffer and the commit (plan 5, section 5.3).

The use cases do not change: `with ctx.uow.write() as now:` gives the time of the write, as with SQLite.
Inside the block, the repositories put their writes into the write buffer of the session (KgSession.buffer).
Nothing goes to the store before the end of the block. An error in the block discards the buffer (no write).

Why a buffer: Virtuoso does not run one request as one transaction. If a later operation fails, the earlier ones
stay. Only one INSERT DATA (or one DELETE DATA) is all-or-nothing, also over two graphs. So the commit:
1. runs the guards on the buffered change (guards.py), under the lock;
2. checks with one ASK that no new IRI exists already (else Conflict, and the counters are seeded again);
3. sends one DELETE/INSERT ... WHERE for each changed property (replace), then the deletes (delete_subject),
   then ONE INSERT DATA with all new triples and the new counter values (create, add). The WHERE of a change
   matches the stored value, so the store form of a literal does not matter (D11);
4. if an operation fails after other operations were applied, sends the inverse of the applied operations in
   the reverse order, then raises the error. (A test forces a failure in the second operation.)

The write lock is process-wide and not reentrant: write() inside write() raises NestedWriteError at once (SQLite
also fails at once), so a nested write cannot hang. Another thread waits for the lock. Run one writer process
for each store.

The buffer API for the repositories (see README.md for examples):
    buf = session.write_buffer()
    new_id = buf.create("visit", {"visitClass": "AMB", "startDate": now, ...})    # mints the id; rdf:type triad:Visit
    buf.add(iri("patient", 1), {"hasVisit": iri("visit", new_id)})              # more triples on a subject
    buf.replace(iri("patient", 1), "phoneNumber", "+1-555-0100")                # None removes the value
    buf.delete_subject("location", 7)                                           # only the kinds of the allow-list
    buf.find("medication", code=..., codeSystem=...)                            # read your writes
"""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterator, Mapping, Optional, Sequence

from domain.errors import Conflict, Invalid
from domain.rules import parse_time

from infrastructure.clock import DemoClock
from infrastructure.sparql import ids, terms
from infrastructure.sparql.change import Added, Change, Deletion, NewSubject, Replacement
from infrastructure.sparql.client import SparqlStoreError
from infrastructure.sparql.guards import REVERSE_FK, Facts, run_guards
from infrastructure.sparql.terms import Term, TermError

log = logging.getLogger("triad.sparql")

LOCK_TIMEOUT = 30.0   # seconds. SQLite waits 5 s (busy_timeout); a KG write has more requests.

# The time properties that the API writes with the clock (the TIME_COLUMNS of the SQLite unit of work).
# The latest of them sets the time of the next write.
TIME_PROPERTIES = ("assertedAt", "sentAt", "startDate", "endDate", "startedAt", "createdAt", "at")
LATEST_QUERY = "SELECT ?t FROM $abox WHERE {\n" + "\n  UNION\n".join(
    f"  {{ SELECT (MAX(?t{i}) AS ?t) WHERE {{ ?x{i} triad:{prop} ?t{i} }} }}"
    for i, prop in enumerate(TIME_PROPERTIES)) + "\n}"


class NestedWriteError(RuntimeError):
    """write() was called inside write() (in the same thread)."""


class HalfWriteError(SparqlStoreError):
    """A write failed, and the inverse of its applied operations failed too. The store can hold a half change."""


# ---------------------------------------------------------------------------------------------
# The state of one store in this process

class StoreState:
    """The process-wide state of one store: the write lock and the latest time of the data.

    One object for each store key (client.key). ensure-kg calls forget() after a rebuild of the store.
    """
    _states: dict[str, "StoreState"] = {}
    _states_lock = threading.Lock()

    def __init__(self, key: str):
        self.key = key
        self.write_lock = threading.Lock()
        self.owner: Optional[int] = None          # the thread that holds the write lock
        self._latest: Optional[datetime] = None
        self._latest_known = False
        self._read_lock = threading.Lock()
        self.last_write: Optional[str] = None     # the time of the last commit of this process

    @classmethod
    def of(cls, key: str) -> "StoreState":
        with cls._states_lock:
            state = cls._states.get(key)
            if state is None:
                state = cls._states[key] = StoreState(key)
            return state

    @classmethod
    def forget(cls, key: str) -> None:
        with cls._states_lock:
            cls._states.pop(key, None)

    def latest(self, client) -> Optional[datetime]:
        """The latest time of the data (as an instant). One query at the first call; then each commit updates it."""
        if not self._latest_known:
            with self._read_lock:
                if not self._latest_known:
                    moments = [parse_time(row["t"]) for row in client.select(LATEST_QUERY) if row.get("t")]
                    self._latest = max(moments) if moments else None
                    self._latest_known = True
        return self._latest

    def note(self, moments: Sequence[datetime], write_time: Optional[str] = None) -> None:
        if write_time is not None:
            self.last_write = write_time
        if moments and self._latest_known:
            newest = max(moments)
            if self._latest is None or newest > self._latest:
                self._latest = newest


# ---------------------------------------------------------------------------------------------
# The session of one request

class KgSession:
    """The shared parts of one request: the client, the state of the store, and the write buffer of a write."""

    def __init__(self, client, state: Optional[StoreState] = None):
        self.client = client
        self.state = state or StoreState.of(client.key)
        self.buffer: Optional[WriteBuffer] = None

    def write_buffer(self) -> "WriteBuffer":
        """The buffer of the current write. A write method of a repository calls this first."""
        if self.buffer is None:
            raise RuntimeError("This repository method writes. Call it inside `with ctx.uow.write():`.")
        return self.buffer

    def select(self, template: str, bindings: Optional[Mapping[str, Any]] = None) -> list[dict]:
        return self.client.select(template, bindings)

    def ask(self, template: str, bindings: Optional[Mapping[str, Any]] = None) -> bool:
        return self.client.ask(template, bindings)

    def close(self) -> None:
        self.buffer = None


# ---------------------------------------------------------------------------------------------
# The operations of a commit

@dataclass
class Operation:
    """One update request of a commit and its inverse (read before the update is sent)."""
    label: str
    template: str
    bindings: dict = field(default_factory=dict)
    undo: list[tuple[str, dict]] = field(default_factory=list)

    def prepare(self, client) -> None:
        """Read the stored values that the inverse needs. The default: no inverse (an INSERT DATA)."""


def object_list(values: Sequence[Term]) -> Term:
    return Term(", ".join(values))


REPLACE_WITH_VALUES = """WITH $abox
DELETE { $s $p ?old }
INSERT { $s $p $values }
WHERE { $s a ?type . OPTIONAL { $s $p ?old } }"""
REMOVE = "WITH $abox DELETE { $s $p ?old } WHERE { $s $p ?old }"


@dataclass
class ReplaceOperation(Operation):
    subject: Term = Term("")
    prop: str = ""
    values: tuple[Term, ...] = ()

    @staticmethod
    def request(subject: Term, prop: str, values: Sequence[Term]) -> tuple[str, dict]:
        bindings = {"s": subject, "p": terms.property_term(prop)}
        if values:
            return REPLACE_WITH_VALUES, {**bindings, "values": object_list(values)}
        return REMOVE, bindings

    def prepare(self, client) -> None:
        rows = client.select("SELECT ?old FROM $abox WHERE { $s $p ?old }",
                             {"s": self.subject, "p": terms.property_term(self.prop)}, raw=True)
        self.undo = [self.request(self.subject, self.prop, [row["old"] for row in rows])]


DELETE_SUBJECT = """WITH $abox DELETE { $s ?p ?o } WHERE { $s ?p ?o } ;
WITH $abox DELETE { ?x ?q $s } WHERE { ?x ?q $s . FILTER (?q IN ($reverse)) }"""


@dataclass
class DeleteOperation(Operation):
    subject: Term = Term("")

    def prepare(self, client) -> None:
        reverse = terms.term_list(terms.term(p) for p in sorted(REVERSE_FK))
        out = client.select("SELECT ?p ?o FROM $abox WHERE { $s ?p ?o }", {"s": self.subject}, raw=True)
        into = client.select("SELECT ?x ?q FROM $abox WHERE { ?x ?q $s . FILTER (?q IN ($reverse)) }",
                             {"s": self.subject, "reverse": reverse}, raw=True)
        triples = [f"{self.subject} {r['p']} {r['o']} ." for r in out] + [f"{r['x']} {r['q']} {self.subject} ."
                                                                           for r in into]
        if triples:
            self.undo = [("INSERT DATA { GRAPH $abox { $triples } }", {"triples": Term("\n".join(triples))})]


# ---------------------------------------------------------------------------------------------
# The write buffer

class WriteBuffer:
    """The writes of one unit of work. See the module text for the API."""

    def __init__(self, session: KgSession):
        self.session = session
        self._counters: Optional[dict[str, int]] = None
        self._issued: dict[str, int] = {}                  # kind -> the largest id of this write
        self._new: dict[Term, NewSubject] = {}
        self._added: list[Added] = []
        self._replaced: dict[tuple[Term, str], Replacement] = {}
        self._deleted: dict[Term, Deletion] = {}

    # ----- ids -----

    def _counter(self, kind: str) -> int:
        if self._counters is None:
            self._counters = ids.read_counters(self.session.client)
        if kind not in self._counters:           # a store with no counter for the kind (not built by ensure-kg)
            self._counters[kind] = ids.max_id(self.session.client, kind)
        return max(self._counters[kind], self._issued.get(kind, 0))

    def new_id(self, kind: str) -> int:
        """The next id of a kind: the counter + 1 (never an id that was used before)."""
        if kind not in terms.KINDS:
            raise ValueError(f"{kind!r} is not a class path.")
        number = self._counter(kind) + 1
        self._issued[kind] = number
        return number

    # ----- appends: one INSERT DATA at the commit -----

    @staticmethod
    def _check(prop: str, values: Sequence[Any]) -> None:
        if prop not in terms.PROPERTIES:
            raise ValueError(f"triad:{prop} is not a stored property of the TRIAD ontology.")
        for value in values:
            terms.value_of(prop, value)          # raises TermError for a wrong value

    @staticmethod
    def _as_list(value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return [v for v in value if v is not None]
        return [value]

    def create(self, kind: str, values: Optional[Mapping[str, Any]] = None, *, types: Sequence[str] = (),
               id: Optional[int] = None) -> int:
        """Add a new individual of a kind: its rdf:type (the class of the kind, then `types`) and its values.

        `values` maps a property name to a value, a list of values (a multivalued property) or None (no triple).
        A value of an object property is an IRI (terms.iri). Return the id (new from the counter, or `id`).
        """
        if kind not in terms.KINDS:
            raise ValueError(f"{kind!r} is not a class path.")
        classes = (terms.CLASS_OF_KIND[kind], *[t for t in types if t != terms.CLASS_OF_KIND[kind]])
        for name in classes:
            terms.class_term(name)
        if id is None:
            id = self.new_id(kind)
        else:
            self._issued[kind] = max(self._issued.get(kind, 0), id)
        subject = terms.iri(kind, id)
        if subject in self._new:
            raise ValueError(f"{subject} is new in this write already.")
        new = NewSubject(kind, id, subject, tuple(classes))
        self._new[subject] = new
        self._merge(new, values or {})
        return id

    def _merge(self, new: NewSubject, values: Mapping[str, Any]) -> None:
        for prop, value in values.items():
            items = self._as_list(value)
            self._check(prop, items)
            if items:
                new.values.setdefault(prop, []).extend(items)

    def add(self, subject: Term, values: Mapping[str, Any]) -> None:
        """Add triples to a subject: a subject that is new in this write, or a stored subject."""
        terms.split_iri(subject)
        if subject in self._new:
            self._merge(self._new[subject], values)
            return
        for prop, value in values.items():
            items = self._as_list(value)
            self._check(prop, items)
            self._added += [Added(subject, prop, item) for item in items]

    # ----- changes: one DELETE/INSERT ... WHERE for each property -----

    def replace(self, subject: Term, prop: str, value: Any) -> None:
        """Give a property of a subject new values: a value, a list (a multivalued property) or None (remove)."""
        terms.split_iri(subject)
        items = self._as_list(value)
        self._check(prop, items)
        if subject in self._new:
            if items:
                self._new[subject].values[prop] = items
            else:
                self._new[subject].values.pop(prop, None)
            return
        self._replaced[(subject, prop)] = Replacement(subject, prop, tuple(items))

    def delete_subject(self, kind: str, id: int) -> None:
        """Delete all triples of a stored subject, and the links of its parent to it (the reverse-direction
        properties, for example <patient> triad:identifier <patient-identifier>). The guards check the
        allow-list (Assertion and AuditEvent are append-only) and that no other row uses it (Conflict)."""
        subject = terms.iri(kind, id)
        if subject in self._new:
            del self._new[subject]
            return
        self._deleted[subject] = Deletion(kind, id, subject)

    # ----- read your writes -----

    def created(self, kind: Optional[str] = None) -> list[NewSubject]:
        return [s for s in self._new.values() if kind is None or s.kind == kind]

    def find(self, kind: str, **match: Any) -> list[int]:
        """The ids of the new subjects of a kind whose values include each value of `match`."""
        return [s.id for s in self.created(kind)
                if all(value in s.values.get(prop, []) for prop, value in match.items())]

    def values(self, kind: str, prop: str, **match: Any) -> list[Any]:
        """The values of one property of the new subjects of a kind that match (see find)."""
        out: list[Any] = []
        for s in self.created(kind):
            if all(value in s.values.get(p, []) for p, value in match.items()):
                out += s.values.get(prop, [])
        return out

    def change(self) -> Change:
        replaced = [r for r in self._replaced.values() if r.subject not in self._deleted]
        return Change(self._new.values(), self._added, replaced, self._deleted.values())

    def is_empty(self) -> bool:
        return self.change().is_empty()

    # ----- the commit -----

    def _triples(self) -> list[str]:
        out = []
        rdf_type = f"<{terms.RDF_TYPE}>"
        for s in self._new.values():
            out += [f"{s.iri} {rdf_type} {terms.class_term(c)} ." for c in s.types]
            for prop, values in s.values.items():
                out += [f"{s.iri} {terms.property_term(prop)} {terms.value_of(prop, v)} ." for v in values]
        out += [f"{a.subject} {terms.property_term(a.prop)} {terms.value_of(a.prop, a.value)} ." for a in self._added]
        return out

    def _counter_values(self) -> dict[str, int]:
        return {kind: max(number, (self._counters or {}).get(kind, 0)) for kind, number in self._issued.items()}

    def _check_new_iris(self) -> None:
        """One ASK: no new IRI exists in the store already. Else seed the counters again and raise Conflict."""
        new = sorted(self._new)
        if not new:
            return
        client = self.session.client
        if not client.ask("ASK FROM $abox WHERE { VALUES ?x { $iris } ?x ?p ?o }", {"iris": Term(" ".join(new))}):
            return
        kinds = sorted({s.kind for s in self._new.values()})
        stored = ids.read_counters(client)
        values = {kind: max(stored.get(kind, 0), ids.max_id(client, kind)) for kind in kinds}
        client.update("INSERT DATA { GRAPH $meta { $counters } }",
                      {"counters": Term("\n".join(ids.counter_triples(values)))})
        log.warning("[sparql] The id counters of %s were behind the data. They are seeded again: %s",
                    client.key, values)
        raise Conflict("The id counters of the knowledge graph were behind the data. They are correct now. "
                       "Send the request again.")

    def operations(self) -> list[Operation]:
        """The update requests of the commit, in order: the changes, the deletes, then one INSERT DATA."""
        ops: list[Operation] = []
        for r in self.change().replaced():
            values = tuple(terms.value_of(r.prop, v) for v in r.values)
            template, bindings = ReplaceOperation.request(r.subject, r.prop, values)
            ops.append(ReplaceOperation(f"replace {r.prop}", template, bindings, subject=r.subject, prop=r.prop,
                                        values=values))
        reverse = terms.term_list(terms.term(p) for p in sorted(REVERSE_FK))
        for d in self._deleted.values():
            ops.append(DeleteOperation(f"delete {d.kind}", DELETE_SUBJECT, {"s": d.iri, "reverse": reverse},
                                       subject=d.iri))
        triples = self._triples()
        counters = ids.counter_triples(self._counter_values())
        if triples or counters:
            ops.append(Operation("insert data", "INSERT DATA { GRAPH $abox { $triples } GRAPH $meta { $counters } }",
                                 {"triples": Term("\n".join(triples)), "counters": Term("\n".join(counters))}))
        return ops

    def times(self) -> list[datetime]:
        """The instants of the time properties that this write sets (for the latest time of the store)."""
        found = [v for s in self._new.values() for p in TIME_PROPERTIES for v in s.values.get(p, [])]
        found += [a.value for a in self._added if a.prop in TIME_PROPERTIES]
        found += [v for r in self._replaced.values() if r.prop in TIME_PROPERTIES for v in r.values]
        return [parse_time(v) for v in found if isinstance(v, str)]

    def commit(self) -> list[datetime]:
        """Check the change, then send it (see the module text). Return the times that it wrote."""
        change = self.change()
        if change.is_empty():
            return []
        client = self.session.client
        run_guards(change, Facts(client))
        self._check_new_iris()
        ops = self.operations()
        for op in ops:
            op.prepare(client)
        applied: list[Operation] = []
        for op in ops:
            try:
                client.update(op.template, op.bindings)
            except Exception as error:
                self._compensate(applied, op, error)
                raise
            applied.append(op)
        return self.times()

    def _compensate(self, applied: list[Operation], failed: Operation, error: Exception) -> None:
        """Send the inverse of each applied operation, in the reverse order."""
        client = self.session.client
        problems = []
        for op in reversed(applied):
            for template, bindings in op.undo:
                try:
                    client.update(template, bindings)
                except Exception as undo_error:   # keep on: undo as much as possible
                    problems.append(f"{op.label}: {undo_error}")
        if problems:
            log.error("[sparql] A write failed (%s: %s), and its inverse failed too: %s", failed.label, error,
                      "; ".join(problems))
            raise HalfWriteError(f"A write failed ({failed.label}: {error}), and the inverse of the applied "
                                 f"operations failed too ({'; '.join(problems)}). The store can hold a half "
                                 "change.") from error


# ---------------------------------------------------------------------------------------------
# The unit of work (the UnitOfWork port)

class SparqlUnitOfWork:
    def __init__(self, session: KgSession, clock: DemoClock):
        self.session = session
        self.clock = clock

    def latest_time(self) -> Optional[datetime]:
        return self.session.state.latest(self.session.client)

    def now(self) -> str:
        return self.clock.current(self.latest_time())

    @contextmanager
    def write(self) -> Iterator[str]:
        session, state = self.session, self.session.state
        me = threading.get_ident()
        if state.owner == me or session.buffer is not None:
            raise NestedWriteError("A write cannot start inside another write (ctx.uow.write() inside "
                                   "ctx.uow.write()).")
        if not state.write_lock.acquire(timeout=LOCK_TIMEOUT):
            raise SparqlStoreError(f"Another write holds the write lock of the store for more than {LOCK_TIMEOUT} s.")
        state.owner = me
        buffer = WriteBuffer(session)
        session.buffer = buffer
        try:
            try:
                now = self.clock.write_time(self.latest_time())
                yield now
                written = buffer.commit()
            except TermError as error:            # a value that is not correct: as a failed CHECK in SQLite
                raise Invalid("The input is not correct.", {"database": str(error)}) from error
            state.note(written, now)
        finally:
            session.buffer = None
            state.owner = None
            state.write_lock.release()
