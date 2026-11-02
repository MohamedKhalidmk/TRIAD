"""Paths and settings. Environment variables can change them.

Environment variables:
    TRIAD_DB_PATH    the SQLite database (default: src/backend/data/triad.db)
    TRIAD_NOW        the demo time (default: triadNow in hospital_profile.json); "system" uses the computer clock
    TRIAD_LLM        the chat mode: "fake" (default, no network) or "llm" (LiteLLM)
    TRIAD_LLM_MODEL  the LiteLLM model (default: anthropic/claude-opus-5-5)
    PORT             the port of "main.py serve" (default: 8000)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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
FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"

SCHEMA_VERSION = 1

# The identifier systems of the two sources. A resource with no identifier gets
# the key (source system, "ResourceType/id").
SYNTHEA_SYSTEM = "https://github.com/synthetichealth/synthea"
TRIAD_SYSTEM = "https://triad.example/fhir"
CHAT_SESSION_SYSTEM = "https://triad.example/fhir/sid/chat-session"
AUDIT_EVENT_SYSTEM = "https://triad.example/fhir/sid/audit-event"

DEFAULT_LLM_MODEL = "anthropic/claude-opus-5-5"


def profile_now() -> str:
    """The demo time of the hospital profile (triadNow)."""
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))["triadNow"]


@dataclass(frozen=True)
class Settings:
    db_path: Path
    now: str                      # an ISO 8601 time, or "system"
    llm_mode: str                 # "fake" or "llm"
    llm_model: str
    frontend_dist: Optional[Path]

    @staticmethod
    def from_env(**overrides) -> "Settings":
        mode = os.environ.get("TRIAD_LLM", "fake").strip().lower() or "fake"
        values = dict(
            db_path=Path(os.environ.get("TRIAD_DB_PATH", DATA_DIR / "triad.db")),
            now=os.environ.get("TRIAD_NOW", "").strip() or profile_now(),
            llm_mode=mode if mode in ("fake", "llm") else "fake",
            llm_model=os.environ.get("TRIAD_LLM_MODEL", "").strip() or DEFAULT_LLM_MODEL,
            frontend_dist=FRONTEND_DIST,
        )
        values.update({k: v for k, v in overrides.items() if v is not None})
        values["db_path"] = Path(values["db_path"])
        return Settings(**values)
