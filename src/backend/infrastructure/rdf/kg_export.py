"""The knowledge-graph export: the R2RML mapping on the SQLite database gives the RDF files (plan 5, section 3.2).

export_kg(db_path, out_dir, scope) writes three files into out_dir (main.py export-kg; kg.sh load runs it):
    triad_kg.nt.gz    N-Triples. The lines are sorted, and gzip writes no time, so the same data gives the same bytes.
    triad_kg.rdf.gz   RDF/XML (pyoxigraph 0.3) of the same sorted triples, with one element on each line.
                      Both files thus give the same literals in a store.
    kg_report.json    the counts (see counts.py for the shape), the scope and the time.
write_seed() writes the scenario graph models/semantic/kg/triad_kg_seed.rdf (RDF/XML, not compressed). Git keeps it.

The steps:
1. Copy the database into a temporary folder (the SQLite backup API), so the export reads one fixed state.
   Scope "scenarios": delete the rows that are not in the scope of the scenario SQL (sql_export.scope_ids).
   A query "WHERE Id IN (...)" in the mapping would hit the NULL bug of rr:sqlQuery (plan 3.1).
2. Run Morph-KGC 2.10.0 in this process on models/semantic/mapping/triad.r2rml.ttl. Morph-KGC returns a set of
   triples. Sort the N-Triples lines.
3. Count the triples per predicate and per class, and compare them with the SQL counts (counts.expected_counts).
   If one count differs, stop with an error and write no file.
4. Write the files. Each file goes to a temporary name first, so a reader never sees half a file.

This module imports the RDF packages (morph_kgc, pyoxigraph) only in the functions that use them, so the SQLite
path of the app does not need them.

Usage (from the root folder of the repository; main.py export-kg is the usual command):
    .venv/bin/python -m infrastructure.rdf.kg_export --seed [--db PATH] [--out FILE]    (PYTHONPATH=src/backend)
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import warnings
from collections import Counter
from pathlib import Path
from typing import Mapping, Optional

from infrastructure import config
from infrastructure.rdf import counts
from models.semantic import vocabulary as V

SCOPES = ("all", "scenarios")
MAPPING_PATH = config.SEMANTIC_DIR / "mapping" / "triad.r2rml.ttl"
SEED_PATH = config.SEMANTIC_DIR / "kg" / "triad_kg_seed.rdf"
NT_FILE = "triad_kg.nt.gz"
RDF_FILE = "triad_kg.rdf.gz"
REPORT_FILE = "kg_report.json"

# The Morph-KGC value for NULL. The default (",nan") drops the real values "" and "nan" (plan 3.1); this value is not
# in the data. The mapping reads only tables and columns, so Morph-KGC filters the real NULLs in SQL (IS NOT NULL).
NA_VALUE = "__TRIAD_NO_NA__"
GZIP_LEVEL = 6   # the level of the gzip command. The Python default (9) is slower.


class ExportError(Exception):
    """The export cannot run, or the triples do not agree with the rows of the database."""


def _morph_kgc():
    try:
        import morph_kgc
    except ImportError as error:
        raise ExportError("The export needs morph-kgc. Install the KG packages: "
                          "uv pip install --python .venv/bin/python -r requirements-kg.txt") from error
    return morph_kgc


def _pyoxigraph():
    try:
        import pyoxigraph
    except ImportError as error:
        raise ExportError("The export needs pyoxigraph. Install the KG packages: "
                          "uv pip install --python .venv/bin/python -r requirements-kg.txt") from error
    return pyoxigraph


# ---------------------------------------------------------------------------------------------
# The database copy and the scope

def copy_database(db_path: Path, target: Path) -> None:
    """Copy a SQLite database with the backup API (a consistent copy, also of a database in WAL mode)."""
    db_path = Path(db_path)
    if not db_path.is_file():
        raise ExportError(f"The database {db_path} does not exist. Run: python src/backend/main.py ensure-db")
    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    copy = sqlite3.connect(str(target))
    try:
        source.backup(copy)
        copy.execute("PRAGMA journal_mode = DELETE")
    finally:
        copy.close()
        source.close()


def keep_scenarios(db_path: Path) -> int:
    """Delete the rows that are not in the scope of the scenario data. Return the number of rows that stay.

    The scope is the one of dml/02_insert_seed.sql (sql_export.scope_ids): the TRIAD General directory, Patient A
    with all her records, and the chat and audit rows. Use this function only on a copy: it drops the triggers.
    """
    from infrastructure.sqlite.onboarding_store import TABLES
    from infrastructure.sqlite.sql_export import scope_ids

    conn = sqlite3.connect(str(db_path))
    try:
        ids = scope_ids(conn)
        conn.execute("PRAGMA foreign_keys = OFF")
        # The triggers of the append-only tables (Assertion, AuditEvent) refuse a DELETE.
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'").fetchall():
            conn.execute(f'DROP TRIGGER "{name}"')
        conn.execute("CREATE TEMP TABLE keep (Id INTEGER PRIMARY KEY)")
        for table in TABLES:
            conn.execute("DELETE FROM temp.keep")
            conn.executemany("INSERT INTO temp.keep (Id) VALUES (?)", [(i,) for i in ids.get(table, [])])
            conn.execute(f'DELETE FROM "{table}" WHERE Id NOT IN (SELECT Id FROM temp.keep)')
        conn.commit()
        dangling = conn.execute("PRAGMA foreign_key_check").fetchall()
        if dangling:
            raise ExportError(f"The scenario scope has {len(dangling)} foreign keys to rows out of the scope, "
                              f"for example {tuple(dangling[0])}.")
        return sum(conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] for table in TABLES)
    finally:
        conn.close()


# ---------------------------------------------------------------------------------------------
# Morph-KGC

def morph_config(db_path: Path, mapping: Path = MAPPING_PATH) -> str:
    """The Morph-KGC configuration (an INI text): one SQLite source, the TRIAD mapping, one process."""
    def value(path: Path) -> str:
        return str(Path(path).resolve()).replace("$", "$$")   # Morph-KGC reads the text with ${...} interpolation
    return "\n".join([
        "[CONFIGURATION]",
        f"na_values={NA_VALUE}",
        "output_format=N-TRIPLES",
        "number_of_processes=1",
        "logging_level=WARNING",
        "",
        "[TRIAD]",
        f"mappings={value(mapping)}",
        f"db_url=sqlite:///{value(db_path)}",
        "",
    ])


def materialize(db_path: Path, mapping: Path = MAPPING_PATH) -> list[str]:
    """The triples of the mapping on a database: sorted N-Triples lines, each with its final " ." and no newline."""
    morph_kgc = _morph_kgc()
    if not Path(mapping).is_file():
        raise ExportError(f"The mapping {mapping} does not exist.")
    with warnings.catch_warnings():
        # Morph-KGC reads the mapping with the SPARQL parser of rdflib 7.2, which uses old pyparsing names.
        warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"(rdflib|pyparsing)\b")
        triples = morph_kgc.materialize_set(morph_config(db_path, mapping))
    return sorted(f"{triple.strip()} ." for triple in triples)


# ---------------------------------------------------------------------------------------------
# The counts of the triples

def graph_counts(lines: list[str]) -> dict:
    """The counts of sorted N-Triples lines, with the keys of counts.expected_counts()."""
    per_predicate: Counter = Counter()
    per_class: Counter = Counter()
    typed = set()
    for line in lines:
        subject, predicate, rest = line.split(" ", 2)
        predicate = predicate[1:-1]
        per_predicate[predicate] += 1
        if predicate == counts.RDF_TYPE:
            per_class[rest[1:-3]] += 1          # rest is "<class> ."
            typed.add(subject)
    per_kind = dict.fromkeys(counts.KINDS, 0)
    for predicate, number in per_predicate.items():
        kind = counts.kind_of(predicate)
        if kind is None:
            raise ExportError(f"The mapping gives the predicate <{predicate}>, which is not a TRIAD term.")
        per_kind[kind] += number
    return {
        "total": len(lines),
        "per_kind": per_kind,
        "individuals": len(typed),
        "per_predicate": dict(sorted(per_predicate.items())),
        "per_class": dict(sorted(per_class.items())),
    }


def check_counts(found: Mapping, db_path: Path) -> dict:
    """Compare the counts of the triples with the SQL counts of the same database. Stop if one differs."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        expected = counts.expected_counts(conn)
    finally:
        conn.close()
    problems = counts.compare_with_sql(found, expected)
    if problems:
        raise ExportError("The triples do not agree with the rows of the database (plan 3.3):\n    "
                          + "\n    ".join(problems))
    return expected


# ---------------------------------------------------------------------------------------------
# The files

def _line_breaks(xml: str) -> str:
    """Put each element of the pyoxigraph RDF/XML on its own line. pyoxigraph 0.3 writes all of it on one line.

    A literal cannot hold "<" (the writer escapes it as &lt;), so a new line goes only between two elements.
    The text of a property element does not change: the step puts no break before a closing tag of a property.
    """
    head, _, body = xml.partition("?>")
    body = re.sub(r"<(?!/|rdf:Description|rdf:RDF)", "\n  <", body)
    body = body.replace("<rdf:Description", "\n<rdf:Description")
    body = body.replace("</rdf:Description>", "\n</rdf:Description>").replace("</rdf:RDF>", "\n</rdf:RDF>")
    return head + "?>" + body + "\n"


def nt_bytes(lines: list[str]) -> bytes:
    return ("\n".join(lines) + "\n").encode("utf-8") if lines else b""


def rdf_xml_bytes(nt: bytes) -> bytes:
    """The RDF/XML of N-Triples bytes, in the same order of the triples, with one element on each line."""
    ox = _pyoxigraph()
    out = io.BytesIO()
    ox.serialize(ox.parse(io.BytesIO(nt), "application/n-triples"), out, "application/rdf+xml")
    return _line_breaks(out.getvalue().decode("utf-8")).encode("utf-8")


def _write_atomic(path: Path, data: bytes, gzip_name: Optional[str] = None) -> int:
    """Write the bytes (gzip with no time and a fixed name if gzip_name is given) to a temporary file, then rename."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        with open(tmp, "wb") as raw:
            if gzip_name is None:
                raw.write(data)
            else:
                with gzip.GzipFile(filename=gzip_name, mode="wb", fileobj=raw, compresslevel=GZIP_LEVEL,
                                   mtime=0) as gz:
                    gz.write(data)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return path.stat().st_size


# ---------------------------------------------------------------------------------------------
# The two entry points

def _snapshot(db_path: Path, folder: Path, scope: str) -> tuple[Path, int]:
    """A copy of the database in `folder`, with the rows of the scope. Return its path and its number of rows."""
    if scope not in SCOPES:
        raise ExportError(f'The scope is "{scope}". Use one of: {", ".join(SCOPES)}.')
    copy = folder / "export.db"
    copy_database(db_path, copy)
    if scope == "scenarios":
        rows = keep_scenarios(copy)
    else:
        conn = sqlite3.connect(str(copy))
        try:
            rows = sum(conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in V.SUBJECT)
        finally:
            conn.close()
    return copy, rows


def export_kg(db_path: Path, out_dir: Path, scope: str = "all", *, mapping: Path = MAPPING_PATH,
              extra: Optional[Mapping] = None) -> dict:
    """Export the knowledge graph of a database into out_dir: triad_kg.nt.gz, triad_kg.rdf.gz, kg_report.json.

    scope "all" exports all rows; "scenarios" only the rows of the scenario data (plan 3.2).
    `extra` adds keys to kg_report.json (for example the hashes of the build marker, plan 3.5).
    Return the report (the content of kg_report.json). Raise ExportError if the export cannot run, or if the
    counts of the triples differ from the SQL counts (then no file changes).
    """
    started = time.perf_counter()
    steps: dict[str, float] = {}

    def step(name: str, since: float) -> float:
        now = time.perf_counter()
        steps[name] = round(now - since, 2)
        return now

    out_dir = Path(out_dir)
    with tempfile.TemporaryDirectory(prefix="triad-kg-") as folder:
        copy, rows = _snapshot(Path(db_path), Path(folder), scope)
        mark = step("copy", started)
        lines = materialize(copy, mapping)
        mark = step("materialize", mark)
        found = graph_counts(lines)
        expected = check_counts(found, copy)
        mark = step("check", mark)
    nt = nt_bytes(lines)
    del lines
    rdf = rdf_xml_bytes(nt)
    mark = step("rdf_xml", mark)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {NT_FILE: _write_atomic(out_dir / NT_FILE, nt, gzip_name=NT_FILE[:-3])}
    del nt
    files[RDF_FILE] = _write_atomic(out_dir / RDF_FILE, rdf, gzip_name=RDF_FILE[:-3])
    del rdf
    step("write", mark)
    report = {
        "scope": scope,
        "database": str(Path(db_path).resolve()),
        "mapping": MAPPING_PATH.name if Path(mapping) == MAPPING_PATH else str(mapping),
        "ontology_version": V.ONTOLOGY_VERSION,
        "rows": rows,
        "total": found["total"],
        "per_kind": found["per_kind"],
        "individuals": found["individuals"],
        "count_check": f"passed: the counts per predicate and per class equal the SQL counts of "
                       f"{expected['rows']} rows",
        "files": files,
        "seconds": round(time.perf_counter() - started, 2),
        "steps": steps,
        **dict(extra or {}),
        "per_predicate": found["per_predicate"],
        "per_class": found["per_class"],
    }
    _write_atomic(out_dir / REPORT_FILE, (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return report


def scenario_database(target: Path) -> Path:
    """Make the scenario database from the SQL scripts 01 and 02 (no onboarding) at `target`."""
    conn = sqlite3.connect(str(target))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript((config.DDL_DIR / "01_create_tables.sql").read_text(encoding="utf-8"))
        conn.executescript((config.DML_DIR / "02_insert_seed.sql").read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return Path(target)


def write_seed(db_path: Optional[Path] = None, out: Path = SEED_PATH, *, mapping: Path = MAPPING_PATH) -> dict:
    """Write the scenario graph as RDF/XML (not compressed; the same bytes on each run). Return its counts.

    With no db_path, the rows come from the SQL scripts 01_create_tables.sql and 02_insert_seed.sql, so the
    file depends only on files in git. With db_path, the rows come from that database, in the scenario scope.
    The app of a developer adds chat and audit rows to its database, and all of them are in the scope.
    """
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="triad-seed-") as folder:
        source = Path(db_path) if db_path else scenario_database(Path(folder) / "scenario.db")
        copy, rows = _snapshot(source, Path(folder), "scenarios")
        lines = materialize(copy, mapping)
        found = graph_counts(lines)
        check_counts(found, copy)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    size = _write_atomic(out, rdf_xml_bytes(nt_bytes(lines)))
    return {"scope": "scenarios", "rows": rows, **{k: found[k] for k in ("total", "per_kind", "individuals")},
            "file": str(out), "bytes": size, "seconds": round(time.perf_counter() - started, 2),
            "per_predicate": found["per_predicate"], "per_class": found["per_class"]}


def summary(report: Mapping) -> str:
    """The totals of a report in one line, for the command output."""
    kinds = report["per_kind"]
    return (f"{report['total']:,} triples ({kinds['type']:,} rdf:type, {kinds['attribute']:,} attribute, "
            f"{kinds['fk']:,} foreign key), {report['individuals']:,} individuals, from {report['rows']:,} rows")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Write the scenario graph models/semantic/kg/triad_kg_seed.rdf.")
    parser.add_argument("--seed", action="store_true", required=True, help="write the seed graph")
    parser.add_argument("--db", type=Path, default=None,
                        help="the database (default: the SQL scripts 01 and 02 in a temporary database)")
    parser.add_argument("--out", type=Path, default=SEED_PATH, help="the output file (default: %(default)s)")
    args = parser.parse_args(argv)
    try:
        report = write_seed(args.db, args.out)
    except ExportError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Wrote {args.out} ({report['bytes']:,} bytes) in {report['seconds']} s: {summary(report)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
