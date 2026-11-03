"""Ports (interfaces) of the application layer. The infrastructure layer implements them.

The application layer uses only these Protocols. It does not know SQLite, FastAPI or LiteLLM.
Each list method for the API takes a PageRequest and gives a Page (doc/api.md section 1.5).
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Optional, Protocol, Sequence

from domain.access import Actor
from domain.records import Address, OnboardBatch
from domain.views import (AssertionView, AuditEventView, CareTeamVersion, ChatSessionSummary, DepartmentView,
                          LocationView, MedicationView, PatientSummary, PatientView, StaffView, UserView, VisitView)

from application.paging import Page, PageRequest


# ----- onboarding (Phase 4) -----

class OnboardingSource(Protocol):
    """Gives the records of one onboarding run (for example, from FHIR files)."""

    def load_batch(self) -> OnboardBatch: ...


class OnboardingStore(Protocol):
    """Writes a batch of records in one transaction and returns the row count of each table."""

    def write(self, batch: OnboardBatch) -> dict[str, int]: ...


# ----- rows that the repositories give back -----

@dataclass
class EntryInfo:
    id: int
    patient_id: int
    visit_id: int
    category: str
    head_id: Optional[int]          # the current assertion of the entry, or None


@dataclass
class NewEntryRow:
    """A new clinical entry with its subtype values (the names of the subtype columns)."""
    visit_id: int
    category: str
    code: str
    code_system: str
    display: str
    text: Optional[str]
    recorded_at: str
    details: dict = field(default_factory=dict)
    medication_id: Optional[int] = None              # Prescription
    members: list[tuple[str, str, Optional[str]]] = field(default_factory=list)  # CareTeam


@dataclass
class ChatSessionRow:
    id: int
    identifier: str
    user_role: str
    user_system: str
    user_value: str
    subject_name: str
    subject_date_of_birth: str
    started_at: str
    mode: str
    model: Optional[str]
    patient_id: Optional[int]


@dataclass
class ChatTurnRow:
    id: int
    seq: int
    client_turn_id: str
    speaker: str
    text: str
    created_at: str
    kind: Optional[str]                              # the audit action of the turn: ask or tell
    citations: list[tuple[int, int]] = field(default_factory=list)  # (assertion id, rank)


@dataclass
class ExtractedFact:
    """One fact that an extractor found in a "tell" turn."""
    category: str
    code: str
    code_system: str
    display: str
    statement: str
    details: dict = field(default_factory=dict)


# ----- the unit of work and the clock -----

class UnitOfWork(Protocol):
    def write(self) -> AbstractContextManager[str]:
        """Start a write transaction (BEGIN IMMEDIATE). Gives the time of the write. Commits at the end."""
        ...

    def now(self) -> str:
        """The current demo time (no write)."""
        ...


# ----- repositories -----

class UserRepository(Protocol):
    def actor(self, role: str, value: str) -> Optional[Actor]: ...
    def user(self, role: str, value: str, pinned_keys: Sequence[str]) -> Optional[UserView]: ...
    def users(self, role: Optional[str], q: Optional[str], pinned_keys: Sequence[str],
              page: PageRequest) -> Page[UserView]: ...


class PatientRepository(Protocol):
    def get(self, patient_id: int) -> Optional[PatientView]: ...
    def search(self, q: Optional[str], dob: Optional[str], scope: str, member: Optional[tuple[str, str]],
               page: PageRequest) -> Page[PatientSummary]: ...
    def key_exists(self, name: str, date_of_birth: str) -> bool: ...
    def create(self, name: str, date_of_birth: str, sex: str, phone: Optional[str], address: Address,
               identifiers: list[tuple[str, str]]) -> int: ...
    def update(self, patient_id: int, changes: dict) -> None: ...
    def has_visits(self, patient_id: int) -> bool: ...
    def delete(self, patient_id: int) -> None: ...
    def on_care_team(self, patient_id: int, system: str, value: str) -> bool: ...
    def next_identifier(self, system: str, prefix: str, width: int) -> str: ...


class VisitRepository(Protocol):
    def for_patient_page(self, patient_id: int, page: PageRequest) -> Page[VisitView]: ...
    def get(self, visit_id: int) -> Optional[VisitView]: ...
    def open_visit_id(self, patient_id: int) -> Optional[int]: ...
    def visit_rows(self, patient_id: int) -> list[tuple[int, str, str, Optional[str]]]: ...
    def create(self, patient_id: int, identifier: tuple[str, str], visit_class: str, type_: Optional[str],
               reason: Optional[str], start: str, location_id: Optional[int], end: Optional[str] = None) -> int: ...
    def move(self, visit_id: int, location_id: int, now: str) -> None: ...
    def end(self, visit_id: int, now: str) -> None: ...
    def next_identifier(self, system: str, prefix: str, width: int) -> str: ...


class RecordRepository(Protocol):
    def items_page(self, patient_id: int, *, current_only: bool = True, visit_id: Optional[int] = None,
                   category: Optional[str] = None, text: Optional[str] = None, visible_only: bool = False,
                   page: PageRequest) -> Page[AssertionView]:
        """One page of the chart, in the order of the chart (the category, the newest first, the Id).

        `text` searches the display, the statement and the author name. `visible_only` keeps only the
        patient-visible items (the predicate of query Q12, in SQL).
        """
        ...
    def category_counts(self, patient_id: int, *, current_only: bool = True, visit_id: Optional[int] = None,
                        text: Optional[str] = None, visible_only: bool = False) -> dict[str, int]:
        """The number of items of each category for the same filters (no category filter)."""
        ...
    # The lookups of the Care Assistant tools. Each one is one query with a WHERE clause on the patient and the
    # filters, an ORDER BY and LIMIT ?. `visible_only` keeps only the patient-visible items (Q12, in SQL).
    # `words`: each word must be in the text of the item (case is not important).
    def allergies(self, patient_id: int, *, words: Sequence[str] = (), visible_only: bool,
                  limit: int) -> list[AssertionView]:
        """The current allergy items, newest first. The words are in the display or the substance."""
        ...
    def prescriptions(self, patient_id: int, *, current_status: bool, visible_only: bool,
                      limit: int) -> list[AssertionView]:
        """The current prescription items, newest first.

        `current_status`: only the status active or draft, and not refuted or entered in error.
        """
        ...
    def diagnoses(self, patient_id: int, *, active_only: bool, visible_only: bool, limit: int) -> list[AssertionView]:
        """The current diagnosis items, newest first.

        `active_only`: only a clinical status that is empty, active, recurrence or relapse, and not refuted
        or entered in error.
        """
        ...
    def lab_items(self, patient_id: int, *, words: Sequence[str] = (), visible_only: bool,
                  limit: int) -> list[AssertionView]:
        """The current lab orders and lab results, newest first. The words are in the display, the test name
        or the conclusion."""
        ...
    def visit_items(self, patient_id: int, visit_id: int, categories: Sequence[str], *, visible_only: bool,
                    limit: int) -> list[AssertionView]:
        """The current items of the categories in one visit: in the order of `categories`, then newest first."""
        ...
    def latest_observations(self, patient_id: int, codes: Sequence[str], *, visible_only: bool,
                            limit: int) -> list[AssertionView]:
        """The newest current observation of each code (ROW_NUMBER() OVER (PARTITION BY the code)), newest first."""
        ...
    def recommendations(self, patient_id: int, visit_id: int, *, author_role: Optional[str], visible_only: bool,
                        limit: int) -> list[AssertionView]:
        """The recommendations of one visit, current and superseded, oldest first (the time, then Seq)."""
        ...
    def assertion(self, assertion_id: int) -> Optional[AssertionView]: ...
    def assertions_by_id(self, ids: Sequence[int]) -> dict[int, AssertionView]: ...
    def chain(self, assertion_id: int) -> list[AssertionView]: ...                 # all, newest first
    def chain_page(self, assertion_id: int, page: PageRequest) -> Page[AssertionView]: ...
    def chain_head(self, assertion_id: int) -> Optional[AssertionView]: ...
    def entry(self, entry_id: int) -> Optional[EntryInfo]: ...
    def add_message(self, identifier: tuple[str, str], staff_id: Optional[int], channel: str, origin: str,
                    sent_at: str, text: str) -> int: ...
    def add_entry(self, identifier: tuple[str, str], entry: NewEntryRow) -> int: ...
    def add_assertion(self, message_id: int, seq: int, entry_id: int, supersedes_id: Optional[int], at: str,
                      intent: str, source: str, verification: str, statement: str) -> int: ...
    def medication_for(self, code: str, code_system: str, name: str) -> int: ...
    def care_team_versions(self, visit_id: int) -> list[CareTeamVersion]: ...
    def next_identifier(self, table: str, system: str, prefix: str, width: int) -> str: ...


class ChatRepository(Protocol):
    def create_session(self, identifier: tuple[str, str], actor: Actor, subject: tuple[str, str], started_at: str,
                       mode: str, model: Optional[str]) -> int: ...
    def session(self, session_id: int) -> Optional[ChatSessionRow]: ...
    def sessions(self, actor: Actor, subject: tuple[str, str], page: PageRequest) -> Page[ChatSessionSummary]: ...
    def turns(self, session_id: int) -> list[ChatTurnRow]: ...
    def turn_by_client_id(self, session_id: int, client_turn_id: str) -> Optional[ChatTurnRow]: ...
    def add_turn(self, session_id: int, client_turn_id: str, speaker: str, text: str, at: str) -> int: ...
    def add_citations(self, turn_id: int, assertion_ids: Sequence[int]) -> None: ...
    def next_identifier(self, system: str, prefix: str, width: int) -> str: ...


class AuditRepository(Protocol):
    def add(self, at: str, action: str, outcome: str, actor: Actor, subject: tuple[str, str], path: str,
            chat_turn_id: Optional[int] = None) -> int: ...
    def for_subject(self, subject: tuple[str, str], page: PageRequest) -> Page[AuditEventView]: ...
    def denied_count(self, subject: tuple[str, str]) -> int: ...


class DirectoryRepository(Protocol):
    # departments
    def departments(self, q: Optional[str], page: PageRequest) -> Page[DepartmentView]: ...
    def department(self, department_id: int) -> Optional[DepartmentView]: ...
    def department_by_name(self, name: str) -> Optional[DepartmentView]: ...
    def department_name_exists(self, name: str, except_id: Optional[int] = None) -> bool: ...
    def add_department(self, values: dict) -> int: ...
    def update_department(self, department_id: int, values: dict) -> None: ...
    def delete_department(self, department_id: int) -> None: ...
    def department_use(self, department_id: int) -> tuple[int, int]: ...
    # locations
    def locations(self, department: Optional[str], q: Optional[str], page: PageRequest) -> Page[LocationView]: ...
    def location(self, location_id: int) -> Optional[LocationView]: ...
    def location_by_identifier(self, system: str, value: str) -> Optional[LocationView]: ...
    def add_location(self, values: dict) -> int: ...
    def update_location(self, location_id: int, values: dict) -> None: ...
    def delete_location(self, location_id: int) -> None: ...
    # staff
    def staff_list(self, role: Optional[str], department: Optional[str], q: Optional[str],
                   page: PageRequest) -> Page[StaffView]: ...
    def staff(self, staff_id: int) -> Optional[StaffView]: ...
    def staff_by_identifier(self, system: str, value: str) -> Optional[StaffView]: ...
    def add_staff(self, values: dict) -> int: ...
    def update_staff(self, staff_id: int, values: dict) -> None: ...
    def staff_use(self, staff_id: int) -> dict[str, int]: ...
    def delete_staff(self, staff_id: int) -> None: ...
    # medications
    def medications(self, q: Optional[str], page: PageRequest) -> Page[MedicationView]: ...
    def medication(self, medication_id: int) -> Optional[MedicationView]: ...
    def add_medication(self, values: dict) -> int: ...
    def update_medication(self, medication_id: int, values: dict) -> None: ...
    def medication_in_use(self, medication_id: int) -> bool: ...
    def delete_medication(self, medication_id: int) -> None: ...
    # identifiers
    def unique_identifier(self, table: str, system: str, base: str) -> str: ...
    def next_identifier(self, table: str, system: str, prefix: str, width: int) -> str: ...


# ----- the language model -----

@dataclass(frozen=True)
class ToolDefinition:
    """One tool that the model can call: the name, the description and the JSON Schema of the arguments."""
    name: str
    description: str
    parameters: dict


@dataclass(frozen=True)
class ToolCall:
    """One tool call that the model asks for. `arguments` is the JSON text that the model gave.

    `call_id` identifies the call in the conversation with the model (the provider or the fake model gives it).
    It is not the id of a record. `provider_data` is data of the provider that must go back with the call
    (for example a thought signature). The application does not read it.
    """
    call_id: str
    name: str
    arguments: str
    provider_data: dict = field(default_factory=dict)


@dataclass
class ChatMessage:
    """One message of the conversation with the model. The role is system, user, assistant or tool.

    Only `content`, `tool_calls`, `tool_call_id` and `name` go to the model. `result` is the server-side
    result of a tool message (the items with their ids). It never goes to the model. Only the fake model reads it.
    """
    role: str
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()        # an assistant message that asks for tools
    tool_call_id: Optional[str] = None           # a tool message: the call that it answers
    name: Optional[str] = None                   # a tool message: the name of the tool
    result: Optional[object] = None              # a tool message: the server-side result (not for the model)


@dataclass
class ToolCalls:
    """The step of the model is one or more tool calls. `text` is the text that the model gave with them."""
    calls: list[ToolCall]
    text: str = ""


@dataclass
class FinalText:
    """The step of the model is the final answer, with a reference such as [E1] after each fact."""
    text: str


class LanguageModel(Protocol):
    """Selects the tools and writes the answer of an "ask" turn, and extracts the facts of a "tell" turn.

    The fake model needs no network.
    """

    def next_step(self, messages: Sequence[ChatMessage], tools: Sequence[ToolDefinition]) -> ToolCalls | FinalText:
        """The next step of the conversation: tool calls, or the final text."""
        ...
    def extract_facts(self, text: str, speaker_role: str) -> list[ExtractedFact]: ...
