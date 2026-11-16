"""The load check: compare the triples of each predicate in the ABox graph with kg_report.json.

"kg.sh load" runs this check after the bulk load when kg_report.json exists. The check sends one SPARQL query
(GROUP BY ?p over the ABox graph) to TRIAD_SPARQL_QUERY_URL. A check of the total only can hide an error:
the count per predicate found the NULL bug of the mapping (plan 5, section 3.3).

The shape of kg_report.json. The export (main.py export-kg) writes it into TRIAD_KG_DIR, next to triad_kg.nt.gz.
This check reads only "total" and "per_predicate"; the file can have more keys.
    {
      "total": 1298807,
      "per_predicate": {
        "http://www.w3.org/1999/02/22-rdf-syntax-ns#type": 188302,
        "https://github.com/MohamedKhalidmk/TRIAD/ontology/triad#name": 405,
        ...
      },
      "per_class": {
        "https://github.com/MohamedKhalidmk/TRIAD/ontology/triad#Patient": 113,
        ...
      },
      ...
    }
- "total": the number of triples in triad_kg.nt.gz, thus the triples of the ABox graph after the load.
- "per_predicate": the number of triples of each predicate in triad_kg.nt.gz. A key is a full IRI with no
  angle brackets. The sum of the values must equal "total".
- "per_class": the number of rdf:type triples of each class (full IRIs). The export checks it against the
  rows of the tables; this load check does not use it.

The SQL side (plan 5, section 3.3): expected_counts() computes the same counts from the rows of a SQLite
database with the column map of models/semantic/vocabulary.py. The export (kg_export.py) compares the two
before it writes a file, and the tests compare them on the scenario and the full databases:
- per class: the rdf:type triples of a class = the rows of its table (a subtype row adds a second type);
- per property: the triples = the non-NULL cells of its columns (an FK of FK_JOINS: the rows of the join);
- individuals: the rows of the tables whose rows have an IRI of their own (not the subtypes, not StaffLanguage).

Usage (kg.sh sets PYTHONPATH to src/backend):
    python -m infrastructure.rdf.counts [--report FILE] [--graph IRI]
The exit code is 0 if the counts agree, 1 if they do not agree, and 2 if the check cannot run.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Mapping, Optional

from infrastructure.rdf.namespaces import ABOX_GRAPH, TRIAD
from infrastructure.rdf.protocol import DEFAULT_TIMEOUT, SparqlError, send
from models.semantic import vocabulary as V

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
KINDS = ("type", "attribute", "fk")   # the keys of "per_kind" in kg_report.json


def expected_counts(conn: sqlite3.Connection) -> dict:
    """The triples that the R2RML mapping gives for the rows of a database, from SQL and vocabulary.py.

    The result has the keys of kg_report.json: "total", "per_kind" (type, attribute, fk), "individuals",
    "per_predicate" and "per_class" (full IRIs). A predicate or a class with no triples is not in the result,
    because the graph has no triple of it.
    """
    def one(sql: str) -> int:
        return int(conn.execute(sql).fetchone()[0])

    rows = {table: one(f'SELECT count(*) FROM "{table}"') for table in V.SUBJECT}
    per_class = {TRIAD + cls: rows[table] for table, cls in V.TABLE_CLASS.items() if rows[table]}
    per_predicate: Counter = Counter()
    per_kind = {"type": sum(per_class.values()), "attribute": 0, "fk": 0}
    for (table, column), (term, kind) in V.COLUMNS.items():
        if (table, column) in V.FK_JOINS:   # the join of the mapping (CareTeamMember -> CareTeam)
            join_table, join_column, subject_column = V.FK_JOINS[(table, column)]
            count = one(f'SELECT count(*) FROM "{table}" c JOIN "{join_table}" j ON j."{join_column}" = c."{column}" '
                        f'WHERE j."{subject_column}" IS NOT NULL')
        else:
            count = one(f'SELECT count("{column}") FROM "{table}"')
        per_predicate[TRIAD + term] += count
        per_kind["attribute" if kind == V.ATTRIBUTE else "fk"] += count
    per_predicate[RDF_TYPE] = per_kind["type"]
    individuals = sum(rows[table] for table, (_, column) in V.SUBJECT.items() if column == "Id")
    return {
        "total": sum(per_kind.values()),
        "per_kind": per_kind,
        "individuals": individuals,
        "rows": sum(rows.values()),
        "per_predicate": {iri: n for iri, n in sorted(per_predicate.items()) if n},
        "per_class": dict(sorted(per_class.items())),
    }


def kind_of(predicate: str) -> Optional[str]:
    """The kind of a predicate IRI: "type", "attribute", "fk", or None if the mapping has no such predicate."""
    if predicate == RDF_TYPE:
        return "type"
    if not predicate.startswith(TRIAD):
        return None
    term = predicate[len(TRIAD):]
    if term in V.attribute_properties():
        return "attribute"
    if term in V.stored_object_properties():
        return "fk"
    return None


def compare_with_sql(report: Mapping, expected: Mapping) -> list[str]:
    """The differences between the counts of a graph (kg_report.json) and expected_counts(): one line each.

    An empty list means that the check passes: the same triples per predicate and per class, the same
    total and the same number of individuals.
    """
    lines = [f"per predicate: {line}"
             for line in differences(expected["per_predicate"], report["per_predicate"], "SQL")]
    lines += [f"per class: {line}" for line in differences(expected["per_class"], report["per_class"], "SQL")]
    for key in ("total", "individuals"):
        if report.get(key) != expected[key]:
            lines.append(f"{key}: SQL {expected[key]}, the graph {report.get(key)}")
    return lines


def read_report(path: Path) -> tuple[int, dict[str, int]]:
    """The total and the counts per predicate of kg_report.json. Raise ValueError if the file has a problem."""
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"Cannot read {path}: {error}") from None
    if not isinstance(report, dict):
        raise ValueError(f"{path} does not hold a JSON object.")
    total, per_predicate = report.get("total"), report.get("per_predicate")
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise ValueError(f'{path}: "total" must be a number of triples.')
    if not isinstance(per_predicate, dict) or not per_predicate:
        raise ValueError(f'{path}: "per_predicate" must be an object of predicate IRIs and numbers.')
    counts = {}
    for iri, count in per_predicate.items():
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError(f'{path}: the count of {iri} in "per_predicate" is not a number of triples.')
        counts[iri.strip().strip("<>")] = count
    if sum(counts.values()) != total:
        raise ValueError(f'{path}: the sum of "per_predicate" ({sum(counts.values())}) is not "total" ({total}).')
    return total, counts


def predicate_count_query(graph: str = ABOX_GRAPH) -> str:
    """The SPARQL query of the counts per predicate: ?p and ?n. Virtuoso and Oxigraph run the same text."""
    return f"SELECT ?p (COUNT(*) AS ?n) FROM <{graph}> WHERE {{ ?s ?p ?o }} GROUP BY ?p"


def class_count_query(graph: str = ABOX_GRAPH) -> str:
    """The SPARQL query of the rdf:type triples per class: ?c and ?n."""
    return f"SELECT ?c (COUNT(*) AS ?n) FROM <{graph}> WHERE {{ ?s a ?c }} GROUP BY ?c"


def predicate_counts(query_url: str, graph: str = ABOX_GRAPH, timeout: float = DEFAULT_TIMEOUT) -> dict[str, int]:
    """The number of triples of each predicate in a graph (one SPARQL query)."""
    query = predicate_count_query(graph)
    answer = send(query_url, query=query, accept="application/sparql-results+json", timeout=timeout)
    rows = json.loads(answer.body.decode("utf-8"))["results"]["bindings"]
    return {row["p"]["value"]: int(row["n"]["value"]) for row in rows}


def differences(expected: Mapping[str, int], found: Mapping[str, int], source: str = "kg_report.json") -> list[str]:
    """One line for each predicate (or class) with a different count, in the order of the IRIs."""
    lines = []
    for iri in sorted(set(expected) | set(found)):
        want, have = expected.get(iri, 0), found.get(iri, 0)
        if want != have:
            lines.append(f"{iri}: {source} {want}, the graph {have} ({have - want:+d})")
    return lines


def main(argv: Optional[list[str]] = None) -> int:
    from infrastructure import config
    config.load_env_file()
    settings = config.Settings.from_env()
    parser = argparse.ArgumentParser(description="Compare the triples per predicate of a graph with kg_report.json.")
    parser.add_argument("--report", type=Path, default=settings.kg_dir / "kg_report.json",
                        help="the report of the export (default: TRIAD_KG_DIR/kg_report.json)")
    parser.add_argument("--graph", default=ABOX_GRAPH, help="the graph IRI (default: the ABox graph)")
    args = parser.parse_args(argv)
    try:
        total, expected = read_report(args.report)
        found = predicate_counts(settings.sparql_query_url, args.graph)
    except (ValueError, SparqlError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    lines = differences(expected, found)
    if lines:
        print(f"ERROR: the counts per predicate of <{args.graph}> do not agree with {args.report}:", file=sys.stderr)
        for line in lines:
            print("    " + line, file=sys.stderr)
        print(f"    The graph has {sum(found.values())} triples; kg_report.json gives {total}.", file=sys.stderr)
        return 1
    print(f"The counts per predicate agree with {args.report.name}: {len(expected)} predicates, {total} triples.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
