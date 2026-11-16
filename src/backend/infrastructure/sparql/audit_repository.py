"""The audit log on the knowledge graph (the AuditRepository port).

STUB: agent C writes this file. Each method has the signature of application/ports.py, and it must
give the same results as infrastructure/sqlite/chat_repository.py (SqliteAuditRepository).
Follow the pattern of users_repository.py and README.md in this folder.
The port has 3 methods. Each one raises NotImplementedError until it is written.
"""
from __future__ import annotations

from typing import Optional

from domain.access import Actor
from domain.views import AuditEventView

from application.paging import Page, PageRequest
from infrastructure.sparql.unit_of_work import KgSession

AGENT = "agent C"


class SparqlAuditRepository:
    """The AuditRepository port on SPARQL."""

    def __init__(self, session: KgSession):
        self.session = session

    def add(self, at: str, action: str, outcome: str, actor: Actor, subject: tuple[str, str], path: str,
            chat_turn_id: Optional[int] = None) -> int:
        raise NotImplementedError(AGENT)

    def for_subject(self, subject: tuple[str, str], page: PageRequest) -> Page[AuditEventView]:
        raise NotImplementedError(AGENT)

    def denied_count(self, subject: tuple[str, str]) -> int:
        raise NotImplementedError(AGENT)
