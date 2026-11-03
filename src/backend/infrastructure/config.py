"""Paths and settings. Environment variables can change them.

Environment variables:
    TRIAD_DB_PATH    the SQLite database (default: src/backend/data/triad.db); a relative path starts at the repo root
    TRIAD_NOW        the demo time (default: triadNow in hospital_profile.json); "system" uses the computer clock
    TRIAD_LLM        the chat mode: "fake" (default, no network) or "llm" (LiteLLM)
    TRIAD_LLM_MODEL  the LiteLLM model (default: gemini/gemini-3.8-flash)
    PORT             the port of "main.py serve" (default: 8000)
The API key of the LLM provider (for example GEMINI_API_KEY) is also an environment variable.
Only LiteLLM reads it. TRIAD does not keep it in the settings.

The file src/backend/.env can hold these variables (see src/backend/.env.example). main.py loads it
at the start. A variable of the shell wins over the file.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import MutableMapping, Optional

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parents[1]
ENV_FILE = BACKEND_DIR / ".env"   # the local settings and API keys; git ignores it
DATA_DIR = BACKEND_DIR / "data"
SQL_DIR = BACKEND_DIR / "models" / "relational" / "sql"
DDL_DIR = SQL_DIR / "ddl"   # CREATE statements: the schema
DML_DIR = SQL_DIR / "dml"   # INSERT, SELECT, UPDATE and DELETE statements

DEFAULT_DB_PATH = DATA_DIR / "triad.db"
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

DEFAULT_LLM_MODEL = "gemini/gemini-3.8-flash"   # Gemini has a free tier


def load_env_file(path: Path = ENV_FILE, environ: MutableMapping[str, str] = os.environ) -> list[str]:
    """Copy the variables of a .env file into the environment. Return the names that it set.

    A variable that is already set (in the shell) keeps its value. An empty value sets nothing.
    If the file does not exist, nothing changes. Only main.py calls this function, at the start.
    The tests do not call it, so they do not read the .env file of the developer.
    """
    if not Path(path).is_file():
        return []
    try:
        from dotenv import dotenv_values
    except ImportError as error:
        raise SystemExit("python-dotenv is not installed. Run: "
                         "uv pip install --python .venv/bin/python -r requirements.txt") from error
    loaded = []
    for name, value in dotenv_values(path).items():
        if value and name not in environ:
            environ[name] = value
            loaded.append(name)
    return loaded


def env_db_path() -> Path:
    """The database of TRIAD_DB_PATH, or the default. A relative path starts at the root folder of the repo."""
    value = os.environ.get("TRIAD_DB_PATH", "").strip()
    if not value:
        return DEFAULT_DB_PATH
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT_DIR / path


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
            db_path=env_db_path(),
            now=os.environ.get("TRIAD_NOW", "").strip() or profile_now(),
            llm_mode=mode if mode in ("fake", "llm") else "fake",
            llm_model=os.environ.get("TRIAD_LLM_MODEL", "").strip() or DEFAULT_LLM_MODEL,
            frontend_dist=FRONTEND_DIST,
        )
        values.update({k: v for k, v in overrides.items() if v is not None})
        values["db_path"] = Path(values["db_path"])
        return Settings(**values)
