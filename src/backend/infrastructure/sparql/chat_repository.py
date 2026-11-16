"""Chat sessions, chat turns and citations on the knowledge graph (the ChatRepository port).

STUB: agent C writes this file. Each method has the signature of application/ports.py, and it must
give the same results as infrastructure/sqlite/chat_repository.py (SqliteChatRepository).
Follow the pattern of users_repository.py and README.md in this folder.
The port has 8 methods. Each one raises NotImplementedError until it is written.
"""
from __future__ import annotations

from typing import Optional, Sequence

from domain.access import Actor
from domain.views import ChatSessionSummary

from application.paging import Page, PageRequest
from application.ports import ChatSessionRow, ChatTurnRow
from infrastructure.sparql.unit_of_work import KgSession

AGENT = "agent C"


class SparqlChatRepository:
    """The ChatRepository port on SPARQL."""

    def __init__(self, session: KgSession):
        self.session = session

    def create_session(self, identifier: tuple[str, str], actor: Actor, subject: tuple[str, str], started_at: str,
                       mode: str, model: Optional[str]) -> int:
        raise NotImplementedError(AGENT)

    def session(self, session_id: int) -> Optional[ChatSessionRow]:
        raise NotImplementedError(AGENT)

    def sessions(self, actor: Actor, subject: tuple[str, str], page: PageRequest) -> Page[ChatSessionSummary]:
        raise NotImplementedError(AGENT)

    def turns(self, session_id: int) -> list[ChatTurnRow]:
        raise NotImplementedError(AGENT)

    def turn_by_client_id(self, session_id: int, client_turn_id: str) -> Optional[ChatTurnRow]:
        raise NotImplementedError(AGENT)

    def add_turn(self, session_id: int, client_turn_id: str, speaker: str, text: str, at: str) -> int:
        raise NotImplementedError(AGENT)

    def add_citations(self, turn_id: int, assertion_ids: Sequence[int]) -> None:
        raise NotImplementedError(AGENT)

    def next_identifier(self, system: str, prefix: str, width: int) -> str:
        raise NotImplementedError(AGENT)
