"""TRIAD backend: the composition root. Only this file knows the concrete adapters.

Commands:
    python src/backend/main.py init-db    [--db PATH]               create the empty schema
    python src/backend/main.py ensure-db  [--db PATH] [--reset-db]  build and load the database if it is missing
    python src/backend/main.py onboard    [--db PATH]               load the FHIR data into an empty schema
    python src/backend/main.py export-sql [--db PATH] [--out FILE]  write dml/02_insert_seed.sql (the scenario data)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from application.onboarding.import_fhir_source import ImportFhirSource  # noqa: E402
from infrastructure import config  # noqa: E402
from infrastructure.fhir.mappers import FhirOnboardingSource  # noqa: E402
from infrastructure.sqlite.connection import connect  # noqa: E402
from infrastructure.sqlite.onboarding_store import SqliteOnboardingStore  # noqa: E402
from infrastructure.sqlite.schema import ensure_db, init_db  # noqa: E402


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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="TRIAD backend commands")
    parser.add_argument("command", choices=["init-db", "ensure-db", "onboard", "export-sql"])
    parser.add_argument("--db", type=Path, default=config.DB_PATH, help="Path of the SQLite database.")
    parser.add_argument("--reset-db", action="store_true", help="Build the database again (ensure-db).")
    parser.add_argument("--out", type=Path, default=config.DML_DIR / "02_insert_seed.sql",
                        help="Output file of export-sql.")
    args = parser.parse_args(argv)

    if args.command == "init-db":
        conn = connect(args.db)
        init_db(conn)
        print(f"Created the schema in {args.db}.")
    elif args.command == "onboard":
        conn = connect(args.db)
        report = onboard(conn)
        print(json.dumps(report["rows"], indent=1))
    elif args.command == "ensure-db":
        def build(conn: sqlite3.Connection) -> None:
            print("Loading the FHIR data. This takes about one minute ...", flush=True)
            report = onboard(conn)
            print(f"Loaded {report['rows']['Patient']} patients, {report['rows']['Visit']} visits and "
                  f"{report['rows']['Assertion']} assertions in {report['seconds']} s.")
        state = ensure_db(args.db, build, reset=args.reset_db)
        print(f"The database {args.db} is {state}.")
    elif args.command == "export-sql":
        from infrastructure.sqlite.sql_export import export_scenarios
        conn = connect(args.db)
        count = export_scenarios(conn, args.out)
        print(f"Wrote {count} INSERT statements to {args.out}.")


if __name__ == "__main__":
    main()
