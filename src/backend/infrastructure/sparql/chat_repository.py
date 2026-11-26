"""Chat sessions, chat turns and citations on the knowledge graph (the ChatRepository port).

The same results as SqliteChatRepository (infrastructure/sqlite/chat_repository.py), on the terms of the
ontology (models/semantic/vocabulary.py):

    SQLite                                       knowledge graph
    ChatSession.IdentifierSystem, ...Value       ?s triad:identifierSystem, triad:identifierValue
    UserRole, UserSystem, UserValue              ?s triad:userRole, triad:userSystem, triad:userValue
    SubjectName, SubjectDateOfBirth              ?s triad:subjectName, triad:subjectDateOfBirth (xsd:date)
    StartedAt, Mode, Model                       ?s triad:startedAt (xsd:dateTime), triad:mode, triad:model
    ChatTurn.ChatSessionId                       ?s triad:includes ?t
    ChatTurn.Seq, ClientTurnId, Speaker, ...     ?t triad:seq, triad:clientTurnId, triad:speaker, triad:text,
                                                 triad:createdAt
    Citation (ChatTurnId, AssertionId, Rank)     ?c triad:byTurn ?t ; triad:citedAssertion ?a ; triad:rank
    AuditEvent.ChatTurnId, Action                ?e triad:inTurn ?t ; triad:action

The rules of the SQLite repository:
- A session keeps the user and the patient (the subject) as values. The patient of a session is the patient
  with that name and date of birth (None if no patient has them).
- The kind of a turn is the action ("ask" or "tell") of its first audit record (the smallest id) of the turn.
- The turns of a session are in the order of seq; the citations of a turn are in the order of rank.
- add_turn() gives the turn the next seq of its session (the largest stored seq + 1, and the turns of this
  write). The key (session, clientTurnId) makes a turn idempotent: the use case reads turn_by_client_id() first,
  and the key guard of ChatTurn (guards_directory.py) refuses a second turn with the same key (Conflict 409).
- add_citations() writes each assertion one time, with the rank 1, 2, ... in the order of the first place.
  The citation guard (guards_chat.py) holds TR_Citation_Check.
- sessions(): the newest session first (the instant of startedAt, then the largest id). Python makes this order
  (Virtuoso orders xsd:dateTime by the text, D11); one user has a small number of sessions about one patient.
  turnCount counts all turns; firstQuestion is the text of the User turn with the smallest seq.
"""
from __future__ import annotations

from typing import Optional, Sequence

from domain.access import Actor
from domain.views import ChatSessionSummary

from application.paging import Page, PageRequest
from application.ports import ChatSessionRow, ChatTurnRow
from infrastructure.sparql import ids, terms
from infrastructure.sparql.terms import id_of, iri
from infrastructure.sparql.unit_of_work import KgSession
from infrastructure.sparql.visits_repository import iri_list, newest_first, page_slice

SESSION = """
SELECT ?system ?value ?role ?userSystem ?userValue ?subjectName ?subjectDob ?startedAt ?mode ?model ?p
FROM $abox WHERE {
  $session a triad:ChatSession ; triad:identifierSystem ?system ; triad:identifierValue ?value ;
           triad:userRole ?role ; triad:userSystem ?userSystem ; triad:userValue ?userValue ;
           triad:subjectName ?subjectName ; triad:subjectDateOfBirth ?subjectDob ; triad:startedAt ?startedAt ;
           triad:mode ?mode .
  OPTIONAL { $session triad:model ?model }
  OPTIONAL { ?p triad:name ?subjectName ; triad:dateOfBirth ?subjectDob ; a triad:Patient . }
}"""

# The sessions of one user (role, system, value) about one patient (name, date of birth).
SESSIONS_OF = """
SELECT ?s ?startedAt FROM $abox WHERE {
  ?s triad:subjectName $name ; triad:subjectDateOfBirth $dob ; a triad:ChatSession ;
     triad:userValue $userValue ; triad:userSystem ?userSystem ; triad:userRole ?userRole ;
     triad:startedAt ?startedAt .
  FILTER (?userSystem = $userSystem && ?userRole = $userRole)
}"""

SESSION_SUMMARIES = """
SELECT ?s ?value ?startedAt ?mode FROM $abox WHERE {
  VALUES ?s { $sessions }
  ?s triad:identifierValue ?value ; triad:startedAt ?startedAt ; triad:mode ?mode .
}"""

# The turns of the sessions of a page: no text (firstQuestion reads the text of one turn for each session).
SESSION_TURNS = """
SELECT ?s ?t ?seq ?speaker FROM $abox WHERE {
  VALUES ?s { $sessions }
  ?s triad:includes ?t .
  ?t triad:seq ?seq ; triad:speaker ?speaker .
}"""

TURN_TEXTS = """
SELECT ?t ?text FROM $abox WHERE {
  VALUES ?t { $turns }
  ?t triad:text ?text .
}"""


def turns_query(one_turn: bool) -> str:
    """The turns of a session (or the one turn with $clientTurnId), with the actions of their audit records."""
    match = "\n  FILTER (?clientTurnId = $clientTurnId)" if one_turn else ""
    return f"""
SELECT ?t ?seq ?clientTurnId ?speaker ?text ?createdAt ?e ?kind FROM $abox WHERE {{
  $session triad:includes ?t .
  ?t triad:seq ?seq ; triad:clientTurnId ?clientTurnId ; triad:speaker ?speaker ; triad:text ?text ;
     triad:createdAt ?createdAt .{match}
  OPTIONAL {{ ?e triad:inTurn ?t ; triad:action ?kind . FILTER (?kind IN ("ask", "tell")) }}
}}"""


TURNS = turns_query(False)
ONE_TURN = turns_query(True)

CITATIONS = """
SELECT ?t ?c ?a ?rank FROM $abox WHERE {
  $session triad:includes ?t .
  ?c triad:byTurn ?t ; triad:citedAssertion ?a ; triad:rank ?rank .
}"""

LAST_SEQ = """
SELECT (MAX(?seq) AS ?last) FROM $abox WHERE {
  $session triad:includes ?t .
  ?t triad:seq ?seq .
}"""


def subject_bindings(subject: tuple[str, str]) -> dict:
    name, date_of_birth = subject
    return {"name": name, "dob": terms.date(date_of_birth)}


class SparqlChatRepository:
    """The ChatRepository port on SPARQL."""

    def __init__(self, session: KgSession):
        # Not "self.session": the port has the method session(). (The other repositories use self.session.)
        self.kg = session

    def create_session(self, identifier: tuple[str, str], actor: Actor, subject: tuple[str, str], started_at: str,
                       mode: str, model: Optional[str]) -> int:
        buf = self.kg.write_buffer()
        system, value = identifier
        name, date_of_birth = subject
        return buf.create("chat-session", {
            "identifierSystem": system, "identifierValue": value, "userRole": actor.role,
            "userSystem": actor.system, "userValue": actor.value, "subjectName": name,
            "subjectDateOfBirth": date_of_birth, "startedAt": started_at, "mode": mode, "model": model})

    def session(self, session_id: int) -> Optional[ChatSessionRow]:
        if session_id < 0:                  # no IRI has a negative id (SQLite: no row)
            return None
        rows = self.kg.select(SESSION, {"session": iri("chat-session", session_id)})
        if not rows:
            return None
        r = rows[0]
        return ChatSessionRow(id=session_id, identifier=r["value"], user_role=r["role"], user_system=r["userSystem"],
                              user_value=r["userValue"], subject_name=r["subjectName"],
                              subject_date_of_birth=r["subjectDob"], started_at=r["startedAt"], mode=r["mode"],
                              model=r["model"], patient_id=id_of(r["p"], "patient"))

    def _summaries(self, session_iris: list[str]) -> list[ChatSessionSummary]:
        if not session_iris:
            return []
        listed = iri_list(session_iris)
        values = {r["s"]: r for r in self.kg.select(SESSION_SUMMARIES, {"sessions": listed})}
        counts: dict[str, int] = {}
        first: dict[str, tuple[int, str]] = {}            # session -> (seq, turn) of the first User turn
        for r in self.kg.select(SESSION_TURNS, {"sessions": listed}):
            counts[r["s"]] = counts.get(r["s"], 0) + 1
            if r["speaker"] == "User" and (r["s"] not in first or r["seq"] < first[r["s"]][0]):
                first[r["s"]] = (r["seq"], r["t"])
        texts = {}
        if first:
            texts = {r["t"]: r["text"] for r in self.kg.select(
                TURN_TEXTS, {"turns": iri_list(sorted({t for _, t in first.values()}))})}
        out = []
        for s in session_iris:
            r = values.get(s)
            if r is None:
                continue
            question = texts.get(first[s][1]) if s in first else None
            out.append(ChatSessionSummary(id=id_of(s, "chat-session"), identifier=r["value"],
                                          started_at=r["startedAt"], mode=r["mode"], turn_count=counts.get(s, 0),
                                          first_question=question))
        return out

    def sessions(self, actor: Actor, subject: tuple[str, str], page: PageRequest) -> Page[ChatSessionSummary]:
        """One page of the sessions of the user about the patient, newest first."""
        rows = self.kg.select(SESSIONS_OF, {**subject_bindings(subject), "userRole": actor.role,
                                            "userSystem": actor.system, "userValue": actor.value})
        newest = newest_first(rows, lambda r: r["startedAt"], lambda r: id_of(r["s"], "chat-session"))
        found = [r["s"] for r in newest]
        return Page(items=self._summaries(page_slice(found, page)), total=len(found), limit=page.limit,
                    offset=page.offset)

    def _turns(self, session_id: int, client_turn_id: Optional[str] = None) -> list[ChatTurnRow]:
        session = iri("chat-session", session_id)
        if client_turn_id is None:
            found = self.kg.select(TURNS, {"session": session})
        else:
            found = self.kg.select(ONE_TURN, {"session": session, "clientTurnId": client_turn_id})
        turns: dict[str, dict] = {}
        kinds: dict[str, tuple[int, str]] = {}            # turn -> (audit id, action) of its first audit record
        for r in found:
            turns.setdefault(r["t"], r)
            if r["e"] is not None:
                event = id_of(r["e"], "audit-event")
                if r["t"] not in kinds or event < kinds[r["t"]][0]:
                    kinds[r["t"]] = (event, r["kind"])
        if not turns:
            return []
        cites: dict[str, list[tuple[int, int, int]]] = {}  # turn -> (rank, citation id, assertion id)
        for c in self.kg.select(CITATIONS, {"session": session}):
            if c["t"] in turns:
                cites.setdefault(c["t"], []).append((c["rank"], id_of(c["c"], "citation"), id_of(c["a"], "assertion")))
        rows = sorted(turns.values(), key=lambda r: (r["seq"], id_of(r["t"], "chat-turn")))
        return [ChatTurnRow(id=id_of(r["t"], "chat-turn"), seq=r["seq"], client_turn_id=r["clientTurnId"],
                            speaker=r["speaker"], text=r["text"], created_at=r["createdAt"],
                            kind=kinds[r["t"]][1] if r["t"] in kinds else None,
                            citations=[(a, rank) for rank, _, a in sorted(cites.get(r["t"], []))])
                for r in rows]

    def turns(self, session_id: int) -> list[ChatTurnRow]:
        if session_id < 0:
            return []
        return self._turns(session_id)

    def turn_by_client_id(self, session_id: int, client_turn_id: str) -> Optional[ChatTurnRow]:
        if session_id < 0:
            return None
        found = self._turns(session_id, client_turn_id)
        return found[0] if found else None

    def add_turn(self, session_id: int, client_turn_id: str, speaker: str, text: str, at: str) -> int:
        buf = self.kg.write_buffer()
        session = iri("chat-session", session_id)
        rows = self.kg.select(LAST_SEQ, {"session": session})
        stored = rows[0]["last"] if rows and rows[0].get("last") is not None else 0
        change = buf.change()                              # the turns of this write in the same session
        new = [turn.get("seq") for turn in buf.created("chat-turn")
               if (session, "includes") in change.links_to(turn.iri, "includes")]
        turn_id = buf.create("chat-turn", {"seq": max([int(stored), *new]) + 1, "clientTurnId": client_turn_id,
                                           "speaker": speaker, "text": text, "createdAt": at})
        buf.add(session, {"includes": iri("chat-turn", turn_id)})
        return turn_id

    def add_citations(self, turn_id: int, assertion_ids: Sequence[int]) -> None:
        buf = self.kg.write_buffer()
        for rank, assertion_id in enumerate(dict.fromkeys(assertion_ids), 1):
            buf.create("citation", {"byTurn": iri("chat-turn", turn_id),
                                    "citedAssertion": iri("assertion", assertion_id), "rank": rank})

    def next_identifier(self, system: str, prefix: str, width: int) -> str:
        return ids.next_identifier(self.kg, "chat-session", system, prefix, width)
