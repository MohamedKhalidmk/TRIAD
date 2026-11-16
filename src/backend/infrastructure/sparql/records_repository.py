"""Clinical entries, messages, assertions, chains and care teams on the knowledge graph (the RecordRepository port).

STUB: agent B writes this file. Each method has the signature of application/ports.py, and it must
give the same results as infrastructure/sqlite/records_repository.py (SqliteRecordRepository).
Follow the pattern of users_repository.py and README.md in this folder.
The port has 21 methods. Each one raises NotImplementedError until it is written.
"""
from __future__ import annotations

from typing import Optional, Sequence

from domain.views import AssertionView, CareTeamVersion

from application.paging import Page, PageRequest
from application.ports import EntryInfo, NewEntryRow
from infrastructure.sparql.unit_of_work import KgSession

AGENT = "agent B"


class SparqlRecordRepository:
    """The RecordRepository port on SPARQL."""

    def __init__(self, session: KgSession):
        self.session = session

    def items_page(self, patient_id: int, *, current_only: bool = True, visit_id: Optional[int] = None,
                   category: Optional[str] = None, text: Optional[str] = None, visible_only: bool = False,
                   date_from: Optional[str] = None, date_to: Optional[str] = None,
                   page: PageRequest) -> Page[AssertionView]:
        raise NotImplementedError(AGENT)

    def category_counts(self, patient_id: int, *, current_only: bool = True, visit_id: Optional[int] = None,
                        text: Optional[str] = None, visible_only: bool = False, date_from: Optional[str] = None,
                        date_to: Optional[str] = None) -> dict[str, int]:
        raise NotImplementedError(AGENT)

    def allergies(self, patient_id: int, *, words: Sequence[str] = (), visible_only: bool,
                  limit: int) -> list[AssertionView]:
        raise NotImplementedError(AGENT)

    def prescriptions(self, patient_id: int, *, current_status: bool, visible_only: bool,
                      limit: int) -> list[AssertionView]:
        raise NotImplementedError(AGENT)

    def diagnoses(self, patient_id: int, *, active_only: bool, visible_only: bool, limit: int) -> list[AssertionView]:
        raise NotImplementedError(AGENT)

    def lab_items(self, patient_id: int, *, words: Sequence[str] = (), visible_only: bool,
                  limit: int) -> list[AssertionView]:
        raise NotImplementedError(AGENT)

    def visit_items(self, patient_id: int, visit_id: int, categories: Sequence[str], *, visible_only: bool,
                    limit: int) -> list[AssertionView]:
        raise NotImplementedError(AGENT)

    def latest_observations(self, patient_id: int, codes: Sequence[str], *, visible_only: bool,
                            limit: int) -> list[AssertionView]:
        raise NotImplementedError(AGENT)

    def recommendations(self, patient_id: int, visit_id: int, *, author_role: Optional[str], visible_only: bool,
                        limit: int) -> list[AssertionView]:
        raise NotImplementedError(AGENT)

    def assertion(self, assertion_id: int) -> Optional[AssertionView]:
        raise NotImplementedError(AGENT)

    def assertions_by_id(self, ids: Sequence[int]) -> dict[int, AssertionView]:
        raise NotImplementedError(AGENT)

    def chain(self, assertion_id: int) -> list[AssertionView]:
        raise NotImplementedError(AGENT)

    def chain_page(self, assertion_id: int, page: PageRequest) -> Page[AssertionView]:
        raise NotImplementedError(AGENT)

    def chain_head(self, assertion_id: int) -> Optional[AssertionView]:
        raise NotImplementedError(AGENT)

    def entry(self, entry_id: int) -> Optional[EntryInfo]:
        raise NotImplementedError(AGENT)

    def add_message(self, identifier: tuple[str, str], staff_id: Optional[int], channel: str, origin: str,
                    sent_at: str, text: str) -> int:
        raise NotImplementedError(AGENT)

    def add_entry(self, identifier: tuple[str, str], entry: NewEntryRow) -> int:
        raise NotImplementedError(AGENT)

    def add_assertion(self, message_id: int, seq: int, entry_id: int, supersedes_id: Optional[int], at: str,
                      intent: str, source: str, verification: str, statement: str) -> int:
        raise NotImplementedError(AGENT)

    def medication_for(self, code: str, code_system: str, name: str) -> int:
        raise NotImplementedError(AGENT)

    def care_team_versions(self, visit_id: int) -> list[CareTeamVersion]:
        raise NotImplementedError(AGENT)

    def next_identifier(self, table: str, system: str, prefix: str, width: int) -> str:
        raise NotImplementedError(AGENT)
