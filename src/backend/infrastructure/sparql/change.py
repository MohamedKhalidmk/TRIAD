"""The buffered change of one unit of work, as the guards see it (read only).

The write buffer (unit_of_work.WriteBuffer) keeps three kinds of change:
- NewSubject: a new individual (create()) with its types and its values. Its triples go into the one INSERT DATA.
- Added: more triples on a subject that is stored already (add()), for example <patient/1> triad:hasVisit <visit/9>.
- Replacement: new values of one property of a stored subject (replace()). Each one becomes one
  DELETE/INSERT ... WHERE. An empty list of values removes the property.
- Deletion: a stored subject to delete (delete_subject()).
A guard gets a Change and reads these lists. The values are Python values as the repository gave them:
text, int, bool, or a terms.Term (an IRI, from terms.iri(kind, id)).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from infrastructure.sparql.terms import Term, split_iri


@dataclass
class NewSubject:
    kind: str                         # the class path, for example "assertion"
    id: int
    iri: Term
    types: tuple[str, ...]            # the classes, for example ("Staff", "Doctor")
    values: dict[str, list[Any]] = field(default_factory=dict)

    def get(self, prop: str) -> Any:
        """The first value of the property, or None."""
        found = self.values.get(prop)
        return found[0] if found else None

    def all(self, prop: str) -> list[Any]:
        return list(self.values.get(prop, []))


@dataclass(frozen=True)
class Added:
    subject: Term                     # a stored subject (not a NewSubject)
    prop: str
    value: Any


@dataclass(frozen=True)
class Replacement:
    subject: Term
    prop: str
    values: tuple[Any, ...]           # the new values; () removes the property

    @property
    def kind(self) -> str:
        return split_iri(self.subject)[0]

    @property
    def id(self) -> int:
        return split_iri(self.subject)[1]


@dataclass(frozen=True)
class Deletion:
    kind: str
    id: int
    iri: Term


class Change:
    """A read-only view of a write buffer for the guards."""

    def __init__(self, new: Iterable[NewSubject], added: Iterable[Added], replaced: Iterable[Replacement],
                 deleted: Iterable[Deletion]):
        self._new = list(new)
        self._added = list(added)
        self._replaced = list(replaced)
        self._deleted = list(deleted)
        self._new_iris = {s.iri: s for s in self._new}
        self._deleted_iris = {d.iri for d in self._deleted}

    def created(self, kind: Optional[str] = None) -> list[NewSubject]:
        """The new subjects (of one kind, or all)."""
        return [s for s in self._new if kind is None or s.kind == kind]

    def added(self, prop: Optional[str] = None) -> list[Added]:
        """The triples that the change adds to stored subjects (of one property, or all)."""
        return [a for a in self._added if prop is None or a.prop == prop]

    def replaced(self, kind: Optional[str] = None) -> list[Replacement]:
        return [r for r in self._replaced if kind is None or r.kind == kind]

    def deleted(self, kind: Optional[str] = None) -> list[Deletion]:
        return [d for d in self._deleted if kind is None or d.kind == kind]

    def new_subject(self, iri: str) -> Optional[NewSubject]:
        """The new subject with this IRI (with or without angle brackets), or None."""
        key = iri if iri.startswith("<") else f"<{iri}>"
        return self._new_iris.get(Term(key))

    def is_new(self, iri: str) -> bool:
        return self.new_subject(iri) is not None

    def is_deleted(self, iri: str) -> bool:
        key = iri if iri.startswith("<") else f"<{iri}>"
        return Term(key) in self._deleted_iris

    def links_to(self, target: str, prop: Optional[str] = None) -> list[tuple[Term, str]]:
        """The (subject, property) pairs of the change whose value is the IRI `target` (new and added triples)."""
        key = target if target.startswith("<") else f"<{target}>"
        out = []
        for s in self._new:
            for name, values in s.values.items():
                if (prop is None or name == prop) and any(v == key for v in values):
                    out.append((s.iri, name))
        out += [(a.subject, a.prop) for a in self._added if a.value == key and (prop is None or a.prop == prop)]
        return out

    def kinds(self) -> set[str]:
        """The kinds that the change touches (new, added to, replaced or deleted)."""
        found = {s.kind for s in self._new} | {d.kind for d in self._deleted} | {r.kind for r in self._replaced}
        found |= {split_iri(a.subject)[0] for a in self._added}
        return found

    def is_empty(self) -> bool:
        return not (self._new or self._added or self._replaced or self._deleted)
