"""Chat sessions, chat turns, citations and the audit log (the ChatRepository and AuditRepository ports).

A chat session and an audit record keep the user and the patient (Subject) as values, not as foreign keys.
"""
from __future__ import annotations

import sqlite3
from typing import Optional, Sequence

from domain.access import Actor
from domain.views import AuditEventView, ChatSessionSummary

from application.ports import ChatSessionRow, ChatTurnRow
from infrastructure import ids
from infrastructure.config import AUDIT_EVENT_SYSTEM

SESSION_SQL = """
SELECT cs.*, (SELECT p.Id FROM Patient p WHERE p.Name = cs.SubjectName AND p.DateOfBirth = cs.SubjectDateOfBirth)
       AS PatientId
FROM ChatSession cs
"""

# The kind of an assistant turn is the action of its audit record (InTurn): ask or tell.
TURN_SQL = """
SELECT t.Id, t.Seq, t.ClientTurnId, t.Speaker, t.Text, t.CreatedAt,
       (SELECT ae.Action FROM AuditEvent ae WHERE ae.ChatTurnId = t.Id AND ae.Action IN ('ask', 'tell')
        ORDER BY ae.Id LIMIT 1) AS Kind
FROM ChatTurn t
"""


class SqliteChatRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create_session(self, identifier: tuple[str, str], actor: Actor, subject: tuple[str, str], started_at: str,
                       mode: str, model: Optional[str]) -> int:
        return self.conn.execute(
            "INSERT INTO ChatSession (IdentifierSystem, IdentifierValue, UserRole, UserSystem, UserValue, SubjectName, "
            "SubjectDateOfBirth, StartedAt, Mode, Model) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (*identifier, actor.role, actor.system, actor.value, *subject, started_at, mode, model)).lastrowid

    def session(self, session_id: int) -> Optional[ChatSessionRow]:
        r = self.conn.execute(SESSION_SQL + " WHERE cs.Id = ?", (session_id,)).fetchone()
        if r is None:
            return None
        return ChatSessionRow(id=r["Id"], identifier=r["IdentifierValue"], user_role=r["UserRole"],
                              user_system=r["UserSystem"], user_value=r["UserValue"], subject_name=r["SubjectName"],
                              subject_date_of_birth=r["SubjectDateOfBirth"], started_at=r["StartedAt"],
                              mode=r["Mode"], model=r["Model"], patient_id=r["PatientId"])

    def sessions(self, actor: Actor, subject: tuple[str, str]) -> list[ChatSessionSummary]:
        rows = self.conn.execute("""
            SELECT cs.Id, cs.IdentifierValue, cs.StartedAt, cs.Mode,
                   (SELECT COUNT(*) FROM ChatTurn t WHERE t.ChatSessionId = cs.Id) AS TurnCount,
                   (SELECT t.Text FROM ChatTurn t WHERE t.ChatSessionId = cs.Id AND t.Speaker = 'User'
                    ORDER BY t.Seq LIMIT 1) AS FirstQuestion
            FROM ChatSession cs
            WHERE cs.UserRole = ? AND cs.UserSystem = ? AND cs.UserValue = ?
              AND cs.SubjectName = ? AND cs.SubjectDateOfBirth = ?
            ORDER BY julianday(cs.StartedAt) DESC, cs.Id DESC""",
                                 (actor.role, actor.system, actor.value, *subject))
        return [ChatSessionSummary(id=r["Id"], identifier=r["IdentifierValue"], started_at=r["StartedAt"],
                                   mode=r["Mode"], turn_count=r["TurnCount"], first_question=r["FirstQuestion"])
                for r in rows]

    def _turns(self, where: str, args: tuple) -> list[ChatTurnRow]:
        rows = self.conn.execute(TURN_SQL + where + " ORDER BY t.Seq", args).fetchall()
        if not rows:
            return []
        marks = ",".join("?" * len(rows))
        cites: dict[int, list[tuple[int, int]]] = {}
        for c in self.conn.execute(f"SELECT ChatTurnId, AssertionId, Rank FROM Citation WHERE ChatTurnId IN ({marks}) "
                                   "ORDER BY Rank", [r["Id"] for r in rows]):
            cites.setdefault(c["ChatTurnId"], []).append((c["AssertionId"], c["Rank"]))
        return [ChatTurnRow(id=r["Id"], seq=r["Seq"], client_turn_id=r["ClientTurnId"], speaker=r["Speaker"],
                            text=r["Text"], created_at=r["CreatedAt"], kind=r["Kind"], citations=cites.get(r["Id"], []))
                for r in rows]

    def turns(self, session_id: int) -> list[ChatTurnRow]:
        return self._turns(" WHERE t.ChatSessionId = ?", (session_id,))

    def turn_by_client_id(self, session_id: int, client_turn_id: str) -> Optional[ChatTurnRow]:
        found = self._turns(" WHERE t.ChatSessionId = ? AND t.ClientTurnId = ?", (session_id, client_turn_id))
        return found[0] if found else None

    def add_turn(self, session_id: int, client_turn_id: str, speaker: str, text: str, at: str) -> int:
        seq = self.conn.execute("SELECT COALESCE(MAX(Seq), 0) + 1 FROM ChatTurn WHERE ChatSessionId = ?",
                                (session_id,)).fetchone()[0]
        return self.conn.execute(
            "INSERT INTO ChatTurn (ChatSessionId, Seq, ClientTurnId, Speaker, Text, CreatedAt) VALUES (?,?,?,?,?,?)",
            (session_id, seq, client_turn_id, speaker, text, at)).lastrowid

    def add_citations(self, turn_id: int, assertion_ids: Sequence[int]) -> None:
        self.conn.executemany("INSERT INTO Citation (ChatTurnId, AssertionId, Rank) VALUES (?,?,?)",
                              [(turn_id, aid, rank) for rank, aid in enumerate(dict.fromkeys(assertion_ids), 1)])

    def next_identifier(self, system: str, prefix: str, width: int) -> str:
        return ids.next_identifier(self.conn, "ChatSession", system, prefix, width)


class SqliteAuditRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add(self, at: str, action: str, outcome: str, actor: Actor, subject: tuple[str, str], path: str,
            chat_turn_id: Optional[int] = None) -> int:
        value = ids.next_identifier(self.conn, "AuditEvent", AUDIT_EVENT_SYSTEM, "AUDIT-", 4)
        return self.conn.execute(
            "INSERT INTO AuditEvent (IdentifierSystem, IdentifierValue, At, Action, Outcome, ActorRole, ActorSystem, "
            "ActorValue, SubjectName, SubjectDateOfBirth, Path, ChatTurnId) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (AUDIT_EVENT_SYSTEM, value, at, action, outcome, actor.role, actor.system, actor.value, *subject, path,
             chat_turn_id)).lastrowid

    def for_subject(self, subject: tuple[str, str]) -> list[AuditEventView]:
        rows = self.conn.execute("""
            SELECT ae.*, COALESCE(s.Name, (SELECT pp.Name FROM PatientIdentifier pi
                                           JOIN Patient pp ON pp.Id = pi.PatientId
                                           WHERE pi.System = ae.ActorSystem AND pi.Value = ae.ActorValue)) AS ActorName
            FROM AuditEvent ae
            LEFT JOIN Staff s ON s.IdentifierSystem = ae.ActorSystem AND s.IdentifierValue = ae.ActorValue
            WHERE ae.SubjectName = ? AND ae.SubjectDateOfBirth = ?
            ORDER BY julianday(ae.At) DESC, ae.Id DESC""", subject)
        return [AuditEventView(id=r["Id"], identifier=r["IdentifierValue"], at=r["At"], action=r["Action"],
                               outcome=r["Outcome"], actor_role=r["ActorRole"],
                               actor_key=f"{r['ActorRole']}:{r['ActorValue']}", actor_name=r["ActorName"],
                               path=r["Path"], chat_turn_id=r["ChatTurnId"]) for r in rows]
