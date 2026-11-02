"""Paths and settings. Environment variables can change them."""
from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_DIR / "data"
SQL_DIR = BACKEND_DIR / "models" / "relational" / "sql"
DDL_DIR = SQL_DIR / "ddl"   # CREATE statements: the schema
DML_DIR = SQL_DIR / "dml"   # INSERT, SELECT, UPDATE and DELETE statements

DB_PATH = Path(os.environ.get("TRIAD_DB_PATH", DATA_DIR / "triad.db"))
SYNTHEA_PATH = DATA_DIR / "preprocessed" / "synthea_r4.ndjson.gz"
SCENARIOS_PATH = DATA_DIR / "raw" / "triad_scenarios.fhir.json"
DEMO_ACTIVITY_PATH = DATA_DIR / "raw" / "demo_activity.json"
PROFILE_PATH = DATA_DIR / "raw" / "hospital_profile.json"
ONBOARD_REPORT_PATH = DATA_DIR / "preprocessed" / "onboard_report.json"

SCHEMA_VERSION = 1

# The identifier systems of the two sources. A resource with no identifier gets
# the key (source system, "ResourceType/id").
SYNTHEA_SYSTEM = "https://github.com/synthetichealth/synthea"
TRIAD_SYSTEM = "https://triad.example/fhir"
CHAT_SESSION_SYSTEM = "https://triad.example/fhir/sid/chat-session"
AUDIT_EVENT_SYSTEM = "https://triad.example/fhir/sid/audit-event"
