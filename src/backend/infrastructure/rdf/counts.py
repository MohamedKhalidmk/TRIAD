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

Usage (kg.sh sets PYTHONPATH to src/backend):
    python -m infrastructure.rdf.counts [--report FILE] [--graph IRI]
The exit code is 0 if the counts agree, 1 if they do not agree, and 2 if the check cannot run.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Mapping, Optional

from infrastructure.rdf.namespaces import ABOX_GRAPH
from infrastructure.rdf.protocol import DEFAULT_TIMEOUT, SparqlError, send


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


def predicate_counts(query_url: str, graph: str = ABOX_GRAPH, timeout: float = DEFAULT_TIMEOUT) -> dict[str, int]:
    """The number of triples of each predicate in a graph (one SPARQL query)."""
    query = f"SELECT ?p (COUNT(*) AS ?n) FROM <{graph}> WHERE {{ ?s ?p ?o }} GROUP BY ?p"
    answer = send(query_url, query=query, accept="application/sparql-results+json", timeout=timeout)
    rows = json.loads(answer.body.decode("utf-8"))["results"]["bindings"]
    return {row["p"]["value"]: int(row["n"]["value"]) for row in rows}


def differences(expected: Mapping[str, int], found: Mapping[str, int]) -> list[str]:
    """One line for each predicate with a different count, in the order of the IRIs."""
    lines = []
    for iri in sorted(set(expected) | set(found)):
        want, have = expected.get(iri, 0), found.get(iri, 0)
        if want != have:
            lines.append(f"{iri}: kg_report.json {want}, the graph {have} ({have - want:+d})")
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
