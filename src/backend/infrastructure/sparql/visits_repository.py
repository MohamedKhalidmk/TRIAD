"""Visits and their locations on the knowledge graph (the VisitRepository port).

STUB: agent C writes this file. Each method has the signature of application/ports.py, and it must
give the same results as infrastructure/sqlite/patients_repository.py (SqliteVisitRepository).
Follow the pattern of users_repository.py and README.md in this folder.
The port has 8 methods. Each one raises NotImplementedError until it is written.
"""
from __future__ import annotations

from typing import Optional

from domain.views import VisitView

from application.paging import Page, PageRequest
from infrastructure.sparql.unit_of_work import KgSession

AGENT = "agent C"


class SparqlVisitRepository:
    """The VisitRepository port on SPARQL."""

    def __init__(self, session: KgSession):
        self.session = session

    def for_patient_page(self, patient_id: int, page: PageRequest) -> Page[VisitView]:
        raise NotImplementedError(AGENT)

    def get(self, visit_id: int) -> Optional[VisitView]:
        raise NotImplementedError(AGENT)

    def open_visit_id(self, patient_id: int) -> Optional[int]:
        raise NotImplementedError(AGENT)

    def visit_rows(self, patient_id: int) -> list[tuple[int, str, str, Optional[str]]]:
        raise NotImplementedError(AGENT)

    def create(self, patient_id: int, identifier: tuple[str, str], visit_class: str, type_: Optional[str],
               reason: Optional[str], start: str, location_id: Optional[int], end: Optional[str] = None) -> int:
        raise NotImplementedError(AGENT)

    def move(self, visit_id: int, location_id: int, now: str) -> None:
        raise NotImplementedError(AGENT)

    def end(self, visit_id: int, now: str) -> None:
        raise NotImplementedError(AGENT)

    def next_identifier(self, system: str, prefix: str, width: int) -> str:
        raise NotImplementedError(AGENT)
