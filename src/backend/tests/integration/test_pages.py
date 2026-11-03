"""The pages of the list endpoints (doc/api.md section 1.5), on a copy of the full database.

For each list: page 1 and page 2 are slices of the full order, `total` is correct, an offset after the end
gives no items, and a limit or an offset out of range gives 422. The chart also has `counts` and `q`.
"""
from __future__ import annotations

import re
import shutil
import sqlite3

import pytest

from application.paging import PageRequest
from application.users import PINNED_KEYS
from domain.rules import parse_time
from infrastructure import config
from infrastructure.sqlite.connection import connect
from infrastructure.sqlite.records_repository import CHART_CATEGORIES, SqliteRecordRepository
from tests.conftest import all_items, as_user, make_client
from tests.integration.test_api import q12_ids

pytestmark = pytest.mark.slow

ELENA, PATIENT_B = "Patient:MRN-000001", "Patient:0c1b260c-7f32-fdd5-15dd-1160caf24c2b"
SOFIA, OKAFOR = "MOA:E1001", "Doctor:E1005"
B_ID, B_NAME, B_DOB = 81, "Marlin805 Reggie481 Nienow652", "1966-02-18"
B_DOCTOR = "Doctor:9999981795"            # a Synthea doctor on the current care team of Patient B
LONG_PATIENT, LONG_DOCTOR = 61, "Doctor:9999948794"   # the patient with the longest chart and chain


def head_of_longest_chain(path, patient_id: int) -> int:
    """The current assertion of the longest chain of the patient."""
    conn = connect(path)
    try:
        repo = SqliteRecordRepository(conn)
        heads = [r[0] for r in conn.execute(
            "SELECT a.Id FROM Assertion a JOIN ClinicalEntry e ON e.Id = a.ClinicalEntryId "
            "JOIN Visit v ON v.Id = e.VisitId WHERE v.PatientId = ? AND a.SupersedesId IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM Assertion n WHERE n.SupersedesId = a.Id)", (patient_id,))]
        return max(heads, key=lambda h: repo.chain_page(h, PageRequest(1)).total)
    finally:
        conn.close()


@pytest.fixture(scope="module")
def api(full_db, tmp_path_factory):
    """One API client for the read tests of this module, with 4 more chat sessions of Dr. Okafor about Elena."""
    path = tmp_path_factory.mktemp("pages") / "pages.db"
    shutil.copy(full_db, path)
    client = make_client(path)
    for _ in range(4):
        assert client.post("/api/patients/1/chat/sessions", headers=as_user(OKAFOR)).status_code == 201
    client.db_path = path
    return client


@pytest.fixture(scope="module")
def b_chain(api) -> int:
    return head_of_longest_chain(api.db_path, B_ID)


def lists(b_chain: int) -> list[tuple[str, str, str | None, dict]]:
    """(name, url, user, params) of each paged list endpoint. The audit list is in its own test."""
    return [
        ("users", "/api/users", None, {}),
        ("users of a role", "/api/users", None, {"role": "Doctor"}),
        ("patients", "/api/patients", SOFIA, {}),
        ("visits", f"/api/patients/{B_ID}/visits", SOFIA, {}),
        ("chart", f"/api/patients/{B_ID}/chart", B_DOCTOR, {}),
        ("chart history", f"/api/patients/{B_ID}/chart", B_DOCTOR, {"history": "true"}),
        ("patient chart", f"/api/patients/{B_ID}/chart", PATIENT_B, {}),
        ("chain", f"/api/assertions/{b_chain}/chain", B_DOCTOR, {}),
        ("chat sessions", "/api/patients/1/chat/sessions", OKAFOR, {}),
        ("departments", "/api/departments", SOFIA, {}),
        ("locations", "/api/locations", SOFIA, {}),
        ("staff", "/api/staff", SOFIA, {}),
        ("medications", "/api/medications", SOFIA, {}),
    ]


def get(client, url: str, user, **params) -> dict:
    response = client.get(url, headers=as_user(user) if user else {}, params=params)
    assert response.status_code == 200, response.text
    return response.json()


# ----- each list -----

def test_page_1_and_page_2_are_slices_of_the_full_order(api, b_chain):
    for name, url, user, params in lists(b_chain):
        full = all_items(api, url, user, **params)
        total = len(full)
        assert total >= 5, name
        first = get(api, url, user, **params, limit=2)
        second = get(api, url, user, **params, limit=2, offset=2)
        assert first["items"] == full[:2] and second["items"] == full[2:4], name
        assert (first["total"], first["limit"], first["offset"]) == (total, 2, 0), name
        assert (second["total"], second["limit"], second["offset"]) == (total, 2, 2), name
        default = get(api, url, user, **params)
        assert (default["limit"], default["offset"]) == (25, 0) and default["items"] == full[:25], name
        last = get(api, url, user, **params, limit=5, offset=total - 1)
        assert last["items"] == full[-1:] and last["total"] == total, name
        past = get(api, url, user, **params, limit=5, offset=total + 10)
        assert past["items"] == [] and past["total"] == total, name
        assert len({str(item.get("id") or item.get("key")) for item in full}) == total, name   # no row twice


@pytest.mark.parametrize("params,field", [({"limit": 0}, "limit"), ({"limit": 201}, "limit"),
                                          ({"offset": -1}, "offset"), ({"limit": "ten"}, "limit"),
                                          ({"offset": "1.5"}, "offset")])
def test_a_page_value_out_of_range_gives_422(api, b_chain, params, field):
    for name, url, user, filters in lists(b_chain) + [("audit", "/api/patients/1/audit", OKAFOR, {})]:
        response = api.get(url, headers=as_user(user) if user else {}, params={**filters, **params})
        body = response.json()
        assert response.status_code == 422 and body["code"] == "validation", name
        assert list(body["fields"]) == [field] and body["message"] == "The input is not correct.", name
    assert get(api, "/api/staff", SOFIA, limit=200)["limit"] == 200            # 200 is the largest page


# ----- the order of each list -----

def test_the_demo_users_come_first_on_all_pages(api):
    first = get(api, "/api/users", None, limit=5)
    second = get(api, "/api/users", None, limit=5, offset=5)
    assert [u["key"] for u in first["items"]] == list(PINNED_KEYS[:5]) and all(u["pinned"] for u in first["items"])
    assert [u["key"] for u in second["items"][:3]] == list(PINNED_KEYS[5:])
    assert not any(u["pinned"] for u in second["items"][3:])
    full = all_items(api, "/api/users")
    rest = full[len(PINNED_KEYS):]
    assert [(u["name"].lower(), u["key"]) for u in rest] == sorted((u["name"].lower(), u["key"]) for u in rest)
    assert full[0]["detail"] == "born 1971-05-14" and full[2]["detail"] == "Front Office"
    nurses = get(api, "/api/users", None, role="Nurse", limit=2, offset=1)
    assert [u["key"] for u in nurses["items"]] == ["Nurse:E1003", "Nurse:E1004"]
    assert get(api, "/api/users", None, q="okafor")["total"] == 1


def test_the_lists_use_their_order(api, b_chain):
    patients = all_items(api, "/api/patients", SOFIA)
    assert [(p["name"], p["id"]) for p in patients] == sorted((p["name"], p["id"]) for p in patients)
    visits = all_items(api, f"/api/patients/{B_ID}/visits", SOFIA)
    starts = [parse_time(v["startDate"]) for v in visits]
    assert starts == sorted(starts, reverse=True)                                   # newest first
    chain = all_items(api, f"/api/assertions/{b_chain}/chain", B_DOCTOR)
    assert chain[0]["id"] == b_chain and chain[0]["isCurrent"]
    assert [a["supersedesId"] for a in chain[:-1]] == [a["id"] for a in chain[1:]]  # newest first, one link each
    staff = all_items(api, "/api/staff", SOFIA)
    hospital = [s for s in staff if s["identifier"]["system"] == "https://triad.example/fhir/sid/employee"]
    assert staff[:len(hospital)] == hospital and len(staff) == 292
    assert [s["name"] for s in staff[len(hospital):]] == sorted(s["name"] for s in staff[len(hospital):])
    medications = all_items(api, "/api/medications", SOFIA)
    assert [m["name"] for m in medications] == sorted(m["name"] for m in medications)
    departments = all_items(api, "/api/departments", SOFIA)
    assert [d["name"] for d in departments] == sorted(d["name"] for d in departments)
    locations = all_items(api, "/api/locations", SOFIA)
    assert [loc["id"] for loc in locations] == sorted(loc["id"] for loc in locations)
    sessions = all_items(api, "/api/patients/1/chat/sessions", OKAFOR)
    assert [s["id"] for s in sessions] == sorted((s["id"] for s in sessions), reverse=True)


def chart_key(a: dict):
    return CHART_CATEGORIES.index(a["category"]), -parse_time(a["assertedAt"]).timestamp(), -a["id"]


def test_the_chart_is_in_the_category_order_then_newest_first(api):
    for params in ({}, {"history": "true"}):
        items = all_items(api, f"/api/patients/{B_ID}/chart", B_DOCTOR, **params)
        assert items == sorted(items, key=chart_key)
    # The longest chart: the full order in one repository call, and the last API page is its end.
    conn = connect(api.db_path)
    views = SqliteRecordRepository(conn).items_page(LONG_PATIENT, page=PageRequest(limit=20000)).items
    conn.close()
    rows = [{"category": a.category, "assertedAt": a.asserted_at, "id": a.id} for a in views]
    assert len(rows) == 12471 and rows == sorted(rows, key=chart_key)
    last = get(api, f"/api/patients/{LONG_PATIENT}/chart", LONG_DOCTOR, limit=200, offset=12400)
    assert [a["id"] for a in last["items"]] == [r["id"] for r in rows[12400:]] and last["total"] == 12471


def test_the_longest_chain_in_pages_of_200(api):
    head = head_of_longest_chain(api.db_path, LONG_PATIENT)
    first = get(api, f"/api/assertions/{head}/chain", LONG_DOCTOR, limit=200)
    second = get(api, f"/api/assertions/{head}/chain", LONG_DOCTOR, limit=200, offset=200)
    assert first["total"] == second["total"] == 222 and len(first["items"]) == 200 and len(second["items"]) == 22
    conn = connect(api.db_path)
    order = [a.id for a in SqliteRecordRepository(conn).chain(head)]
    conn.close()
    assert [a["id"] for a in first["items"] + second["items"]] == order
    middle = first["items"][100]["id"]                     # the chain of any assertion in it is the same chain
    assert get(api, f"/api/assertions/{middle}/chain", LONG_DOCTOR, limit=3)["headId"] == head


# ----- the chart: counts, search and the patient-visible rule -----

def test_the_chart_counts_ignore_the_category_filter(api):
    url = f"/api/patients/{B_ID}/chart"
    full = all_items(api, url, B_DOCTOR)
    expected = {c: n for c in CHART_CATEGORIES if (n := sum(a["category"] == c for a in full))}
    page = get(api, url, B_DOCTOR, limit=1)
    assert page["counts"] == expected and sum(page["counts"].values()) == page["total"] == len(full)
    assert "Allergy" not in page["counts"] and page["patientId"] == B_ID           # a category with no item
    observations = get(api, url, B_DOCTOR, category="Observation", limit=3)
    assert observations["counts"] == expected and observations["total"] == expected["Observation"]
    assert observations["items"] == [a for a in full if a["category"] == "Observation"][:3]
    history = get(api, url, B_DOCTOR, history="true", limit=1)
    assert sum(history["counts"].values()) == history["total"] > page["total"]
    visit = full[0]["visitId"]
    in_visit = get(api, url, B_DOCTOR, visitId=visit, limit=200)
    assert in_visit["items"] == [a for a in full if a["visitId"] == visit]
    assert sum(in_visit["counts"].values()) == in_visit["total"]
    assert get(api, url, B_DOCTOR, category="Allergy")["items"] == []
    bad = api.get(url, headers=as_user(B_DOCTOR), params={"category": "Nothing"})
    assert bad.status_code == 422 and "category" in bad.json()["fields"]


@pytest.mark.parametrize("q", ["METFORMIN", "roberts511", "hypertension", "  ", "no-such-text"])
def test_the_chart_search_is_in_the_display_the_statement_and_the_author_name(api, q):
    url = f"/api/patients/{B_ID}/chart"
    full = all_items(api, url, B_DOCTOR, history="true")
    needle = q.strip().lower()
    expected = [a for a in full if needle in a["display"].lower() or needle in a["statement"].lower()
                or needle in a["author"]["name"].lower()]
    found = all_items(api, url, B_DOCTOR, history="true", q=q)
    assert found == expected
    page = get(api, url, B_DOCTOR, history="true", q=q, limit=1)
    assert page["total"] == len(expected) and sum(page["counts"].values()) == len(expected)
    if needle and needle != "no-such-text":
        assert expected and len(expected) < len(full)


def test_the_patient_chart_total_is_the_size_of_the_q12_set(api):
    for key, pid, name, dob in ((ELENA, 1, "Elena Marsh", "1971-05-14"), (PATIENT_B, B_ID, B_NAME, B_DOB)):
        page = get(api, f"/api/patients/{pid}/chart", key, limit=1, history="true")    # history is staff only
        q12 = q12_ids(api.db_path, name, dob)
        assert page["total"] == len(q12) == sum(page["counts"].values())
        items = all_items(api, f"/api/patients/{pid}/chart", key)
        assert {a["id"] for a in items} == q12 and all(a["patientVisible"] and a["isCurrent"] for a in items)
    staff = get(api, f"/api/patients/{B_ID}/chart", B_DOCTOR, limit=1)["total"]
    assert staff > get(api, f"/api/patients/{B_ID}/chart", PATIENT_B, limit=1)["total"]


def test_the_sql_patient_visible_rule_is_the_rules_py_rule_for_each_patient(db, full_db):
    """The predicate of Q12 in the chart query gives the same items as domain.rules.is_patient_visible."""
    repo = SqliteRecordRepository(db)
    patients = db.execute("SELECT Id, Name, DateOfBirth FROM Patient").fetchall()
    assert len(patients) == 113
    for pid, name, dob in patients:
        rules = {a.id for a in repo.assertions(pid, current_only=True) if a.patient_visible}
        page = repo.items_page(pid, visible_only=True, page=PageRequest(limit=20000))
        sql = {a.id for a in page.items}
        assert sql == rules == q12_ids(full_db, name, dob), name
        assert page.total == len(sql) == sum(repo.category_counts(pid, visible_only=True).values())


def test_query_q14_is_the_second_chart_page_of_patient_b(api):
    """Q14a and Q14b of dml/03_select_queries.sql give the page and the total of the API."""
    text = (config.DML_DIR / "03_select_queries.sql").read_text(encoding="utf-8")
    page_sql = re.search(r"-- Q14a\..*?(SELECT e\.Category.*?;)", text, re.S).group(1)
    count_sql = re.search(r"-- Q14b\..*?(SELECT COUNT.*?;)", text, re.S).group(1)
    page_sql = re.sub(r"SELECT e\.Category.*?FROM Patient p", "SELECT a.Id FROM Patient p", page_sql, count=1,
                      flags=re.S)
    conn = sqlite3.connect(api.db_path)
    ids = [r[0] for r in conn.execute(page_sql)]
    total = conn.execute(count_sql).fetchone()[0]
    conn.close()
    page = get(api, f"/api/patients/{B_ID}/chart", B_DOCTOR, limit=25, offset=25)
    assert [a["id"] for a in page["items"]] == ids and len(ids) == 25
    assert page["total"] == total == 574


# ----- the lists of one row, and the audit -----

def test_a_patient_gets_one_row_in_the_patient_list_and_in_the_chain(api, b_chain):
    own = get(api, "/api/patients", PATIENT_B)
    assert [p["id"] for p in own["items"]] == [B_ID] and own["total"] == 1
    assert get(api, "/api/patients", PATIENT_B, offset=1) == {"items": [], "total": 1, "limit": 25, "offset": 1}
    chain = get(api, f"/api/assertions/{b_chain}/chain", PATIENT_B)
    assert [a["id"] for a in chain["items"]] == [b_chain] and chain["total"] == 1 and chain["headId"] == b_chain
    assert get(api, f"/api/assertions/{b_chain}/chain", PATIENT_B, offset=1)["items"] == []
    assert get(api, "/api/patients", SOFIA, scope="care-team")["total"] == 0          # an MOA has no care team


def count_audit(path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM AuditEvent").fetchone()[0]
    finally:
        conn.close()


def test_each_chart_or_chain_page_writes_one_audit_record_and_a_list_writes_none(client, full_copy):
    before = count_audit(full_copy)
    for offset in (0, 25, 5000):
        get(client, f"/api/patients/{B_ID}/chart", B_DOCTOR, offset=offset)
    get(client, "/api/assertions/1/chain", OKAFOR, limit=1, offset=1)
    assert count_audit(full_copy) == before + 4
    for url, user in (("/api/users", None), ("/api/patients", SOFIA), (f"/api/patients/{B_ID}/visits", SOFIA),
                      ("/api/patients/1/chat/sessions", OKAFOR), ("/api/departments", SOFIA),
                      ("/api/locations", SOFIA), ("/api/staff", SOFIA), ("/api/medications", SOFIA)):
        get(client, url, user, limit=3, offset=3)
    assert count_audit(full_copy) == before + 4


def test_the_audit_pages_and_the_denied_count(client, full_copy):
    """Each audit read adds one record at the top, so a later page starts one row later in the older list."""
    assert client.get("/api/patients/1/chart", headers=as_user("Nurse:E1004")).status_code == 403
    full = all_items(client, "/api/patients/1/audit", OKAFOR)
    assert full[0]["action"] == "read" and full[0]["actorKey"] == OKAFOR
    second = get(client, "/api/patients/1/audit", OKAFOR, limit=3, offset=3)       # one more record at the top
    assert second["items"] == full[2:5] and second["total"] == len(full) + 1
    denied = sum(e["outcome"] == "Denied" for e in full)
    assert denied >= 2 and second["denied"] == denied                               # all pages, not this page
    past = get(client, "/api/patients/1/audit", OKAFOR, offset=1000)
    assert past["items"] == [] and past["total"] == len(full) + 2 and past["denied"] == denied
