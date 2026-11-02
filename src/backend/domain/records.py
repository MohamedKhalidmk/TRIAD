"""Domain records of TRIAD.

These records have no I/O. The onboarding mapper makes them from FHIR, and a store writes them.
Records point to each other by their natural keys (the keys of the ER diagram), not by row ids.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

Ident = tuple[str, str]          # (IdentifierSystem, IdentifierValue): the FHIR Identifier
PatientKey = tuple[str, str]     # (Name, DateOfBirth): the key of Patient
MedicationKey = tuple[str, str]  # (Code, CodeSystem): the key of Medication


@dataclass
class Address:
    street: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None


@dataclass
class Department:
    ident: Ident
    name: str
    type: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Address = field(default_factory=Address)


@dataclass
class Location:
    ident: Ident
    name: str
    type: Optional[str] = None
    physical_type: Optional[str] = None
    phone: Optional[str] = None
    address: Address = field(default_factory=Address)


@dataclass
class WorksIn:
    department: Ident
    role_code: str
    specialty: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


@dataclass
class Staff:
    ident: Ident
    name: str
    role: str                                   # Doctor, Nurse or MOA (the ISA discriminator)
    sex: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    active: bool = True
    languages: list[str] = field(default_factory=list)
    works_in: list[WorksIn] = field(default_factory=list)
    # Subtype attributes
    license_number: Optional[str] = None        # Doctor, Nurse
    qualification: Optional[str] = None         # Doctor
    designation: Optional[str] = None           # Nurse
    certification_number: Optional[str] = None  # MOA
    desk: Optional[str] = None                  # MOA
    phone_extension: Optional[str] = None       # MOA


@dataclass
class Patient:
    name: str
    birth_date: str
    sex: str
    phone: Optional[str] = None
    address: Address = field(default_factory=Address)
    identifiers: list[Ident] = field(default_factory=list)

    @property
    def key(self) -> PatientKey:
        return (self.name, self.birth_date)


@dataclass
class VisitLocation:
    location: Ident
    start: str
    end: Optional[str] = None


@dataclass
class Visit:
    ident: Ident
    patient: PatientKey
    visit_class: str
    start: str
    end: Optional[str] = None
    type: Optional[str] = None
    reason: Optional[str] = None
    locations: list[VisitLocation] = field(default_factory=list)


@dataclass
class Medication:
    code: str
    code_system: str
    name: str
    form: Optional[str] = None
    manufacturer: Optional[str] = None

    @property
    def key(self) -> MedicationKey:
        return (self.code, self.code_system)


@dataclass
class CareTeamMember:
    member: Ident
    role: Optional[str] = None


@dataclass
class ClinicalEntry:
    ident: Ident
    visit: Ident
    category: str
    code: str
    code_system: str
    display: str
    recorded_at: str
    text: Optional[str] = None
    details: dict = field(default_factory=dict)              # the subtype attributes
    medication: Optional[MedicationKey] = None               # Prescription only
    members: list[CareTeamMember] = field(default_factory=list)  # CareTeam only


@dataclass
class Message:
    ident: Ident
    staff: Optional[Ident]          # None: the patient sent the message (Origin = Patient)
    channel: str
    origin: str
    sent_at: str
    text: str


@dataclass
class Assertion:
    key: str                        # a load key (for example "Provenance/prov-elena-pen-3"); not stored
    message: Ident
    seq: int
    entry: Ident
    asserted_at: str
    intent: str
    source: str
    verification: str
    statement: str
    supersedes: Optional[str] = None  # the load key of the superseded assertion


@dataclass
class ChatTurn:
    seq: int
    client_turn_id: str
    speaker: str
    text: str
    created_at: str
    citations: list[tuple[str, int]] = field(default_factory=list)  # (assertion load key, rank)


@dataclass
class ChatSession:
    ident: Ident
    user_role: str
    user: Ident
    subject: PatientKey
    started_at: str
    mode: str
    model: Optional[str] = None
    turns: list[ChatTurn] = field(default_factory=list)


@dataclass
class AuditEvent:
    ident: Ident
    at: str
    action: str
    outcome: str
    actor_role: str
    actor: Ident
    subject: PatientKey
    path: str
    chat_turn: Optional[tuple[Ident, int]] = None  # (chat session ident, turn seq)


@dataclass
class OnboardBatch:
    """All records of one onboarding run, in the order that a store must write them."""
    departments: list[Department] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)
    staff: list[Staff] = field(default_factory=list)
    patients: list[Patient] = field(default_factory=list)
    visits: list[Visit] = field(default_factory=list)
    medications: list[Medication] = field(default_factory=list)
    entries: list[ClinicalEntry] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)
    assertions: list[Assertion] = field(default_factory=list)
    chat_sessions: list[ChatSession] = field(default_factory=list)
    audit_events: list[AuditEvent] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
