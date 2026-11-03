"""TRIAD backend: the composition root. Only this file knows the concrete adapters.

Commands:
    python src/backend/main.py init-db    [--db PATH]               create the empty schema
    python src/backend/main.py ensure-db  [--db PATH] [--reset-db]  build and load the database if it is missing
    python src/backend/main.py onboard    [--db PATH]               load the FHIR data into an empty schema
    python src/backend/main.py export-sql [--db PATH] [--out FILE]  write dml/02_insert_seed.sql (the scenario data)
    python src/backend/main.py serve      [--db PATH] [--reset-db]  run ensure-db, then serve the API on port 8000

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
    """Wire the concrete adapters to the ports. The API calls the factory once for each request."""
    from application.context import AppContext, Identity
    from infrastructure.clock import DemoClock
    from infrastructure.llm.fake_client import FakeLanguageModel
    from infrastructure.sqlite.chat_repository import SqliteAuditRepository, SqliteChatRepository
    from infrastructure.sqlite.directory_repository import SqliteDirectoryRepository
    from infrastructure.sqlite.patients_repository import SqlitePatientRepository, SqliteVisitRepository
    from infrastructure.sqlite.records_repository import SqliteRecordRepository
    from infrastructure.sqlite.unit_of_work import SqliteUnitOfWork
    from infrastructure.sqlite.users_repository import SqliteUserRepository

    clock = DemoClock(settings.now)
    fake = FakeLanguageModel()
    llm, mode, model = fake, "fake", None
    if settings.llm_mode == "llm":
        from infrastructure.llm import litellm_client
        problem = litellm_client.check_ready(settings.llm_model)
        if problem:   # the sessions then record the mode that really runs
            print(f"TRIAD_LLM=llm, but {problem} The chat uses the fake model.", file=sys.stderr, flush=True)
        else:
            llm, mode, model = litellm_client.LiteLlmLanguageModel(settings.llm_model), "llm", settings.llm_model
    identity = Identity()

    def open_context() -> AppContext:
        conn = connect(settings.db_path)
        return AppContext(
            uow=SqliteUnitOfWork(conn, clock), users=SqliteUserRepository(conn),
            patients=SqlitePatientRepository(conn), visits=SqliteVisitRepository(conn),
            records=SqliteRecordRepository(conn), chat=SqliteChatRepository(conn),
            audit=SqliteAuditRepository(conn), directory=SqliteDirectoryRepository(conn),
            llm=llm, fallback_llm=fake, chat_mode=mode, chat_model=model,
            schema_version=config.SCHEMA_VERSION, identity=identity, close=conn.close, clock_mode=clock.mode)

    return open_context


def create_app(settings: Optional[config.Settings] = None):
    """The FastAPI application (uvicorn main:create_app --factory). The database must exist (ensure-db)."""
    from api.app import build_app

    if settings is None:   # uvicorn --factory (dev.sh). The tests give their own settings.
        config.load_env_file()
        settings = config.Settings.from_env()
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
    return build_app(context_factory(settings), settings.frontend_dist)


def build_database(conn: sqlite3.Connection) -> None:
    print("Loading the FHIR data. This takes some seconds ...", flush=True)
    report = onboard(conn)
    print(f"Loaded {report['rows']['Patient']} patients, {report['rows']['Visit']} visits and "
          f"{report['rows']['Assertion']} assertions in {report['seconds']} s.")


def main(argv: list[str] | None = None) -> None:
    config.load_env_file()
    parser = argparse.ArgumentParser(description="TRIAD backend commands")
    parser.add_argument("command", choices=["init-db", "ensure-db", "onboard", "export-sql", "serve"])
    parser.add_argument("--db", type=Path, default=None,
                        help="Path of the SQLite database (default: TRIAD_DB_PATH or src/backend/data/triad.db).")
    parser.add_argument("--reset-db", action="store_true", help="Build the database again (ensure-db).")
    parser.add_argument("--out", type=Path, default=config.DML_DIR / "02_insert_seed.sql",
                        help="Output file of export-sql.")
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
        port = int(os.environ.get("PORT", "8000"))
        print(f"TRIAD serves on http://127.0.0.1:{port} (API: /api, documentation: /docs).", flush=True)
        uvicorn.run(create_app(config.Settings.from_env(db_path=args.db)), host="127.0.0.1", port=port)
    elif args.command == "export-sql":
        from infrastructure.sqlite.sql_export import export_scenarios
        conn = connect(args.db)
        count = export_scenarios(conn, args.out)
        print(f"Wrote {count} INSERT statements to {args.out}.")


if __name__ == "__main__":
    main()
