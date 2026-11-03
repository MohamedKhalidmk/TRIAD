"""The users of the picker: patients and staff (the UserRepository port)."""
from __future__ import annotations

import sqlite3
from typing import Optional, Sequence

from domain.access import Actor
from domain.views import UserView

MRN_SYSTEM = "https://triad.example/fhir/sid/mrn"
SYNTHEA_SYSTEM = "https://github.com/synthetichealth/synthea"

# The key value of a patient: the first identifier in the order MRN, then Synthea.
PATIENT_USERS_SQL = """
SELECT p.Id, p.Name, p.DateOfBirth,
       COALESCE((SELECT Value FROM PatientIdentifier WHERE PatientId = p.Id AND System = :mrn),
                (SELECT Value FROM PatientIdentifier WHERE PatientId = p.Id AND System = :synthea)) AS KeyValue
FROM Patient p
"""

STAFF_USERS_SQL = """
SELECT s.Id, s.Name, s.Role, s.IdentifierValue AS KeyValue,
       (SELECT group_concat(Name, ', ') FROM (SELECT DISTINCT d.Name FROM WorksIn w
            JOIN Department d ON d.Id = w.DepartmentId WHERE w.StaffId = s.Id ORDER BY d.Name)) AS Departments
FROM Staff s
"""


class SqliteUserRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def actor(self, role: str, value: str) -> Optional[Actor]:
        if role == "Patient":
            row = self.conn.execute(
                "SELECT p.Id, p.Name, pi.System FROM PatientIdentifier pi JOIN Patient p ON p.Id = pi.PatientId "
                "WHERE pi.Value = ? AND pi.System IN (?, ?) ORDER BY pi.System = ? DESC LIMIT 1",
                (value, MRN_SYSTEM, SYNTHEA_SYSTEM, MRN_SYSTEM)).fetchone()
            if row is None:
                return None
            return Actor(role="Patient", key=f"Patient:{value}", name=row["Name"], system=row["System"], value=value,
                         patient_id=row["Id"])
        row = self.conn.execute("SELECT Id, Name, IdentifierSystem FROM Staff WHERE Role = ? AND IdentifierValue = ?",
                                (role, value)).fetchone()
        if row is None:
            return None
        return Actor(role=role, key=f"{role}:{value}", name=row["Name"], system=row["IdentifierSystem"], value=value,
                     staff_id=row["Id"])

    def _all(self, role: Optional[str], q: Optional[str], pinned_keys: Sequence[str]) -> list[UserView]:
        out: list[UserView] = []
        like = f"%{q.lower()}%" if q else None
        if role in (None, "Patient"):
            sql = PATIENT_USERS_SQL + (" WHERE lower(p.Name) LIKE :like" if like else "")
            for r in self.conn.execute(sql, {"mrn": MRN_SYSTEM, "synthea": SYNTHEA_SYSTEM, "like": like}):
                if r["KeyValue"]:
                    key = f"Patient:{r['KeyValue']}"
                    out.append(UserView(key=key, role="Patient", name=r["Name"], detail=f"born {r['DateOfBirth']}",
                                        pinned=key in pinned_keys, patient_id=r["Id"], staff_id=None))
        if role != "Patient":
            clauses, args = [], {}
            if role:
                clauses.append("s.Role = :role")
                args["role"] = role
            if like:
                clauses.append("lower(s.Name) LIKE :like")
                args["like"] = like
            sql = STAFF_USERS_SQL + (" WHERE " + " AND ".join(clauses) if clauses else "")
            for r in self.conn.execute(sql, args):
                key = f"{r['Role']}:{r['KeyValue']}"
                out.append(UserView(key=key, role=r["Role"], name=r["Name"], detail=r["Departments"] or "",
                                    pinned=key in pinned_keys, patient_id=None, staff_id=r["Id"]))
        order = {key: i for i, key in enumerate(pinned_keys)}
        out.sort(key=lambda u: (0, order[u.key], "") if u.pinned else (1, 0, u.name.lower()))
        return out

    def users(self, role: Optional[str], q: Optional[str], limit: int, pinned_keys: Sequence[str]) -> list[UserView]:
        return self._all(role, q, pinned_keys)[:limit]

    def user(self, role: str, value: str, pinned_keys: Sequence[str]) -> Optional[UserView]:
        actor = self.actor(role, value)
        if actor is None:
            return None
        if actor.is_patient:
            r = self.conn.execute(PATIENT_USERS_SQL + " WHERE p.Id = :id",
                                  {"mrn": MRN_SYSTEM, "synthea": SYNTHEA_SYSTEM, "id": actor.patient_id}).fetchone()
            key = f"Patient:{r['KeyValue'] or value}"
            return UserView(key=key, role="Patient", name=r["Name"], detail=f"born {r['DateOfBirth']}",
                            pinned=key in pinned_keys, patient_id=r["Id"], staff_id=None)
        r = self.conn.execute(STAFF_USERS_SQL + " WHERE s.Id = :id", {"id": actor.staff_id}).fetchone()
        key = f"{r['Role']}:{r['KeyValue']}"
        return UserView(key=key, role=r["Role"], name=r["Name"], detail=r["Departments"] or "",
                        pinned=key in pinned_keys, patient_id=None, staff_id=r["Id"])
