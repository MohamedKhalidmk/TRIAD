"""Departments, locations, staff and medications on the knowledge graph (the DirectoryRepository port).

STUB: agent D writes this file. Each method has the signature of application/ports.py, and it must
give the same results as infrastructure/sqlite/directory_repository.py (SqliteDirectoryRepository).
Follow the pattern of users_repository.py and README.md in this folder.
The port has 29 methods. Each one raises NotImplementedError until it is written.
"""
from __future__ import annotations

from typing import Optional

from domain.views import DepartmentView, LocationView, MedicationView, StaffView

from application.paging import Page, PageRequest
from infrastructure.sparql.unit_of_work import KgSession

AGENT = "agent D"


class SparqlDirectoryRepository:
    """The DirectoryRepository port on SPARQL."""

    def __init__(self, session: KgSession):
        self.session = session

    def departments(self, q: Optional[str], page: PageRequest) -> Page[DepartmentView]:
        raise NotImplementedError(AGENT)

    def department(self, department_id: int) -> Optional[DepartmentView]:
        raise NotImplementedError(AGENT)

    def department_by_name(self, name: str) -> Optional[DepartmentView]:
        raise NotImplementedError(AGENT)

    def department_name_exists(self, name: str, except_id: Optional[int] = None) -> bool:
        raise NotImplementedError(AGENT)

    def add_department(self, values: dict) -> int:
        raise NotImplementedError(AGENT)

    def update_department(self, department_id: int, values: dict) -> None:
        raise NotImplementedError(AGENT)

    def delete_department(self, department_id: int) -> None:
        raise NotImplementedError(AGENT)

    def department_use(self, department_id: int) -> tuple[int, int]:
        raise NotImplementedError(AGENT)

    def locations(self, department: Optional[str], q: Optional[str], page: PageRequest) -> Page[LocationView]:
        raise NotImplementedError(AGENT)

    def location(self, location_id: int) -> Optional[LocationView]:
        raise NotImplementedError(AGENT)

    def location_by_identifier(self, system: str, value: str) -> Optional[LocationView]:
        raise NotImplementedError(AGENT)

    def add_location(self, values: dict) -> int:
        raise NotImplementedError(AGENT)

    def update_location(self, location_id: int, values: dict) -> None:
        raise NotImplementedError(AGENT)

    def delete_location(self, location_id: int) -> None:
        raise NotImplementedError(AGENT)

    def staff_list(self, role: Optional[str], department: Optional[str], q: Optional[str],
                   page: PageRequest) -> Page[StaffView]:
        raise NotImplementedError(AGENT)

    def staff(self, staff_id: int) -> Optional[StaffView]:
        raise NotImplementedError(AGENT)

    def staff_by_identifier(self, system: str, value: str) -> Optional[StaffView]:
        raise NotImplementedError(AGENT)

    def add_staff(self, values: dict) -> int:
        raise NotImplementedError(AGENT)

    def update_staff(self, staff_id: int, values: dict) -> None:
        raise NotImplementedError(AGENT)

    def staff_use(self, staff_id: int) -> dict[str, int]:
        raise NotImplementedError(AGENT)

    def delete_staff(self, staff_id: int) -> None:
        raise NotImplementedError(AGENT)

    def medications(self, q: Optional[str], page: PageRequest) -> Page[MedicationView]:
        raise NotImplementedError(AGENT)

    def medication(self, medication_id: int) -> Optional[MedicationView]:
        raise NotImplementedError(AGENT)

    def add_medication(self, values: dict) -> int:
        raise NotImplementedError(AGENT)

    def update_medication(self, medication_id: int, values: dict) -> None:
        raise NotImplementedError(AGENT)

    def medication_in_use(self, medication_id: int) -> bool:
        raise NotImplementedError(AGENT)

    def delete_medication(self, medication_id: int) -> None:
        raise NotImplementedError(AGENT)

    def unique_identifier(self, table: str, system: str, base: str) -> str:
        raise NotImplementedError(AGENT)

    def next_identifier(self, table: str, system: str, prefix: str, width: int) -> str:
        raise NotImplementedError(AGENT)
