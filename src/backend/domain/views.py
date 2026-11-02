"""Read models of TRIAD: what the application gives to the API layer.

The fields follow the types of doc/api.md section 2, in snake_case. The API layer writes them in camelCase.
These records have no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from domain.records import Address

Details = dict[str, Optional[object]]


@dataclass
class Identifier:
    system: str
    value: str


@dataclass
class UserView:
    key: str
    role: str
    name: str
    detail: str
    pinned: bool
    patient_id: Optional[int]
    staff_id: Optional[int]


@dataclass
class Permissions:
    view_chart: bool = False
    chat: bool = False
    tell: bool = False
    edit_demographics: bool = False
    check_in: bool = False
    end_visit: bool = False
    move_location: bool = False
    manage_care_team: bool = False
    view_audit: bool = False
    record_intents: list[str] = field(default_factory=list)


@dataclass
class PatientSummary:
    id: int
    name: str
    date_of_birth: str
    sex: str
    phone_number: Optional[str]
    open_visit_id: Optional[int]


@dataclass
class PatientView(PatientSummary):
    address: Address = field(default_factory=Address)
    identifiers: list[Identifier] = field(default_factory=list)
    permissions: Permissions = field(default_factory=Permissions)


@dataclass
class VisitLocationView:
    location_id: int
    name: str
    department: Optional[str]
    start_date: str
    end_date: Optional[str]


@dataclass
class VisitView:
    id: int
    patient_id: int
    identifier: Identifier
    visit_class: str
    type: Optional[str]
    reason: Optional[str]
    start_date: str
    end_date: Optional[str]
    is_open: bool
    department: Optional[str]
    locations: list[VisitLocationView] = field(default_factory=list)


@dataclass
class Author:
    name: str
    role: str
    staff_id: Optional[int]
    label: str


@dataclass
class AssertionView:
    id: int
    entry_id: int
    message_id: int
    seq: int
    visit_id: int
    category: str
    code: str
    code_system: str
    display: str
    details: Details
    statement: str
    intent: str
    source: str
    verification: str
    asserted_at: str
    author: Author
    channel: str
    origin: str
    supersedes_id: Optional[int]
    superseded_by_id: Optional[int]
    is_current: bool
    patient_visible: bool
    patient_id: int = 0          # not in the API shape; the rules use it


@dataclass
class Chart:
    patient_id: int
    items: list[AssertionView]


@dataclass
class Chain:
    head_id: int
    items: list[AssertionView]


@dataclass
class CareTeamMemberView:
    system: str
    value: str
    role: Optional[str]
    staff_id: Optional[int]
    name: str
    staff_role: Optional[str]
    department: Optional[str]


@dataclass
class CareTeamVersion:
    entry_id: int
    assertion_id: int
    visit_id: int
    name: Optional[str]
    status: str
    members: list[CareTeamMemberView]
    author: Author
    asserted_at: str
    is_current: bool


@dataclass
class CareTeamView:
    visit_id: int
    current: Optional[CareTeamVersion]
    chain: list[CareTeamVersion]


@dataclass
class RecordResult:
    message_id: int
    assertions: list[AssertionView]


@dataclass
class CodePreset:
    category: str
    code: str
    code_system: str
    display: str
    details: Details


@dataclass
class Card:
    rank: int
    assertion: AssertionView
    supersedes: list[AssertionView]


@dataclass
class ChatTurnView:
    id: int
    seq: int
    speaker: str
    text: str
    created_at: str
    kind: Optional[str]
    cards: list[Card] = field(default_factory=list)
    recorded_ids: list[int] = field(default_factory=list)


@dataclass
class ChatSessionSummary:
    id: int
    identifier: str
    started_at: str
    mode: str
    turn_count: int
    first_question: Optional[str]


@dataclass
class ChatSessionView:
    id: int
    identifier: str
    patient_id: int
    started_at: str
    mode: str
    model: Optional[str]
    turns: list[ChatTurnView] = field(default_factory=list)


@dataclass
class TurnResult:
    user_turn: ChatTurnView
    assistant_turn: ChatTurnView


@dataclass
class AuditEventView:
    id: int
    identifier: str
    at: str
    action: str
    outcome: str
    actor_role: str
    actor_key: str
    actor_name: Optional[str]
    path: str
    chat_turn_id: Optional[int]


@dataclass
class DepartmentView:
    id: int
    identifier: Identifier
    name: str
    type: Optional[str]
    phone_number: Optional[str]
    email: Optional[str]
    address: Address
    staff_count: int


@dataclass
class LocationView:
    id: int
    identifier: Identifier
    name: str
    department: Optional[str]
    physical_type: Optional[str]
    phone_number: Optional[str]
    address: Address
    in_use: bool


@dataclass
class StaffDepartment:
    department_id: int
    name: str
    role_code: str
    specialty: Optional[str]


@dataclass
class StaffView:
    id: int
    key: str
    identifier: Identifier
    name: str
    role: str
    sex: Optional[str]
    email: Optional[str]
    phone_number: Optional[str]
    active: bool
    departments: list[StaffDepartment]
    languages: list[str]
    license_number: Optional[str]
    qualification: Optional[str]
    designation: Optional[str]
    certification_number: Optional[str]
    desk: Optional[str]
    phone_extension: Optional[str]


@dataclass
class MedicationView:
    id: int
    code: str
    code_system: str
    name: str
    form: Optional[str]
    manufacturer: Optional[str]
