"""The SPARQL terms and templates (infrastructure/sparql/terms.py): the escape function, the IRIs and render().

The injection strings of plan 5.2 go into a store in memory and come back unchanged.
"""
from __future__ import annotations

import re

import pytest

from infrastructure import config
from infrastructure.rdf.namespaces import ABOX_GRAPH, KG, TRIAD
from infrastructure.sparql import terms
from infrastructure.sparql.terms import Term, TermError

XSD = "http://www.w3.org/2001/XMLSchema#"
INJECTIONS = ['" } ; DROP ALL ; #', '"', "\\", '\\"', "\\u0022 } ; CLEAR ALL ; #", "a\\u0022b", "line 1\nline 2\r\n",
              "tab\there", "\b\f", "$name", "${name}", "?x } UNION { ?s ?p ?o", "'single'", "<urn:x>", "émile ü 中文",
              "#comment", ""]


def test_text_is_a_simple_literal_with_the_echar_escapes():
    assert terms.literal("Elena Marsh") == '"Elena Marsh"'
    assert terms.literal('a "b" \\ c') == '"a \\"b\\" \\\\ c"'
    assert terms.literal("x\ny\rz\tw") == '"x\\ny\\rz\\tw"'
    assert "^^" not in terms.literal("text")                  # never ^^xsd:string (rule 4)
    assert "\\u" not in terms.literal("\\u0022")[1:-1].replace("\\\\u", "")   # no \u escape is written


def test_the_typed_literals():
    assert terms.literal(42) == f'"42"^^<{XSD}integer>'
    assert terms.literal(True) == f'"true"^^<{XSD}boolean>' and terms.literal(False) == f'"false"^^<{XSD}boolean>'
    assert terms.literal(1, "boolean") == f'"true"^^<{XSD}boolean>'          # SQLite keeps a boolean as 0 or 1
    assert terms.date("1971-05-14") == f'"1971-05-14"^^<{XSD}date>'
    assert terms.date_time("2026-10-30T09:00:00-04:00") == f'"2026-10-30T09:00:00-04:00"^^<{XSD}dateTime>'
    assert terms.date_time("2026-10-02T11:45:10.165-04:00").startswith('"2026-10-02T11:45:10.165-04:00"')
    assert terms.value_of("assertedAt", "2026-10-30T09:00:00+00:00").endswith(f"^^<{XSD}dateTime>")
    assert terms.value_of("dateOfBirth", "1971-05-14").endswith(f"^^<{XSD}date>")
    assert terms.value_of("seq", 2) == f'"2"^^<{XSD}integer>'
    assert terms.value_of("name", "x") == '"x"'


@pytest.mark.parametrize("call", [
    lambda: terms.literal(None), lambda: terms.literal(1.5), lambda: terms.literal(b"x"),
    lambda: terms.date("1971-5-14"), lambda: terms.date("born 1971"), lambda: terms.date_time("2026-10-30 09:00"),
    lambda: terms.date_time('2026-10-30T09:00:00" } ; DROP ALL ; #'), lambda: terms.literal("x", "float"),
    lambda: terms.literal(True, "integer"), lambda: terms.value_of("about", "clinical-entry/1"),
    lambda: terms.literal(Term("<urn:x>")),
])
def test_wrong_values_raise_a_term_error(call):
    with pytest.raises(TermError):
        call()


def test_the_iri_of_an_individual_takes_only_a_class_path_and_an_integer():
    assert terms.iri("patient", 42) == f"<{KG}patient/42>"
    assert terms.iri("audit-event", 0) == f"<{KG}audit-event/0>"
    for kind, id_ in (("patient", "42"), ("patient", "1> } ; DROP ALL ; #"), ("patient", True), ("patient", -1),
                      ("patient", 1.0), ("Patient", 1), ("counter", 1), ("patient/1", 1), ("../x", 1)):
        with pytest.raises(TermError):
            terms.iri(kind, id_)
    assert len(terms.KINDS) == 17


def test_the_id_and_the_kind_of_an_iri():
    assert terms.id_of(f"{KG}assertion/10") == 10
    assert terms.id_of(f"<{KG}assertion/10>", "assertion") == 10
    assert terms.id_of(None) is None
    assert terms.kind_of(f"{KG}care-team-member/3") == "care-team-member"
    for bad in (f"{KG}assertion/x", f"{KG}nothing/1", "urn:x", f"{KG}assertion/1/2"):
        with pytest.raises(TermError):
            terms.id_of(bad)
    with pytest.raises(TermError):
        terms.id_of(f"{KG}assertion/10", "patient")


def test_the_ontology_terms():
    assert terms.term("name") == f"<{TRIAD}name>"
    assert terms.class_term("Doctor") == f"<{TRIAD}Doctor>"
    assert terms.name_of(f"{TRIAD}Doctor") == "Doctor" and terms.name_of(f"<{TRIAD}Allergy>") == "Allergy"
    for bad in ("na me", "name>", "", "1x", "a:b"):
        with pytest.raises(TermError):
            terms.term(bad)
    with pytest.raises(TermError):
        terms.class_term("Admin")
    with pytest.raises(TermError):
        terms.property_term("phone")                            # not a stored property (phoneNumber is)


def test_render_puts_the_terms_into_the_template_in_one_pass():
    text = terms.render("SELECT ?x FROM $abox WHERE { ?x triad:name $name ; triad:seq $seq . $s ?p ?o }",
                        {"name": "$seq", "seq": 2, "s": terms.iri("patient", 1)}, prologue=False)
    assert text == (f'SELECT ?x FROM <{ABOX_GRAPH}> WHERE {{ ?x triad:name "$seq" ; '
                    f'triad:seq "2"^^<{XSD}integer> . <{KG}patient/1> ?p ?o }}')
    assert terms.render("ASK FROM $abox { }").startswith(terms.PROLOGUE)
    with pytest.raises(KeyError):
        terms.render("SELECT * WHERE { ?s ?p $missing }")
    assert terms.render("FILTER (?x IN ($list))", {"list": ["a", "b"]}, prologue=False) == 'FILTER (?x IN ("a", "b"))'
    with pytest.raises(TermError):
        terms.render("FILTER (?x IN ($list))", {"list": []})
    assert terms.placeholders("$a $b $a ?c") == ["a", "b"]


def test_the_datatypes_equal_the_rr_datatype_of_the_mapping():
    """The write side gives each property the datatype of the R2RML mapping (the export of the data)."""
    text = (config.SEMANTIC_DIR / "mapping" / "triad.r2rml.ttl").read_text(encoding="utf-8")
    found = {}
    for prop, datatype in re.findall(r"rr:predicate triad:(\w+)\s*;\s*rr:objectMap \[[^\]]*rr:datatype xsd:(\w+)",
                                     text, re.S):
        found[prop] = datatype
    assert found == terms.DATATYPES


@pytest.mark.parametrize("text", INJECTIONS)
def test_the_injection_strings_go_into_a_store_and_come_back_unchanged(text):
    pytest.importorskip("pyoxigraph")
    from infrastructure.sparql.client import EmbeddedSparqlClient
    client = EmbeddedSparqlClient(None)
    subject = terms.iri("patient", 1)
    client.update("INSERT DATA { GRAPH $abox { $s triad:name $text . $s triad:city \"x\" } }",
                  {"s": subject, "text": text})
    rows = client.select("SELECT ?name FROM $abox WHERE { $s triad:name ?name }", {"s": subject})
    assert [r["name"] for r in rows] == [text]
    found = client.select("SELECT ?s FROM $abox WHERE { ?s triad:name $text }", {"text": text})
    assert [r["s"] for r in found] == [subject[1:-1]]
    search = client.select("SELECT ?s FROM $abox WHERE { ?s triad:name ?n . FILTER (CONTAINS(LCASE(?n), $q)) }",
                           {"q": text.lower()})
    assert len(search) == 1
    assert client.select("SELECT (COUNT(*) AS ?n) FROM $abox WHERE { ?s ?p ?o }")[0]["n"] == 2   # nothing else changed


def test_a_values_block_of_one_iri_gets_a_second_iri_that_matches_nothing():
    """terms.iri_values: Virtuoso compiles a query with one value in VALUES much more slowly (300 ms, not 50 ms)."""
    one = terms.iri_values([f"{KG}assertion/7"])
    assert one == f"<{KG}assertion/7> <{KG}assertion/0>"
    assert terms.iri_values([f"<{KG}visit/2>", f"{KG}visit/3"]) == f"<{KG}visit/2> <{KG}visit/3>"
    with pytest.raises(TermError):
        terms.iri_values(["https://example.org/x/1"])        # only the IRIs of TRIAD individuals
    with pytest.raises(TermError):
        terms.iri_values([])
