"""Validate a TRIAD graph with the W3C SHACL shapes of the knowledge graph (plan 5, section 3.4).

validate(data, shapes=SHAPES_PATH) runs pyshacl 0.31 on one graph and returns a ShaclResult:
    conforms     True when the graph has no violation;
    violations   a list of Violation(focus, source, message, component, path, value):
                 focus      the IRI of the node that breaks the rule;
                 source     the IRI of the SHACL-SPARQL constraint (for example shape:UK_Patient_Name_DateOfBirth),
                            or else the IRI of the shape (for example shape:Patient-name);
                 message    the sh:message of the rule;
                 component  the SHACL constraint component without "ConstraintComponent", for example "MinCount",
                            "Datatype", "In", "Class" or "SPARQL";
                 path, value  the sh:resultPath ("^" before an inverse path) and the sh:value, or None.
The data is an rdflib Graph or a file: .rdf, .owl, .xml (RDF/XML), .ttl (Turtle) or .nt (N-Triples), also with .gz.

Use it on the seed graph (models/semantic/kg/triad_kg_seed.rdf: 0.2 s) or on another small graph. pyshacl keeps
all of the graph in memory and runs each SPARQL constraint once for each focus node: the full graph (1.3 M triples)
needs about 6 minutes and 3.5 GB. For the full graph, use the SPARQL checks (plan 4.4, 05_constraint_checks.sparql).

pyshacl sends the same SPARQL text for each focus node, and rdflib parses the text each time: on the seed graph
the parser takes 70 % of the time. So validate() gives pyshacl a view of the data that parses each text once.

This module imports rdflib and pyshacl only in the functions that use them, so the SQLite path does not need them.

Usage (from the root folder of the repository):
    PYTHONPATH=src/backend .venv/bin/python -m infrastructure.rdf.shacl [FILE] [--shapes FILE] [--limit N]
FILE is the seed graph if you give no file. The command prints a summary. Its exit code is 0 when the graph
conforms, 1 when it does not conform, and 2 when it cannot run.
"""
from __future__ import annotations

import argparse
import gzip
import sys
import time
import warnings
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, Optional, Union

from infrastructure import config
from infrastructure.rdf.namespaces import KG, TRIAD

if TYPE_CHECKING:   # only for the type hints
    from rdflib import Graph

SHAPES_PATH = config.SEMANTIC_DIR / "shapes" / "triad.shacl.ttl"
SEED_PATH = config.SEMANTIC_DIR / "kg" / "triad_kg_seed.rdf"
SHAPE = "https://github.com/MohamedKhalidmk/TRIAD/shapes/triad#"
SH = "http://www.w3.org/ns/shacl#"

# The rdflib parser of each file suffix (after a ".gz").
FORMATS = {".rdf": "xml", ".owl": "xml", ".xml": "xml", ".ttl": "turtle", ".nt": "nt"}
# The short forms of the IRIs in the summary.
SHORT = {SHAPE: "shape:", TRIAD: "triad:", KG: "kg:", SH: "sh:", "http://www.w3.org/2001/XMLSchema#": "xsd:",
         "http://www.w3.org/1999/02/22-rdf-syntax-ns#": "rdf:"}

GraphSource = Union[str, Path, "Graph"]


class ShaclError(Exception):
    """The validation cannot run: a package is missing, or a file is missing or not valid RDF."""


class Violation(NamedTuple):
    """One validation result. The first three fields are (focus node, source shape or constraint, message)."""
    focus: str
    source: str
    message: str
    component: str
    path: Optional[str] = None
    value: Optional[str] = None


@dataclass
class ShaclResult:
    conforms: bool
    violations: list[Violation] = field(default_factory=list)
    triples: int = 0
    seconds: float = 0.0
    data: str = ""
    shapes: str = ""

    def pairs(self) -> set[tuple[str, str]]:
        """The (focus node, source) pairs of the violations."""
        return {(v.focus, v.source) for v in self.violations}

    def has(self, focus: str, source: str, component: Optional[str] = None) -> bool:
        """True when a violation has this focus node and this source (and this component, if given)."""
        return any(v.focus == focus and v.source == source and (component is None or v.component == component)
                   for v in self.violations)

    def per_source(self) -> Counter:
        return Counter(v.source for v in self.violations)

    def summary(self, limit: int = 20) -> str:
        """A text for people: the totals, the first `limit` violations, and the count of each source."""
        head = (f"SHACL validation of {self.data or 'the graph'} ({self.triples:,} triples) with "
                f"{self.shapes or SHAPES_PATH.name}: {self.seconds:.2f} s.")
        if self.conforms:
            return f"{head}\nThe graph conforms: no violation."
        sources = self.per_source()
        lines = [head, f"The graph does not conform: {_count(len(self.violations), 'violation')} of "
                       f"{_count(len(sources), 'rule')}."]
        for v in sorted(self.violations)[:limit]:
            lines.append(f"  {short(v.focus)}  {short(v.source)} ({v.component})")
            lines.append(f"      {shorten_text(v.message)}")
        if len(self.violations) > limit:
            lines.append(f"  ... and {_count(len(self.violations) - limit, 'more violation')}.")
        lines.append("The violations of each rule:")
        lines += [f"  {count:6,}  {short(source)}" for source, count in sorted(sources.items(),
                                                                                key=lambda i: (-i[1], i[0]))]
        return "\n".join(lines)


def _count(number: int, noun: str) -> str:
    return f"{number:,} {noun}" + ("" if number == 1 else "s")


def short(iri: Optional[str]) -> str:
    """The short form of an IRI, for example kg:patient/1 or shape:Patient-name."""
    if iri is None:
        return "-"
    for namespace, prefix in SHORT.items():
        if iri.startswith(namespace):
            return prefix + iri[len(namespace):]
    return iri


def shorten_text(text: str) -> str:
    """A message with the short form of each KG IRI (pyshacl puts full IRIs for {?value})."""
    return text.replace(KG, "kg:")


# ---------------------------------------------------------------------------------------------
# The packages (lazy imports)

@contextmanager
def _quiet():
    """Hide the DeprecationWarnings of the SPARQL parser of rdflib 7.2 (old pyparsing names; as kg_export)."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"(rdflib|pyparsing)\b")
        yield


def _rdflib():
    try:
        import rdflib
    except ImportError as error:
        raise ShaclError("The validation needs rdflib. Install the KG packages: "
                         "uv pip install --python .venv/bin/python -r requirements-kg.txt") from error
    return rdflib


def _pyshacl():
    try:
        with _quiet():
            import pyshacl
    except ImportError as error:
        raise ShaclError("The validation needs pyshacl. Install the KG packages: "
                         "uv pip install --python .venv/bin/python -r requirements-kg.txt") from error
    return pyshacl


_PREPARED: dict[str, Any] = {}       # SPARQL text -> the parsed query (rdflib prepareQuery)
_GRAPH_CLASS: list[type] = []        # the class of _query_graph_class(), made once


def _query_graph_class() -> type:
    """An rdflib Graph class whose query() parses each SPARQL text only once (see the module text)."""
    if _GRAPH_CLASS:
        return _GRAPH_CLASS[0]
    rdflib = _rdflib()
    with _quiet():
        from rdflib.plugins.sparql import prepareQuery

    class PreparedQueryGraph(rdflib.Graph):
        def query(self, query_object, *args, **kwargs):
            if isinstance(query_object, str) and not args and set(kwargs) <= {"initBindings"}:
                prepared = _PREPARED.get(query_object)
                if prepared is None:
                    with _quiet():
                        prepared = _PREPARED[query_object] = prepareQuery(query_object)
                query_object = prepared
            return super().query(query_object, *args, **kwargs)

    _GRAPH_CLASS.append(PreparedQueryGraph)
    return PreparedQueryGraph


# ---------------------------------------------------------------------------------------------
# The graphs

def _format(path: Path) -> tuple[str, bool]:
    suffixes = [s.lower() for s in path.suffixes]
    compressed = bool(suffixes) and suffixes[-1] == ".gz"
    suffix = suffixes[-2] if compressed and len(suffixes) > 1 else (suffixes[-1] if suffixes else "")
    if suffix not in FORMATS:
        raise ShaclError(f"{path.name}: the file type is not known. Use one of: "
                         f"{', '.join(sorted(FORMATS))} (also with .gz).")
    return FORMATS[suffix], compressed


def load_graph(source: GraphSource) -> "Graph":
    """An rdflib Graph of a file, or the Graph itself."""
    rdflib = _rdflib()
    if isinstance(source, rdflib.Graph):
        return source
    path = Path(source)
    if not path.is_file():
        raise ShaclError(f"The file {path} does not exist.")
    rdf_format, compressed = _format(path)
    graph = _query_graph_class()()
    try:
        if compressed:
            graph.parse(data=gzip.decompress(path.read_bytes()), format=rdf_format)
        else:
            graph.parse(path, format=rdf_format)
    except Exception as error:   # rdflib raises several types for a syntax error
        raise ShaclError(f"{path.name} is not valid RDF: {error}") from error
    return graph


_SHAPES: dict[tuple[str, int], "Graph"] = {}


def load_shapes(shapes: GraphSource = SHAPES_PATH) -> "Graph":
    """The shapes graph. A file is parsed once while it does not change."""
    rdflib = _rdflib()
    if isinstance(shapes, rdflib.Graph):
        return shapes
    path = Path(shapes).resolve()
    if not path.is_file():
        raise ShaclError(f"The shapes file {path} does not exist.")
    key = (str(path), path.stat().st_mtime_ns)
    if key not in _SHAPES:
        _SHAPES.clear()
        _SHAPES[key] = load_graph(path)
    return _SHAPES[key]


def _query_view(graph: "Graph") -> "Graph":
    """A view of the same triples (the same store, no copy) with the query() of _query_graph_class."""
    rdflib = _rdflib()
    cls = _query_graph_class()
    if isinstance(graph, cls) or type(graph) is not rdflib.Graph:
        return graph   # a Dataset or a ConjunctiveGraph goes to pyshacl as it is
    return cls(store=graph.store, identifier=graph.identifier, namespace_manager=graph.namespace_manager)


# ---------------------------------------------------------------------------------------------
# The validation

def _path_text(results: "Graph", node) -> Optional[str]:
    rdflib = _rdflib()
    if node is None:
        return None
    if isinstance(node, rdflib.BNode):
        inverse = results.value(node, rdflib.URIRef(SH + "inversePath"))
        return f"^{inverse}" if inverse is not None else str(node)
    return str(node)


def violations_of(results: "Graph") -> list[Violation]:
    """The violations of a pyshacl results graph, sorted."""
    rdflib = _rdflib()
    sh = rdflib.Namespace(SH)
    found = []
    for r in results.subjects(rdflib.RDF.type, sh.ValidationResult):
        constraint = results.value(r, sh.sourceConstraint)
        shape = results.value(r, sh.sourceShape)
        source = constraint if isinstance(constraint, rdflib.URIRef) else shape
        component = str(results.value(r, sh.sourceConstraintComponent))
        component = component[len(SH):] if component.startswith(SH) else component
        value = results.value(r, sh.value)
        found.append(Violation(
            focus=str(results.value(r, sh.focusNode)),
            source=str(source),
            message=" ".join(sorted(str(m) for m in results.objects(r, sh.resultMessage))),
            component=component.removesuffix("ConstraintComponent"),
            path=_path_text(results, results.value(r, sh.resultPath)),
            value=None if value is None else str(value)))
    return sorted(found)


def validate(data: GraphSource, shapes: GraphSource = SHAPES_PATH) -> ShaclResult:
    """Validate a graph (or a file) with the SHACL shapes. Raise ShaclError if the validation cannot run."""
    started = time.perf_counter()
    with _quiet():
        pyshacl = _pyshacl()
        data_graph = _query_view(load_graph(data))
        shapes_graph = load_shapes(shapes)
        try:
            conforms, results, _ = pyshacl.validate(data_graph, shacl_graph=shapes_graph, inference="none",
                                                    abort_on_first=False, allow_warnings=False, advanced=False)
        except Exception as error:   # pyshacl raises ReportableRuntimeError and others
            raise ShaclError(f"pyshacl stopped: {error}") from error
    return ShaclResult(
        conforms=bool(conforms), violations=violations_of(results), triples=len(data_graph),
        seconds=round(time.perf_counter() - started, 3),
        data=_name(data, "the graph"), shapes=_name(shapes, "the shapes graph"))


def _name(source: GraphSource, default: str) -> str:
    if isinstance(source, (str, Path)):
        path = Path(source)
        try:
            return str(path.resolve().relative_to(config.ROOT_DIR))
        except ValueError:
            return str(path)
    return default


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a TRIAD graph with the SHACL shapes (triad.shacl.ttl).")
    parser.add_argument("file", nargs="?", type=Path, default=SEED_PATH,
                        help="the graph: .rdf, .owl, .xml, .ttl or .nt, also with .gz (default: the seed graph)")
    parser.add_argument("--shapes", type=Path, default=SHAPES_PATH, help="the shapes file (default: %(default)s)")
    parser.add_argument("--limit", type=int, default=20, help="the number of violations to print (default: 20)")
    args = parser.parse_args(argv)
    try:
        result = validate(args.file, args.shapes)
    except ShaclError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(result.summary(args.limit))
    return 0 if result.conforms else 1


if __name__ == "__main__":
    sys.exit(main())
