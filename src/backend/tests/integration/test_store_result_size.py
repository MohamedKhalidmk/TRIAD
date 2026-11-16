"""A large result comes back whole (plan 4.1 and 5.5): all 13,756 assertions of the largest chart in one SELECT.

Virtuoso cuts a result above ResultSetMaxRows with HTTP 200 and the header X-SPARQL-MaxRows; the HTTP client then
raises SparqlStoreError (client.py). kg.sh does not set ResultSetMaxRows, so the result is complete.
"""
from __future__ import annotations

import sqlite3

import pytest

from infrastructure.sparql import records_repository as R

pytestmark = pytest.mark.stores("oxigraph", "virtuoso")


def test_all_versions_of_the_largest_chart_in_one_select(full_store):
    conn = sqlite3.connect(f"file:{full_store.db_path}?mode=ro", uri=True)
    try:
        patient, count = conn.execute(
            "SELECT v.PatientId, COUNT(*) FROM Assertion a JOIN ClinicalEntry e ON e.Id = a.ClinicalEntryId "
            "JOIN Visit v ON v.Id = e.VisitId GROUP BY v.PatientId ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    assert count == 13756
    items = R._Items(patient).where(current_only=False, visible_only=False)
    ctx = full_store.open_ctx()
    try:
        rows = ctx.records.session.select(f"SELECT ?a FROM $abox WHERE {{{items.text()}\n}}", items.bindings)
    finally:
        ctx.close()
    assert len(rows) == count == len({r["a"] for r in rows})
