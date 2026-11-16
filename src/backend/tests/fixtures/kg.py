"""The helpers of the SQL = SPARQL tests (tests/integration/test_kg_queries.py; plan 5, sections 4.4 and 4.5).

- sql_queries() and sparql_operations(): the queries of the SQL file and of a .sparql file, by their ID.
- build_oxigraph(): an Oxigraph store with the graph of a SQLite database. The R2RML mapping runs in this process
  (kg_export.materialize); no file is written. The ABox graph gets the data, the TBox graph gets triad.owl, and the
  scratch and meta graphs exist and are empty (as after G1 of 01_create_graphs.sparql).
  oxigraph_for() keeps one store for each database in this process, so the build of the full graph
  (1.3 million triples, about 10 s) runs once in a test session.
- OxigraphKg and VirtuosoKg: one small interface for the two stores. run() gives Rows (SELECT), a bool (ASK) or a
  set of triples (CONSTRUCT, DESCRIBE); update() runs an update; count() gives the triples of a graph.
- The values of both sides become plain Python values with the comparison rules of plan 4.5:
  a NULL of SQL and an unbound variable are None; a number is an int (or a float); a time (xsd:dateTime, or an
  ISO 8601 text with a time and an offset) is its instant in UTC, because the stores write "+00:00" as "Z" and drop
  the trailing zeros of the seconds; other values are their text; an IRI is "<iri>".
"""
from __future__ import annotations

import io
import json
import re
import sqlite3
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Union

from infrastructure import config
from infrastructure.rdf import kg_export, namespaces, oxigraph_store, sparql_script
from infrastructure.rdf.protocol import send

SPARQL_DIR = config.SEMANTIC_DIR / "sparql"
SQL_SELECT_FILE = config.DML_DIR / "03_select_queries.sql"
SQL_UPDATE_FILE = config.DML_DIR / "04_update_delete.sql"

XSD = "http://www.w3.org/2001/XMLSchema#"
INTEGER_TYPES = {XSD + name for name in ("integer", "int", "long", "short", "byte", "nonNegativeInteger",
                                          "positiveInteger", "nonPositiveInteger", "negativeInteger",
                                          "unsignedInt", "unsignedLong", "unsignedShort", "unsignedByte")}
DECIMAL_TYPES = {XSD + "decimal", XSD + "double", XSD + "float"}
DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$")
SQL_MARKER = re.compile(r"^-- (?P<id>Q\d+[a-z]?)\. ", re.MULTILINE)

Value = Union[None, int, float, bool, str, datetime]


# ---------------------------------------------------------------------------------------------
# The query files

def sql_queries(path: Path = SQL_SELECT_FILE) -> dict[str, str]:
    """The queries of 03_select_queries.sql by ID (Q1 ... Q14b). A query is the text from its marker line
    "-- Qn. Title" to the next marker line (the comments stay; SQLite ignores them)."""
    text = path.read_text(encoding="utf-8")
    starts = list(SQL_MARKER.finditer(text))
    return {match["id"]: text[match.start():starts[i + 1].start() if i + 1 < len(starts) else len(text)].strip()
            for i, match in enumerate(starts)}


def sparql_operations(name: str) -> dict[str, sparql_script.Operation]:
    """The operations of a file of models/semantic/sparql/ by ID, split with the rule of kg.sh sparql."""
    path = SPARQL_DIR / name
    return {op.id: op for op in sparql_script.split_operations(path.read_text(encoding="utf-8"), path.name)}


def with_graph(text: str, graph: str, instead_of: str = namespaces.ABOX_GRAPH) -> str:
    """The text with each <instead_of> changed to <graph> (to run a script on a copy in another graph)."""
    return text.replace(f"<{instead_of}>", f"<{graph}>")


# ---------------------------------------------------------------------------------------------
# The values

def instant(text: str) -> datetime:
    """The instant of an ISO 8601 time with an offset, in UTC."""
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def sql_value(value) -> Value:
    if isinstance(value, str) and DATETIME.match(value):
        return instant(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def literal_value(text: str, datatype: Optional[str]) -> Value:
    if datatype in INTEGER_TYPES:
        return int(text)
    if datatype in DECIMAL_TYPES:
        number = float(text)
        return int(number) if number.is_integer() else number
    if datatype == XSD + "boolean":
        return text in ("true", "1")
    if datatype == XSD + "dateTime" or (datatype is None and DATETIME.match(text)):
        return instant(text)
    return text


def term_value(term) -> Value:
    """A pyoxigraph term (or None for an unbound variable) as a plain value."""
    import pyoxigraph as ox
    if term is None:
        return None
    if isinstance(term, ox.NamedNode):
        return f"<{term.value}>"
    if isinstance(term, ox.BlankNode):
        return f"_:{term.value}"
    return literal_value(term.value, term.datatype.value if term.datatype else None)


def json_value(term: Optional[dict]) -> Value:
    """A term of the SPARQL JSON results (or None for an unbound variable) as a plain value."""
    if term is None:
        return None
    kind = term.get("type")
    if kind == "uri":
        return f"<{term['value']}>"
    if kind == "bnode":
        return f"_:{term['value']}"
    return literal_value(term["value"], term.get("datatype"))


def triple_key(triple) -> tuple:
    """A pyoxigraph triple as (subject, predicate, object) plain values."""
    return term_value(triple.subject), term_value(triple.predicate), term_value(triple.object)


@dataclass
class Rows:
    names: list[str]
    rows: list[tuple]

    def column(self, name: str) -> list:
        index = self.names.index(name)
        return [row[index] for row in self.rows]


def sql_rows(db_path: Path, sql: str) -> Rows:
    """Run one SQL query on a database (read only)."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cursor = conn.execute(sql)
        names = [d[0] for d in cursor.description]
        return Rows(names, [tuple(sql_value(v) for v in row) for row in cursor.fetchall()])
    finally:
        conn.close()


def sort_key(row: tuple) -> tuple:
    """A key that sorts rows with None, numbers, texts and times together (for a readable error message)."""
    return tuple((value is None, type(value).__name__, str(value)) for value in row)


def differences(sql: Rows, kg: Rows, ordered: bool) -> list[str]:
    """The differences between the SQL rows and the SPARQL rows ([] if they are the same; plan 4.5).

    The SPARQL variable of each column is the SQL column name with a small first letter (VisitDate -> visitDate).
    ordered: compare the order too (the queries with a total ORDER BY); else compare the rows as multisets.
    """
    problems = []
    names = [name[:1].lower() + name[1:] for name in sql.names]
    if names != kg.names:
        problems.append(f"the columns differ: SQL {names}, SPARQL {kg.names}")
    if ordered:
        if sql.rows != kg.rows:
            problems.append("the rows or their order differ:\n  SQL:    " + "\n          ".join(map(repr, sql.rows))
                            + "\n  SPARQL: " + "\n          ".join(map(repr, kg.rows)))
    else:
        only_sql = Counter(sql.rows) - Counter(kg.rows)
        only_kg = Counter(kg.rows) - Counter(sql.rows)
        for label, rows in (("only in SQL", only_sql), ("only in SPARQL", only_kg)):
            for row in sorted(rows.elements(), key=sort_key)[:10]:
                problems.append(f"{label}: {row!r}")
    return problems


# ---------------------------------------------------------------------------------------------
# The stores

class OxigraphKg:
    """The embedded Oxigraph store (pyoxigraph 0.3)."""

    name = "oxigraph"

    def __init__(self, store, folder: Optional[Path] = None):
        self.store = store
        self.folder = folder

    def run(self, text: str):
        import pyoxigraph as ox
        result = self.store.query(text)
        if isinstance(result, bool):
            return result
        if isinstance(result, ox.QuerySolutions):
            names = [variable.value for variable in result.variables]
            return Rows(names, [tuple(term_value(solution[i]) for i in range(len(names))) for solution in result])
        return {triple_key(triple) for triple in result}

    def update(self, text: str) -> None:
        self.store.update(text)

    def count(self, graph: str = namespaces.ABOX_GRAPH) -> int:
        return oxigraph_store.triple_count(self.store, graph)

    def insert(self, graph: str, triples: str, prefixes: str = "") -> None:
        self.update(f"{prefixes}\nINSERT DATA {{ GRAPH <{graph}> {{\n{triples}\n}} }}")

    def clear(self, graph: str) -> None:
        self.update(f"CLEAR SILENT GRAPH <{graph}>")


class VirtuosoKg:
    """Virtuoso over the SPARQL 1.1 Protocol: queries on TRIAD_SPARQL_QUERY_URL (no login), updates on
    TRIAD_SPARQL_UPDATE_URL as TRIAD_SPARQL_USER (digest login). The same client as kg.sh sparql."""

    name = "virtuoso"

    def __init__(self, settings, timeout: float = 600.0):
        self.settings = settings
        self.timeout = timeout

    def run(self, text: str):
        form = sparql_script.operation_form(text)
        if form in ("CONSTRUCT", "DESCRIBE"):
            import pyoxigraph as ox
            answer = send(self.settings.sparql_query_url, query=text, accept="application/n-triples",
                          timeout=self.timeout)
            return {triple_key(t) for t in ox.parse(io.BytesIO(answer.body), answer.content_type)}
        answer = send(self.settings.sparql_query_url, query=text, accept="application/sparql-results+json",
                      timeout=self.timeout)
        results = json.loads(answer.body.decode("utf-8"))
        if "boolean" in results:
            return bool(results["boolean"])
        names = results["head"]["vars"]
        return Rows(names, [tuple(json_value(binding.get(name)) for name in names)
                            for binding in results["results"]["bindings"]])

    def update(self, text: str) -> None:
        send(self.settings.sparql_update_url, update=text, accept="application/sparql-results+json",
             user=self.settings.sparql_user, password=self.settings.sparql_password, timeout=self.timeout)

    def count(self, graph: str = namespaces.ABOX_GRAPH) -> int:
        rows = self.run(f"SELECT (COUNT(*) AS ?n) FROM <{graph}> WHERE {{ ?s ?p ?o }}")
        return rows.rows[0][0]

    def insert(self, graph: str, triples: str, prefixes: str = "") -> None:
        self.update(f"{prefixes}\nINSERT DATA {{ GRAPH <{graph}> {{\n{triples}\n}} }}")

    def clear(self, graph: str) -> None:
        self.update(f"CLEAR SILENT GRAPH <{graph}>")


def build_oxigraph(db_path: Path, folder: Optional[Path] = None):
    """A pyoxigraph Store with the graph of a database in the ABox graph and triad.owl in the TBox graph.

    folder None gives a store in memory; a folder gives a store on disk (less memory for the full graph).
    """
    import pyoxigraph as ox
    with tempfile.TemporaryDirectory(prefix="triad-kg-test-") as tmp:
        copy = Path(tmp) / "copy.db"
        kg_export.copy_database(Path(db_path), copy)
        lines = kg_export.materialize(copy)
    store = ox.Store(str(folder)) if folder else ox.Store()
    store.bulk_load(io.BytesIO(kg_export.nt_bytes(lines)), "application/n-triples",
                    to_graph=ox.NamedNode(namespaces.ABOX_GRAPH))
    del lines
    store.bulk_load(io.BytesIO(oxigraph_store.OWL_PATH.read_bytes()), "application/rdf+xml",
                    to_graph=ox.NamedNode(namespaces.TBOX_GRAPH))
    for graph in namespaces.GRAPHS:
        store.add_graph(ox.NamedNode(graph))
    return store


_STORES: dict[Path, OxigraphKg] = {}


def oxigraph_for(db_path: Path, folder: Optional[Path] = None) -> OxigraphKg:
    """The Oxigraph store of a database: built at the first call, then the same object in this process.
    The tests must not change it: use copy_of() for a test that writes (or clean the scratch graph)."""
    key = Path(db_path).resolve()
    if key not in _STORES:
        _STORES[key] = OxigraphKg(build_oxigraph(key, folder), folder)
    return _STORES[key]


def copy_of(kg: OxigraphKg, folder: Optional[Path] = None) -> OxigraphKg:
    """A copy of a store: a RocksDB backup for a store on disk (fast: hard links), else a new store in memory."""
    import pyoxigraph as ox
    if kg.folder is not None and folder is not None:
        kg.store.flush()
        kg.store.backup(str(folder))
        return OxigraphKg(ox.Store(str(folder)), folder)
    store = ox.Store()
    store.bulk_extend(kg.store.quads_for_pattern(None, None, None, None))
    for graph in kg.store.named_graphs():
        store.add_graph(graph)
    return OxigraphKg(store)


def data_triples(text: str) -> int:
    """The number of triples in the INSERT DATA blocks of an update text (TriG between the braces)."""
    import pyoxigraph as ox
    prefixes = "\n".join(line for line in text.splitlines() if sparql_script.PROLOGUE_LINE.match(line))
    total = 0
    for match in re.finditer(r"INSERT DATA\s*\{", text):
        depth, start = 1, match.end()
        position = start
        while depth:
            char = text[position]
            if char == '"':                                  # skip a literal: it can hold braces
                position = text.index('"', position + 1)
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            position += 1
        body = text[start:position - 1]
        total += len(list(ox.parse(io.BytesIO(f"{prefixes}\n{body}".encode()), "application/trig")))
    return total


def iris_in(rows: Iterable[tuple]) -> set[str]:
    """The IRIs (as "<iri>") in the cells of some rows."""
    return {value for row in rows for value in row if isinstance(value, str) and value.startswith("<")}
