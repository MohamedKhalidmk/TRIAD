"""The SPARQL client of the app: one interface for Virtuoso (HTTP) and for the embedded Oxigraph store.

SparqlClient (the protocol) has three methods. Each one takes a template and its bindings (terms.render):
    select(template, bindings) -> list of rows     a row is a dict {variable: Python value}; no value: None
    ask(template, bindings)    -> bool
    update(template, bindings) -> None

The conversion of a value (one layer for both stores, `python_value`):
    an IRI -> its text (str), with no angle brackets; terms.id_of() gives the integer id of an individual;
    xsd:integer (and the other integer types) -> int; xsd:decimal, xsd:double, xsd:float -> float;
    xsd:boolean -> bool; xsd:dateTime -> output_time() (D11); any other literal -> its text (str).
select(..., raw=True) gives each value as a terms.Term in SPARQL form instead (the unit of work uses this to
send a stored value back unchanged).

D11 (the times): both stores write "+00:00" as "Z" and drop the trailing zeros of the seconds. output_time()
changes "Z" back to "+00:00" (the data has no "Z" of its own) and keeps the rest of the text of the store.
Compare times as instants (domain.rules.parse_time), not as text.

HttpSparqlClient (SPARQLWrapper 2.0.0, the driver of the semantic data layer):
- SELECT and ASK go to the query URL (Virtuoso: /sparql) with no login. Only the updates go to the update URL
  (Virtuoso: /sparql-auth) with a digest login. Digest costs one extra 401 round trip for each update.
- The requests are HTTP POST with the form field "query" or "update", JSON results, and a timeout.
  Do not use the time limit of Virtuoso: it cuts the results with HTTP 200 and no error (plan 4.1).
- A response with the header X-SPARQL-MaxRows has fewer rows than the result: the client raises an error.
- An HTTP error (also HTTP 500, for example SR186 or SR619 of Virtuoso) raises SparqlStoreError with the status
  and the first paragraph of the text of the server.
EmbeddedSparqlClient (pyoxigraph 0.3.22): one shared Store object for each folder of this process
(oxigraph_store.open_store). A second Store on the same folder fails, so never open one yourself.

The RDF packages (SPARQLWrapper, pyoxigraph) load only when a client is made.
"""
from __future__ import annotations

import ast
import http.client
import socket
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Protocol, Union

from infrastructure.rdf.protocol import DEFAULT_TIMEOUT, server_message
from infrastructure.sparql import terms
from infrastructure.sparql.terms import XSD, Term

INTEGER_TYPES = frozenset(XSD + t for t in (
    "integer", "int", "long", "short", "byte", "nonNegativeInteger", "positiveInteger", "nonPositiveInteger",
    "negativeInteger", "unsignedLong", "unsignedInt", "unsignedShort", "unsignedByte"))
DECIMAL_TYPES = frozenset(XSD + t for t in ("decimal", "double", "float"))
BOOLEAN = XSD + "boolean"
DATE_TIME = XSD + "dateTime"
STRING = XSD + "string"
LANG_STRING = "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString"
MAX_ROWS_HEADER = "X-SPARQL-MaxRows"

Bindings = Optional[Mapping[str, Any]]
Row = dict[str, Any]


class SparqlStoreError(Exception):
    """The store refused a request, or no store answered. `status` is the HTTP status, or None."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Binding:
    """One value of a result row, the same for both stores."""
    kind: str                       # "uri", "literal" or "bnode"
    value: str
    datatype: Optional[str] = None  # a literal: the datatype IRI (None or xsd:string for a simple literal)
    language: Optional[str] = None


def output_time(text: str) -> str:
    """The output form of a stored xsd:dateTime (D11): "Z" becomes "+00:00"; the rest stays as the store gives it."""
    return text[:-1] + "+00:00" if text.endswith("Z") else text


def python_value(binding: Optional[Binding]) -> Any:
    """The Python value of one result value (the one conversion layer)."""
    if binding is None:
        return None
    if binding.kind == "uri":
        return binding.value
    if binding.kind == "bnode":
        return "_:" + binding.value
    datatype = binding.datatype
    if datatype in INTEGER_TYPES:
        return int(binding.value)
    if datatype in DECIMAL_TYPES:
        return float(binding.value)
    if datatype == BOOLEAN:
        return binding.value in ("true", "1")
    if datatype == DATE_TIME:
        return output_time(binding.value)
    return binding.value


def sparql_term(binding: Optional[Binding]) -> Optional[Term]:
    """The SPARQL form of one result value, unchanged (for example to write a stored value back)."""
    if binding is None:
        return None
    if binding.kind == "uri":
        return Term(f"<{binding.value}>")
    if binding.kind == "bnode":
        return Term(f"_:{binding.value}")
    body = f'"{terms.escape(binding.value)}"'
    if binding.language:
        return Term(f"{body}@{binding.language}")
    if binding.datatype and binding.datatype not in (STRING, LANG_STRING):
        return Term(f"{body}^^<{binding.datatype}>")
    return Term(body)


class SparqlClient(Protocol):
    """The interface of the repositories, the unit of work and the guards. See the module text."""
    store: str      # "virtuoso" or "oxigraph"
    key: str        # the identity of the store in this process (the write lock and the state use it)

    def select(self, template: str, bindings: Bindings = None, *, raw: bool = False) -> list[Row]: ...
    def ask(self, template: str, bindings: Bindings = None) -> bool: ...
    def update(self, template: str, bindings: Bindings = None) -> None: ...


def check_dataset(text: str) -> None:
    """SPARQL writing rule 1: a query selects its graphs with a dataset clause (FROM <graph>).

    Oxigraph has an empty default graph, but Virtuoso uses all graphs, so a query with no FROM would give
    different results on the two stores.
    """
    if "FROM <" not in text and "FROM $" not in text:
        raise ValueError("A SPARQL query needs a dataset clause, for example FROM $abox (SPARQL writing rule 1).")


class BaseSparqlClient:
    """select, ask and update on top of three methods of the store: _select, _ask and _update."""
    store = "?"
    key = "?"

    def select(self, template: str, bindings: Bindings = None, *, raw: bool = False) -> list[Row]:
        check_dataset(template)
        variables, rows = self._select(terms.render(template, bindings))
        convert: Callable[[Optional[Binding]], Any] = sparql_term if raw else python_value
        return [{name: convert(row.get(name)) for name in variables} for row in rows]

    def ask(self, template: str, bindings: Bindings = None) -> bool:
        check_dataset(template)
        return self._ask(terms.render(template, bindings))

    def update(self, template: str, bindings: Bindings = None) -> None:
        self._update(terms.render(template, bindings))

    # The methods of a store. The text is the full request (with the PREFIX lines).
    def _select(self, text: str) -> tuple[list[str], list[dict[str, Binding]]]:
        raise NotImplementedError

    def _ask(self, text: str) -> bool:
        raise NotImplementedError

    def _update(self, text: str) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------------------------
# Virtuoso (or any SPARQL 1.1 endpoint) over HTTP

def _sparqlwrapper():
    try:
        import SPARQLWrapper
    except ImportError as error:
        raise RuntimeError("The Virtuoso store needs SPARQLWrapper. Install the KG packages: "
                           "uv pip install --python .venv/bin/python -r requirements-kg.txt") from error
    return SPARQLWrapper


HTTP_STATUS = {"QueryBadFormed": 400, "Unauthorized": 401, "EndPointNotFound": 404, "URITooLong": 414,
               "EndPointInternalError": 500}


def response_text(error: Exception) -> str:
    """The text of the server in a SPARQLWrapper error. SPARQLWrapper keeps it only in the message."""
    message = str(error)
    _, found, rest = message.partition("Response:\n")
    if not found:
        return ""
    try:
        body = ast.literal_eval(rest.strip())
    except (ValueError, SyntaxError):
        return rest.strip()
    return body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)


def json_binding(value: Mapping[str, str]) -> Binding:
    """One value of a SPARQL JSON result (SPARQL 1.1 Query Results JSON Format)."""
    kind = value.get("type", "literal")
    if kind == "typed-literal":   # the old form of some endpoints
        kind = "literal"
    return Binding(kind, value.get("value", ""), value.get("datatype"), value.get("xml:lang"))


class HttpSparqlClient(BaseSparqlClient):
    """A SPARQL 1.1 endpoint over HTTP with SPARQLWrapper (Virtuoso 7.2)."""
    store = "virtuoso"

    def __init__(self, query_url: str, update_url: str, user: Optional[str], password: Optional[str],
                 timeout: float = DEFAULT_TIMEOUT, realm: str = "SPARQL"):
        self.query_url = query_url
        self.update_url = update_url
        self.user = user
        self.password = password
        self.timeout = timeout
        self.realm = realm
        self.key = f"http:{query_url}|{update_url}"

    def _wrapper(self, text: str, form: str):
        sw = _sparqlwrapper()
        wrapper = sw.SPARQLWrapper(self.query_url, updateEndpoint=self.update_url)
        wrapper.setMethod(sw.POST)
        wrapper.setReturnFormat(sw.JSON)
        wrapper.setTimeout(max(1, int(round(self.timeout))))
        wrapper.setQuery(text)
        # SPARQLWrapper finds the form of a request with a regular expression on its text. The client knows the
        # form, so it sets it: the form decides the endpoint and the form field ("query" or "update").
        wrapper.queryType = form
        if form == sw.INSERT:
            wrapper.setHTTPAuth(sw.DIGEST)
            wrapper.setCredentials(self.user, self.password, realm=self.realm)
        return wrapper

    def _send(self, text: str, form: str):
        sw = _sparqlwrapper()
        from SPARQLWrapper.SPARQLExceptions import SPARQLWrapperException
        url = self.update_url if form == sw.INSERT else self.query_url
        wrapper = self._wrapper(text, form)
        try:
            result = wrapper.query()
            if form == sw.INSERT:
                result.response.read()
                result.response.close()
                return None
            if result.info().get(MAX_ROWS_HEADER.lower()) is not None:
                raise SparqlStoreError(f"{url} cut the result ({MAX_ROWS_HEADER}: "
                                       f"{result.info()[MAX_ROWS_HEADER.lower()]}). Remove ResultSetMaxRows from "
                                       "virtuoso.ini (plan 4.1).")
            return result.convert()
        except SparqlStoreError:
            raise
        except SPARQLWrapperException as error:
            status = HTTP_STATUS.get(type(error).__name__)
            raise self._http_error(url, status, response_text(error)) from None
        except urllib.error.HTTPError as error:
            raise self._http_error(url, error.code, error.read().decode("utf-8", "replace")) from None
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError,
                http.client.HTTPException) as error:
            reason = getattr(error, "reason", error)
            raise SparqlStoreError(f"No answer from {url} ({reason}). Does Virtuoso run? "
                                   "Start it with: ./src/scripts/kg.sh up") from None

    def _http_error(self, url: str, status: Optional[int], text: str) -> SparqlStoreError:
        message = f"HTTP {status} from {url}"
        if status == 401:
            message += (": the endpoint refuses the login. Check TRIAD_SPARQL_USER and TRIAD_SPARQL_PASSWORD, "
                        "and run ./src/scripts/kg.sh init")
        elif text.strip():
            message += ": " + server_message(text)
        return SparqlStoreError(message, status)

    def _select(self, text: str) -> tuple[list[str], list[dict[str, Binding]]]:
        data = self._send(text, _sparqlwrapper().SELECT)
        variables = list(data.get("head", {}).get("vars", []))
        rows = [{name: json_binding(value) for name, value in row.items()}
                for row in data.get("results", {}).get("bindings", [])]
        return variables, rows

    def _ask(self, text: str) -> bool:
        data = self._send(text, _sparqlwrapper().ASK)
        value = data.get("boolean")
        if not isinstance(value, bool):
            raise SparqlStoreError(f"{self.query_url} gave no boolean for an ASK query.")
        return value

    def _update(self, text: str) -> None:
        self._send(text, _sparqlwrapper().INSERT)


# ---------------------------------------------------------------------------------------------
# The embedded Oxigraph store

def oxigraph_binding(value: Any) -> Optional[Binding]:
    if value is None:
        return None
    kind = type(value).__name__
    if kind == "NamedNode":
        return Binding("uri", value.value)
    if kind == "BlankNode":
        return Binding("bnode", value.value)
    datatype = value.datatype.value if value.datatype is not None else None
    return Binding("literal", value.value, datatype, value.language)


class EmbeddedSparqlClient(BaseSparqlClient):
    """The embedded Oxigraph store of a folder (one shared Store object for each folder in this process)."""
    store = "oxigraph"

    def __init__(self, path: Optional[Union[str, Path]] = None, store: Any = None):
        from infrastructure.rdf import oxigraph_store
        if store is None:
            store = oxigraph_store.open_store(path)
        self.oxigraph = store
        self.path = Path(path).expanduser().resolve() if path is not None else None
        self.key = f"oxigraph:{self.path}" if self.path is not None else f"oxigraph:memory:{id(store)}"

    def _run(self, call: Callable[[], Any]) -> Any:
        try:
            return call()
        except (SyntaxError, ValueError, OSError, RuntimeError) as error:
            raise SparqlStoreError(f"Oxigraph refused the request: {error}") from None

    def _select(self, text: str) -> tuple[list[str], list[dict[str, Binding]]]:
        def run():
            result = self.oxigraph.query(text)
            names = [v.value for v in result.variables]
            rows = []
            for solution in result:
                row = {}
                for index, name in enumerate(names):
                    found = oxigraph_binding(solution[index])
                    if found is not None:
                        row[name] = found
                rows.append(row)
            return names, rows
        return self._run(run)

    def _ask(self, text: str) -> bool:
        return bool(self._run(lambda: self.oxigraph.query(text)))

    def _update(self, text: str) -> None:
        self._run(lambda: self.oxigraph.update(text))


def open_client(settings) -> BaseSparqlClient:
    """The client of the store of the settings (TRIAD_STORE = virtuoso or oxigraph)."""
    if settings.store == "virtuoso":
        return HttpSparqlClient(settings.sparql_query_url, settings.sparql_update_url, settings.sparql_user,
                                settings.sparql_password)
    if settings.store == "oxigraph":
        return EmbeddedSparqlClient(settings.kg_oxigraph_path)
    raise ValueError(f'The store "{settings.store}" has no SPARQL client.')
