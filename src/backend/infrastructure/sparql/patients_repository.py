"""Patients on the knowledge graph (the PatientRepository port).

STUB: agent C writes this file. Each method has the signature of application/ports.py, and it must
give the same results as infrastructure/sqlite/patients_repository.py (SqlitePatientRepository).
Follow the pattern of users_repository.py and README.md in this folder.
The port has 9 methods. Each one raises NotImplementedError until it is written.
"""
from __future__ import annotations

from typing import Optional

from domain.records import Address
from domain.views import PatientSummary, PatientView

from application.paging import Page, PageRequest
from infrastructure.sparql.unit_of_work import KgSession

AGENT = "agent C"


class SparqlPatientRepository:
    """The PatientRepository port on SPARQL."""

    def __init__(self, session: KgSession):
        self.session = session

    def get(self, patient_id: int) -> Optional[PatientView]:
        raise NotImplementedError(AGENT)

    def search(self, q: Optional[str], dob: Optional[str], scope: str, member: Optional[tuple[str, str]],
               page: PageRequest) -> Page[PatientSummary]:
        raise NotImplementedError(AGENT)

    def key_exists(self, name: str, date_of_birth: str) -> bool:
        raise NotImplementedError(AGENT)

    def create(self, name: str, date_of_birth: str, sex: str, phone: Optional[str], address: Address,
               identifiers: list[tuple[str, str]]) -> int:
        raise NotImplementedError(AGENT)

    def update(self, patient_id: int, changes: dict) -> None:
        raise NotImplementedError(AGENT)

    def has_visits(self, patient_id: int) -> bool:
        raise NotImplementedError(AGENT)

    def delete(self, patient_id: int) -> None:
        raise NotImplementedError(AGENT)

    def on_care_team(self, patient_id: int, system: str, value: str) -> bool:
        raise NotImplementedError(AGENT)

    def next_identifier(self, system: str, prefix: str, width: int) -> str:
        raise NotImplementedError(AGENT)
