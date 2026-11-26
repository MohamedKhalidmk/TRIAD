"""The settings: the .env loader, the defaults, the database path, the knowledge-graph settings and the start
check of the llm mode."""
from __future__ import annotations

import re
import sys
import types

import pytest
from dotenv import dotenv_values

from infrastructure import config
from infrastructure.llm import litellm_client

EXAMPLES = (config.BACKEND_DIR / ".env.example", config.BACKEND_DIR.parent / "frontend" / ".env.example")


def test_the_env_file_sets_only_the_missing_names(tmp_path):
    env = tmp_path / ".env"
    env.write_text("TRIAD_LLM=llm\nGEMINI_API_KEY=\n# a comment\nTRIAD_LLM_MODEL='gemini/gemini-3.5-flash-lite'\n"
                   "TRIAD_NOW=from-the-file\n", encoding="utf-8")
    environ = {"TRIAD_NOW": "from-the-shell"}
    assert config.load_env_file(env, environ) == ["TRIAD_LLM", "TRIAD_LLM_MODEL"]
    assert environ == {"TRIAD_LLM": "llm", "TRIAD_LLM_MODEL": "gemini/gemini-3.5-flash-lite",
                       "TRIAD_NOW": "from-the-shell"}     # the shell wins, and the empty key sets nothing


def test_a_missing_env_file_changes_nothing(tmp_path):
    environ: dict[str, str] = {}
    assert config.load_env_file(tmp_path / "no.env", environ) == []
    assert environ == {}


def test_the_example_files_hold_no_secret_values():
    for path in EXAMPLES:
        values = dotenv_values(path)
        assert values, path
        for name, value in values.items():
            if name.endswith(("_KEY", "_TOKEN", "_SECRET")):
                assert not value, f"{path.name} gives a value to {name}"


def test_the_backend_example_gives_the_defaults():
    values = dotenv_values(EXAMPLES[0])
    assert values["TRIAD_LLM"] == "fake"
    assert values["TRIAD_LLM_MODEL"] == config.DEFAULT_LLM_MODEL
    assert "GEMINI_API_KEY" in values
    assert "TRIAD_NOW" not in values                  # a comment only, so the default (system) stays
    assert values["TRIAD_SQL_LOG"] == "on"


def test_the_clock_is_the_system_clock_by_default(monkeypatch):
    monkeypatch.delenv("TRIAD_NOW", raising=False)
    assert config.Settings.from_env().now == "system"
    monkeypatch.setenv("TRIAD_NOW", "")
    assert config.Settings.from_env().now == "system"
    monkeypatch.setenv("TRIAD_NOW", "2026-10-30T09:00:00-04:00")
    assert config.Settings.from_env().now == "2026-10-30T09:00:00-04:00"
    assert config.Settings.from_env(now="2026-01-01T08:00:00-05:00").now == "2026-01-01T08:00:00-05:00"


def test_the_sql_log_setting(monkeypatch, tmp_path):
    monkeypatch.delenv("TRIAD_SQL_LOG", raising=False)
    assert config.Settings.from_env().sql_log == "on"
    monkeypatch.setenv("TRIAD_SQL_LOG", " Params ")
    assert config.Settings.from_env().sql_log == "params"
    assert config.Settings.from_env(sql_log="off").sql_log == "off"
    monkeypatch.setenv("TRIAD_SQL_LOG", "yes")
    with pytest.raises(SystemExit, match='TRIAD_SQL_LOG is "yes". Use off, on or params.'):
        config.Settings.from_env()
    direct = config.Settings(db_path=tmp_path / "a.db", now="system", llm_mode="fake", llm_model="m",
                             frontend_dist=None)
    assert direct.sql_log == "off"                     # code that makes its own Settings logs nothing


def test_a_relative_db_path_starts_at_the_repo_root(monkeypatch, tmp_path):
    monkeypatch.setenv("TRIAD_DB_PATH", "x/y.db")
    assert config.env_db_path() == config.ROOT_DIR / "x" / "y.db"
    monkeypatch.setenv("TRIAD_DB_PATH", str(tmp_path / "a.db"))
    assert config.env_db_path() == tmp_path / "a.db"
    monkeypatch.delenv("TRIAD_DB_PATH")
    assert config.env_db_path() == config.DEFAULT_DB_PATH


KG_VARIABLES = ("TRIAD_STORE", "TRIAD_SPARQL_QUERY_URL", "TRIAD_SPARQL_UPDATE_URL", "TRIAD_SPARQL_USER",
                "TRIAD_SPARQL_PASSWORD", "TRIAD_SPARQL_LOG", "TRIAD_KG_DIR", "TRIAD_KG_OXIGRAPH_PATH",
                "TRIAD_VIRTUOSO_DBA_PASSWORD", "KG_HTTP_PORT")


@pytest.fixture
def no_kg_env(monkeypatch):
    for name in KG_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_the_knowledge_graph_settings_have_safe_defaults(no_kg_env, tmp_path):
    settings = config.Settings.from_env()
    assert settings.store == "sqlite"                  # the Milestone 4 app, also for an old .env
    assert settings.sparql_query_url == "http://127.0.0.1:8890/sparql"
    assert settings.sparql_update_url == "http://127.0.0.1:8890/sparql-auth"
    assert (settings.sparql_user, settings.sparql_password) == ("triad", "triad")
    assert settings.sparql_log == "on"
    assert settings.kg_dir == config.BACKEND_DIR / "data" / "kg"
    assert settings.kg_oxigraph_path == config.BACKEND_DIR / "data" / "kg" / "oxigraph"
    assert config.env_kg_http_port() == 8890
    assert config.env_virtuoso_dba_password() == "dba"
    direct = config.Settings(db_path=tmp_path / "a.db", now="system", llm_mode="fake", llm_model="m",
                             frontend_dist=None)
    assert (direct.store, direct.sparql_log) == ("sqlite", "off")
    assert (direct.sparql_query_url, direct.sparql_update_url) == (settings.sparql_query_url,
                                                                   settings.sparql_update_url)
    assert (direct.kg_dir, direct.kg_oxigraph_path) == (settings.kg_dir, settings.kg_oxigraph_path)


def test_the_store_setting(no_kg_env):
    no_kg_env.setenv("TRIAD_STORE", " Virtuoso ")
    assert config.Settings.from_env().store == "virtuoso"
    no_kg_env.setenv("TRIAD_STORE", "oxigraph")
    assert config.Settings.from_env().store == "oxigraph"
    assert config.Settings.from_env(store="sqlite").store == "sqlite"
    no_kg_env.setenv("TRIAD_STORE", "neo4j")
    with pytest.raises(SystemExit, match='TRIAD_STORE is "neo4j". Use sqlite, virtuoso or oxigraph.'):
        config.Settings.from_env()
    no_kg_env.delenv("TRIAD_STORE")
    with pytest.raises(SystemExit, match="TRIAD_STORE"):
        config.Settings.from_env(store="graphdb")


def test_the_port_of_virtuoso_gives_the_default_endpoints(no_kg_env):
    no_kg_env.setenv("KG_HTTP_PORT", "18890")
    settings = config.Settings.from_env()
    assert settings.sparql_query_url == "http://127.0.0.1:18890/sparql"
    assert settings.sparql_update_url == "http://127.0.0.1:18890/sparql-auth"
    no_kg_env.setenv("TRIAD_SPARQL_QUERY_URL", " http://kg.test:9999/sparql ")
    settings = config.Settings.from_env()
    assert settings.sparql_query_url == "http://kg.test:9999/sparql"     # a URL that is set wins
    assert settings.sparql_update_url == "http://127.0.0.1:18890/sparql-auth"
    for bad in ("abc", "0", "70000", "-1", "88.5"):
        no_kg_env.setenv("KG_HTTP_PORT", bad)
        with pytest.raises(SystemExit, match=f'KG_HTTP_PORT is "{bad}". Use a port number from 1 to 65535.'):
            config.Settings.from_env()


def test_the_sparql_log_setting(no_kg_env):
    no_kg_env.setenv("TRIAD_SPARQL_LOG", " Params ")
    assert config.Settings.from_env().sparql_log == "params"
    assert config.Settings.from_env(sparql_log="off").sparql_log == "off"
    no_kg_env.setenv("TRIAD_SPARQL_LOG", "yes")
    with pytest.raises(SystemExit, match='TRIAD_SPARQL_LOG is "yes". Use off, on or params.'):
        config.Settings.from_env()


def test_the_kg_paths_start_at_the_repo_root(no_kg_env, tmp_path):
    no_kg_env.setenv("TRIAD_KG_DIR", "x/kg")
    settings = config.Settings.from_env()
    assert settings.kg_dir == config.ROOT_DIR / "x" / "kg"
    assert settings.kg_oxigraph_path == config.ROOT_DIR / "x" / "kg" / "oxigraph"   # it follows TRIAD_KG_DIR
    no_kg_env.setenv("TRIAD_KG_OXIGRAPH_PATH", str(tmp_path / "store"))
    assert config.Settings.from_env().kg_oxigraph_path == tmp_path / "store"
    assert config.Settings.from_env(kg_dir=str(tmp_path)).kg_dir == tmp_path      # an override becomes a Path


def test_the_passwords_and_the_user(no_kg_env):
    no_kg_env.setenv("TRIAD_SPARQL_USER", " app ")
    no_kg_env.setenv("TRIAD_SPARQL_PASSWORD", "s3cret pass")
    no_kg_env.setenv("TRIAD_VIRTUOSO_DBA_PASSWORD", "other")
    settings = config.Settings.from_env()
    assert (settings.sparql_user, settings.sparql_password) == ("app", "s3cret pass")
    assert config.env_virtuoso_dba_password() == "other"
    assert "s3cret" not in repr(settings)                 # a log of the settings does not show the password
    no_kg_env.setenv("TRIAD_SPARQL_PASSWORD", " ")
    no_kg_env.setenv("TRIAD_VIRTUOSO_DBA_PASSWORD", "")
    assert config.Settings.from_env().sparql_password == config.DEFAULT_SPARQL_PASSWORD
    assert config.env_virtuoso_dba_password() == config.DEFAULT_VIRTUOSO_DBA_PASSWORD


def test_the_backend_example_shows_the_kg_defaults_as_comments(no_kg_env):
    text = EXAMPLES[0].read_text(encoding="utf-8")
    values = dotenv_values(EXAMPLES[0])
    shown = dict(re.findall(r"^# ((?:TRIAD|KG)_[A-Z_]+)=(.*)$", text, flags=re.MULTILINE))
    assert set(shown) >= set(KG_VARIABLES)
    assert not set(KG_VARIABLES) & set(values)          # comments only, so the defaults of the code stay
    settings = config.Settings.from_env()
    assert shown["TRIAD_STORE"] == settings.store
    assert shown["TRIAD_SPARQL_QUERY_URL"] == settings.sparql_query_url
    assert shown["TRIAD_SPARQL_UPDATE_URL"] == settings.sparql_update_url
    assert shown["TRIAD_SPARQL_USER"] == settings.sparql_user
    assert shown["TRIAD_SPARQL_PASSWORD"] == settings.sparql_password
    assert shown["TRIAD_SPARQL_LOG"] == settings.sparql_log
    assert config.ROOT_DIR / shown["TRIAD_KG_DIR"] == settings.kg_dir
    assert config.ROOT_DIR / shown["TRIAD_KG_OXIGRAPH_PATH"] == settings.kg_oxigraph_path
    assert shown["TRIAD_VIRTUOSO_DBA_PASSWORD"] == config.env_virtuoso_dba_password()
    assert shown["KG_HTTP_PORT"] == str(config.env_kg_http_port())


def fake_litellm(found: dict) -> types.ModuleType:
    module = types.ModuleType("litellm")
    module.validate_environment = lambda model: found
    return module


def test_the_start_check_names_the_missing_key_variables(monkeypatch):
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm(
        {"keys_in_environment": False, "missing_keys": ["GOOGLE_API_KEY", "GEMINI_API_KEY"]}))
    problem = litellm_client.check_ready("gemini/gemini-3.8-flash")
    assert "GOOGLE_API_KEY, GEMINI_API_KEY" in problem and "src/backend/.env" in problem


def test_the_start_check_passes_when_the_key_is_set(monkeypatch):
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm({"keys_in_environment": True, "missing_keys": []}))
    assert litellm_client.check_ready("gemini/gemini-3.8-flash") is None


def test_the_start_check_needs_a_model_that_can_call_tools(monkeypatch):
    module = fake_litellm({"keys_in_environment": True, "missing_keys": []})
    module.supports_function_calling = lambda model: False
    monkeypatch.setitem(sys.modules, "litellm", module)
    problem = litellm_client.check_ready("some/old-model")
    assert "some/old-model cannot call tools" in problem and "TRIAD_LLM_MODEL" in problem


def test_an_error_of_the_tool_check_does_not_stop_the_llm_mode(monkeypatch):
    module = fake_litellm({"keys_in_environment": True, "missing_keys": []})

    def unknown(model):
        raise ValueError("This model is not in the model list.")
    module.supports_function_calling = unknown
    monkeypatch.setitem(sys.modules, "litellm", module)
    assert litellm_client.check_ready("gemini/gemini-3.8-flash") is None


def test_the_start_check_needs_litellm(monkeypatch):
    monkeypatch.setitem(sys.modules, "litellm", None)       # "import litellm" then raises ImportError
    assert "litellm is not installed" in litellm_client.check_ready("gemini/gemini-3.8-flash")
