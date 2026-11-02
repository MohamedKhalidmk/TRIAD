"""Write an onboarding batch to SQLite in one transaction (the OnboardingStore port)."""
from __future__ import annotations

import sqlite3

from domain import records as d

TABLES = ("Department", "Location", "Staff", "StaffLanguage", "WorksIn", "Doctor", "Nurse", "MOA",
          "Patient", "PatientIdentifier", "Visit", "VisitLocation", "ClinicalEntry", "Diagnosis",
          "Procedure", "Allergy", "Observation", "LabOrder", "LabReport", "Prescription", "CareTeam",
          "CareTeamMember", "Medication", "Message", "Assertion", "ChatSession", "ChatTurn",
          "Citation", "AuditEvent")

SUBTYPE_COLUMNS = {
    "Diagnosis": ("OnsetDate", "AbatementDate", "ClinicalStatus", "Severity"),
    "Procedure": ("PerformedDate", "Outcome"),
    "Allergy": ("Substance", "Type", "AllergyCategory", "Criticality", "ClinicalStatus"),
    "Observation": ("Value", "Unit"),
    "LabOrder": ("TestName", "Priority", "Specimen"),
    "LabReport": ("IssuedDate", "Conclusion"),
    "Prescription": ("Dosage", "Frequency", "Status"),
    "CareTeam": ("Name", "Status"),
}


def _addr(a: d.Address) -> tuple:
    return (a.street, a.city, a.region, a.postal_code, a.country)


class SqliteOnboardingStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def _insert(self, sql: str, values: tuple) -> int:
        return self.conn.execute(sql, values).lastrowid

    def write(self, batch: d.OnboardBatch) -> dict[str, int]:
        c = self.conn
        c.execute("BEGIN IMMEDIATE")
        try:
            dept_id = {x.ident: self._insert(
                "INSERT INTO Department (IdentifierSystem, IdentifierValue, Name, Type, PhoneNumber, Email, "
                "Street, City, Region, PostalCode, Country) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (*x.ident, x.name, x.type, x.phone, x.email, *_addr(x.address))) for x in batch.departments}
            loc_id = {x.ident: self._insert(
                "INSERT INTO Location (IdentifierSystem, IdentifierValue, Name, Type, PhysicalType, PhoneNumber, "
                "Street, City, Region, PostalCode, Country) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (*x.ident, x.name, x.type, x.physical_type, x.phone, *_addr(x.address))) for x in batch.locations}

            for s in batch.staff:
                sid = self._insert(
                    "INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (*s.ident, s.name, s.sex, s.email, s.phone, 1 if s.active else 0, s.role))
                c.executemany("INSERT INTO StaffLanguage (StaffId, Language) VALUES (?,?)",
                              [(sid, lang) for lang in dict.fromkeys(s.languages)])
                c.executemany(
                    "INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate) "
                    "VALUES (?,?,?,?,?,?)",
                    [(sid, dept_id[w.department], w.role_code, w.specialty, w.start_date, w.end_date)
                     for w in s.works_in])
                if s.role == "Doctor":
                    c.execute("INSERT INTO Doctor (StaffId, LicenseNumber, Qualification) VALUES (?,?,?)",
                              (sid, s.license_number, s.qualification))
                elif s.role == "Nurse":
                    c.execute("INSERT INTO Nurse (StaffId, LicenseNumber, Designation) VALUES (?,?,?)",
                              (sid, s.license_number, s.designation))
                else:
                    c.execute("INSERT INTO MOA (StaffId, CertificationNumber, Desk, PhoneExtension) VALUES (?,?,?,?)",
                              (sid, s.certification_number, s.desk, s.phone_extension))
            staff_id = {row["IdentifierSystem"] + "|" + row["IdentifierValue"]: row["Id"]
                        for row in c.execute("SELECT Id, IdentifierSystem, IdentifierValue FROM Staff")}

            patient_id = {}
            for p in batch.patients:
                pid = self._insert(
                    "INSERT INTO Patient (Name, DateOfBirth, Sex, PhoneNumber, Street, City, Region, PostalCode, "
                    "Country) VALUES (?,?,?,?,?,?,?,?,?)", (p.name, p.birth_date, p.sex, p.phone, *_addr(p.address)))
                patient_id[p.key] = pid
                c.executemany("INSERT INTO PatientIdentifier (PatientId, System, Value) VALUES (?,?,?)",
                              [(pid, *i) for i in p.identifiers])

            visit_id = {}
            for v in batch.visits:
                vid = self._insert(
                    "INSERT INTO Visit (IdentifierSystem, IdentifierValue, PatientId, Class, Type, Reason, StartDate, "
                    "EndDate) VALUES (?,?,?,?,?,?,?,?)",
                    (*v.ident, patient_id[v.patient], v.visit_class, v.type, v.reason, v.start, v.end))
                visit_id[v.ident] = vid
                c.executemany("INSERT INTO VisitLocation (VisitId, LocationId, StartDate, EndDate) VALUES (?,?,?,?)",
                              [(vid, loc_id[x.location], x.start, x.end) for x in v.locations])

            med_id = {m.key: self._insert(
                "INSERT INTO Medication (Code, CodeSystem, Name, Form, Manufacturer) VALUES (?,?,?,?,?)",
                (m.code, m.code_system, m.name, m.form, m.manufacturer)) for m in batch.medications}

            entry_id = {}
            for e in batch.entries:
                eid = self._insert(
                    "INSERT INTO ClinicalEntry (IdentifierSystem, IdentifierValue, VisitId, Category, Code, CodeSystem, "
                    "Display, Text, RecordedAt) VALUES (?,?,?,?,?,?,?,?,?)",
                    (*e.ident, visit_id[e.visit], e.category, e.code, e.code_system, e.display, e.text, e.recorded_at))
                entry_id[e.ident] = eid
                cols = SUBTYPE_COLUMNS[e.category]
                values = [e.details.get(col) for col in cols]
                if e.category == "Prescription":
                    sub = self._insert(
                        f"INSERT INTO Prescription (ClinicalEntryId, MedicationId, {', '.join(cols)}) "
                        f"VALUES (?,?,{','.join('?' * len(cols))})", (eid, med_id[e.medication], *values))
                else:
                    sub = self._insert(
                        f"INSERT INTO {e.category} (ClinicalEntryId, {', '.join(cols)}) "
                        f"VALUES (?,{','.join('?' * len(cols))})", (eid, *values))
                if e.category == "CareTeam":
                    members = {m.member: m for m in e.members}
                    c.executemany(
                        "INSERT INTO CareTeamMember (CareTeamId, MemberSystem, MemberValue, Role) VALUES (?,?,?,?)",
                        [(sub, *m.member, m.role) for m in members.values()])

            message_id = {m.ident: self._insert(
                "INSERT INTO Message (IdentifierSystem, IdentifierValue, StaffId, Channel, Origin, SentAt, Text) "
                "VALUES (?,?,?,?,?,?,?)",
                (*m.ident, staff_id[m.staff[0] + "|" + m.staff[1]] if m.staff else None, m.channel, m.origin,
                 m.sent_at, m.text)) for m in batch.messages}

            # Insert each superseded assertion before the assertion that supersedes it.
            by_key = {a.key: a for a in batch.assertions}
            assertion_id: dict[str, int] = {}

            def insert_assertion(a: d.Assertion) -> int:
                if a.key in assertion_id:
                    return assertion_id[a.key]
                old = insert_assertion(by_key[a.supersedes]) if a.supersedes else None
                aid = self._insert(
                    "INSERT INTO Assertion (MessageId, Seq, ClinicalEntryId, SupersedesId, AssertedAt, Intent, Source, "
                    "Verification, Statement) VALUES (?,?,?,?,?,?,?,?,?)",
                    (message_id[a.message], a.seq, entry_id[a.entry], old, a.asserted_at, a.intent, a.source,
                     a.verification, a.statement))
                assertion_id[a.key] = aid
                return aid

            for a in batch.assertions:
                insert_assertion(a)

            turn_id = {}
            for s in batch.chat_sessions:
                csid = self._insert(
                    "INSERT INTO ChatSession (IdentifierSystem, IdentifierValue, UserRole, UserSystem, UserValue, "
                    "SubjectName, SubjectDateOfBirth, StartedAt, Mode, Model) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (*s.ident, s.user_role, *s.user, *s.subject, s.started_at, s.mode, s.model))
                for t in s.turns:
                    tid = self._insert(
                        "INSERT INTO ChatTurn (ChatSessionId, Seq, ClientTurnId, Speaker, Text, CreatedAt) "
                        "VALUES (?,?,?,?,?,?)", (csid, t.seq, t.client_turn_id, t.speaker, t.text, t.created_at))
                    turn_id[(s.ident, t.seq)] = tid
                    c.executemany("INSERT INTO Citation (ChatTurnId, AssertionId, Rank) VALUES (?,?,?)",
                                  [(tid, assertion_id[key], rank) for key, rank in t.citations])
            for a in batch.audit_events:
                c.execute(
                    "INSERT INTO AuditEvent (IdentifierSystem, IdentifierValue, At, Action, Outcome, ActorRole, "
                    "ActorSystem, ActorValue, SubjectName, SubjectDateOfBirth, Path, ChatTurnId) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (*a.ident, a.at, a.action, a.outcome, a.actor_role, *a.actor, *a.subject, a.path,
                     turn_id[a.chat_turn] if a.chat_turn else None))
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
        return {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
