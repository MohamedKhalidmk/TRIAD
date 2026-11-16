"""The adapters of the knowledge-graph build (the ports of application/semantic/build_kg.py).

- SqliteKgSource: the fingerprint (logical_hash.py) and the last ids (sqlite_sequence) of a SQLite database.
- MorphKgcExporter: the export of kg_export.py (Morph-KGC, R2RML). kg_report.json gets the marker.
- OxigraphTripleStore: the embedded store. It loads the files in this process (pyoxigraph bulk load).
- VirtuosoTripleStore: Virtuoso in Docker. It loads the files with "kg.sh load --no-export" (or "--seed"):
  the Virtuoso bulk loader (ld_dir, rdf_loader_run, checkpoint) with the checks of kg.sh (the load list,
  ll_error, the counts per predicate). This is the tested way of plan 4.1; an upload over HTTP of 1.3 million
  triples is much slower. kg.sh needs Docker (or KG_ISQL), and Virtuoso reads only the folders that its
  container mounts: TRIAD_KG_DIR (at /import/kg) and models/semantic (at /import/semantic).
The marker, the counters and the counts go over SPARQL (the client of infrastructure/sparql/client.py), the
same for both stores. They are in the meta graph:
    <KG build-marker> triad:dataHash "..." ; triad:mappingHash "..." ; triad:ontologyVersion "5.0.0" ;
                      triad:scope "all" ; triad:builtAt "..."^^xsd:dateTime .
    <KG counter/assertion> triad:issued 57022 .     (one fact for each class path; see sparql/ids.py)
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional

from application.semantic.build_kg import KgBuildError, KgExport, KgMarker
from infrastructure import config
from infrastructure.rdf import counts, logical_hash
from infrastructure.rdf.namespaces import ABOX_GRAPH, BUILD_MARKER, META_GRAPH, TBOX_GRAPH
from infrastructure.sparql import ids
from infrastructure.sparql.terms import Term, literal
from models.semantic import vocabulary as V

KG_SH = config.ROOT_DIR / "src" / "scripts" / "kg.sh"
OWL_PATH = config.SEMANTIC_DIR / "triad.owl"
SEED_PATH = config.SEMANTIC_DIR / "kg" / "triad_kg_seed.rdf"
NT_FILE = "triad_kg.nt.gz"
REPORT_FILE = "kg_report.json"
GRAPH_IRIS = {"tbox": TBOX_GRAPH, "abox": ABOX_GRAPH, "meta": META_GRAPH}
MARKER = Term(f"<{BUILD_MARKER}>")

MARKER_QUERY = """
SELECT ?dataHash ?mappingHash ?ontologyVersion ?scope FROM $meta WHERE {
  $marker triad:dataHash ?dataHash ; triad:mappingHash ?mappingHash ; triad:ontologyVersion ?ontologyVersion ;
          triad:scope ?scope .
}"""


def marker_dict(marker: KgMarker) -> dict:
    return asdict(marker)


def marker_of(values: Mapping) -> KgMarker:
    return KgMarker(str(values["data_hash"]), str(values["mapping_hash"]), str(values["ontology_version"]),
                    str(values["scope"]))


# ---------------------------------------------------------------------------------------------
# The source and the exporter

class SqliteKgSource:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def fingerprint(self) -> str:
        return logical_hash.logical_hash(self.db_path)

    def sequences(self) -> dict[str, int]:
        return logical_hash.sequences(self.db_path)


class MorphKgcExporter:
    def __init__(self, db_path: Path, out_dir: Path):
        self.db_path = Path(db_path)
        self.out_dir = Path(out_dir)

    def mapping_fingerprint(self) -> tuple[str, str]:
        return logical_hash.mapping_hash(), V.ONTOLOGY_VERSION

    def export(self, scope: str, marker: KgMarker) -> KgExport:
        from infrastructure.rdf.kg_export import ExportError, export_kg
        try:
            report = export_kg(self.db_path, self.out_dir, scope, extra={"marker": marker_dict(marker)})
        except ExportError as error:
            raise KgBuildError(str(error)) from None
        return KgExport(OWL_PATH, self.out_dir / NT_FILE, report["per_predicate"])


def export_of_folder(kg_dir: Path) -> tuple[KgExport, KgMarker]:
    """The export that "main.py export-kg" wrote into a folder, and the marker in its kg_report.json."""
    report_path = Path(kg_dir) / REPORT_FILE
    if not (Path(kg_dir) / NT_FILE).is_file() or not report_path.is_file():
        raise KgBuildError(f"{kg_dir} has no export ({NT_FILE} and {REPORT_FILE}). Run: "
                           "python src/backend/main.py export-kg")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if "marker" not in report:
        raise KgBuildError(f"{report_path} has no marker (an old export). Run: python src/backend/main.py export-kg")
    return KgExport(OWL_PATH, Path(kg_dir) / NT_FILE, report["per_predicate"]), marker_of(report["marker"])


class SeedSource:
    """The scenario data of the SQL scripts 01 and 02: the source of the seed graph models/semantic/kg/.

    The seed graph is the export of this data (a test of test_kg_export.py shows it), so load-kg --seed needs
    no Morph-KGC. The database is made in a temporary folder.
    """

    def __init__(self):
        from infrastructure.rdf.kg_export import scenario_database
        self._folder = tempfile.mkdtemp(prefix="triad-seed-source-")
        self.db_path = scenario_database(Path(self._folder) / "scenario.db")
        self._source = SqliteKgSource(self.db_path)

    def fingerprint(self) -> str:
        return self._source.fingerprint()

    def sequences(self) -> dict[str, int]:
        return self._source.sequences()

    def export(self) -> KgExport:
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            expected = counts.expected_counts(conn)
        finally:
            conn.close()
        return KgExport(OWL_PATH, SEED_PATH, expected["per_predicate"])

    def marker(self) -> KgMarker:
        return KgMarker(self.fingerprint(), logical_hash.mapping_hash(), V.ONTOLOGY_VERSION, "all")

    def close(self) -> None:
        shutil.rmtree(self._folder, ignore_errors=True)


# ---------------------------------------------------------------------------------------------
# The triple stores

class SparqlTripleStore:
    """The parts of a TripleStore that go over SPARQL: the marker, the counters, the counts, clear."""
    name = "SPARQL"

    def __init__(self, client):
        self.client = client

    def marker(self) -> Optional[KgMarker]:
        rows = self.client.select(MARKER_QUERY, {"marker": MARKER})
        if not rows:
            return None
        r = rows[0]
        return KgMarker(r["dataHash"], r["mappingHash"], r["ontologyVersion"], r["scope"])

    def set_marker(self, marker: KgMarker) -> None:
        self.client.update("WITH $meta DELETE { $marker ?p ?o } WHERE { $marker ?p ?o }", {"marker": MARKER})
        built = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        self.client.update(
            "INSERT DATA { GRAPH $meta { $marker triad:dataHash $data ; triad:mappingHash $mapping ; "
            "triad:ontologyVersion $version ; triad:scope $scope ; triad:builtAt $built } }",
            {"marker": MARKER, "data": marker.data_hash, "mapping": marker.mapping_hash,
             "version": marker.ontology_version, "scope": marker.scope, "built": literal(built, "dateTime")})

    def clear(self, graph: str) -> None:
        self.client.update(f"WITH <{GRAPH_IRIS[graph]}> DELETE {{ ?s ?p ?o }} WHERE {{ ?s ?p ?o }}")

    def predicate_counts(self) -> dict[str, int]:
        rows = self.client.select(counts.predicate_count_query(ABOX_GRAPH))
        return {r["p"]: int(r["n"]) for r in rows}

    def seed_counters(self, sequences: Mapping[str, int]) -> dict[str, int]:
        values = ids.seed_values(sequences)
        self.client.update("INSERT DATA { GRAPH $meta { $counters } }",
                           {"counters": Term("\n".join(ids.counter_triples(values)))})
        return values

    def load(self, files: Mapping[str, Path]) -> None:
        raise NotImplementedError

    def forget_state(self) -> None:
        """The data of the store changed: the next write reads the latest time again."""
        from infrastructure.sparql.unit_of_work import StoreState
        StoreState.forget(self.client.key)


class OxigraphTripleStore(SparqlTripleStore):
    name = "Oxigraph"

    def clear(self, graph: str) -> None:
        import pyoxigraph
        self.client.oxigraph.clear_graph(pyoxigraph.NamedNode(GRAPH_IRIS[graph]))

    def load(self, files: Mapping[str, Path]) -> None:
        from infrastructure.rdf import oxigraph_store
        for graph, path in files.items():
            oxigraph_store.load_file(self.client.oxigraph, path, GRAPH_IRIS[graph])
        self.forget_state()


Runner = Callable[..., subprocess.CompletedProcess]


class VirtuosoTripleStore(SparqlTripleStore):
    """Virtuoso: the files load with kg.sh (the bulk loader). See the module text."""
    name = "Virtuoso"

    def __init__(self, client, kg_dir: Path, kg_sh: Path = KG_SH, run: Runner = subprocess.run):
        super().__init__(client)
        self.kg_dir = Path(kg_dir)
        self.kg_sh = Path(kg_sh)
        self.run = run

    def load_command(self, files: Mapping[str, Path]) -> list[str]:
        tbox, abox = Path(files["tbox"]).resolve(), Path(files["abox"]).resolve()
        if tbox != OWL_PATH.resolve():
            raise KgBuildError(f"Virtuoso loads the TBox only from {OWL_PATH} (kg.sh load).")
        if abox == SEED_PATH.resolve():
            return [str(self.kg_sh), "load", "--seed"]
        if abox == (self.kg_dir / NT_FILE).resolve():
            return [str(self.kg_sh), "load", "--no-export"]
        raise KgBuildError(f"Virtuoso loads the ABox only from {self.kg_dir / NT_FILE} or {SEED_PATH}: its "
                           "container mounts only these folders.")

    def load(self, files: Mapping[str, Path]) -> None:
        command = self.load_command(files)
        env = {**os.environ, "TRIAD_KG_DIR": str(self.kg_dir)}
        print(f"Running: ./src/scripts/kg.sh {' '.join(command[1:])}", flush=True)
        result = self.run(command, env=env, cwd=str(config.ROOT_DIR))
        if result.returncode != 0:
            raise KgBuildError(f"kg.sh {' '.join(command[1:])} failed with the exit code {result.returncode} "
                               "(see the messages above).")
        self.forget_state()


def triple_store(settings, client) -> SparqlTripleStore:
    """The TripleStore adapter of TRIAD_STORE (oxigraph or virtuoso)."""
    if settings.store == "oxigraph":
        return OxigraphTripleStore(client)
    if settings.store == "virtuoso":
        return VirtuosoTripleStore(client, settings.kg_dir)
    raise ValueError(f'The store "{settings.store}" is not a knowledge-graph store.')
