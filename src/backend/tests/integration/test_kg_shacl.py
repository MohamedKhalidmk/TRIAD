"""The SHACL shapes of the knowledge graph (plan 5, section 3.4): models/semantic/shapes/triad.shacl.ttl.

The tests validate small graphs only: the committed seed graph (about 0.2 s for each validation) and the graph of
the planted database. pyshacl needs about 6 minutes and 3.5 GB for the full graph, so no test validates it.

A planted error adds triples to a copy of the seed graph in memory (or removes triples from it). The test then
expects that the result INCLUDES the (focus node, rule) pair. It does not expect "exactly one violation": a
duplicate key reports both nodes, and one bad node can break more than one rule.

The tests:
- The file: the generated part is current, one node shape for each class, and each value set, each NOT NULL
  column, each foreign key and each range of the DDL and triad.ttl has its rule.
- Each kind of rule on all the shapes of its kind (NOT NULL, CHECK ... IN, the datatypes, the foreign keys,
  the single values, the subtypes, the 18 keys).
- Each case of 05_constraint_violations.sql (SQL_CASES; shapes/README.md has the same table) and the other
  rules of plan 1.7 (RULE_CASES).
"""
from __future__ import annotations

import gzip
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Union

import pytest

pytest.importorskip("rdflib")
pytest.importorskip("pyshacl")

from rdflib import BNode, Graph, Literal, Namespace, URIRef  # noqa: E402
from rdflib.collection import Collection  # noqa: E402
from rdflib.namespace import OWL, RDF, RDFS  # noqa: E402

from infrastructure import config  # noqa: E402
from infrastructure.rdf import shacl  # noqa: E402
from infrastructure.rdf.namespaces import KG, TRIAD  # noqa: E402
from models.semantic import build_ontology as bo  # noqa: E402
from models.semantic import vocabulary as V  # noqa: E402
from models.semantic.mapping import build_mapping as bm  # noqa: E402
from models.semantic.shapes import build_shapes as bs  # noqa: E402

SH = Namespace(shacl.SH)
T = Namespace(TRIAD)
XSD = Namespace("http://www.w3.org/2001/XMLSchema#")   # an open namespace: pytest reads the attributes of the module
SHAPE = shacl.SHAPE
VIOLATIONS_SQL = config.DML_DIR / "05_constraint_violations.sql"

# The prefixes of the planted Turtle. The base is the KG namespace, so <patient/1> is kg:patient/1.
TURTLE_HEAD = (f"@base <{KG}> .\n@prefix triad: <{TRIAD}> .\n"
               "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n")


# ---------------------------------------------------------------------------------------------
# Helpers

def kg(path: str) -> URIRef:
    return URIRef(KG + path)


def copy_of(graph: Graph) -> Graph:
    new = Graph()
    for triple in graph:
        new.add(triple)
    return new


def plant(graph: Graph, turtle: str) -> Graph:
    graph.parse(data=TURTLE_HEAD + turtle, format="turtle")
    return graph


def term(text):
    """A term of a triple pattern: None (any), "a" (rdf:type), "triad:x", or a KG path such as "patient/1"."""
    if text is None:
        return None
    if text == "a":
        return RDF.type
    if text.startswith("triad:"):
        return T[text[len("triad:"):]]
    return kg(text)


def missing(result: shacl.ShaclResult, expected) -> list:
    """The expected (focus, shape, component) triples that the result does not have."""
    return [e for e in expected if not result.has(
        str(e[0]) if isinstance(e[0], URIRef) else KG + e[0], SHAPE + e[1], e[2] if len(e) > 2 else None)]


@pytest.fixture(scope="module")
def shapes_graph() -> Graph:
    return shacl.load_shapes()


@pytest.fixture(scope="module")
def seed() -> Graph:
    return shacl.load_graph(shacl.SEED_PATH)


@pytest.fixture(scope="module")
def ontology() -> Graph:
    return bo.load_graph()


def shapes_of_class(shapes_graph: Graph) -> dict[str, list[dict]]:
    """The class -> the property shapes of its node shape (the parts that the generic tests need)."""
    found: dict[str, list[dict]] = {}
    for node in shapes_graph.subjects(RDF.type, SH.NodeShape):
        target = shapes_graph.value(node, SH.targetClass)
        if not str(node).endswith("Shape") or str(node) == SHAPE + "MessageIssuerShape":
            continue
        cls = str(target)[len(TRIAD):]
        for ps in shapes_graph.objects(node, SH.property):
            path = shapes_graph.value(ps, SH.path)
            inverse = isinstance(path, BNode)
            if inverse:
                path = shapes_graph.value(path, SH.inversePath)
            values = shapes_graph.value(ps, SH["in"])
            found.setdefault(cls, []).append({
                "name": str(ps)[len(SHAPE):], "path": path, "inverse": inverse,
                "datatype": shapes_graph.value(ps, SH.datatype), "class": shapes_graph.value(ps, SH["class"]),
                "in": [str(v) for v in Collection(shapes_graph, values)] if values is not None else None,
                "min": shapes_graph.value(ps, SH.minCount), "max": shapes_graph.value(ps, SH.maxCount),
                "minInclusive": shapes_graph.value(ps, SH.minInclusive)})
    return found


# The subtype -> its parent class (vocabulary.SUBTYPE_TABLES), and the parent -> its subtypes.
PARENT = {V.TABLE_CLASS[t]: V.TABLE_CLASS[parent] for t, (_, parent) in V.SUBTYPE_TABLES.items()}
CHILDREN = {p: [c for c, q in PARENT.items() if q == p] for p in sorted(set(PARENT.values()))}


def bare_node(graph: Graph, cls: str) -> URIRef:
    """A new node of the class (and of its parent class, for a subtype) with no other triple."""
    node = kg(f"test/{cls}")
    graph.add((node, RDF.type, T[cls]))
    if cls in PARENT:
        graph.add((node, RDF.type, T[PARENT[cls]]))
    return node


def good_values(spec: dict) -> list:
    """Two values of the right datatype (or of the value set) for a datatype property."""
    if spec["in"]:
        return [Literal(v) for v in spec["in"][:2]]
    datatype = spec["datatype"]
    return {
        XSD.string: [Literal("a"), Literal("b")],
        XSD.dateTime: [Literal("2026-10-30T10:00:00-04:00", datatype=XSD.dateTime),
                       Literal("2026-10-30T11:00:00-04:00", datatype=XSD.dateTime)],
        XSD.date: [Literal("2026-10-30", datatype=XSD.date), Literal("2026-10-31", datatype=XSD.date)],
        XSD.integer: [Literal(1), Literal(2)],
        XSD.boolean: [Literal(True), Literal(False)],
    }[datatype]


# ---------------------------------------------------------------------------------------------
# The seed graph and the planted database

def test_the_seed_graph_conforms(seed):
    result = shacl.validate(seed)
    assert result.conforms, result.summary()
    assert result.violations == []
    assert result.triples == len(seed) > 1000
    assert result.seconds < 5   # about 0.2 s; pyshacl parses each SPARQL text once (shacl.py)


def test_the_graph_of_the_planted_database_conforms(planted_db):
    """The planted rows: a patient message with no issuer, times with Z, +05:30 and milliseconds (plant.py)."""
    pytest.importorskip("morph_kgc")
    from infrastructure.rdf import kg_export
    text = "\n".join(kg_export.materialize(planted_db))
    graph = Graph().parse(data=text, format="nt")
    result = shacl.validate(graph)
    assert result.conforms, result.summary()
    # The graph has the hard parts, so the test can see a wrong shape.
    no_issuer = [m for m in graph.subjects(RDF.type, T.Message) if (None, T.issues, m) not in graph]
    assert no_issuer and all((m, T.origin, Literal("Patient")) in graph for m in no_issuer)
    for time in ("2026-10-02T20:15:00Z", "2026-10-03T01:10:00+05:30", "2026-10-02T11:45:10.165-04:00"):
        assert f'"{time}"^^<{XSD.dateTime}>' in text, time
    # A pair where the text order and the time order differ: a text comparison of supersedes would fail.
    pairs = [(graph.value(new, T.assertedAt), graph.value(old, T.assertedAt))
             for new, old in graph.subject_objects(T.supersedes)]
    assert any(str(n) < str(o) and n.value > o.value for n, o in pairs)


# ---------------------------------------------------------------------------------------------
# The file

def test_the_generated_part_of_the_shapes_is_current():
    text, counts = bs.shapes_text()
    assert bs.SHAPES_PATH.read_text(encoding="utf-8") == text, \
        "Run: .venv/bin/python src/backend/models/semantic/shapes/build_shapes.py"
    assert counts["node_shapes"] == 28
    assert counts["key_constraints"] == 18


def test_one_node_shape_for_each_class(shapes_graph, ontology):
    classes = {str(c)[len(TRIAD):] for c in bo.classes(ontology)}
    assert len(classes) == 28
    targets = {}
    for node in shapes_graph.subjects(RDF.type, SH.NodeShape):
        if str(node).endswith("Shape") and node != URIRef(SHAPE + "MessageIssuerShape"):
            targets[str(node)[len(SHAPE):-len("Shape")]] = str(shapes_graph.value(node, SH.targetClass))
    assert targets == {c: TRIAD + c for c in classes}


def test_the_shapes_follow_the_ddl_and_the_ontology(shapes_graph, ontology):
    """Each column of vocabulary.COLUMNS has its rule: NOT NULL, the value set, the range, the foreign key."""
    ddl = bm.ddl_connection()
    shapes = shapes_of_class(shapes_graph)
    functional = set(ontology.subjects(RDF.type, OWL.FunctionalProperty))
    errors = []

    def find(cls, prop, inverse):
        hits = [s for s in shapes[cls] if s["path"] == T[prop] and s["inverse"] == inverse
                and not s["name"].endswith("-dates")]   # the date pairs (sh:lessThanOrEquals) use the path too
        if len(hits) != 1:
            errors.append(f"{cls}: {len(hits)} shapes on {'^' if inverse else ''}triad:{prop}")
            return None
        return hits[0]

    try:
        for (table, column), (prop, kind) in sorted(V.COLUMNS.items()):
            cls = V.TABLE_CLASS.get(table, "Staff")
            notnull = {r[1]: bool(r[3]) for r in ddl.execute(f"PRAGMA table_info({table})")}[column]
            if table == "StaffLanguage":
                notnull = False   # a multivalued attribute: a staff member can have no language
            spec = find(cls, prop, kind == V.FK_REVERSE)
            if spec is None:
                continue
            if (spec["min"] == Literal(1)) != notnull:
                errors.append(f"{table}.{column}: NOT NULL is {notnull}, sh:minCount is {spec['min']}")
            if kind == V.ATTRIBUTE:
                single = T[prop] in functional
                if (spec["max"] == Literal(1)) != single:
                    errors.append(f"{table}.{column}: Functional is {single}, sh:maxCount is {spec['max']}")
                rng = ontology.value(T[prop], RDFS.range)
                closed = bo.closed_values(ontology, T[prop])
                if closed:
                    want = XSD.string
                    if spec["in"] != closed or spec["in"] != bo.ddl_value_set(ddl, table, column):
                        errors.append(f"{table}.{column}: sh:in {spec['in']} differs from {closed}")
                elif rng == RDFS.Literal:
                    want = XSD.date   # OWL 2 has no xsd:date; the data and SHACL use it
                elif isinstance(rng, BNode):
                    want = ontology.value(rng, OWL.onDatatype)
                    if spec["minInclusive"] != Literal(1):
                        errors.append(f"{table}.{column}: no sh:minInclusive 1")
                else:
                    want = rng
                if not closed and spec["in"] is not None:
                    errors.append(f"{table}.{column}: sh:in without a value set")
                if spec["datatype"] != want:
                    errors.append(f"{table}.{column}: sh:datatype {spec['datatype']}, the range is {want}")
                mapped = bm.DATATYPES.get(prop, "xsd:string")
                if XSD[mapped[len("xsd:"):]] != spec["datatype"]:
                    errors.append(f"{table}.{column}: the mapping gives {mapped}, SHACL {spec['datatype']}")
                continue
            target = V.TABLE_CLASS[bm.fk_target(ddl, table, column)]
            if spec["class"] != T[target] or spec["max"] != Literal(1):
                errors.append(f"{table}.{column}: sh:class {spec['class']} (want {target}), max {spec['max']}")
            if kind == V.FK_REVERSE:   # <target> triad:prop <row>: the values on the target side are rows
                other = find(target, prop, False)
                if other and other["class"] != T[cls]:
                    errors.append(f"{target}: the values of triad:{prop} must be triad:{cls}")
    finally:
        ddl.close()
    # The rules without a column, and the subtypes.
    for cls, prop, inverse, target, lo, hi in [("Message", "contains", False, "Assertion", 1, None),
                                               ("ClinicalEntry", "about", True, "Assertion", 1, None),
                                               ("Staff", "ofStaff", True, "WorksIn", 1, None),
                                               ("Assertion", "supersedes", True, "Assertion", None, 1)]:
        spec = find(cls, prop, inverse)
        if spec and (spec["class"] != T[target] or spec["min"] != (lo and Literal(lo))
                     or spec["max"] != (hi and Literal(hi))):
            errors.append(f"{cls} {'^' if inverse else ''}triad:{prop}: {spec}")
    assert errors == []


def test_each_rule_has_a_message_and_a_sql_comment(shapes_graph):
    rules = (set(shapes_graph.subjects(RDF.type, SH.PropertyShape))
             | set(shapes_graph.subjects(RDF.type, SH.SPARQLConstraint))
             | {s for s in shapes_graph.subjects(RDF.type, SH.NodeShape) if shapes_graph.value(s, SH["or"])})
    assert len(rules) > 200
    for rule in rules:
        message = shapes_graph.value(rule, SH.message)
        assert isinstance(message, Literal) and len(str(message)) > 30, rule
        assert str(message)[0].isupper() and str(message).endswith("."), rule
    # In the file, the line above each rule is a comment that names its SQL (or the reason for no column).
    lines = bs.SHAPES_PATH.read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines):
        if re.match(r"shape:\S+ a sh:(PropertyShape|SPARQLConstraint)", line) or "a sh:NodeShape" in line \
                and "Issuer" in line:
            above = lines[number - 1]
            assert above.startswith("# "), line
    # Each SPARQL constraint has the prefixes and belongs to exactly one node shape.
    for constraint in shapes_graph.subjects(RDF.type, SH.SPARQLConstraint):
        assert shapes_graph.value(constraint, SH.prefixes) == URIRef(bs.SHAPES_IRI), constraint
        assert len(list(shapes_graph.subjects(SH.sparql, constraint))) == 1, constraint


def test_the_counts_of_the_rules(shapes_graph):
    """The counts of the report (plan 3.4): node shapes, property shapes and SPARQL constraints."""
    node_shapes = set(shapes_graph.subjects(RDF.type, SH.NodeShape))
    property_shapes = set(shapes_graph.subjects(RDF.type, SH.PropertyShape))
    sparql = set(shapes_graph.subjects(RDF.type, SH.SPARQLConstraint))
    assert (len(node_shapes), len(property_shapes), len(sparql)) == (29, 181, 28)
    assert len({c for c in sparql if str(c).startswith(SHAPE + "UK_")}) == 18


# ---------------------------------------------------------------------------------------------
# Each kind of rule, on all the shapes of that kind

def test_each_not_null_rule(seed, shapes_graph):
    graph, expected = copy_of(seed), []
    for cls, specs in shapes_of_class(shapes_graph).items():
        node = bare_node(graph, cls)
        expected += [(node, s["name"], "MinCount") for s in specs if s["min"] == Literal(1)]
    assert len(expected) == 81 + 9 + 5 + 3   # NOT NULL: 81 attributes, 9 + 5 foreign keys (both directions); 3 rules
    assert missing(shacl.validate(graph), expected) == []


def test_each_value_set_rule(seed, shapes_graph):
    graph, expected = copy_of(seed), []
    for cls, specs in shapes_of_class(shapes_graph).items():
        node = bare_node(graph, cls)
        for s in specs:
            if s["in"]:
                graph.add((node, s["path"], Literal("NotInTheSet")))
                expected.append((node, s["name"], "In"))
    assert len(expected) == 17
    assert missing(shacl.validate(graph), expected) == []


def test_each_datatype_rule(seed, shapes_graph):
    graph, expected = copy_of(seed), []
    for cls, specs in shapes_of_class(shapes_graph).items():
        node = bare_node(graph, cls)
        for s in specs:
            if s["datatype"] is not None:
                wrong = Literal(5) if s["datatype"] == XSD.string else Literal("wrong")
                graph.add((node, s["path"], wrong))
                expected.append((node, s["name"], "Datatype"))
    assert len(expected) == 138   # the 138 attribute columns
    # An ill-typed literal (the right datatype, but a text that is not a value of it) breaks the rule too.
    # rdflib is lenient: it reads "2026-10-30 10:00"^^xsd:dateTime as a valid time, so the test does not use it.
    with pytest.warns(UserWarning, match="weird boolean"):   # rdflib warns on the ill-typed boolean
        plant(graph, '<test/ill-Patient> a triad:Patient ; triad:dateOfBirth "1971-02-30"^^xsd:date .\n'
                     '<test/ill-Visit> a triad:Visit ; triad:endDate "2026-13-45T99:00:00Z"^^xsd:dateTime .\n'
                     '<test/ill-Staff> a triad:Staff ; triad:active "yes"^^xsd:boolean .\n'
                     '<test/ill-Assertion> a triad:Assertion ; triad:seq "one"^^xsd:integer .')
    expected += [("test/ill-Patient", "Patient-dateOfBirth", "Datatype"),
                 ("test/ill-Visit", "Visit-endDate", "Datatype"),
                 ("test/ill-Staff", "Staff-active", "Datatype"),
                 ("test/ill-Assertion", "Assertion-seq", "Datatype")]
    assert missing(shacl.validate(graph), expected) == []


def test_each_foreign_key_rule(seed, shapes_graph):
    """A value that is not a node of the right class (a dangling IRI, or a literal) breaks sh:class."""
    graph, expected = copy_of(seed), []
    dangling = kg("test/no-such-node")
    for cls, specs in shapes_of_class(shapes_graph).items():
        node = bare_node(graph, cls)
        for s in specs:
            if s["class"] is not None:
                graph.add((dangling, s["path"], node) if s["inverse"] else (node, s["path"], dangling))
                expected.append((node, s["name"], "Class"))
    assert len(expected) == 17 + 6 + 3   # the 17 FK columns, the 6 reverse FKs on the parent, 3 rules
    plant(graph, '<test/Assertion> triad:about "clinical-entry/1" .')
    result = shacl.validate(graph)
    assert missing(result, expected + [(kg("test/Assertion"), "Assertion-about", "NodeKind")]) == []


def test_each_single_value_rule(seed, shapes_graph):
    graph, expected = copy_of(seed), []
    for cls, specs in shapes_of_class(shapes_graph).items():
        node = bare_node(graph, cls)
        for s in specs:
            if s["max"] != Literal(1):
                continue
            if s["class"] is not None:
                for n in (1, 2):
                    other = kg(f"test/{cls}-{s['name']}-{n}")
                    graph.add((other, RDF.type, s["class"]))
                    graph.add((other, s["path"], node) if s["inverse"] else (node, s["path"], other))
            else:
                for value in good_values(s):
                    graph.add((node, s["path"], value))
            expected.append((node, s["name"], "MaxCount"))
    assert len(expected) == 137 + 17 + 1   # the Functional attributes, the FK columns, ^supersedes
    assert missing(shacl.validate(graph), expected) == []


def test_each_subtype_rule(seed):
    graph, expected = copy_of(seed), []
    assert {p: len(c) for p, c in CHILDREN.items()} == {"ClinicalEntry": 8, "Staff": 3}
    for parent, children in CHILDREN.items():
        none = bare_node(graph, parent)                             # no subtype
        two = kg(f"test/{parent}-two")
        for cls in (parent, *children[:2]):                         # two subtypes
            graph.add((two, RDF.type, T[cls]))
        expected += [(none, f"{parent}-subtype", "QualifiedMinCount"),
                     (two, f"{parent}-subtype", "QualifiedMaxCount")]
        for child in children:                                       # a subtype that is not of the parent class
            node = kg(f"test/only-{child}")
            graph.add((node, RDF.type, T[child]))
            expected.append((node, f"{child}-type", "HasValue"))
    assert missing(shacl.validate(graph), expected) == []


# The 18 keys (owl:hasKey) and their UNIQUE constraints. A test compares this table with triad.ttl.
KEYS = {
    **{f"UK_{c}_Identifier": (c, ("identifierSystem", "identifierValue")) for c in (
        "Department", "Location", "Staff", "Visit", "ClinicalEntry", "Message", "ChatSession", "AuditEvent")},
    "UK_Patient_Name_DateOfBirth": ("Patient", ("name", "dateOfBirth")),
    "UK_PatientIdentifier_System_Value": ("PatientIdentifier", ("identifierSystem", "identifierValue")),
    "UK_Medication_Code_CodeSystem": ("Medication", ("code", "codeSystem")),
    "UK_Assertion_MessageId_Seq": ("Assertion", ("inMessage", "seq")),
    "UK_ChatTurn_ChatSessionId_Seq": ("ChatTurn", ("inSession", "seq")),
    "UK_ChatTurn_ChatSessionId_ClientTurnId": ("ChatTurn", ("inSession", "clientTurnId")),
    "UK_WorksIn_StaffId_DepartmentId_RoleCode": ("WorksIn", ("ofStaff", "atDepartment", "roleCode")),
    "UK_VisitLocation_VisitId_LocationId_StartDate": ("VisitLocation", ("ofVisit", "atLocation", "startDate")),
    "UK_Citation_ChatTurnId_AssertionId": ("Citation", ("byTurn", "citedAssertion")),
    "UK_CareTeamMember_CareTeamId_Member": ("CareTeamMember", ("memberOf", "memberSystem", "memberValue")),
}


def test_each_key_rule(seed, shapes_graph, ontology):
    """A new node with the key values of a seed node: both nodes break the key (UNIQUE)."""
    assert {(c, frozenset(p)) for c, p in KEYS.values()} == {
        (str(c)[len(TRIAD):], frozenset(str(p)[len(TRIAD):] for p in props)) for c, props in bo.keys(ontology)}
    assert {str(c)[len(SHAPE):] for c in shapes_graph.subjects(RDF.type, SH.SPARQLConstraint)
            if str(c).startswith(SHAPE + "UK_")} == set(KEYS)
    graph, expected = copy_of(seed), []
    for name, (cls, props) in KEYS.items():
        original = sorted(seed.subjects(RDF.type, T[cls]))[0]
        twin = kg(f"test/twin-{name}")
        graph.add((twin, RDF.type, T[cls]))
        for prop in props:
            if prop in V.NAMED_INVERSES:   # the key uses the named inverse; the store has the stored property
                stored = T[V.NAMED_INVERSES[prop]]
                owners = list(seed.subjects(stored, original))
                assert owners, (name, prop)
                for owner in owners:
                    graph.add((owner, stored, twin))
            else:
                values = list(seed.objects(original, T[prop]))
                assert values, (name, prop)
                for value in values:
                    graph.add((twin, T[prop], value))
        expected += [(original, name, "SPARQL"), (twin, name, "SPARQL")]
    result = shacl.validate(graph)
    assert missing(result, expected) == []
    # The message names the other node.
    patient = next(v for v in result.violations if v.source == SHAPE + "UK_Patient_Name_DateOfBirth"
                   and v.focus == KG + "patient/1")
    assert patient.value == KG + "test/twin-UK_Patient_Name_DateOfBirth"
    assert KG + "test/twin-UK_Patient_Name_DateOfBirth" in patient.message


# ---------------------------------------------------------------------------------------------
# The cases of 05_constraint_violations.sql and the other rules of plan 1.7

@dataclass(frozen=True)
class Case:
    """A planted error: Turtle to add, triple patterns to remove, and the (focus, shape, component) to expect."""
    plant: str = ""
    drop: tuple = ()
    expect: Union[tuple, Callable[[Graph], list]] = ()


NO_RDF_FORM = "no RDF form"


# The Turtle of the rows that the SQL cases insert. Each function gives the triples of one row.

def message(n: int, issuer: str = "", origin: str = "Staff", channel: str = "InPerson") -> str:
    issued = f"<{issuer}> triad:issues <message/{n}> .\n" if issuer else ""
    return (issued + f'<message/{n}> a triad:Message ; triad:identifierSystem "https://triad.example/fhir/sid/message" ;\n'
            f'    triad:identifierValue "MSG-TEST-{n}" ; triad:channel "{channel}" ; triad:origin "{origin}" ;\n'
            f'    triad:sentAt "2026-10-30T08:06:00-04:00"^^xsd:dateTime ; triad:text "A test message." .\n')


def patient(n: int) -> str:
    """A new patient with one visit (visit/n) and one Observation entry (clinical-entry/n) in that visit."""
    return (f'<patient/{n}> a triad:Patient ; triad:name "Test Patient {n}" ; '
            f'triad:dateOfBirth "1980-01-01"^^xsd:date ; triad:patientSex "male" .\n'
            + visit(n, f"patient/{n}") + entry(n, f"visit/{n}"))


def visit(n: int, owner: str, start: str = "2026-10-30T08:00:00-04:00", extra: str = "") -> str:
    return (f'<{owner}> triad:hasVisit <visit/{n}> .\n'
            f'<visit/{n}> a triad:Visit ; triad:identifierSystem "https://triad.example/fhir" ;\n'
            f'    triad:identifierValue "Encounter/test-{n}" ; triad:visitClass "AMB" ;\n'
            f'    triad:startDate "{start}"^^xsd:dateTime {extra}.\n')


def entry(n: int, during: str) -> str:
    return (f'<clinical-entry/{n}> a triad:ClinicalEntry , triad:Observation ; triad:during <{during}> ;\n'
            f'    triad:identifierSystem "https://triad.example/fhir" ; triad:identifierValue "Observation/test-{n}" ;\n'
            f'    triad:code "8867-4" ; triad:codeSystem "http://loinc.org" ; triad:display "Heart rate" ;\n'
            f'    triad:value "88" ; triad:recordedAt "2026-10-30T08:05:00-04:00"^^xsd:dateTime .\n')


def assertion(n: int, in_message: str, about: str, at: str = "2026-10-30T08:06:00-04:00", seq: int = 99,
              supersedes: str = "") -> str:
    link = f" ; triad:supersedes <{supersedes}>" if supersedes else ""
    return (f'<{in_message}> triad:contains <assertion/{n}> .\n'
            f'<assertion/{n}> a triad:Assertion ; triad:seq {seq} ; triad:about <{about}>{link} ;\n'
            f'    triad:assertedAt "{at}"^^xsd:dateTime ; triad:intent "Report" ; triad:source "Human" ;\n'
            f'    triad:verification "Unconfirmed" ; triad:statement "A test claim." .\n')


def works_in_at(graph: Graph, department: str) -> list:
    return [(w, "WorksIn-atDepartment", "Class") for w in graph.subjects(T.atDepartment, kg(department))]


# The 26 cases of 05_constraint_violations.sql, in the order of the file (shapes/README.md has the same table).
# The SQL inserts a row; the RDF form adds the triples of that row. Patient A is kg:patient/1; her penicillin
# allergy is kg:clinical-entry/1 (current assertion kg:assertion/3, which supersedes 2, which supersedes 1).
# kg:message/5 is MSG-ELENA-2026-10-02. E1001, E1002 and E1005 are kg:staff/1, 2 and 5 (E1005 is a doctor).
SQL_CASES: dict[str, Union[Case, str]] = {
    "duplicate patient key (Name, DateOfBirth)": Case(
        '<patient/9001> a triad:Patient ; triad:name "Elena Marsh" ; triad:dateOfBirth "1971-05-14"^^xsd:date ;\n'
        '    triad:patientSex "female" .',
        expect=(("patient/1", "UK_Patient_Name_DateOfBirth", "SPARQL"),
                ("patient/9001", "UK_Patient_Name_DateOfBirth", "SPARQL"))),
    "duplicate patient identifier": Case(
        '<patient/1> triad:identifier <patient-identifier/9001> .\n'
        '<patient-identifier/9001> a triad:PatientIdentifier ;\n'
        '    triad:identifierSystem "https://triad.example/fhir/sid/mrn" ; triad:identifierValue "MRN-000001" .',
        expect=(("patient-identifier/1", "UK_PatientIdentifier_System_Value", "SPARQL"),
                ("patient-identifier/9001", "UK_PatientIdentifier_System_Value", "SPARQL"))),
    "a visit for a patient that does not exist": Case(
        visit(9001, "patient/99999"),
        expect=(("visit/9001", "Visit-inverse-hasVisit", "Class"),)),
    "ISA mismatch (a Nurse row for a staff member whose role is Doctor)": Case(
        '<staff/5> a triad:Nurse ; triad:designation "RN" .',
        expect=(("staff/5", "Staff-subtype", "QualifiedMaxCount"),)),
    # A Doctor row for E1002 (a nurse) with Role = 'Nurse'. Role gives no triple; the row gives a second subtype.
    "a subtype row with the wrong role value": Case(
        '<staff/2> a triad:Doctor .',
        expect=(("staff/2", "Staff-subtype", "QualifiedMaxCount"),)),
    "a nurse designation that is not in the value set": Case(
        '<staff/9001> a triad:Staff , triad:Nurse ; triad:identifierSystem "https://triad.example/fhir/sid/employee" ;\n'
        '    triad:identifierValue "E9001" ; triad:name "Test Nurse" ; triad:active true ; triad:designation "Chief" .',
        expect=(("staff/9001", "Nurse-designation", "In"),)),
    "a message with no issuer that does not come from the patient": Case(
        message(9001, channel="Phone") + assertion(9001, "message/9001", "clinical-entry/2"),
        expect=(("message/9001", "MessageIssuerShape", "Or"),)),
    "a channel that is not in the value set": Case(
        message(9001, issuer="staff/1", channel="Pigeon"),
        expect=(("message/9001", "Message-channel", "In"),)),
    "a visit that ends before it starts": Case(
        visit(9001, "patient/1", start="2026-10-30T10:00:00-04:00",
              extra='; triad:endDate "2026-10-30T09:00:00-04:00"^^xsd:dateTime '),
        expect=(("visit/9001", "Visit-dates", "LessThanOrEquals"),)),
    "a visit class that is not in the value set": Case(
        visit(9001, "patient/1").replace('"AMB"', '"XYZ"'),
        expect=(("visit/9001", "Visit-visitClass", "In"),)),
    "a date of birth that is not a date": Case(
        '<patient/9001> a triad:Patient ; triad:name "Test Patient Date" ;\n'
        '    triad:dateOfBirth "not a date"^^xsd:date ; triad:patientSex "female" .',
        expect=(("patient/9001", "Patient-dateOfBirth", "Datatype"),)),
    "change an assertion (assertions are append-only)": NO_RDF_FORM,
    "delete an assertion (assertions are append-only)": NO_RDF_FORM,
    "a new claim about an entry that has a current assertion, without superseding it": Case(
        assertion(9001, "message/5", "clinical-entry/1"),
        expect=(("clinical-entry/1", "ClinicalEntry-one-head", "SPARQL"),)),
    "supersede an assertion that is newer than the new assertion": Case(
        assertion(9001, "message/5", "clinical-entry/1", at="2020-01-01T08:00:00-05:00", supersedes="assertion/3"),
        expect=(("assertion/9001", "Assertion-supersedes-not-newer", "SPARQL"),)),
    # A new Observation entry in the visit of 2026-10-02, and an assertion that supersedes the first penicillin
    # assertion. kg:assertion/2 supersedes it already.
    "a second assertion that supersedes the same assertion (Supersedes is one-to-one)": Case(
        entry(9001, "visit/3") + assertion(9001, "message/5", "clinical-entry/9001", supersedes="assertion/1"),
        expect=(("assertion/1", "Assertion-inverse-supersedes", "MaxCount"),)),
    "supersede an assertion of another patient": Case(
        patient(9001) + message(9001, issuer="staff/2")
        + assertion(9001, "message/9001", "clinical-entry/9001", seq=1, supersedes="assertion/3"),
        expect=(("assertion/9001", "Assertion-supersedes-same-patient", "SPARQL"),)),
    "one message with assertions about two patients": Case(
        patient(9001) + assertion(9001, "message/5", "clinical-entry/9001"),
        expect=(("message/5", "Message-one-patient", "SPARQL"),)),
    "a care-team member that is not a staff member": Case(
        '<clinical-entry/8> triad:member <care-team-member/9001> .\n'   # kg:clinical-entry/8: the care team
        '<care-team-member/9001> a triad:CareTeamMember ;\n'
        '    triad:memberSystem "https://triad.example/fhir/sid/employee" ; triad:memberValue "E0000" ;\n'
        '    triad:memberRole "Nurse" .',
        expect=(("care-team-member/9001", "CareTeamMember-staff", "SPARQL"),)),
    "a citation from a user turn (only the assistant cites)": Case(
        '<citation/9001> a triad:Citation ; triad:byTurn <chat-turn/1> ; triad:citedAssertion <assertion/1> ;\n'
        '    triad:rank 1 .',   # kg:chat-turn/1 is the user turn, kg:chat-turn/2 the assistant turn
        expect=(("citation/9001", "Citation-assistant-turn", "SPARQL"),)),
    "a citation of an assertion about another patient": Case(
        patient(9001) + message(9001, issuer="staff/2") + assertion(9001, "message/9001", "clinical-entry/9001", seq=1)
        + '<citation/9001> a triad:Citation ; triad:byTurn <chat-turn/2> ; triad:citedAssertion <assertion/9001> ;\n'
          '    triad:rank 2 .',
        expect=(("citation/9001", "Citation-patient", "SPARQL"),)),
    "an audit record of a chat turn with another patient as subject": Case(
        '<audit-event/9001> a triad:AuditEvent ;\n'
        '    triad:identifierSystem "https://triad.example/fhir/sid/audit-event" ; triad:identifierValue "AUDIT-TEST" ;\n'
        '    triad:at "2026-10-30T08:00:00-04:00"^^xsd:dateTime ; triad:action "ask" ; triad:auditOutcome "Allowed" ;\n'
        '    triad:actorRole "Doctor" ; triad:actorSystem "https://triad.example/fhir/sid/employee" ;\n'
        '    triad:actorValue "E1005" ; triad:subjectName "Someone Else" ;\n'
        '    triad:subjectDateOfBirth "1990-01-01"^^xsd:date ; triad:path "/api/chat" ; triad:inTurn <chat-turn/2> .',
        expect=(("audit-event/9001", "AuditEvent-subject", "SPARQL"),)),
    "change an audit record (audit records are append-only)": NO_RDF_FORM,
    # A graph has no update event. But the state after the change breaks a rule: the chat session keeps the old
    # key as values, so its citation no longer cites an assertion of the patient of the session.
    "change the key of a patient (the logs keep Name and DateOfBirth as values)": Case(
        '<patient/1> triad:name "Elena M." .', drop=(("patient/1", "triad:name", None),),
        expect=(("citation/1", "Citation-patient", "SPARQL"),)),
    # A delete of an individual removes the triples whose subject it is (also triad:hasVisit).
    "delete a patient who has visits (the app shows 409)": Case(
        drop=(("patient/1", None, None),),
        expect=tuple((f"visit/{n}", "Visit-inverse-hasVisit", "MinCount") for n in (1, 2, 3))),
    "delete a department that has staff (the app shows 409; journey Use case 8)": Case(
        drop=(("department/1", None, None),),   # kg:department/1 is TRIAD-GH-EMER
        expect=lambda graph: works_in_at(graph, "department/1")),
}

# The other rules of plan 1.7 that SHACL holds (the generic tests above hold NOT NULL, CHECK ... IN, the datatypes,
# the foreign keys, the single values, the subtypes and the keys).
RULE_CASES: dict[str, Case] = {
    "a visit location that ends before it starts": Case(
        '<visit-location/1> triad:endDate "2019-06-12T10:00:00-04:00"^^xsd:dateTime .',
        drop=(("visit-location/1", "triad:endDate", None),),
        expect=(("visit-location/1", "VisitLocation-dates", "LessThanOrEquals"),)),
    "a role that ends before it starts": Case(
        '<works-in/5> triad:roleEndDate "2012-01-01"^^xsd:date .',   # the role starts on 2012-03-03
        expect=(("works-in/5", "WorksIn-dates", "LessThanOrEquals"),)),
    "an assertion that supersedes itself": Case(
        '<assertion/1> triad:supersedes <assertion/1> .',
        expect=(("assertion/1", "Assertion-supersedes-not-reflexive", "SPARQL"),)),
    "a cycle of supersedes links": Case(
        '<assertion/1> triad:supersedes <assertion/3> .',   # 3 -> 2 -> 1 -> 3
        expect=tuple((f"assertion/{n}", "Assertion-supersedes-no-cycle", "SPARQL") for n in (1, 2, 3))),
    "a message with no assertion": Case(
        drop=(("message/4", "triad:contains", None),),
        expect=(("message/4", "Message-contains", "MinCount"),)),
    "an entry with no assertion": Case(
        drop=((None, "triad:about", "clinical-entry/6"),),
        expect=(("clinical-entry/6", "ClinicalEntry-inverse-about", "MinCount"),)),
    "a staff member who works in no department": Case(
        drop=((None, "triad:ofStaff", "staff/3"),),
        expect=(("staff/3", "Staff-inverse-ofStaff", "MinCount"),)),
    "a staff member with no subtype": Case(
        drop=(("staff/3", "a", "triad:Nurse"), ("staff/3", "a", "triad:Doctor"), ("staff/3", "a", "triad:MOA")),
        expect=(("staff/3", "Staff-subtype", "QualifiedMinCount"),)),
    "an entry with two subtypes": Case(
        '<clinical-entry/2> a triad:Diagnosis ; triad:clinicalStatus "active" .',
        expect=(("clinical-entry/2", "ClinicalEntry-subtype", "QualifiedMaxCount"),)),
    "a language of a node that is not a staff member": Case(
        '<staff/99999> triad:language "en" .',
        expect=(("staff/99999", "language-subject", "HasValue"),)),
    "a sequence number less than 1": Case(
        '<assertion/1> triad:seq 0 .', drop=(("assertion/1", "triad:seq", None),),
        expect=(("assertion/1", "Assertion-seq", "MinInclusive"),)),
    "a care-team member of no care team": Case(
        drop=((None, "triad:member", "care-team-member/2"),),
        expect=(("care-team-member/2", "CareTeamMember-inverse-member", "MinCount"),)),
}


def run_case(seed: Graph, case: Case) -> tuple[shacl.ShaclResult, list]:
    graph = copy_of(seed)
    for pattern in case.drop:
        graph.remove(tuple(term(t) for t in pattern))
    if case.plant:
        plant(graph, case.plant)
    expected = case.expect(seed) if callable(case.expect) else list(case.expect)
    assert expected, "a case must expect at least one violation"
    return shacl.validate(graph), expected


@pytest.mark.parametrize("name", [n for n, c in SQL_CASES.items() if isinstance(c, Case)])
def test_each_sql_case_with_an_rdf_form_breaks_its_shape(seed, name):
    result, expected = run_case(seed, SQL_CASES[name])
    assert missing(result, expected) == [], result.summary(50)


@pytest.mark.parametrize("name", list(RULE_CASES))
def test_each_other_rule_breaks_its_shape(seed, name):
    result, expected = run_case(seed, RULE_CASES[name])
    assert missing(result, expected) == [], result.summary(50)


def test_the_sql_cases_are_the_cases_of_the_sql_file():
    cases = re.findall(r"^-- CASE: (.+)$", VIOLATIONS_SQL.read_text(encoding="utf-8"), flags=re.MULTILINE)
    assert len(cases) == 26
    assert list(SQL_CASES) == cases
    assert [n for n, c in SQL_CASES.items() if c == NO_RDF_FORM] == [
        "change an assertion (assertions are append-only)", "delete an assertion (assertions are append-only)",
        "change an audit record (audit records are append-only)"]
    # shapes/README.md has one row for each case, in the same order.
    readme = (config.SEMANTIC_DIR / "shapes" / "README.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| (\d+) \| (.+?) \|", readme, flags=re.MULTILINE)
    assert [(int(n), text) for n, text in rows] == list(enumerate(cases, 1))


# ---------------------------------------------------------------------------------------------
# Times with different offsets and milliseconds

def test_a_date_pair_compares_instants(seed):
    graph = plant(copy_of(seed), "\n".join(
        f'<visit/{n}> triad:startDate "{start}"^^xsd:dateTime ; triad:endDate "{end}"^^xsd:dateTime .'
        for n, start, end in [
            (9001, "2026-10-31T01:00:00+05:30", "2026-10-30T16:00:00-04:00"),   # 19:30Z <= 20:00Z: correct
            (9002, "2026-10-30T16:00:00-04:00", "2026-10-31T01:00:00+05:30"),   # 20:00Z > 19:30Z: wrong
            (9003, "2026-10-30T14:00:00Z", "2026-10-30T10:00:00-04:00"),        # the same instant: correct
            (9004, "2026-10-30T10:00:00.250-04:00", "2026-10-30T10:00:00.100-04:00")]))   # wrong
    for n in (9001, 9002, 9003, 9004):
        graph.add((kg(f"visit/{n}"), RDF.type, T.Visit))
    result = shacl.validate(graph)
    wrong = {v.focus for v in result.violations if v.source == SHAPE + "Visit-dates"}
    assert wrong == {KG + "visit/9002", KG + "visit/9004"}


def test_the_superseded_assertion_compares_instants(seed):
    """kg:assertion/3 was asserted at 2026-10-02T11:40:00-04:00 (15:40Z)."""
    graph = plant(copy_of(seed), assertion(9001, "message/5", "clinical-entry/1", supersedes="assertion/3",
                                           at="2026-10-02T08:45:00-07:00"))      # 15:45Z: not newer, correct
    result = shacl.validate(graph)
    assert not result.has(KG + "assertion/9001", SHAPE + "Assertion-supersedes-not-newer")
    graph = plant(copy_of(seed), assertion(9001, "message/5", "clinical-entry/1", supersedes="assertion/3",
                                           at="2026-10-02T20:30:00+05:30"))      # 15:00Z: older, wrong
    result = shacl.validate(graph)
    assert result.has(KG + "assertion/9001", SHAPE + "Assertion-supersedes-not-newer", "SPARQL")


def test_a_patient_message_with_no_issuer_conforms(seed):
    graph = plant(copy_of(seed), message(9001, origin="Patient", channel="App")
                  + assertion(9001, "message/9001", "clinical-entry/1", seq=1, supersedes="assertion/3"))
    result = shacl.validate(graph)
    assert result.conforms, result.summary()


# ---------------------------------------------------------------------------------------------
# The module infrastructure/rdf/shacl.py

def test_validate_reads_files_and_graphs(seed, tmp_path):
    by_file = shacl.validate(shacl.SEED_PATH)
    assert by_file.conforms and by_file.triples == len(seed)
    compressed = tmp_path / "seed.nt.gz"
    compressed.write_bytes(gzip.compress(seed.serialize(format="nt", encoding="utf-8")))
    assert shacl.validate(compressed).triples == len(seed)
    bad = plant(copy_of(seed), '<patient/1> triad:patientSex "none" .')
    result = shacl.validate(bad, shacl.SHAPES_PATH)
    assert not result.conforms
    focus, source, message = result.violations[0][:3]
    assert (focus, source) == (KG + "patient/1", SHAPE + "Patient-patientSex")
    assert "female, male, other, unknown" in message
    assert result.pairs() == {(KG + "patient/1", SHAPE + "Patient-patientSex")}
    with pytest.raises(shacl.ShaclError, match="does not exist"):
        shacl.validate(tmp_path / "none.rdf")
    (tmp_path / "graph.json").write_text("{}")
    with pytest.raises(shacl.ShaclError, match="file type"):
        shacl.validate(tmp_path / "graph.json")


def test_the_command(seed, tmp_path, capsys):
    assert shacl.main([str(shacl.SEED_PATH)]) == 0
    assert "The graph conforms: no violation." in capsys.readouterr().out
    bad = plant(copy_of(seed), '<visit/1> triad:visitClass "XYZ" .\n<staff/99999> triad:language "en" .')
    path = tmp_path / "bad.ttl"
    bad.serialize(path, format="turtle")
    assert shacl.main([str(path), "--limit", "1"]) == 1
    out = capsys.readouterr().out
    assert "The graph does not conform: 3 violations of 2 rules." in out   # visitClass: In and MaxCount
    assert "shape:Visit-visitClass" in out and "... and 2 more violations." in out
    assert shacl.main([str(tmp_path / "none.ttl")]) == 2
    assert "does not exist" in capsys.readouterr().err


def test_the_module_loads_no_rdf_package():
    code = ("import sys; import infrastructure.rdf.shacl; "
            "bad = [m for m in ('rdflib', 'pyshacl') if m in sys.modules]; assert not bad, bad")
    subprocess.run([sys.executable, "-c", code], cwd=config.BACKEND_DIR, check=True)
