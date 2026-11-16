"""The SPARQL client (infrastructure/sparql/client.py): the value conversion, the time form and the HTTP driver.

HttpSparqlClient (SPARQLWrapper) runs against a fake endpoint on 127.0.0.1 that answers like Virtuoso 7.2
(plan 4.2): queries on /sparql with no login, updates on /sparql-auth with a digest login, HTTP 500 with the
Virtuoso text, and the header X-SPARQL-MaxRows when it cuts a result. No Docker.
"""
from __future__ import annotations

import hashlib
import json
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from infrastructure.sparql import client as sc
from infrastructure.sparql.client import Binding, SparqlStoreError
from infrastructure.sparql.terms import XSD

pytest.importorskip("SPARQLWrapper")

REALM, USER, PASSWORD, NONCE = "SPARQL", "triad", "secret", "dcd98b7102dd2f0e8b11d0f600bfb0c093"
VIRTUOSO_500 = ("Virtuoso 42000 Error SR186:SECURITY: No permission to execute procedure DB.DBA.SPARQL_INSERT_DICT"
                "_CONTENT with user ID 107, group ID 107\n\nSPARQL query:\ndefine sql:big-data-const 0 INSERT DATA {}")
SELECT_RESULT = {"head": {"vars": ["s", "n", "b", "t", "d", "name", "none", "x"]}, "results": {"bindings": [{
    "s": {"type": "uri", "value": "https://github.com/MohamedKhalidmk/TRIAD/kg/patient/1"},
    "n": {"type": "typed-literal", "datatype": XSD + "integer", "value": "57022"},
    "b": {"type": "literal", "datatype": XSD + "boolean", "value": "1"},
    "t": {"type": "literal", "datatype": XSD + "dateTime", "value": "2026-10-30T13:00:00Z"},
    "d": {"type": "literal", "datatype": XSD + "date", "value": "1971-05-14"},
    "name": {"type": "literal", "value": "Elena \"E\" Marsh"},
    "x": {"type": "literal", "datatype": XSD + "decimal", "value": "2.5"}}]}}


def md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


class FakeVirtuoso(BaseHTTPRequestHandler):
    """Answers like Virtuoso. The server object holds the settings and records the requests."""

    def log_message(self, *args):   # no output in the tests
        pass

    def _answer(self, status: int, body: bytes, content_type: str = "application/sparql-results+json",
                headers: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _digest_ok(self) -> bool:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Digest "):
            return False
        parts = dict(urllib.parse.parse_qsl(header[7:].replace(", ", "&").replace('"', ""), keep_blank_values=True))
        ha1 = md5(f"{parts.get('username')}:{REALM}:{self.server.password}")
        ha2 = md5(f"{self.command}:{parts.get('uri')}")
        expected = md5(f"{ha1}:{NONCE}:{parts.get('nc')}:{parts.get('cnonce')}:{parts.get('qop')}:{ha2}")
        return parts.get("response") == expected and parts.get("username") == USER

    def do_POST(self):
        server = self.server
        length = int(self.headers.get("Content-Length", "0"))
        form = dict(urllib.parse.parse_qsl(self.rfile.read(length).decode("utf-8")))
        if server.sleep:
            time.sleep(server.sleep)
        if self.path.startswith("/sparql-auth"):
            if not self._digest_ok():
                server.challenges += 1
                self.send_response(401)
                self.send_header("WWW-Authenticate", f'Digest realm="{REALM}", nonce="{NONCE}", qop="auth", '
                                                     'algorithm="MD5", opaque="5ccc069c403ebaf9f0171e9517f40e41"')
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            server.calls.append(("update", self.path, form.get("update"), True))
            if server.fail_status:
                self._answer(server.fail_status, VIRTUOSO_500.encode(), "text/plain")
                return
            body = {"head": {"vars": ["callret-0"]}, "results": {"bindings": [
                {"callret-0": {"type": "literal", "value": "Insert into <g>, 1 (or less) triples -- done"}}]}}
            self._answer(200, json.dumps(body).encode())
            return
        query = form.get("query", "")
        server.calls.append(("query", self.path, query, "Authorization" in self.headers))
        if server.fail_status:
            self._answer(server.fail_status, VIRTUOSO_500.encode(), "text/plain")
            return
        headers = {"X-SPARQL-MaxRows": "10000"} if server.max_rows else {}
        if "ASK" in query:
            self._answer(200, json.dumps({"head": {}, "boolean": True}).encode(), headers=headers)
        else:
            self._answer(200, json.dumps(SELECT_RESULT).encode(), headers=headers)


@pytest.fixture
def endpoint():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeVirtuoso)
    server.calls, server.challenges, server.password = [], 0, PASSWORD
    server.fail_status, server.max_rows, server.sleep = 0, False, 0
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def http_client(server, password: str = PASSWORD, timeout: float = 5) -> sc.HttpSparqlClient:
    base = f"http://127.0.0.1:{server.server_address[1]}"
    return sc.HttpSparqlClient(f"{base}/sparql", f"{base}/sparql-auth", USER, password, timeout=timeout)


# ----- the conversion of the values (both stores) -----

def test_the_time_form_of_d11():
    assert sc.output_time("2026-10-30T13:00:00Z") == "2026-10-30T13:00:00+00:00"
    assert sc.output_time("2026-10-02T11:45:10.1-04:00") == "2026-10-02T11:45:10.1-04:00"   # the rest stays
    assert sc.output_time("2026-10-30T09:00:00-04:00") == "2026-10-30T09:00:00-04:00"


def test_the_python_values():
    assert sc.python_value(None) is None
    assert sc.python_value(Binding("uri", "urn:x")) == "urn:x"
    assert sc.python_value(Binding("literal", "7", XSD + "integer")) == 7
    assert sc.python_value(Binding("literal", "7", XSD + "long")) == 7
    assert sc.python_value(Binding("literal", "2.5", XSD + "double")) == 2.5
    assert sc.python_value(Binding("literal", "true", XSD + "boolean")) is True
    assert sc.python_value(Binding("literal", "0", XSD + "boolean")) is False
    assert sc.python_value(Binding("literal", "2026-10-30T13:00:00Z", XSD + "dateTime")) == "2026-10-30T13:00:00+00:00"
    assert sc.python_value(Binding("literal", "1971-05-14", XSD + "date")) == "1971-05-14"
    assert sc.python_value(Binding("literal", "text", XSD + "string")) == "text"
    assert sc.python_value(Binding("literal", "text")) == "text"


def test_the_sparql_form_of_a_stored_value_is_unchanged():
    assert sc.sparql_term(Binding("uri", "urn:x")) == "<urn:x>"
    assert sc.sparql_term(Binding("literal", 'a "b"')) == '"a \\"b\\""'
    assert sc.sparql_term(Binding("literal", "a", XSD + "string")) == '"a"'
    assert sc.sparql_term(Binding("literal", "hi", None, "en")) == '"hi"@en'
    assert sc.sparql_term(Binding("literal", "2026-10-30T13:00:00Z", XSD + "dateTime")) == \
           f'"2026-10-30T13:00:00Z"^^<{XSD}dateTime>'


def test_a_query_needs_a_dataset_clause():
    client = sc.EmbeddedSparqlClient(None) if pytest.importorskip("pyoxigraph") else None
    with pytest.raises(ValueError, match="rule 1"):
        client.select("SELECT * WHERE { ?s ?p ?o }")
    assert client.select("SELECT * FROM $abox WHERE { ?s ?p ?o }") == []


# ----- HttpSparqlClient against the fake Virtuoso -----

def test_a_select_goes_to_the_query_url_with_no_login(endpoint):
    rows = http_client(endpoint).select("SELECT ?s FROM $abox WHERE { ?s triad:name $name }", {"name": "Elena"})
    assert rows == [{"s": "https://github.com/MohamedKhalidmk/TRIAD/kg/patient/1", "n": 57022, "b": True,
                     "t": "2026-10-30T13:00:00+00:00", "d": "1971-05-14", "name": 'Elena "E" Marsh', "none": None,
                     "x": 2.5}]
    [(form, path, text, login)] = endpoint.calls
    assert (form, path, login) == ("query", "/sparql", False)
    assert 'triad:name "Elena"' in text and text.startswith("PREFIX triad:")


def test_an_ask_gives_a_boolean(endpoint):
    assert http_client(endpoint).ask("ASK FROM $abox WHERE { ?s ?p ?o }") is True
    assert endpoint.calls[0][:2] == ("query", "/sparql")


def test_an_update_goes_to_the_update_url_with_a_digest_login(endpoint):
    client = http_client(endpoint)
    client.update("WITH $abox DELETE { $s triad:phoneNumber ?old } INSERT { $s triad:phoneNumber $new } "
                  "WHERE { $s a ?type . OPTIONAL { $s triad:phoneNumber ?old } }",
                  {"s": sc.terms.iri("patient", 1), "new": "555"})
    [(form, path, text, login)] = endpoint.calls
    assert (form, path, login) == ("update", "/sparql-auth", True)
    assert endpoint.challenges == 1                         # one extra 401 round trip (plan 5.2)
    assert text.lstrip().split("\n")[-1].startswith("WITH <https://github.com/MohamedKhalidmk/TRIAD/graph/abox>")


def test_http_500_raises_a_clear_error_with_the_first_paragraph(endpoint):
    endpoint.fail_status = 500
    with pytest.raises(SparqlStoreError) as error:
        http_client(endpoint).update("INSERT DATA { GRAPH $abox { <urn:a> <urn:b> <urn:c> } }")
    assert error.value.status == 500
    assert "SR186" in str(error.value) and "/sparql-auth" in str(error.value)
    assert "SPARQL query" not in str(error.value)            # Virtuoso writes the query after a blank line
    with pytest.raises(SparqlStoreError) as error:
        http_client(endpoint).select("SELECT * FROM $abox WHERE { ?s ?p ?o }")
    assert error.value.status == 500


def test_a_wrong_password_names_the_settings(endpoint):
    with pytest.raises(SparqlStoreError) as error:
        http_client(endpoint, password="wrong").update("INSERT DATA { GRAPH $abox { <urn:a> <urn:b> <urn:c> } }")
    assert error.value.status == 401 and "TRIAD_SPARQL_PASSWORD" in str(error.value)


def test_a_cut_result_is_an_error(endpoint):
    endpoint.max_rows = True
    with pytest.raises(SparqlStoreError, match="X-SPARQL-MaxRows"):
        http_client(endpoint).select("SELECT * FROM $abox WHERE { ?s ?p ?o }")


def test_the_timeout_and_no_endpoint(endpoint):
    endpoint.sleep = 2.5
    started = time.perf_counter()
    with pytest.raises(SparqlStoreError, match="No answer") as error:
        http_client(endpoint, timeout=1).select("SELECT * FROM $abox WHERE { ?s ?p ?o }")
    assert error.value.status is None and time.perf_counter() - started < 2.4
    with socket.socket() as s:                               # a free port with no server
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    client = sc.HttpSparqlClient(f"http://127.0.0.1:{port}/sparql", f"http://127.0.0.1:{port}/sparql-auth", USER,
                                 PASSWORD, timeout=2)
    with pytest.raises(SparqlStoreError, match="kg.sh up"):
        client.ask("ASK FROM $abox WHERE { ?s ?p ?o }")


def test_open_client_selects_the_store():
    from infrastructure import config
    settings = config.Settings(db_path=config.DEFAULT_DB_PATH, now="system", llm_mode="fake", llm_model="m",
                               frontend_dist=None, store="virtuoso")
    client = sc.open_client(settings)
    assert isinstance(client, sc.HttpSparqlClient) and client.store == "virtuoso"
    assert client.query_url.endswith("/sparql") and client.update_url.endswith("/sparql-auth")
    with pytest.raises(ValueError):
        sc.open_client(config.Settings(db_path=config.DEFAULT_DB_PATH, now="system", llm_mode="fake",
                                       llm_model="m", frontend_dist=None))
