"""Departments, locations, staff and medications (the DirectoryRepository port).

Location.Type holds the name of the department of the location (a value, not a foreign key).
Column names come only from the fixed lists below. Each value is a parameter.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from domain.records import Address
from domain.views import (DepartmentView, Identifier, LocationView, MedicationView, StaffDepartment, StaffView)

from infrastructure import ids

EMPLOYEE_SYSTEM = "https://triad.example/fhir/sid/employee"
ADDRESS = ("Street", "City", "Region", "PostalCode", "Country")
DEPARTMENT_COLUMNS = ("IdentifierSystem", "IdentifierValue", "Name", "Type", "PhoneNumber", "Email") + ADDRESS
LOCATION_COLUMNS = ("IdentifierSystem", "IdentifierValue", "Name", "Type", "PhysicalType", "PhoneNumber") + ADDRESS
STAFF_COLUMNS = ("IdentifierSystem", "IdentifierValue", "Name", "Sex", "Email", "PhoneNumber", "Active", "Role")
SUBTYPE_COLUMNS = {"Doctor": ("LicenseNumber", "Qualification"), "Nurse": ("LicenseNumber", "Designation"),
                   "MOA": ("CertificationNumber", "Desk", "PhoneExtension")}
MEDICATION_COLUMNS = ("Code", "CodeSystem", "Name", "Form", "Manufacturer")

STAFF_SQL = """
SELECT s.*, dr.LicenseNumber AS DoctorLicense, dr.Qualification, nu.LicenseNumber AS NurseLicense, nu.Designation,
       mo.CertificationNumber, mo.Desk, mo.PhoneExtension
FROM Staff s
LEFT JOIN Doctor dr ON dr.StaffId = s.Id
LEFT JOIN Nurse nu ON nu.StaffId = s.Id
LEFT JOIN MOA mo ON mo.StaffId = s.Id
"""


def address_of(r: sqlite3.Row) -> Address:
    return Address(street=r["Street"], city=r["City"], region=r["Region"], postal_code=r["PostalCode"],
                   country=r["Country"])


def insert(conn: sqlite3.Connection, table: str, allowed: tuple[str, ...], values: dict) -> int:
    columns = [c for c in allowed if c in values]
    return conn.execute(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({','.join('?' * len(columns))})",
                        [values[c] for c in columns]).lastrowid


def update(conn: sqlite3.Connection, table: str, allowed: tuple[str, ...], row_id: int, values: dict,
           key: str = "Id") -> None:
    columns = [c for c in allowed if c in values]
    if columns:
        conn.execute(f"UPDATE {table} SET {', '.join(c + ' = ?' for c in columns)} WHERE {key} = ?",
                     [values[c] for c in columns] + [row_id])


class SqliteDirectoryRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ----- departments -----

    def _department(self, r: sqlite3.Row) -> DepartmentView:
        return DepartmentView(id=r["Id"], identifier=Identifier(r["IdentifierSystem"], r["IdentifierValue"]),
                              name=r["Name"], type=r["Type"], phone_number=r["PhoneNumber"], email=r["Email"],
                              address=address_of(r), staff_count=r["StaffCount"])

    def departments(self) -> list[DepartmentView]:
        return [self._department(r) for r in self.conn.execute(
            "SELECT d.*, (SELECT COUNT(DISTINCT w.StaffId) FROM WorksIn w WHERE w.DepartmentId = d.Id) AS StaffCount "
            "FROM Department d ORDER BY d.Name")]

    def department(self, department_id: int) -> Optional[DepartmentView]:
        r = self.conn.execute(
            "SELECT d.*, (SELECT COUNT(DISTINCT w.StaffId) FROM WorksIn w WHERE w.DepartmentId = d.Id) AS StaffCount "
            "FROM Department d WHERE d.Id = ?", (department_id,)).fetchone()
        return self._department(r) if r else None

    def department_name_exists(self, name: str, except_id: Optional[int] = None) -> bool:
        return self.conn.execute("SELECT 1 FROM Department WHERE lower(Name) = lower(?) AND Id IS NOT ?",
                                 (name, except_id)).fetchone() is not None

    def add_department(self, values: dict) -> int:
        return insert(self.conn, "Department", DEPARTMENT_COLUMNS, values)

    def update_department(self, department_id: int, values: dict) -> None:
        old = self.conn.execute("SELECT Name FROM Department WHERE Id = ?", (department_id,)).fetchone()[0]
        update(self.conn, "Department", DEPARTMENT_COLUMNS, department_id, values)
        if "Name" in values and values["Name"] != old:
            # A location keeps the department name as a value. Change it with the department.
            self.conn.execute("UPDATE Location SET Type = ? WHERE Type = ?", (values["Name"], old))

    def delete_department(self, department_id: int) -> None:
        self.conn.execute("DELETE FROM Department WHERE Id = ?", (department_id,))

    def department_use(self, department_id: int) -> tuple[int, int]:
        r = self.conn.execute(
            "SELECT (SELECT COUNT(DISTINCT StaffId) FROM WorksIn WHERE DepartmentId = d.Id), "
            "(SELECT COUNT(*) FROM Location l WHERE l.Type = d.Name) FROM Department d WHERE d.Id = ?",
            (department_id,)).fetchone()
        return (r[0], r[1]) if r else (0, 0)

    # ----- locations -----

    def _location(self, r: sqlite3.Row) -> LocationView:
        return LocationView(id=r["Id"], identifier=Identifier(r["IdentifierSystem"], r["IdentifierValue"]),
                            name=r["Name"], department=r["Type"], physical_type=r["PhysicalType"],
                            phone_number=r["PhoneNumber"], address=address_of(r), in_use=bool(r["InUse"]))

    LOCATION_SQL = ("SELECT l.*, EXISTS (SELECT 1 FROM VisitLocation vl WHERE vl.LocationId = l.Id) AS InUse "
                    "FROM Location l")

    def locations(self, department: Optional[str]) -> list[LocationView]:
        if department:
            sql = (self.LOCATION_SQL + " WHERE lower(l.Type) = lower(?) OR l.Type IN (SELECT Name FROM Department "
                   "WHERE IdentifierValue = ? OR CAST(Id AS TEXT) = ?) ORDER BY l.Id")
            rows = self.conn.execute(sql, (department, department, department))
        else:
            rows = self.conn.execute(self.LOCATION_SQL + " ORDER BY l.Id")
        return [self._location(r) for r in rows]

    def location(self, location_id: int) -> Optional[LocationView]:
        r = self.conn.execute(self.LOCATION_SQL + " WHERE l.Id = ?", (location_id,)).fetchone()
        return self._location(r) if r else None

    def add_location(self, values: dict) -> int:
        return insert(self.conn, "Location", LOCATION_COLUMNS, values)

    def update_location(self, location_id: int, values: dict) -> None:
        update(self.conn, "Location", LOCATION_COLUMNS, location_id, values)

    def delete_location(self, location_id: int) -> None:
        self.conn.execute("DELETE FROM Location WHERE Id = ?", (location_id,))

    # ----- staff -----

    def _staff_views(self, rows: list[sqlite3.Row]) -> list[StaffView]:
        if not rows:
            return []
        staff_ids = [r["Id"] for r in rows]
        marks = ",".join("?" * len(staff_ids))
        depts: dict[int, list[StaffDepartment]] = {}
        for r in self.conn.execute(
                f"SELECT w.StaffId, w.DepartmentId, d.Name, w.RoleCode, w.Specialty FROM WorksIn w "
                f"JOIN Department d ON d.Id = w.DepartmentId WHERE w.StaffId IN ({marks}) ORDER BY w.Id", staff_ids):
            depts.setdefault(r["StaffId"], []).append(
                StaffDepartment(r["DepartmentId"], r["Name"], r["RoleCode"], r["Specialty"]))
        langs: dict[int, list[str]] = {}
        for r in self.conn.execute(f"SELECT StaffId, Language FROM StaffLanguage WHERE StaffId IN ({marks}) "
                                   "ORDER BY Id", staff_ids):
            langs.setdefault(r["StaffId"], []).append(r["Language"])
        return [StaffView(
            id=r["Id"], key=f"{r['Role']}:{r['IdentifierValue']}",
            identifier=Identifier(r["IdentifierSystem"], r["IdentifierValue"]), name=r["Name"], role=r["Role"],
            sex=r["Sex"], email=r["Email"], phone_number=r["PhoneNumber"], active=bool(r["Active"]),
            departments=depts.get(r["Id"], []), languages=langs.get(r["Id"], []),
            license_number=r["DoctorLicense"] if r["Role"] == "Doctor" else r["NurseLicense"],
            qualification=r["Qualification"], designation=r["Designation"],
            certification_number=r["CertificationNumber"], desk=r["Desk"], phone_extension=r["PhoneExtension"])
            for r in rows]

    def staff_list(self, role: Optional[str], department: Optional[str], q: Optional[str],
                   limit: int) -> list[StaffView]:
        clauses, args = [], []
        if role:
            clauses.append("s.Role = ?")
            args.append(role)
        if q:
            clauses.append("(lower(s.Name) LIKE ? OR s.IdentifierValue = ?)")
            args += [f"%{q.lower()}%", q]
        if department:
            clauses.append("EXISTS (SELECT 1 FROM WorksIn w JOIN Department d ON d.Id = w.DepartmentId "
                           "WHERE w.StaffId = s.Id AND (lower(d.Name) = lower(?) OR d.IdentifierValue = ? "
                           "OR CAST(d.Id AS TEXT) = ?))")
            args += [department] * 3
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.conn.execute(STAFF_SQL + where + " ORDER BY s.IdentifierSystem = ? DESC, s.Name, s.Id LIMIT ?",
                                 (*args, EMPLOYEE_SYSTEM, limit)).fetchall()
        return self._staff_views(rows)

    def staff(self, staff_id: int) -> Optional[StaffView]:
        views = self._staff_views(self.conn.execute(STAFF_SQL + " WHERE s.Id = ?", (staff_id,)).fetchall())
        return views[0] if views else None

    def staff_by_identifier(self, system: str, value: str) -> Optional[StaffView]:
        views = self._staff_views(self.conn.execute(
            STAFF_SQL + " WHERE s.IdentifierSystem = ? AND s.IdentifierValue = ?", (system, value)).fetchall())
        return views[0] if views else None

    def add_staff(self, values: dict) -> int:
        staff_id = insert(self.conn, "Staff", STAFF_COLUMNS, values)
        role = values["Role"]
        sub = dict(values.get("subtype", {}), StaffId=staff_id)
        insert(self.conn, role, ("StaffId",) + SUBTYPE_COLUMNS[role], sub)
        self.conn.execute("INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty) VALUES (?,?,?,?)",
                          (staff_id, values["department_id"], values["role_code"], values.get("specialty")))
        self.conn.executemany("INSERT INTO StaffLanguage (StaffId, Language) VALUES (?,?)",
                              [(staff_id, lang) for lang in values.get("languages", [])])
        return staff_id

    def update_staff(self, staff_id: int, values: dict) -> None:
        update(self.conn, "Staff", STAFF_COLUMNS[3:7], staff_id, values)
        if values.get("subtype"):
            role = self.conn.execute("SELECT Role FROM Staff WHERE Id = ?", (staff_id,)).fetchone()[0]
            update(self.conn, role, SUBTYPE_COLUMNS[role], staff_id, values["subtype"], key="StaffId")
        if "languages" in values:
            self.conn.execute("DELETE FROM StaffLanguage WHERE StaffId = ?", (staff_id,))
            self.conn.executemany("INSERT INTO StaffLanguage (StaffId, Language) VALUES (?,?)",
                                  [(staff_id, lang) for lang in values["languages"]])

    def staff_use(self, staff_id: int) -> dict[str, int]:
        r = self.conn.execute("""
            SELECT (SELECT COUNT(*) FROM Message WHERE StaffId = s.Id) AS Messages,
                   (SELECT COUNT(*) FROM WorksIn WHERE StaffId = s.Id) AS Departments,
                   (SELECT COUNT(*) FROM CareTeamMember m WHERE m.MemberSystem = s.IdentifierSystem
                        AND m.MemberValue = s.IdentifierValue) AS CareTeams
            FROM Staff s WHERE s.Id = ?""", (staff_id,)).fetchone()
        return {"messages": r[0], "departments": r[1], "careTeams": r[2]}

    def delete_staff(self, staff_id: int) -> None:
        self.conn.execute("DELETE FROM StaffLanguage WHERE StaffId = ?", (staff_id,))
        for table in ("Doctor", "Nurse", "MOA"):
            self.conn.execute(f"DELETE FROM {table} WHERE StaffId = ?", (staff_id,))
        self.conn.execute("DELETE FROM Staff WHERE Id = ?", (staff_id,))

    # ----- medications -----

    @staticmethod
    def _medication(r: sqlite3.Row) -> MedicationView:
        return MedicationView(id=r["Id"], code=r["Code"], code_system=r["CodeSystem"], name=r["Name"], form=r["Form"],
                              manufacturer=r["Manufacturer"])

    def medications(self, q: Optional[str], limit: int) -> list[MedicationView]:
        if q:
            rows = self.conn.execute("SELECT * FROM Medication WHERE lower(Name) LIKE ? OR Code = ? "
                                     "ORDER BY Name LIMIT ?", (f"%{q.lower()}%", q, limit))
        else:
            rows = self.conn.execute("SELECT * FROM Medication ORDER BY Name LIMIT ?", (limit,))
        return [self._medication(r) for r in rows]

    def medication(self, medication_id: int) -> Optional[MedicationView]:
        r = self.conn.execute("SELECT * FROM Medication WHERE Id = ?", (medication_id,)).fetchone()
        return self._medication(r) if r else None

    def add_medication(self, values: dict) -> int:
        return insert(self.conn, "Medication", MEDICATION_COLUMNS, values)

    def update_medication(self, medication_id: int, values: dict) -> None:
        update(self.conn, "Medication", MEDICATION_COLUMNS, medication_id, values)

    def medication_in_use(self, medication_id: int) -> bool:
        return self.conn.execute("SELECT 1 FROM Prescription WHERE MedicationId = ? LIMIT 1",
                                 (medication_id,)).fetchone() is not None

    def delete_medication(self, medication_id: int) -> None:
        self.conn.execute("DELETE FROM Medication WHERE Id = ?", (medication_id,))

    # ----- identifiers -----

    def unique_identifier(self, table: str, system: str, base: str) -> str:
        return ids.unique_identifier(self.conn, table, system, base)

    def next_identifier(self, table: str, system: str, prefix: str, width: int) -> str:
        return ids.next_identifier(self.conn, table, system, prefix, width)
