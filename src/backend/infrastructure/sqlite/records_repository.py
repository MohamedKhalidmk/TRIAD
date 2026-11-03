"""Clinical entries, messages, assertions and care teams (the RecordRepository port).

The read side uses the logic of the queries in dml/03_select_queries.sql:
- Q1: the current record is each assertion that no assertion supersedes (NOT EXISTS ... SupersedesId = a.Id);
- Q2: a chain follows Supersedes with WITH RECURSIVE;
- Q12: the patient-visible rule. PATIENT_VISIBLE is its WHERE predicate, and domain.rules.is_patient_visible
  is the same rule in Python. A test shows that both give the same rows for each patient;
- Q13: the current care team is a CareTeam entry with Status = 'active' whose assertion nothing supersedes;
- Q14: one page of the chart (ORDER BY the category, the newest first, the Id; LIMIT ? OFFSET ?).

The lookups of the Care Assistant tools (allergies, prescriptions, ...) use the same FROM clause and the same
filters as the chart, with more conditions, an ORDER BY and LIMIT ?. They never read the full chart.
"""
from __future__ import annotations

import sqlite3
from typing import Optional, Sequence

from domain.rules import author_label, is_patient_visible
from domain.views import AssertionView, Author, CareTeamMemberView, CareTeamVersion

from application.paging import Page, PageRequest
from application.ports import EntryInfo, NewEntryRow
from infrastructure import ids
from infrastructure.sqlite.paging import each_row, fetch_page, where

CURRENT = "NOT EXISTS (SELECT 1 FROM Assertion n2 WHERE n2.SupersedesId = a.Id)"

# The predicate of query Q12 (the patient-visible rule of USER_FLOWS.md section 2.1). It includes CURRENT.
PATIENT_VISIBLE = f"""({CURRENT}
    AND a.Verification <> 'EnteredInError'
    AND ((a.Intent = 'Decision' AND a.Source = 'Human' AND s.Role = 'Doctor')
         OR (e.Category IN ('Observation', 'LabReport') AND a.Verification = 'Confirmed')
         OR (m.StaffId IS NULL AND m.Origin = 'Patient')))"""

# The author name of an assertion: the staff member, or the patient for a patient report (as in author_of).
AUTHOR_NAME = "CASE WHEN m.StaffId IS NULL THEN p.Name ELSE s.Name END"

# The order of the chart: the categories in the order of the UI, then the newest first, then the Id.
CHART_CATEGORIES = ("Allergy", "Diagnosis", "Prescription", "Observation", "LabOrder", "LabReport", "Procedure",
                    "CareTeam")
CATEGORY_RANK = ("CASE e.Category " + " ".join(f"WHEN '{c}' THEN {i}" for i, c in enumerate(CHART_CATEGORIES))
                 + f" ELSE {len(CHART_CATEGORIES)} END")
CHART_ORDER = f"{CATEGORY_RANK}, julianday(a.AssertedAt) DESC, a.Id DESC"

# The subtype columns of each category: (column alias, key in AssertionView.details).
DETAIL_KEYS = {
    "Diagnosis": (("dg_OnsetDate", "onsetDate"), ("dg_AbatementDate", "abatementDate"),
                  ("dg_ClinicalStatus", "clinicalStatus"), ("dg_Severity", "severity")),
    "Procedure": (("pc_PerformedDate", "performedDate"), ("pc_Outcome", "outcome")),
    "Allergy": (("al_Substance", "substance"), ("al_Type", "type"), ("al_AllergyCategory", "allergyCategory"),
                ("al_Criticality", "criticality"), ("al_ClinicalStatus", "clinicalStatus")),
    "Observation": (("ob_Value", "value"), ("ob_Unit", "unit")),
    "LabOrder": (("lo_TestName", "testName"), ("lo_Priority", "priority"), ("lo_Specimen", "specimen")),
    "LabReport": (("lr_IssuedDate", "issuedDate"), ("lr_Conclusion", "conclusion")),
    "Prescription": (("pr_Medication", "medication"), ("pr_Dosage", "dosage"), ("pr_Frequency", "frequency"),
                     ("pr_Status", "status")),
    "CareTeam": (("ct_Name", "name"), ("ct_Status", "status"), ("ct_Members", "members")),
}

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

ASSERTION_COLUMNS = """
a.Id, a.ClinicalEntryId AS EntryId, a.MessageId, a.Seq, e.VisitId, v.PatientId, p.Name AS PatientName,
       e.Category, e.Code, e.CodeSystem, e.Display,
       a.Statement, a.Intent, a.Source, a.Verification, a.AssertedAt, a.SupersedesId, n.Id AS SupersededById,
       m.Channel, m.Origin, m.StaffId, s.Name AS StaffName, s.Role AS StaffRole,
       dg.OnsetDate AS dg_OnsetDate, dg.AbatementDate AS dg_AbatementDate, dg.ClinicalStatus AS dg_ClinicalStatus,
       dg.Severity AS dg_Severity,
       pc.PerformedDate AS pc_PerformedDate, pc.Outcome AS pc_Outcome,
       al.Substance AS al_Substance, al.Type AS al_Type, al.AllergyCategory AS al_AllergyCategory,
       al.Criticality AS al_Criticality, al.ClinicalStatus AS al_ClinicalStatus,
       ob.Value AS ob_Value, ob.Unit AS ob_Unit,
       lo.TestName AS lo_TestName, lo.Priority AS lo_Priority, lo.Specimen AS lo_Specimen,
       lr.IssuedDate AS lr_IssuedDate, lr.Conclusion AS lr_Conclusion,
       med.Name AS pr_Medication, pr.Dosage AS pr_Dosage, pr.Frequency AS pr_Frequency, pr.Status AS pr_Status,
       ct.Name AS ct_Name, ct.Status AS ct_Status,
       CASE WHEN ct.Id IS NULL THEN NULL ELSE
           (SELECT group_concat(COALESCE(ms.Name, ctm.MemberValue), ', ')
            FROM CareTeamMember ctm
            LEFT JOIN Staff ms ON ms.IdentifierSystem = ctm.MemberSystem AND ms.IdentifierValue = ctm.MemberValue
            WHERE ctm.CareTeamId = ct.Id) END AS ct_Members
"""

ASSERTION_FROM = """
FROM Visit v
JOIN Patient p ON p.Id = v.PatientId
JOIN ClinicalEntry e ON e.VisitId = v.Id
JOIN Assertion a ON a.ClinicalEntryId = e.Id
JOIN Message m ON m.Id = a.MessageId
LEFT JOIN Staff s ON s.Id = m.StaffId
LEFT JOIN Assertion n ON n.SupersedesId = a.Id
LEFT JOIN Diagnosis dg ON dg.ClinicalEntryId = e.Id
LEFT JOIN Procedure pc ON pc.ClinicalEntryId = e.Id
LEFT JOIN Allergy al ON al.ClinicalEntryId = e.Id
LEFT JOIN Observation ob ON ob.ClinicalEntryId = e.Id
LEFT JOIN LabOrder lo ON lo.ClinicalEntryId = e.Id
LEFT JOIN LabReport lr ON lr.ClinicalEntryId = e.Id
LEFT JOIN Prescription pr ON pr.ClinicalEntryId = e.Id
LEFT JOIN Medication med ON med.Id = pr.MedicationId
LEFT JOIN CareTeam ct ON ct.ClinicalEntryId = e.Id
"""

ASSERTION_SELECT = "SELECT " + ASSERTION_COLUMNS + ASSERTION_FROM

NEWEST_FIRST = " ORDER BY julianday(a.AssertedAt) DESC, a.Id DESC"

# An assertion that a clinician did not refute and that is not entered in error.
NOT_REFUTED = "a.Verification NOT IN ('Refuted', 'EnteredInError')"


def contains_words(text_sql: str, words: Sequence[str]) -> tuple[list[str], list[str]]:
    """One condition for each word: the word is in the text (case is not important). instr() has no wildcards."""
    return [f"instr(lower({text_sql}), ?) > 0" for _ in words], [w.lower() for w in words]

# Q2: from any assertion, go forward to the current one (the head of the chain).
FORWARD_CTE = """
WITH RECURSIVE forward (Id, Step) AS (
    SELECT ?, 0
    UNION ALL
    SELECT n.Id, f.Step + 1 FROM Assertion n JOIN forward f ON n.SupersedesId = f.Id
)"""

HEAD_SQL = FORWARD_CTE + " SELECT Id FROM forward ORDER BY Step DESC LIMIT 1"

# Q2: from the head, go back to the first assertion. Depth 0 is the head, so the order by Depth is newest first.
CHAIN_IDS = FORWARD_CTE + """,
chain (Id, SupersedesId, Depth) AS (
    SELECT a.Id, a.SupersedesId, 0 FROM Assertion a
    WHERE a.Id = (SELECT Id FROM forward ORDER BY Step DESC LIMIT 1)
    UNION ALL
    SELECT a.Id, a.SupersedesId, c.Depth + 1 FROM Assertion a JOIN chain c ON a.Id = c.SupersedesId
)
SELECT Id, Depth FROM chain"""

CHAIN_SQL = CHAIN_IDS + " ORDER BY Depth"


def author_of(source: str, origin: str, staff_id: Optional[int], staff_name: Optional[str],
              staff_role: Optional[str], patient_name: str) -> Author:
    return Author(name=staff_name if staff_id is not None else patient_name,
                  role=staff_role if staff_id is not None else "Patient", staff_id=staff_id,
                  label=author_label(source, origin, staff_id, staff_role))


def to_view(r: sqlite3.Row) -> AssertionView:
    is_current = r["SupersededById"] is None
    details = {key: r[col] for col, key in DETAIL_KEYS.get(r["Category"], ())}
    return AssertionView(
        id=r["Id"], entry_id=r["EntryId"], message_id=r["MessageId"], seq=r["Seq"], visit_id=r["VisitId"],
        category=r["Category"], code=r["Code"], code_system=r["CodeSystem"], display=r["Display"], details=details,
        statement=r["Statement"], intent=r["Intent"], source=r["Source"], verification=r["Verification"],
        asserted_at=r["AssertedAt"],
        author=author_of(r["Source"], r["Origin"], r["StaffId"], r["StaffName"], r["StaffRole"], r["PatientName"]),
        channel=r["Channel"], origin=r["Origin"], supersedes_id=r["SupersedesId"],
        superseded_by_id=r["SupersededById"], is_current=is_current,
        patient_visible=is_patient_visible(is_current=is_current, verification=r["Verification"], intent=r["Intent"],
                                           source=r["Source"], author_role=r["StaffRole"], staff_id=r["StaffId"],
                                           origin=r["Origin"], category=r["Category"]),
        patient_id=r["PatientId"])


class SqliteRecordRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ----- reads -----

    def assertions(self, patient_id: int, current_only: bool, visit_id: Optional[int] = None,
                   category: Optional[str] = None) -> list[AssertionView]:
        """All items of the patient, newest first (no page). It is not in the port: no use case reads the full
        chart. The tests use it as the reference of the lookups of the Care Assistant."""
        clauses, args = self._item_filters(patient_id, current_only, visit_id, category, None, False)
        return [to_view(r) for r in self.conn.execute(ASSERTION_SELECT + where(clauses) + NEWEST_FIRST, args)]

    @staticmethod
    def _item_filters(patient_id: int, current_only: bool, visit_id: Optional[int], category: Optional[str],
                      text: Optional[str], visible_only: bool) -> tuple[list[str], list]:
        """The WHERE conditions of the chart. A patient-visible item is always current (Q12)."""
        clauses, args = ["v.PatientId = ?"], [patient_id]
        if visible_only:
            clauses.append(PATIENT_VISIBLE)
        elif current_only:
            clauses.append(CURRENT)
        if visit_id is not None:
            clauses.append("e.VisitId = ?")
            args.append(visit_id)
        if category:
            # The unary + stops the use of the index on Category. The path of the patient (Visit, then
            # ClinicalEntry) is faster: the index finds the entries of all patients first.
            clauses.append("+e.Category = ?")
            args.append(category)
        if text:
            clauses.append(f"(lower(e.Display) LIKE ? OR lower(a.Statement) LIKE ? OR lower({AUTHOR_NAME}) LIKE ?)")
            args += [f"%{text.lower()}%"] * 3
        return clauses, args

    def items_page(self, patient_id: int, *, current_only: bool = True, visit_id: Optional[int] = None,
                   category: Optional[str] = None, text: Optional[str] = None, visible_only: bool = False,
                   page: PageRequest) -> Page[AssertionView]:
        """One page of the chart (query Q14), in the order of the chart.

        `text` searches the display, the statement and the author name (case is not important).
        `visible_only` keeps only the items that the patient can see (the predicate of Q12).
        """
        clauses, args = self._item_filters(patient_id, current_only, visit_id, category, text, visible_only)
        return fetch_page(self.conn, ASSERTION_COLUMNS, ASSERTION_FROM + where(clauses), args, CHART_ORDER, page,
                          each_row(to_view))

    def category_counts(self, patient_id: int, *, current_only: bool = True, visit_id: Optional[int] = None,
                        text: Optional[str] = None, visible_only: bool = False) -> dict[str, int]:
        """The number of items of each category for the filters of the chart. A category with no item is not in it."""
        clauses, args = self._item_filters(patient_id, current_only, visit_id, None, text, visible_only)
        rows = self.conn.execute(f"SELECT e.Category, COUNT(*) {ASSERTION_FROM}{where(clauses)} "
                                 f"GROUP BY e.Category ORDER BY {CATEGORY_RANK}", args)
        return {r[0]: r[1] for r in rows}

    # ----- the lookups of the Care Assistant tools (one query each, with LIMIT ?) -----

    def _lookup(self, patient_id: int, conditions: Sequence[str], args: Sequence, *, visible_only: bool,
                limit: int, current_only: bool = True, visit_id: Optional[int] = None,
                category: Optional[str] = None, order_by: str = "julianday(a.AssertedAt) DESC, a.Id DESC",
                order_args: Sequence = ()) -> list[AssertionView]:
        """The items of the chart filters and the extra `conditions`, in the order `order_by`, at most `limit`."""
        clauses, values = self._item_filters(patient_id, current_only, visit_id, category, None, visible_only)
        sql = f"{ASSERTION_SELECT}{where([*clauses, *conditions])} ORDER BY {order_by} LIMIT ?"
        return [to_view(r) for r in self.conn.execute(sql, (*values, *args, *order_args, limit))]

    def allergies(self, patient_id: int, *, words: Sequence[str] = (), visible_only: bool,
                  limit: int) -> list[AssertionView]:
        conditions, args = contains_words("e.Display || ' ' || COALESCE(al.Substance, '')", words)
        return self._lookup(patient_id, conditions, args, category="Allergy", visible_only=visible_only,
                            limit=limit)

    def prescriptions(self, patient_id: int, *, current_status: bool, visible_only: bool,
                      limit: int) -> list[AssertionView]:
        conditions = ["pr.Status IN ('active', 'draft')", NOT_REFUTED] if current_status else []
        return self._lookup(patient_id, conditions, (), category="Prescription", visible_only=visible_only,
                            limit=limit)

    def diagnoses(self, patient_id: int, *, active_only: bool, visible_only: bool, limit: int) -> list[AssertionView]:
        conditions = ["(dg.ClinicalStatus IS NULL OR dg.ClinicalStatus IN ('active', 'recurrence', 'relapse'))",
                      NOT_REFUTED] if active_only else []
        return self._lookup(patient_id, conditions, (), category="Diagnosis", visible_only=visible_only,
                            limit=limit)

    def lab_items(self, patient_id: int, *, words: Sequence[str] = (), visible_only: bool,
                  limit: int) -> list[AssertionView]:
        conditions, args = contains_words(
            "e.Display || ' ' || COALESCE(lo.TestName, '') || ' ' || COALESCE(lr.Conclusion, '')", words)
        return self._lookup(patient_id, ["+e.Category IN ('LabOrder', 'LabReport')", *conditions], args,
                            visible_only=visible_only, limit=limit)

    def visit_items(self, patient_id: int, visit_id: int, categories: Sequence[str], *, visible_only: bool,
                    limit: int) -> list[AssertionView]:
        marks = ",".join("?" * len(categories))
        rank = "CASE e.Category " + " ".join(f"WHEN ? THEN {i}" for i in range(len(categories))) + " END"
        return self._lookup(patient_id, [f"+e.Category IN ({marks})"], categories, visit_id=visit_id,
                            visible_only=visible_only, limit=limit,
                            order_by=f"{rank}, julianday(a.AssertedAt) DESC, a.Id DESC", order_args=categories)

    def latest_observations(self, patient_id: int, codes: Sequence[str], *, visible_only: bool,
                            limit: int) -> list[AssertionView]:
        clauses, args = self._item_filters(patient_id, True, None, "Observation", None, visible_only)
        clauses.append(f"e.Code IN ({','.join('?' * len(codes))})")
        sql = (f"SELECT * FROM (SELECT {ASSERTION_COLUMNS}, ROW_NUMBER() OVER (PARTITION BY e.Code "
               f"ORDER BY julianday(a.AssertedAt) DESC, a.Id DESC) AS CodeRank {ASSERTION_FROM}{where(clauses)}) "
               "WHERE CodeRank = 1 ORDER BY julianday(AssertedAt) DESC, Id DESC LIMIT ?")
        return [to_view(r) for r in self.conn.execute(sql, (*args, *codes, limit))]

    def recommendations(self, patient_id: int, visit_id: int, *, author_role: Optional[str], visible_only: bool,
                        limit: int) -> list[AssertionView]:
        conditions, args = ["a.Intent = 'Recommendation'"], []
        if author_role:
            conditions.append("s.Role = ?")
            args.append(author_role)
        return self._lookup(patient_id, conditions, args, current_only=False, visit_id=visit_id,
                            visible_only=visible_only, limit=limit, order_by="a.AssertedAt, a.Seq, a.Id DESC")

    def assertions_by_id(self, ids_: Sequence[int]) -> dict[int, AssertionView]:
        out: dict[int, AssertionView] = {}
        unique = list(dict.fromkeys(ids_))
        for start in range(0, len(unique), 500):
            part = unique[start:start + 500]
            sql = ASSERTION_SELECT + f" WHERE a.Id IN ({','.join('?' * len(part))})"
            out.update({r["Id"]: to_view(r) for r in self.conn.execute(sql, part)})
        return out

    def assertion(self, assertion_id: int) -> Optional[AssertionView]:
        return self.assertions_by_id([assertion_id]).get(assertion_id)

    def chain(self, assertion_id: int) -> list[AssertionView]:
        order = [r["Id"] for r in self.conn.execute(CHAIN_SQL, (assertion_id,))]
        found = self.assertions_by_id(order)
        return [found[i] for i in order if i in found]

    def chain_page(self, assertion_id: int, page: PageRequest) -> Page[AssertionView]:
        """One page of the chain of an assertion, newest first (the head first)."""
        source = f"{ASSERTION_FROM} JOIN ({CHAIN_IDS}) c ON c.Id = a.Id"
        return fetch_page(self.conn, ASSERTION_COLUMNS, source, (assertion_id,), "c.Depth, a.Id", page,
                          each_row(to_view))

    def chain_head(self, assertion_id: int) -> Optional[AssertionView]:
        """The current assertion (the head) of the chain of an assertion."""
        row = self.conn.execute(HEAD_SQL, (assertion_id,)).fetchone()
        return self.assertion(row[0]) if row else None

    def entry(self, entry_id: int) -> Optional[EntryInfo]:
        r = self.conn.execute(
            "SELECT e.Id, v.PatientId, e.VisitId, e.Category, "
            f"(SELECT a.Id FROM Assertion a WHERE a.ClinicalEntryId = e.Id AND {CURRENT} "
            "ORDER BY a.Id DESC LIMIT 1) AS HeadId "
            "FROM ClinicalEntry e JOIN Visit v ON v.Id = e.VisitId WHERE e.Id = ?", (entry_id,)).fetchone()
        if r is None:
            return None
        return EntryInfo(id=r["Id"], patient_id=r["PatientId"], visit_id=r["VisitId"], category=r["Category"],
                         head_id=r["HeadId"])

    # ----- writes (inside a unit of work) -----

    def add_message(self, identifier: tuple[str, str], staff_id: Optional[int], channel: str, origin: str,
                    sent_at: str, text: str) -> int:
        return self.conn.execute(
            "INSERT INTO Message (IdentifierSystem, IdentifierValue, StaffId, Channel, Origin, SentAt, Text) "
            "VALUES (?,?,?,?,?,?,?)", (*identifier, staff_id, channel, origin, sent_at, text)).lastrowid

    def add_entry(self, identifier: tuple[str, str], entry: NewEntryRow) -> int:
        entry_id = self.conn.execute(
            "INSERT INTO ClinicalEntry (IdentifierSystem, IdentifierValue, VisitId, Category, Code, CodeSystem, "
            "Display, Text, RecordedAt) VALUES (?,?,?,?,?,?,?,?,?)",
            (*identifier, entry.visit_id, entry.category, entry.code, entry.code_system, entry.display, entry.text,
             entry.recorded_at)).lastrowid
        columns = SUBTYPE_COLUMNS[entry.category]
        values = [entry.details.get(c) for c in columns]
        if entry.category == "Prescription":
            self.conn.execute(
                f"INSERT INTO Prescription (ClinicalEntryId, MedicationId, {', '.join(columns)}) "
                f"VALUES (?,?,{','.join('?' * len(columns))})", (entry_id, entry.medication_id, *values))
        else:
            sub_id = self.conn.execute(
                f"INSERT INTO {entry.category} (ClinicalEntryId, {', '.join(columns)}) "
                f"VALUES (?,{','.join('?' * len(columns))})", (entry_id, *values)).lastrowid
            if entry.category == "CareTeam":
                self.conn.executemany(
                    "INSERT INTO CareTeamMember (CareTeamId, MemberSystem, MemberValue, Role) VALUES (?,?,?,?)",
                    [(sub_id, system, value, role) for system, value, role in entry.members])
        return entry_id

    def add_assertion(self, message_id: int, seq: int, entry_id: int, supersedes_id: Optional[int], at: str,
                      intent: str, source: str, verification: str, statement: str) -> int:
        return self.conn.execute(
            "INSERT INTO Assertion (MessageId, Seq, ClinicalEntryId, SupersedesId, AssertedAt, Intent, Source, "
            "Verification, Statement) VALUES (?,?,?,?,?,?,?,?,?)",
            (message_id, seq, entry_id, supersedes_id, at, intent, source, verification, statement)).lastrowid

    def medication_for(self, code: str, code_system: str, name: str) -> int:
        """The Medication with this (code, system). Add it if it does not exist."""
        row = self.conn.execute("SELECT Id FROM Medication WHERE Code = ? AND CodeSystem = ?",
                                (code, code_system)).fetchone()
        if row:
            return row[0]
        return self.conn.execute("INSERT INTO Medication (Code, CodeSystem, Name) VALUES (?,?,?)",
                                 (code, code_system, name)).lastrowid

    def next_identifier(self, table: str, system: str, prefix: str, width: int) -> str:
        return ids.next_identifier(self.conn, table, system, prefix, width)

    # ----- care teams -----

    def care_team_versions(self, visit_id: int) -> list[CareTeamVersion]:
        """The chain of the newest care-team head of the visit, newest first."""
        head = self.conn.execute(
            "SELECT a.Id FROM Assertion a JOIN ClinicalEntry e ON e.Id = a.ClinicalEntryId "
            f"WHERE e.VisitId = ? AND e.Category = 'CareTeam' AND {CURRENT} "
            "ORDER BY julianday(a.AssertedAt) DESC, a.Id DESC LIMIT 1", (visit_id,)).fetchone()
        if head is None:
            return []
        chain = self.chain(head[0])
        entry_ids = [a.entry_id for a in chain]
        marks = ",".join("?" * len(entry_ids))
        members: dict[int, list[CareTeamMemberView]] = {}
        for r in self.conn.execute(f"""
                SELECT ct.ClinicalEntryId, ctm.MemberSystem, ctm.MemberValue, ctm.Role, s.Id AS StaffId, s.Name,
                       s.Role AS StaffRole,
                       (SELECT d.Name FROM WorksIn w JOIN Department d ON d.Id = w.DepartmentId
                        WHERE w.StaffId = s.Id ORDER BY w.Id LIMIT 1) AS Department
                FROM CareTeam ct
                JOIN CareTeamMember ctm ON ctm.CareTeamId = ct.Id
                LEFT JOIN Staff s ON s.IdentifierSystem = ctm.MemberSystem AND s.IdentifierValue = ctm.MemberValue
                WHERE ct.ClinicalEntryId IN ({marks}) ORDER BY ctm.Id""", entry_ids):
            members.setdefault(r["ClinicalEntryId"], []).append(CareTeamMemberView(
                system=r["MemberSystem"], value=r["MemberValue"], role=r["Role"], staff_id=r["StaffId"],
                name=r["Name"] or r["MemberValue"], staff_role=r["StaffRole"], department=r["Department"]))
        out = []
        for depth, a in enumerate(chain):
            status = a.details.get("status") or "active"
            out.append(CareTeamVersion(entry_id=a.entry_id, assertion_id=a.id, visit_id=a.visit_id,
                                       name=a.details.get("name"), status=status,
                                       members=members.get(a.entry_id, []), author=a.author,
                                       asserted_at=a.asserted_at, is_current=depth == 0 and status == "active"))
        return out
