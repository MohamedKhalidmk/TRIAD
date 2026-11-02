"""Use case: onboard FHIR data into the TRIAD database."""
from __future__ import annotations

from application.onboarding.derive_supersedes import derive_prescription_renewals
from application.ports import OnboardingSource, OnboardingStore


class ImportFhirSource:
    def __init__(self, source: OnboardingSource, store: OnboardingStore, synthea_system: str):
        self.source = source
        self.store = store
        self.synthea_system = synthea_system

    def run(self) -> dict:
        batch = self.source.load_batch()
        batch.stats.update(derive_prescription_renewals(batch, self.synthea_system))
        rows = self.store.write(batch)
        return {"rows": rows, "mapping": batch.stats}
