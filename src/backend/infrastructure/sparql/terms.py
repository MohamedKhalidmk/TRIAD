"""SPARQL terms and templates: the one escape function, the IRIs of the individuals and the ontology terms.

The SPARQL Protocol has no bound parameters, so each value goes into the text of the request. These rules
prevent SPARQL injection (plan 5, section 5.2, and the SPARQL writing rules 3, 4 and 7):

- A query or an update is a TEMPLATE and a dict of BINDINGS. A template is text of the code, never of the user.
  "$name" in a template is a placeholder. render() replaces each placeholder with the SPARQL form of its value.
  So a template never uses "$" for a SPARQL variable: write "?x", not "$x".
- literal() is the only function that writes a literal. Text is a simple literal ("..."), never ^^xsd:string:
  on Virtuoso the two forms do not match each other. A date, a dateTime, an integer and a boolean get their
  xsd datatype. literal() escapes the backslash, the double quote and the line breaks with the ECHAR escapes
  of the SPARQL grammar. It never writes a \\u escape: a store reads the \\u escapes of the request before
  it parses the text, so "\\u0022" in a value would close the literal (a test shows this on Oxigraph).
- iri(kind, id) writes the full IRI of an individual (rule 3: a prefixed name such as kg:patient/42 is not valid
  SPARQL). It accepts only a class path of the list KINDS and an integer id.
- term(name) writes an ontology term (a class or a property). The name must be a plain identifier.

The log of the SPARQL requests shows the template (with the "$name" placeholders), not the values.
This module imports no RDF library.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Optional

from infrastructure.rdf.namespaces import ABOX_GRAPH, KG, META_GRAPH, SCRATCH_GRAPH, TBOX_GRAPH, TRIAD
from models.semantic import vocabulary as V

XSD = "http://www.w3.org/2001/XMLSchema#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

# The PREFIX lines that render() puts before each request. Templates can use triad:, xsd: and rdf: names.
# There is no kg: prefix on purpose: an individual is always a full IRI (iri()).
PROLOGUE = (f"PREFIX triad: <{TRIAD}>\n"
            f"PREFIX xsd: <{XSD}>\n"
            "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n")

# The class path of each kind of individual (plan 1.1): KG + "<kind>/<Id>". 17 kinds.
KINDS: tuple[str, ...] = tuple(sorted(set(V.CLASS_PATHS.values())))
CLASS_OF_KIND: dict[str, str] = {path: cls for cls, path in V.CLASS_PATHS.items()}
CLASSES: frozenset[str] = frozenset(V.TABLE_CLASS.values())

# The datatype of each datatype property that is not text (from the rr:datatype of the R2RML mapping;
# a test compares the two). A property that is not in this map holds simple literals (text).
DATATYPES: dict[str, str] = {
    **dict.fromkeys(("startDate", "endDate", "recordedAt", "onsetDate", "abatementDate", "performedDate",
                     "issuedDate", "sentAt", "assertedAt", "startedAt", "createdAt", "at"), "dateTime"),
    **dict.fromkeys(("dateOfBirth", "subjectDateOfBirth", "roleStartDate", "roleEndDate"), "date"),
    "seq": "integer", "rank": "integer", "active": "boolean",
}
# The properties of the meta graph (the id counters and the build marker). They are not in the ontology.
META_PROPERTIES: dict[str, Optional[str]] = {
    "issued": "integer", "dataHash": None, "mappingHash": None, "ontologyVersion": None, "scope": None,
    "builtAt": "dateTime",
}
ATTRIBUTES: frozenset[str] = frozenset(V.attribute_properties())
OBJECT_PROPERTIES: frozenset[str] = frozenset(V.stored_object_properties())
PROPERTIES: frozenset[str] = ATTRIBUTES | OBJECT_PROPERTIES

_NAME = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_PLACEHOLDER = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DATE_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?")
_INTEGER = re.compile(r"[+-]?\d+")
_ECHAR = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t", "\b": "\\b", "\f": "\\f"}
_ESCAPED = re.compile(r'[\\"\n\r\t\b\f]')


class TermError(ValueError):
    """A value cannot become a SPARQL term (for example a date that is not YYYY-MM-DD).

    The unit of work changes this error into Invalid (422), as SQLite does for a failed CHECK.
    """


class Term(str):
    """A SPARQL term or a piece of SPARQL text that the code made. render() writes it as it is.

    Only the functions of this module make a Term from a value. A plain str value is always text (a literal).
    """
    __slots__ = ()


def escape(text: str) -> str:
    """The body of a SPARQL string literal: the ECHAR escapes for \\ " and the line breaks, no \\u escape."""
    return _ESCAPED.sub(lambda m: _ECHAR[m.group(0)], text)


def literal(value: Any, datatype: Optional[str] = None) -> Term:
    """The SPARQL literal of a Python value. This is the only escape function.

    - str with no datatype: a simple literal "...";
    - str with datatype "date" (YYYY-MM-DD), "dateTime" (ISO 8601) or "integer": a typed literal. The text of a
      date or a dateTime does not change (D11: keep the source form);
    - bool: "true" or "false" as xsd:boolean; int: xsd:integer.
    Raise TermError for None, a float, or a text that is not a correct date, dateTime or integer.
    """
    if isinstance(value, Term):
        raise TermError("A Term is not a value. Give it to render() as it is.")
    if value is None:
        raise TermError("A SPARQL value cannot be None. Leave the triple or the pattern out.")
    if isinstance(value, bool):
        if datatype not in (None, "boolean"):
            raise TermError(f"A boolean is not an xsd:{datatype}.")
        return typed("true" if value else "false", "boolean")
    if isinstance(value, int):
        if datatype == "boolean" and value in (0, 1):   # SQLite keeps a boolean as 0 or 1
            return typed("true" if value else "false", "boolean")
        if datatype not in (None, "integer"):
            raise TermError(f"The integer {value} is not an xsd:{datatype}.")
        return typed(str(value), "integer")
    if not isinstance(value, str):
        raise TermError(f"A SPARQL value must be text, an integer or a boolean, not {type(value).__name__}.")
    if datatype is None or datatype == "string":
        return Term(f'"{escape(value)}"')
    return typed(value, datatype)


def typed(text: str, datatype: str) -> Term:
    """A typed literal "text"^^<xsd:datatype>. The text must be a correct form of the datatype."""
    checks = {"date": _DATE, "dateTime": _DATE_TIME, "integer": _INTEGER}
    if datatype == "boolean":
        if text not in ("true", "false", "1", "0"):
            raise TermError(f'"{text}" is not an xsd:boolean.')
    elif datatype in checks:
        if not checks[datatype].fullmatch(text):
            raise TermError(f'"{text}" is not an xsd:{datatype}.')
    else:
        raise TermError(f"The datatype xsd:{datatype} is not in the list (date, dateTime, integer, boolean).")
    return Term(f'"{escape(text)}"^^<{XSD}{datatype}>')


def date(text: str) -> Term:
    """An xsd:date literal (YYYY-MM-DD), for example a date of birth in a query."""
    return typed(text, "date")


def date_time(text: str) -> Term:
    """An xsd:dateTime literal. The text keeps its offset (D11)."""
    return typed(text, "dateTime")


def value_of(prop: str, value: Any) -> Term:
    """The object term of a triple with the property `prop`: an IRI as it is, else a literal of its datatype."""
    if isinstance(value, Term):
        return value
    if prop in OBJECT_PROPERTIES:
        raise TermError(f"The value of triad:{prop} must be an IRI (iri(kind, id)), not {value!r}.")
    return literal(value, DATATYPES.get(prop, META_PROPERTIES.get(prop)))


def term(name: str) -> Term:
    """An ontology term in full: <...triad#name>. The name must be a plain identifier (a class or a property)."""
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise TermError(f"{name!r} is not the name of an ontology term.")
    return Term(f"<{TRIAD}{name}>")


def class_term(name: str) -> Term:
    """A class of the ontology (Patient, Doctor, ...). Raise TermError for a name that is not a TRIAD class."""
    if name not in CLASSES:
        raise TermError(f"{name!r} is not a class of the TRIAD ontology.")
    return term(name)


def property_term(name: str) -> Term:
    """A stored property of the ontology. Raise TermError for a name that the data does not use."""
    if name not in PROPERTIES and name not in META_PROPERTIES:
        raise TermError(f"{name!r} is not a stored property of the TRIAD ontology.")
    return term(name)


def iri(kind: str, id_: int) -> Term:
    """The full IRI of an individual: <https://github.com/MohamedKhalidmk/TRIAD/kg/<kind>/<id>>.

    `kind` is a class path of KINDS (patient, staff, assertion, ...). `id_` is an integer, not text.
    """
    if kind not in KINDS:
        raise TermError(f"{kind!r} is not a class path. Use one of: {', '.join(KINDS)}.")
    if isinstance(id_, bool) or not isinstance(id_, int) or id_ < 0:
        raise TermError(f"The id of an individual must be an integer of 0 or more, not {id_!r}.")
    return Term(f"<{KG}{kind}/{id_}>")


def iri_text(kind: str, id_: int) -> str:
    """The IRI of an individual without the angle brackets (as the client gives it in a row)."""
    return iri(kind, id_)[1:-1]


_IRI = re.compile(re.escape(KG) + r"(?P<kind>[a-z][a-z-]*)/(?P<id>\d+)")


def split_iri(value: str) -> tuple[str, int]:
    """(kind, id) of the IRI of an individual (with or without the angle brackets)."""
    text = value[1:-1] if value.startswith("<") and value.endswith(">") else value
    match = _IRI.fullmatch(text)
    if not match or match["kind"] not in KINDS:
        raise TermError(f"{value!r} is not the IRI of a TRIAD individual.")
    return match["kind"], int(match["id"])


def id_of(value: Optional[str], kind: Optional[str] = None) -> Optional[int]:
    """The integer id of an individual IRI, or None for None. With `kind`, the IRI must be of that kind."""
    if value is None:
        return None
    found, number = split_iri(value)
    if kind is not None and found != kind:
        raise TermError(f"{value!r} is a {found}, not a {kind}.")
    return number


def kind_of(value: str) -> str:
    return split_iri(value)[0]


def name_of(value: str) -> str:
    """The local name of an ontology term IRI: <...triad#Doctor> or ...triad#Doctor -> 'Doctor'."""
    text = value[1:-1] if value.startswith("<") else value
    if not text.startswith(TRIAD):
        raise TermError(f"{value!r} is not a TRIAD term.")
    return text[len(TRIAD):]


def term_list(values: Iterable[Any], datatype: Optional[str] = None) -> Term:
    """A list of terms for IN ( ... ) or VALUES { ... }: Terms as they are, other values as literals."""
    items = [v if isinstance(v, Term) else literal(v, datatype) for v in values]
    if not items:
        raise TermError("A list of SPARQL values cannot be empty.")
    return Term(", ".join(items))


def iri_values(iris: Iterable[str]) -> Term:
    """The IRIs of individuals for a VALUES block: <a> <b> ... (VALUES has no commas). The values are IRI texts,
    with or without the angle brackets; each one is made again from its kind and id (only TRIAD individuals).

    A block with ONE IRI also gets the IRI of id 0 of the same kind (no individual has id 0, so it matches no
    triple). Virtuoso 7.2 compiles each new query text, and with one value in VALUES it puts the constant into
    the plan: the assertion view of one assertion took about 300 ms to compile, with two values 50 ms. The
    pattern after VALUES must need a triple of the variable (then the padding IRI gives no row)."""
    found = [iri(*split_iri(v)) for v in iris]
    if not found:
        raise TermError("A list of SPARQL values cannot be empty.")
    if len(found) == 1:
        found.append(iri(split_iri(found[0])[0], 0))
    return Term(" ".join(found))


# The graph placeholders that each template can use without a binding.
GRAPH_BINDINGS: dict[str, Term] = {
    "abox": Term(f"<{ABOX_GRAPH}>"), "tbox": Term(f"<{TBOX_GRAPH}>"), "meta": Term(f"<{META_GRAPH}>"),
    "scratch": Term(f"<{SCRATCH_GRAPH}>"),
}


def bound_term(name: str, value: Any) -> Term:
    """The SPARQL text of one binding: a Term as it is, a list as term_list(), any other value as literal()."""
    if isinstance(value, Term):
        return value
    if isinstance(value, (list, tuple, set, frozenset)):
        return term_list(sorted(value) if isinstance(value, (set, frozenset)) else value)
    try:
        return literal(value)
    except TermError as error:
        raise TermError(f"${name}: {error}") from None


def placeholders(template: str) -> list[str]:
    """The placeholder names of a template, in order of their first place."""
    return list(dict.fromkeys(_PLACEHOLDER.findall(template)))


def render(template: str, bindings: Optional[Mapping[str, Any]] = None, prologue: bool = True) -> str:
    """The text of a request: the PREFIX lines, then the template with the SPARQL form of each binding.

    Each "$name" of the template needs a binding (or is a graph: $abox, $tbox, $meta, $scratch). A missing
    binding raises KeyError. The replacement is one pass, so a value cannot add a placeholder.
    """
    values = dict(GRAPH_BINDINGS)
    values.update(bindings or {})

    def replace(match: re.Match) -> str:
        name = match.group(1)
        if name not in values:
            raise KeyError(f"The SPARQL template needs a value for ${name}.")
        return bound_term(name, values[name])

    text = _PLACEHOLDER.sub(replace, template)
    return PROLOGUE + text if prologue else text
