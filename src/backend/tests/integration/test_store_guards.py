"""The guard table (plan 5.4, 5.6): the rules of the database through the API, on each store.

Each case of models/relational/sql/dml/05_constraint_violations.sql that the API can reach gives the same status,
code and body on each store, and changes no row. SQLite holds these rules in its constraints and triggers (and the
use cases check some of them first); the knowledge graph holds them in the use cases and in the guards of
infrastructure/sparql/guards*.py. `twin` is a SQLite copy of the data that the test makes before it writes.

The cases that the API cannot reach (the request has no field for them, or the use case sets the value): an ISA
mismatch, a subtype row with the wrong role, a message with no issuer from staff, a visit that ends before it
starts, a change or a delete of an assertion or of an audit record, a superseded assertion that is newer, a
message about two patients, and the three citation and audit checks of the chat. The port tests hold these on
each store (test_store_records_writes.py, test_store_chat_audit.py, test_sparql_unit_of_work.py).

The last tests show the order of the guards: the assertion guards (agent B) run before the key guards (agent D),
as SQLite runs the triggers of a row before its UNIQUE constraints.
"""
from __future__ import annotations

import shutil
from typing import Callable

import pytest

from tests.conftest import as_user, make_client

MOA, OKAFOR = as_user("MOA:E1001"), as_user("Doctor:E1005")
EMPLOYEE = "https://triad.example/fhir/sid/employee"
LOINC = "http://loinc.org"
KINDS = ("patient", "patient-identifier", "visit", "department", "staff", "message", "clinical-entry", "assertion",
         "care-team-member", "medication")


@pytest.fixture
def twin(store, tmp_path):
    path = tmp_path / "twin.db"
    shutil.copy(store.db_path, path)
    return make_client(path)


def note(*assertions: dict, **extra) -> dict:
    return {"patientId": 1, "text": "A note.", "assertions": list(assertions), **extra}


def observation(**extra) -> dict:
    return {"newEntry": {"category": "Observation", "code": "8867-4", "codeSystem": LOINC, "display": "Heart rate",
                         "details": {"value": "80"}},
            "intent": "Decision", "verification": "Confirmed", "statement": "Heart rate 80.", **extra}


def other_patient_report(api):
    """A second patient reports a new fact that supersedes the current penicillin assertion of Elena (3)."""
    created = api.post("/api/patients", headers=MOA, json={"name": "Test Person", "dateOfBirth": "1990-01-02",
                                                           "sex": "female"})
    assert created.status_code == 201, created.text
    key = f"Patient:{created.json()['identifiers'][0]['value']}"
    return api.post("/api/messages", headers=as_user(key), json={
        "patientId": created.json()["id"], "text": "Not allergic.",
        "assertions": [observation(intent="Report", verification="Unconfirmed", supersedesId=3)]})


def department_id(api, value: str) -> int:
    return next(d["id"] for d in api.get("/api/departments", headers=MOA, params={"limit": 200}).json()["items"]
                if d["identifier"]["value"] == value)


# (the case of 05_constraint_violations.sql, the request, the status, the code)
CASES: list[tuple[str, Callable, int, str]] = [
    ("duplicate patient key (Name, DateOfBirth)",
     lambda api: api.post("/api/patients", headers=MOA, json={"name": "Elena Marsh", "dateOfBirth": "1971-05-14",
                                                              "sex": "female"}), 409, "conflict"),
    ("duplicate identifier (a client-given department identifier)",
     lambda api: api.post("/api/departments", headers=MOA, json={
         "name": "Another Emergency", "identifier": {"system": "https://triad.example/fhir/sid/organization",
                                                     "value": "TRIAD-GH-EMER"}}), 409, "conflict"),
    ("a visit for a patient that does not exist",
     lambda api: api.post("/api/patients/99999/visits", headers=MOA, json={"class": "EMER", "locationId": 1}),
     404, "not_found"),
    ("a nurse designation that is not in the value set",
     lambda api: api.post("/api/staff", headers=MOA, json={"name": "Test Nurse", "role": "Nurse",
                                                           "departmentId": 1, "designation": "Chief"}),
     422, "validation"),
    ("a channel that is not in the value set",
     lambda api: api.post("/api/messages", headers=OKAFOR, json=note(observation(), visitId=3, channel="Pigeon")),
     422, "validation"),
    ("a visit class that is not in the value set",
     lambda api: api.post("/api/patients/1/visits", headers=MOA, json={"class": "XYZ", "locationId": 1}),
     422, "validation"),
    ("a date of birth that is not a date",
     lambda api: api.post("/api/patients", headers=MOA, json={"name": "Test Patient Date",
                                                              "dateOfBirth": "not a date", "sex": "female"}),
     422, "validation"),
    ("a new claim about an entry that has a current assertion, without superseding it",
     lambda api: api.post("/api/messages", headers=OKAFOR, json=note(
         {"entryId": 1, "intent": "Report", "verification": "Unconfirmed", "statement": "Rash again."})),
     409, "conflict"),
    ("a second assertion that supersedes the same assertion",
     lambda api: api.post("/api/messages", headers=OKAFOR, json=note(observation(supersedesId=1), visitId=3)),
     409, "conflict"),
    ("supersede an assertion of another patient", other_patient_report, 422, "validation"),
    ("a care-team member that is not a staff member",
     lambda api: api.put("/api/visits/3/care-team", headers=MOA, json={"members": [{"system": EMPLOYEE,
                                                                                     "value": "E0000"}]}),
     422, "validation"),
    ("change the key of a patient",
     lambda api: api.patch("/api/patients/1", headers=MOA, json={"name": "Elena M."}), 422, "validation"),
    ("delete a patient who has visits",
     lambda api: api.delete("/api/patients/1", headers=MOA), 409, "conflict"),
    ("delete a department that has staff",
     lambda api: api.delete(f"/api/departments/{department_id(api, 'TRIAD-GH-EMER')}", headers=MOA),
     409, "conflict"),
    ("(plan 5.4) a duplicate medication key (Code, CodeSystem)",
     lambda api: [api.post("/api/medications", headers=MOA, json={"code": "T-1", "codeSystem": "urn:test",
                                                                   "name": name}) for name in ("Test", "Again")][-1],
     409, "conflict"),
]


def counts(store) -> dict[str, int]:
    return {kind: store.probe.count(kind) for kind in KINDS}


@pytest.mark.parametrize("name, request_, status, code", CASES, ids=[case[0] for case in CASES])
def test_each_reachable_case_gives_the_same_error_on_each_store(store, twin, name, request_, status, code):
    before = counts(store)
    found, expected = request_(store.client()), request_(twin)
    assert (found.status_code, found.json()["code"]) == (status, code), found.text
    assert (expected.status_code, expected.json()["code"]) == (status, code), expected.text
    assert found.json() == expected.json()
    changed = {kind: n for kind, n in counts(store).items() if n != before[kind]}
    setup = {"supersede an assertion of another patient": {"patient", "patient-identifier"},
             "(plan 5.4) a duplicate medication key (Code, CodeSystem)": {"medication"}}.get(name, set())
    assert set(changed) == setup and all(n == before[kind] + 1 for kind, n in changed.items()), changed


# ----- the order of the guards -----

def test_the_assertion_guards_run_before_the_key_guards():
    """guards.EXTENSIONS: the guards of agent B (the triggers of SQLite) before the guards of agent D (UNIQUE)."""
    from infrastructure.sparql import guards
    owners = [g.owner for g in guards.registered()]
    assert owners == sorted(owners, key="ABCD".index) and set(owners) == {"A", "B", "C", "D"}
    assert guards.EXTENSIONS.index("infrastructure.sparql.guards_records") < \
        guards.EXTENSIONS.index("infrastructure.sparql.guards_directory")


def test_a_write_that_breaks_a_trigger_and_a_key_gives_the_trigger_error_on_each_store(store, tmp_path,
                                                                                         monkeypatch):
    """Two new assertions of one write supersede the head of the penicillin entry (3). The second one breaks the
    one-head trigger (422) and the key UK_Assertion_SupersedesId (409). SQLite runs the trigger first (BEFORE
    INSERT), so the knowledge graph must too. The API cannot send this write (the use case refuses two assertions
    that supersede the same one: 422), so the test writes through the port. With the key guards first, the
    knowledge graph would give the UNIQUE error: the test sees the order."""
    from infrastructure.sparql import guards
    from tests.integration.test_store_records_writes import ONE_HEAD, assertion, head_of, new_message, open_pair, \
        outcome
    pair = open_pair(store, tmp_path)
    try:
        head = head_of(pair, 1)

        def two_heads(ctx, now):
            message = new_message(ctx, now)
            assertion(ctx, message, 1, 1, head, now)
            assertion(ctx, message, 2, 1, head, now)
        assert outcome(pair, two_heads) == [ONE_HEAD, ONE_HEAD]
        if store.is_kg:
            keys_first = sorted(guards.registered(), key=lambda g: g.owner != "D")
            monkeypatch.setattr(guards, "_REGISTRY", {g.name: g for g in keys_first})
            key = ("Conflict", "A row with the same key exists already.", {"key": "Assertion.SupersedesId"})
            assert outcome(pair, two_heads) == [key, ONE_HEAD]
    finally:
        pair.kg.close()
        pair.ref.close()
