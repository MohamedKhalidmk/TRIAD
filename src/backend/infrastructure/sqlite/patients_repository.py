"""Patients and visits (the PatientRepository and VisitRepository ports)."""
from __future__ import annotations

import sqlite3
from typing import Optional

from domain.records import Address
from domain.views import Identifier, PatientSummary, PatientView, VisitLocationView, VisitView

from infrastructure import ids

# The patients whose current care team has the member (query Q13: a care-team entry that nothing
# supersedes and whose status is active).
CARE_TEAM_PATIENTS_SQL = """
SELECT v.PatientId
FROM CareTeamMember ctm
JOIN CareTeam ct ON ct.Id = ctm.CareTeamId AND ct.Status = 'active'
JOIN ClinicalEntry e ON e.Id = ct.ClinicalEntryId
JOIN Visit v ON v.Id = e.VisitId
JOIN Assertion a ON a.ClinicalEntryId = e.Id
WHERE ctm.MemberSystem = ? AND ctm.MemberValue = ?
  AND NOT EXISTS (SELECT 1 FROM Assertion n WHERE n.SupersedesId = a.Id)
"""

OPEN_VISIT_SQL = ("(SELECT v.Id FROM Visit v WHERE v.PatientId = p.Id AND v.EndDate IS NULL "
                  "ORDER BY julianday(v.StartDate) DESC, v.Id DESC LIMIT 1)")

PATIENT_COLUMNS = ("Sex", "PhoneNumber", "Street", "City", "Region", "PostalCode", "Country")


def address_of(row: sqlite3.Row) -> Address:
    return Address(street=row["Street"], city=row["City"], region=row["Region"], postal_code=row["PostalCode"],
                   country=row["Country"])


class SqlitePatientRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get(self, patient_id: int) -> Optional[PatientView]:
        row = self.conn.execute(f"SELECT p.*, {OPEN_VISIT_SQL} AS OpenVisitId FROM Patient p WHERE p.Id = ?",
                                (patient_id,)).fetchone()
        if row is None:
            return None
        idents = [Identifier(r["System"], r["Value"]) for r in self.conn.execute(
            "SELECT System, Value FROM PatientIdentifier WHERE PatientId = ? ORDER BY Id", (patient_id,))]
        return PatientView(id=row["Id"], name=row["Name"], date_of_birth=row["DateOfBirth"], sex=row["Sex"],
                           phone_number=row["PhoneNumber"], open_visit_id=row["OpenVisitId"],
                           address=address_of(row), identifiers=idents)

    def search(self, q: Optional[str], dob: Optional[str], scope: str, member: Optional[tuple[str, str]],
               limit: int) -> list[PatientSummary]:
        clauses, args = [], []
        if q:
            clauses.append("lower(p.Name) LIKE ?")
            args.append(f"%{q.lower()}%")
        if dob:
            clauses.append("p.DateOfBirth = ?")
            args.append(dob)
        if scope == "open-visits":
            clauses.append("EXISTS (SELECT 1 FROM Visit v WHERE v.PatientId = p.Id AND v.EndDate IS NULL)")
        if scope == "care-team" and member:
            clauses.append(f"p.Id IN ({CARE_TEAM_PATIENTS_SQL})")
            args.extend(member)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.conn.execute(
            f"SELECT p.Id, p.Name, p.DateOfBirth, p.Sex, p.PhoneNumber, {OPEN_VISIT_SQL} AS OpenVisitId "
            f"FROM Patient p{where} ORDER BY p.Name, p.Id LIMIT ?", (*args, limit))
        return [PatientSummary(r["Id"], r["Name"], r["DateOfBirth"], r["Sex"], r["PhoneNumber"], r["OpenVisitId"])
                for r in rows]

    def key_exists(self, name: str, date_of_birth: str) -> bool:
        return self.conn.execute("SELECT 1 FROM Patient WHERE Name = ? AND DateOfBirth = ?",
                                 (name, date_of_birth)).fetchone() is not None

    def create(self, name: str, date_of_birth: str, sex: str, phone: Optional[str], address: Address,
               identifiers: list[tuple[str, str]]) -> int:
        patient_id = self.conn.execute(
            "INSERT INTO Patient (Name, DateOfBirth, Sex, PhoneNumber, Street, City, Region, PostalCode, Country) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (name, date_of_birth, sex, phone, address.street, address.city, address.region, address.postal_code,
             address.country)).lastrowid
        self.conn.executemany("INSERT INTO PatientIdentifier (PatientId, System, Value) VALUES (?,?,?)",
                              [(patient_id, s, v) for s, v in identifiers])
        return patient_id

    def update(self, patient_id: int, changes: dict) -> None:
        columns = [c for c in PATIENT_COLUMNS if c in changes]
        if columns:
            self.conn.execute(f"UPDATE Patient SET {', '.join(c + ' = ?' for c in columns)} WHERE Id = ?",
                              (*[changes[c] for c in columns], patient_id))

    def has_visits(self, patient_id: int) -> bool:
        row = self.conn.execute("SELECT 1 FROM Visit WHERE PatientId = ? LIMIT 1", (patient_id,)).fetchone()
        return row is not None

    def delete(self, patient_id: int) -> None:
        self.conn.execute("DELETE FROM PatientIdentifier WHERE PatientId = ?", (patient_id,))
        self.conn.execute("DELETE FROM Patient WHERE Id = ?", (patient_id,))

    def on_care_team(self, patient_id: int, system: str, value: str) -> bool:
        return self.conn.execute(f"SELECT 1 FROM ({CARE_TEAM_PATIENTS_SQL}) WHERE PatientId = ? LIMIT 1",
                                 (system, value, patient_id)).fetchone() is not None

    def next_identifier(self, system: str, prefix: str, width: int) -> str:
        return ids.next_identifier(self.conn, "PatientIdentifier", system, prefix, width)


VISIT_SQL = ("SELECT Id, PatientId, IdentifierSystem, IdentifierValue, Class, Type, Reason, StartDate, EndDate "
             "FROM Visit")


class SqliteVisitRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def _views(self, rows: list[sqlite3.Row]) -> list[VisitView]:
        if not rows:
            return []
        marks = ",".join("?" * len(rows))
        places: dict[int, list[VisitLocationView]] = {}
        for r in self.conn.execute(
                f"SELECT vl.VisitId, vl.LocationId, l.Name, l.Type, vl.StartDate, vl.EndDate FROM VisitLocation vl "
                f"JOIN Location l ON l.Id = vl.LocationId WHERE vl.VisitId IN ({marks}) "
                f"ORDER BY julianday(vl.StartDate), vl.Id", [r["Id"] for r in rows]):
            places.setdefault(r["VisitId"], []).append(
                VisitLocationView(r["LocationId"], r["Name"], r["Type"], r["StartDate"], r["EndDate"]))
        out = []
        for r in rows:
            locs = places.get(r["Id"], [])
            out.append(VisitView(id=r["Id"], patient_id=r["PatientId"],
                                 identifier=Identifier(r["IdentifierSystem"], r["IdentifierValue"]),
                                 visit_class=r["Class"], type=r["Type"], reason=r["Reason"],
                                 start_date=r["StartDate"], end_date=r["EndDate"], is_open=r["EndDate"] is None,
                                 department=locs[-1].department if locs else None, locations=locs))
        return out

    def for_patient(self, patient_id: int) -> list[VisitView]:
        rows = self.conn.execute(f"{VISIT_SQL} WHERE PatientId = ? ORDER BY julianday(StartDate) DESC, Id DESC",
                                 (patient_id,)).fetchall()
        return self._views(rows)

    def get(self, visit_id: int) -> Optional[VisitView]:
        views = self._views(self.conn.execute(f"{VISIT_SQL} WHERE Id = ?", (visit_id,)).fetchall())
        return views[0] if views else None

    def open_visit_id(self, patient_id: int) -> Optional[int]:
        row = self.conn.execute("SELECT Id FROM Visit WHERE PatientId = ? AND EndDate IS NULL "
                                "ORDER BY julianday(StartDate) DESC, Id DESC LIMIT 1", (patient_id,)).fetchone()
        return row[0] if row else None

    def visit_rows(self, patient_id: int) -> list[tuple[int, str, str, Optional[str]]]:
        return [tuple(r) for r in self.conn.execute(
            "SELECT Id, Class, StartDate, EndDate FROM Visit WHERE PatientId = ?", (patient_id,))]

    def create(self, patient_id: int, identifier: tuple[str, str], visit_class: str, type_: Optional[str],
               reason: Optional[str], start: str, location_id: Optional[int], end: Optional[str] = None) -> int:
        visit_id = self.conn.execute(
            "INSERT INTO Visit (IdentifierSystem, IdentifierValue, PatientId, Class, Type, Reason, StartDate, EndDate) "
            "VALUES (?,?,?,?,?,?,?,?)", (*identifier, patient_id, visit_class, type_, reason, start, end)).lastrowid
        if location_id is not None:
            self.conn.execute("INSERT INTO VisitLocation (VisitId, LocationId, StartDate, EndDate) VALUES (?,?,?,?)",
                              (visit_id, location_id, start, end))
        return visit_id

    def move(self, visit_id: int, location_id: int, now: str) -> None:
        self.conn.execute("UPDATE VisitLocation SET EndDate = ? WHERE VisitId = ? AND EndDate IS NULL", (now, visit_id))
        self.conn.execute("INSERT INTO VisitLocation (VisitId, LocationId, StartDate) VALUES (?,?,?)",
                          (visit_id, location_id, now))

    def end(self, visit_id: int, now: str) -> None:
        self.conn.execute("UPDATE Visit SET EndDate = ? WHERE Id = ?", (now, visit_id))
        self.conn.execute("UPDATE VisitLocation SET EndDate = ? WHERE VisitId = ? AND EndDate IS NULL", (now, visit_id))

    def next_identifier(self, system: str, prefix: str, width: int) -> str:
        return ids.next_identifier(self.conn, "Visit", system, prefix, width)
