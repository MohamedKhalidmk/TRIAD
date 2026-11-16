"""The patients on each store (the PatientRepository port; plan 5.5 and 5.6).

Each test runs on SQLite and on the knowledge graph (Oxigraph; Virtuoso with TRIAD_TEST_STORES). A KG store must
give the same results as SQLite on the same data: the reads are compared with `store.reference()`, the writes with
the `twin` (a SQLite copy of the same data; tests/integration/kg_compare.py).
"""
from __future__ import annotations

import time

import pytest

from application.paging import PageRequest
from domain.errors import Conflict, Invalid
from tests.conftest import all_items, as_user, make_client
from tests.fixtures.stores import SqliteProbe
from tests.integration.kg_compare import (BRENNAN, ELENA, EMPLOYEE, MOA, OKAFOR, PARK, both, instants,
                                          response, twin)  # noqa: F401 (twin is a fixture)

INJECTIONS = ('" } ; DROP ALL ; #', '"', "\\", "\\u0022 } ; CLEAR ALL ; #", "'; DROP", "$q", "a\nb")
NEW_PATIENTS = [
    {"name": "Test Person", "dateOfBirth": "1990-01-02", "sex": "female", "address": {"city": "Worcester"}},
    {"name": "anna lee", "dateOfBirth": "1985-03-04", "sex": "female", "phoneNumber": "+1-508-555-0101"},
    {"name": "Zoë Marlow", "dateOfBirth": "1971-05-14", "sex": "other",
     "address": {"street": "1 Main Street", "city": "Boston", "region": "MA", "postalCode": "02108", "country": "US"}},
    {"name": "Test Person", "dateOfBirth": "1990-01-03", "sex": "male"},
    {"name": "O'Neil \"Ned\" Back\\slash", "dateOfBirth": "2001-12-31", "sex": "unknown"},
]


@pytest.fixture
def reference(store):
    """A SQLite client on the same data as the store (for the reads)."""
    return make_client(store.db_path)


# ----- reads -----

@pytest.mark.parametrize("user", [MOA, PARK, OKAFOR, BRENNAN, ELENA])
def test_one_patient_is_the_same_on_each_store(store, reference, user):
    api = store.client()
    found = api.get("/api/patients/1", headers=as_user(user))
    assert response(found) == response(reference.get("/api/patients/1", headers=as_user(user)))
    assert found.status_code == 200 and found.json()["identifiers"][0]["value"] == "MRN-000001"
    for missing in (99999, -1, 0):
        r = api.get(f"/api/patients/{missing}", headers=as_user(MOA))
        assert r.status_code == 404 and r.json()["code"] == "not_found", missing


def test_the_patient_port_reads(store):
    ctx, ref = store.open_ctx(), store.reference()
    assert ctx.patients.get(1) == ref.patients.get(1)
    assert ctx.patients.get(99999) is None and ctx.patients.get(-1) is None
    assert ctx.patients.key_exists("Elena Marsh", "1971-05-14") and ref.patients.key_exists("Elena Marsh", "1971-05-14")
    for name, dob in (("Elena Marsh", "1971-05-15"), ("elena marsh", "1971-05-14"), ("Elena", "1971-05-14")):
        assert ctx.patients.key_exists(name, dob) is ref.patients.key_exists(name, dob) is False
    assert ctx.patients.has_visits(1) and not ctx.patients.has_visits(99999)
    for member in ("E1005", "E1006", "E1004", "E1001", "e1005"):
        assert ctx.patients.on_care_team(1, EMPLOYEE, member) is ref.patients.on_care_team(1, EMPLOYEE, member), member
    assert ctx.patients.on_care_team(1, EMPLOYEE, "E1005") and not ctx.patients.on_care_team(1, "urn:other", "E1005")


@pytest.mark.parametrize("params", [{}, {"q": "mar"}, {"q": "MARSH"}, {"q": "no such name"}, {"dob": "1971-05-14"},
                                    {"dob": "1971-05-15"}, {"scope": "open-visits"}, {"scope": "care-team"},
                                    {"q": "elena", "scope": "care-team", "dob": "1971-05-14"}])
@pytest.mark.parametrize("user", [MOA, OKAFOR, PARK, ELENA])
def test_the_search_on_the_scenario_data(store, reference, params, user):
    expected = all_items(reference, "/api/patients", user, **params)
    assert all_items(store.client(), "/api/patients", user, **params) == expected


def test_a_search_text_cannot_change_the_query(store):
    """Plan 5.2: the escape function. The search works, and no graph changes."""
    api = store.client()
    rows = store.probe.count("patient"), store.probe.count("patient-identifier")
    for text in INJECTIONS:
        r = api.get("/api/patients", params={"q": text}, headers=as_user(MOA))
        assert r.status_code == 200 and r.json()["total"] == 0, text
    assert api.get("/api/patients", params={"dob": '1971-05-14"'}, headers=as_user(MOA)).status_code == 422
    assert (store.probe.count("patient"), store.probe.count("patient-identifier")) == rows
    assert api.get("/api/patients", params={"q": "marsh"}, headers=as_user(MOA)).json()["total"] == 1


# ----- writes (each one on the store and on the twin) -----

def test_register_change_and_delete_on_each_store(store, twin):
    created = [both(store, twin, "post", "/api/patients", MOA, json=body) for body in NEW_PATIENTS]
    assert [status for status, _ in created] == [201] * len(NEW_PATIENTS)
    assert [p["identifiers"][0]["value"] for _, p in created] == [f"MRN-00000{n}" for n in range(2, 7)]
    first = created[0][1]["id"]
    assert both(store, twin, "post", "/api/patients", MOA, json=NEW_PATIENTS[0])[0] == 409
    assert both(store, twin, "post", "/api/patients", PARK, json=NEW_PATIENTS[1])[0] == 403
    wrong_date = {**NEW_PATIENTS[1], "dateOfBirth": "1985-02-30"}
    assert both(store, twin, "post", "/api/patients", MOA, json=wrong_date)[0] == 422
    # The search over the new patients: the order of the names (the code points), then the id.
    api, other = store.client(), twin.client()
    for params in ({}, {"q": "test"}, {"q": "ë"}, {"q": "'neil \"ned\" back\\"}, {"dob": "1971-05-14"},
                   {"q": "a", "dob": "1985-03-04"}):
        full = all_items(other, "/api/patients", MOA, **params)
        assert all_items(api, "/api/patients", MOA, **params) == full, params
        for offset in (0, 2, len(full), len(full) + 3):
            page = api.get("/api/patients", headers=as_user(MOA), params={**params, "limit": 2, "offset": offset})
            assert page.json()["total"] == len(full) and page.json()["items"] == full[offset:offset + 2]
    names = [p["name"] for p in all_items(api, "/api/patients", MOA)]
    assert names[:3] == ["Elena Marsh", "O'Neil \"Ned\" Back\\slash", "Test Person"] and names[-1] == "anna lee"
    # The changes: phone, sex, a part of the address; the key cannot change.
    url = f"/api/patients/{first}"
    for body in ({"phoneNumber": "+1-508-555-0199"}, {"sex": "other"}, {"address": {"street": "2 Elm Street"}},
                 {"address": {"city": None, "country": "CA"}}, {"phoneNumber": ""}, {},
                 {"name": "Test Person", "dateOfBirth": "1990-01-02", "sex": "female"}):
        status, patient = both(store, twin, "patch", url, MOA, json=body)
        assert status == 200, body
    assert patient["address"] == {"street": "2 Elm Street", "city": None, "region": None, "postalCode": None,
                                  "country": "CA"} and patient["phoneNumber"] is None
    for body in ({"name": "Other Name"}, {"dateOfBirth": "1990-01-05"}, {"sex": "robot"}):
        status, error = both(store, twin, "patch", url, MOA, json=body)
        assert status == 422 and error["code"] == "validation", body
    assert both(store, twin, "patch", url, OKAFOR, json={"phoneNumber": "1"})[0] == 403    # a denial: an audit record
    # The delete: a patient with no visits; a patient with visits is in use.
    assert both(store, twin, "delete", url, MOA) == (204, None)
    assert both(store, twin, "get", url, MOA)[0] == 404
    assert both(store, twin, "delete", "/api/patients/1", MOA)[0] == 409
    assert both(store, twin, "get", "/api/patients/1", MOA)[0] == 200
    # The stored rows are the same (times as instants).
    reference = SqliteProbe(twin.path)
    for kind in ("patient", "patient-identifier", "audit-event"):
        assert instants(store.probe.rows(kind)) == instants(reference.rows(kind)), kind
    assert store.probe.count("patient-identifier") == 2 + len(NEW_PATIENTS) - 1


def test_the_next_mrn_looks_in_the_write_buffer(store, twin):
    """Two new patients in one write get two MRN values (the KG reads the write buffer too)."""
    from domain.records import Address
    values = {}
    for name, ctx in (("store", store.open_ctx()), ("twin", twin.ctx())):
        with ctx.uow.write():
            for n in (1, 2):
                mrn = ctx.patients.next_identifier(ctx.identity.mrn, "MRN-", 6)
                ctx.patients.create(f"Buffer Person {n}", "2000-01-0" + str(n), "male", None, Address(),
                                    [(ctx.identity.mrn, mrn)])
        values[name] = [ctx.patients.get(i) for i in (2, 3)]
    assert values["store"] == values["twin"]
    assert [p.identifiers[0].value for p in values["store"]] == ["MRN-000002", "MRN-000003"]


# ----- the guards (the unit of work directly: the API checks these rules first) -----

def write_error(ctx, change) -> Exception:
    with pytest.raises((Conflict, Invalid)) as error:
        with ctx.uow.write():
            change(ctx)
    return error.value


def kg_or_sql(store, kg, sql):
    """The violating change: `kg` (the write buffer) on a KG store, `sql` (one statement) on SQLite."""
    def change(ctx):
        if store.is_kg:
            kg(ctx.patients.session.write_buffer())
        else:
            ctx.patients.conn.execute(sql)
    return change


def test_the_patient_key_cannot_change(store):
    from infrastructure.sparql.terms import iri
    ctx, ref = store.open_ctx(), store.reference()
    for prop, column, value in (("name", "Name", "Elena M."), ("dateOfBirth", "DateOfBirth", "1971-05-15")):
        found = write_error(ctx, kg_or_sql(store, lambda buf: buf.replace(iri("patient", 1), prop, value),
                                           f"UPDATE Patient SET {column} = '{value}' WHERE Id = 1"))
        expected = write_error(ref, lambda c: c.patients.conn.execute(
            f"UPDATE Patient SET {column} = '{value}' WHERE Id = 1"))
        assert (type(found), found.message, found.fields) == (type(expected), expected.message, expected.fields)
        assert found.message == "The name and the date of birth of a patient cannot change."
    with ctx.uow.write():                                       # the same value again is not a change
        ctx.patients.update(1, {"Sex": "female"})
    assert ctx.patients.get(1) == ref.patients.get(1)


def test_a_patient_with_visits_cannot_be_deleted(store):
    ctx, ref = store.open_ctx(), store.reference()
    found = write_error(ctx, lambda c: c.patients.delete(1))
    expected = write_error(ref, lambda c: c.patients.delete(1))
    assert (type(found), found.message) == (type(expected), expected.message) == \
           (Conflict, "The row is in use, or it points to a row that does not exist.")
    assert ctx.patients.get(1) == ref.patients.get(1)


@pytest.mark.skip(reason="needs the key guard key.patient of agent D (guards_directory.py)")
def test_the_patient_key_is_unique(store):
    """UK_Patient_Name_DateOfBirth: a second patient with the same name and date of birth (the use case checks
    this first, so only the port can write it)."""
    from domain.records import Address
    ctx, ref = store.open_ctx(), store.reference()
    found = write_error(ctx, lambda c: c.patients.create("Elena Marsh", "1971-05-14", "female", None, Address(), []))
    expected = write_error(ref, lambda c: c.patients.create("Elena Marsh", "1971-05-14", "female", None, Address(), []))
    assert (type(found), found.message, found.fields) == (type(expected), expected.message, expected.fields)
    assert found.fields == {"key": "Patient.Name, Patient.DateOfBirth"}


# ----- the full data -----

def timed(fn, *args, **kwargs):
    start = time.perf_counter()
    out = fn(*args, **kwargs)
    return out, time.perf_counter() - start


@pytest.mark.parametrize("params", [{}, {"q": "a"}, {"q": "MAR"}, {"dob": "1971-05-14"}, {"scope": "open-visits"},
                                    {"scope": "care-team"}, {"q": "e", "scope": "open-visits"}])
def test_the_search_on_the_full_data(full_store, params):
    api, reference = full_store.client(), make_client(full_store.db_path)
    user = OKAFOR if params.get("scope") == "care-team" else MOA
    full = all_items(reference, "/api/patients", user, **params)
    assert all_items(api, "/api/patients", user, **params) == full
    for offset in (0, 7, len(full) - 1, len(full), len(full) + 5):
        page, seconds = timed(api.get, "/api/patients", headers=as_user(user),
                              params={**params, "limit": 25, "offset": max(offset, 0)})
        assert page.json()["total"] == len(full) and page.json()["items"] == full[max(offset, 0):max(offset, 0) + 25]
        assert seconds < full_store.time_limit(0.3), (params, offset, seconds)


def test_the_care_team_of_the_full_data(full_store):
    """on_care_team() and the care-team search for the members with the most care teams (Synthea NPI members)."""
    import sqlite3
    ctx, ref = full_store.open_ctx(), full_store.reference()
    conn = sqlite3.connect(full_store.db_path)
    members = conn.execute("SELECT MemberSystem, MemberValue FROM CareTeamMember GROUP BY 1, 2 "
                           "ORDER BY COUNT(*) DESC, 1, 2 LIMIT 3").fetchall()
    patients = [r[0] for r in conn.execute("SELECT Id FROM Patient ORDER BY Id")]
    conn.close()
    members.append((EMPLOYEE, "E1005"))
    for member in members:
        page = PageRequest(limit=200)
        found, seconds = timed(ctx.patients.search, None, None, "care-team", member, page)
        assert found == ref.patients.search(None, None, "care-team", member, page), member
        assert seconds < full_store.time_limit(0.3), (member, seconds)
        team = {p.id for p in found.items}
        for patient_id in patients[:40] + [p for p in team]:
            assert ctx.patients.on_care_team(patient_id, *member) is (patient_id in team), (member, patient_id)


def test_the_patient_reads_of_the_full_data_are_fast(full_store):
    ctx, ref = full_store.open_ctx(), full_store.reference()
    timings = {}
    for patient_id in (1, 61, 81, 95):
        found, timings[f"get {patient_id}"] = timed(ctx.patients.get, patient_id)
        assert found == ref.patients.get(patient_id)
    _, timings["search all"] = timed(ctx.patients.search, None, None, "all", None, PageRequest())
    _, timings["search q"] = timed(ctx.patients.search, "mar", None, "all", None, PageRequest())
    with ctx.uow.write():
        _, timings["next MRN"] = timed(ctx.patients.next_identifier, ctx.identity.mrn, "MRN-", 6)
    print("\n[patients, full data]", {k: f"{v * 1000:.1f} ms" for k, v in timings.items()})
    assert max(timings.values()) < full_store.time_limit(0.3), timings
