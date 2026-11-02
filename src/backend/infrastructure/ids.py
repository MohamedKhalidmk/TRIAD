"""New identifier values for new rows (a FHIR Identifier: a system and a value).

The table and column names come only from the fixed list below. Each value is a parameter.
Call these functions inside a write transaction (BEGIN IMMEDIATE), so two writers cannot get the same value.
"""
from __future__ import annotations

import sqlite3

# table -> (system column, value column)
IDENTIFIER_COLUMNS = {
    "Department": ("IdentifierSystem", "IdentifierValue"),
    "Location": ("IdentifierSystem", "IdentifierValue"),
    "Staff": ("IdentifierSystem", "IdentifierValue"),
    "Visit": ("IdentifierSystem", "IdentifierValue"),
    "ClinicalEntry": ("IdentifierSystem", "IdentifierValue"),
    "Message": ("IdentifierSystem", "IdentifierValue"),
    "ChatSession": ("IdentifierSystem", "IdentifierValue"),
    "AuditEvent": ("IdentifierSystem", "IdentifierValue"),
    "PatientIdentifier": ("System", "Value"),
}


def next_identifier(conn: sqlite3.Connection, table: str, system: str, prefix: str, width: int) -> str:
    """The next value `<prefix><number>`, for example MRN-000002. Values with other forms do not count."""
    system_col, value_col = IDENTIFIER_COLUMNS[table]
    row = conn.execute(
        f"SELECT MAX(CAST(substr({value_col}, ?) AS INTEGER)) FROM {table} "
        f"WHERE {system_col} = ? AND {value_col} GLOB ?",
        (len(prefix) + 1, system, prefix + "[0-9]*")).fetchone()
    number = (row[0] or 0) + 1
    return f"{prefix}{number:0{width}d}"


def unique_identifier(conn: sqlite3.Connection, table: str, system: str, base: str) -> str:
    """`base`, or `base-2`, `base-3` ... if the value is in use."""
    system_col, value_col = IDENTIFIER_COLUMNS[table]
    value, n = base, 1
    while conn.execute(f"SELECT 1 FROM {table} WHERE {system_col} = ? AND {value_col} = ?",
                       (system, value)).fetchone():
        n += 1
        value = f"{base}-{n}"
    return value
