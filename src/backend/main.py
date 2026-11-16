"""TRIAD backend: the composition root. Only this file knows the concrete adapters.

Commands:
    python src/backend/main.py init-db    [--db PATH]               create the empty schema
    python src/backend/main.py ensure-db  [--db PATH] [--reset-db]  build and load the database if it is missing
    python src/backend/main.py onboard    [--db PATH]               load the FHIR data into an empty schema
    python src/backend/main.py export-sql [--db PATH] [--out FILE]  write dml/02_insert_seed.sql (the scenario data)
    python src/backend/main.py export-kg  [--db PATH] [--scope all|scenarios] [--out DIR]
                                                                    write the knowledge graph (R2RML, Morph-KGC):
                                                                    triad_kg.nt.gz, triad_kg.rdf.gz, kg_report.json
                                                                    (default DIR: TRIAD_KG_DIR or src/backend/data/kg)
    python src/backend/main.py ensure-kg  [--db PATH] [--store oxigraph|virtuoso] [--reset-kg] [--scope all|scenarios]
                                                                    build the knowledge graph of the store if its
                                                                    marker is not current (plan 3.5): export, load,
                                                                    count check, id counters, marker
    python src/backend/main.py load-kg    [--db PATH] [--store oxigraph|virtuoso] [--seed]
                                                                    load the export of TRIAD_KG_DIR (or the seed
                                                                    graph) with no new export
    python src/backend/main.py validate-kg [--file PATH]            check a graph with the SHACL shapes (default:
                                                                    the seed graph)
    python src/backend/main.py serve      [--db PATH] [--reset-db] [--store sqlite|virtuoso|oxigraph] [--reset-kg]
                                                                    run ensure-db (and ensure-kg for a KG store),
                                                                    then serve the API on port 8000

TRIAD_STORE (or --store) selects the data store of the API: sqlite (the default), virtuoso or oxigraph.
A rebuild of the knowledge graph (ensure-kg) deletes the writes that the app made in the knowledge graph.

The API server can also start with uvicorn (the dev.sh script does this):
    .venv/bin/uvicorn main:create_app --factory --app-dir src/backend

The commands and create_app() first load src/backend/.env (see .env.example). A variable of the shell wins.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from application.onboarding.import_fhir_source import ImportFhirSource  # noqa: E402
from infrastructure import config  # noqa: E402
from infrastructure.fhir.mappers import FhirOnboardingSource  # noqa: E402
from infrastructure.sqlite.connection import connect  # noqa: E402
from infrastructure.sqlite.onboarding_store import SqliteOnboardingStore  # noqa: E402
from infrastructure.sqlite.schema import ensure_db, init_db, schema_version  # noqa: E402


def onboard(conn: sqlite3.Connection, report_path: Path | None = config.ONBOARD_REPORT_PATH) -> dict:
    profile = json.loads(config.PROFILE_PATH.read_text(encoding="utf-8"))
    source = FhirOnboardingSource(config.SYNTHEA_PATH, config.SCENARIOS_PATH, config.DEMO_ACTIVITY_PATH, profile)
    started = time.time()
    report = ImportFhirSource(source, SqliteOnboardingStore(conn), config.SYNTHEA_SYSTEM).run()
    report["seconds"] = round(time.time() - started, 1)
    if report_path:
        stable = {k: v for k, v in report.items() if k != "seconds"}
        report_path.write_text(json.dumps(stable, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def context_factory(settings: config.Settings) -> Callable:
    """Wire the concrete adapters to the ports. The API calls the factory once for each request.

    TRIAD_STORE (settings.store) selects the adapters: sqlite (infrastructure/sqlite/) or a knowledge-graph store
    (infrastructure/sparql/). The KG modules load only for a KG store, so the SQLite path imports no RDF package.
    """
    from application.assistant.rule_model import RuleModel
    from application.context import Identity
    from infrastructure.clock import DemoClock
    from infrastructure.llm.fake_client import FakeLanguageModel

    clock = DemoClock(settings.now)
    fake = FakeLanguageModel(RuleModel())   # the rules select the tool of an "ask" turn
    llm, mode, model = fake, "fake", None
    if settings.llm_mode == "llm":
        from infrastructure.llm import litellm_client
        problem = litellm_client.check_ready(settings.llm_model)
        if problem:   # the sessions then record the mode that really runs
            print(f"TRIAD_LLM=llm, but {problem} The chat uses the fake model.", file=sys.stderr, flush=True)
        else:
            llm, mode, model = litellm_client.LiteLlmLanguageModel(settings.llm_model), "llm", settings.llm_model
    common = dict(llm=llm, fallback_llm=fake, chat_mode=mode, chat_model=model, schema_version=config.SCHEMA_VERSION,
                  identity=Identity(), clock_mode=clock.mode, store=settings.store)
    if settings.store == "sqlite":
        return sqlite_context_factory(settings, clock, common)
    return kg_context_factory(settings, clock, common)


def sqlite_context_factory(settings: config.Settings, clock, common: dict) -> Callable:
    """The SQLite adapters: one connection for each request."""
    from application.context import AppContext
    from infrastructure.sqlite.chat_repository import SqliteAuditRepository, SqliteChatRepository
    from infrastructure.sqlite.directory_repository import SqliteDirectoryRepository
    from infrastructure.sqlite.patients_repository import SqlitePatientRepository, SqliteVisitRepository
    from infrastructure.sqlite.records_repository import SqliteRecordRepository
    from infrastructure.sqlite.sql_log import LoggedConnection
    from infrastructure.sqlite.unit_of_work import SqliteUnitOfWork
    from infrastructure.sqlite.users_repository import SqliteUserRepository

    show_params = settings.sql_log == "params"

    def open_context() -> AppContext:
        conn = connect(settings.db_path)
        if settings.sql_log != "off":   # TRIAD_SQL_LOG: log each statement with its time
            conn = LoggedConnection(conn, show_params)
        return AppContext(
            uow=SqliteUnitOfWork(conn, clock), users=SqliteUserRepository(conn),
            patients=SqlitePatientRepository(conn), visits=SqliteVisitRepository(conn),
            records=SqliteRecordRepository(conn), chat=SqliteChatRepository(conn),
            audit=SqliteAuditRepository(conn), directory=SqliteDirectoryRepository(conn),
            close=conn.close, **common)

    return open_context


def kg_client(settings: config.Settings):
    """The SPARQL client of a knowledge-graph store, with the SPARQL log of TRIAD_SPARQL_LOG."""
    from infrastructure.sparql.client import open_client
    client = open_client(settings)
    if settings.sparql_log != "off":   # TRIAD_SPARQL_LOG: log each request with its time
        from infrastructure.sparql.sparql_log import LoggedSparqlClient
        client = LoggedSparqlClient(client, settings.sparql_log == "params")
    return client


def kg_context_factory(settings: config.Settings, clock, common: dict) -> Callable:
    """The SPARQL adapters: one client for the process (Virtuoso over HTTP, or the shared Oxigraph store)."""
    from application.context import AppContext
    from infrastructure.rdf.kg_store import triple_store
    from infrastructure.sparql.audit_repository import SparqlAuditRepository
    from infrastructure.sparql.chat_repository import SparqlChatRepository
    from infrastructure.sparql.directory_repository import SparqlDirectoryRepository
    from infrastructure.sparql.patients_repository import SparqlPatientRepository
    from infrastructure.sparql.records_repository import SparqlRecordRepository
    from infrastructure.sparql.unit_of_work import KgSession, SparqlUnitOfWork
    from infrastructure.sparql.users_repository import SparqlUserRepository
    from infrastructure.sparql.visits_repository import SparqlVisitRepository

    client = kg_client(settings)
    marker = triple_store(settings, client).marker()
    ontology_version = marker.ontology_version if marker else None

    def open_context() -> AppContext:
        session = KgSession(client)
        return AppContext(
            uow=SparqlUnitOfWork(session, clock), users=SparqlUserRepository(session),
            patients=SparqlPatientRepository(session), visits=SparqlVisitRepository(session),
            records=SparqlRecordRepository(session), chat=SparqlChatRepository(session),
            audit=SparqlAuditRepository(session), directory=SparqlDirectoryRepository(session),
            close=session.close, ontology_version=ontology_version, **common)

    return open_context


def check_sqlite(settings: config.Settings) -> None:
    """The start check of the SQLite store: the database exists and has the schema version of the code."""
    if not settings.db_path.exists():
        raise SystemExit(f"The database {settings.db_path} does not exist. Run: python src/backend/main.py ensure-db")
    version = schema_version(settings.db_path)
    if version != config.SCHEMA_VERSION:
        raise SystemExit(f"The database {settings.db_path} has schema version {version}, not "
                         f"{config.SCHEMA_VERSION}. Run: python src/backend/main.py ensure-db --reset-db")
    conn = connect(settings.db_path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")   # readers do not wait for a writer
    finally:
        conn.close()


def check_kg(settings: config.Settings) -> None:
    """The start check of a knowledge-graph store (plan 5.1): the store has a current build marker.

    The SQLite path checks the schema version instead. The data hash is not checked here: the writes of KG mode do
    not change the SQLite data, so ensure-kg keeps them. "serve --store ..." runs ensure-kg first.
    """
    from infrastructure.rdf.kg_store import triple_store
    from infrastructure.rdf.logical_hash import mapping_hash
    from infrastructure.sparql.client import SparqlStoreError
    from models.semantic.vocabulary import ONTOLOGY_VERSION

    command = f"python src/backend/main.py ensure-kg --store {settings.store}"
    try:
        marker = triple_store(settings, kg_client(settings)).marker()
    except (SparqlStoreError, RuntimeError) as error:
        raise SystemExit(f"The {settings.store} store does not answer: {error}") from None
    if marker is None:
        raise SystemExit(f"The {settings.store} store has no knowledge graph of TRIAD (no build marker). "
                         f"Run: {command}")
    if marker.ontology_version != ONTOLOGY_VERSION or marker.mapping_hash != mapping_hash():
        raise SystemExit(f"The {settings.store} store holds a knowledge graph of another ontology or mapping "
                         f"(ontology version {marker.ontology_version}). Run: {command}")


def create_app(settings: Optional[config.Settings] = None):
    """The FastAPI application (uvicorn main:create_app --factory).

    The store must exist: the database (ensure-db) for TRIAD_STORE=sqlite, the knowledge graph (ensure-kg) else.
    """
    from api.app import build_app
    from infrastructure.sqlite import sql_log

    if settings is None:   # uvicorn --factory (dev.sh). The tests give their own settings.
        config.load_env_file()
        settings = config.Settings.from_env()
    if settings.store == "sqlite":
        check_sqlite(settings)
    else:
        check_kg(settings)
    app = build_app(context_factory(settings), settings.frontend_dist)
    if settings.store == "sqlite" and settings.sql_log != "off":
        sql_log.configure_logger()
        app.add_middleware(sql_log.SqlLogMiddleware, show_query=settings.sql_log == "params")
    elif settings.store != "sqlite" and settings.sparql_log != "off":
        from infrastructure.sparql import sparql_log
        sparql_log.configure_logger()
        app.add_middleware(sql_log.SqlLogMiddleware, **sparql_log.middleware_options(settings.sparql_log == "params"))
    return app


def build_database(conn: sqlite3.Connection) -> None:
    print("Loading the FHIR data. This takes some seconds ...", flush=True)
    report = onboard(conn)
    print(f"Loaded {report['rows']['Patient']} patients, {report['rows']['Visit']} visits and "
          f"{report['rows']['Assertion']} assertions in {report['seconds']} s.")


def kg_settings(store: Optional[str], db_path: Path) -> config.Settings:
    """The settings of a knowledge-graph command: --store, else TRIAD_STORE. The store must be a KG store."""
    settings = config.Settings.from_env(db_path=db_path, store=store)
    if settings.store == "sqlite":
        raise SystemExit("This command needs a knowledge-graph store. Give --store oxigraph or --store virtuoso "
                         "(or set TRIAD_STORE).")
    return settings


def print_build(result, settings: config.Settings) -> None:
    where = settings.kg_oxigraph_path if settings.store == "oxigraph" else settings.sparql_query_url
    if result.state == "current":
        print(f"The knowledge graph of the {settings.store} store ({where}) is current: {result.reason}.")
        return
    print(f"Built the knowledge graph of the {settings.store} store ({where}) in {result.seconds} s "
          f"({result.reason}): {result.triples:,} triples in the ABox graph.")
    print("The counts per predicate equal the export. The id counters and the build marker are in the meta graph.")


def ensure_kg(settings: config.Settings, scope: str = "all", reset: bool = False):
    """ensure-kg (plan 3.5): build the knowledge graph of the store if its marker is not current."""
    from application.semantic.build_kg import KgBuildError
    from application.semantic.build_kg import ensure_kg as ensure
    from infrastructure.rdf.kg_store import MorphKgcExporter, SqliteKgSource, triple_store
    from infrastructure.sparql.client import SparqlStoreError

    store = triple_store(settings, kg_client(settings))
    try:
        return ensure(SqliteKgSource(settings.db_path), MorphKgcExporter(settings.db_path, settings.kg_dir), store,
                      scope=scope, reset=reset)
    except (KgBuildError, SparqlStoreError, RuntimeError, FileNotFoundError) as error:
        raise SystemExit(f"ERROR: {error}") from None


def load_kg(settings: config.Settings, seed: bool = False):
    """load-kg: load the export of TRIAD_KG_DIR (or the seed graph) into the store, with no new export."""
    from application.semantic.build_kg import KgBuildError
    from application.semantic.build_kg import load_kg as load
    from infrastructure.rdf.kg_store import SeedSource, SqliteKgSource, export_of_folder, triple_store
    from infrastructure.sparql.client import SparqlStoreError

    store = triple_store(settings, kg_client(settings))
    try:
        if seed:
            source = SeedSource()
            try:
                return load(source, source.export(), source.marker(), store, "load-kg --seed")
            finally:
                source.close()
        export, marker = export_of_folder(settings.kg_dir)
        return load(SqliteKgSource(settings.db_path), export, marker, store, f"load-kg of {settings.kg_dir}")
    except (KgBuildError, SparqlStoreError, RuntimeError, FileNotFoundError) as error:
        raise SystemExit(f"ERROR: {error}") from None


def validate_kg(path: Optional[Path]) -> int:
    """validate-kg: check a graph with the SHACL shapes (infrastructure/rdf/shacl.py). Return the exit code."""
    from infrastructure.rdf.kg_store import SEED_PATH
    try:
        from infrastructure.rdf import shacl
    except ImportError as error:
        raise SystemExit(f"The SHACL check is not available ({error}). It needs infrastructure/rdf/shacl.py and "
                         "the KG packages (requirements-kg.txt).") from None
    return shacl.main([str(path or SEED_PATH)])


def main(argv: list[str] | None = None) -> None:
    config.load_env_file()
    parser = argparse.ArgumentParser(description="TRIAD backend commands")
    parser.add_argument("command", choices=["init-db", "ensure-db", "onboard", "export-sql", "export-kg", "ensure-kg",
                                            "load-kg", "validate-kg", "serve"])
    parser.add_argument("--db", type=Path, default=None,
                        help="Path of the SQLite database (default: TRIAD_DB_PATH or src/backend/data/triad.db).")
    parser.add_argument("--reset-db", action="store_true", help="Build the database again (ensure-db).")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output file of export-sql (default: dml/02_insert_seed.sql), or output folder of "
                             "export-kg (default: TRIAD_KG_DIR or src/backend/data/kg).")
    parser.add_argument("--scope", choices=["all", "scenarios"], default="all",
                        help="The rows of export-kg and ensure-kg: all rows (default), or only the scenario data.")
    parser.add_argument("--store", choices=list(config.STORES), default=None,
                        help="The data store of serve, ensure-kg and load-kg (default: TRIAD_STORE or sqlite).")
    parser.add_argument("--reset-kg", action="store_true",
                        help="Build the knowledge graph again (ensure-kg, serve). This deletes the writes of KG mode.")
    parser.add_argument("--seed", action="store_true", help="load-kg: load the seed graph models/semantic/kg/.")
    parser.add_argument("--file", type=Path, default=None,
                        help="validate-kg: the RDF file to check (default: the seed graph).")
    args = parser.parse_args(argv)
    args.db = args.db or config.env_db_path()

    if args.command == "init-db":
        conn = connect(args.db)
        init_db(conn)
        print(f"Created the schema in {args.db}.")
    elif args.command == "onboard":
        conn = connect(args.db)
        report = onboard(conn)
        print(json.dumps(report["rows"], indent=1))
    elif args.command == "ensure-db":
        state = ensure_db(args.db, build_database, reset=args.reset_db)
        print(f"The database {args.db} is {state}.")
    elif args.command == "serve":
        import uvicorn
        state = ensure_db(args.db, build_database, reset=args.reset_db)
        print(f"The database {args.db} is {state}.")
        settings = config.Settings.from_env(db_path=args.db, store=args.store)
        if settings.store != "sqlite":
            print_build(ensure_kg(settings, args.scope, args.reset_kg), settings)
        port = int(os.environ.get("PORT", "8000"))
        print(f"TRIAD serves on http://127.0.0.1:{port} (API: /api, documentation: /docs; store: {settings.store}).",
              flush=True)
        uvicorn.run(create_app(settings), host="127.0.0.1", port=port)
    elif args.command == "ensure-kg":
        settings = kg_settings(args.store, args.db)
        state = ensure_db(args.db, build_database, reset=args.reset_db)
        print(f"The database {args.db} is {state}.")
        print_build(ensure_kg(settings, args.scope, args.reset_kg), settings)
    elif args.command == "load-kg":
        settings = kg_settings(args.store, args.db)
        print_build(load_kg(settings, seed=args.seed), settings)
    elif args.command == "validate-kg":
        sys.exit(validate_kg(args.file))
    elif args.command == "export-sql":
        from infrastructure.sqlite.sql_export import export_scenarios
        out = args.out or config.DML_DIR / "02_insert_seed.sql"
        conn = connect(args.db)
        count = export_scenarios(conn, out)
        print(f"Wrote {count} INSERT statements to {out}.")
    elif args.command == "export-kg":
        # The KG packages (morph-kgc, pyoxigraph) load only here, so the other commands do not need them.
        from application.semantic.build_kg import wanted_marker
        from infrastructure.rdf.kg_export import ExportError, export_kg, summary
        from infrastructure.rdf.kg_store import MorphKgcExporter, SqliteKgSource, marker_dict
        out = args.out or config.env_kg_dir()
        print(f"Exporting the knowledge graph of {args.db} (scope: {args.scope}) ...", flush=True)
        try:
            # kg_report.json keeps the build marker of the export, so load-kg can write it into the store.
            marker = wanted_marker(SqliteKgSource(args.db), MorphKgcExporter(args.db, out), args.scope)
            report = export_kg(args.db, out, args.scope, extra={"marker": marker_dict(marker)})
        except (ExportError, FileNotFoundError) as error:
            raise SystemExit(f"ERROR: {error}") from None
        print(f"Wrote {', '.join(report['files'])} and kg_report.json to {out} in {report['seconds']} s.")
        print(f"The knowledge graph has {summary(report)}.")
        print(f"The counts per predicate and per class equal the SQL counts ({len(report['per_predicate'])} "
              f"predicates, {len(report['per_class'])} classes).")


if __name__ == "__main__":
    main()
