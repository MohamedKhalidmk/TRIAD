"""The unit of work: one write transaction on the connection of the request.

A write starts with BEGIN IMMEDIATE, so it takes the write lock first. The SQLite errors of the
statements become domain errors: UNIQUE and FOREIGN KEY give Conflict (409); CHECK, NOT NULL and the
RAISE of a trigger give Invalid (422) with the message of the trigger.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

from domain.errors import Conflict, DomainError, Invalid

from infrastructure.clock import DemoClock

# The time columns that the API writes with the clock. The latest of them sets the next write time.
TIME_COLUMNS = (
    ("Assertion", "AssertedAt"), ("Message", "SentAt"), ("Visit", "StartDate"), ("Visit", "EndDate"),
    ("VisitLocation", "StartDate"), ("VisitLocation", "EndDate"), ("ChatSession", "StartedAt"),
    ("ChatTurn", "CreatedAt"), ("AuditEvent", "At"),
)
LATEST_SQL = "SELECT MAX(j) FROM (" + " UNION ALL ".join(
    f"SELECT MAX(julianday({column})) AS j FROM {table}" for table, column in TIME_COLUMNS) + ")"


def map_integrity_error(error: sqlite3.IntegrityError) -> DomainError:
    text = str(error)
    if text.startswith("UNIQUE constraint failed"):
        return Conflict("A row with the same key exists already.", {"key": text.split(": ", 1)[-1]})
    if text.startswith("FOREIGN KEY constraint failed"):
        return Conflict("The row is in use, or it points to a row that does not exist.")
    if text.startswith("CHECK constraint failed") or text.startswith("NOT NULL constraint failed"):
        return Invalid("The input is not correct.", {"database": text})
    return Invalid(text)                    # the message of a trigger (RAISE)


class SqliteUnitOfWork:
    def __init__(self, conn: sqlite3.Connection, clock: DemoClock):
        self.conn = conn
        self.clock = clock

    def latest_time(self) -> Optional[datetime]:
        row = self.conn.execute(f"SELECT datetime(({LATEST_SQL}))").fetchone()
        if not row or not row[0]:
            return None
        return datetime.fromisoformat(row[0]).replace(tzinfo=timezone.utc)

    def now(self) -> str:
        return self.clock.current(self.latest_time())

    @contextmanager
    def write(self) -> Iterator[str]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.clock.write_time(self.latest_time())
        except sqlite3.IntegrityError as error:
            self.conn.execute("ROLLBACK")
            raise map_integrity_error(error) from error
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")
