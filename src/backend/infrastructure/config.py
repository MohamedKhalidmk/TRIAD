"""Paths and settings. Environment variables can change them.

Environment variables:
    TRIAD_DB_PATH    the SQLite database (default: src/backend/data/triad.db); a relative path starts at the repo root
    TRIAD_NOW        the clock: "system" (default, the computer clock) or a fixed ISO 8601 time,
                     for example 2026-10-30T09:00:00-04:00 (triadNow in hospital_profile.json)
    TRIAD_LLM        the chat mode: "fake" (default, no network) or "llm" (LiteLLM)
    TRIAD_LLM_MODEL  the LiteLLM model (default: gemini/gemini-3.8-flash)
    TRIAD_SQL_LOG    the SQL log of the API: "off", "on" (default: the SQL, the time and the rows) or
                     "params" (also the bound values; they can be patient names and dates of birth)
    PORT             the port of "main.py serve" (default: 8000)

The knowledge graph (Milestone 5; src/scripts/kg.sh starts Virtuoso in Docker):
    TRIAD_STORE              the data store of the API: "sqlite" (default), "virtuoso" or "oxigraph"
    TRIAD_SPARQL_QUERY_URL   the SPARQL query endpoint, no login (default: http://127.0.0.1:8890/sparql)
    TRIAD_SPARQL_UPDATE_URL  the SPARQL update endpoint, digest login (default: http://127.0.0.1:8890/sparql-auth)
    TRIAD_SPARQL_USER        the user of the update endpoint (default: triad)
    TRIAD_SPARQL_PASSWORD    the password of that user (default: triad, a value for local development)
    TRIAD_SPARQL_LOG         the SPARQL log of the API: "off", "on" (default: the query text, the time and the
                             rows) or "params" (also the values; they can be patient names and dates of birth)
    TRIAD_KG_DIR             the knowledge-graph files (default: src/backend/data/kg)
    TRIAD_KG_OXIGRAPH_PATH   the embedded Oxigraph store (default: TRIAD_KG_DIR/oxigraph)
    TRIAD_VIRTUOSO_DBA_PASSWORD  the password of the Virtuoso user dba (default: dba). Only kg.sh uses it.
    KG_HTTP_PORT             the port of Virtuoso on 127.0.0.1 (default: 8890). kg.sh publishes this port,
                             and the default endpoint URLs use it.
A relative path starts at the root folder of the repo.
The API key of the LLM provider (for example GEMINI_API_KEY) is also an environment variable.
Only LiteLLM reads it. TRIAD does not keep it in the settings.

The file src/backend/.env can hold these variables (see src/backend/.env.example). main.py loads it
at the start. A variable of the shell wins over the file.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
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
SEMANTIC_DIR = BACKEND_DIR / "models" / "semantic"   # the ontology, the mapping, the seed graph, the SPARQL scripts
DEFAULT_KG_DIR = DATA_DIR / "kg"                      # the knowledge-graph export; git ignores it

SCHEMA_VERSION = 1

# The identifier systems of the two sources. A resource with no identifier gets
# the key (source system, "ResourceType/id").
SYNTHEA_SYSTEM = "https://github.com/synthetichealth/synthea"
TRIAD_SYSTEM = "https://triad.example/fhir"
CHAT_SESSION_SYSTEM = "https://triad.example/fhir/sid/chat-session"
AUDIT_EVENT_SYSTEM = "https://triad.example/fhir/sid/audit-event"

DEFAULT_LLM_MODEL = "gemini/gemini-3.8-flash"   # Gemini has a free tier
SQL_LOG_MODES = ("off", "on", "params")          # TRIAD_SQL_LOG (infrastructure/sqlite/sql_log.py)

# The knowledge graph (Milestone 5).
STORES = ("sqlite", "virtuoso", "oxigraph")      # TRIAD_STORE
SPARQL_LOG_MODES = ("off", "on", "params")       # TRIAD_SPARQL_LOG
DEFAULT_KG_HTTP_PORT = 8890                      # the HTTP port of Virtuoso (KG_HTTP_PORT)
DEFAULT_SPARQL_USER = "triad"
# Values for local development only: Virtuoso listens on 127.0.0.1, and the data is synthetic.
# A user can change them in src/backend/.env (see .env.example).
DEFAULT_SPARQL_PASSWORD = "triad"
DEFAULT_VIRTUOSO_DBA_PASSWORD = "dba"            # the default of the manual (Conductor: dba / dba)


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


def env_path(name: str, default: Path) -> Path:
    """The path of an environment variable, or the default. A relative path starts at the root folder of the repo."""
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT_DIR / path


def env_db_path() -> Path:
    """The database of TRIAD_DB_PATH, or the default. A relative path starts at the root folder of the repo."""
    return env_path("TRIAD_DB_PATH", DEFAULT_DB_PATH)


def env_kg_dir() -> Path:
    """The folder of the knowledge-graph files (TRIAD_KG_DIR), or src/backend/data/kg."""
    return env_path("TRIAD_KG_DIR", DEFAULT_KG_DIR)


def env_kg_http_port() -> int:
    """The port of Virtuoso on 127.0.0.1 (KG_HTTP_PORT), or 8890. A value that is not a port number stops."""
    value = os.environ.get("KG_HTTP_PORT", "").strip()
    if not value:
        return DEFAULT_KG_HTTP_PORT
    if not value.isdigit() or not 1 <= int(value) <= 65535:
        raise SystemExit(f'KG_HTTP_PORT is "{value}". Use a port number from 1 to 65535.')
    return int(value)


def env_secret(name: str, default: str) -> str:
    """A password of the environment, or the default. Only an empty value gives the default."""
    value = os.environ.get(name, "")
    return value if value.strip() else default


def env_virtuoso_dba_password() -> str:
    """The password of the Virtuoso user dba (TRIAD_VIRTUOSO_DBA_PASSWORD). Only kg.sh uses it."""
    return env_secret("TRIAD_VIRTUOSO_DBA_PASSWORD", DEFAULT_VIRTUOSO_DBA_PASSWORD)


@dataclass(frozen=True)
class Settings:
    db_path: Path
    now: str                      # an ISO 8601 time, or "system"
    llm_mode: str                 # "fake" or "llm"
    llm_model: str
    frontend_dist: Optional[Path]
    sql_log: str = "off"          # "off", "on" or "params". from_env gives "on" if TRIAD_SQL_LOG is not set.
    # The knowledge graph (Milestone 5). The defaults are the values of from_env with no variable set.
    store: str = "sqlite"         # "sqlite", "virtuoso" or "oxigraph"
    sparql_query_url: str = f"http://127.0.0.1:{DEFAULT_KG_HTTP_PORT}/sparql"
    sparql_update_url: str = f"http://127.0.0.1:{DEFAULT_KG_HTTP_PORT}/sparql-auth"
    sparql_user: str = DEFAULT_SPARQL_USER
    sparql_password: str = field(default=DEFAULT_SPARQL_PASSWORD, repr=False)
    kg_dir: Path = DEFAULT_KG_DIR
    kg_oxigraph_path: Path = DEFAULT_KG_DIR / "oxigraph"
    sparql_log: str = "off"       # "off", "on" or "params". from_env gives "on" if TRIAD_SPARQL_LOG is not set.

    @staticmethod
    def from_env(**overrides) -> "Settings":
        mode = os.environ.get("TRIAD_LLM", "fake").strip().lower() or "fake"
        port = env_kg_http_port()
        kg_dir = env_kg_dir()
        values = dict(
            db_path=env_db_path(),
            now=os.environ.get("TRIAD_NOW", "").strip() or "system",
            llm_mode=mode if mode in ("fake", "llm") else "fake",
            llm_model=os.environ.get("TRIAD_LLM_MODEL", "").strip() or DEFAULT_LLM_MODEL,
            frontend_dist=FRONTEND_DIST,
            sql_log=os.environ.get("TRIAD_SQL_LOG", "").strip().lower() or "on",
            store=os.environ.get("TRIAD_STORE", "").strip().lower() or "sqlite",
            sparql_query_url=os.environ.get("TRIAD_SPARQL_QUERY_URL", "").strip()
            or f"http://127.0.0.1:{port}/sparql",
            sparql_update_url=os.environ.get("TRIAD_SPARQL_UPDATE_URL", "").strip()
            or f"http://127.0.0.1:{port}/sparql-auth",
            sparql_user=os.environ.get("TRIAD_SPARQL_USER", "").strip() or DEFAULT_SPARQL_USER,
            sparql_password=env_secret("TRIAD_SPARQL_PASSWORD", DEFAULT_SPARQL_PASSWORD),
            kg_dir=kg_dir,
            kg_oxigraph_path=env_path("TRIAD_KG_OXIGRAPH_PATH", kg_dir / "oxigraph"),
            sparql_log=os.environ.get("TRIAD_SPARQL_LOG", "").strip().lower() or "on",
        )
        values.update({k: v for k, v in overrides.items() if v is not None})
        for name in ("db_path", "kg_dir", "kg_oxigraph_path"):
            values[name] = Path(values[name])
        if values["sql_log"] not in SQL_LOG_MODES:
            raise SystemExit(f'TRIAD_SQL_LOG is "{values["sql_log"]}". Use off, on or params.')
        if values["sparql_log"] not in SPARQL_LOG_MODES:
            raise SystemExit(f'TRIAD_SPARQL_LOG is "{values["sparql_log"]}". Use off, on or params.')
        if values["store"] not in STORES:
            raise SystemExit(f'TRIAD_STORE is "{values["store"]}". Use sqlite, virtuoso or oxigraph.')
        return Settings(**values)
