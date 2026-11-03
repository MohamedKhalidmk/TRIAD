"""Pydantic models of the API (doc/api.md section 2). The JSON field names are camelCase.

The response models read the read models of domain/views.py (snake_case). The request models check the input.
"""
from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

Role = Literal["Patient", "Doctor", "Nurse", "MOA"]
StaffRole = Literal["Doctor", "Nurse", "MOA"]
Intent = Literal["Report", "Recommendation", "Decision"]
Verification = Literal["Unconfirmed", "Provisional", "Differential", "Confirmed", "Refuted", "EnteredInError"]
Channel = Literal["InPerson", "Phone", "Video", "Email", "Fax", "Transfer", "Chat", "App"]
VisitClass = Literal["AMB", "EMER", "IMP", "HH", "VR"]
NewCategory = Literal["Diagnosis", "Procedure", "Allergy", "Observation", "LabOrder", "LabReport", "Prescription"]
Value = Union[str, int, float, None]


class Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True, validate_by_alias=True,
                              serialize_by_alias=True, from_attributes=True)


# ----- shared -----

class Identifier(Model):
    system: str
    value: str


class Address(Model):
    street: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None


class ApiError(Model):
    code: str
    message: str
    fields: Optional[dict[str, str]] = None


class Health(Model):
    status: str
    schema_version: int
    mode: str
    now: str


# ----- users and patients -----

class UserView(Model):
    key: str
    role: str
    name: str
    detail: str
    pinned: bool
    patient_id: Optional[int]
    staff_id: Optional[int]


class Permissions(Model):
    view_chart: bool
    chat: bool
    tell: bool
    edit_demographics: bool
    check_in: bool
    end_visit: bool
    move_location: bool
    manage_care_team: bool
    view_audit: bool
    record_intents: list[str]


class PatientSummary(Model):
    id: int
    name: str
    date_of_birth: str
    sex: str
    phone_number: Optional[str]
    open_visit_id: Optional[int]


class Patient(PatientSummary):
    address: Address
    identifiers: list[Identifier]
    permissions: Permissions


class PatientCreate(Model):
    name: str
    date_of_birth: str
    sex: Literal["female", "male", "other", "unknown"]
    phone_number: Optional[str] = None
    address: Optional[Address] = None


class PatientPatch(Model):
    sex: Optional[str] = None
    phone_number: Optional[str] = None
    address: Optional[Address] = None
    name: Optional[str] = None
    date_of_birth: Optional[str] = None


# ----- visits and care teams -----

class VisitLocation(Model):
    location_id: int
    name: str
    department: Optional[str]
    start_date: str
    end_date: Optional[str]


class Visit(Model):
    id: int
    patient_id: int
    identifier: Identifier
    visit_class: str = Field(alias="class")
    type: Optional[str]
    reason: Optional[str]
    start_date: str
    end_date: Optional[str]
    is_open: bool
    department: Optional[str]
    locations: list[VisitLocation]


class VisitCreate(Model):
    visit_class: VisitClass = Field(alias="class")
    reason: Optional[str] = None
    type: Optional[str] = None
    location_id: int


class LocationMove(Model):
    location_id: int


class Author(Model):
    name: str
    role: str
    staff_id: Optional[int]
    label: str


class CareTeamMember(Model):
    system: str
    value: str
    role: Optional[str]
    staff_id: Optional[int]
    name: str
    staff_role: Optional[str]
    department: Optional[str]


class CareTeamVersion(Model):
    entry_id: int
    assertion_id: int
    visit_id: int
    name: Optional[str]
    status: str
    members: list[CareTeamMember]
    author: Author
    asserted_at: str
    is_current: bool


class CareTeam(Model):
    visit_id: int
    current: Optional[CareTeamVersion]
    chain: list[CareTeamVersion]


class MemberIn(Model):
    system: str
    value: str
    role: Optional[str] = None


class CareTeamPut(Model):
    members: list[MemberIn]
    name: Optional[str] = None


# ----- assertions and records -----

class AssertionView(Model):
    id: int
    entry_id: int
    message_id: int
    seq: int
    visit_id: int
    category: str
    code: str
    code_system: str
    display: str
    details: dict[str, Value]
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


class Chart(Model):
    patient_id: int
    items: list[AssertionView]


class Chain(Model):
    head_id: int
    items: list[AssertionView]


class NewEntry(Model):
    category: NewCategory
    code: str
    code_system: str
    display: str
    text: Optional[str] = None
    details: dict[str, Value] = Field(default_factory=dict)


class NewAssertion(Model):
    entry_id: Optional[int] = None
    new_entry: Optional[NewEntry] = None
    supersedes_id: Optional[int] = None
    intent: Intent
    verification: Verification
    statement: str


class NewMessage(Model):
    patient_id: int
    visit_id: Optional[int] = None
    channel: Optional[Channel] = None
    text: str
    assertions: list[NewAssertion] = Field(min_length=1)


class RecordResult(Model):
    message_id: int
    assertions: list[AssertionView]


class CodePreset(Model):
    category: str
    code: str
    code_system: str
    display: str
    details: dict[str, Value]


# ----- chat -----

class Card(Model):
    rank: int
    assertion: AssertionView
    supersedes: list[AssertionView]


class ChatTurn(Model):
    id: int
    seq: int
    speaker: str
    text: str
    created_at: str
    kind: Optional[str]
    cards: list[Card]
    recorded_ids: list[int]


class ChatSessionSummary(Model):
    id: int
    identifier: str
    started_at: str
    mode: str
    turn_count: int
    first_question: Optional[str]


class ChatSession(Model):
    id: int
    identifier: str
    patient_id: int
    started_at: str
    mode: str
    model: Optional[str]
    turns: list[ChatTurn]


class TurnIn(Model):
    client_turn_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class TurnResult(Model):
    user_turn: ChatTurn
    assistant_turn: ChatTurn


# ----- audit -----

class AuditEvent(Model):
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


# ----- directory -----

class Department(Model):
    id: int
    identifier: Identifier
    name: str
    type: Optional[str]
    phone_number: Optional[str]
    email: Optional[str]
    address: Address
    staff_count: int


class DepartmentIn(Model):
    identifier: Optional[Identifier] = None
    name: Optional[str] = None
    type: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None
    address: Optional[Address] = None


class Location(Model):
    id: int
    identifier: Identifier
    name: str
    department: Optional[str]
    physical_type: Optional[str]
    phone_number: Optional[str]
    address: Address
    in_use: bool


class LocationIn(Model):
    identifier: Optional[Identifier] = None
    name: Optional[str] = None
    department: Optional[str] = None
    physical_type: Optional[str] = None
    phone_number: Optional[str] = None
    address: Optional[Address] = None


class StaffDepartment(Model):
    department_id: int
    name: str
    role_code: str
    specialty: Optional[str]


class Staff(Model):
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


class StaffPatch(Model):
    email: Optional[str] = None
    phone_number: Optional[str] = None
    active: Optional[bool] = None
    languages: Optional[list[str]] = None
    license_number: Optional[str] = None
    qualification: Optional[str] = None
    designation: Optional[str] = None
    certification_number: Optional[str] = None
    desk: Optional[str] = None
    phone_extension: Optional[str] = None


class StaffCreate(StaffPatch):
    identifier: Optional[Identifier] = None
    name: str
    role: StaffRole
    sex: Optional[str] = None
    department_id: int
    role_code: Optional[str] = None
    specialty: Optional[str] = None


class Medication(Model):
    id: int
    code: str
    code_system: str
    name: str
    form: Optional[str]
    manufacturer: Optional[str]


class MedicationIn(Model):
    code: Optional[str] = None
    code_system: Optional[str] = None
    name: Optional[str] = None
    form: Optional[str] = None
    manufacturer: Optional[str] = None
