"""Run the operations of a .sparql file on the SPARQL endpoints of TRIAD (src/scripts/kg.sh sparql FILE).

The split rule (the files in models/semantic/sparql/ follow it):
- A marker line starts each operation: "# ID. Title", for example "# Q1. The current record of Patient A".
  The ID is a capital letter, then capital letters or digits, then one optional small letter:
  Q1, Q14b, QA, U1, D2, C1. An ID can also have parts after a dot, each with digits: B.1, B.2a.
  Then the period after the ID is optional: "# B.1 All graphs" and "# B.1. All graphs" are both markers.
  The regular expression is MARKER (below); a match without a dot part needs the period.
- The operation is the text from its marker line to the next marker line, or to the end of the file.
  Its comment lines stay in the text (SPARQL ignores them).
- The PREFIX and BASE lines before the first marker go before each operation.
  The other lines before the first marker (comments, blank lines) are not sent.
- A file with no marker line is one operation, with the file name as its title.
- Other comment lines, such as "# Note: ..." or "#     ?below = ...", do not start an operation.
  Do not start a comment line with a capital word and a period (for example "# NOTE. ...").
- ";" does not split an operation: it is also part of the SPARQL triple patterns. One update operation can hold
  more than one update, separated by ";". The store gets them in one request.

The form of the operation decides the endpoint:
- SELECT, ASK, CONSTRUCT and DESCRIBE go to TRIAD_SPARQL_QUERY_URL, with no login.
- All other forms (INSERT, DELETE, LOAD, CLEAR, CREATE, DROP, COPY, MOVE, ADD, WITH) are updates. They go to
  TRIAD_SPARQL_UPDATE_URL with a digest login as TRIAD_SPARQL_USER.

The output shows the ID and the title of each operation, then a table of the rows (SELECT), true or false (ASK),
a table of the triples (CONSTRUCT, DESCRIBE) or the message of the store (an update).
The IRIs show with the prefixes of the file. The exit code is 0 if all operations pass, 1 if an operation fails,
and 2 if the file or an option has a problem.

Usage (kg.sh sets PYTHONPATH to src/backend):
    python -m infrastructure.rdf.sparql_script FILE [--only ID[,ID...]] [--max-rows N] [--keep-going]
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TextIO

from infrastructure.rdf import namespaces
from infrastructure.rdf.protocol import DEFAULT_TIMEOUT, SparqlError, send

MARKER = re.compile(r"^# (?P<id>[A-Z][A-Z0-9]*[a-z]?(?P<parts>(?:\.[0-9]+[a-z]?)*))(?P<dot>\.?) +(?P<title>\S.*?)\s*$")
PROLOGUE_LINE = re.compile(r"^\s*(PREFIX|BASE)\b", re.IGNORECASE)
PREFIX_DECL = re.compile(r"PREFIX\s+([A-Za-z][\w.-]*)?:\s*<([^>]*)>", re.IGNORECASE)
# The parts before the form keyword: space, comments, PREFIX and BASE declarations.
LEADING = re.compile(r"\s+|#[^\n]*|PREFIX\s+[^\s:]*:\s*<[^>]*>|BASE\s*<[^>]*>", re.IGNORECASE)
QUERY_FORMS = ("SELECT", "ASK", "CONSTRUCT", "DESCRIBE")
UPDATE_FORMS = ("INSERT", "DELETE", "LOAD", "CLEAR", "CREATE", "DROP", "COPY", "MOVE", "ADD", "WITH")
CELL_WIDTH = 60
DEFAULT_MAX_ROWS = 50
# Prefixes for the output only, if the file does not declare them.
DISPLAY_PREFIXES = (
    ("rdf", "http://www.w3.org/1999/02/22-rdf-syntax-ns#"),
    ("rdfs", "http://www.w3.org/2000/01/rdf-schema#"),
    ("owl", "http://www.w3.org/2002/07/owl#"),
    ("xsd", "http://www.w3.org/2001/XMLSchema#"),
    ("triad", namespaces.TRIAD),
    ("kg", namespaces.KG),
)


@dataclass(frozen=True)
class Operation:
    id: str              # "" for a file with no marker line
    title: str
    line: int            # the line of the marker in the file (1 = the first line)
    text: str            # the PREFIX and BASE lines of the file, then the lines of the operation


def marker(line: str) -> Optional[re.Match]:
    match = MARKER.match(line)
    if match and (match["dot"] or match["parts"]):
        return match
    return None


def split_operations(text: str, name: str = "the file") -> list[Operation]:
    """Split the text of a .sparql file into its operations (the split rule of the module docstring)."""
    lines = text.splitlines()
    starts = [(number, match) for number, line in enumerate(lines) if (match := marker(line))]
    if not starts:
        return [Operation(id="", title=name, line=1, text=text)]
    prologue = [line for line in lines[:starts[0][0]] if PROLOGUE_LINE.match(line)]
    operations = []
    for index, (number, match) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(lines)
        body = "\n".join(prologue + lines[number:end]).rstrip() + "\n"
        operations.append(Operation(id=match["id"], title=match["title"], line=number + 1, text=body))
    return operations


def operation_form(text: str) -> str:
    """The first keyword after the prologue and the comments, in capitals ("" if the text has no keyword)."""
    position = 0
    while match := LEADING.match(text, position):
        if match.end() == position:
            break
        position = match.end()
    word = re.match(r"[A-Za-z]+", text[position:])
    return word.group(0).upper() if word else ""


def prefixes_of(text: str) -> list[tuple[str, str]]:
    """The prefixes for the output: the PREFIX declarations of the text, then the DISPLAY_PREFIXES that the text
    does not declare. A list of (prefix, namespace), the longest namespace first."""
    found = {namespace: prefix or "" for prefix, namespace in PREFIX_DECL.findall(text) if namespace}
    for prefix, namespace in DISPLAY_PREFIXES:
        if namespace not in found and prefix not in found.values():
            found[namespace] = prefix
    return sorted(((prefix, namespace) for namespace, prefix in found.items()), key=lambda item: -len(item[1]))


def show_iri(iri: str, prefixes: list[tuple[str, str]]) -> str:
    for prefix, namespace in prefixes:
        if iri.startswith(namespace) and len(iri) > len(namespace):
            return f"{prefix}:{iri[len(namespace):]}"
    return f"<{iri}>"


def show_term(term: dict, prefixes: list[tuple[str, str]]) -> str:
    """One RDF term of the SPARQL JSON results, as a short text."""
    kind, value = term.get("type"), term.get("value", "")
    if kind == "uri":
        return show_iri(value, prefixes)
    if kind == "bnode":
        return f"_:{value}"
    if term.get("xml:lang"):
        return f"{value}@{term['xml:lang']}"
    return value


def cell(text: str) -> str:
    """A table cell of at most CELL_WIDTH characters. A long IRI loses its middle part, a long text its end."""
    text = " ".join(text.split())
    if len(text) <= CELL_WIDTH:
        return text
    if text.startswith("<") and text.endswith(">"):
        head = (CELL_WIDTH - 3) // 2
        return text[:head] + "..." + text[len(text) - (CELL_WIDTH - 3 - head):]
    return text[:CELL_WIDTH - 3] + "..."


def table(header: list[str], rows: list[list[str]], max_rows: int) -> list[str]:
    """A text table. max_rows = 0 shows all rows."""
    shown = rows if max_rows <= 0 else rows[:max_rows]
    cells = [[cell(value) for value in row] for row in shown]
    widths = [max([len(name)] + [len(row[i]) for row in cells]) for i, name in enumerate(header)]
    lines = [" | ".join(name.ljust(widths[i]) for i, name in enumerate(header)).rstrip(),
             "-+-".join("-" * width for width in widths)]
    lines += [" | ".join(value.ljust(widths[i]) for i, value in enumerate(row)).rstrip() for row in cells]
    if len(shown) < len(rows):
        lines.append(f"... {len(rows) - len(shown)} more rows. Use --max-rows 0 to show all rows.")
    return lines


def show_select(body: bytes, prefixes: list[tuple[str, str]], max_rows: int) -> tuple[str, list[str]]:
    results = json.loads(body.decode("utf-8"))
    if "boolean" in results:
        return "ASK", ["true" if results["boolean"] else "false"]
    names = results.get("head", {}).get("vars", [])
    bindings = results.get("results", {}).get("bindings", [])
    rows = [[show_term(row[name], prefixes) if name in row else "" for name in names] for row in bindings]
    count = f"{len(rows)} row" + ("" if len(rows) == 1 else "s")
    return count, (table(names, rows, max_rows) if rows else ["(no rows)"])


def show_triples(answer_type: str, body: bytes, prefixes: list[tuple[str, str]], max_rows: int) -> tuple[str, list[str]]:
    import pyoxigraph   # the RDF parser; imported here, so a query-only run does not need it

    def term(node) -> str:
        if isinstance(node, pyoxigraph.NamedNode):
            return show_iri(node.value, prefixes)
        if isinstance(node, pyoxigraph.BlankNode):
            return f"_:{node.value}"
        return f"{node.value}@{node.language}" if node.language else node.value

    triples = list(pyoxigraph.parse(io.BytesIO(body), answer_type))
    rows = [[term(t.subject), term(t.predicate), term(t.object)] for t in triples]
    count = f"{len(rows)} triple" + ("" if len(rows) == 1 else "s")
    return count, (table(["subject", "predicate", "object"], rows, max_rows) if rows else ["(no triples)"])


def show_update(body: bytes) -> list[str]:
    """The message of the store. Virtuoso gives it as one result value ("Insert into <g>, 3 (or less) triples -- done")."""
    text = body.decode("utf-8", "replace").strip()
    try:
        results = json.loads(text)
        values = [term.get("value", "") for row in results["results"]["bindings"] for term in row.values()]
        lines = [line for value in values for line in value.splitlines() if line.strip()]
    except (ValueError, KeyError, TypeError, AttributeError):
        lines = [line for line in text.splitlines() if line.strip()]
    return lines or ["(the store sent no message)"]


def run_operation(operation: Operation, settings, max_rows: int, timeout: float) -> tuple[str, list[str]]:
    """Send one operation. Return the summary and the result lines. Raise SparqlError if the store refuses it."""
    form = operation_form(operation.text)
    if not form:
        raise SparqlError("The operation has no SPARQL text.")
    prefixes = prefixes_of(operation.text)
    if form in QUERY_FORMS:
        accept = ("application/n-triples" if form in ("CONSTRUCT", "DESCRIBE")
                  else "application/sparql-results+json")
        answer = send(settings.sparql_query_url, query=operation.text, accept=accept, timeout=timeout)
        if form in ("CONSTRUCT", "DESCRIBE"):
            count, lines = show_triples(answer.content_type, answer.body, prefixes, max_rows)
        else:
            count, lines = show_select(answer.body, prefixes, max_rows)
        return f"{form}, {count}" if form != "ASK" else "ASK", lines
    if form not in UPDATE_FORMS:
        raise SparqlError(f'The operation starts with "{form}". Use a SPARQL query or update form.')
    answer = send(settings.sparql_update_url, update=operation.text, accept="application/sparql-results+json",
                  user=settings.sparql_user, password=settings.sparql_password, timeout=timeout)
    return f"update as {settings.sparql_user}", show_update(answer.body)


def run_file(path: Path, settings, only: Optional[list[str]] = None, max_rows: int = DEFAULT_MAX_ROWS,
             keep_going: bool = False, timeout: float = DEFAULT_TIMEOUT, out: TextIO = sys.stdout) -> int:
    """Run the operations of a file and write the results. Return the exit code (0, 1 or 2)."""
    operations = split_operations(path.read_text(encoding="utf-8"), path.name)
    if only:
        wanted = {name.upper() for name in only}
        unknown = wanted - {operation.id.upper() for operation in operations}
        if unknown:
            known = ", ".join(operation.id for operation in operations)
            out.write(f"ERROR: {path.name} has no operation {', '.join(sorted(unknown))}. It has: {known}.\n")
            return 2
        operations = [operation for operation in operations if operation.id.upper() in wanted]
    out.write(f"{path}: {len(operations)} operation" + ("" if len(operations) == 1 else "s") +
              f". Queries: {settings.sparql_query_url}. Updates: {settings.sparql_update_url}"
              f" (user {settings.sparql_user}).\n")
    failed = 0
    for operation in operations:
        label = f"{operation.id}. {operation.title}" if operation.id else operation.title
        started = time.perf_counter()
        try:
            summary, lines = run_operation(operation, settings, max_rows, timeout)
        except (SparqlError, ValueError) as error:
            failed += 1
            out.write(f"\n== {label} (line {operation.line})\nERROR: {error}\n")
            if not keep_going:
                out.write(f"\nStopped at line {operation.line} of {path.name}. "
                          "Use --keep-going to run the other operations after an error.\n")
                out.flush()
                return 1
            continue
        seconds = time.perf_counter() - started
        out.write(f"\n== {label} ({summary}, {seconds:.2f} s)\n" + "\n".join(lines) + "\n")
        out.flush()
    passed = len(operations) - failed
    out.write(f"\n{passed} of {len(operations)} operations passed.\n")
    return 1 if failed else 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the queries and updates of a .sparql file (see the split rule).")
    parser.add_argument("file", type=Path, help="the .sparql file")
    parser.add_argument("--only", help="run only these operations, for example --only Q1,Q2,QA")
    parser.add_argument("--max-rows", type=int, default=DEFAULT_MAX_ROWS,
                        help=f"show this number of rows for each operation (default {DEFAULT_MAX_ROWS}; 0 = all)")
    parser.add_argument("--keep-going", action="store_true", help="run the other operations after an error")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help=f"the time limit of one request in seconds (default {DEFAULT_TIMEOUT:.0f})")
    args = parser.parse_args(argv)
    if not args.file.is_file():
        print(f"ERROR: the file {args.file} does not exist.", file=sys.stderr)
        return 2
    from infrastructure import config
    config.load_env_file()
    settings = config.Settings.from_env()
    only = [name.strip() for name in args.only.split(",") if name.strip()] if args.only else None
    return run_file(args.file, settings, only=only, max_rows=args.max_rows, keep_going=args.keep_going,
                    timeout=args.timeout)


if __name__ == "__main__":
    sys.exit(main())
