"""The TRIAD ontology: the build of triad.owl and its checks (models/semantic/build_ontology.py)."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from rdflib import BNode, Graph, Literal
from rdflib.collection import Collection
from rdflib.compare import isomorphic
from rdflib.namespace import OWL, RDF, RDFS

from models.semantic import build_ontology as bo
from models.semantic import vocabulary as V

T = bo.TRIAD
BACKEND = bo.HERE.parents[1]
ONTOLOGY_MD = (bo.HERE / "ontology.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def source() -> Graph:
    return bo.load_graph()


@pytest.fixture
def graph(source) -> Graph:
    """A copy of the ontology that a test can change."""
    copy = Graph()
    for triple in source:
        copy.add(triple)
    return copy


def union_of(g: Graph, *classes) -> BNode:
    node, members = BNode(), BNode()
    Collection(g, members, list(classes))
    g.add((node, RDF.type, OWL.Class))
    g.add((node, OWL.unionOf, members))
    return node


# ---------------------------------------------------------------------------
# The build
# ---------------------------------------------------------------------------

def test_the_build_runs_and_a_rerun_gives_the_same_bytes(tmp_path):
    # The committed triad.owl comes from an earlier run. The build also writes, reads back and compares.
    out = tmp_path / "triad.owl"
    result = bo.build(out)
    assert result["Classes"] == 28
    assert out.read_bytes() == bo.OWL_PATH.read_bytes(), "triad.owl is old: run build_ontology.py"


def test_triad_owl_is_the_graph_of_triad_ttl(source):
    back = Graph().parse(bo.OWL_PATH, format="xml")
    assert isomorphic(source, back)


def test_all_checks_pass_on_the_source(source):
    assert bo.run_checks(source) == (28, 27)


@pytest.mark.skipif(not os.environ.get("TRIAD_PROTEGE_OWL"), reason="set TRIAD_PROTEGE_OWL to a Protégé re-save")
def test_the_protege_resave_is_the_same_graph():
    # Plan Phase 2: open triad.owl in Protégé, save it as RDF/XML to a temporary file, and set TRIAD_PROTEGE_OWL.
    assert bo.compare(Path(os.environ["TRIAD_PROTEGE_OWL"])) == []


def protege_style_copy(source: Graph) -> Graph:
    """triad.owl as Protégé 5.6 saves it (issue 6): rdf:type rdf:List on the list nodes, owl:inverseOf flipped."""
    g = Graph()
    for s, p, o in source:
        if p == OWL.inverseOf and not isinstance(s, BNode):
            s, o = o, s
        g.add((s, p, o))
    for node in {s for s, p, _ in source if p == RDF.first}:
        g.add((node, RDF.type, RDF.List))
    return g


def test_the_compare_ignores_how_protege_writes_the_file(source, tmp_path):
    copy = protege_style_copy(source)
    assert len(copy) > len(source) and {(s, o) for s, _, o in copy.triples((None, OWL.inverseOf, None))} != \
        {(s, o) for s, _, o in source.triples((None, OWL.inverseOf, None))}
    path = tmp_path / "protege.owl"
    copy.serialize(path, format="xml")
    assert bo.compare(path) == []
    copy.remove((T.Patient, RDFS.label, None))
    copy.serialize(path, format="xml")
    assert bo.compare(path) and all(line.startswith("- <") and "Patient" in line for line in bo.compare(path))


def test_the_script_checks_the_committed_file():
    script = bo.HERE / "build_ontology.py"
    done = subprocess.run([sys.executable, str(script), "--check"], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    assert "Checks passed." in done.stdout


# ---------------------------------------------------------------------------
# Each check stops on a known error
# ---------------------------------------------------------------------------

def test_the_tree_check_stops_on_a_loop(graph):
    # A direct link Message -> Patient closes the loop Message - Assertion - ClinicalEntry - Visit - Patient.
    graph.add((T.sentFor, RDF.type, OWL.ObjectProperty))
    graph.add((T.sentFor, RDFS.domain, T.Message))
    graph.add((T.sentFor, RDFS.range, T.Patient))
    with pytest.raises(bo.CheckError, match="Loop found: sentFor links"):
        bo.check_tree(graph)


def test_the_tree_check_ignores_the_inverses_and_the_derived_properties(source):
    # assertedBy (Assertion -> Staff) and visitOf (Visit -> Patient) would close loops if they were edges.
    assert bo.check_tree(source) == (28, 27)
    assert T.assertedBy not in bo.stored_properties(source)
    assert T.visitOf not in bo.stored_properties(source)


def test_the_tree_check_stops_on_a_class_with_no_link(graph):
    graph.add((T.Ward, RDF.type, OWL.Class))
    with pytest.raises(bo.CheckError, match="2 parts"):
        bo.check_tree(graph)


def test_the_coverage_check_stops_on_a_missing_column(graph):
    conn = bo.ddl_connection()
    conn.execute("ALTER TABLE Patient ADD COLUMN Nickname TEXT")
    with pytest.raises(bo.CheckError, match="Patient.Nickname maps to no property"):
        bo.check_coverage(graph, conn)


def test_the_coverage_check_stops_on_a_missing_not_null_restriction(graph):
    for r in list(graph.objects(T.Patient, RDFS.subClassOf)):
        if graph.value(r, OWL.onProperty) == T.name:
            graph.remove((T.Patient, RDFS.subClassOf, r))
    with pytest.raises(bo.CheckError, match="Patient.Name is NOT NULL"):
        bo.check_coverage(graph, bo.ddl_connection())


def test_the_coverage_check_stops_on_a_missing_key(graph):
    graph.remove((T.Medication, OWL.hasKey, None))
    with pytest.raises(bo.CheckError, match=r"UNIQUE Medication\(Code, CodeSystem\) has no owl:hasKey"):
        bo.check_coverage(graph, bo.ddl_connection())


def test_the_coverage_check_stops_on_a_wrong_fk_direction(graph):
    # Visit.PatientId is stored as Patient -> Visit (hasVisit). The other direction is wrong.
    graph.set((T.hasVisit, RDFS.domain, T.Visit))
    graph.set((T.hasVisit, RDFS.range, T.Patient))
    with pytest.raises(bo.CheckError, match="Visit.PatientId"):
        bo.check_coverage(graph, bo.ddl_connection())


def test_the_datatype_map_check_stops_on_xsd_date(graph):
    graph.set((T.dateOfBirth, RDFS.range, bo.XSD.date))
    with pytest.raises(bo.CheckError, match="xsd:date is not in the OWL 2 datatype map"):
        bo.check_datatypes(graph)


def test_the_closed_range_check_stops_on_a_shared_closed_range(graph):
    # Revision 1 of the plan shared one "status" between CareTeam (closed) and Prescription (text).
    graph.set((T.careTeamStatus, RDFS.domain, union_of(graph, T.CareTeam, T.Prescription)))
    with pytest.raises(bo.CheckError, match="careTeamStatus has a closed range, but it is shared"):
        bo.check_closed_ranges(graph)


def test_the_value_set_check_stops_on_a_value_that_the_ddl_does_not_allow(graph):
    values = graph.value(graph.value(T.intent, RDFS.range), OWL.oneOf)
    Collection(graph, values).append(Literal("Guess"))
    with pytest.raises(bo.CheckError, match="Assertion.Intent: the DDL allows"):
        bo.check_value_sets(graph, bo.ddl_connection())


def test_the_simple_property_check_stops_on_a_functional_chain(graph):
    graph.add((T.assertedBy, RDF.type, OWL.FunctionalProperty))
    with pytest.raises(bo.CheckError, match="assertedBy is not simple"):
        bo.check_simple_properties(graph)


def test_a_super_property_of_a_chain_is_not_simple(graph):
    # assertedBy is below prov:wasAttributedTo, so prov:wasAttributedTo is not simple (OWL 2, 11.1).
    graph.add((bo.PROV.wasAttributedTo, RDF.type, OWL.FunctionalProperty))
    with pytest.raises(bo.CheckError, match="prov:wasAttributedTo is not simple"):
        bo.check_simple_properties(graph)


def test_the_simple_property_check_stops_on_a_cardinality_on_a_transitive_property(graph):
    restriction = BNode()
    graph.add((restriction, RDF.type, OWL.Restriction))
    graph.add((restriction, OWL.onProperty, T.supersedesTransitively))
    graph.add((restriction, OWL.maxCardinality, Literal(1, datatype=bo.XSD.nonNegativeInteger)))
    graph.add((T.Assertion, RDFS.subClassOf, restriction))
    with pytest.raises(bo.CheckError, match="supersedesTransitively, which is not simple"):
        bo.check_simple_properties(graph)


def test_the_domain_check_stops_on_two_domains(graph):
    graph.add((T.name, RDFS.domain, T.Patient))
    with pytest.raises(bo.CheckError, match="name has 2 rdfs:domain axioms"):
        bo.check_domains_ranges(graph)


def test_the_declaration_check_stops_on_a_term_with_two_types(graph):
    graph.add((T.name, RDF.type, OWL.ObjectProperty))
    with pytest.raises(bo.CheckError, match="name has 2 declarations"):
        bo.check_declarations(graph)


def test_the_declaration_check_stops_on_an_import(graph):
    graph.add((bo.ONTOLOGY, OWL.imports, bo.PROV_O))
    with pytest.raises(bo.CheckError, match="owl:imports"):
        bo.check_declarations(graph)


def test_the_label_check_stops_on_a_missing_comment(graph):
    graph.remove((T.Visit, RDFS.comment, None))
    with pytest.raises(bo.CheckError, match="Visit has no rdfs:comment"):
        bo.check_labels(graph)


# ---------------------------------------------------------------------------
# The ontology agrees with ontology.md and vocabulary.py
# ---------------------------------------------------------------------------

def test_the_counts_equal_ontology_md(source):
    section = ONTOLOGY_MD.split("## 12. Counts")[1].split("\n## ")[0]
    table = {name: int(value) for name, value in re.findall(r"^\| ([^|]+?) \| (\d+) \|$", section, re.M)}
    expected = bo.counts(source)
    expected["Tree nodes"], expected["Tree edges"] = bo.check_tree(source)
    assert table == expected


def test_ontology_md_maps_each_column_as_vocabulary_does():
    rows = dict(((t, c), term) for t, c, term in
                re.findall(r"^\| (\w+)\.(\w+) \| (`triad:\w+`|—) \|", ONTOLOGY_MD, re.M))
    expected = {key: f"`triad:{term}`" for key, (term, _) in V.COLUMNS.items()}
    expected.update({key: "—" for key in V.NO_PROPERTY})
    assert rows == expected
    assert len(rows) == 209


def test_the_stored_properties_are_the_fk_columns(source):
    assert {bo.local(p) for p in bo.stored_properties(source)} == V.stored_object_properties()
    assert len(V.CLASS_PATHS) == 17


def test_each_date_only_property_has_the_range_rdfs_literal(source):
    for term in ("dateOfBirth", "subjectDateOfBirth", "roleStartDate", "roleEndDate"):
        assert source.value(T[term], RDFS.range) == RDFS.Literal


# ---------------------------------------------------------------------------
# The Direct Mapping example (plan 3.6)
# ---------------------------------------------------------------------------

def test_the_direct_mapping_example_shows_both_mappings():
    text = bo.direct_mapping_example()
    example = Graph().parse(data=text, format="turtle")       # the output is valid Turtle
    dm, kg = bo.DM_BASE, V.KG
    triples = {(str(s), str(p), str(o)) for s, p, o in example}
    assert (f"{dm}Assertion/Id=3", f"{dm}Assertion#ref-SupersedesId", f"{dm}Assertion/Id=2") in triples
    assert (f"{dm}Assertion/Id=3", f"{dm}Assertion#MessageId", "5") in triples
    assert (f"{kg}assertion/3", str(T.supersedes), f"{kg}assertion/2") in triples
    assert (f"{kg}message/5", str(T.contains), f"{kg}assertion/3") in triples
    assert [o.datatype for o in example.objects(None, T.assertedAt)] == [bo.XSD.dateTime]
    assert not any(p == str(T) + "id" for _, p, _ in triples)


# ---------------------------------------------------------------------------
# The dependency rule (plan, "Repository layout")
# ---------------------------------------------------------------------------

def test_the_inner_layers_import_no_rdf_library():
    pattern = re.compile(r"^\s*(import|from)\s+(rdflib|pyoxigraph|SPARQLWrapper|morph_kgc|pyshacl)\b", re.M)
    found = [str(path.relative_to(BACKEND)) for layer in ("domain", "application", "api")
             for path in sorted((BACKEND / layer).rglob("*.py")) if pattern.search(path.read_text(encoding="utf-8"))]
    assert found == []


def test_vocabulary_imports_no_rdf_library():
    text = Path(V.__file__).read_text(encoding="utf-8")
    assert not re.search(r"^\s*(import|from)\s+(rdflib|pyoxigraph)", text, re.M)
