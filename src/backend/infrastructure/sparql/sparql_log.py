"""The SPARQL log (TRIAD_SPARQL_LOG): one line for each SPARQL request of an API request, with its time.

The parallel of infrastructure/sqlite/sql_log.py for the knowledge graph:
- LoggedSparqlClient wraps a SPARQL client. select, ask and update run the request and then write one line.
- The line shows the TEMPLATE of the request (with the "$name" placeholders), not the values. The mode "on" thus
  never shows a name or a date of birth. The mode "params" adds the bindings (the data of TRIAD is synthetic,
  but a real system must not log them).
- One middleware writes the summary line of a request for both stores: sql_log.SqlLogMiddleware with the words
  of this log (middleware_options()). The requests of a request count in the same context variable.

The lines go to stderr (logger "triad.sparql"). dev.sh shows them with the prefix [api]:
    [sparql] GET /api/users  1.84 ms  25 rows  SELECT ?role ?id ... LIMIT 25 OFFSET 0
    [sparql] GET /api/users 200: 2 requests, 3.1 ms in SPARQL, 9.0 ms in all.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Mapping, Optional

from infrastructure.sqlite import sql_log
from infrastructure.sqlite.sql_log import NO_REQUEST, one_line, plural

LOGGER_NAME = "triad.sparql"
HANDLER_NAME = "triad.sparql.stderr"

log = logging.getLogger(LOGGER_NAME)


def log_request(form: str, template: str, bindings: Optional[Mapping[str, Any]], seconds: float, result: str,
                show_params: bool, error: Optional[BaseException] = None) -> None:
    """Add the request to the API request, and write its line."""
    stats = sql_log._request.get()
    if stats is not None:
        stats.statements += 1
        stats.seconds += seconds
    if not log.isEnabledFor(logging.INFO):
        return
    shown = f"failed ({type(error).__name__})" if error is not None else result
    line = f"[sparql] {stats.label if stats else NO_REQUEST}  {seconds * 1000:.2f} ms  {shown}  {one_line(template)}"
    if show_params and bindings:
        line += f"  params: {dict(bindings)!r}"
    log.info(line)


class LoggedSparqlClient:
    """A SPARQL client that logs each request with its time. The other attributes go to the client."""

    def __init__(self, client: Any, show_params: bool = False):
        self._client = client
        self._show_params = show_params

    @property
    def store(self) -> str:
        return self._client.store

    @property
    def key(self) -> str:
        return self._client.key

    def _timed(self, form: str, template: str, bindings: Optional[Mapping[str, Any]], call, describe) -> Any:
        start = time.perf_counter()
        try:
            result = call()
        except Exception as error:
            log_request(form, template, bindings, time.perf_counter() - start, "", self._show_params, error)
            raise
        log_request(form, template, bindings, time.perf_counter() - start, describe(result), self._show_params)
        return result

    def select(self, template: str, bindings: Optional[Mapping[str, Any]] = None, *, raw: bool = False) -> list:
        return self._timed("select", template, bindings,
                           lambda: self._client.select(template, bindings, raw=raw),
                           lambda rows: plural(len(rows), "row"))

    def ask(self, template: str, bindings: Optional[Mapping[str, Any]] = None) -> bool:
        return self._timed("ask", template, bindings, lambda: self._client.ask(template, bindings),
                           lambda value: "true" if value else "false")

    def update(self, template: str, bindings: Optional[Mapping[str, Any]] = None) -> None:
        return self._timed("update", template, bindings, lambda: self._client.update(template, bindings),
                           lambda _: "done")

    def __getattr__(self, name: str) -> Any:
        if name == "_client":
            raise AttributeError(name)
        return getattr(self._client, name)


def middleware_options(show_query: bool) -> dict:
    """The options of sql_log.SqlLogMiddleware for the SPARQL log."""
    return {"show_query": show_query, "tag": "sparql", "unit": "request", "store": "SPARQL", "logger": log}


def configure_logger() -> logging.Logger:
    """Send the lines of "triad.sparql" (level INFO) to stderr, once (see sql_log.configure_logger)."""
    return sql_log.configure_logger(log, HANDLER_NAME)
