"""The knowledge-graph build: make the graph of a store equal to the export of the relational data (plan 3.5).

ensure_kg() is the use case of "main.py ensure-kg" (and of "main.py serve --store oxigraph|virtuoso"):
- The marker of a store holds the SHA-256 of a logical dump of the SQLite data (the rows of the tables in a fixed
  order, not the file), the SHA-256 of the R2RML mapping, the ontology version and the scope. The file hash would
  change when only the journal mode changes (serve sets WAL), and a false rebuild deletes the writes of KG mode.
- If the marker of the store equals the current values, ensure_kg does nothing.
- If not (or with reset), it exports the data (KgExporter), clears the meta graph (so a stop during the build
  leaves no marker, and the next run builds again), loads the TBox and the ABox graphs, checks the triples per
  predicate, seeds the id counters from sqlite_sequence, and writes the marker last.
- A rebuild deletes the writes that the app made in KG mode. The README says so.
load_kg() is the second half (load, check, counters, marker) for files that exist already ("main.py load-kg").

The ports are below. The adapters are in infrastructure/rdf/kg_store.py; main.py connects them.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Protocol


@dataclass(frozen=True)
class KgMarker:
    data_hash: str          # SHA-256 of the logical dump of the SQLite data
    mapping_hash: str       # SHA-256 of models/semantic/mapping/triad.r2rml.ttl
    ontology_version: str   # owl:versionInfo of the ontology, for example 5.0.0
    scope: str              # the scope of the export: all or scenarios


@dataclass(frozen=True)
class KgExport:
    """The files of one export and the triples per predicate of the ABox file (full IRIs)."""
    tbox_file: Path
    abox_file: Path
    per_predicate: Mapping[str, int]


@dataclass
class KgBuildResult:
    state: str                       # "current" (no change) or "built"
    marker: KgMarker
    reason: str                      # why the build ran, or why it did not run
    triples: int = 0                 # the triples of the ABox graph (0 when nothing changed)
    seconds: float = 0.0
    counters: dict = field(default_factory=dict)


class KgBuildError(Exception):
    """The build cannot run, or the store does not hold the triples of the export."""


class KgSource(Protocol):
    """The relational data: its fingerprint and the last ids of its tables."""

    def fingerprint(self) -> str: ...
    def sequences(self) -> dict[str, int]: ...      # table name -> the last id (sqlite_sequence)


class KgExporter(Protocol):
    def mapping_fingerprint(self) -> tuple[str, str]: ...                  # (mapping hash, ontology version)
    def export(self, scope: str, marker: KgMarker) -> KgExport: ...


class TripleStore(Protocol):
    name: str

    def marker(self) -> Optional[KgMarker]: ...
    def set_marker(self, marker: KgMarker) -> None: ...
    def clear(self, graph: str) -> None: ...                               # graph: "tbox", "abox" or "meta"
    def load(self, files: Mapping[str, Path]) -> None: ...                 # {"tbox": file, "abox": file}
    def predicate_counts(self) -> dict[str, int]: ...                      # the ABox graph
    def seed_counters(self, sequences: Mapping[str, int]) -> dict: ...


def wanted_marker(source: KgSource, exporter: KgExporter, scope: str) -> KgMarker:
    mapping_hash, ontology_version = exporter.mapping_fingerprint()
    return KgMarker(source.fingerprint(), mapping_hash, ontology_version, scope)


def why_build(found: Optional[KgMarker], wanted: KgMarker) -> Optional[str]:
    """The reason for a build, or None if the marker of the store is current."""
    if found is None:
        return "the store has no build marker"
    reasons = [text for differs, text in (
        (found.data_hash != wanted.data_hash, "the relational data changed"),
        (found.mapping_hash != wanted.mapping_hash, "the R2RML mapping changed"),
        (found.ontology_version != wanted.ontology_version,
         f"the ontology version changed ({found.ontology_version} -> {wanted.ontology_version})"),
        (found.scope != wanted.scope, f"the scope changed ({found.scope} -> {wanted.scope})")) if differs]
    return ", ".join(reasons) or None


def count_differences(expected: Mapping[str, int], found: Mapping[str, int]) -> list[str]:
    return [f"{iri}: the export {expected.get(iri, 0)}, the store {found.get(iri, 0)}"
            for iri in sorted(set(expected) | set(found)) if expected.get(iri, 0) != found.get(iri, 0)]


def load_kg(source: KgSource, export: KgExport, marker: KgMarker, store: TripleStore,
            reason: str = "load-kg") -> KgBuildResult:
    """Load the files of an export, check the counts, seed the counters, then write the marker (last)."""
    started = time.perf_counter()
    store.clear("meta")
    store.load({"tbox": export.tbox_file, "abox": export.abox_file})
    found = store.predicate_counts()
    problems = count_differences(export.per_predicate, found)
    if problems:
        raise KgBuildError(f"The {store.name} store does not hold the triples of the export:\n    "
                           + "\n    ".join(problems[:20]))
    counters = store.seed_counters(source.sequences())
    store.set_marker(marker)
    return KgBuildResult("built", marker, reason, sum(found.values()), round(time.perf_counter() - started, 2),
                         dict(counters))


def ensure_kg(source: KgSource, exporter: KgExporter, store: TripleStore, scope: str = "all",
              reset: bool = False) -> KgBuildResult:
    """Build the knowledge graph of the store if its marker is not current (or if `reset`)."""
    started = time.perf_counter()
    wanted = wanted_marker(source, exporter, scope)
    reason = "--reset-kg" if reset else why_build(store.marker(), wanted)
    if reason is None:
        return KgBuildResult("current", wanted, "the marker equals the data, the mapping and the ontology")
    export = exporter.export(scope, wanted)
    result = load_kg(source, export, wanted, store, reason)
    result.seconds = round(time.perf_counter() - started, 2)
    return result
