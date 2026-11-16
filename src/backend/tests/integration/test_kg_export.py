"""The knowledge-graph export (plan 5, sections 3.1 to 3.3): the R2RML mapping, the files, the counts and the store.

The fast tests use the scenario database (01 + 02) and the planted database. The tests of the full database have
the marker "slow". The tests need the KG packages (requirements-kg.txt); without them they are skipped.

The test of each value builds the expected triples from SQL and vocabulary.py, not from the mapping file. So it is
a second, independent form of the mapping rules.
"""
from __future__ import annotations

import gzip
import io
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ox = pytest.importorskip("pyoxigraph")
pytest.importorskip("morph_kgc")
pytest.importorskip("rdflib")

from infrastructure import config  # noqa: E402
from infrastructure.rdf import counts, kg_export, oxigraph_store  # noqa: E402
from infrastructure.rdf.namespaces import ABOX_GRAPH, KG, TBOX_GRAPH, TRIAD  # noqa: E402
from models.semantic import vocabulary as V  # noqa: E402
from models.semantic.mapping import build_mapping as bm  # noqa: E402

XSD = "http://www.w3.org/2001/XMLSchema#"
XSD_STRING = XSD + "string"

# The scenario data (01_create_tables.sql + 02_insert_seed.sql): the counts of the committed seed graph.
SCENARIO = {"rows": 195, "total": 1_125, "type": 154, "attribute": 866, "fk": 105, "individuals": 121}
# The full database of a new onboarding (the fixture full_db, and "main.py ensure-db" on a new clone).
# The dev database of the plan has 31 more rows that the app wrote (2 chat sessions, 6 chat turns, 2 citations,
# 21 audit events), thus 325 more triples: 1,298,807 = 188,302 + 911,978 + 198,527, and 130,990 individuals.
FULL = {"rows": 188_312, "total": 1_298_482, "type": 188_271, "attribute": 911_697, "fk": 198_514,
        "individuals": 130_959}


# ---------------------------------------------------------------------------------------------
# Helpers

def read_lines(out_dir: Path) -> list[str]:
    with gzip.open(out_dir / kg_export.NT_FILE, "rt", encoding="utf-8") as f:
        return f.read().splitlines()


def parse(data: bytes, mime: str = "application/n-triples") -> list:
    return list(ox.parse(io.BytesIO(data), mime))


def nt_triples(out_dir: Path) -> list:
    """The triples of triad_kg.nt.gz (pyoxigraph terms)."""
    return parse(gzip.decompress((out_dir / kg_export.NT_FILE).read_bytes()))


def as_tuple(triple) -> tuple:
    o = triple.object
    if isinstance(o, ox.Literal):
        return triple.subject.value, triple.predicate.value, ("literal", o.value, o.datatype.value, o.language)
    return triple.subject.value, triple.predicate.value, o.value


def expected_triples(db_path: Path) -> set[tuple]:
    """All triples that the rows of a database must give, from SQL and vocabulary.py (not from the mapping)."""
    ddl = bm.ddl_connection()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    out: set[tuple] = set()
    try:
        for table, (path, id_column) in V.SUBJECT.items():
            subject = f"{KG}{path}/" + "{}"
            if table in V.TABLE_CLASS:
                for (row_id,) in conn.execute(f'SELECT "{id_column}" FROM "{table}"'):
                    out.add((subject.format(row_id), counts.RDF_TYPE, TRIAD + V.TABLE_CLASS[table]))
        for (table, column), (term, kind) in V.COLUMNS.items():
            path, id_column = V.SUBJECT[table]
            rows = conn.execute(f'SELECT "{id_column}", "{column}", Id FROM "{table}" WHERE "{column}" IS NOT NULL')
            if kind == V.ATTRIBUTE:
                datatype = XSD + bm.DATATYPES[term][4:] if term in bm.DATATYPES else XSD_STRING
                out |= {(f"{KG}{path}/{sid}", TRIAD + term, ("literal", str(value), datatype, None))
                        for sid, value, _ in rows}
                continue
            target = bm.fk_target(ddl, table, column)
            if (table, column) in V.FK_JOINS:
                join_table, join_column, subject_column = V.FK_JOINS[(table, column)]
                rows = conn.execute(f'SELECT j."{subject_column}", c.Id FROM "{table}" c '
                                    f'JOIN "{join_table}" j ON j."{join_column}" = c."{column}"')
                out |= {(f"{KG}{V.SUBJECT[join_table][0]}/{entry}", TRIAD + term, f"{KG}{path}/{row_id}")
                        for entry, row_id in rows}
            elif kind == V.FK:
                out |= {(f"{KG}{path}/{sid}", TRIAD + term, f"{KG}{V.SUBJECT[target][0]}/{value}")
                        for sid, value, _ in rows}
            else:
                out |= {(f"{KG}{V.SUBJECT[target][0]}/{value}", TRIAD + term, f"{KG}{path}/{row_id}")
                        for _, value, row_id in rows}
    finally:
        conn.close()
        ddl.close()
    return out


def sql_counts(db_path: Path) -> dict:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return counts.expected_counts(conn)
    finally:
        conn.close()


def check_totals(report: dict, want: dict) -> None:
    assert report["rows"] == want["rows"]
    assert report["total"] == want["total"]
    assert report["per_kind"] == {k: want[k] for k in counts.KINDS}
    assert report["individuals"] == want["individuals"]
    assert sum(report["per_kind"].values()) == report["total"] == sum(report["per_predicate"].values())


def bad_terms(lines: list[str]) -> list[str]:
    """The lines with a literal "None" (the NULL bug) or an IRI that ends in ".0" (a NULL in an integer column)."""
    return [line for line in lines if '"None"' in line or re.search(r"\.0>", line)]


@pytest.fixture(scope="module")
def scenario_export(scenario_db, tmp_path_factory):
    out = tmp_path_factory.mktemp("kg-scenario")
    report = kg_export.export_kg(scenario_db, out, "all")
    return out, report


@pytest.fixture(scope="module")
def planted_export(scenario_db, tmp_path_factory):
    """The export of the planted database (times with Z, +05:30 and milliseconds; a message with no issuer)."""
    from tests.fixtures.plant import plant
    folder = tmp_path_factory.mktemp("kg-planted")
    db = folder / "planted.db"
    shutil.copy(scenario_db, db)
    plant(db)
    report = kg_export.export_kg(db, folder / "out", "all")
    return db, folder / "out", report


# ---------------------------------------------------------------------------------------------
# The mapping file

def test_the_mapping_file_is_current():
    text, count = bm.mapping_text()
    assert bm.MAPPING_PATH.read_text(encoding="utf-8") == text, \
        "Run: .venv/bin/python src/backend/models/semantic/mapping/build_mapping.py"
    assert count == 35


def test_the_mapping_reads_tables_and_columns_only():
    from rdflib import Graph, Namespace
    from rdflib.namespace import RDF
    rr = Namespace("http://www.w3.org/ns/r2rml#")
    g = Graph().parse(bm.MAPPING_PATH, format="turtle")
    maps = set(g.subjects(RDF.type, rr.TriplesMap))
    assert len(maps) == 35
    assert not list(g.triples((None, rr.sqlQuery, None)))   # the NULL bug of Morph-KGC (plan 3.1)
    tables = {str(g.value(g.value(m, rr.logicalTable), rr.tableName)) for m in maps}
    assert tables == set(V.SUBJECT)
    # Six TriplesMaps for the foreign keys in the reverse direction, and one join (CareTeamMember -> CareTeam).
    reverse = {k for k, (_, kind) in V.COLUMNS.items() if kind == V.FK_REVERSE}
    assert len(maps) == len(V.SUBJECT) + len(reverse) == 29 + 6
    joins = list(g.triples((None, rr.joinCondition, None)))
    assert len(joins) == 1
    condition = joins[0][2]
    assert (str(g.value(condition, rr.child)), str(g.value(condition, rr.parent))) == ("Id", "CareTeamId")


def test_the_mapping_uses_the_terms_of_the_ontology():
    from rdflib import Graph, Namespace
    from rdflib.namespace import OWL, RDF
    rr = Namespace("http://www.w3.org/ns/r2rml#")
    mapping = Graph().parse(bm.MAPPING_PATH, format="turtle")
    ontology = Graph().parse(config.SEMANTIC_DIR / "triad.ttl", format="turtle")
    predicates = {str(p) for p in mapping.objects(None, rr.predicate)}
    classes = {str(c) for c in mapping.objects(None, rr["class"])}
    declared = {str(s) for t in (OWL.DatatypeProperty, OWL.ObjectProperty) for s in ontology.subjects(RDF.type, t)}
    assert predicates <= declared
    assert classes <= {str(s) for s in ontology.subjects(RDF.type, OWL.Class)}
    assert predicates == {TRIAD + t for t in V.attribute_properties() | V.stored_object_properties()}
    assert classes == {TRIAD + c for c in V.TABLE_CLASS.values()}
    datatypes = {str(d) for d in mapping.objects(None, rr.datatype)}
    assert datatypes == {XSD + d for d in ("date", "dateTime", "integer", "boolean")}   # never xsd:string


def test_the_datatypes_of_the_mapping_follow_the_ranges_of_the_ontology():
    from models.semantic import build_ontology as bo
    g = bo.load_graph()
    for term in sorted(V.attribute_properties()):
        assert bm.DATATYPES.get(term) == bo._range_datatype(g, bo.TRIAD[term]), term


# ---------------------------------------------------------------------------------------------
# The export of the scenario database

def test_the_counts_equal_the_sql_counts(scenario_export, scenario_db):
    _, report = scenario_export
    expected = sql_counts(scenario_db)
    assert counts.compare_with_sql(report, expected) == []
    assert report["per_predicate"] == expected["per_predicate"]
    assert report["per_class"] == expected["per_class"]
    assert report["per_kind"] == expected["per_kind"]
    check_totals(report, SCENARIO)


def test_each_triple_comes_from_a_cell_of_the_database(scenario_export, scenario_db):
    out, _ = scenario_export
    assert {as_tuple(t) for t in nt_triples(out)} == expected_triples(scenario_db)


def test_no_literal_is_none_and_no_iri_ends_in_dot_zero(scenario_export, planted_export):
    assert bad_terms(read_lines(scenario_export[0])) == []
    assert bad_terms(read_lines(planted_export[1])) == []


def test_the_care_team_members_hang_on_the_right_entry(scenario_export, scenario_db):
    out, _ = scenario_export
    conn = sqlite3.connect(scenario_db)
    pairs = conn.execute("SELECT t.ClinicalEntryId, m.Id, t.Id FROM CareTeamMember m "
                         "JOIN CareTeam t ON t.Id = m.CareTeamId").fetchall()
    conn.close()
    assert pairs and all(entry != team for entry, _, team in pairs)   # else the test could not see the trap
    member = f"<{TRIAD}member>"
    found = {line for line in read_lines(out) if f" {member} " in line}
    assert found == {f"<{KG}clinical-entry/{entry}> {member} <{KG}care-team-member/{m}> ." for entry, m, _ in pairs}


def test_the_datatypes_of_the_literals(scenario_export):
    out, _ = scenario_export
    by_term: dict[str, set] = {}
    for t in nt_triples(out):
        if isinstance(t.object, ox.Literal):
            term = t.predicate.value[len(TRIAD):]
            by_term.setdefault(term, set()).add((t.object.datatype.value, t.object.language))
    for term in ("dateOfBirth", "subjectDateOfBirth", "roleStartDate"):
        assert by_term[term] == {(XSD + "date", None)}, term
    for term in ("seq", "rank"):
        assert by_term[term] == {(XSD + "integer", None)}, term
    assert by_term["active"] == {(XSD + "boolean", None)}
    for term in ("assertedAt", "sentAt", "recordedAt", "startDate", "at", "createdAt", "startedAt"):
        assert by_term[term] == {(XSD + "dateTime", None)}, term
    for term in set(by_term) - set(bm.DATATYPES):   # text: simple literals (xsd:string, no language)
        assert by_term[term] == {(XSD_STRING, None)}, term
    text = gzip.decompress((out / kg_export.NT_FILE).read_bytes()).decode("utf-8")
    assert f"^^<{XSD_STRING}>" not in text   # SPARQL rule 4: "^^xsd:string" does not match a simple literal
    assert '"1"^^<http://www.w3.org/2001/XMLSchema#boolean>' in text   # the SQLite form of Active stays


def test_the_times_keep_the_exact_text_of_the_database(planted_export):
    db, out, _ = planted_export
    assert {as_tuple(t) for t in nt_triples(out)} == expected_triples(db)   # each literal: the text of its cell
    text = gzip.decompress((out / kg_export.NT_FILE).read_bytes()).decode("utf-8")
    for time in ("2026-10-02T20:15:00Z", "2026-10-02T11:45:10.165-04:00", "2026-10-03T01:10:00+05:30",
                 "2026-10-02T09:20:00.100-07:00"):
        assert f'"{time}"^^<{XSD}dateTime>' in text, time


def test_a_message_with_no_issuer_gives_no_issues_triple(planted_export):
    db, out, report = planted_export
    conn = sqlite3.connect(db)
    issued = conn.execute("SELECT count(StaffId), count(*) FROM Message").fetchone()
    conn.close()
    assert issued[0] < issued[1]   # the planted patient message has StaffId NULL
    assert report["per_predicate"][TRIAD + "issues"] == issued[0]


def test_the_export_is_byte_identical_on_a_rerun(scenario_export, scenario_db, tmp_path):
    out, _ = scenario_export
    again = kg_export.export_kg(scenario_db, tmp_path, "all")
    for name in (kg_export.NT_FILE, kg_export.RDF_FILE):
        assert (tmp_path / name).read_bytes() == (out / name).read_bytes(), name
    assert again["per_predicate"] == scenario_export[1]["per_predicate"]


def test_the_rdf_xml_file_holds_the_same_triples(scenario_export):
    out, _ = scenario_export
    nt = {as_tuple(t) for t in nt_triples(out)}
    rdf = gzip.decompress((out / kg_export.RDF_FILE).read_bytes())
    assert {as_tuple(t) for t in parse(rdf, "application/rdf+xml")} == nt
    assert rdf.count(b"\n") > len(nt) // 2   # one element on each line, not one long line


def test_the_committed_seed_graph_equals_a_fresh_export(scenario_export, scenario_db, tmp_path):
    seed = kg_export.SEED_PATH.read_bytes()
    report = kg_export.write_seed(None, tmp_path / "from_sql.rdf")   # the default: the SQL scripts 01 and 02
    assert (tmp_path / "from_sql.rdf").read_bytes() == seed, "Run: python -m infrastructure.rdf.kg_export --seed"
    check_totals(report, SCENARIO)
    kg_export.write_seed(scenario_db, tmp_path / "from_db.rdf")
    assert (tmp_path / "from_db.rdf").read_bytes() == seed
    # The scenario database is all in the scope, so its RDF/XML export is the seed graph too.
    assert gzip.decompress((scenario_export[0] / kg_export.RDF_FILE).read_bytes()) == seed


def test_the_scenario_scope_deletes_the_rows_out_of_the_scope(scenario_db, tmp_path):
    db = tmp_path / "more.db"
    shutil.copy(scenario_db, db)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("INSERT INTO Patient (Name, DateOfBirth, Sex) VALUES ('Test Person', '1980-01-01', 'female')")
    conn.execute("INSERT INTO PatientIdentifier (PatientId, System, Value) "
                 "VALUES (last_insert_rowid(), 'urn:test', 'P-1')")
    conn.commit()
    conn.close()
    report = kg_export.export_kg(db, tmp_path / "out", "scenarios")
    check_totals(report, SCENARIO)
    assert report["scope"] == "scenarios"
    assert gzip.decompress((tmp_path / "out" / kg_export.RDF_FILE).read_bytes()) == kg_export.SEED_PATH.read_bytes()
    assert sql_counts(db)["rows"] == SCENARIO["rows"] + 2   # the export changed only its copy


def test_the_export_stops_when_a_count_differs(scenario_db, tmp_path):
    broken = tmp_path / "broken.r2rml.ttl"
    text = bm.MAPPING_PATH.read_text(encoding="utf-8")
    line = '    rr:predicateObjectMap [ rr:predicate triad:phoneNumber ; rr:objectMap [ rr:column "PhoneNumber" ] ] ;\n'
    assert line in text
    broken.write_text(text.replace(line, "", 1), encoding="utf-8")   # the Department phone numbers are lost
    with pytest.raises(kg_export.ExportError, match="phoneNumber: SQL"):
        kg_export.export_kg(scenario_db, tmp_path / "out", "all", mapping=broken)
    assert not (tmp_path / "out").exists()   # no file changes


def test_the_report_has_the_shape_of_the_load_check(scenario_export):
    out, report = scenario_export
    saved = json.loads((out / kg_export.REPORT_FILE).read_text(encoding="utf-8"))
    assert saved == report
    assert counts.read_report(out / kg_export.REPORT_FILE) == (report["total"], report["per_predicate"])
    for key in ("scope", "total", "per_kind", "individuals", "per_predicate", "per_class", "seconds", "files"):
        assert key in saved, key
    assert all(iri.startswith("http") for iri in list(saved["per_predicate"]) + list(saved["per_class"]))
    assert set(saved["files"]) == {kg_export.NT_FILE, kg_export.RDF_FILE}


def test_the_report_takes_more_keys(scenario_db, tmp_path):
    report = kg_export.export_kg(scenario_db, tmp_path, "all", extra={"marker": {"mapping_sha256": "abc"}})
    assert json.loads((tmp_path / kg_export.REPORT_FILE).read_text())["marker"] == {"mapping_sha256": "abc"}
    assert report["marker"]["mapping_sha256"] == "abc"


def test_the_export_kg_command(scenario_db, tmp_path, capsys):
    import main
    main.main(["export-kg", "--db", str(scenario_db), "--out", str(tmp_path), "--scope", "scenarios"])
    printed = capsys.readouterr().out
    assert "1,125 triples (154 rdf:type, 866 attribute, 105 foreign key), 121 individuals" in printed
    assert "equal the SQL counts" in printed
    assert json.loads((tmp_path / kg_export.REPORT_FILE).read_text())["scope"] == "scenarios"
    with pytest.raises(SystemExit):
        main.main(["--help"])
    assert "export-kg" in capsys.readouterr().out   # kg.sh load looks for this word


def test_the_sqlite_path_loads_no_kg_package():
    code = ("import sys; import main; import infrastructure.rdf.kg_export, infrastructure.rdf.oxigraph_store, "
            "infrastructure.rdf.counts; "
            "bad = [m for m in ('morph_kgc', 'pyoxigraph', 'rdflib', 'pandas') if m in sys.modules]; "
            "assert not bad, bad")
    subprocess.run([sys.executable, "-c", code], cwd=config.BACKEND_DIR, check=True)


# ---------------------------------------------------------------------------------------------
# The Oxigraph store

def test_loading_into_oxigraph_gives_the_same_counts(scenario_export, tmp_path):
    out, report = scenario_export
    store = oxigraph_store.open_store(tmp_path / "store")
    try:
        loaded = oxigraph_store.load_graphs(store, oxigraph_store.OWL_PATH, out / kg_export.NT_FILE)
        tbox = len(parse(oxigraph_store.OWL_PATH.read_bytes(), "application/rdf+xml"))
        assert loaded == {"tbox": tbox, "abox": report["total"]}
        found = oxigraph_store.graph_counts(store, ABOX_GRAPH)
        assert found["per_predicate"] == report["per_predicate"]
        assert found["per_class"] == report["per_class"]
        # The seed graph (RDF/XML) and the compressed RDF/XML give the same graph. Each load clears the graph first.
        for abox in (kg_export.SEED_PATH, out / kg_export.RDF_FILE):
            assert oxigraph_store.load_graphs(store, abox_file=abox) == loaded
            assert oxigraph_store.graph_counts(store, ABOX_GRAPH) == found
        assert oxigraph_store.triple_count(store, TBOX_GRAPH) == tbox
    finally:
        oxigraph_store.close_store(tmp_path / "store")


def test_the_store_cache_gives_one_object_per_folder(tmp_path):
    first = oxigraph_store.open_store(tmp_path / "a")
    assert oxigraph_store.open_store(str(tmp_path / "a")) is first
    assert oxigraph_store.open_store(None) is not oxigraph_store.open_store(None)   # in memory: not cached
    first.add(ox.Quad(ox.NamedNode("urn:s"), ox.NamedNode("urn:p"), ox.Literal("o"), ox.NamedNode(ABOX_GRAPH)))
    copy = oxigraph_store.backup_store(first, tmp_path / "b")
    with pytest.raises(FileExistsError):
        oxigraph_store.backup_store(first, copy)
    assert oxigraph_store.triple_count(oxigraph_store.open_store(copy)) == 1
    del first
    assert oxigraph_store.close_store(tmp_path / "a") is True
    assert oxigraph_store.close_store(tmp_path / "a") is False
    assert oxigraph_store.triple_count(oxigraph_store.open_store(tmp_path / "a")) == 1   # the folder opens again
    for path in (tmp_path / "a", tmp_path / "b"):
        oxigraph_store.close_store(path)
    assert all(tmp_path not in p.parents for p in oxigraph_store.cached_paths())


def test_the_file_types_of_the_store():
    assert oxigraph_store.mime_type("triad_kg.nt.gz") == ("application/n-triples", True)
    assert oxigraph_store.mime_type("triad_kg.rdf.gz") == ("application/rdf+xml", True)
    assert oxigraph_store.mime_type("triad.owl") == ("application/rdf+xml", False)
    with pytest.raises(ValueError):
        oxigraph_store.mime_type("kg_report.json")


# ---------------------------------------------------------------------------------------------
# The full database (slow)

@pytest.fixture(scope="module")
def full_export(full_db, tmp_path_factory):
    out = tmp_path_factory.mktemp("kg-full")
    return out, kg_export.export_kg(full_db, out, "all")


@pytest.mark.slow
def test_the_full_export_has_the_counts_of_the_sql_rows(full_export, full_db):
    _, report = full_export
    expected = sql_counts(full_db)
    assert report["per_predicate"] == expected["per_predicate"]   # per predicate: the NULL bug shows here
    assert report["per_class"] == expected["per_class"]
    check_totals(report, FULL)
    # 188,312 rows - 57,312 subtype rows - 41 StaffLanguage rows = 130,959 individuals (plan 3.3).
    subtype_rows = sum(report["per_class"][TRIAD + V.TABLE_CLASS[t]] for t in V.SUBTYPE_TABLES)
    assert subtype_rows == 57_312
    assert report["rows"] - subtype_rows - 41 == report["individuals"]


@pytest.mark.slow
def test_the_full_export_has_no_null_terms_and_the_right_care_teams(full_export, full_db):
    out, report = full_export
    lines = read_lines(out)
    assert len(lines) == report["total"]
    assert bad_terms(lines) == []
    conn = sqlite3.connect(full_db)
    pairs = conn.execute("SELECT t.ClinicalEntryId, m.Id FROM CareTeamMember m "
                         "JOIN CareTeam t ON t.Id = m.CareTeamId").fetchall()
    differ = conn.execute("SELECT count(*) FROM CareTeam WHERE Id <> ClinicalEntryId").fetchone()[0]
    conn.close()
    assert differ == 369 and len(pairs) == 411
    member = f"<{TRIAD}member>"
    assert {line for line in lines if f" {member} " in line} == {
        f"<{KG}clinical-entry/{entry}> {member} <{KG}care-team-member/{m}> ." for entry, m in pairs}


@pytest.mark.slow
def test_the_scenario_scope_of_the_full_database_is_the_seed_graph(full_db, tmp_path):
    report = kg_export.write_seed(full_db, tmp_path / "seed.rdf")
    check_totals(report, SCENARIO)
    assert (tmp_path / "seed.rdf").read_bytes() == kg_export.SEED_PATH.read_bytes()


@pytest.mark.slow
def test_the_full_graph_in_oxigraph_has_the_counts_of_the_report(full_export, tmp_path):
    out, report = full_export
    store = oxigraph_store.open_store(tmp_path / "store")
    try:
        assert oxigraph_store.load_graphs(store, abox_file=out / kg_export.NT_FILE)["abox"] == FULL["total"]
        found = oxigraph_store.graph_counts(store, ABOX_GRAPH)
        assert counts.differences(report["per_predicate"], found["per_predicate"]) == []
        assert found["per_class"] == report["per_class"]
    finally:
        oxigraph_store.close_store(tmp_path / "store")
