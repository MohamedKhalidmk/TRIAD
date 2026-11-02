"""Write the scenario data as plain SQL INSERT statements (02_insert_seed.sql).

The scope is the TRIAD General directory (departments, locations, TRIAD staff), Patient A
(Elena Marsh) with all her records, and the demo chat and audit rows. The file fills all 29 tables.
Each foreign key is a subselect on the natural key of the target row, as the course manual shows.
So the file does not depend on row ids, and it runs after 01_create_tables.sql on a new database.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from infrastructure.sqlite.onboarding_store import TABLES

EMPLOYEE_SYSTEM = "https://triad.example/fhir/sid/employee"
SCENARIO_PATIENT = ("Elena Marsh", "1971-05-14")

NATURAL_KEY = {
    "Department": ("IdentifierSystem", "IdentifierValue"), "Location": ("IdentifierSystem", "IdentifierValue"),
    "Staff": ("IdentifierSystem", "IdentifierValue"), "Visit": ("IdentifierSystem", "IdentifierValue"),
    "ClinicalEntry": ("IdentifierSystem", "IdentifierValue"), "Message": ("IdentifierSystem", "IdentifierValue"),
    "ChatSession": ("IdentifierSystem", "IdentifierValue"), "AuditEvent": ("IdentifierSystem", "IdentifierValue"),
    "Patient": ("Name", "DateOfBirth"), "Medication": ("Code", "CodeSystem"),
    "Assertion": ("MessageId", "Seq"), "ChatTurn": ("ChatSessionId", "Seq"), "CareTeam": ("ClinicalEntryId",),
}
SUBTYPES = ("Diagnosis", "Procedure", "Allergy", "Observation", "LabOrder", "LabReport", "Prescription", "CareTeam")
FOREIGN_KEYS = {
    "StaffLanguage": {"StaffId": "Staff"}, "WorksIn": {"StaffId": "Staff", "DepartmentId": "Department"},
    "Doctor": {"StaffId": "Staff"}, "Nurse": {"StaffId": "Staff"}, "MOA": {"StaffId": "Staff"},
    "PatientIdentifier": {"PatientId": "Patient"}, "Visit": {"PatientId": "Patient"},
    "VisitLocation": {"VisitId": "Visit", "LocationId": "Location"}, "ClinicalEntry": {"VisitId": "Visit"},
    **{t: {"ClinicalEntryId": "ClinicalEntry"} for t in SUBTYPES},
    "CareTeamMember": {"CareTeamId": "CareTeam"}, "Message": {"StaffId": "Staff"},
    "Assertion": {"MessageId": "Message", "ClinicalEntryId": "ClinicalEntry", "SupersedesId": "Assertion"},
    "ChatTurn": {"ChatSessionId": "ChatSession"}, "Citation": {"ChatTurnId": "ChatTurn", "AssertionId": "Assertion"},
    "AuditEvent": {"ChatTurnId": "ChatTurn"},
}
FOREIGN_KEYS["Prescription"] = {"ClinicalEntryId": "ClinicalEntry", "MedicationId": "Medication"}

# The rows in scope, per table (SQL that returns Id values).
SCOPE = {
    "Department": "SELECT Id FROM Department",
    "Location": "SELECT Id FROM Location",
    "Staff": f"SELECT Id FROM Staff WHERE IdentifierSystem = '{EMPLOYEE_SYSTEM}'",
    "Patient": "SELECT Id FROM Patient WHERE Name = ? AND DateOfBirth = ?",
}


def literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


class _Exporter:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.columns = {t: [r["name"] for r in conn.execute(f"PRAGMA table_info({t})") if r["name"] != "Id"]
                        for t in TABLES}

    def key_expr(self, table: str, row_id: int) -> str:
        """A subselect that finds the row `row_id` of `table` by its natural key."""
        keys = NATURAL_KEY[table]
        row = self.conn.execute(f"SELECT {', '.join(keys)} FROM {table} WHERE Id = ?", (row_id,)).fetchone()
        parts = []
        for k in keys:
            target = FOREIGN_KEYS.get(table, {}).get(k)
            value = self.key_expr(target, row[k]) if target else literal(row[k])
            parts.append(f"{k} = {value}")
        return f"(SELECT Id FROM {table} WHERE {' AND '.join(parts)})"

    def insert(self, table: str, row_id: int) -> str:
        row = self.conn.execute(f"SELECT * FROM {table} WHERE Id = ?", (row_id,)).fetchone()
        values = []
        for col in self.columns[table]:
            target = FOREIGN_KEYS.get(table, {}).get(col)
            values.append(self.key_expr(target, row[col]) if target and row[col] is not None else literal(row[col]))
        return f"INSERT INTO {table} ({', '.join(self.columns[table])})\nVALUES ({', '.join(values)});"


def scope_ids(conn: sqlite3.Connection) -> dict[str, list[int]]:
    q = lambda sql, *args: [r[0] for r in conn.execute(sql, args)]  # noqa: E731
    ids: dict[str, list[int]] = {}
    ids["Department"] = q(SCOPE["Department"] + " ORDER BY Id")
    ids["Location"] = q(SCOPE["Location"] + " ORDER BY Id")
    ids["Staff"] = q(SCOPE["Staff"] + " ORDER BY Id")
    staff = ",".join(map(str, ids["Staff"])) or "NULL"
    for t in ("StaffLanguage", "WorksIn", "Doctor", "Nurse", "MOA"):
        ids[t] = q(f"SELECT Id FROM {t} WHERE StaffId IN ({staff}) ORDER BY Id")
    ids["Patient"] = q(SCOPE["Patient"], *SCENARIO_PATIENT)
    pat = ",".join(map(str, ids["Patient"])) or "NULL"
    ids["PatientIdentifier"] = q(f"SELECT Id FROM PatientIdentifier WHERE PatientId IN ({pat}) ORDER BY Id")
    ids["Visit"] = q(f"SELECT Id FROM Visit WHERE PatientId IN ({pat}) ORDER BY Id")
    visits = ",".join(map(str, ids["Visit"])) or "NULL"
    ids["VisitLocation"] = q(f"SELECT Id FROM VisitLocation WHERE VisitId IN ({visits}) ORDER BY Id")
    ids["ClinicalEntry"] = q(f"SELECT Id FROM ClinicalEntry WHERE VisitId IN ({visits}) ORDER BY Id")
    entries = ",".join(map(str, ids["ClinicalEntry"])) or "NULL"
    for t in SUBTYPES:
        ids[t] = q(f"SELECT Id FROM {t} WHERE ClinicalEntryId IN ({entries}) ORDER BY Id")
    teams = ",".join(map(str, ids["CareTeam"])) or "NULL"
    ids["CareTeamMember"] = q(f"SELECT Id FROM CareTeamMember WHERE CareTeamId IN ({teams}) ORDER BY Id")
    ids["Medication"] = q(f"SELECT DISTINCT MedicationId FROM Prescription WHERE ClinicalEntryId IN ({entries}) "
                          f"ORDER BY MedicationId")
    ids["Assertion"] = q(f"SELECT Id FROM Assertion WHERE ClinicalEntryId IN ({entries}) ORDER BY Id")
    asserts = ",".join(map(str, ids["Assertion"])) or "NULL"
    ids["Message"] = q(f"SELECT DISTINCT MessageId FROM Assertion WHERE Id IN ({asserts}) ORDER BY MessageId")
    for t in ("ChatSession", "ChatTurn", "Citation", "AuditEvent"):
        ids[t] = q(f"SELECT Id FROM {t} ORDER BY Id")
    return ids


def export_scenarios(conn: sqlite3.Connection, out: Path) -> int:
    exporter = _Exporter(conn)
    ids = scope_ids(conn)
    # Medication comes before Prescription; the rest follows the order of 01_create_tables.sql.
    order = [t for t in TABLES if t != "Medication"]
    order.insert(order.index("Prescription"), "Medication")
    lines = [
        "-- TRIAD scenario data (Milestone 4). This file is made by:",
        "--     python src/backend/main.py export-sql",
        "-- Do not edit it by hand. Run it after 01_create_tables.sql on a new database:",
        "--     sqlite3 triad.db < 01_create_tables.sql",
        "--     sqlite3 triad.db < 02_insert_seed.sql",
        "-- It holds the TRIAD General directory, Patient A (Elena Marsh) and the demo chat and audit rows.",
        "-- Each foreign key is a subselect on the natural key of the target row (no row ids).",
        "-- The full data set (112 Synthea patients) comes from the onboarding step (main.py ensure-db).",
        "",
        "PRAGMA foreign_keys = ON;",
        "BEGIN TRANSACTION;",
        "",
    ]
    count = 0
    for table in order:
        if not ids.get(table):
            continue
        lines.append(f"-- {table} ({len(ids[table])} rows)")
        for row_id in ids[table]:
            lines.append(exporter.insert(table, row_id))
            count += 1
        lines.append("")
    lines.append("COMMIT;")
    Path(out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return count
