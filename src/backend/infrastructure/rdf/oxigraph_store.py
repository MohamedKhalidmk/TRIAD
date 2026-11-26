"""The embedded Oxigraph store (pyoxigraph 0.3.22): open, load, count and copy (plan 5, sections 5.2 and 5.6).

One Store object per folder per process. RocksDB locks the folder of an open store, so a second Store(path) in
the same process fails, and a read-only copy does not see the new commits. open_store() thus keeps the Store
objects in a cache, and each caller of the same folder gets the same object.

load_graphs() fills the two named graphs of the knowledge graph:
    the TBox graph   <https://github.com/MohamedKhalidmk/TRIAD/graph/tbox>  from triad.owl (RDF/XML);
    the ABox graph   <https://github.com/MohamedKhalidmk/TRIAD/graph/abox>  from triad_kg.nt.gz (the export) or
                     from an .rdf file (for example the seed graph models/semantic/kg/triad_kg_seed.rdf).
pyoxigraph 0.3 takes MIME types as text (it has no RdfFormat). pyoxigraph is imported only when a function needs it.
"""
from __future__ import annotations

import gzip
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union

from infrastructure import config
from infrastructure.rdf import counts
from infrastructure.rdf.namespaces import ABOX_GRAPH, TBOX_GRAPH

if TYPE_CHECKING:   # only for the type hints
    from pyoxigraph import Store

OWL_PATH = config.SEMANTIC_DIR / "triad.owl"

# The MIME type of each file suffix (after a ".gz").
MIME_TYPES = {".nt": "application/n-triples", ".rdf": "application/rdf+xml", ".owl": "application/rdf+xml",
              ".xml": "application/rdf+xml", ".ttl": "text/turtle"}

_STORES: dict[Path, "Store"] = {}
_LOCK = threading.Lock()

PathLike = Union[str, Path]


def _pyoxigraph():
    try:
        import pyoxigraph
    except ImportError as error:
        raise RuntimeError("The Oxigraph store needs pyoxigraph. Install the KG packages: "
                           "uv pip install --python .venv/bin/python -r requirements-kg.txt") from error
    return pyoxigraph


def _key(path: PathLike) -> Path:
    return Path(path).expanduser().resolve()


def open_store(path: Optional[PathLike]) -> "Store":
    """The Store of a folder: the same object for each call in this process. The folder is made if it is missing.

    With path None, the result is a new store in memory (not in the cache), for example for a test.
    """
    ox = _pyoxigraph()
    if path is None:
        return ox.Store()
    key = _key(path)
    with _LOCK:
        store = _STORES.get(key)
        if store is None:
            key.mkdir(parents=True, exist_ok=True)
            store = ox.Store(str(key))
            _STORES[key] = store
        return store


def close_store(path: PathLike) -> bool:
    """Remove the Store of a folder from the cache, so the folder can open again (for example after a copy).

    pyoxigraph 0.3 has no close(): RocksDB releases the lock of the folder when Python frees the last reference to
    the Store object. So a caller must not keep its own reference. Return True if the folder was in the cache.
    """
    with _LOCK:
        store = _STORES.pop(_key(path), None)
    if store is None:
        return False
    store.flush()
    del store
    return True


def cached_paths() -> list[Path]:
    """The folders of the open stores in the cache."""
    with _LOCK:
        return sorted(_STORES)


def mime_type(path: PathLike) -> tuple[str, bool]:
    """The MIME type of an RDF file and True if gzip compresses it, from its suffixes (.nt.gz, .rdf, .owl, ...)."""
    suffixes = [s.lower() for s in Path(path).suffixes]
    compressed = bool(suffixes) and suffixes[-1] == ".gz"
    if compressed:
        suffixes = suffixes[:-1]
    if not suffixes or suffixes[-1] not in MIME_TYPES:
        raise ValueError(f"{Path(path).name}: use an RDF file with one of the suffixes {', '.join(MIME_TYPES)} "
                         "(and .gz if it is compressed).")
    return MIME_TYPES[suffixes[-1]], compressed


def load_file(store: "Store", path: PathLike, graph: str) -> int:
    """Clear a named graph, then load an RDF file into it (bulk load). Return the triples of the graph."""
    ox = _pyoxigraph()
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"The RDF file {path} does not exist.")
    mime, compressed = mime_type(path)
    name = ox.NamedNode(graph)
    store.clear_graph(name)
    opener = gzip.open if compressed else open
    with opener(path, "rb") as data:
        store.bulk_load(data, mime, to_graph=name)
    store.flush()
    return triple_count(store, graph)


def load_graphs(store: "Store", tbox_file: PathLike = OWL_PATH,
                abox_file: Optional[PathLike] = None) -> dict[str, int]:
    """Load the ontology into the TBox graph and the data into the ABox graph. Each graph is cleared first.

    abox_file: the export (triad_kg.nt.gz) or an RDF/XML file (.rdf, .rdf.gz). With None, only the TBox loads,
    and the ABox graph does not change. Return the triples of each graph: {"tbox": n, "abox": n}.
    """
    result = {"tbox": load_file(store, tbox_file, TBOX_GRAPH)}
    result["abox"] = load_file(store, abox_file, ABOX_GRAPH) if abox_file is not None else triple_count(store)
    return result


def _select(store: "Store", query: str) -> list[tuple[str, int]]:
    return [(row[0].value, int(row[1].value)) for row in store.query(query)]


def triple_count(store: "Store", graph: str = ABOX_GRAPH) -> int:
    """The number of triples in a named graph."""
    rows = list(store.query(f"SELECT (COUNT(*) AS ?n) FROM <{graph}> WHERE {{ ?s ?p ?o }}"))
    return int(rows[0][0].value)


def graph_counts(store: "Store", graph: str = ABOX_GRAPH) -> dict:
    """The counts of a graph with the keys of kg_report.json: total, per_predicate and per_class (full IRIs).

    It runs the same GROUP BY queries as the load check of Virtuoso (counts.py).
    """
    per_predicate = dict(sorted(_select(store, counts.predicate_count_query(graph))))
    per_class = dict(sorted(_select(store, counts.class_count_query(graph))))
    return {"total": sum(per_predicate.values()), "per_predicate": per_predicate, "per_class": per_class}


def backup_store(store: "Store", target: PathLike) -> Path:
    """Copy an on-disk store into a new folder (Store.backup). The copy opens with open_store(target).

    The target folder must not exist. On the same file system, RocksDB uses hard links, so a copy takes some
    milliseconds. A store in memory (open_store(None)) has no backup.
    """
    target = Path(target)
    if target.exists():
        raise FileExistsError(f"The backup folder {target} exists already. Give a new folder.")
    target.parent.mkdir(parents=True, exist_ok=True)
    store.flush()
    store.backup(str(target))
    return target
