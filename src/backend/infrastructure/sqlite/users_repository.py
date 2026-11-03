"""The users of the picker: patients and staff (the UserRepository port)."""
from __future__ import annotations

import sqlite3
from typing import Optional, Sequence

from domain.access import Actor
from domain.views import UserView

from application.paging import Page, PageRequest
from infrastructure.sqlite.paging import each_row, fetch_page, where

MRN_SYSTEM = "https://triad.example/fhir/sid/mrn"
SYNTHEA_SYSTEM = "https://github.com/synthetichealth/synthea"

# All users in one relation: the patients, then the staff. The two parameters are MRN_SYSTEM and SYNTHEA_SYSTEM.
# The key value of a patient is the first identifier in the order MRN, then Synthea (no identifier: no key).
USERS_SQL = """
SELECT 'Patient' AS Role, p.Id AS Id, p.Id AS PatientId, NULL AS StaffId, p.Name, 'born ' || p.DateOfBirth AS Detail,
       'Patient:' || COALESCE((SELECT Value FROM PatientIdentifier WHERE PatientId = p.Id AND System = ?),
                              (SELECT Value FROM PatientIdentifier WHERE PatientId = p.Id AND System = ?)) AS UserKey
FROM Patient p
UNION ALL
SELECT s.Role, s.Id, NULL, s.Id, s.Name,
       COALESCE((SELECT group_concat(Name, ', ') FROM (SELECT DISTINCT d.Name FROM WorksIn w
                 JOIN Department d ON d.Id = w.DepartmentId WHERE w.StaffId = s.Id ORDER BY d.Name)), ''),
       s.Role || ':' || s.IdentifierValue
FROM Staff s
"""
USERS_ARGS = (MRN_SYSTEM, SYNTHEA_SYSTEM)


def pinned_first(pinned_keys: Sequence[str]) -> str:
    """The ORDER BY key of the demo users: their place in `pinned_keys` (bound values), then all other users."""
    whens = " ".join(f"WHEN ? THEN {i}" for i in range(len(pinned_keys)))
    return f"CASE u.UserKey {whens} ELSE {len(pinned_keys)} END" if pinned_keys else "0"


def user_view(r: sqlite3.Row, pinned_keys: Sequence[str]) -> UserView:
    return UserView(key=r["UserKey"], role=r["Role"], name=r["Name"], detail=r["Detail"],
                    pinned=r["UserKey"] in pinned_keys, patient_id=r["PatientId"], staff_id=r["StaffId"])


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

    def users(self, role: Optional[str], q: Optional[str], pinned_keys: Sequence[str],
              page: PageRequest) -> Page[UserView]:
        """One page of the users: the demo users first (in the order of `pinned_keys`), then by name, then key."""
        clauses, args = ["u.UserKey IS NOT NULL"], list(USERS_ARGS)
        if role:
            clauses.append("u.Role = ?")
            args.append(role)
        if q:
            clauses.append("lower(u.Name) LIKE ?")
            args.append(f"%{q.lower()}%")
        return fetch_page(self.conn, "u.*", f"FROM ({USERS_SQL}) u{where(clauses)}", args,
                          f"{pinned_first(pinned_keys)}, lower(u.Name), u.UserKey, u.Id", page,
                          each_row(lambda r: user_view(r, pinned_keys)), order_args=pinned_keys)

    def user(self, role: str, value: str, pinned_keys: Sequence[str]) -> Optional[UserView]:
        actor = self.actor(role, value)
        if actor is None:
            return None
        row_id = actor.patient_id if actor.is_patient else actor.staff_id
        r = self.conn.execute(f"SELECT u.* FROM ({USERS_SQL}) u WHERE u.Role = ? AND u.Id = ?",
                              (*USERS_ARGS, role, row_id)).fetchone()
        return user_view(r, pinned_keys) if r else None
