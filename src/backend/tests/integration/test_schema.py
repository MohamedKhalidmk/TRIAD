"""The SQL scripts 01-05 on a new database (the plain sqlite3 path of the course manual)."""
from __future__ import annotations

import re
import shutil
import sqlite3
import subprocess

import pytest

from infrastructure import config
from infrastructure.sqlite.connection import connect
from infrastructure.sqlite.onboarding_store import TABLES


def statements(text: str) -> list[str]:
    """Split a SQL file into complete statements."""
    out, buf = [], ""
    for line in text.splitlines(keepends=True):
        if not buf and line.strip().startswith("--"):
            continue
        buf += line
        if sqlite3.complete_statement(buf):
            out.append(buf.strip())
            buf = ""
    return [s for s in out if s and not s.upper().startswith("PRAGMA")]


def violation_cases() -> list[tuple[str, str, str]]:
    text = (config.SQL_DIR / "05_constraint_violations.sql").read_text(encoding="utf-8")
    parts = re.split(r"^-- CASE: (.+)$", text, flags=re.M)[1:]
    cases = []
    for name, body in zip(parts[0::2], parts[1::2]):
        expect = re.search(r"^-- EXPECT: (.+)$", body, flags=re.M).group(1).strip()
        cases.append((name.strip(), expect, body))
    return cases


def test_01_creates_29_tables_and_the_triggers(scenario_db):
    conn = connect(scenario_db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}
    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
    assert tables == set(TABLES) and len(tables) == 29
    assert len(triggers) == 11
    assert conn.execute("PRAGMA user_version").fetchone()[0] == config.SCHEMA_VERSION


def test_02_fills_all_29_tables(scenario_db):
    conn = connect(scenario_db)
    empty = [t for t in TABLES if conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0]
    assert empty == []
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.skipif(shutil.which("sqlite3") is None, reason="the sqlite3 command-line shell is not installed")
def test_scripts_run_with_the_sqlite3_shell(tmp_path):
    db = tmp_path / "shell.db"
    for name in ("01_create_tables.sql", "02_insert_seed.sql", "03_select_queries.sql"):
        result = subprocess.run(["sqlite3", "-bail", str(db)], input=(config.SQL_DIR / name).read_text(),
                                capture_output=True, text=True)
        assert result.returncode == 0, f"{name}: {result.stderr}"


def test_03_select_queries_run_and_answer_the_slide_question(scenario_db):
    conn = connect(scenario_db)
    results = [conn.execute(sql).fetchall() for sql in statements(
        (config.SQL_DIR / "03_select_queries.sql").read_text(encoding="utf-8"))]
    assert len(results) == 14  # Q1-Q13, with Q9 in two parts
    q3 = results[2]
    assert [tuple(r) for r in q3] == [("No", "Physician", "2026-10-02", "Not allergic. Allergy test negative.")]
    q2 = results[1]
    assert [r["Verification"] for r in q2] == ["Refuted", "Unconfirmed", "Unconfirmed"]


def test_04_update_delete_runs_on_a_copy(scenario_copy):
    conn = connect(scenario_copy)
    conn.executescript((config.SQL_DIR / "04_update_delete.sql").read_text(encoding="utf-8"))
    chain = conn.execute(
        "SELECT a.SupersedesId, a.Statement FROM Assertion a JOIN ClinicalEntry e ON e.Id = a.ClinicalEntryId "
        "WHERE e.IdentifierValue = 'MedicationRequest/mr-elena-amlodipine' ORDER BY a.Id").fetchall()
    assert len(chain) == 2 and chain[1]["SupersedesId"] is not None
    assert conn.execute("SELECT COUNT(*) FROM Location WHERE IdentifierValue = 'STORE-OLD'").fetchone()[0] == 0


@pytest.mark.parametrize("name,expect,body", violation_cases(), ids=[c[0] for c in violation_cases()])
def test_05_each_violation_fails(scenario_copy, name, expect, body):
    conn = connect(scenario_copy)
    with pytest.raises(sqlite3.Error) as error:
        conn.executescript(body)
    assert expect in str(error.value)
