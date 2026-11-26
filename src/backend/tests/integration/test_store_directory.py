"""The directory on each store: departments, locations, staff and medications (DirectoryRepository; plan 5.5, 5.6).

Each test runs on SQLite and on the knowledge graph (Oxigraph; Virtuoso with TRIAD_TEST_STORES). A KG store must
give the same results as SQLite on the same data:
- the reads: each list endpoint with each filter and page slice, and each port method, against `reference`
  (a SQLite client on the same data);
- the writes: each create, change and delete through the API on the store and on `twin` (a SQLite copy of the
  data, made before the test writes), then the same reads on both;
- the errors: each key guard (UNIQUE), each delete of a row in use (FOREIGN KEY), the NOT NULL and CHECK rules
  of the port and the validation errors of the API: the same exception (status), code, message and fields.
The test on the full data (`full_store`, "slow") runs each new query once there and measures the times.
"""
from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Optional

import pytest

from application.paging import PageRequest
from domain.errors import DomainError
from tests.conftest import all_items, as_user, make_client
from tests.fixtures.stores import base_settings

SOFIA, PARK = "MOA:E1001", "Nurse:E1004"
ORG = "https://triad.example/fhir/sid/organization"
LOC = "https://triad.example/fhir/sid/location"
EMPLOYEE = "https://triad.example/fhir/sid/employee"
LISTS = ("/api/departments", "/api/locations", "/api/staff", "/api/medications")
INJECTIONS = ('" } ; DROP ALL ; #', '"', "\\", "'; DROP", "$q", "a\nb")


# ---------------------------------------------------------------------------------------------
# Helpers

@pytest.fixture
def reference(store):
    """A SQLite client on the same data as the store (for the reads)."""
    return make_client(store.db_path)


def copy_db(handle, tmp_path: Path, name: str = "twin.db") -> Path:
    path = tmp_path / name
    shutil.copy(handle.db_path, path)
    return path


@pytest.fixture
def twin_db(store, tmp_path) -> Path:
    """A SQLite copy of the data of the store, made before the test writes (for the writes)."""
    return copy_db(store, tmp_path)


@pytest.fixture
def twin(twin_db):
    return make_client(twin_db)


def sqlite_ctx(db_path: Path):
    import main
    return main.context_factory(base_settings(db_path))()


def answer(response) -> tuple[int, Any]:
    return response.status_code, (response.json() if response.content else None)


def same(api, twin, method: str, url: str, body: Optional[dict] = None, user: str = SOFIA,
         params: Optional[dict] = None) -> Any:
    """Send the same request to the store and to the twin. Both must give the same status and the same body."""
    a = api.request(method, url, headers=as_user(user), json=body, params=params)
    b = twin.request(method, url, headers=as_user(user), json=body, params=params)
    assert answer(a) == answer(b), (method, url, body)
    return a.json() if a.content else None


def same_lists(api, twin) -> None:
    for url in LISTS:
        assert all_items(api, url, SOFIA) == all_items(twin, url, SOFIA), url


def error_of(call: Callable[[], Any]) -> Optional[tuple]:
    """(the exception class, the message, the fields) of a call, or None if it gives no domain error."""
    try:
        call()
    except DomainError as error:
        return type(error).__name__, error.message, error.fields
    return None


def write(ctx, step: Callable[[], Any]) -> Callable[[], Any]:
    def run():
        with ctx.uow.write():
            return step()
    return run


def rows_of(db_path: Path, sql: str, args: tuple = ()) -> list[dict]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


# ---------------------------------------------------------------------------------------------
# The reads

LIST_CASES = [
    ("/api/departments", {}), ("/api/departments", {"q": "care"}), ("/api/departments", {"q": "TRIAD-GH-C"}),
    ("/api/departments", {"q": "  MEDICINE "}), ("/api/departments", {"q": "no such"}),
    ("/api/locations", {}), ("/api/locations", {"department": "emergency"}),
    ("/api/locations", {"department": "TRIAD-GH-CARD"}), ("/api/locations", {"department": "3"}),
    ("/api/locations", {"department": "no such"}), ("/api/locations", {"q": "bed"}),
    ("/api/locations", {"q": "desk", "department": "Cardiology"}), ("/api/locations", {"q": "er-"}),
    ("/api/staff", {}), ("/api/staff", {"role": "Nurse"}),
    ("/api/staff", {"role": "MOA", "department": "front office"}),
    ("/api/staff", {"department": "TRIAD-GH-EMER"}), ("/api/staff", {"department": "7"}),
    ("/api/staff", {"department": "nothing"}), ("/api/staff", {"q": "farid"}), ("/api/staff", {"q": "E1005"}),
    ("/api/staff", {"q": "e1005"}), ("/api/staff", {"q": "a", "role": "Doctor"}),
    ("/api/medications", {}), ("/api/medications", {"q": "amlo"}), ("/api/medications", {"q": "197361"}),
    ("/api/medications", {"q": "nothing"}),
]


@pytest.mark.parametrize("url, params", LIST_CASES)
def test_each_list_is_the_same_on_each_store(store, reference, url, params):
    assert all_items(store.client(), url, SOFIA, **params) == all_items(reference, url, SOFIA, **params)


def test_the_lists_of_the_planted_data_are_the_same_on_each_store(planted_store):
    """The planted data deleted a location and a medication (04_update_delete.sql): the ids have gaps."""
    api, reference = planted_store.client(), make_client(planted_store.db_path)
    for url, params in LIST_CASES:
        assert all_items(api, url, SOFIA, **params) == all_items(reference, url, SOFIA, **params), (url, params)


@pytest.mark.parametrize("url, params", [("/api/departments", {}), ("/api/locations", {}),
                                         ("/api/locations", {"department": "emergency"}), ("/api/staff", {}),
                                         ("/api/staff", {"role": "Nurse", "q": "a"}), ("/api/medications", {})])
def test_each_page_is_a_slice_of_the_full_list(planted_store, url, params):
    api, reference = planted_store.client(), make_client(planted_store.db_path)
    full = all_items(reference, url, SOFIA, **params)
    for offset in (0, 3, 7, len(full) - 1, len(full), len(full) + 5):
        page = api.get(url, headers=as_user(SOFIA), params={**params, "limit": 3, "offset": offset}).json()
        assert page["total"] == len(full)
        assert page["items"] == full[offset:offset + 3]


def test_the_staff_languages_are_by_name_on_each_store(store):
    """Plan 5.5: SPARQL has no order for a set of literals, so both stores give the languages by name."""
    becker = store.client().get("/api/staff", headers=as_user(SOFIA), params={"q": "E1003"}).json()["items"][0]
    assert becker["languages"] == ["de", "en"]          # entered as en, de


def test_the_port_reads_are_the_same_on_each_store(planted_store):
    ctx, ref = planted_store.open_ctx(), planted_store.reference()
    d, r = ctx.directory, ref.directory
    db = planted_store.db_path
    try:
        for table, method in (("Department", d.department), ("Location", d.location), ("Staff", d.staff),
                              ("Medication", d.medication)):
            known = [row["Id"] for row in rows_of(db, f"SELECT Id FROM {table}")]
            for row_id in sorted({0, *known, max(known) + 1, max(known) + 50, *range(1, max(known) + 2)}):
                assert method(row_id) == getattr(r, method.__name__)(row_id), (table, row_id)
        names = [row["Name"] for row in rows_of(db, "SELECT Name FROM Department")]
        for name in [*names, *(n.lower() for n in names), *(n.upper() for n in names), "Emerg", "no such", ""]:
            assert d.department_by_name(name) == r.department_by_name(name), name
            for except_id in (None, 1, 2, 99):
                assert d.department_name_exists(name, except_id) == r.department_name_exists(name, except_id)
        for department_id in range(0, 11):
            assert d.department_use(department_id) == r.department_use(department_id)
        for row in rows_of(db, "SELECT IdentifierSystem, IdentifierValue FROM Location"):
            for system in (row["IdentifierSystem"], ORG):
                assert d.location_by_identifier(system, row["IdentifierValue"]) == \
                       r.location_by_identifier(system, row["IdentifierValue"])
        for row in rows_of(db, "SELECT Id, IdentifierSystem, IdentifierValue FROM Staff"):
            for system in (row["IdentifierSystem"], ORG):
                assert d.staff_by_identifier(system, row["IdentifierValue"]) == \
                       r.staff_by_identifier(system, row["IdentifierValue"])
            assert d.staff_use(row["Id"]) == r.staff_use(row["Id"])
        assert d.location_by_identifier(LOC, "no-such") is None and d.staff_by_identifier(EMPLOYEE, "E9") is None
        for medication_id in range(0, 6):
            assert d.medication_in_use(medication_id) == r.medication_in_use(medication_id)
        for table, system, base in (("Department", ORG, "TRIAD-GH-EMER"), ("Department", ORG, "TRIAD-GH-NEW"),
                                    ("Location", LOC, "ER-BED-1"), ("Location", LOC, "ER-BED"),
                                    ("Staff", EMPLOYEE, "E1001")):
            assert d.unique_identifier(table, system, base) == r.unique_identifier(table, system, base)
        for table, system, prefix, width in (("Staff", EMPLOYEE, "E", 4), ("Department", ORG, "TRIAD-GH-", 3),
                                             ("Location", LOC, "ER-BED-", 1), ("Staff", "urn:none", "X", 2)):
            assert d.next_identifier(table, system, prefix, width) == r.next_identifier(table, system, prefix, width)
        # The page objects of the port (not only the API rows).
        for page in (PageRequest(limit=5, offset=0), PageRequest(limit=5, offset=20), PageRequest(limit=50, offset=0)):
            assert d.staff_list(None, None, None, page) == r.staff_list(None, None, None, page)
            assert d.staff_list("Admin", None, None, page) == r.staff_list("Admin", None, None, page)
            assert d.locations("Emergency", "bed", page) == r.locations("Emergency", "bed", page)
            assert d.departments(None, page) == r.departments(None, page)
            assert d.medications(None, page) == r.medications(None, page)
    finally:
        ctx.close()
        ref.close()


@pytest.mark.parametrize("text", INJECTIONS)
def test_a_search_text_cannot_change_the_query(store, text):
    api, h = store.client(), as_user(SOFIA)
    before = [store.probe.count(kind) for kind in ("department", "location", "staff", "medication")]
    for url in LISTS:
        response = api.get(url, headers=h, params={"q": text})
        assert response.status_code == 200 and response.json()["total"] == 0, url
    for params in ({"department": text}, {"department": text, "q": text}):
        assert api.get("/api/locations", headers=h, params=params).json()["total"] == 0
        assert api.get("/api/staff", headers=h, params=params).json()["total"] == 0
    assert [store.probe.count(kind) for kind in ("department", "location", "staff", "medication")] == before


# ---------------------------------------------------------------------------------------------
# The writes through the API

def test_create_change_and_delete_a_department(store, twin):
    api = store.client()
    dept = same(api, twin, "POST", "/api/departments", {"name": "Radiology", "phoneNumber": "+1-508-555-0190",
                                                        "address": {"street": "1 Main Street", "city": "Worcester"}})
    assert dept["identifier"] == {"system": ORG, "value": "TRIAD-GH-RADIOLOGY"} and dept["staffCount"] == 0
    other = same(api, twin, "POST", "/api/departments", {"name": "radiology!"})       # the same slug: a new value
    assert other["identifier"]["value"] == "TRIAD-GH-RADIOLOGY-2"
    given = same(api, twin, "POST", "/api/departments", {"name": "Imaging Lab", "type": "Lab", "email": "lab@x",
                                                         "identifier": {"system": "urn:test", "value": "IMG-1"}})
    assert given["identifier"] == {"system": "urn:test", "value": "IMG-1"}
    room = same(api, twin, "POST", "/api/locations", {"name": "X-ray Room 1", "department": "radiology",
                                                      "physicalType": "Room"})
    assert room["department"] == "Radiology"
    renamed = same(api, twin, "PATCH", f"/api/departments/{dept['id']}", {"name": "Imaging"})
    assert renamed["name"] == "Imaging"
    imaging = same(api, twin, "GET", "/api/locations", params={"department": "Imaging"})
    assert [x["name"] for x in imaging["items"]] == ["X-ray Room 1"]                   # the location follows
    same(api, twin, "PATCH", f"/api/departments/{dept['id']}", {"phoneNumber": None, "type": "Clinic",
                                                                "address": {"city": None, "country": "US"}})
    same(api, twin, "PATCH", f"/api/departments/{dept['id']}", {"identifier": {"system": "urn:test", "value": "IMG-2"}})
    same(api, twin, "PATCH", f"/api/departments/{dept['id']}", {"name": "imaging"})   # its own name: no conflict
    assert same(api, twin, "PATCH", f"/api/departments/{dept['id']}", {"name": "EMERGENCY"})["code"] == "conflict"
    assert same(api, twin, "PATCH", f"/api/departments/{dept['id']}", {"name": "  "})["code"] == "validation"
    assert same(api, twin, "POST", "/api/departments", {"name": "cardiology"})["code"] == "conflict"
    assert same(api, twin, "POST", "/api/departments", {"type": "No name"})["code"] == "validation"
    assert same(api, twin, "POST", "/api/departments", {"name": "X", "identifier": {"system": "s"}})["code"] == \
        "validation"
    assert same(api, twin, "POST", "/api/departments", {"name": "Nurse dept"}, user=PARK)["code"] == "forbidden"
    assert same(api, twin, "DELETE", f"/api/departments/{dept['id']}")["fields"] == {"locations": "1"}
    assert same(api, twin, "DELETE", "/api/departments/1")["fields"] == {"staffCount": "6"}
    assert same(api, twin, "DELETE", f"/api/locations/{room['id']}") is None
    assert same(api, twin, "DELETE", f"/api/departments/{dept['id']}") is None
    assert same(api, twin, "PATCH", f"/api/departments/{dept['id']}", {"name": "Gone"})["code"] == "not_found"
    assert same(api, twin, "DELETE", f"/api/departments/{dept['id']}")["code"] == "not_found"
    same_lists(api, twin)


def test_a_department_name_compares_only_the_ascii_letters_without_case(store, twin, twin_db):
    """SQLite lower() lowers only A-Z. The KG store gives the same result for a name with other letters."""
    api = store.client()
    same(api, twin, "POST", "/api/departments", {"name": "Équipe Ünit"})
    assert same(api, twin, "POST", "/api/departments", {"name": "ÉQUIPE ÜNIT"})["code"] == "conflict"
    same(api, twin, "POST", "/api/departments", {"name": "équipe ünit"})              # not the same name in SQLite
    ctx, ref = store.open_ctx(), sqlite_ctx(twin_db)
    try:
        for name in ("Équipe Ünit", "équipe ünit", "ÉQUIPE ÜNIT", "Équipe ünit", "équipe Ünit"):
            assert ctx.directory.department_by_name(name) == ref.directory.department_by_name(name), name
            assert ctx.directory.department_name_exists(name) == ref.directory.department_name_exists(name), name
    finally:
        ctx.close()
        ref.close()
    for department in ("équipe ünit", "ÉQUIPE ÜNIT"):
        same(api, twin, "POST", "/api/locations", {"name": f"Room {department}", "department": department})
        same(api, twin, "GET", "/api/locations", params={"department": department})
    same_lists(api, twin)


def test_create_change_and_delete_a_location(store, twin):
    api = store.client()
    lab = same(api, twin, "POST", "/api/locations", {
        "name": "Lab 1", "department": "CARDIOLOGY", "identifier": {"system": LOC, "value": "LAB-1"},
        "phoneNumber": "+1-508-555-0111", "physicalType": "Room",
        "address": {"street": "2 Main Street", "city": "Worcester", "region": "MA", "postalCode": "01608",
                    "country": "US"}})
    assert lab["department"] == "Cardiology" and lab["inUse"] is False
    second = same(api, twin, "POST", "/api/locations", {"name": "Lab 1", "department": "cardiology"})
    assert second["identifier"] == {"system": LOC, "value": "LAB-1-2"}
    assert same(api, twin, "POST", "/api/locations", {"name": "X", "department": "No such"})["code"] == "validation"
    assert same(api, twin, "POST", "/api/locations", {"department": "Emergency"})["code"] == "validation"
    same(api, twin, "PATCH", f"/api/locations/{lab['id']}", {"department": None, "physicalType": "Bed",
                                                             "address": {"street": None}})
    same(api, twin, "PATCH", f"/api/locations/{lab['id']}", {"name": "Lab 9",
                                                             "identifier": {"system": LOC, "value": "LAB-9"}})
    assert same(api, twin, "PATCH", f"/api/locations/{lab['id']}", {"department": "TRIAD-GH-EMER"})["code"] == \
        "validation"
    assert same(api, twin, "PATCH", f"/api/locations/{lab['id']}", {"identifier": {"system": "", "value": "x"}})[
        "code"] == "validation"
    assert same(api, twin, "PATCH", "/api/locations/999", {"name": "None"})["code"] == "not_found"
    used = rows_of(store.db_path, "SELECT LocationId FROM VisitLocation ORDER BY Id LIMIT 1")[0]["LocationId"]
    assert same(api, twin, "DELETE", f"/api/locations/{used}")["code"] == "conflict"     # a visit used it
    assert same(api, twin, "DELETE", f"/api/locations/{lab['id']}") is None
    assert same(api, twin, "DELETE", f"/api/locations/{lab['id']}")["code"] == "not_found"
    same_lists(api, twin)


ROLE_FIELDS = [
    ("Doctor", {"licenseNumber": "MD-1", "qualification": "MD"}, {"qualification": "PhD", "licenseNumber": None}),
    ("Nurse", {"designation": "NP", "licenseNumber": "RN-1"}, {"designation": "LPN"}),
    ("Nurse", {}, {"licenseNumber": "RN-2"}),
    ("MOA", {"desk": "Desk 9", "certificationNumber": "C-1", "phoneExtension": "201"},
     {"desk": "Desk 2", "phoneExtension": None}),
    ("MOA", {}, {"certificationNumber": "C-2"}),
]


@pytest.mark.parametrize("role, extra, change", ROLE_FIELDS)
def test_create_and_change_a_staff_member(store, twin, role, extra, change):
    api = store.client()
    staff = same(api, twin, "POST", "/api/staff", {
        "name": "Test Person", "role": role, "departmentId": 7, "sex": "other", "email": "t@x", "phoneNumber": "1",
        "languages": ["fr", "en", " de ", "en", ""], "roleCode": "locum", "specialty": "Testing", **extra})
    assert staff["key"] == f"{role}:E1026" and staff["languages"] == ["de", "en", "fr"]
    assert staff["departments"] == [{"departmentId": 7, "name": "Cardiology", "roleCode": "locum",
                                     "specialty": "Testing"}]
    second = same(api, twin, "POST", "/api/staff", {"name": "Second Person", "role": role, "departmentId": 1})
    assert second["key"] == f"{role}:E1027" and second["languages"] == [] and second["active"] is True
    same(api, twin, "PATCH", f"/api/staff/{staff['id']}", {"active": False, "languages": ["ko"], "email": None})
    same(api, twin, "PATCH", f"/api/staff/{staff['id']}", change)
    same(api, twin, "PATCH", f"/api/staff/{staff['id']}", {"languages": []})
    same(api, twin, "PATCH", f"/api/staff/{staff['id']}", {"sex": "male", "name": "Not changed"})  # not a PATCH field
    other_role = {"Doctor": {"desk": "D"}, "Nurse": {"qualification": "Q"}, "MOA": {"designation": "RN"}}[role]
    assert same(api, twin, "PATCH", f"/api/staff/{staff['id']}", other_role)["code"] == "validation"
    if role == "Nurse":
        assert same(api, twin, "PATCH", f"/api/staff/{staff['id']}", {"designation": "XX"})["code"] == "validation"
    assert same(api, twin, "DELETE", f"/api/staff/{staff['id']}")["code"] == "conflict"   # works in a department
    same(api, twin, "GET", "/api/staff", params={"q": "person", "role": role})
    same_lists(api, twin)


def test_the_staff_errors_are_the_same_on_each_store(store, twin):
    api = store.client()
    for body in ({"name": "X", "role": "Nurse", "departmentId": 999}, {"name": "", "role": "Nurse", "departmentId": 1},
                 {"name": "X", "role": "Admin", "departmentId": 1}, {"name": "X", "role": "Nurse", "departmentId": 1,
                                                                     "sex": "robot"},
                 {"name": "X", "role": "MOA", "departmentId": 1, "designation": "RN"},
                 {"name": "X", "role": "Nurse", "departmentId": 1, "designation": "XX"},
                 {"name": "X", "role": "Doctor", "departmentId": 1,
                  "identifier": {"system": EMPLOYEE, "value": "E1002"}},
                 {"name": "X", "role": "Doctor", "departmentId": 1, "identifier": {"value": "E1"}}):
        response = same(api, twin, "POST", "/api/staff", body)
        assert response["code"] in ("validation", "conflict"), body
    assert same(api, twin, "PATCH", "/api/staff/999", {"email": "x"})["code"] == "not_found"
    assert same(api, twin, "DELETE", "/api/staff/999")["code"] == "not_found"
    assert same(api, twin, "DELETE", "/api/staff/5")["code"] == "conflict"               # Okafor issued messages
    assert same(api, twin, "GET", "/api/staff", params={"role": "Admin"})["code"] == "validation"
    same_lists(api, twin)


def remove_works_in(handle_ctx, is_kg: bool, staff_id: int, works: list[int]) -> None:
    """Remove the WorksIn rows of a staff member (no port method does this; the test needs a free staff member)."""
    with handle_ctx.uow.write():
        if is_kg:
            for w in works:
                handle_ctx.directory.session.write_buffer().delete_subject("works-in", w)
        else:
            handle_ctx.directory.conn.execute("DELETE FROM WorksIn WHERE StaffId = ?", (staff_id,))


def test_delete_a_staff_member_with_no_department(store, twin, twin_db):
    """The delete removes the individual: its two types, its subtype values and its languages (SQLite: the
    StaffLanguage, the subtype and the Staff rows)."""
    api = store.client()
    staff = same(api, twin, "POST", "/api/staff", {"name": "Leaving Person", "role": "Doctor", "departmentId": 3,
                                                   "languages": ["en", "es"], "qualification": "MD"})
    works = [row["id"] for row in store.probe.rows("works-in", ofStaff=staff["id"])]
    assert len(works) == 1
    ctx, ref = store.open_ctx(), sqlite_ctx(twin_db)
    try:
        remove_works_in(ctx, store.is_kg, staff["id"], works)
        remove_works_in(ref, False, staff["id"], works)
    finally:
        ctx.close()
        ref.close()
    assert same(api, twin, "DELETE", f"/api/staff/{staff['id']}") is None
    assert store.probe.row("staff", staff["id"]) is None
    if store.is_kg:                                    # no triple names the individual
        client = store.open_ctx().directory.session.client
        assert not client.ask("ASK FROM $abox WHERE { { $s ?p ?o } UNION { ?x ?q $s } }",
                              {"s": kg_term("staff", staff["id"])})
    same_lists(api, twin)


def test_create_change_and_delete_a_medication(store, twin):
    api = store.client()
    med = same(api, twin, "POST", "/api/medications", {"code": "T-1", "codeSystem": "urn:test", "name": "Test",
                                                       "form": "Tablet", "manufacturer": "ACME"})
    again = same(api, twin, "POST", "/api/medications", {"code": "T-1", "codeSystem": "urn:test", "name": "Again"})
    assert again == {"code": "conflict", "message": "A row with the same key exists already.",
                     "fields": {"key": "Medication.Code, Medication.CodeSystem"}}
    other = same(api, twin, "POST", "/api/medications", {"code": "T-1", "codeSystem": "urn:other", "name": "Other"})
    assert same(api, twin, "PATCH", f"/api/medications/{other['id']}", {"codeSystem": "urn:test"})["fields"] == \
        {"key": "Medication.Code, Medication.CodeSystem"}                               # a replace is checked too
    same(api, twin, "PATCH", f"/api/medications/{other['id']}", {"codeSystem": "urn:other", "code": "T-1"})
    same(api, twin, "PATCH", f"/api/medications/{med['id']}", {"form": None, "name": "Test 2"})
    assert same(api, twin, "PATCH", f"/api/medications/{med['id']}", {"code": ""})["code"] == "validation"
    assert same(api, twin, "POST", "/api/medications", {"name": "No code"})["code"] == "validation"
    assert same(api, twin, "DELETE", "/api/medications/1")["code"] == "conflict"         # a prescription uses it
    assert same(api, twin, "DELETE", f"/api/medications/{med['id']}") is None
    assert same(api, twin, "DELETE", f"/api/medications/{med['id']}")["code"] == "not_found"
    same(api, twin, "GET", "/api/medications", params={"q": "t-1"})
    same_lists(api, twin)


def test_a_duplicate_identifier_is_a_conflict_on_each_store(store, twin):
    """The client-given identifiers: only the database enforces their key today (test_api.py), so the KG has a
    guard (key.identifier)."""
    api = store.client()
    pair = "SELECT IdentifierSystem AS s, IdentifierValue AS v FROM {} WHERE Id = 1"
    emergency = rows_of(store.db_path, pair.format("Department"))[0]
    unit = rows_of(store.db_path, pair.format("Location"))[0]
    key = {"system": emergency["s"], "value": emergency["v"]}
    assert same(api, twin, "POST", "/api/departments", {"name": "Dup", "identifier": key})["fields"] == \
        {"key": "Department.IdentifierSystem, Department.IdentifierValue"}
    assert same(api, twin, "PATCH", "/api/departments/2", {"identifier": key})["code"] == "conflict"
    same(api, twin, "PATCH", "/api/departments/1", {"identifier": key})                 # its own identifier
    same(api, twin, "POST", "/api/departments", {"name": "Other system",
                                                 "identifier": {"system": "urn:other", "value": emergency["v"]}})
    unit_key = {"system": unit["s"], "value": unit["v"]}
    assert same(api, twin, "POST", "/api/locations", {"name": "Dup", "identifier": unit_key})["fields"] == \
        {"key": "Location.IdentifierSystem, Location.IdentifierValue"}
    assert same(api, twin, "PATCH", "/api/locations/2", {"identifier": unit_key})["code"] == "conflict"
    same(api, twin, "POST", "/api/locations", {"name": "Same value, a department identifier",
                                               "identifier": {"system": emergency["s"], "value": emergency["v"]}})
    assert same(api, twin, "POST", "/api/staff", {"name": "Dup", "role": "Nurse", "departmentId": 1,
                                                  "identifier": {"system": EMPLOYEE, "value": "E1002"}})["fields"] == \
        {"key": "Staff.IdentifierSystem, Staff.IdentifierValue"}
    same_lists(api, twin)


# ---------------------------------------------------------------------------------------------
# The port: the rules of the database (NOT NULL, CHECK, UNIQUE, FOREIGN KEY) on both stores

def both_errors(store, twin_db, step: Callable[[Any], Any]) -> tuple:
    """The error of the same port write on the store and on the SQLite twin. They must be the same."""
    ctx, ref = store.open_ctx(), sqlite_ctx(twin_db)
    try:
        found = error_of(write(ctx, lambda: step(ctx.directory))), error_of(write(ref, lambda: step(ref.directory)))
    finally:
        ctx.close()
        ref.close()
    assert found[0] == found[1]
    return found[0]


STAFF_ROW = {"IdentifierSystem": EMPLOYEE, "IdentifierValue": "E7777", "Name": "Port Person", "Role": "Nurse",
             "subtype": {"Designation": "RN"}, "department_id": 1, "role_code": "nurse"}
PORT_ERRORS = [
    ("department with no name", lambda d: d.add_department({"IdentifierSystem": ORG, "IdentifierValue": "X"}),
     "NOT NULL constraint failed: Department.Name"),
    ("department with no identifier value", lambda d: d.add_department({"IdentifierSystem": ORG, "Name": "X"}),
     "NOT NULL constraint failed: Department.IdentifierValue"),
    ("a department name of None", lambda d: d.update_department(2, {"Name": None}),
     "NOT NULL constraint failed: Department.Name"),
    ("location with no name", lambda d: d.add_location({"IdentifierSystem": LOC, "IdentifierValue": "X"}),
     "NOT NULL constraint failed: Location.Name"),
    ("staff sex", lambda d: d.add_staff({**STAFF_ROW, "Sex": "robot"}),
     "CHECK constraint failed: Sex IN ('female', 'male', 'other', 'unknown')"),
    ("staff active", lambda d: d.add_staff({**STAFF_ROW, "Active": 2}), "CHECK constraint failed: Active IN (0, 1)"),
    ("staff role", lambda d: d.add_staff({**STAFF_ROW, "Role": "Admin"}),
     "CHECK constraint failed: Role IN ('Doctor', 'Nurse', 'MOA')"),
    ("staff with no role", lambda d: d.add_staff({**STAFF_ROW, "Role": None}),
     "NOT NULL constraint failed: Staff.Role"),
    ("NOT NULL before CHECK", lambda d: d.add_staff({**STAFF_ROW, "Name": None, "Sex": "robot"}),
     "NOT NULL constraint failed: Staff.Name"),
    ("nurse with no designation", lambda d: d.add_staff({**STAFF_ROW, "subtype": {}}),
     "NOT NULL constraint failed: Nurse.Designation"),
    ("nurse designation", lambda d: d.add_staff({**STAFF_ROW, "subtype": {"Designation": "XX"}}),
     "CHECK constraint failed: Designation IN ('RN', 'LPN', 'RPN', 'NP')"),
    ("moa with no desk", lambda d: d.add_staff({**STAFF_ROW, "Role": "MOA", "subtype": {"Designation": "RN"}}),
     "NOT NULL constraint failed: MOA.Desk"),
    ("works-in with no department", lambda d: d.add_staff({**STAFF_ROW, "department_id": None}),
     "NOT NULL constraint failed: WorksIn.DepartmentId"),
    ("works-in with no role code", lambda d: d.add_staff({**STAFF_ROW, "role_code": None}),
     "NOT NULL constraint failed: WorksIn.RoleCode"),
    ("a language of None", lambda d: d.add_staff({**STAFF_ROW, "languages": ["en", None]}),
     "NOT NULL constraint failed: StaffLanguage.Language"),
    ("a changed sex", lambda d: d.update_staff(2, {"Sex": "robot"}),
     "CHECK constraint failed: Sex IN ('female', 'male', 'other', 'unknown')"),
    ("a changed active", lambda d: d.update_staff(2, {"Active": None}), "NOT NULL constraint failed: Staff.Active"),
    ("a changed designation", lambda d: d.update_staff(2, {"subtype": {"Designation": "XX"}}),
     "CHECK constraint failed: Designation IN ('RN', 'LPN', 'RPN', 'NP')"),
    ("a changed language of None", lambda d: d.update_staff(2, {"languages": [None]}),
     "NOT NULL constraint failed: StaffLanguage.Language"),
    ("medication with no name", lambda d: d.add_medication({"Code": "C", "CodeSystem": "S"}),
     "NOT NULL constraint failed: Medication.Name"),
    ("a medication code of None", lambda d: d.update_medication(1, {"Code": None}),
     "NOT NULL constraint failed: Medication.Code"),
]


@pytest.mark.parametrize("name, step, text", PORT_ERRORS, ids=[case[0] for case in PORT_ERRORS])
def test_the_not_null_and_check_rules_of_the_port(store, twin_db, name, step, text):
    assert both_errors(store, twin_db, step) == ("Invalid", "The input is not correct.", {"database": text})


IN_USE_DELETES = [("department", lambda d: d.delete_department(1)), ("location", lambda d: d.delete_location(8)),
                  ("staff", lambda d: d.delete_staff(1)), ("medication", lambda d: d.delete_medication(1))]


@pytest.mark.parametrize("kind, step", IN_USE_DELETES, ids=[case[0] for case in IN_USE_DELETES])
def test_a_delete_of_a_row_in_use_is_a_conflict_on_each_store(store, twin_db, kind, step):
    """SQLite: FOREIGN KEY (RESTRICT). The KG: the guard "foreign-keys". The use cases check first (the API)."""
    before = store.probe.rows(kind)
    assert both_errors(store, twin_db, step) == \
        ("Conflict", "The row is in use, or it points to a row that does not exist.", None)
    assert store.probe.rows(kind) == before


def test_a_staff_member_needs_a_department_that_exists(store, twin_db):
    assert both_errors(store, twin_db, lambda d: d.add_staff({**STAFF_ROW, "department_id": 999})) == \
        ("Conflict", "The row is in use, or it points to a row that does not exist.", None)


def test_a_staff_member_has_each_language_one_time(store, twin_db):
    key = ("Conflict", "A row with the same key exists already.",
           {"key": "StaffLanguage.StaffId, StaffLanguage.Language"})
    assert both_errors(store, twin_db, lambda d: d.add_staff({**STAFF_ROW, "languages": ["en", "fr", "en"]})) == key
    assert both_errors(store, twin_db, lambda d: d.update_staff(1, {"languages": ["en", "en"]})) == key


def test_the_port_writes_give_the_same_rows(store, twin_db):
    """The direct writes of the port: a rename in the same write as a new location, an empty change, a new staff
    member with no languages, and the default of Active."""
    ctx, ref = store.open_ctx(), sqlite_ctx(twin_db)
    try:
        for c in (ctx, ref):
            with c.uow.write():
                location = c.directory.add_location({"IdentifierSystem": LOC, "IdentifierValue": "P-1",
                                                     "Name": "Port Room", "Type": "Cardiology"})
                c.directory.update_department(7, {"Name": "Heart Care"})
                c.directory.update_location(location, {})
                c.directory.update_medication(1, {})
                staff = c.directory.add_staff({**STAFF_ROW, "Role": "Doctor", "subtype": {}})
                c.directory.update_staff(staff, {"subtype": {"Qualification": "MD", "Desk": "ignored"}})
                c.directory.update_department(8, {"Name": "Front Office"})          # the same name: no change
        assert ctx.directory.location(location) == ref.directory.location(location)
        assert ctx.directory.staff(staff) == ref.directory.staff(staff)
        page = PageRequest(limit=200, offset=0)
        assert ctx.directory.locations(None, None, page) == ref.directory.locations(None, None, page)
        assert ctx.directory.departments(None, page) == ref.directory.departments(None, page)
        assert ctx.directory.department_use(7) == ref.directory.department_use(7)
        assert ctx.directory.staff(staff).active is True
    finally:
        ctx.close()
        ref.close()


# ---------------------------------------------------------------------------------------------
# The key guards of all kinds (the UNIQUE constraints): the same error as SQLite for a copy of a stored key

def kg_term(kind: str, row_id: int):
    from infrastructure.sparql.terms import iri
    return iri(kind, row_id)


def care_team_entry(db: Path, care_team_id: int) -> int:
    return rows_of(db, "SELECT ClinicalEntryId FROM CareTeam WHERE Id = ?", (care_team_id,))[0]["ClinicalEntryId"]


KEY_CASES = {
    # name: (source row SQL, SQLite statement, the KG write, the key)
    "department": ("SELECT * FROM Department ORDER BY Id LIMIT 1",
                   lambda r: ("INSERT INTO Department (IdentifierSystem, IdentifierValue, Name) VALUES (?, ?, 'Copy')",
                              (r["IdentifierSystem"], r["IdentifierValue"])),
                   lambda buf, r, db: buf.create("department", {
                       "identifierSystem": r["IdentifierSystem"], "identifierValue": r["IdentifierValue"],
                       "name": "Copy"}),
                   "Department.IdentifierSystem, Department.IdentifierValue"),
    "location": ("SELECT * FROM Location ORDER BY Id DESC LIMIT 1",
                 lambda r: ("INSERT INTO Location (IdentifierSystem, IdentifierValue, Name) VALUES (?, ?, 'Copy')",
                            (r["IdentifierSystem"], r["IdentifierValue"])),
                 lambda buf, r, db: buf.create("location", {"identifierSystem": r["IdentifierSystem"],
                                                            "identifierValue": r["IdentifierValue"], "name": "Copy"}),
                 "Location.IdentifierSystem, Location.IdentifierValue"),
    "visit": ("SELECT * FROM Visit ORDER BY Id LIMIT 1",
              lambda r: ("INSERT INTO Visit (IdentifierSystem, IdentifierValue, PatientId, Class, StartDate) "
                         "VALUES (?, ?, ?, 'AMB', ?)", (r["IdentifierSystem"], r["IdentifierValue"], r["PatientId"],
                                                        r["StartDate"])),
              lambda buf, r, db: buf.add(kg_term("patient", r["PatientId"]), {"hasVisit": kg_term("visit", buf.create(
                  "visit", {"identifierSystem": r["IdentifierSystem"], "identifierValue": r["IdentifierValue"],
                            "visitClass": "AMB", "startDate": r["StartDate"]}))}),
              "Visit.IdentifierSystem, Visit.IdentifierValue"),
    "clinical-entry": ("SELECT * FROM ClinicalEntry ORDER BY Id LIMIT 1",
                       lambda r: ("INSERT INTO ClinicalEntry (IdentifierSystem, IdentifierValue, VisitId, Category, "
                                  "Code, CodeSystem, Display, RecordedAt) VALUES (?, ?, ?, ?, 'X', 'X', 'X', ?)",
                                  (r["IdentifierSystem"], r["IdentifierValue"], r["VisitId"], r["Category"],
                                   r["RecordedAt"])),
                       lambda buf, r, db: buf.create("clinical-entry", {
                           "identifierSystem": r["IdentifierSystem"], "identifierValue": r["IdentifierValue"],
                           "during": kg_term("visit", r["VisitId"]), "code": "X", "codeSystem": "X", "display": "X",
                           "recordedAt": r["RecordedAt"]}, types=(r["Category"],)),
                       "ClinicalEntry.IdentifierSystem, ClinicalEntry.IdentifierValue"),
    "message": ("SELECT * FROM Message WHERE StaffId IS NOT NULL ORDER BY Id LIMIT 1",
                lambda r: ("INSERT INTO Message (IdentifierSystem, IdentifierValue, StaffId, Channel, Origin, SentAt, "
                           "Text) VALUES (?, ?, ?, ?, ?, ?, 'Copy')",
                           (r["IdentifierSystem"], r["IdentifierValue"], r["StaffId"], r["Channel"], r["Origin"],
                            r["SentAt"])),
                lambda buf, r, db: buf.add(kg_term("staff", r["StaffId"]), {"issues": kg_term("message", buf.create(
                    "message", {"identifierSystem": r["IdentifierSystem"], "identifierValue": r["IdentifierValue"],
                                "channel": r["Channel"], "origin": r["Origin"], "sentAt": r["SentAt"],
                                "text": "Copy"}))}),
                "Message.IdentifierSystem, Message.IdentifierValue"),
    "chat-session": ("SELECT * FROM ChatSession ORDER BY Id LIMIT 1",
                     lambda r: ("INSERT INTO ChatSession (IdentifierSystem, IdentifierValue, UserRole, UserSystem, "
                                "UserValue, SubjectName, SubjectDateOfBirth, StartedAt, Mode) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                tuple(r[c] for c in ("IdentifierSystem", "IdentifierValue", "UserRole", "UserSystem",
                                                     "UserValue", "SubjectName", "SubjectDateOfBirth", "StartedAt",
                                                     "Mode"))),
                     lambda buf, r, db: buf.create("chat-session", {
                         "identifierSystem": r["IdentifierSystem"], "identifierValue": r["IdentifierValue"],
                         "userRole": r["UserRole"], "userSystem": r["UserSystem"], "userValue": r["UserValue"],
                         "subjectName": r["SubjectName"], "subjectDateOfBirth": r["SubjectDateOfBirth"],
                         "startedAt": r["StartedAt"], "mode": r["Mode"]}),
                     "ChatSession.IdentifierSystem, ChatSession.IdentifierValue"),
    "audit-event": ("SELECT * FROM AuditEvent WHERE ChatTurnId IS NULL ORDER BY Id LIMIT 1",
                    lambda r: ("INSERT INTO AuditEvent (IdentifierSystem, IdentifierValue, At, Action, Outcome, "
                               "ActorRole, ActorSystem, ActorValue, SubjectName, SubjectDateOfBirth, Path) "
                               "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               tuple(r[c] for c in ("IdentifierSystem", "IdentifierValue", "At", "Action", "Outcome",
                                                    "ActorRole", "ActorSystem", "ActorValue", "SubjectName",
                                                    "SubjectDateOfBirth", "Path"))),
                    lambda buf, r, db: buf.create("audit-event", {
                        "identifierSystem": r["IdentifierSystem"], "identifierValue": r["IdentifierValue"],
                        "at": r["At"], "action": r["Action"], "auditOutcome": r["Outcome"],
                        "actorRole": r["ActorRole"], "actorSystem": r["ActorSystem"], "actorValue": r["ActorValue"],
                        "subjectName": r["SubjectName"], "subjectDateOfBirth": r["SubjectDateOfBirth"],
                        "path": r["Path"]}),
                    "AuditEvent.IdentifierSystem, AuditEvent.IdentifierValue"),
    "patient-identifier": ("SELECT * FROM PatientIdentifier ORDER BY Id LIMIT 1",
                           lambda r: ("INSERT INTO PatientIdentifier (PatientId, System, Value) VALUES (?, ?, ?)",
                                      (r["PatientId"], r["System"], r["Value"])),
                           lambda buf, r, db: buf.add(kg_term("patient", r["PatientId"]), {
                               "identifier": kg_term("patient-identifier", buf.create("patient-identifier", {
                                   "identifierSystem": r["System"], "identifierValue": r["Value"]}))}),
                           "PatientIdentifier.System, PatientIdentifier.Value"),
    "patient": ("SELECT * FROM Patient ORDER BY Id LIMIT 1",
                lambda r: ("INSERT INTO Patient (Name, DateOfBirth, Sex) VALUES (?, ?, ?)",
                           (r["Name"], r["DateOfBirth"], r["Sex"])),
                lambda buf, r, db: buf.create("patient", {"name": r["Name"], "dateOfBirth": r["DateOfBirth"],
                                                          "patientSex": r["Sex"]}),
                "Patient.Name, Patient.DateOfBirth"),
    "medication": ("SELECT * FROM Medication ORDER BY Id LIMIT 1",
                   lambda r: ("INSERT INTO Medication (Code, CodeSystem, Name) VALUES (?, ?, 'Copy')",
                              (r["Code"], r["CodeSystem"])),
                   lambda buf, r, db: buf.create("medication", {"code": r["Code"], "codeSystem": r["CodeSystem"],
                                                                "name": "Copy"}),
                   "Medication.Code, Medication.CodeSystem"),
    "works-in": ("SELECT * FROM WorksIn ORDER BY Id LIMIT 1",
                 lambda r: ("INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode) VALUES (?, ?, ?)",
                            (r["StaffId"], r["DepartmentId"], r["RoleCode"])),
                 lambda buf, r, db: buf.create("works-in", {"ofStaff": kg_term("staff", r["StaffId"]),
                                                            "atDepartment": kg_term("department", r["DepartmentId"]),
                                                            "roleCode": r["RoleCode"]}),
                 "WorksIn.StaffId, WorksIn.DepartmentId, WorksIn.RoleCode"),
    "visit-location": ("SELECT * FROM VisitLocation ORDER BY Id LIMIT 1",
                       lambda r: ("INSERT INTO VisitLocation (VisitId, LocationId, StartDate) VALUES (?, ?, ?)",
                                  (r["VisitId"], r["LocationId"], r["StartDate"])),
                       lambda buf, r, db: buf.create("visit-location", {
                           "ofVisit": kg_term("visit", r["VisitId"]),
                           "atLocation": kg_term("location", r["LocationId"]), "startDate": r["StartDate"]}),
                       "VisitLocation.VisitId, VisitLocation.LocationId, VisitLocation.StartDate"),
    "citation": ("SELECT * FROM Citation ORDER BY Id LIMIT 1",
                 lambda r: ("INSERT INTO Citation (ChatTurnId, AssertionId, Rank) VALUES (?, ?, 9)",
                            (r["ChatTurnId"], r["AssertionId"])),
                 lambda buf, r, db: buf.create("citation", {"byTurn": kg_term("chat-turn", r["ChatTurnId"]),
                                                            "citedAssertion": kg_term("assertion", r["AssertionId"]),
                                                            "rank": 9}),
                 "Citation.ChatTurnId, Citation.AssertionId"),
    "care-team-member": ("SELECT * FROM CareTeamMember ORDER BY Id LIMIT 1",
                         lambda r: ("INSERT INTO CareTeamMember (CareTeamId, MemberSystem, MemberValue) "
                                    "VALUES (?, ?, ?)", (r["CareTeamId"], r["MemberSystem"], r["MemberValue"])),
                         lambda buf, r, db: buf.add(kg_term("clinical-entry", care_team_entry(db, r["CareTeamId"])), {
                             "member": kg_term("care-team-member", buf.create("care-team-member", {
                                 "memberSystem": r["MemberSystem"], "memberValue": r["MemberValue"]}))}),
                         "CareTeamMember.CareTeamId, CareTeamMember.MemberSystem, CareTeamMember.MemberValue"),
    "chat-turn seq": ("SELECT * FROM ChatTurn ORDER BY Id LIMIT 1",
                      lambda r: ("INSERT INTO ChatTurn (ChatSessionId, Seq, ClientTurnId, Speaker, Text, CreatedAt) "
                                 "VALUES (?, ?, 'new-turn', ?, 'Copy', ?)",
                                 (r["ChatSessionId"], r["Seq"], r["Speaker"], r["CreatedAt"])),
                      lambda buf, r, db: buf.add(kg_term("chat-session", r["ChatSessionId"]), {
                          "includes": kg_term("chat-turn", buf.create("chat-turn", {
                              "seq": r["Seq"], "clientTurnId": "new-turn", "speaker": r["Speaker"], "text": "Copy",
                              "createdAt": r["CreatedAt"]}))}),
                      "ChatTurn.ChatSessionId, ChatTurn.Seq"),
    "chat-turn client id": ("SELECT * FROM ChatTurn ORDER BY Id LIMIT 1",
                            lambda r: ("INSERT INTO ChatTurn (ChatSessionId, Seq, ClientTurnId, Speaker, Text, "
                                       "CreatedAt) VALUES (?, 999, ?, ?, 'Copy', ?)",
                                       (r["ChatSessionId"], r["ClientTurnId"], r["Speaker"], r["CreatedAt"])),
                            lambda buf, r, db: buf.add(kg_term("chat-session", r["ChatSessionId"]), {
                                "includes": kg_term("chat-turn", buf.create("chat-turn", {
                                    "seq": 999, "clientTurnId": r["ClientTurnId"], "speaker": r["Speaker"],
                                    "text": "Copy", "createdAt": r["CreatedAt"]}))}),
                            "ChatTurn.ChatSessionId, ChatTurn.ClientTurnId"),
    # A new assertion with the (message, seq) of the current head of an entry, that supersedes that head: the
    # triggers accept it, and the key (MessageId, Seq) stops it.
    "assertion message seq": ("SELECT a.* FROM Assertion a WHERE NOT EXISTS (SELECT 1 FROM Assertion n "
                              "WHERE n.SupersedesId = a.Id) ORDER BY a.Id LIMIT 1",
                              lambda r: ("INSERT INTO Assertion (MessageId, Seq, ClinicalEntryId, SupersedesId, "
                                         "AssertedAt, Intent, Source, Verification, Statement) "
                                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Copy')",
                                         (r["MessageId"], r["Seq"], r["ClinicalEntryId"], r["Id"], r["AssertedAt"],
                                          r["Intent"], r["Source"], r["Verification"])),
                              lambda buf, r, db: buf.add(kg_term("message", r["MessageId"]), {
                                  "contains": kg_term("assertion", buf.create("assertion", {
                                      "seq": r["Seq"], "about": kg_term("clinical-entry", r["ClinicalEntryId"]),
                                      "supersedes": kg_term("assertion", r["Id"]), "assertedAt": r["AssertedAt"],
                                      "intent": r["Intent"], "source": r["Source"],
                                      "verification": r["Verification"], "statement": "Copy"}))}),
                              "Assertion.MessageId, Assertion.Seq"),
    "staff language": ("SELECT * FROM StaffLanguage ORDER BY Id LIMIT 1",
                       lambda r: ("INSERT INTO StaffLanguage (StaffId, Language) VALUES (?, ?)",
                                  (r["StaffId"], r["Language"])),
                       lambda buf, r, db: buf.add(kg_term("staff", r["StaffId"]), {"language": r["Language"]}),
                       "StaffLanguage.StaffId, StaffLanguage.Language"),
}


def key_case_errors(handle, twin_db: Path, name: str) -> Optional[tuple]:
    """The error of the copy of a stored key on the store and on the SQLite twin (None: the data has no row)."""
    source, statement, kg_write, key = KEY_CASES[name]
    found = rows_of(twin_db, source)
    if not found:
        return None
    row = found[0]
    ctx, ref = handle.open_ctx(), sqlite_ctx(twin_db)
    try:
        def on_kg():
            kg_write(ctx.directory.session.write_buffer(), row, twin_db)

        def on_sqlite(c):
            return lambda: c.directory.conn.execute(*statement(row))
        mine = error_of(write(ctx, on_kg if handle.is_kg else on_sqlite(ctx)))
        expected = error_of(write(ref, on_sqlite(ref)))
    finally:
        ctx.close()
        ref.close()
    assert expected == ("Conflict", "A row with the same key exists already.", {"key": key}), name
    assert mine == expected, name
    return mine


@pytest.mark.parametrize("name", list(KEY_CASES))
def test_each_key_guard_gives_the_error_of_sqlite(store, twin_db, name):
    before = store.probe.count("department"), store.probe.count("assertion"), store.probe.count("chat-turn")
    assert key_case_errors(store, twin_db, name) is not None
    assert (store.probe.count("department"), store.probe.count("assertion"), store.probe.count("chat-turn")) == before


@pytest.mark.stores("oxigraph", "virtuoso")
def test_the_key_guards_alone(store):
    """The cases that SQLite never reports as a key error (a trigger or the use case stops them first), and the
    keys inside one change: the guard functions on a change that the test makes."""
    from domain.errors import Conflict
    from infrastructure.sparql import guards_directory as G
    from infrastructure.sparql.change import Added, Change, NewSubject, Replacement
    from infrastructure.sparql.guards import Facts
    from infrastructure.sparql.terms import iri
    facts = Facts(store.open_ctx().directory.session.client)

    def new(kind, number, values, types=()):
        return NewSubject(kind, number, iri(kind, number), types, {k: list(v) if isinstance(v, list) else [v]
                                                                   for k, v in values.items()})

    def key_of(check, change):
        with pytest.raises(Conflict) as error:
            check(change, facts)
        return error.value.fields["key"]

    # One new assertion for each old one (UK_Assertion_SupersedesId): assertion 1 has a newer assertion.
    superseded = store.probe.rows("assertion")[0]["id"]
    older = [r for r in store.probe.rows("assertion") if r["supersedes"] == superseded]
    assert older
    change = Change([new("assertion", 900, {"supersedes": iri("assertion", superseded), "seq": 99})],
                    [Added(iri("message", 1), "contains", iri("assertion", 900))], [], [])
    assert key_of(G.assertion_keys, change) == "Assertion.SupersedesId"
    # Two new rows of one change with the same key.
    twins = Change([new("medication", 900, {"code": "Z", "codeSystem": "S"}),
                    new("medication", 901, {"code": "Z", "codeSystem": "S"})], [], [], [])
    assert key_of(G.medication_key, twins) == "Medication.Code, Medication.CodeSystem"
    twins = Change([new("department", 900, {"identifierSystem": "S", "identifierValue": "V"}),
                    new("department", 901, {"identifierSystem": "S", "identifierValue": "V"})], [], [], [])
    assert key_of(G.identifier_key, twins) == "Department.IdentifierSystem, Department.IdentifierValue"
    # The same identifier for two kinds is not a duplicate; a stored row that the change deletes is not either.
    G.identifier_key(Change([new("department", 900, {"identifierSystem": "S", "identifierValue": "V"}),
                             new("location", 900, {"identifierSystem": "S", "identifierValue": "V"})], [], [], []),
                     facts)
    medication = store.probe.rows("medication")[0]
    from infrastructure.sparql.change import Deletion
    G.medication_key(Change([new("medication", 900, {"code": medication["code"],
                                                     "codeSystem": medication["codeSystem"]})], [], [],
                            [Deletion("medication", medication["id"], iri("medication", medication["id"]))]), facts)
    # A replace of a key value of a stored row: the value after the change counts.
    G.medication_key(Change([], [], [Replacement(iri("medication", medication["id"]), "name", ("X",))], []), facts)
    G.medication_key(Change([], [], [Replacement(iri("medication", 999), "code", ("Z",))], []), facts)  # no row
    # A time key compares the instant text of the store: the trailing zeros of the seconds do not count.
    vl = store.probe.rows("visit-location")[0]
    start = vl["startDate"]
    with_zeros = start[:19] + ".000" + start[19:] if "." not in start else start + "0"
    change = Change([new("visit-location", 900, {"ofVisit": iri("visit", vl["ofVisit"]),
                                                 "atLocation": iri("location", vl["atLocation"]),
                                                 "startDate": with_zeros})], [], [], [])
    assert key_of(G.association_keys, change) == \
        "VisitLocation.VisitId, VisitLocation.LocationId, VisitLocation.StartDate"
    # A language that a change adds two times, and a language that a replace and an add give together.
    staff = iri("staff", 2)
    assert key_of(G.association_keys, Change([], [Added(staff, "language", "xx"), Added(staff, "language", "xx")],
                                             [], [])) == "StaffLanguage.StaffId, StaffLanguage.Language"
    assert key_of(G.association_keys, Change([], [Added(staff, "language", "xx")],
                                             [Replacement(staff, "language", ("xx",))], [])) == \
        "StaffLanguage.StaffId, StaffLanguage.Language"
    G.association_keys(Change([], [Added(staff, "language", "en")], [Replacement(staff, "language", ("fr",))], []),
                       facts)
    # A chat turn of a new session: no stored turns to read.
    G.chat_turn_keys(Change([new("chat-session", 900, {"includes": iri("chat-turn", 900)}),
                             new("chat-turn", 900, {"seq": 1, "clientTurnId": "a"})], [], [], []), facts)
    assert key_of(G.chat_turn_keys, Change([new("chat-session", 900, {"includes": [iri("chat-turn", 900),
                                                                                    iri("chat-turn", 901)]}),
                                            new("chat-turn", 900, {"seq": 1, "clientTurnId": "a"}),
                                            new("chat-turn", 901, {"seq": 2, "clientTurnId": "a"})], [], [], [])) == \
        "ChatTurn.ChatSessionId, ChatTurn.ClientTurnId"


# ---------------------------------------------------------------------------------------------
# The full data: each new query once, with the times (plan 5.6; README.md, rule 4)

def test_the_directory_on_the_full_data(full_store, tmp_path, capsys):
    api, h = full_store.client(), as_user(SOFIA)
    twin_db = copy_db(full_store, tmp_path)
    twin = make_client(twin_db)
    times: dict[str, float] = {}

    def timed(name: str, call: Callable[[], Any]) -> Any:
        start = time.perf_counter()
        result = call()
        times[name] = time.perf_counter() - start
        return result

    # The lists: the first page of each filter, and all staff (292).
    for url, params in [*LIST_CASES, ("/api/medications", {"q": "tablet"}), ("/api/staff", {"q": "a"}),
                        ("/api/locations", {"department": "emergency", "q": "bed"})]:
        page = timed(f"GET {url} {params}", lambda: api.get(url, headers=h, params={**params, "limit": 50}))
        assert answer(page) == answer(twin.get(url, headers=h, params={**params, "limit": 50})), (url, params)
    assert all_items(api, "/api/staff", SOFIA) == all_items(twin, "/api/staff", SOFIA)
    # The port reads.
    ctx, ref = full_store.open_ctx(), sqlite_ctx(twin_db)
    d, r = ctx.directory, ref.directory
    staff = rows_of(twin_db, "SELECT Id, IdentifierSystem, IdentifierValue FROM Staff ORDER BY Id DESC LIMIT 1")[0]
    medication = rows_of(twin_db, "SELECT Id FROM Medication WHERE Id IN (SELECT MedicationId FROM Prescription) "
                                  "LIMIT 1")[0]["Id"]
    try:
        for name, call in [
            ("department(1)", lambda x: x.department(1)), ("location(1)", lambda x: x.location(1)),
            ("staff(last)", lambda x: x.staff(staff["Id"])), ("medication(1)", lambda x: x.medication(1)),
            ("department_by_name", lambda x: x.department_by_name("cardiology")),
            ("department_name_exists", lambda x: x.department_name_exists("CARDIOLOGY", 7)),
            ("department_use", lambda x: x.department_use(1)),
            ("location_by_identifier", lambda x: x.location_by_identifier(LOC, "ER-BED-2")),
            ("staff_by_identifier", lambda x: x.staff_by_identifier(staff["IdentifierSystem"],
                                                                      staff["IdentifierValue"])),
            ("staff_use", lambda x: x.staff_use(staff["Id"])), ("staff_use(Okafor)", lambda x: x.staff_use(5)),
            ("medication_in_use", lambda x: x.medication_in_use(medication)),
            ("unique_identifier", lambda x: x.unique_identifier("Location", LOC, "ER-BED-1")),
            ("next_identifier", lambda x: x.next_identifier("Staff", EMPLOYEE, "E", 4)),
            ("staff_list(page 3)", lambda x: x.staff_list(None, None, None, PageRequest(limit=50, offset=100))),
        ]:
            assert timed(name, lambda: call(d)) == call(r), name
    finally:
        ctx.close()
        ref.close()
    # The writes (and their guards).
    created = timed("POST /api/staff", lambda: api.post("/api/staff", headers=h, json={
        "name": "Full Person", "role": "Nurse", "departmentId": 1, "languages": ["en", "fr"]}))
    assert answer(created) == answer(twin.post("/api/staff", headers=h, json={
        "name": "Full Person", "role": "Nurse", "departmentId": 1, "languages": ["en", "fr"]}))
    staff_id = created.json()["id"]
    body = {"active": False, "languages": ["ko"], "designation": "LPN"}
    assert answer(timed("PATCH /api/staff", lambda: api.patch(f"/api/staff/{staff_id}", headers=h, json=body))) == \
        answer(twin.patch(f"/api/staff/{staff_id}", headers=h, json=body))
    metformin = rows_of(twin_db, "SELECT Id, Code, CodeSystem FROM Medication WHERE Code = '860975'")[0]
    for label, method, url, json in [
            ("new location", "POST", "/api/locations", {"name": "Full Room", "department": "Cardiology"}),
            ("new medication", "POST", "/api/medications", {"code": "F-1", "codeSystem": "urn:f", "name": "F"}),
            ("medication key 409", "POST", "/api/medications", {"code": metformin["Code"], "name": "Dup",
                                                                "codeSystem": metformin["CodeSystem"]}),
            ("medication code", "PATCH", f"/api/medications/{metformin['Id']}", {"code": "X-860975"}),
            ("location identifier", "PATCH", "/api/locations/2", {"identifier": {"system": LOC, "value": "ER-W2"}}),
            ("location identifier 409", "PATCH", "/api/locations/3", {"identifier": {"system": LOC, "value": "ER-W2"}}),
            ("new department", "POST", "/api/departments", {"name": "Full Dept"}),
            ("department name", "PATCH", "/api/departments/7", {"name": "Heart"}),
            ("staff in use 409", "DELETE", "/api/staff/5", None),
            ("medication in use 409", "DELETE", f"/api/medications/{metformin['Id']}", None)]:
        response = timed(f"{method} {label}", lambda: api.request(method, url, headers=h, json=json))
        assert answer(response) == answer(twin.request(method, url, headers=h, json=json)), label
        assert (response.status_code == 409) == label.endswith("409"), label
    room = rows_of(twin_db, "SELECT Id FROM Location ORDER BY Id DESC LIMIT 1")[0]["Id"]
    assert answer(timed("DELETE /api/locations", lambda: api.delete(f"/api/locations/{room}", headers=h))) == \
        answer(twin.delete(f"/api/locations/{room}", headers=h))
    works = [row["id"] for row in full_store.probe.rows("works-in", ofStaff=staff_id)]
    ctx, ref = full_store.open_ctx(), sqlite_ctx(twin_db)
    try:
        remove_works_in(ctx, full_store.is_kg, staff_id, works)
        remove_works_in(ref, False, staff_id, works)
    finally:
        ctx.close()
        ref.close()
    assert answer(timed("DELETE /api/staff", lambda: api.delete(f"/api/staff/{staff_id}", headers=h))) == \
        answer(twin.delete(f"/api/staff/{staff_id}", headers=h))
    for url in LISTS:
        assert all_items(api, url, SOFIA) == all_items(twin, url, SOFIA), url
    # Each key guard once on the full data.
    for name in KEY_CASES:
        start = time.perf_counter()
        key_case_errors(full_store, twin_db, name)
        times[f"key {name}"] = time.perf_counter() - start
    with capsys.disabled():
        print(f"\n[{full_store.name}] the directory on the full data (seconds):")
        for name, seconds in sorted(times.items(), key=lambda item: -item[1])[:12]:
            print(f"  {seconds:7.3f}  {name}")
    slow = {name: seconds for name, seconds in times.items() if seconds > full_store.time_limit(0.5)}
    assert slow == {}
