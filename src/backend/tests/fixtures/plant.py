"""A planted test database: the scenario data plus rows that the scenario data does not have.

`plant(db_path)` adds the rows with plain SQL inserts. The constraints and the triggers of
`01_create_tables.sql` stay on, so each row must be correct. It adds, for the patient Elena Marsh:

- 5 nurse recommendations (Assertion.Intent = 'Recommendation'). For Q4 of `03_select_queries.sql`:
  3 are "open" (nothing supersedes them), 1 is "accepted" (a doctor decision, Confirmed, on the same entry
  supersedes it) and 1 is "revised" (a doctor decision, Refuted, supersedes it).
- 1 patient message with no issuer (StaffId NULL, Origin 'Patient'). Its assertion supersedes the current
  penicillin-allergy assertion. So the "Patient" author branches of Q1, Q6 and Q12 give a row.
- Times with mixed offsets (-04:00, -07:00, +05:30, Z) and with milliseconds (.165, .100).
  One time has the local date 2026-10-02 and the UTC date 2026-10-03.

By default, `plant` first runs `04_update_delete.sql` on the database (the plan of Milestone 5).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from infrastructure import config
from infrastructure.sqlite.connection import connect

FHIR = "https://triad.example/fhir"
MESSAGE_SYSTEM = "https://triad.example/fhir/sid/message"
EMPLOYEE_SYSTEM = "https://triad.example/fhir/sid/employee"
VISIT = "ENC-ELENA-2026-10-02"
PENICILLIN = "AllergyIntolerance/ai-elena-penicillin"

# (number, nurse, time of the recommendation, doctor reply or None)
# A reply is (Verification, time). The doctor is E1005. The reply is always later than the recommendation.
RECOMMENDATIONS = [
    (1, "E1004", "2026-10-02T11:45:10.165-04:00", None),                        # open
    (2, "E1002", "2026-10-02T09:20:00.100-07:00", None),                        # open
    (3, "E1003", "2026-10-03T01:10:00+05:30", ("Confirmed", "2026-10-02T16:05:30.250-04:00")),   # accepted
    (4, "E1004", "2026-10-02T20:15:00Z", ("Refuted", "2026-10-02T14:30:45.165-07:00")),          # revised
    (5, "E1002", "2026-10-02T21:30:00.100-04:00", None),                        # open (UTC date 2026-10-03)
]
DISPLAYS = {
    1: "Elevated blood pressure on arrival",
    2: "Dizziness after standing",
    3: "Poor sleep for two weeks",
    4: "Ankle swelling",
    5: "Missed doses of amlodipine",
}
PATIENT_MESSAGE = ("MSG-ELENA-APP-0002", "2026-10-30T07:45:12.100-07:00",
                   "I had a skin rash after a penicillin tablet last week.")


def plant(db_path: Path | str, apply_update_delete: bool = True) -> None:
    """Add the planted rows to the database at `db_path`. It works on a copy: it changes the file."""
    conn = connect(db_path)
    try:
        if apply_update_delete:
            conn.executescript((config.DML_DIR / "04_update_delete.sql").read_text(encoding="utf-8"))
            conn.commit()
        for number, nurse, at, reply in RECOMMENDATIONS:
            entry = add_entry(conn, number, at)
            first = add_assertion(conn, f"MSG-PLANT-REC-{number}", nurse, "InPerson", "Staff", at, entry, None,
                                  "Recommendation", "Unconfirmed", f"Recommend a check: {DISPLAYS[number].lower()}.")
            if reply:
                verification, reply_at = reply
                add_assertion(conn, f"MSG-PLANT-DEC-{number}", "E1005", "InPerson", "Staff", reply_at, entry, first,
                              "Decision", verification,
                              "Doctor accepts the recommendation." if verification == "Confirmed"
                              else "Doctor does not accept the recommendation.")
        add_patient_message(conn)
        conn.commit()
    finally:
        conn.close()


def add_entry(conn: sqlite3.Connection, number: int, at: str) -> int:
    """A new Diagnosis entry in the visit of 2026-10-02 of Elena (the entry and its subtype row)."""
    visit = conn.execute("SELECT Id FROM Visit WHERE IdentifierValue = ?", (VISIT,)).fetchone()[0]
    cursor = conn.execute(
        "INSERT INTO ClinicalEntry (IdentifierSystem, IdentifierValue, VisitId, Category, Code, CodeSystem, "
        "Display, Text, RecordedAt) VALUES (?, ?, ?, 'Diagnosis', ?, 'https://triad.example/fhir/CodeSystem/local', "
        "?, ?, ?)",
        (FHIR, f"Condition/cond-elena-plant-{number}", visit, f"plant-{number}", DISPLAYS[number], DISPLAYS[number], at))
    entry = cursor.lastrowid
    conn.execute("INSERT INTO Diagnosis (ClinicalEntryId, Category, OnsetDate, ClinicalStatus) "
                 "VALUES (?, 'Diagnosis', ?, 'active')", (entry, at))
    return entry


def add_assertion(conn: sqlite3.Connection, identifier: str, staff_value: str | None, channel: str, origin: str,
                  at: str, entry: int, supersedes: int | None, intent: str, verification: str, statement: str) -> int:
    """A message with one assertion. `staff_value` None gives a message with no issuer (a patient message)."""
    staff = None
    if staff_value is not None:
        staff = conn.execute("SELECT Id FROM Staff WHERE IdentifierSystem = ? AND IdentifierValue = ?",
                             (EMPLOYEE_SYSTEM, staff_value)).fetchone()[0]
    message = conn.execute(
        "INSERT INTO Message (IdentifierSystem, IdentifierValue, StaffId, Channel, Origin, SentAt, Text) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)", (MESSAGE_SYSTEM, identifier, staff, channel, origin, at, statement)).lastrowid
    return conn.execute(
        "INSERT INTO Assertion (MessageId, Seq, ClinicalEntryId, SupersedesId, AssertedAt, Intent, Source, "
        "Verification, Statement) VALUES (?, 1, ?, ?, ?, ?, 'Human', ?, ?)",
        (message, entry, supersedes, at, intent, verification, statement)).lastrowid


def add_patient_message(conn: sqlite3.Connection) -> None:
    """A patient message with no issuer. Its assertion supersedes the current penicillin-allergy assertion."""
    identifier, at, text = PATIENT_MESSAGE
    entry = conn.execute("SELECT Id FROM ClinicalEntry WHERE IdentifierSystem = ? AND IdentifierValue = ?",
                         (FHIR, PENICILLIN)).fetchone()[0]
    head = conn.execute(
        "SELECT a.Id FROM Assertion a WHERE a.ClinicalEntryId = ? "
        "AND NOT EXISTS (SELECT 1 FROM Assertion n WHERE n.SupersedesId = a.Id)", (entry,)).fetchone()[0]
    add_assertion(conn, identifier, None, "App", "Patient", at, entry, head, "Report", "Unconfirmed", text)
