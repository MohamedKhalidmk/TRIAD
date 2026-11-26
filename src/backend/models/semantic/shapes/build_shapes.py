#!/usr/bin/env python3
"""Write the generated part of the W3C SHACL shapes triad.shacl.ttl (plan 5, section 3.4).

Run it from the root folder of the repository:
    .venv/bin/python src/backend/models/semantic/shapes/build_shapes.py           # write the generated part
    .venv/bin/python src/backend/models/semantic/shapes/build_shapes.py --check   # stop if the file is old

triad.shacl.ttl is the artifact. It has two parts:
1. The generated part (from the start of the file to the line END_MARKER). This script writes it:
   the prefixes, one sh:NodeShape for each of the 28 classes, one sh:PropertyShape for each (class, path),
   the "exactly one subtype" rules, and one SHACL-SPARQL constraint for each owl:hasKey.
2. The hand-written part (after END_MARKER): the rules across columns (the date pairs, the issuer rule) and
   the rules of the triggers (SHACL-SPARQL). The script keeps this part as it is.

The inputs:
    ../triad.ttl               the classes, the ranges, the value sets (owl:oneOf), the Functional and
                               InverseFunctional characteristics, the cardinality restrictions and the keys;
    ../vocabulary.py           the term of each DDL column, and the direction of each foreign key;
    01_create_tables.sql       the column definitions and the constraint names, for the comments.
A test (tests/integration/test_kg_shacl.py) checks the file against the DDL and triad.ttl a second time.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    from models.semantic import build_ontology as bo
    from models.semantic import vocabulary as V
except ImportError:  # run as a script: put src/backend on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from models.semantic import build_ontology as bo
    from models.semantic import vocabulary as V

from rdflib import BNode, Graph, URIRef
from rdflib.collection import Collection
from rdflib.namespace import OWL, RDF, RDFS, XSD

HERE = Path(__file__).resolve().parent
SHAPES_PATH = HERE / "triad.shacl.ttl"
SHAPES_IRI = f"{V.REPO}/shapes/triad"   # the IRI of the shapes graph (it holds the SPARQL prefixes)
SHAPE = f"{SHAPES_IRI}#"                # the IRIs of the shapes and the constraints
END_MARKER = "# ===== END OF THE GENERATED PART. Write the hand-written rules below this line. ====="

# The rules without a column (ER participation, or new in Milestone 5):
# (class, property, inverse) -> (the comment, the short reason for the message).
NO_COLUMN = {
    ("Message", "contains", False): (
        "No column: the ER participation of Contains. A message has at least one assertion. "
        "triad.ttl: Message ⊑ ≥1 contains.", "the ER participation of Contains"),
    ("ClinicalEntry", "about", True): (
        "No column: the ER participation of About. An entry has at least one assertion. "
        "triad.ttl: ClinicalEntry ⊑ ≥1 inverse(about).Assertion.", "the ER participation of About"),
    ("Staff", "ofStaff", True): (
        "No column: new in Milestone 5 (plan 1.3). A staff member works in at least one department. "
        "triad.ttl: Staff ⊑ ≥1 inverse(ofStaff).WorksIn.", "new in Milestone 5"),
}

HAND_WRITTEN_STUB = "\n# The hand-written rules go here.\n"


@dataclass
class PropertySpec:
    """One sh:PropertyShape: the values of one path of the nodes of one class."""
    cls: str
    prop: str
    inverse: bool
    datatype: str | None = None       # "xsd:string", "xsd:dateTime", ... for a datatype property
    target: str | None = None         # the sh:class of an object property
    values: list[str] | None = None   # the sh:in list
    min_inclusive: int | None = None
    min1: bool = False
    max1: bool = False
    label: str | None = None          # the source of the rule in the message: "Table.Column" or a reason
    sql: list[str] = field(default_factory=list)   # the SQL that the shape replaces (the comment lines)

    @property
    def name(self) -> str:
        return f"{self.cls}-{'inverse-' if self.inverse else ''}{self.prop}"


# ---------------------------------------------------------------------------------------------
# The DDL: column definitions and constraint names

def table_items(conn: sqlite3.Connection, table: str) -> list[str]:
    """The items of CREATE TABLE (column definitions and table constraints), each on one line."""
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()[0]
    sql = re.sub(r"--[^\n]*", "", sql)
    body = sql[sql.index("(") + 1:sql.rindex(")")]
    items, depth, current = [], 0, []
    for char in body:
        depth += {"(": 1, ")": -1}.get(char, 0)
        if char == "," and depth == 0:
            items.append(current)
            current = []
        else:
            current.append(char)
    items.append(current)
    return [" ".join("".join(item).split()) for item in items if "".join(item).strip()]


_KEYWORDS = ("CONSTRAINT", "CHECK", "UNIQUE", "FOREIGN", "PRIMARY")


def column_definition(conn: sqlite3.Connection, table: str, column: str) -> str:
    for item in table_items(conn, table):
        if item.split()[0] == column and item.split()[0] not in _KEYWORDS:
            return item
    raise ValueError(f"The DDL has no column {table}.{column}.")


def foreign_key(conn: sqlite3.Connection, table: str, column: str) -> str:
    """The text of the FOREIGN KEY constraint of one column."""
    for item in table_items(conn, table):
        if item.startswith("CONSTRAINT") and re.search(rf"FOREIGN KEY \({column}\)", item):
            return item
    raise ValueError(f"The DDL has no foreign key on {table}.{column}.")


def unique_constraints(conn: sqlite3.Connection, table: str) -> dict[tuple[str, ...], str]:
    """(columns) -> the text of the UNIQUE constraint."""
    found = {}
    for item in table_items(conn, table):
        match = re.match(r"CONSTRAINT (\w+) UNIQUE \(([^)]*)\)", item)
        if match:
            found[tuple(c.strip() for c in match.group(2).split(","))] = item
    return found


def constraint_name(text: str) -> str:
    return text.split()[1]


# ---------------------------------------------------------------------------------------------
# The ontology

def xsd_name(term) -> str:
    return "xsd:" + str(term)[len(str(XSD)):]


def datatype_of(g: Graph, prop: URIRef) -> tuple[str, int | None]:
    """(sh:datatype, sh:minInclusive) of a datatype property, from its rdfs:range in triad.ttl."""
    rng = g.value(prop, RDFS.range)
    if rng == RDFS.Literal:
        return "xsd:date", None   # OWL 2 has no xsd:date: the TBox range is rdfs:Literal, the data uses xsd:date
    if isinstance(rng, BNode):
        if g.value(rng, OWL.oneOf) is not None:
            return "xsd:string", None   # a closed value set of simple literals
        minimum = None
        for facet in Collection(g, g.value(rng, OWL.withRestrictions)):
            value = g.value(facet, XSD.minInclusive)
            if value is not None:
                minimum = int(value)
        return xsd_name(g.value(rng, OWL.onDatatype)), minimum
    return xsd_name(rng), None


def subtypes(g: Graph) -> dict[str, list[str]]:
    """The parent class -> its subclasses, in the order of owl:disjointUnionOf."""
    return {bo.local(parent): [bo.local(c) for c in Collection(g, union)]
            for parent, union in g.subject_objects(OWL.disjointUnionOf)}


def class_order() -> list[str]:
    """The 28 classes in the order of the tables of the DDL (vocabulary.TABLE_CLASS)."""
    return list(V.TABLE_CLASS.values())


# ---------------------------------------------------------------------------------------------
# The property shapes

def property_specs(g: Graph, conn: sqlite3.Connection) -> dict[str, list[PropertySpec]]:
    """The property shapes of each class, in the order of the DDL columns."""
    tables = {cls: table for table, cls in V.TABLE_CLASS.items()}
    functional = set(g.subjects(RDF.type, OWL.FunctionalProperty))
    inverse_functional = set(g.subjects(RDF.type, OWL.InverseFunctionalProperty))
    specs: dict[str, list[PropertySpec]] = {cls: [] for cls in class_order()}
    by_key: dict[tuple[str, str, bool], PropertySpec] = {}
    later: dict[str, list[PropertySpec]] = {cls: [] for cls in class_order()}

    def add(spec: PropertySpec, into: dict[str, list[PropertySpec]]) -> PropertySpec:
        key = (spec.cls, spec.prop, spec.inverse)
        if key in by_key:
            raise ValueError(f"Two rules give the shape {spec.name}.")
        by_key[key] = spec
        into[spec.cls].append(spec)
        return spec

    for cls in class_order():
        table = tables[cls]
        columns = [(table, c) for c in ddl_columns(conn, table)]
        if cls == "Staff":
            columns += [("StaffLanguage", c) for c in ddl_columns(conn, "StaffLanguage")]
        for t, column in columns:
            if (t, column) in V.NO_PROPERTY:
                continue
            term, kind = V.COLUMNS[(t, column)]
            prop = bo.TRIAD[term]
            definition = f"{t}.{column_definition(conn, t, column)}"
            if kind == V.ATTRIBUTE:
                datatype, minimum = datatype_of(g, prop)
                add(PropertySpec(cls, term, False, datatype=datatype, values=bo.closed_values(g, prop) or None,
                                 min_inclusive=minimum, label=f"{t}.{column}", sql=[definition]), specs)
            elif kind == V.FK:
                add(PropertySpec(cls, term, False, target=bo.local(g.value(prop, RDFS.range)),
                                 label=f"{t}.{column}", sql=[definition, foreign_key(conn, t, column)]), specs)
            else:   # the reverse direction: <parent> triad:term <row>
                parent = bo.local(g.value(prop, RDFS.domain))
                fk = foreign_key(conn, t, column)
                add(PropertySpec(cls, term, True, target=parent, label=f"{t}.{column}", sql=[definition, fk]),
                    specs)
                add(PropertySpec(parent, term, False, target=cls, label=f"{t}.{column}", sql=[fk]), later)
    # A stored FK that is also InverseFunctional (supersedes): at most one row points to each target.
    for (t, column), (term, kind) in V.COLUMNS.items():
        prop = bo.TRIAD[term]
        if kind == V.FK and prop in inverse_functional:
            unique = unique_constraints(conn, t)[(column,)]
            add(PropertySpec(bo.local(g.value(prop, RDFS.range)), term, True, target=V.TABLE_CLASS[t],
                             label=constraint_name(unique), sql=[unique]), later)
    # The cardinality restrictions of triad.ttl give sh:minCount and sh:maxCount.
    for r in bo.restrictions(g):
        stored, inverse = r["expr"]
        key = (bo.local(r["class"]), bo.local(stored), inverse)
        spec = by_key.get(key)
        if spec is None:
            if key not in NO_COLUMN:
                raise ValueError(f"The restriction on {key} has no column and no reason in NO_COLUMN.")
            cls, term, _ = key
            target = g.value(stored, RDFS.domain if inverse else RDFS.range)
            spec = add(PropertySpec(cls, term, inverse, target=bo.local(target)), later)
        if key in NO_COLUMN:
            spec.sql.append(NO_COLUMN[key][0])
            spec.label = spec.label or NO_COLUMN[key][1]
        if r["kind"] in ("min", "exact") and r["value"] == 1:
            spec.min1 = True
        if r["kind"] in ("max", "exact") and r["value"] == 1:
            spec.max1 = True
    # owl:FunctionalProperty gives sh:maxCount 1 on the path; InverseFunctional on the inverse path.
    for spec in by_key.values():
        prop = bo.TRIAD[spec.prop]
        if (not spec.inverse and prop in functional) or (spec.inverse and prop in inverse_functional):
            spec.max1 = True
    return {cls: specs[cls] + later[cls] for cls in class_order()}


def ddl_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


# ---------------------------------------------------------------------------------------------
# The messages (ASD-STE100)

def _term(cls: str) -> str:
    return f"triad:{cls}"


def property_message(spec: PropertySpec) -> str:
    who = f"Each {_term(spec.cls)}"
    if spec.inverse:
        link = f"{_term(spec.target)} that links to it with triad:{spec.prop}"
        if spec.min1 and spec.max1:
            text = f"{who} must have exactly one {link}."
        elif spec.min1:
            text = f"{who} must have at least one {link}."
        else:
            text = f"{who} can have at most one {link}."
    else:
        if spec.min1 and spec.max1:
            text, each = f"{who} must have exactly one value of triad:{spec.prop}.", "The value"
        elif spec.min1:
            text, each = f"{who} must have at least one value of triad:{spec.prop}.", "Each value"
        elif spec.max1:
            text, each = f"{who} can have at most one value of triad:{spec.prop}.", "The value"
        else:
            text, each = f"{who} can have more than one value of triad:{spec.prop}.", "Each value"
        if spec.target:
            text += f" {each} must be a {_term(spec.target)}."
        elif spec.values:
            text += f" {each} must be one of: {', '.join(spec.values)}."
        elif spec.min_inclusive is not None:
            text += f" {each} must be an {spec.datatype} of {spec.min_inclusive} or more."
        else:
            text += f" {each} must be an {spec.datatype}."
    return text[:-1] + (f" ({spec.label})." if spec.label else ".")


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


# ---------------------------------------------------------------------------------------------
# The Turtle text

def _property_shape(spec: PropertySpec) -> str:
    lines = [f"# {line}" if line.startswith("No column") else f"# SQL: {line}" for line in spec.sql]
    path = f"[ sh:inversePath triad:{spec.prop} ]" if spec.inverse else f"triad:{spec.prop}"
    body = [f"shape:{spec.name} a sh:PropertyShape", f"    sh:path {path}"]
    if spec.datatype:
        body.append(f"    sh:datatype {spec.datatype}")
    if spec.target:
        body += [f"    sh:class triad:{spec.target}", "    sh:nodeKind sh:IRI"]
    if spec.values:
        body.append("    sh:in ( " + " ".join(_quote(v) for v in spec.values) + " )")
    if spec.min_inclusive is not None:
        body.append(f"    sh:minInclusive {spec.min_inclusive}")
    if spec.min1:
        body.append("    sh:minCount 1")
    if spec.max1:
        body.append("    sh:maxCount 1")
    body.append(f"    sh:message {_quote(property_message(spec))}")
    return "\n".join(lines + [" ;\n".join(body) + " ."])


def _subtype_shapes(conn: sqlite3.Connection, parent: str, children: list[str]) -> tuple[str, dict[str, str]]:
    """The rule "exactly one subtype" on the parent, and the rule "also the parent" on each subtype."""
    discriminator = {"Staff": "Role", "ClinicalEntry": "Category"}[parent]
    names = ", ".join(_term(c) for c in children[:-1]) + f" or {_term(children[-1])}"
    uniques = ", ".join(constraint_name(text) for c in children for text in unique_constraints(conn, c).values())
    whole = "\n".join([
        f"# SQL: {parent}.{column_definition(conn, parent, discriminator)}",
        f"# SQL: the subtype rows ({uniques}).",
        f"# The discriminator gives no property: rdf:type holds it (ontology.md section 2).",
        f"shape:{parent}-subtype a sh:PropertyShape ;",
        "    sh:path rdf:type ;",
        "    sh:qualifiedValueShape [ sh:in ( " + " ".join(_term(c) for c in children) + " ) ] ;",
        "    sh:qualifiedMinCount 1 ;",
        "    sh:qualifiedMaxCount 1 ;",
        f"    sh:message {_quote(f'Each {_term(parent)} must have exactly one subtype: {names} ({parent}.{discriminator}; the ISA is disjoint and total).')} ."])
    own = {}
    for child in children:
        fk = next(item for item in table_items(conn, child) if item.startswith("CONSTRAINT FK_") and
                  f"REFERENCES {parent} " in item)
        own[child] = "\n".join([
            f"# SQL: {child}.{column_definition(conn, child, discriminator)}",
            f"# SQL: {fk}",
            f"shape:{child}-type a sh:PropertyShape ;",
            "    sh:path rdf:type ;",
            f"    sh:hasValue triad:{parent} ;",
            f"    sh:message {_quote(f'Each {_term(child)} must also be a {_term(parent)}: the subtype row and the parent row are one individual ({constraint_name(fk)}).')} ."])
    return whole, own


def key_constraints(g: Graph, conn: sqlite3.Connection) -> dict[str, list[tuple[str, str]]]:
    """The class -> [(constraint name, Turtle text)] of the SHACL-SPARQL constraint of each owl:hasKey."""
    tables = {cls: table for table, cls in V.TABLE_CLASS.items()}
    inverses = {bo.local(named): bo.local(stored) for named, stored in bo.named_inverses(g).items()}
    named_of = {stored: named for named, stored in inverses.items()}
    found: dict[str, list[tuple[str, str]]] = {cls: [] for cls in class_order()}
    for cls_term, props in bo.keys(g):
        cls = bo.local(cls_term)
        table = tables[cls]
        names = [bo.local(p) for p in props]
        terms_of = {}   # column -> the key term (a reverse FK gives the named inverse, for example inMessage)
        for column in ddl_columns(conn, table):
            term, kind = V.COLUMNS.get((table, column), (None, None))
            if term is not None:
                terms_of[column] = named_of.get(term, term) if kind == V.FK_REVERSE else term
        unique = next(text for cols, text in unique_constraints(conn, table).items()
                      if sorted(terms_of.get(c, "") for c in cols) == sorted(names))
        name = constraint_name(unique)
        paths = [f"^triad:{inverses[n]}" if n in inverses else f"triad:{n}" for n in names]
        values = " ;\n                ".join(f"{p} ?key{i}" for i, p in enumerate(paths, 1))
        listed = " and ".join(f"triad:{n}" for n in names) if len(names) == 2 else \
            ", ".join(f"triad:{n}" for n in names[:-1]) + f" and triad:{names[-1]}"
        message = (f"Another {_term(cls)} ({{?value}}) has the same values of {listed}. "
                   f"The key must be unique ({name}).")
        text = "\n".join([
            f"# SQL: {unique}",
            f"# triad.ttl: {_term(cls)} owl:hasKey ( {' '.join('triad:' + n for n in names)} ).",
            f"shape:{name} a sh:SPARQLConstraint ;",
            f"    sh:message {_quote(message)} ;",
            f"    sh:prefixes <{SHAPES_IRI}> ;",
            '    sh:select """',
            "        SELECT $this ?value",
            "        WHERE {",
            f"            $this {values} .",
            f"            ?value {values} ;",
            f"                a triad:{cls} .",
            "            FILTER (?value != $this)",
            "        }",
            '        """ .'])
        found[cls].append((name, text))
    return found


HEADER = f"""# TRIAD: the W3C SHACL shapes (https://www.w3.org/TR/shacl/) of the knowledge graph. Milestone 5, plan 3.4.
#
# The shapes hold the closed-world rules of the SQLite schema (01_create_tables.sql): NOT NULL, CHECK ... IN,
# the foreign keys, the UNIQUE constraints, the CHECKs across columns and the triggers. OWL cannot hold them,
# because OWL uses the Open World Assumption (ontology.md section 8).
#
# This file has two parts:
# 1. The generated part (to the END line). Do not edit it by hand. build_shapes.py writes it from ../triad.ttl,
#    ../vocabulary.py and 01_create_tables.sql:
#        .venv/bin/python src/backend/models/semantic/shapes/build_shapes.py
# 2. The hand-written part (after the END line): the rules across columns and the rules of the triggers.
#
# Each shape and constraint has an sh:message that names the rule. The comment above it names the SQL that
# it replaces. Run the shapes with: python -m infrastructure.rdf.shacl FILE (PYTHONPATH=src/backend).

@prefix shape: <{SHAPE}> .
@prefix triad: <{V.TRIAD}> .
@prefix sh:    <http://www.w3.org/ns/shacl#> .
@prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:   <http://www.w3.org/2002/07/owl#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .

# The shapes graph. Its sh:declare values give the prefixes of the SPARQL constraints (sh:prefixes).
<{SHAPES_IRI}> a owl:Ontology ;
    rdfs:label "TRIAD SHACL shapes"@en ;
    rdfs:comment "The closed-world rules of the TRIAD knowledge graph: the rules of the SQLite schema that OWL cannot hold."@en ;
    sh:declare
        [ sh:prefix "triad" ; sh:namespace "{V.TRIAD}"^^xsd:anyURI ] ,
        [ sh:prefix "rdf" ; sh:namespace "http://www.w3.org/1999/02/22-rdf-syntax-ns#"^^xsd:anyURI ] ,
        [ sh:prefix "xsd" ; sh:namespace "http://www.w3.org/2001/XMLSchema#"^^xsd:anyURI ] .
"""


def _rule(title: str) -> str:
    return "\n".join(["# " + "-" * 110, f"# {title}", "# " + "-" * 110])


def generated_text(ttl_path: Path = bo.TTL_PATH, ddl_path: Path = bo.DDL_PATH) -> tuple[str, dict[str, int]]:
    """The text of the generated part (with END_MARKER and a new line at the end), and its counts."""
    g = bo.load_graph(ttl_path)
    conn = bo.ddl_connection(ddl_path)
    try:
        specs = property_specs(g, conn)
        keys = key_constraints(g, conn)
        children_of = subtypes(g)
        subtype_text = {parent: _subtype_shapes(conn, parent, children) for parent, children in children_of.items()}
    finally:
        conn.close()
    parent_of = {child: parent for parent, children in children_of.items() for child in children}
    tables = {cls: table for table, cls in V.TABLE_CLASS.items()}
    blocks = [HEADER]
    counts = {"node_shapes": 0, "property_shapes": 0, "key_constraints": 0}
    for cls in class_order():
        table = tables[cls]
        names = [f"shape:{s.name}" for s in specs[cls]]
        if cls in children_of:
            names.append(f"shape:{cls}-subtype")
        if cls in parent_of:
            names.append(f"shape:{cls}-type")
        kind = f"a subtype of {_term(parent_of[cls])}: the same individual as its parent row" if cls in parent_of \
            else f"the rows of the table {table}"
        node = [f"shape:{cls}Shape a sh:NodeShape", f"    sh:targetClass triad:{cls}"]
        node.append("    sh:property\n        " + " ,\n        ".join(names))
        if keys[cls]:
            node.append("    sh:sparql " + " , ".join(f"shape:{n}" for n, _ in keys[cls]))
        parts = [_rule(f"{_term(cls)} ({kind})"), " ;\n".join(node) + " ."]
        parts += [_property_shape(s) for s in specs[cls]]
        if cls in children_of:
            parts.append(subtype_text[cls][0])
        if cls in parent_of:
            parts.append(subtype_text[parent_of[cls]][1][cls])
        parts += [text for _, text in keys[cls]]
        blocks.append("\n\n".join(parts) + "\n")
        counts["node_shapes"] += 1
        counts["property_shapes"] += len(names)
        counts["key_constraints"] += len(keys[cls])
    return "\n".join(blocks) + "\n" + END_MARKER + "\n", counts


def split(text: str) -> tuple[str, str]:
    """(the generated part with END_MARKER and its new line, the hand-written part)."""
    marker = END_MARKER + "\n"
    if marker not in text:
        raise ValueError(f"{SHAPES_PATH.name} has no line {END_MARKER!r}.")
    head, tail = text.split(marker, 1)
    return head + marker, tail


def shapes_text(path: Path = SHAPES_PATH) -> tuple[str, dict[str, int]]:
    """The full text of triad.shacl.ttl: the new generated part and the hand-written part of the file at `path`."""
    generated, counts = generated_text()
    hand = split(path.read_text(encoding="utf-8"))[1] if path.is_file() else HAND_WRITTEN_STUB
    return generated + hand, counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="check only; stop if triad.shacl.ttl is not current")
    parser.add_argument("--out", type=Path, default=SHAPES_PATH, help="the shapes file (default: %(default)s)")
    args = parser.parse_args(argv)
    try:
        text, counts = shapes_text(args.out)
    except (ValueError, bo.CheckError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    summary = (f"{counts['node_shapes']} node shapes, {counts['property_shapes']} property shapes and "
               f"{counts['key_constraints']} key constraints in the generated part")
    if args.check:
        if not args.out.is_file() or args.out.read_text(encoding="utf-8") != text:
            print(f"Check failed. {args.out.name} is not current. Run build_shapes.py without --check.",
                  file=sys.stderr)
            return 1
        print(f"{args.out.name} is current: {summary}.")
        return 0
    args.out.write_text(text, encoding="utf-8")
    print(f"Wrote {args.out}: {summary}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
