"""The context of one request: the ports that a use case can use.

The composition root (main.py) makes one context for each request, with the concrete adapters.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from application.ports import (AuditRepository, ChatRepository, DirectoryRepository, LanguageModel,
                               PatientRepository, RecordRepository, UnitOfWork, UserRepository, VisitRepository)


@dataclass
class Identity:
    """The identifier systems that the application uses for new rows."""
    mrn: str = "https://triad.example/fhir/sid/mrn"
    synthea: str = "https://github.com/synthetichealth/synthea"
    employee: str = "https://triad.example/fhir/sid/employee"
    organization: str = "https://triad.example/fhir/sid/organization"
    location: str = "https://triad.example/fhir/sid/location"
    encounter: str = "https://triad.example/fhir/sid/encounter"
    message: str = "https://triad.example/fhir/sid/message"
    entry: str = "https://triad.example/fhir/sid/clinical-entry"
    chat_session: str = "https://triad.example/fhir/sid/chat-session"
    local_codes: str = "https://triad.example/fhir/CodeSystem/local"
    hospital_code: str = "TRIAD-GH"


@dataclass
class AppContext:
    uow: UnitOfWork
    users: UserRepository
    patients: PatientRepository
    visits: VisitRepository
    records: RecordRepository
    chat: ChatRepository
    audit: AuditRepository
    directory: DirectoryRepository
    llm: LanguageModel                 # the model of the chat mode
    fallback_llm: LanguageModel        # the fake model; the chat uses it when `llm` fails
    chat_mode: str                     # 'fake' or 'llm'
    chat_model: Optional[str]
    schema_version: int
    identity: Identity
    close: Callable[[], None] = lambda: None
    clock_mode: str = "fixed"          # 'system' (the computer clock) or 'fixed' (a fixed TRIAD_NOW)
