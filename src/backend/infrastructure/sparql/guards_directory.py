"""The key guards (agent D): the UNIQUE constraints of SQLite, as Conflict (409) in the knowledge graph.

`owl:hasKey` infers owl:sameAs and gives no error (plan 1.5), so the app holds each key. A key guard looks at the
new subjects and the replaced values of a change, and finds a duplicate with one SELECT on the stored facts (and
in the change itself: two new rows with the same key). Error: unique_conflict(table, columns), the same text and
`fields.key` as SQLite, for example unique_conflict("Medication", ("Code", "CodeSystem")) gives
{"key": "Medication.Code, Medication.CodeSystem"}.

Two of these keys only the database enforces today (the Medication key and the client-given identifiers of a
department, a location and a staff member): test_api.py expects 409 for them.

How a guard compares the values (the same rule for a buffered value and a stored value, `plain`):
- an IRI is its text with no angle brackets; an integer is an int; text is text;
- a time is the output text of the store (D11): "Z" becomes "+00:00" and the trailing zeros of the seconds go.
  SQLite compares the text, and the stores drop these zeros, so two times that differ only in these zeros are
  the same key here (the store cannot keep the difference).
- A NULL (no value) is never a duplicate (as in SQLite UNIQUE).
The key of a stored subject that the change replaces is its value after the change. A stored subject that the
change deletes or changes is not compared with its stored values.

The lookups start with a bound value (VALUES at the start of the pattern), never with a constant that many
subjects share (README.md, rule 4).

Do not edit guards.py: add a guard here with @register(..., owner="D").
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

from infrastructure.sparql import ids, terms
from infrastructure.sparql.change import Change
from infrastructure.sparql.client import output_time
from infrastructure.sparql.guards import Facts, register, unique_conflict
from infrastructure.sparql.terms import Term, TermError

_TIME = re.compile(r"(?P<head>.*T\d{2}:\d{2}:\d{2})(?P<fraction>\.\d+)?(?P<zone>.*)")


def time_text(text: str) -> str:
    """The form of a time as the stores give it: "+00:00" for "Z", no trailing zeros of the seconds."""
    text = output_time(text)
    match = _TIME.fullmatch(text)
    if not match:
        return text
    fraction = (match["fraction"] or "").rstrip("0")
    return match["head"] + ("" if fraction == "." else fraction) + match["zone"]


def iri_text(value: str) -> str:
    return value[1:-1] if value.startswith("<") and value.endswith(">") else value


_LITERAL = re.compile(r'"(?P<text>(?:[^"\\]|\\.)*)"(?:\^\^<[^>]*>|@[A-Za-z0-9-]+)?')
_UNESCAPE = {"\\\\": "\\", '\\"': '"', "\\n": "\n", "\\r": "\r", "\\t": "\t", "\\b": "\b", "\\f": "\f"}


def plain(prop: str, value: Any) -> Any:
    """The comparable form of a value of `prop` (see the module text). None stays None."""
    if value is None:
        return None
    if isinstance(value, Term):
        literal = _LITERAL.fullmatch(value)
        if literal is None:
            return iri_text(value)
        value = re.sub(r"\\.", lambda m: _UNESCAPE.get(m.group(0), m.group(0)), literal["text"])
    if prop in terms.OBJECT_PROPERTIES:
        return iri_text(str(value))
    datatype = terms.DATATYPES.get(prop)
    if datatype == "dateTime":
        return time_text(str(value))
    if datatype == "integer" and not isinstance(value, bool):
        return int(value)
    if datatype == "boolean":
        return value if isinstance(value, bool) else str(value) in ("true", "1")
    return value if isinstance(value, (int, bool)) else str(value)


def sparql_value(prop: str, value: Any) -> Term:
    """The SPARQL term of a plain value of `prop` (for a VALUES block)."""
    if prop in terms.OBJECT_PROPERTIES:
        return Term(f"<{value}>")
    return terms.value_of(prop, value)


def values_block(prop: str, values: Iterable[Any]) -> Term:
    """The values of a VALUES block, with spaces (VALUES has no commas)."""
    return Term(" ".join(sparql_value(prop, v) for v in sorted(set(values), key=str)))


def is_kind(value: str, kind: str) -> bool:
    try:
        return terms.split_iri(value)[0] == kind
    except TermError:
        return False


def no_twins(keys: Mapping[str, tuple], table: str, columns: Sequence[str]) -> None:
    """Two subjects of the change with the same key: the error of the second INSERT in SQLite."""
    if len(set(keys.values())) < len(keys):
        raise unique_conflict(table, columns)


# ---------------------------------------------------------------------------------------------
# The key values of the subjects that a change makes or changes

STORED_VALUES = """
SELECT ?x ?p ?o FROM $abox WHERE {
  VALUES ?x { $subjects }
  ?x ?p ?o .
  FILTER (?p IN ($props))
}"""


def final_values(change: Change, facts: Facts, kind: str, props: Sequence[str]) -> dict[str, dict[str, Any]]:
    """{subject: {property: plain value}} after the change, for each new subject of the kind and each stored subject
    of the kind whose key properties the change replaces. One SELECT, only if the change replaces a key property.
    A replace of a subject that does not exist writes nothing, so that subject is not in the result."""
    out = {iri_text(new.iri): {p: plain(p, new.get(p)) for p in props} for new in change.created(kind)}
    replaced = [r for r in change.replaced(kind) if r.prop in props]
    if not replaced:
        return out
    subjects = sorted({r.subject for r in replaced})
    wanted = [Term(f"<{terms.RDF_TYPE}>"), *(terms.property_term(p) for p in props)]
    stored: dict[str, dict[str, Any]] = {}
    for row in facts.select(STORED_VALUES, {"subjects": Term(" ".join(subjects)), "props": terms.term_list(wanted)}):
        values = stored.setdefault(row["x"], {})      # the rdf:type row: the subject exists
        if row["p"] != terms.RDF_TYPE:
            name = terms.name_of(row["p"])
            values.setdefault(name, plain(name, row["o"]))
    for r in replaced:
        values = stored.get(iri_text(r.subject))
        if values is not None:
            values[r.prop] = plain(r.prop, r.values[0]) if r.values else None
    out.update({x: {p: values.get(p) for p in props} for x, values in stored.items()})
    return out


def lookup(props: Sequence[str], anchor: str) -> str:
    """The SELECT of the stored subjects with an anchor value: ?x and one variable for each property."""
    others = " ; ".join(f"triad:{p} ?{p}" for p in props if p != anchor)
    pattern = f"?x triad:{anchor} ?{anchor}" + (f" ; {others}" if others else "")
    return (f"SELECT ?x {' '.join('?' + p for p in props)} FROM $abox WHERE {{\n"
            f"  VALUES ?{anchor} {{ $anchors }}\n  {pattern} .\n}}")


def own_key(change: Change, facts: Facts, kind: str, props: Sequence[str], table: str, columns: Sequence[str],
            anchor: str) -> None:
    """A key of the values of the subject itself (for example Medication (code, codeSystem))."""
    keys = {x: tuple(v[p] for p in props) for x, v in final_values(change, facts, kind, props).items()}
    keys = {x: key for x, key in keys.items() if None not in key}
    if not keys:
        return
    no_twins(keys, table, columns)
    wanted = set(keys.values())
    position = list(props).index(anchor)
    rows = facts.select(lookup(props, anchor), {"anchors": values_block(anchor, (k[position] for k in wanted))})
    for row in rows:
        x = row["x"]
        if x in keys or change.is_deleted(x) or not is_kind(x, kind):
            continue
        if tuple(plain(p, row[p]) for p in props) in wanted:
            raise unique_conflict(table, columns)


def child_keys(change: Change, facts: Facts, kind: str, link: str, keys: Sequence[tuple[Sequence[str], str,
                                                                                            Sequence[str]]]) -> None:
    """The keys (parent, values...) of a child whose parent links to it with the reverse-direction property
    `link` (for example <message> triad:contains <assertion>: Assertion (MessageId, Seq)).

    `keys` is a list of (properties, table, columns). One SELECT reads the stored children of the stored parents.
    """
    news = []
    for new in change.created(kind):
        parents = [subject for subject, _ in change.links_to(new.iri, link)]
        if parents:
            news.append((iri_text(new.iri), iri_text(parents[0]), new))
    if not news:
        return
    found = []
    for key_props, table, columns in keys:
        made = {x: (parent, *(plain(p, new.get(p)) for p in key_props)) for x, parent, new in news}
        made = {x: key for x, key in made.items() if None not in key}
        no_twins(made, table, columns)
        found.append((key_props, table, columns, made))
    stored_parents = sorted({parent for _, parent, _ in news if not change.is_new(parent)})
    if not stored_parents:
        return
    every = sorted({p for key_props, _, _ in keys for p in key_props})
    optionals = "\n".join(f"  OPTIONAL {{ ?x triad:{p} ?{p} }}" for p in every)
    template = (f"SELECT ?parent ?x {' '.join('?' + p for p in every)} FROM $abox WHERE {{\n"
                f"  VALUES ?parent {{ $parents }}\n  ?parent triad:{link} ?x .\n{optionals}\n}}")
    rows = facts.select(template, {"parents": Term(" ".join(f"<{p}>" for p in stored_parents))})
    for key_props, table, columns, made in found:
        wanted = set(made.values())
        for row in rows:
            if row["x"] in made or change.is_deleted(row["x"]):
                continue
            if (row["parent"], *(plain(p, row[p]) for p in key_props)) in wanted:
                raise unique_conflict(table, columns)


# ---------------------------------------------------------------------------------------------
# The guards

@register("key.medication", kinds=("medication",), owner="D")
def medication_key(change: Change, facts: Facts) -> None:
    """UK_Medication_Code_CodeSystem: (code, codeSystem). unique_conflict("Medication", ("Code", "CodeSystem")).

    The code is the anchor; a clinical entry has a code too, so the kind of each stored subject is checked."""
    own_key(change, facts, "medication", ("code", "codeSystem"), "Medication", ("Code", "CodeSystem"), "code")


IDENTIFIER_KINDS = ("department", "location", "staff", "visit", "clinical-entry", "message", "chat-session",
                    "audit-event", "patient-identifier")
IDENTIFIER_PROPS = ("identifierSystem", "identifierValue")
IDENTIFIER_LOOKUP = """
SELECT ?x ?system ?value FROM $abox WHERE {
  VALUES ?value { $values }
  ?x triad:identifierValue ?value ; triad:identifierSystem ?system .
}"""


def identifier_conflict(kind: str):
    table = ids.KIND_TABLE[kind]
    return unique_conflict(table, ("System", "Value") if table == "PatientIdentifier"
                           else ("IdentifierSystem", "IdentifierValue"))


@register("key.identifier", kinds=IDENTIFIER_KINDS, owner="D")
def identifier_key(change: Change, facts: Facts) -> None:
    """UK_<Table>_Identifier: (identifierSystem, identifierValue) of each kind of the list. The client gives the
    identifiers of a department, a location and a staff member; the app makes the others (ids.next_identifier).
    The table of a kind is ids.KIND_TABLE[kind]; PatientIdentifier has the columns (System, Value).

    One SELECT for all kinds: the stored subjects with one of the new identifier values."""
    keys: dict[str, tuple[str, str, str]] = {}
    for kind in IDENTIFIER_KINDS:
        if kind not in change.kinds():
            continue
        for x, values in final_values(change, facts, kind, IDENTIFIER_PROPS).items():
            system, value = values["identifierSystem"], values["identifierValue"]
            if system is not None and value is not None:
                keys[x] = (kind, system, value)
    if not keys:
        return
    seen: dict[tuple[str, str, str], str] = {}
    for x, key in keys.items():
        if key in seen:
            raise identifier_conflict(key[0])
        seen[key] = x
    rows = facts.select(IDENTIFIER_LOOKUP, {"values": values_block("identifierValue", (k[2] for k in seen))})
    for row in rows:
        x = row["x"]
        if x in keys or change.is_deleted(x):
            continue
        try:
            kind = terms.split_iri(x)[0]
        except TermError:
            continue
        if (kind, row["system"], row["value"]) in seen:
            raise identifier_conflict(kind)


@register("key.patient", kinds=("patient",), owner="D")
def patient_key(change: Change, facts: Facts) -> None:
    """UK_Patient_Name_DateOfBirth: (name, dateOfBirth). unique_conflict("Patient", ("Name", "DateOfBirth"))."""
    own_key(change, facts, "patient", ("name", "dateOfBirth"), "Patient", ("Name", "DateOfBirth"), "name")


@register("key.assertion", kinds=("assertion",), owner="D")
def assertion_keys(change: Change, facts: Facts) -> None:
    """UK_Assertion_SupersedesId (one new assertion for each old one) and UK_Assertion_MessageId_Seq
    (message, seq). The DDL has the (message, seq) key first, so it is checked first."""
    child_keys(change, facts, "assertion", "contains", [(("seq",), "Assertion", ("MessageId", "Seq"))])
    own_key(change, facts, "assertion", ("supersedes",), "Assertion", ("SupersedesId",), "supersedes")


@register("key.chat-turn", kinds=("chat-turn",), owner="D")
def chat_turn_keys(change: Change, facts: Facts) -> None:
    """The keys of ChatTurn: (session, seq) and (session, clientTurnId). A turn with no clientTurnId has no
    second key (NULL)."""
    child_keys(change, facts, "chat-turn", "includes", [(("seq",), "ChatTurn", ("ChatSessionId", "Seq")),
                                                       (("clientTurnId",), "ChatTurn",
                                                        ("ChatSessionId", "ClientTurnId"))])


LANGUAGES = """
SELECT ?s ?language FROM $abox WHERE {
  VALUES ?s { $staff }
  ?s triad:language ?language .
}"""


def language_key(change: Change, facts: Facts) -> None:
    """UK_StaffLanguage_StaffId_Language: a staff member has each language one time. In the graph, two equal
    triples are one triple, so the guard looks at the lists of the change: a new staff member, a replaced list,
    and the languages that the change adds to a stored staff member."""
    error = unique_conflict("StaffLanguage", ("StaffId", "Language"))
    for new in change.created("staff"):
        languages = new.all("language")
        if len(set(languages)) < len(languages):
            raise error
    replaced = {r.subject: list(r.values) for r in change.replaced("staff") if r.prop == "language"}
    for languages in replaced.values():
        if len(set(languages)) < len(languages):
            raise error
    added: dict[str, list[str]] = {}
    for a in change.added("language"):
        added.setdefault(a.subject, []).append(a.value)
    if not added:
        return
    stored: dict[str, set[str]] = {}
    without_replace = sorted(s for s in added if s not in replaced)
    if without_replace:
        for row in facts.select(LANGUAGES, {"staff": Term(" ".join(without_replace))}):
            stored.setdefault(f"<{row['s']}>", set()).add(row["language"])
    for subject, languages in added.items():
        before = set(replaced[subject]) if subject in replaced else stored.get(subject, set())
        if len(set(languages)) < len(languages) or before & set(languages):
            raise error


@register("key.association", kinds=("works-in", "visit-location", "citation", "care-team-member", "staff"),
          owner="D")
def association_keys(change: Change, facts: Facts) -> None:
    """The keys of the association classes: WorksIn (staff, department, roleCode), VisitLocation (visit,
    location, startDate), Citation (turn, assertion), CareTeamMember (care team, memberSystem, memberValue);
    and StaffLanguage (staff, language) for triad:language (so the guard runs for a change of a staff member too)."""
    kinds = change.kinds()
    if "works-in" in kinds:
        own_key(change, facts, "works-in", ("ofStaff", "atDepartment", "roleCode"), "WorksIn",
                ("StaffId", "DepartmentId", "RoleCode"), "ofStaff")
    if "visit-location" in kinds:
        own_key(change, facts, "visit-location", ("ofVisit", "atLocation", "startDate"), "VisitLocation",
                ("VisitId", "LocationId", "StartDate"), "ofVisit")
    if "citation" in kinds:
        own_key(change, facts, "citation", ("byTurn", "citedAssertion"), "Citation", ("ChatTurnId", "AssertionId"),
                "byTurn")
    if "care-team-member" in kinds:
        child_keys(change, facts, "care-team-member", "member",
                   [(("memberSystem", "memberValue"), "CareTeamMember", ("CareTeamId", "MemberSystem",
                                                                          "MemberValue"))])
    if "staff" in kinds:
        language_key(change, facts)
