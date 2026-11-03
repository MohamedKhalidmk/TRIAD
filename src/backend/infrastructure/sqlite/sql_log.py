"""The SQL log (TRIAD_SQL_LOG): one line for each SQL statement of an API request, with its time.

Only the API connections use it (open_context in main.py). The onboarding and the tests that open their
own connections do not use it.

- LoggedConnection wraps a sqlite3 connection. execute() runs the statement, reads all the rows, and then
  writes one line. So the time includes all the work of the statement, not only the first row.
- SqlLogMiddleware (pure ASGI) keeps the method and the path of each /api request in a context variable.
  At the end of the request, it writes one summary line.
- The mode "on" does not show the bound values and the query string, because they can be patient names
  and dates of birth. The mode "params" shows them. The data of TRIAD is synthetic, but a real system
  must not log them.

The lines go to stderr (logger "triad.sql"). dev.sh shows them with the prefix [api]:
    [sql] GET /api/patients/1/chart  0.84 ms  25 rows  SELECT ... ORDER BY ... LIMIT ? OFFSET ?
    [sql] GET /api/patients/1/chart 200: 5 statements, 2.1 ms in SQL, 14.0 ms in all.
"""
from __future__ import annotations

import logging
import sqlite3
import sys
import time
from contextvars import ContextVar
from dataclasses import dataclass
from itertools import islice
from typing import Any, Iterable, Optional
from urllib.parse import unquote_plus

LOGGER_NAME = "triad.sql"
HANDLER_NAME = "triad.sql.stderr"
NO_REQUEST = "(no request)"

log = logging.getLogger(LOGGER_NAME)


@dataclass
class RequestStats:
    """The SQL work of one request. The worker threads of the request change the same object."""
    label: str                   # for example "GET /api/patients/1/chart"
    statements: int = 0
    seconds: float = 0.0


_request: ContextVar[Optional[RequestStats]] = ContextVar("triad_sql_request", default=None)


def plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def one_line(sql: str) -> str:
    """The SQL on one line, with no extra spaces."""
    return " ".join(sql.split())


def log_statement(sql: str, params: Any, seconds: float, rows: int, show_params: bool,
                  error: Optional[BaseException] = None) -> None:
    """Add the statement to the request, and write its line."""
    stats = _request.get()
    if stats is not None:
        stats.statements += 1
        stats.seconds += seconds
    if not log.isEnabledFor(logging.INFO):
        return
    result = f"failed ({type(error).__name__})" if error is not None else plural(rows, "row")
    line = f"[sql] {stats.label if stats else NO_REQUEST}  {seconds * 1000:.2f} ms  {result}  {one_line(sql)}"
    if show_params and params:
        line += f"  params: {params!r}"
    log.info(line)


class LoggedCursor:
    """The result of one statement: all its rows, and the cursor attributes that the repositories use."""
    arraysize = 1

    def __init__(self, cursor: sqlite3.Cursor, rows: list):
        self.lastrowid = cursor.lastrowid
        self.rowcount = cursor.rowcount
        self.description = cursor.description
        self._rows = iter(rows)

    def __iter__(self) -> "LoggedCursor":
        return self

    def __next__(self) -> Any:
        return next(self._rows)

    def fetchone(self) -> Any:
        return next(self._rows, None)

    def fetchmany(self, size: Optional[int] = None) -> list:
        return list(islice(self._rows, self.arraysize if size is None else size))

    def fetchall(self) -> list:
        return list(self._rows)

    def close(self) -> None:
        self._rows = iter(())


class LoggedConnection:
    """A sqlite3 connection that logs each statement with its time.

    execute() and executemany() are timed. All other attributes and methods (close, row_factory,
    executescript ...) go to the sqlite3 connection.
    """

    def __init__(self, conn: sqlite3.Connection, show_params: bool = False):
        self._conn = conn
        self._show_params = show_params

    def execute(self, sql: str, parameters: Any = ()) -> LoggedCursor:
        start = time.perf_counter()
        try:
            cursor = self._conn.execute(sql, parameters)
            rows = cursor.fetchall()
        except Exception as error:
            log_statement(sql, parameters, time.perf_counter() - start, 0, self._show_params, error)
            raise
        seconds = time.perf_counter() - start
        result = LoggedCursor(cursor, rows)
        count = len(rows) if cursor.description else max(cursor.rowcount, 0)   # rows read, or rows changed
        log_statement(sql, parameters, seconds, count, self._show_params)
        return result

    def executemany(self, sql: str, seq_of_parameters: Iterable[Any]) -> LoggedCursor:
        values = list(seq_of_parameters)
        start = time.perf_counter()
        try:
            cursor = self._conn.executemany(sql, values)
        except Exception as error:
            log_statement(sql, values, time.perf_counter() - start, 0, self._show_params, error)
            raise
        seconds = time.perf_counter() - start
        log_statement(sql, values, seconds, max(cursor.rowcount, 0), self._show_params)
        return LoggedCursor(cursor, [])

    def __getattr__(self, name: str) -> Any:
        if name == "_conn":                         # not set yet: no loop
            raise AttributeError(name)
        return getattr(self._conn, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:                                       # for example row_factory
            setattr(self._conn, name, value)

    def __enter__(self) -> "LoggedConnection":
        self._conn.__enter__()
        return self

    def __exit__(self, *exc_info: Any) -> Any:
        return self._conn.__exit__(*exc_info)


def is_api_path(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


class SqlLogMiddleware:
    """A pure ASGI middleware. It names the request in each SQL line and writes the summary line.

    Only the /api paths get a summary line. The files of the frontend and /docs do not.
    With show_query (the mode "params"), the label also shows the query string.
    """

    def __init__(self, app: Any, show_query: bool = False):
        self.app = app
        self.show_query = show_query

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not is_api_path(scope["path"]):
            await self.app(scope, receive, send)
            return
        target = scope["path"]
        query = scope.get("query_string", b"")
        if self.show_query and query:
            target += "?" + unquote_plus(query.decode("latin-1"))
        stats = RequestStats(f"{scope['method']} {target}")
        status = 500                                  # if the app fails before it sends a response

        async def send_and_keep_status(message: dict) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        token = _request.set(stats)
        start = time.perf_counter()
        try:
            await self.app(scope, receive, send_and_keep_status)
        finally:
            _request.reset(token)
            total = time.perf_counter() - start
            log.info(f"[sql] {stats.label} {status}: {plural(stats.statements, 'statement')}, "
                     f"{stats.seconds * 1000:.1f} ms in SQL, {total * 1000:.1f} ms in all.")


class StderrHandler(logging.Handler):
    """Write each line to the current sys.stderr. (The tests can then capture the lines.)"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            stream = sys.stderr
            stream.write(self.format(record) + "\n")
            stream.flush()
        except Exception:
            self.handleError(record)


def configure_logger() -> logging.Logger:
    """Send the lines of "triad.sql" (level INFO) to stderr. The root logger does not change.

    create_app can run more than one time in a process (the tests), so the handler is added only once.
    The logger does not send its lines to the root logger, so no line is written two times.
    """
    if not any(handler.get_name() == HANDLER_NAME for handler in log.handlers):
        handler = StderrHandler()
        handler.set_name(HANDLER_NAME)
        log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    return log
