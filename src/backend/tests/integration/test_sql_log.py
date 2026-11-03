"""The SQL log (TRIAD_SQL_LOG, infrastructure/sqlite/sql_log.py): the lines of a request and the connection wrapper."""
from __future__ import annotations

import logging
import re
import sqlite3

import pytest

from infrastructure.sqlite import sql_log
from infrastructure.sqlite.connection import connect
from infrastructure.sqlite.sql_log import LoggedConnection
from tests.conftest import as_user, make_client

OKAFOR = "Doctor:E1005"
ELENA_ID = 1
STATEMENT = re.compile(r"\[sql\] (?P<label>.+?)  (?P<ms>\d+\.\d\d) ms  (?P<rows>\d+) rows?  (?P<sql>\S.*)")
SUMMARY = re.compile(r"\[sql\] (?P<label>.+) (?P<status>\d{3}): (?P<count>\d+) statements?, "
                     r"\d+\.\d ms in SQL, \d+\.\d ms in all\.")


def sql_lines(capsys) -> list[str]:
    return [line for line in capsys.readouterr().err.splitlines() if line.startswith("[sql] ")]


def logged_request(capsys, path, mode="on", db=None, **headers):
    client = make_client(db, sql_log=mode)
    capsys.readouterr()                                    # only the lines of this request
    response = client.get(path, headers=headers or as_user(OKAFOR))
    return response, sql_lines(capsys)


def test_on_logs_each_statement_of_a_request_and_the_summary(scenario_copy, capsys):
    path = f"/api/patients/{ELENA_ID}/chart"
    response, lines = logged_request(capsys, path, db=scenario_copy)
    assert response.status_code == 200, response.text
    *statements, summary = lines
    parsed = [STATEMENT.fullmatch(line) for line in statements]
    assert statements and all(parsed), statements
    assert {m["label"] for m in parsed} == {f"GET {path}"}
    assert any(m["sql"].startswith("SELECT") and int(m["rows"]) > 0 for m in parsed)
    assert all("\n" not in m["sql"] and "  " not in m["sql"] for m in parsed)   # one line, no extra spaces
    total = SUMMARY.fullmatch(summary)
    assert total and total["label"] == f"GET {path}" and total["status"] == "200"
    assert int(total["count"]) == len(statements)


def test_the_summary_gives_the_status_of_the_response(scenario_copy, capsys):
    response, lines = logged_request(capsys, f"/api/patients/{ELENA_ID}/chart", db=scenario_copy,
                                     **{"X-Triad-User": "Doctor:E9999"})
    assert response.status_code >= 400
    assert SUMMARY.fullmatch(lines[-1])["status"] == str(response.status_code)


def test_off_logs_nothing(scenario_copy, capsys):
    response, lines = logged_request(capsys, f"/api/patients/{ELENA_ID}/chart", mode="off", db=scenario_copy)
    assert response.status_code == 200
    assert lines == []


def test_on_does_not_log_the_bound_values(scenario_copy, capsys):
    response, lines = logged_request(capsys, "/api/patients?q=Elena", db=scenario_copy)
    assert response.status_code == 200, response.text
    text = "\n".join(lines)
    assert "LIKE ?" in text                                # the search ran, and its line has the SQL
    assert "elena" not in text.lower()                     # no bound value, no query string
    assert SUMMARY.fullmatch(lines[-1])["label"] == "GET /api/patients"


def test_params_logs_the_bound_values(scenario_copy, capsys):
    response, lines = logged_request(capsys, "/api/patients?q=Elena", mode="params", db=scenario_copy)
    assert response.status_code == 200, response.text
    assert any("LIKE ?" in line and "params: " in line and "'%elena%'" in line for line in lines)
    assert SUMMARY.fullmatch(lines[-1])["label"] == "GET /api/patients?q=Elena"


def test_only_the_api_paths_get_a_summary(scenario_copy, capsys):
    response, lines = logged_request(capsys, "/openapi.json", db=scenario_copy)
    assert response.status_code == 200
    assert lines == []


def test_create_app_adds_the_handler_only_once(scenario_copy):
    root_handlers = list(logging.getLogger().handlers)
    make_client(scenario_copy, sql_log="on")
    make_client(scenario_copy, sql_log="on")
    names = [h.get_name() for h in logging.getLogger("triad.sql").handlers]
    assert names.count(sql_log.HANDLER_NAME) == 1
    assert logging.getLogger().handlers == root_handlers   # the root logger does not change


# ----- the wrapper gives the same results as a plain connection -----

def run_statements(conn) -> list:
    """The same statements on a plain or a logged connection. The result holds all that the code can see."""
    out = []
    conn.execute("CREATE TABLE T (Id INTEGER PRIMARY KEY, Name TEXT NOT NULL UNIQUE)")
    out.append(conn.execute("INSERT INTO T (Name) VALUES (?)", ("a",)).lastrowid)
    out.append(conn.execute("INSERT INTO T (Name) VALUES (:name)", {"name": "b"}).lastrowid)
    many = conn.executemany("INSERT INTO T (Name) VALUES (?)", ((name,) for name in "cde"))
    out.append(many.rowcount)
    out.append(conn.execute("UPDATE T SET Name = upper(Name) WHERE Id > ?", (3,)).rowcount)
    cursor = conn.execute("SELECT Id, Name FROM T ORDER BY Id")
    out.append([column[0] for column in cursor.description])
    first = cursor.fetchone()
    out.append((first["Id"], first["Name"]))
    out.append([tuple(row) for row in cursor.fetchmany(2)])
    out.append([tuple(row) for row in cursor])                        # iteration gives the other rows
    out.append(cursor.fetchone())                                     # no more rows
    out.append([tuple(row) for row in conn.execute("SELECT Name FROM T WHERE Id < 3").fetchall()])
    out.append(conn.execute("SELECT 1 WHERE 0").fetchone())
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute("INSERT INTO T (Name) VALUES ('a')")
    conn.execute("BEGIN IMMEDIATE")
    out.append(conn.in_transaction)
    conn.execute("ROLLBACK")
    out.append(conn.row_factory is sqlite3.Row)
    return out


def test_the_wrapper_gives_the_same_results_as_a_plain_connection(tmp_path, capsys):
    sql_log.configure_logger()
    plain = connect(tmp_path / "plain.db")
    logged = LoggedConnection(connect(tmp_path / "logged.db"))
    try:
        assert run_statements(logged) == run_statements(plain)
    finally:
        plain.close()
        logged.close()
    lines = sql_lines(capsys)
    assert len(lines) == 11                                            # one line for each statement
    assert all(line.startswith("[sql] (no request)  ") for line in lines)   # no request: no error
    assert any("failed (IntegrityError)" in line for line in lines)
    assert any(line.endswith("3 rows  INSERT INTO T (Name) VALUES (?)") for line in lines)   # executemany
    assert not any("params: " in line for line in lines)


def test_the_wrapper_passes_the_attributes_to_the_connection(tmp_path):
    conn = connect(tmp_path / "a.db")
    logged = LoggedConnection(conn)
    logged.row_factory = None
    assert conn.row_factory is None and logged.row_factory is None
    logged.close()
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")
