"""The settings: the .env loader, the defaults, the database path and the start check of the llm mode."""
from __future__ import annotations

import sys
import types

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


def test_the_clock_is_the_system_clock_by_default(monkeypatch):
    monkeypatch.delenv("TRIAD_NOW", raising=False)
    assert config.Settings.from_env().now == "system"
    monkeypatch.setenv("TRIAD_NOW", "")
    assert config.Settings.from_env().now == "system"
    monkeypatch.setenv("TRIAD_NOW", "2026-10-30T09:00:00-04:00")
    assert config.Settings.from_env().now == "2026-10-30T09:00:00-04:00"
    assert config.Settings.from_env(now="2026-01-01T08:00:00-05:00").now == "2026-01-01T08:00:00-05:00"


def test_a_relative_db_path_starts_at_the_repo_root(monkeypatch, tmp_path):
    monkeypatch.setenv("TRIAD_DB_PATH", "x/y.db")
    assert config.env_db_path() == config.ROOT_DIR / "x" / "y.db"
    monkeypatch.setenv("TRIAD_DB_PATH", str(tmp_path / "a.db"))
    assert config.env_db_path() == tmp_path / "a.db"
    monkeypatch.delenv("TRIAD_DB_PATH")
    assert config.env_db_path() == config.DEFAULT_DB_PATH


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


def test_the_start_check_needs_litellm(monkeypatch):
    monkeypatch.setitem(sys.modules, "litellm", None)       # "import litellm" then raises ImportError
    assert "litellm is not installed" in litellm_client.check_ready("gemini/gemini-3.8-flash")
