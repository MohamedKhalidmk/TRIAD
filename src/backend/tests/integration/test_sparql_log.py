"""The SPARQL log (TRIAD_SPARQL_LOG, infrastructure/sparql/sparql_log.py): the lines of a request on the KG store.

"on" shows the template of each request (the "$name" placeholders), never the values: a name or a date of birth
does not go into the log. "params" adds the bindings. One middleware writes the summary line for both stores.
"""
from __future__ import annotations

import re

import pytest

from infrastructure.sparql import sparql_log
from tests.conftest import as_user

pytestmark = pytest.mark.stores("oxigraph", "virtuoso")

LINE = re.compile(r"\[sparql\] (?P<label>.+?)  (?P<ms>\d+\.\d\d) ms  (?P<result>\S.*?)  (?P<template>\S.*)")
SUMMARY = re.compile(r"\[sparql\] (?P<label>.+) (?P<status>\d{3}): (?P<count>\d+) requests?, "
                     r"\d+\.\d ms in SPARQL, \d+\.\d ms in all\.")


def lines(capsys) -> list[str]:
    return [line for line in capsys.readouterr().err.splitlines() if line.startswith("[sparql] ")]


def test_on_logs_each_request_with_the_template_and_no_values(store, capsys):
    client = store.client(sparql_log="on")
    capsys.readouterr()
    response = client.get("/api/users", params={"q": "okafor"}, headers=as_user("Patient:MRN-000001"))
    assert response.status_code == 200
    *requests, summary = lines(capsys)
    parsed = [LINE.fullmatch(line) for line in requests]
    assert requests and all(parsed), requests
    assert {m["label"] for m in parsed} == {"GET /api/users"}
    assert all("okafor" not in line and "Elena" not in line and "MRN-000001" not in line for line in requests)
    assert any("$q" in m["template"] for m in parsed)
    total = SUMMARY.fullmatch(summary)
    assert total and total["status"] == "200" and int(total["count"]) == len(requests)
    assert client.get("/api/me", headers=as_user("Patient:MRN-000001")).status_code == 200
    me = lines(capsys)
    assert any("$value" in line for line in me) and not any("MRN-000001" in line or "Elena" in line for line in me)


def test_params_adds_the_values(store, capsys):
    client = store.client(sparql_log="params")
    capsys.readouterr()
    client.get("/api/users", params={"q": "okafor"})
    found = lines(capsys)
    assert any("params:" in line and "'okafor'" in line for line in found)
    assert found[-1].startswith("[sparql] GET /api/users?q=okafor 200:")


def test_off_logs_nothing(store, capsys):
    client = store.client(sparql_log="off")
    capsys.readouterr()
    client.get("/api/users")
    assert lines(capsys) == []


def test_a_write_logs_the_insert_template_without_the_triples(store, capsys):
    from infrastructure.clock import DemoClock
    from infrastructure.sparql.unit_of_work import KgSession, SparqlUnitOfWork
    import main
    sparql_log.configure_logger()
    client = sparql_log.LoggedSparqlClient(main.kg_client(store.settings), show_params=False)
    session = KgSession(client)
    with SparqlUnitOfWork(session, DemoClock("2026-10-30T09:00:00-04:00")).write():
        session.write_buffer().create("medication", {"code": "SECRET-CODE", "codeSystem": "urn:x", "name": "Secret"})
    found = lines(capsys)
    insert = [line for line in found if "INSERT DATA" in line]
    assert len(insert) == 1 and "$triples" in insert[0] and "SECRET" not in "\n".join(found)
