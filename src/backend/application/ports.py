"""Ports (interfaces) of the application layer. The infrastructure layer implements them."""
from __future__ import annotations

from typing import Protocol

from domain.records import OnboardBatch


class OnboardingSource(Protocol):
    """Gives the records of one onboarding run (for example, from FHIR files)."""

    def load_batch(self) -> OnboardBatch: ...


class OnboardingStore(Protocol):
    """Writes a batch of records in one transaction and returns the row count of each table."""

    def write(self, batch: OnboardBatch) -> dict[str, int]: ...
