#!/usr/bin/env python3
"""Write the W3C R2RML mapping triad.r2rml.ttl from the column map of vocabulary.py (plan 5, section 3.1).

Run it from the root folder of the repository:
    .venv/bin/python src/backend/models/semantic/mapping/build_mapping.py           # write triad.r2rml.ttl
    .venv/bin/python src/backend/models/semantic/mapping/build_mapping.py --check   # stop if the file is old

The mapping is the artifact: Morph-KGC reads triad.r2rml.ttl (infrastructure/rdf/kg_export.py). This script
only makes sure that the mapping follows vocabulary.py and the DDL. It uses the Python standard library only.
The inputs:
    vocabulary.py             the subject IRI of each table, the term of each column, the join of FK_JOINS;
    01_create_tables.sql      the tables and their columns in the DDL order, and the target of each foreign key;
    DATATYPES (below)         the rr:datatype of each term. A test compares it with the ranges of triad.ttl.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

try:
    from models.semantic import vocabulary as V
except ImportError:  # run as a script: put the folder of vocabulary.py on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import vocabulary as V

HERE = Path(__file__).resolve().parent
MAPPING_PATH = HERE / "triad.r2rml.ttl"
DDL_PATH = HERE.parents[1] / "relational" / "sql" / "ddl" / "01_create_tables.sql"
MAP = f"{V.REPO}/mapping/triad#"   # the IRIs of the TriplesMaps

# The rr:datatype of each datatype property that is not text. All other attributes are simple literals.
# OWL 2 has no xsd:date, so the TBox range of the four date terms is rdfs:Literal; the data keeps xsd:date.
DATATYPES = {
    **{term: "xsd:dateTime" for term in (
        "startDate", "endDate", "recordedAt", "onsetDate", "abatementDate", "performedDate", "issuedDate",
        "sentAt", "assertedAt", "startedAt", "createdAt", "at")},
    **{term: "xsd:date" for term in ("dateOfBirth", "subjectDateOfBirth", "roleStartDate", "roleEndDate")},
    "seq": "xsd:integer",       # Morph-KGC infers no SQLite types, so the mapping gives the datatype
    "rank": "xsd:integer",
    "active": "xsd:boolean",    # the values 1 and 0 of SQLite are valid xsd:boolean forms
}


def ddl_connection(ddl_path: Path = DDL_PATH) -> sqlite3.Connection:
    """An in-memory database made by the DDL script 01 (no data)."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(ddl_path.read_text(encoding="utf-8"))
    return conn


def ddl_tables(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid")]


def ddl_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def fk_target(conn: sqlite3.Connection, table: str, column: str) -> str:
    """The table that a one-column foreign key points to."""
    for row in conn.execute(f"PRAGMA foreign_key_list({table})"):
        if row[3] == column:
            return row[2]
    raise ValueError(f"{table}.{column} is not a foreign key in the DDL.")


def template(table: str, column: str | None = None) -> str:
    """The IRI template of the individual of a row: KG + "<class path>/{<column>}"."""
    path, id_column = V.SUBJECT[table]
    return f"{V.KG}{path}/{{{column or id_column}}}"


def _object_map(term: str, column: str) -> str:
    datatype = DATATYPES.get(term)
    return f'[ rr:column "{column}"' + (f" ; rr:datatype {datatype}" if datatype else "") + " ]"


WIDTH = 118   # a longer line breaks before rr:objectMap or rr:class


def _pom(term: str, object_map: str) -> str:
    line = f"    rr:predicateObjectMap [ rr:predicate triad:{term} ; rr:objectMap {object_map} ]"
    if len(line) <= WIDTH and "\n" not in object_map:
        return line
    return f"    rr:predicateObjectMap [ rr:predicate triad:{term} ;\n        rr:objectMap {object_map} ]"


def _subject_map(template_text: str, cls: str | None) -> str:
    if cls is None:
        return f'[ rr:template "{template_text}" ]'
    line = f'    rr:subjectMap [ rr:template "{template_text}" ; rr:class triad:{cls} ] ;'
    if len(line) <= WIDTH:
        return f'[ rr:template "{template_text}" ; rr:class triad:{cls} ]'
    return f'[ rr:template "{template_text}" ;\n                    rr:class triad:{cls} ]'


def _triples_map(name: str, table: str, subject: str, poms: list[str], comment: list[str]) -> str:
    lines = [f"# {line}" if line else "#" for line in comment]
    lines += [f"map:{name} a rr:TriplesMap ;",
              f'    rr:logicalTable [ rr:tableName "{table}" ] ;',
              f"    rr:subjectMap {subject}"]
    body = " ;\n".join(lines[-1:] + poms) if poms else lines[-1]
    return "\n".join(lines[:-1] + [body]) + " .\n"


def _table_map(conn: sqlite3.Connection, table: str) -> tuple[str, list[str]]:
    """The TriplesMap of one table, and the TriplesMaps of its foreign keys in the reverse direction."""
    path, id_column = V.SUBJECT[table]
    cls = V.TABLE_CLASS.get(table)
    subject = _subject_map(template(table), cls)
    poms, reverse = [], []
    for column in ddl_columns(conn, table):
        if (table, column) in V.NO_PROPERTY:
            continue
        term, kind = V.COLUMNS[(table, column)]
        if kind == V.ATTRIBUTE:
            poms.append(_pom(term, _object_map(term, column)))
            continue
        target = fk_target(conn, table, column)
        if kind == V.FK:
            poms.append(_pom(term, f'[ rr:template "{template(target, column)}" ]'))
        else:
            reverse.append(_reverse_map(conn, table, column, term, target))
    if cls is None:
        what = f"kg:{path}/{{{id_column}}} (no individual of its own: each row is one triple of that staff member)"
    elif table in V.SUBTYPE_TABLES:
        parent = V.SUBTYPE_TABLES[table][1]
        what = f"kg:{path}/{{{id_column}}} (the individual of its {parent} row), also a triad:{cls}"
    else:
        what = f"kg:{path}/{{{id_column}}}, a triad:{cls}"
    comment = ["-" * 110, f"{table}: {what}", "-" * 110]
    return _triples_map(table, table, subject, poms, comment), reverse


def _reverse_map(conn: sqlite3.Connection, table: str, column: str, term: str, target: str) -> str:
    """A TriplesMap for a foreign key in the reverse direction: <the target of the FK> triad:term <the row>."""
    name = f"{table}_{column}"
    row_path = V.SUBJECT[table][0]
    if (table, column) in V.FK_JOINS:
        join_table, join_column, subject_column = V.FK_JOINS[(table, column)]
        if join_table != target:
            raise ValueError(f"FK_JOINS gives {join_table} for {table}.{column}, but the DDL gives {target}.")
        subject = _subject_map(template(join_table, subject_column), None)
        object_map = (f"[ rr:parentTriplesMap map:{table} ;\n"
                      f'                       rr:joinCondition [ rr:child "{join_column}" ; rr:parent "{column}" ] ]')
        target_path = V.SUBJECT[join_table][0]
        comment = [f"{table}.{column}, the reverse direction, with a join of {join_table}:",
                   f"    kg:{target_path}/{{{join_table}.{subject_column}}} triad:{term} kg:{row_path}/{{Id}}",
                   f"{table}.{column} holds {join_table}.{join_column}, but the IRI of the {join_table} individual "
                   f"uses {join_table}.{subject_column}.",
                   f"So this TriplesMap reads {join_table} and joins the {table} rows. A plain template would put",
                   "each member on the wrong entry."]
        return _triples_map(name, join_table, subject, [_pom(term, object_map)], comment)
    target_path, target_id = V.SUBJECT[target]
    if target_id != "Id":
        raise ValueError(f"{table}.{column} points to {target}, whose IRI does not use its Id. Add it to FK_JOINS.")
    subject = f'[ rr:template "{template(target, column)}" ]'
    comment = [f"{table}.{column}, the reverse direction:",
               f"    kg:{target_path}/{{{column}}} triad:{term} kg:{row_path}/{{Id}}"]
    return _triples_map(name, table, subject, [_pom(term, f'[ rr:template "{template(table)}" ]')], comment)


def check_vocabulary(conn: sqlite3.Connection) -> None:
    """Each DDL column is in COLUMNS or NO_PROPERTY, and DATATYPES names only attribute terms."""
    for table in ddl_tables(conn):
        if table not in V.SUBJECT:
            raise ValueError(f"The table {table} has no subject IRI in vocabulary.SUBJECT.")
        for column in ddl_columns(conn, table):
            if (table, column) not in V.COLUMNS and (table, column) not in V.NO_PROPERTY:
                raise ValueError(f"{table}.{column} is not in vocabulary.COLUMNS or vocabulary.NO_PROPERTY.")
    unknown = set(DATATYPES) - V.attribute_properties()
    if unknown:
        raise ValueError(f"DATATYPES names terms that are not datatype properties: {sorted(unknown)}")


def mapping_text(ddl_path: Path = DDL_PATH) -> tuple[str, int]:
    """The text of triad.r2rml.ttl and its number of TriplesMaps."""
    conn = ddl_connection(ddl_path)
    try:
        check_vocabulary(conn)
        tables = ddl_tables(conn)
        maps = [_table_map(conn, table) for table in tables]
    finally:
        conn.close()
    count = sum(1 + len(reverse) for _, reverse in maps)
    reverse_count = count - len(tables)
    header = [
        "# TRIAD: the W3C R2RML mapping (https://www.w3.org/TR/r2rml/) from the SQLite database to RDF.",
        "# Milestone 5, plan section 3.1. Morph-KGC 2.10.0 runs it (infrastructure/rdf/kg_export.py,",
        "# main.py export-kg).",
        "#",
        "# Do not edit this file by hand. build_mapping.py writes it from vocabulary.py and 01_create_tables.sql:",
        "#     .venv/bin/python src/backend/models/semantic/mapping/build_mapping.py",
        "# The terms are the terms of ../triad.ttl. The subject IRIs are the ones of ../ontology.md section 1.",
        "#",
        f"# {count} TriplesMaps: {len(tables)} for the tables (in the order of the DDL), "
        f"{reverse_count} for the foreign keys in the reverse direction.",
        "#",
        "# The rules (each rule comes from a failed test):",
        "# - Each TriplesMap reads a table (rr:tableName) and its columns (rr:column). Morph-KGC adds \"IS NOT NULL\"",
        "#   for each column, so a NULL gives no triple. The mapping has no rr:sqlQuery: in a query, Morph-KGC turns a",
        "#   NULL into the literal \"None\", and a nullable integer foreign key into an IRI that ends in \".0\".",
        "# - The configuration of Morph-KGC sets na_values to a value that is not in the data. The default (\",nan\")",
        "#   drops the real values \"\" and \"nan\", which R2RML does not allow.",
        "# - A subtype row (Doctor, Nurse, MOA and the 8 entry subtypes) is the same individual as its parent row.",
        "#   Its TriplesMap uses the parent Id (StaffId, ClinicalEntryId) and adds the second rr:class.",
        "# - A foreign key in the stored direction (about, during, prescribes, ...) is an object map with the",
        "#   template of the target IRI. A foreign key in the reverse direction (hasVisit, contains, issues, includes,",
        "#   identifier, member) has a TriplesMap of its own: the subject is the target, and the object is the row.",
        "# - CareTeamMember.CareTeamId holds CareTeam.Id, not the entry Id, so its TriplesMap joins CareTeam",
        "#   (rr:parentTriplesMap and rr:joinCondition).",
        "# - Dates are xsd:date. Times are xsd:dateTime with the exact text of the database. Seq and Rank are",
        "#   xsd:integer, and Active is xsd:boolean (\"1\" and \"0\" are valid forms). Text values are simple",
        "#   literals (no rr:datatype xsd:string).",
        "",
        "@prefix rr: <http://www.w3.org/ns/r2rml#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        f"@prefix triad: <{V.TRIAD}> .",
        f"@prefix map: <{MAP}> .",
        "",
        "",
    ]
    parts = []
    for table_map, reverse in maps:
        parts.append(table_map)
        parts.extend(reverse)
    return "\n".join(header) + "\n".join(parts), count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="check only; stop if triad.r2rml.ttl is not current")
    parser.add_argument("--out", type=Path, default=MAPPING_PATH, help="the output file")
    args = parser.parse_args(argv)
    try:
        text, count = mapping_text()
    except ValueError as error:
        print(f"Check failed. {error}", file=sys.stderr)
        return 1
    if args.check:
        if not args.out.exists() or args.out.read_text(encoding="utf-8") != text:
            print(f"Check failed. {args.out.name} is not current. Run build_mapping.py without --check.",
                  file=sys.stderr)
            return 1
        print(f"Checked {args.out}: {count} TriplesMaps.")
        return 0
    args.out.write_text(text, encoding="utf-8")
    print(f"Wrote {args.out}: {count} TriplesMaps.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
