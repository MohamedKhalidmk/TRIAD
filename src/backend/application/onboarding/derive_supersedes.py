"""Derive Supersedes links that the Synthea data does not state.

Rule: for one patient and one medication code, a later prescription supersedes the earlier one.
The order is (AssertedAt, entry identifier), so the result is the same on each run.
Synthea has no other revision links. The curated data states its links in FHIR Provenance.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from domain.records import OnboardBatch


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def derive_prescription_renewals(batch: OnboardBatch, source_system: str) -> dict[str, int]:
    """Link renewals of one medication for one patient. Only entries of `source_system` take part."""
    visit_patient = {v.ident: v.patient for v in batch.visits}
    entry_by_ident = {e.ident: e for e in batch.entries}
    groups: dict[tuple, list] = defaultdict(list)
    for a in batch.assertions:
        entry = entry_by_ident[a.entry]
        if entry.category != "Prescription" or entry.ident[0] != source_system or a.supersedes:
            continue
        groups[(visit_patient[entry.visit], entry.medication)].append(a)
    links = 0
    for items in groups.values():
        items.sort(key=lambda a: (_instant(a.asserted_at), a.entry[1]))
        for earlier, later in zip(items, items[1:]):
            later.supersedes = earlier.key
            links += 1
    return {"renewalGroups": sum(1 for g in groups.values() if len(g) > 1), "renewalLinks": links}
