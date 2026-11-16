#!/usr/bin/env python3
"""Check the TRIAD ontology (triad.ttl) and write triad.owl (RDF/XML).

Run it from the root folder of the repository:
    .venv/bin/python src/backend/models/semantic/build_ontology.py             # check, then write triad.owl
    .venv/bin/python src/backend/models/semantic/build_ontology.py --check     # check; stop if triad.owl is old
    .venv/bin/python src/backend/models/semantic/build_ontology.py --direct-mapping-example [--db PATH] [--assertion ID]
    .venv/bin/python src/backend/models/semantic/build_ontology.py --compare /tmp/triad_protege.owl   # Protégé re-save

The checks (each one stops with a clear message):
    coverage    each table, column, foreign key and UNIQUE constraint of 01_create_tables.sql maps to a term,
                or vocabulary.py gives the reason; NOT NULL columns have a cardinality restriction;
    tree        the stored object properties and the subclass edges make a tree (the check of build_erd.py);
    OWL 2 DL    the datatype map (no xsd:date), the simple-property rule, one domain and one range per property,
                no closed range on a shared property, one declaration per term, the value sets of the DDL;
    labels      each class and property has rdfs:label, rdfs:comment and rdfs:isDefinedBy.

triad.owl is deterministic: the script makes the blank nodes canonical (rdflib), sorts the triples and writes
RDF/XML with pyoxigraph 0.3. The rdflib RDF/XML writers change literals ("pretty-xml") or the bytes ("xml").
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import pyoxigraph as ox
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection
from rdflib.compare import graph_diff, to_canonical_graph, to_isomorphic
from rdflib.namespace import OWL, RDF, RDFS, XSD

try:
    from models.semantic import vocabulary as V
except ImportError:  # run as a script: this folder is on sys.path
    import vocabulary as V

HERE = Path(__file__).resolve().parent
TTL_PATH = HERE / "triad.ttl"
OWL_PATH = HERE / "triad.owl"
SQL_DIR = HERE.parents[0] / "relational" / "sql"
DDL_PATH = SQL_DIR / "ddl" / "01_create_tables.sql"
SEED_PATH = SQL_DIR / "dml" / "02_insert_seed.sql"
BUILD_ERD_PATH = HERE.parents[0] / "er" / "build_erd.py"

TRIAD = Namespace(V.TRIAD)
PROV = Namespace(V.PREFIXES["prov"])
DCTERMS = Namespace(V.PREFIXES["dcterms"])
SKOS = Namespace(V.PREFIXES["skos"])
ONTOLOGY = URIRef(V.ONTOLOGY_IRI)
PROV_O = URIRef("http://www.w3.org/ns/prov-o#")

# The OWL 2 datatype map (OWL 2 Structural Specification, section 4). xsd:date is not in it.
OWL2_DATATYPES = {URIRef(XSD + n) for n in (
    "decimal integer nonNegativeInteger nonPositiveInteger positiveInteger negativeInteger long int short byte "
    "unsignedLong unsignedInt unsignedShort unsignedByte double float string normalizedString token language "
    "Name NCName NMTOKEN boolean hexBinary base64Binary anyURI dateTime dateTimeStamp").split()} | {
    OWL.real, OWL.rational, RDF.PlainLiteral, RDF.XMLLiteral, RDFS.Literal, RDF.langString}
FACETS = {URIRef(XSD + n) for n in
          "minInclusive maxInclusive minExclusive maxExclusive length minLength maxLength pattern".split()}

DECLARATION_TYPES = {OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty,
                     RDFS.Datatype, OWL.NamedIndividual}
CHECKED_NAMESPACES = (V.TRIAD, str(PROV), str(DCTERMS), str(SKOS))

# Axioms that OWL 2 DL allows only on a simple property (section 11.2).
SIMPLE_ONLY_TYPES = {OWL.FunctionalProperty, OWL.InverseFunctionalProperty, OWL.IrreflexiveProperty,
                     OWL.AsymmetricProperty}
CARDINALITIES = {OWL.cardinality: "exact", OWL.minCardinality: "min", OWL.maxCardinality: "max",
                 OWL.qualifiedCardinality: "exact", OWL.minQualifiedCardinality: "min",
                 OWL.maxQualifiedCardinality: "max"}
QUALIFIED = {OWL.qualifiedCardinality, OWL.minQualifiedCardinality, OWL.maxQualifiedCardinality}

# UNIQUE constraints of the DDL that give no owl:hasKey, with the reason (ontology.md section 7).
UNIQUE_NOT_KEY = {
    ("Staff", ("Id", "Role")): "The target of the composite FK of the subtypes. The Id is in the IRI.",
    ("ClinicalEntry", ("Id", "Category")): "The target of the composite FK of the subtypes. The Id is in the IRI.",
    ("StaffLanguage", ("StaffId", "Language")): "A graph holds each triple once, so a language cannot repeat.",
    ("Assertion", ("SupersedesId",)): "owl:InverseFunctionalProperty on triad:supersedes.",
    **{(t, (fk,)): "The subtype row is the same individual as its parent row." for t, (fk, _) in
       V.SUBTYPE_TABLES.items()},
}


class CheckError(Exception):
    """A check failed. The message says what to change."""


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_graph(path: Path = TTL_PATH) -> Graph:
    try:
        return Graph().parse(path, format="turtle")
    except Exception as exc:  # rdflib raises several types for a syntax error
        raise CheckError(f"{path.name} is not valid Turtle: {exc}") from exc


def ddl_connection(ddl_path: Path = DDL_PATH) -> sqlite3.Connection:
    """An in-memory database made by the DDL script 01 (no data)."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(ddl_path.read_text(encoding="utf-8"))
    return conn


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Small helpers on the graph
# ---------------------------------------------------------------------------

def local(term) -> str:
    text = str(term)
    for prefix, ns in V.PREFIXES.items():
        if text.startswith(ns):
            return text[len(ns):] if prefix == "triad" else f"{prefix}:{text[len(ns):]}"
    return text


def triad_terms(g: Graph, rdf_type: URIRef) -> set[URIRef]:
    return {s for s in g.subjects(RDF.type, rdf_type) if isinstance(s, URIRef) and str(s).startswith(V.TRIAD)}


def classes(g: Graph) -> set[URIRef]:
    return triad_terms(g, OWL.Class)


def object_properties(g: Graph) -> set[URIRef]:
    return triad_terms(g, OWL.ObjectProperty)


def datatype_properties(g: Graph) -> set[URIRef]:
    return triad_terms(g, OWL.DatatypeProperty)


def named_inverses(g: Graph) -> dict[URIRef, URIRef]:
    """A named inverse -> its stored property (the subject of owl:inverseOf is the named inverse)."""
    return {s: o for s, o in g.subject_objects(OWL.inverseOf) if isinstance(s, URIRef)}


def derived_properties(g: Graph) -> set[URIRef]:
    return set(g.subjects(OWL.propertyChainAxiom, None)) | set(g.subjects(RDF.type, OWL.TransitiveProperty))


def stored_properties(g: Graph) -> set[URIRef]:
    """The object properties that have triples in the store: not a named inverse, not derived."""
    return object_properties(g) - set(named_inverses(g)) - derived_properties(g)


def domain_classes(g: Graph, prop: URIRef) -> set[URIRef]:
    """The classes of the rdfs:domain: one named class, or the members of an owl:unionOf."""
    result: set[URIRef] = set()
    for d in g.objects(prop, RDFS.domain):
        union = g.value(d, OWL.unionOf)
        result |= set(Collection(g, union)) if union is not None else {d}
    return result


def is_closed_range(g: Graph, prop: URIRef) -> bool:
    return any(g.value(r, OWL.oneOf) is not None for r in g.objects(prop, RDFS.range))


def closed_values(g: Graph, prop: URIRef) -> list[str]:
    for r in g.objects(prop, RDFS.range):
        one_of = g.value(r, OWL.oneOf)
        if one_of is not None:
            return [str(v) for v in Collection(g, one_of)]
    return []


def property_expression(g: Graph, node) -> tuple[URIRef, bool]:
    """(stored property, inverted). A named inverse and [ owl:inverseOf p ] both give (p, True)."""
    inverse_of = g.value(node, OWL.inverseOf)
    return (inverse_of, True) if inverse_of is not None else (node, False)


def restrictions(g: Graph) -> list[dict]:
    """Each owl:Restriction that is a superclass of a named class."""
    result = []
    for cls, r in g.subject_objects(RDFS.subClassOf):
        if (r, RDF.type, OWL.Restriction) not in g:
            continue
        on = g.value(r, OWL.onProperty)
        for pred, kind in CARDINALITIES.items():
            value = g.value(r, pred)
            if value is not None:
                result.append({"class": cls, "on": on, "expr": property_expression(g, on), "kind": kind,
                               "value": int(value), "qualified": pred in QUALIFIED,
                               "onClass": g.value(r, OWL.onClass)})
    return result


def keys(g: Graph) -> list[tuple[URIRef, tuple[URIRef, ...]]]:
    return [(cls, tuple(Collection(g, lst))) for cls, lst in g.subject_objects(OWL.hasKey)]


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_declarations(g: Graph) -> None:
    """Each TRIAD, PROV, DCTERMS and SKOS term that the ontology uses has exactly one declaration."""
    if (None, OWL.imports, None) in g:
        raise CheckError("The ontology must not use owl:imports. Declare the reused terms locally.")
    used = {t for triple in g for t in triple if isinstance(t, URIRef) and str(t).startswith(CHECKED_NAMESPACES)}
    errors = []
    for term in sorted(used):
        types = set(g.objects(term, RDF.type)) & DECLARATION_TYPES
        if len(types) != 1:
            names = ", ".join(sorted(local(t) for t in types)) or "none"
            errors.append(f"{local(term)} has {len(types)} declarations ({names}). It needs exactly one.")
    if errors:
        raise CheckError("Declarations:\n  " + "\n  ".join(errors))


def check_labels(g: Graph) -> None:
    """Each class and property has one rdfs:label, an rdfs:comment and rdfs:isDefinedBy."""
    errors = []
    for term in sorted(classes(g) | object_properties(g) | datatype_properties(g)):
        if len(set(g.objects(term, RDFS.label))) != 1:
            errors.append(f"{local(term)} needs exactly one rdfs:label.")
        if g.value(term, RDFS.comment) is None:
            errors.append(f"{local(term)} has no rdfs:comment.")
        if g.value(term, RDFS.isDefinedBy) != ONTOLOGY:
            errors.append(f"{local(term)} needs rdfs:isDefinedBy <{ONTOLOGY}>.")
    for term in sorted(t for t in set(g.subjects(RDF.type, None)) if str(t).startswith(str(PROV))):
        if g.value(term, RDFS.label) is None or g.value(term, RDFS.isDefinedBy) != PROV_O:
            errors.append(f"{local(term)} needs an rdfs:label and rdfs:isDefinedBy <{PROV_O}>.")
    if (ONTOLOGY, RDF.type, OWL.Ontology) not in g:
        errors.append(f"<{ONTOLOGY}> is not declared as owl:Ontology.")
    if g.value(ONTOLOGY, OWL.versionIRI) != URIRef(V.VERSION_IRI):
        errors.append(f"The ontology needs owl:versionIRI <{V.VERSION_IRI}>.")
    if str(g.value(ONTOLOGY, OWL.versionInfo)) != V.ONTOLOGY_VERSION:
        errors.append(f'The ontology needs owl:versionInfo "{V.ONTOLOGY_VERSION}".')
    for pred in (DCTERMS.title, DCTERMS.creator, DCTERMS.license, DCTERMS.source, RDFS.comment):
        if g.value(ONTOLOGY, pred) is None:
            errors.append(f"The ontology has no {local(pred)}.")
    if errors:
        raise CheckError("Labels and metadata:\n  " + "\n  ".join(errors))


def check_datatypes(g: Graph) -> None:
    """Each datatype in the TBox is in the OWL 2 datatype map. OWL 2 has no xsd:date."""
    errors = set()
    for s, p, o in g:
        for term in (s, o):
            if isinstance(term, URIRef) and str(term).startswith(str(XSD)) and term not in OWL2_DATATYPES:
                errors.add(f"{local(term)} is not in the "
                           f"OWL 2 datatype map (used by {local(s)}). For a date, use rdfs:Literal.")
            if isinstance(term, Literal) and term.datatype is not None and term.datatype not in OWL2_DATATYPES:
                errors.add(f"The literal {term!r} has a datatype that is not in the OWL 2 datatype map.")
        if str(p).startswith(str(XSD)) and p not in FACETS:
            errors.add(f"{p} is not a facet of OWL 2.")
    if errors:
        raise CheckError("Datatypes:\n  " + "\n  ".join(sorted(errors)))


def check_domains_ranges(g: Graph) -> None:
    """Each property has exactly one rdfs:domain and one rdfs:range (two domains mean the intersection)."""
    errors = []
    for prop in sorted(object_properties(g) | datatype_properties(g)):
        for pred in (RDFS.domain, RDFS.range):
            n = len(set(g.objects(prop, pred)))
            if n != 1:
                errors.append(f"{local(prop)} has {n} {local(pred)} axioms. Give exactly one "
                              f"(for a shared property, the owl:unionOf of its classes).")
    if errors:
        raise CheckError("Domains and ranges:\n  " + "\n  ".join(errors))


def columns_of(term: str) -> list[tuple[str, str]]:
    return [key for key, (t, _) in V.COLUMNS.items() if t == term]


def check_closed_ranges(g: Graph) -> None:
    """A property with a closed range (owl:oneOf) has exactly one column and one class (decision D10)."""
    errors = []
    for prop in sorted(datatype_properties(g)):
        if not is_closed_range(g, prop):
            continue
        n_columns = len(columns_of(local(prop)))
        if len(domain_classes(g, prop)) > 1 or n_columns > 1:
            errors.append(f"{local(prop)} has a closed range, but it is shared ({n_columns} columns, "
                          f"{len(domain_classes(g, prop))} classes). Give each column its own property.")
    if errors:
        raise CheckError("Closed ranges:\n  " + "\n  ".join(errors))


def ddl_value_set(conn: sqlite3.Connection, table: str, column: str) -> list[str] | None:
    """The text values of CHECK (<column> IN (...)) in the DDL of the table, or None."""
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()[0]
    match = re.search(rf"CHECK\s*\(\s*{column}\s+IN\s*\(([^)]*)\)\s*\)", sql)
    if not match:
        return None
    values = re.findall(r"'([^']*)'", match.group(1))
    return values or None  # Active IN (0, 1) has no text values: it becomes xsd:boolean


def check_value_sets(g: Graph, conn: sqlite3.Connection) -> None:
    """Each closed range equals the CHECK ... IN list of its column, and each such column has a closed range."""
    errors = []
    for (table, column), (term, kind) in sorted(V.COLUMNS.items()):
        if kind != V.ATTRIBUTE:
            continue
        ddl = ddl_value_set(conn, table, column)
        owl = closed_values(g, TRIAD[term])
        if ddl and owl != ddl:
            errors.append(f"{table}.{column}: the DDL allows {ddl}, but triad:{term} allows {owl or 'any value'}.")
        if owl and not ddl:
            errors.append(f"triad:{term} has a closed range, but {table}.{column} has no CHECK ... IN.")
    if errors:
        raise CheckError("Value sets:\n  " + "\n  ".join(errors))


def check_simple_properties(g: Graph) -> None:
    """No characteristic or cardinality on a non-simple property (OWL 2 Structural Specification, 11.1-11.2).

    A property is composite when it has a property chain or it is transitive. A property is non-simple when
    a composite property is below it in the sub-property hierarchy (with the inverses).
    """
    edges: dict[tuple, set[tuple]] = {}

    def add(a: tuple, b: tuple) -> None:
        edges.setdefault(a, set()).add(b)
        edges.setdefault((a[0], not a[1]), set()).add((b[0], not b[1]))

    for a, b in g.subject_objects(RDFS.subPropertyOf):
        add((a, False), (b, False))
    for a, b in g.subject_objects(OWL.inverseOf):
        if isinstance(a, URIRef):
            add((a, False), (b, True))
            add((b, True), (a, False))
    composite = derived_properties(g)
    non_simple = {(p, inv) for p in composite for inv in (False, True)}
    todo = list(non_simple)
    while todo:
        for nxt in edges.get(todo.pop(), ()):
            if nxt not in non_simple:
                non_simple.add(nxt)
                todo.append(nxt)
    non_simple_iris = {p for p, _ in non_simple}
    errors = []
    for prop in sorted(non_simple_iris):
        for rdf_type in sorted(set(g.objects(prop, RDF.type)) & SIMPLE_ONLY_TYPES):
            errors.append(f"{local(prop)} is not simple, so it cannot be {local(rdf_type)}.")
    for r in restrictions(g):
        if r["expr"] in non_simple or (r["on"], False) in non_simple:
            errors.append(f"{local(r['class'])}: a cardinality restriction on {local(r['on'])}, "
                          f"which is not simple.")
    if errors:
        raise CheckError("Simple properties:\n  " + "\n  ".join(errors))


def check_tree(g: Graph) -> tuple[int, int]:
    """The stored object properties and the subclass edges make a tree (one path between two classes).

    It uses the tree check of build_erd.py. The unary property supersedes is the only loop, as in the ER model.
    Returns (nodes, edges).
    """
    model = _load_module("build_erd", BUILD_ERD_PATH).Model()
    nodes = sorted(classes(g))
    for c in nodes:
        model.find(local(c))
    n_edges = 0
    try:
        for child, parent in sorted(g.subject_objects(RDFS.subClassOf)):
            if child in nodes and parent in nodes:
                model.join(local(child), local(parent), "rdfs:subClassOf")
                n_edges += 1
        for prop in sorted(stored_properties(g)):
            ends = [g.value(prop, RDFS.domain), g.value(prop, RDFS.range)]
            if not all(end in nodes for end in ends):
                raise CheckError(f"The stored property {local(prop)} must have a named TRIAD class "
                                 f"as its domain and as its range.")
            for end in ends:
                model.end(local(prop), local(end))
            n_edges += ends[0] != ends[1]
    except SystemExit as exc:  # build_erd.Model.join stops with sys.exit on a loop
        raise CheckError(f"Tree check: {exc.code}") from None
    parts: dict[str, list[str]] = {}
    for c in model.parent:
        parts.setdefault(model.find(c), []).append(c)
    if len(parts) != 1:
        listing = "; ".join(", ".join(sorted(m)) for m in parts.values())
        raise CheckError(f"Tree check: the classes are in {len(parts)} parts, not 1: {listing}")
    return len(nodes), n_edges


def _fk_map(conn: sqlite3.Connection, table: str) -> dict[tuple[str, ...], tuple[str, tuple[str, ...]]]:
    """(from columns) -> (target table, target columns) for each foreign key of the table."""
    groups: dict[int, list] = {}
    for fk_id, seq, target, frm, to, *_ in conn.execute(f"PRAGMA foreign_key_list({table})"):
        groups.setdefault(fk_id, []).append((seq, target, frm, to))
    result = {}
    for rows in groups.values():
        rows.sort()
        result[tuple(r[2] for r in rows)] = (rows[0][1], tuple(r[3] for r in rows))
    return result


def _unique_constraints(conn: sqlite3.Connection, table: str) -> list[tuple[str, ...]]:
    result = []
    for _, name, unique, origin, _ in conn.execute(f"PRAGMA index_list({table})"):
        if unique and origin == "u":
            result.append(tuple(r[2] for r in conn.execute(f"PRAGMA index_info({name})")))
    return sorted(result)


def check_coverage(g: Graph, conn: sqlite3.Connection) -> None:
    """Each table, column, FK and UNIQUE constraint of the DDL maps to the ontology, or has a reason."""
    errors: list[str] = []
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    ddl_columns: dict[tuple[str, str], bool] = {}
    for table in tables:
        if table not in V.SUBJECT:
            errors.append(f"The table {table} has no subject in vocabulary.SUBJECT.")
        for _, column, _, notnull, _, _ in conn.execute(f"PRAGMA table_info({table})"):
            ddl_columns[(table, column)] = bool(notnull)
    for key in sorted(ddl_columns):
        in_map, in_none = key in V.COLUMNS, key in V.NO_PROPERTY
        if not in_map and not in_none:
            errors.append(f"The column {key[0]}.{key[1]} maps to no property, and it has no reason in "
                          f"vocabulary.NO_PROPERTY.")
        if in_map and in_none:
            errors.append(f"The column {key[0]}.{key[1]} is in COLUMNS and in NO_PROPERTY.")
    for key in sorted(set(V.COLUMNS) | set(V.NO_PROPERTY)):
        if key not in ddl_columns:
            errors.append(f"vocabulary.py names {key[0]}.{key[1]}, but the DDL has no such column.")

    obj, dat = object_properties(g), datatype_properties(g)
    inverse_of = {stored: named for named, stored in named_inverses(g).items()}
    used: Counter = Counter()
    for (table, column), (term, kind) in sorted(V.COLUMNS.items()):
        if (table, column) not in ddl_columns:
            continue
        prop = TRIAD[term]
        used[prop] += 1
        row_class = TRIAD[V.TABLE_CLASS.get(table, "Staff")]  # StaffLanguage rows are triples on Staff
        if kind == V.ATTRIBUTE:
            if prop not in dat:
                errors.append(f"{table}.{column} -> triad:{term}, but triad:{term} is not a DatatypeProperty.")
            continue
        if prop not in obj:
            errors.append(f"{table}.{column} -> triad:{term}, but triad:{term} is not an ObjectProperty.")
            continue
        fk = _fk_map(conn, table).get((column,))
        if fk is None:
            errors.append(f"{table}.{column} -> triad:{term}, but the column is not a foreign key.")
            continue
        target_class = TRIAD[V.TABLE_CLASS[fk[0]]]
        dom, rng = (row_class, target_class) if kind == V.FK else (target_class, row_class)
        if g.value(prop, RDFS.domain) != dom or g.value(prop, RDFS.range) != rng:
            errors.append(f"{table}.{column} ({kind}) needs triad:{term} with the domain {local(dom)} and the "
                          f"range {local(rng)}.")
    # Each foreign key of the DDL is a stored property, or its columns have a reason.
    for table in tables:
        for frm, (target, _) in _fk_map(conn, table).items():
            if len(frm) == 1 and (table, frm[0]) in V.COLUMNS:
                continue
            for column in frm:
                if (table, column) not in V.NO_PROPERTY:
                    errors.append(f"The foreign key {table}({', '.join(frm)}) -> {target} has no property.")
    # The stored properties are exactly the properties of the FK columns.
    stored, from_columns = stored_properties(g), {TRIAD[t] for t in V.stored_object_properties()}
    for prop in sorted(stored ^ from_columns):
        errors.append(f"triad:{local(prop)}: the ontology and vocabulary.py disagree on whether it is stored.")
    for prop in sorted(from_columns):
        if used[prop] != 1:
            errors.append(f"triad:{local(prop)} must come from exactly one FK column, not {used[prop]}.")
    if {local(p) for p in named_inverses(g)} != set(V.NAMED_INVERSES):
        errors.append("The named inverses of the ontology and of vocabulary.NAMED_INVERSES differ.")
    for prop in sorted(dat):
        if used[prop] == 0:
            errors.append(f"triad:{local(prop)} has no column.")
            continue
        expected = {TRIAD[V.TABLE_CLASS.get(t, "Staff")] for t, _ in columns_of(local(prop))}
        if domain_classes(g, prop) != expected:
            errors.append(f"triad:{local(prop)}: the domain must be "
                          f"{' or '.join(sorted(local(c) for c in expected))} (its columns).")

    errors += _check_cardinality(g, ddl_columns, inverse_of)
    errors += _check_keys(g, conn, tables, inverse_of)
    if errors:
        raise CheckError("Coverage:\n  " + "\n  ".join(errors))


def _check_cardinality(g: Graph, ddl_columns: dict, inverse_of: dict) -> list[str]:
    """NOT NULL -> a min or exact restriction; a nullable column -> no min restriction. Qualified only on inverses."""
    errors = []
    found: dict[tuple, set[tuple[str, int]]] = {}
    for r in restrictions(g):
        found.setdefault((r["class"], r["expr"]), set()).add((r["kind"], r["value"]))
        if r["qualified"] and not r["expr"][1]:
            errors.append(f"{local(r['class'])}: a qualified restriction on {local(r['on'])}. "
                          f"Use the qualified forms only on the inverse paths.")
    for (table, column), (term, kind) in sorted(V.COLUMNS.items()):
        if table == "StaffLanguage" or (table, column) not in ddl_columns:
            continue  # a multivalued attribute: a staff member can have no language
        notnull = ddl_columns[(table, column)]
        row_class = TRIAD[V.TABLE_CLASS[table]]
        # The row class is the subject of the restriction. For a reverse FK, the path from the row is the inverse.
        expr = (TRIAD[term], kind == V.FK_REVERSE)
        have = found.get((row_class, expr), set())
        need = ("min", 1) if kind == V.ATTRIBUTE else ("exact", 1)
        path = f"{'the inverse of ' if expr[1] else ''}triad:{term}"
        if notnull and need not in have:
            errors.append(f"{table}.{column} is NOT NULL: {local(row_class)} needs the {need[0]} cardinality 1 "
                          f"on {path}.")
        if not notnull and any(k in ("min", "exact") for k, _ in have):
            errors.append(f"{table}.{column} can be NULL: {local(row_class)} must not have a min or exact "
                          f"cardinality on {path}.")
    return errors


def _check_keys(g: Graph, conn: sqlite3.Connection, tables: list[str], inverse_of: dict) -> list[str]:
    """Each UNIQUE constraint of the DDL is an owl:hasKey of its class, or UNIQUE_NOT_KEY gives the reason."""
    errors = []
    owl_keys = {(cls, frozenset(props)) for cls, props in keys(g)}
    matched = set()
    for table in tables:
        for cols in _unique_constraints(conn, table):
            if (table, cols) in UNIQUE_NOT_KEY:
                continue
            props = []
            for column in cols:
                term, kind = V.COLUMNS.get((table, column), (None, None))
                if term is None:
                    props = None
                    break
                prop = TRIAD[term]
                props.append(inverse_of.get(prop, prop) if kind == V.FK_REVERSE else prop)
            key = (TRIAD[V.TABLE_CLASS.get(table, "Staff")], frozenset(props or ()))
            if props is None or key not in owl_keys:
                errors.append(f"UNIQUE {table}({', '.join(cols)}) has no owl:hasKey on "
                              f"{local(key[0])}, and no reason in UNIQUE_NOT_KEY.")
            matched.add(key)
    for key in sorted(owl_keys - matched, key=str):
        errors.append(f"owl:hasKey on {local(key[0])} ({', '.join(sorted(local(p) for p in key[1]))}) "
                      f"has no UNIQUE constraint in the DDL.")
    return errors


def run_checks(g: Graph, conn: sqlite3.Connection | None = None) -> tuple[int, int]:
    """Run all checks. Return the (nodes, edges) of the tree."""
    own = conn is None
    conn = conn or ddl_connection()
    try:
        check_declarations(g)
        check_labels(g)
        check_datatypes(g)
        check_domains_ranges(g)
        check_closed_ranges(g)
        check_value_sets(g, conn)
        check_simple_properties(g)
        tree = check_tree(g)
        check_coverage(g, conn)
        return tree
    finally:
        if own:
            conn.close()


# ---------------------------------------------------------------------------
# Counts
# ---------------------------------------------------------------------------

def counts(g: Graph) -> dict[str, int]:
    """The counts of the TRIAD terms and axioms (ontology.md section 12). PROV-O terms are not counted."""
    res = restrictions(g)
    obj_res = [r for r in res if r["expr"][0] in object_properties(g)]
    return {
        "Classes": len(classes(g)),
        "Object properties": len(object_properties(g)),
        "Stored object properties": len(stored_properties(g)),
        "Named inverses": len(named_inverses(g)),
        "Derived object properties": len(derived_properties(g) & object_properties(g)),
        "Datatype properties": len(datatype_properties(g)),
        "Closed value sets": sum(is_closed_range(g, p) for p in datatype_properties(g)),
        "Keys (owl:hasKey axioms)": len(keys(g)),
        "Classes with a key": len({cls for cls, _ in keys(g)}),
        "Restrictions": len(res),
        "Restrictions on object properties": len(obj_res),
        "Restrictions on datatype properties": len(res) - len(obj_res),
        "Subclass edges between TRIAD classes": sum(1 for c, p in g.subject_objects(RDFS.subClassOf)
                                                    if c in classes(g) and p in classes(g)),
        "Disjointness axioms": len(set(g.subjects(OWL.disjointUnionOf, None)))
        + len(set(g.subjects(RDF.type, OWL.AllDisjointClasses))),
    }


# ---------------------------------------------------------------------------
# RDF/XML output
# ---------------------------------------------------------------------------

def _to_ox(term, labels: dict):
    if isinstance(term, URIRef):
        return ox.NamedNode(str(term))
    if isinstance(term, BNode):
        return ox.BlankNode(labels[term])
    if term.language:
        return ox.Literal(str(term), language=term.language)
    if term.datatype is not None and term.datatype != XSD.string:
        return ox.Literal(str(term), datatype=ox.NamedNode(str(term.datatype)))
    return ox.Literal(str(term))


def owl_bytes(g: Graph) -> bytes:
    """The deterministic RDF/XML of the graph.

    1. Make the blank nodes canonical (rdflib), so the same graph gets the same labels.
    2. Sort the triples, then name the blank nodes b1, b2, ... in that order, then sort again.
    3. Write RDF/XML with pyoxigraph 0.3, then put each element on its own line.
    """
    canonical = to_canonical_graph(g)
    first = sorted(canonical, key=lambda t: t[0].n3() + " " + t[1].n3() + " " + t[2].n3())
    labels: dict = {}
    for s, _, o in first:
        for term in (s, o):
            if isinstance(term, BNode) and term not in labels:
                labels[term] = f"b{len(labels) + 1}"
    triples = sorted((ox.Triple(_to_ox(s, labels), _to_ox(p, labels), _to_ox(o, labels)) for s, p, o in first),
                     key=str)
    out = io.BytesIO()
    ox.serialize(triples, out, "application/rdf+xml")
    head, _, body = out.getvalue().decode("utf-8").partition("?>")
    # Each start tag on a new line. Literals cannot hold "<" (the writer escapes it), so this changes no value.
    body = re.sub(r"<(?!/|rdf:Description|rdf:RDF)", "\n  <", body)
    body = body.replace("<rdf:Description", "\n<rdf:Description")
    body = body.replace("</rdf:Description>", "\n</rdf:Description>").replace("</rdf:RDF>", "\n</rdf:RDF>")
    return (head + "?>" + body + "\n").encode("utf-8")


def write_owl(g: Graph, path: Path = OWL_PATH) -> bytes:
    """Write the RDF/XML. Read it back first: the same canonical bytes mean the same graph (a round trip)."""
    data = owl_bytes(g)
    back = Graph().parse(data=data, format="xml")
    if len(back) != len(g) or owl_bytes(back) != data:
        raise CheckError("The RDF/XML round trip changed the graph.")
    path.write_bytes(data)
    return data


# ---------------------------------------------------------------------------
# The W3C Direct Mapping of one Assertion row (plan 3.6)
# ---------------------------------------------------------------------------

DM_BASE = "http://foo.example/DB/"   # the base IRI of the examples of the W3C Direct Mapping


def _scenario_connection() -> sqlite3.Connection:
    conn = ddl_connection()
    conn.executescript(SEED_PATH.read_text(encoding="utf-8"))
    return conn


def _range_datatype(g: Graph, prop: URIRef) -> str | None:
    rng = g.value(prop, RDFS.range)
    if rng == RDFS.Literal:
        return "xsd:date"             # the date-only attributes (ontology.md section 5)
    if isinstance(rng, BNode) and g.value(rng, OWL.onDatatype) is not None:
        rng = g.value(rng, OWL.onDatatype)
    if rng in (XSD.dateTime, XSD.integer, XSD.boolean):
        return local(rng).replace(str(XSD), "xsd:")
    return None


def _literal(value, datatype: str | None) -> str:
    if datatype == "xsd:boolean":
        value = "true" if value in (1, "1", True) else "false"
    text = '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text + (f"^^{datatype}" if datatype else "")


def triad_triples(g: Graph, conn: sqlite3.Connection, table: str, row: sqlite3.Row) -> list[tuple[str, str]]:
    """(column, triple) of the TRIAD mapping (the rules of plan 3.1) for one row of one table."""
    path, id_col = V.SUBJECT[table]
    subject = f"<{path}/{row[id_col]}>"   # relative to @base <{V.KG}>
    out = [("(row)", f"{subject} rdf:type triad:{V.TABLE_CLASS[table]} .")]
    fks = _fk_map(conn, table)
    for column in row.keys():
        value = row[column]
        if (table, column) in V.NO_PROPERTY:
            out.append((column, f"(no triple: {V.NO_PROPERTY[(table, column)]})"))
            continue
        if value is None:
            out.append((column, "(no triple: the value is NULL)"))
            continue
        term, kind = V.COLUMNS[(table, column)]
        if kind == V.ATTRIBUTE:
            out.append((column, f"{subject} triad:{term} {_literal(value, _range_datatype(g, TRIAD[term]))} ."))
            continue
        target = fks[(column,)][0]
        t_path, _ = V.SUBJECT[target]
        obj = f"<{t_path}/{value}>"
        out.append((column, f"{subject} triad:{term} {obj} ." if kind == V.FK else f"{obj} triad:{term} {subject} ."))
    return out


def direct_mapping_triples(conn: sqlite3.Connection, table: str, row: sqlite3.Row) -> list[tuple[str, str]]:
    """(column, triple) of the W3C Direct Mapping (https://www.w3.org/TR/rdb-direct-mapping/) for one row."""
    types = {r[1]: r[2].upper() for r in conn.execute(f"PRAGMA table_info({table})")}
    subject = f"<{table}/Id={row['Id']}>"
    out = [("(row)", f"{subject} rdf:type <{table}> .")]
    for column in row.keys():
        value = row[column]
        if value is None:
            out.append((column, "(no triple: the value is NULL)"))
            continue
        lit = _literal(value, "xsd:integer" if types[column] == "INTEGER" else None)
        out.append((column, f"{subject} <{table}#{column}> {lit} ."))
    for frm, (target, to) in _fk_map(conn, table).items():
        values = [row[c] for c in frm]
        if any(v is None for v in values):
            continue
        ref = ";".join(f"{t}={v}" for t, v in zip(to, values))
        out.append((",".join(frm), f"{subject} <{table}#ref-{';'.join(frm)}> <{target}/{ref}> ."))
    return out


def direct_mapping_example(db_path: Path | None = None, assertion_id: int = 3) -> str:
    """The W3C Direct Mapping of one Assertion row next to the TRIAD triples of the same row."""
    if db_path is None:
        conn, source = _scenario_connection(), "the scenario database (01_create_tables.sql + 02_insert_seed.sql)"
    else:
        conn, source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True), str(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM Assertion WHERE Id = ?", (assertion_id,)).fetchone()
        if row is None:
            raise CheckError(f"No Assertion with Id {assertion_id} in {source}.")
        g = load_graph()
        dm = direct_mapping_triples(conn, "Assertion", row)
        ours = triad_triples(g, conn, "Assertion", row)
    finally:
        conn.close()
    lines = [f"# One Assertion row (Id = {assertion_id}) from {source}.",
             "# The output is valid Turtle. Each part sets its own @base.", "",
             "# 1. The W3C Direct Mapping (automatic). The base IRI is the one of the W3C examples.",
             f"@base <{DM_BASE}> .",
             "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
             "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> ."]
    lines += [t for _, t in dm if not t.startswith("(")]
    lines += ["", "# 2. The TRIAD mapping (the ontology and the R2RML rules of plan 3.1).",
              f"@base <{V.KG}> .", f"@prefix triad: <{V.TRIAD}> ."]
    lines += [t for _, t in ours if not t.startswith("(")]
    lines += ["", "# 3. Column by column.", f"# {'Column':<16} | {'W3C Direct Mapping':<64} | TRIAD mapping"]
    dm_by_col: dict[str, list[str]] = {}
    for col, t in dm:
        for c in col.split(","):
            dm_by_col.setdefault(c, []).append(t)
    for col, t in ours:
        for i, d in enumerate(dm_by_col.get(col, ["-"])):
            lines.append(f"# {col if i == 0 else '':<16} | {d:<64} | {t if i == 0 else ''}")
    lines += ["", "# What the TRIAD mapping changes (ontology.md section 11):",
              "# - The IRI comes from the class path and the Id (kg/assertion/3), not from the table and the key.",
              "# - The Id gives no triple. A foreign key gives one object property, not a literal and a ref- triple.",
              "# - contains goes from the message to the assertion, in the ER direction. The FK goes the other way.",
              "# - The times are xsd:dateTime, not plain strings. The integers are xsd:integer in both.",
              "# - The class triad:Assertion has a key, a superclass (prov:Entity), cardinality restrictions and",
              "#   a link to FHIR. The Direct Mapping gives only the table name as a class, with no axioms.",
              "# - A subtype row (for example Nurse) is the same individual as its parent row. The Direct Mapping",
              "#   makes a second node <Nurse/Id=...> for it."]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def compare(path: Path) -> list[str]:
    """Compare an RDF/XML file (for example a copy that Protégé saved) with triad.ttl.

    Return the differences as lines; an empty list means that the two graphs are isomorphic.
    """
    other = Graph().parse(path, format="xml")
    _, only_ours, only_theirs = graph_diff(to_isomorphic(load_graph()), to_isomorphic(other))
    lines = [f"- {s.n3()} {p.n3()} {o.n3()}" for s, p, o in sorted(only_ours)]
    lines += [f"+ {s.n3()} {p.n3()} {o.n3()}" for s, p, o in sorted(only_theirs)]
    return lines


def build(out: Path = OWL_PATH, check_only: bool = False) -> dict[str, int]:
    g = load_graph()
    nodes, edges = run_checks(g)
    if check_only:
        if not out.exists() or out.read_bytes() != owl_bytes(g):
            raise CheckError(f"{out.name} is not current. Run build_ontology.py without --check.")
    else:
        write_owl(g, out)
    result = counts(g)
    result["Tree nodes"], result["Tree edges"] = nodes, edges
    result["Triples in triad.owl"] = len(g)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="check only; stop if triad.owl is not current")
    parser.add_argument("--out", type=Path, default=OWL_PATH, help="the RDF/XML output file")
    parser.add_argument("--direct-mapping-example", action="store_true",
                        help="print the W3C Direct Mapping of one Assertion row next to the TRIAD triples")
    parser.add_argument("--db", type=Path, help="the SQLite database of the example (default: the scenario rows)")
    parser.add_argument("--assertion", type=int, default=3, help="the Assertion Id of the example (default: 3)")
    parser.add_argument("--compare", type=Path, metavar="FILE",
                        help="compare an RDF/XML file (for example the Protégé re-save) with triad.ttl")
    args = parser.parse_args(argv)
    try:
        if args.compare:
            diff = compare(args.compare)
            print("\n".join(diff[:40]) or f"{args.compare} has the same graph as triad.ttl (isomorphic).")
            if diff:
                print(f"{len(diff)} triples differ (- only in triad.ttl, + only in {args.compare.name}).")
            return 1 if diff else 0
        if args.direct_mapping_example:
            sys.stdout.write(direct_mapping_example(args.db, args.assertion))
            return 0
        result = build(args.out, args.check)
    except CheckError as exc:
        print(f"Check failed. {exc}", file=sys.stderr)
        return 1
    print(("Checked" if args.check else "Wrote") + f" {args.out}")
    for name, value in result.items():
        print(f"  {name:<40} {value}")
    print("Checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
