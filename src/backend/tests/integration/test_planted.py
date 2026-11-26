"""The planted database (tests/fixtures/plant.py): Q4 and the "Patient" author branches of Q1, Q6 and Q12."""
from __future__ import annotations

import re
import sqlite3

from infrastructure import config
from infrastructure.sqlite.connection import connect


def run_query(path, number: str) -> list[sqlite3.Row]:
    """Run query `number` (for example "Q4") of dml/03_select_queries.sql on the database."""
    text = (config.DML_DIR / "03_select_queries.sql").read_text(encoding="utf-8")
    block = re.search(rf"-- {number}\. .*?\n(SELECT|WITH)(.*?);\n", text, re.S)
    sql = block.group(1) + block.group(2)
    conn = connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_q4_gives_the_three_outcomes_on_the_planted_database(planted_db, scenario_db):
    assert run_query(scenario_db, "Q4") == []
    assert {row[0]: row[1] for row in run_query(planted_db, "Q4")} == {"accepted": 1, "open": 3, "revised": 1}


def test_q1_shows_the_patient_as_the_author_of_the_current_penicillin_allergy(planted_db, scenario_db):
    def allergy(path):
        return [row for row in run_query(path, "Q1") if row["Category"] == "Allergy"]
    assert [row["Author"] for row in allergy(scenario_db)] == ["Amara Okafor"]
    (row,) = allergy(planted_db)
    assert row["Author"] == "Patient" and row["Origin"] == "Patient" and row["Intent"] == "Report"
    assert "penicillin tablet" in row["Statement"]


def test_q6_and_q12_show_the_patient_message(planted_db):
    senders = {row["Message"]: row["Sender"] for row in run_query(planted_db, "Q6")}
    assert senders["MSG-ELENA-APP-0002"] == "Patient"
    assert any("penicillin tablet" in row["Statement"] for row in run_query(planted_db, "Q12"))


def test_the_planted_times_have_mixed_offsets_and_milliseconds(planted_db):
    conn = connect(planted_db)
    try:
        times = [r[0] for r in conn.execute("SELECT AssertedAt FROM Assertion WHERE Id > 10 ORDER BY Id")]
        late = conn.execute("SELECT substr(AssertedAt, 1, 10), date(AssertedAt) FROM Assertion "
                            "WHERE AssertedAt = '2026-10-02T21:30:00.100-04:00'").fetchone()
    finally:
        conn.close()
    assert {t[-6:] if t[-1] != "Z" else "Z" for t in times} >= {"-04:00", "-07:00", "+05:30", "Z"}
    assert any(".165" in t for t in times) and any(".100" in t for t in times)
    assert tuple(late) == ("2026-10-02", "2026-10-03")      # the local date and the UTC date differ
