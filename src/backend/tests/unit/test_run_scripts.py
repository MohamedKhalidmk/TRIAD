"""The run scripts quickstart.sh and dev.sh: syntax, help and the refusal of a wrong store (no Docker, no server)."""
from __future__ import annotations

import subprocess

import pytest

from infrastructure import config

SCRIPTS = config.ROOT_DIR / "src" / "scripts"
QUICKSTART = SCRIPTS / "quickstart.sh"
DEV = SCRIPTS / "dev.sh"


@pytest.mark.parametrize("script", [QUICKSTART, DEV])
def test_the_script_is_an_executable_bash_script(script):
    assert script.stat().st_mode & 0o111
    subprocess.run(["/bin/bash", "-n", str(script)], check=True)


def test_the_quickstart_help_lists_the_stores_and_the_options():
    result = subprocess.run([str(QUICKSTART), "--help"], check=True, capture_output=True, text=True)
    for word in ("--store", "sqlite", "oxigraph", "virtuoso", "--reset-db", "--reset-kg", "--check", "kg.sh down"):
        assert word in result.stdout


@pytest.mark.parametrize("script", [QUICKSTART, DEV])
def test_an_unknown_store_is_refused(script):
    result = subprocess.run([str(script), "--store", "mysql"], capture_output=True, text=True)
    assert result.returncode == 2
    assert "Unknown store: mysql" in result.stderr


@pytest.mark.parametrize("script", [QUICKSTART, DEV])
def test_an_unknown_option_is_refused(script):
    result = subprocess.run([str(script), "--nothing"], capture_output=True, text=True)
    assert result.returncode == 2
    assert "Unknown option: --nothing" in result.stderr


def test_reset_kg_needs_a_knowledge_graph_store():
    result = subprocess.run([str(QUICKSTART), "--store", "sqlite", "--reset-kg"], capture_output=True, text=True)
    assert result.returncode == 2
