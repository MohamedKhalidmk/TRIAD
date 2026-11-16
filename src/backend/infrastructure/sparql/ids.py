"""The ids of new individuals (the counters of the meta graph) and the identifier values of new rows.

The integer ids (D6, plan 5.3). The IRI of a new individual ends with an integer id, as the SQLite row id:
- There is one counter for each class path, in the meta graph: <KG counter/<kind>> triad:issued N.
  Each write adds a new fact; the current value of a counter is the MAX of its facts.
  ensure-kg seeds the counters from sqlite_sequence (seed_triples). So an id is never used again, as with
  AUTOINCREMENT: MAX(Id) would give the id of a deleted row again.
- The unit of work reads the counters once in a write (under the lock), counts up in memory, and writes the new
  values in the same INSERT DATA as the data. Before that, one ASK checks that no new IRI exists already.

The identifier values (next_identifier, unique_identifier): the same rules as infrastructure/ids.py of SQLite,
for the identifier properties (triad:identifierSystem, triad:identifierValue) of an individual. They look in the
write buffer first: three new entries of one message must get three different values (plan 5.3).
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Iterable, Mapping, Optional

from infrastructure.rdf.namespaces import COUNTER, KG
from infrastructure.sparql import terms
from infrastructure.sparql.terms import Term
from models.semantic import vocabulary as V

if TYPE_CHECKING:
    from infrastructure.sparql.unit_of_work import KgSession

# The SQLite table of each class path (the tables whose rows have an IRI of their own).
KIND_TABLE: dict[str, str] = {path: table for table, (path, column) in V.SUBJECT.items() if column == "Id"}
TABLE_KIND: dict[str, str] = {table: path for path, table in KIND_TABLE.items()}

COUNTERS_QUERY = """
SELECT ?counter (MAX(?n) AS ?issued) FROM $meta WHERE { ?counter triad:issued ?n } GROUP BY ?counter"""

MAX_ID_QUERY = """
SELECT (MAX(?n) AS ?max) FROM $abox WHERE {
  ?x a $class .
  BIND (xsd:integer(STRAFTER(STR(?x), $base)) AS ?n)
}"""

IDENTIFIER_VALUES = """
SELECT ?value FROM $abox WHERE {
  ?x a $class ; triad:identifierSystem $system ; triad:identifierValue ?value .
  FILTER (STRSTARTS(?value, $start))
}"""


def counter_iri(kind: str) -> Term:
    if kind not in terms.KINDS:
        raise terms.TermError(f"{kind!r} is not a class path.")
    return Term(f"<{COUNTER}{kind}>")


def read_counters(client) -> dict[str, int]:
    """The current value of each counter of the meta graph (one SELECT)."""
    out = {}
    for row in client.select(COUNTERS_QUERY):
        name = str(row["counter"])
        if name.startswith(COUNTER) and row["issued"] is not None:
            kind = name[len(COUNTER):]
            if kind in terms.KINDS:
                out[kind] = int(row["issued"])
    return out


def max_id(client, kind: str) -> int:
    """The largest id of the stored individuals of a kind (0 if none). It reads all of them: use it only to
    seed a counter that is missing or behind."""
    rows = client.select(MAX_ID_QUERY, {"class": terms.class_term(terms.CLASS_OF_KIND[kind]),
                                        "base": f"{KG}{kind}/"})
    value = rows[0]["max"] if rows else None
    return int(value) if value is not None else 0


def counter_triples(values: Mapping[str, int]) -> list[str]:
    """The counter facts of the meta graph: one triple for each kind."""
    return [f"{counter_iri(kind)} {terms.term('issued')} {terms.literal(int(n))} ."
            for kind, n in sorted(values.items())]


def seed_values(sequences: Mapping[str, int]) -> dict[str, int]:
    """The counter values for the sqlite_sequence values (table -> last id). The tables with no IRI do not count."""
    out = {kind: 0 for kind in terms.KINDS}
    for table, value in sequences.items():
        kind = TABLE_KIND.get(table)
        if kind is not None:
            out[kind] = max(out[kind], int(value))
    return out


# ---------------------------------------------------------------------------------------------
# The identifier values (the same rules as infrastructure/ids.py)

def _number(value: str, prefix: str) -> Optional[int]:
    """The number of `<prefix><digits>...`, as SQLite gives it: GLOB 'prefix[0-9]*', CAST of the rest."""
    match = re.match(r"\d+", value[len(prefix):]) if value.startswith(prefix) else None
    return int(match.group(0)) if match else None


def _values(session: "KgSession", kind: str, system: str, start: str) -> set[str]:
    """The identifier values of the kind with the system that start with `start`: stored and in the buffer."""
    rows = session.client.select(IDENTIFIER_VALUES, {"class": terms.class_term(terms.CLASS_OF_KIND[kind]),
                                                     "system": system, "start": start})
    found = {row["value"] for row in rows}
    buffer = session.buffer
    if buffer is not None:
        found |= {v for v in buffer.values(kind, "identifierValue", identifierSystem=system)
                  if isinstance(v, str) and v.startswith(start)}
    return found


def next_identifier(session: "KgSession", kind: str, system: str, prefix: str, width: int) -> str:
    """The next value `<prefix><number>`, for example MRN-000002. Values with other forms do not count.

    `kind` is the class path (ids.TABLE_KIND gives it for a table name of the ports). Call it inside a write.
    """
    numbers = [n for n in (_number(v, prefix) for v in _values(session, kind, system, prefix)) if n is not None]
    return f"{prefix}{(max(numbers) if numbers else 0) + 1:0{width}d}"


def unique_identifier(session: "KgSession", kind: str, system: str, base: str) -> str:
    """`base`, or `base-2`, `base-3` ... if the value is in use (stored or in the buffer)."""
    used = _values(session, kind, system, base)
    value, n = base, 1
    while value in used:
        n += 1
        value = f"{base}-{n}"
    return value


def kinds_of(tables: Iterable[str]) -> list[str]:
    return [TABLE_KIND[t] for t in tables]
