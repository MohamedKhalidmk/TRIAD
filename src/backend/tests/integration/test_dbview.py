"""The metadata of the database viewer (src/scripts/dbview_metadata.py, used by src/scripts/dbview.sh).

The viewer gets its queries from dml/03_select_queries.sql and adds the schema queries.
Each query must be one statement that runs on the full database.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "dbview_metadata.py"


@pytest.fixture(scope="module")
def dbview():
    spec = importlib.util.spec_from_file_location("dbview_metadata", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_viewer_gets_each_query_of_the_select_file(dbview):
    names = list(dbview.select_queries())
    assert names == ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8", "Q9a", "Q9b", "Q10", "Q11", "Q12", "Q13",
                     "Q14a", "Q14b"]
    q3 = dbview.select_queries()["Q3"]
    assert q3["title"].startswith("Q3. The 3MT slide question")
    assert q3["sql"].lstrip().upper().startswith(("SELECT", "WITH"))


def test_the_metadata_names_the_database_by_its_file(dbview):
    data = json.loads(json.dumps(dbview.metadata("triad")))
    queries = data["databases"]["triad"]["queries"]
    assert {"Q1", "Q14b", "schema_tables", "schema_columns", "schema_foreign_keys", "schema_triggers",
            "schema_indexes"} <= set(queries)
    assert "read-only" in data["title"]


def test_each_query_of_the_viewer_runs_on_the_full_database(dbview, full_db):
    conn = sqlite3.connect(f"file:{full_db}?mode=ro", uri=True)
    try:
        for name, query in dbview.metadata("triad")["databases"]["triad"]["queries"].items():
            conn.execute(query["sql"]).fetchall()           # an error fails the test with the name below
    except sqlite3.Error as error:
        pytest.fail(f"{name}: {error}")
    finally:
        conn.close()


def test_the_schema_queries_show_the_relations_and_the_triggers(dbview, full_db):
    conn = sqlite3.connect(f"file:{full_db}?mode=ro", uri=True)
    try:
        run = lambda name: conn.execute(dbview.SCHEMA_QUERIES[name]["sql"]).fetchall()  # noqa: E731
        assert len(run("schema_tables")) == 29
        assert len(run("schema_triggers")) == 11
        assert ("Assertion", "SupersedesId", "Assertion", "Id") in {row[:4] for row in run("schema_foreign_keys")}
    finally:
        conn.close()
