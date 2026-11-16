"""A small client of the SPARQL 1.1 Protocol for the knowledge-graph scripts (only the standard library).

sparql_script.py and counts.py use it; src/scripts/kg.sh calls them. The API of the app uses its own driver.
- A query goes to the query endpoint (Virtuoso: /sparql) with no login.
- An update goes to the update endpoint (Virtuoso: /sparql-auth) with a digest login.
  Virtuoso refuses basic auth on /sparql-auth (HTTP 401).
The request is an HTTP POST with the form field "query" or "update" (SPARQL 1.1 Protocol, sections 2.1 and 2.2).
"""
from __future__ import annotations

import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional

DEFAULT_TIMEOUT = 120.0   # seconds. Do not use the time limit of Virtuoso: it cuts the results with no error.


@dataclass(frozen=True)
class Answer:
    status: int
    content_type: str     # for example application/sparql-results+json (no parameters)
    body: bytes


class SparqlError(Exception):
    """The endpoint refused the request (status is the HTTP status), or no endpoint answered (status is None)."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def server_message(text: str, limit: int = 600) -> str:
    """The first paragraph of an error text. Virtuoso writes the query after a blank line; the caller has it."""
    first = text.strip().split("\n\n", 1)[0].strip()
    return first if len(first) <= limit else first[:limit] + " ..."


def send(url: str, *, query: Optional[str] = None, update: Optional[str] = None, accept: str,
         user: Optional[str] = None, password: Optional[str] = None,
         timeout: float = DEFAULT_TIMEOUT) -> Answer:
    """Send one query or one update request. Give user and password for a digest login."""
    if (query is None) == (update is None):
        raise ValueError("Give a query or an update, not both.")
    field = {"query": query} if query is not None else {"update": update}
    request = urllib.request.Request(
        url, data=urllib.parse.urlencode(field).encode("utf-8"),
        headers={"Accept": accept, "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
    handlers = []
    if user:
        manager = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        manager.add_password(None, url, user, password or "")
        handlers.append(urllib.request.HTTPDigestAuthHandler(manager))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(request, timeout=timeout) as response:
            return Answer(response.status, response.headers.get_content_type(), response.read())
    except urllib.error.HTTPError as error:
        text = error.read().decode("utf-8", "replace")
        message = f"HTTP {error.code} from {url}"
        if error.code == 401:
            message += (": the endpoint refuses the login. Check TRIAD_SPARQL_USER and TRIAD_SPARQL_PASSWORD, "
                        "and run ./src/scripts/kg.sh init")
        elif text.strip():
            message += ": " + server_message(text)
        raise SparqlError(message, error.code) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as error:
        reason = getattr(error, "reason", error)
        raise SparqlError(f"No answer from {url} ({reason}). Does the store run? "
                          "To start Virtuoso: ./src/scripts/kg.sh up") from None
