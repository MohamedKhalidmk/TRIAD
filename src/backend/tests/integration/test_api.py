"""The API on a copy of the full database: the read side, the records, the chat, the errors and the directory."""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
import types
import uuid

import pytest

from domain.access import CARE_TEAM_DENIED
from domain.errors import Conflict, Invalid
from infrastructure import config
from infrastructure.clock import DemoClock
from infrastructure.sqlite.connection import connect
from infrastructure.sqlite.unit_of_work import SqliteUnitOfWork
from tests.conftest import all_items, as_user, make_client

pytestmark = pytest.mark.slow

ELENA, PATIENT_B = "Patient:MRN-000001", "Patient:0c1b260c-7f32-fdd5-15dd-1160caf24c2b"
SOFIA, PARK, OKAFOR = "MOA:E1001", "Nurse:E1004", "Doctor:E1005"
B_ID = 81


def scalar(path, sql, *args):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql, args).fetchone()[0]
    finally:
        conn.close()


def q12_ids(path, name: str, dob: str) -> set[int]:
    """Run query Q12 of dml/03_select_queries.sql for one patient. It returns the assertion ids."""
    text = (config.DML_DIR / "03_select_queries.sql").read_text(encoding="utf-8")
    block = re.search(r"-- Q12\..*?(SELECT e\.Category.*?;)", text, re.S).group(1)
    sql = block.replace("SELECT e.Category, e.Display, a.Verification, date(a.AssertedAt) AS Date, a.Statement",
                        "SELECT a.Id", 1)
    sql = sql.replace("'Elena Marsh'", "?").replace("'1971-05-14'", "?")
    conn = sqlite3.connect(path)
    try:
        return {row[0] for row in conn.execute(sql, (name, dob))}
    finally:
        conn.close()


def ask(client, user, patient_id, text, client_turn_id=None):
    session = client.post(f"/api/patients/{patient_id}/chat/sessions", headers=as_user(user))
    assert session.status_code == 201, session.text
    body = {"clientTurnId": client_turn_id or str(uuid.uuid4()), "text": text}
    turn = client.post(f"/api/chat/sessions/{session.json()['id']}/turns", headers=as_user(user), json=body)
    assert turn.status_code == 200, turn.text
    return session.json()["id"], turn.json()


# ----- the read side -----

def test_the_patient_chart_is_the_q12_result(client, full_copy):
    for key, pid, name, dob in ((ELENA, 1, "Elena Marsh", "1971-05-14"),
                                (PATIENT_B, B_ID, "Marlin805 Reggie481 Nienow652", "1966-02-18")):
        items = all_items(client, f"/api/patients/{pid}/chart", key)
        assert items and {a["id"] for a in items} == q12_ids(full_copy, name, dob)
    # A patient report (no open visit: the backend makes a virtual visit that ends at once) is visible too.
    report = client.post("/api/messages", headers=as_user(PATIENT_B), json={
        "patientId": B_ID, "text": "I get short of breath on stairs.", "assertions": [{
            "newEntry": {"category": "Observation", "code": "8661-1", "codeSystem": "http://loinc.org",
                         "display": "Chief complaint", "details": {"value": "Short of breath on stairs."}},
            "intent": "Report", "verification": "Unconfirmed", "statement": "I get short of breath on stairs."}]})
    assert report.status_code == 201, report.text
    made = report.json()["assertions"][0]
    visit = client.get(f"/api/patients/{B_ID}/visits", headers=as_user(PATIENT_B)).json()["items"][0]
    assert visit["id"] == made["visitId"] and visit["class"] == "VR" and visit["endDate"] == visit["startDate"]
    assert client.get(f"/api/patients/{B_ID}", headers=as_user(PATIENT_B)).json()["openVisitId"] is None
    items = all_items(client, f"/api/patients/{B_ID}/chart", PATIENT_B)
    assert made["id"] in {a["id"] for a in items}
    assert {a["id"] for a in items} == q12_ids(full_copy, "Marlin805 Reggie481 Nienow652", "1966-02-18")


def test_the_staff_chart_is_the_current_state_and_history_adds_the_old_versions(client):
    current = client.get("/api/patients/1/chart", headers=as_user(OKAFOR)).json()["items"]
    history = client.get("/api/patients/1/chart?history=true", headers=as_user(OKAFOR)).json()["items"]
    assert all(a["isCurrent"] for a in current) and len(current) == 8
    assert len(history) == 10 and {a["id"] for a in current} < {a["id"] for a in history}
    allergy = [a["assertedAt"] for a in history if a["category"] == "Allergy"]
    assert history[0]["category"] == "Allergy" and allergy == sorted(allergy, reverse=True)   # newest first
    allergies = client.get("/api/patients/1/chart?category=Allergy", headers=as_user(OKAFOR)).json()["items"]
    assert [a["details"]["substance"] for a in allergies] == ["Allergy to penicillin"]


def test_the_chart_of_patient_b_is_fast(client):
    """Patient B has more than 500 current items. A chart page (with its audit write) takes less than 300 ms."""
    for params in ("", "?history=true", "?offset=500", "?limit=200&q=e"):
        client.get(f"/api/patients/{B_ID}/chart{params}", headers=as_user(PATIENT_B))
        start = time.perf_counter()
        response = client.get(f"/api/patients/{B_ID}/chart{params}", headers=as_user(PATIENT_B))
        elapsed = time.perf_counter() - start
        assert response.status_code == 200 and response.json()["total"] > 500 and response.json()["items"]
        assert elapsed < 0.3, f"the chart took {elapsed:.3f} s"


def test_the_chain_is_newest_first_and_a_patient_gets_the_head_only(client):
    staff = client.get("/api/assertions/1/chain", headers=as_user(OKAFOR)).json()
    assert staff["headId"] == 3 and [a["id"] for a in staff["items"]] == [3, 2, 1]
    patient = client.get("/api/assertions/1/chain", headers=as_user(ELENA)).json()
    assert [a["id"] for a in patient["items"]] == [3]


# ----- access and audit -----

def test_a_denied_chart_read_is_in_the_audit_log(client, full_copy):
    before = scalar(full_copy, "SELECT COUNT(*) FROM AuditEvent WHERE Outcome = 'Denied'")
    response = client.get("/api/patients/1/chart", headers=as_user(PARK))
    assert response.status_code == 403 and response.json() == {"code": "forbidden", "message": CARE_TEAM_DENIED}
    assert scalar(full_copy, "SELECT COUNT(*) FROM AuditEvent WHERE Outcome = 'Denied'") == before + 1
    assert scalar(full_copy, "SELECT ActorValue || '|' || SubjectName FROM AuditEvent ORDER BY Id DESC LIMIT 1") \
        == "E1004|Elena Marsh"
    page = client.get("/api/patients/1/audit", headers=as_user(ELENA)).json()
    events = page["items"]
    assert events[0]["action"] == "read" and events[0]["actorKey"] == ELENA      # the audit read itself
    assert events[1]["outcome"] == "Denied" and events[1]["actorName"] == "Jun Park"
    assert page["denied"] == scalar(full_copy, "SELECT COUNT(*) FROM AuditEvent WHERE Outcome = 'Denied' "
                                               "AND SubjectName = 'Elena Marsh'")


@pytest.mark.parametrize("user,method,url,status", [
    (SOFIA, "GET", "/api/patients/1/chart", 403),           # an MOA does not see the chart
    (SOFIA, "POST", "/api/patients/1/chat/sessions", 403),  # nor the chat
    (PATIENT_B, "GET", "/api/patients/1", 403),             # a patient sees self only
    (PARK, "GET", "/api/patients/1/visits", 403),
    (OKAFOR, "GET", "/api/patients/1/audit", 200),           # a doctor on the care team
    (SOFIA, "GET", "/api/patients/1/visits", 200),
    (PARK, "GET", "/api/patients/1", 200),                  # staff can read the demographics
    (PATIENT_B, "GET", "/api/departments", 403),
    (PARK, "DELETE", "/api/locations/19", 403),
])
def test_the_access_rules_through_the_api(client, user, method, url, status):
    response = client.request(method, url, headers=as_user(user))
    assert response.status_code == status, response.text
    if status == 403:
        assert response.json()["code"] == "forbidden"


def test_the_user_header(client):
    assert client.get("/api/me").json()["code"] == "no_user"
    assert client.get("/api/me", headers=as_user("Doctor:E9999")).status_code == 401
    assert client.get("/api/me", headers=as_user("Nobody")).status_code == 401
    assert client.get("/api/me", headers=as_user(PATIENT_B)).json()["name"] == "Marlin805 Reggie481 Nienow652"
    assert client.get("/api/users/Doctor:E9999").status_code == 404
    pinned = client.get("/api/users").json()["items"][:8]
    assert [u["key"] for u in pinned][:3] == [ELENA, PATIENT_B, SOFIA] and all(u["pinned"] for u in pinned)
    nurses = client.get("/api/users?role=Nurse&q=park").json()["items"]
    assert [(u["name"], u["detail"]) for u in nurses] == [("Jun Park", "Home Health")]


# ----- records -----

def okafor_note(client, assertion: dict, patient_id: int = 1):
    return client.post("/api/messages", headers=as_user(OKAFOR),
                       json={"patientId": patient_id, "text": "A note.", "assertions": [assertion]})


def test_the_head_check_and_the_supersede_guard(client, full_copy):
    # The allergy entry has a current assertion (3). A new assertion must supersede it.
    wrong = okafor_note(client, {"entryId": 1, "supersedesId": 2, "intent": "Decision", "verification": "Refuted",
                                 "statement": "Not allergic."})
    assert wrong.status_code == 409 and wrong.json()["code"] == "conflict"
    # The current item is visible to the patient: only a doctor decision can supersede it, not a report.
    before = scalar(full_copy, "SELECT COUNT(*) FROM AuditEvent WHERE Outcome = 'Denied'")
    report = okafor_note(client, {"entryId": 1, "supersedesId": 3, "intent": "Report", "verification": "Unconfirmed",
                                  "statement": "Maybe allergic."})
    assert report.status_code == 403
    assert scalar(full_copy, "SELECT COUNT(*) FROM AuditEvent WHERE Outcome = 'Denied'") == before + 1
    decision = okafor_note(client, {"entryId": 1, "supersedesId": 3, "intent": "Decision", "verification": "Refuted",
                                    "statement": "Not allergic. I checked again."})
    assert decision.status_code == 201, decision.text
    again = okafor_note(client, {"entryId": 1, "supersedesId": 3, "intent": "Decision", "verification": "Refuted",
                                 "statement": "Not allergic."})
    assert again.status_code == 409                          # the data changed


def test_new_entries_need_an_open_visit_for_staff(client):
    response = okafor_note(client, {"newEntry": {"category": "Observation", "code": "8867-4",
                                                 "codeSystem": "http://loinc.org", "display": "Heart rate",
                                                 "details": {"value": 80}},
                                    "intent": "Report", "verification": "Confirmed", "statement": "Heart rate 80."})
    assert response.status_code == 422 and "no open visit" in response.json()["message"]


def test_request_errors_use_the_error_body(client):
    response = client.post("/api/messages", headers=as_user(OKAFOR), json={"patientId": 1, "assertions": []})
    body = response.json()
    assert response.status_code == 422 and body["code"] == "validation" and "text" in body["fields"]
    both = okafor_note(client, {"intent": "Decision", "verification": "Refuted", "statement": "x"})
    assert both.status_code == 422 and "assertions[0]" in both.json()["fields"]
    assert client.get("/api/nothing-here").json()["code"] == "not_found"
    assert client.get("/api/patients/99999", headers=as_user(SOFIA)).status_code == 404


def test_database_errors_become_domain_errors(scenario_copy):
    conn = connect(scenario_copy)
    uow = SqliteUnitOfWork(conn, DemoClock("2026-10-30T09:00:00-04:00"))
    with pytest.raises(Invalid, match="append-only"):
        with uow.write():
            conn.execute("UPDATE Assertion SET Statement = 'x' WHERE Id = 1")
    with pytest.raises(Conflict):
        with uow.write():
            conn.execute("INSERT INTO Medication (Code, CodeSystem, Name) SELECT Code, CodeSystem, Name "
                         "FROM Medication LIMIT 1")
    with pytest.raises(Invalid):
        with uow.write():
            conn.execute("UPDATE Patient SET Sex = 'none' WHERE Id = 1")
    assert conn.execute("SELECT Statement FROM Assertion WHERE Id = 1").fetchone()[0] != "x"   # rolled back
    conn.close()


# ----- chat -----

def test_the_cards_come_only_from_the_citation_rows(client, full_copy):
    session_id, turn = ask(client, OKAFOR, 1, "Any allergies?")
    reply = turn["assistantTurn"]
    conn = sqlite3.connect(full_copy)
    rows = conn.execute("SELECT AssertionId, Rank FROM Citation WHERE ChatTurnId = ? ORDER BY Rank",
                        (reply["id"],)).fetchall()
    kind = conn.execute("SELECT Action FROM AuditEvent WHERE ChatTurnId = ?", (reply["id"],)).fetchall()
    conn.close()
    assert rows and [(c["assertion"]["id"], c["rank"]) for c in reply["cards"]] == rows
    assert kind == [("ask",)]
    saved = client.get(f"/api/chat/sessions/{session_id}", headers=as_user(OKAFOR)).json()
    assert saved["turns"][1]["cards"] == reply["cards"] and saved["turns"][1]["kind"] == "ask"
    assert saved["turns"][0]["kind"] is None and saved["mode"] == "fake"


def test_the_same_client_turn_id_gives_the_saved_turns(client, full_copy):
    session_id, first = ask(client, OKAFOR, 1, "Is she allergic to penicillin?", client_turn_id="turn-1")
    count = scalar(full_copy, "SELECT COUNT(*) FROM ChatTurn")
    again = client.post(f"/api/chat/sessions/{session_id}/turns", headers=as_user(OKAFOR),
                        json={"clientTurnId": "turn-1", "text": "Is she allergic to penicillin?"}).json()
    assert again == first and scalar(full_copy, "SELECT COUNT(*) FROM ChatTurn") == count
    other = client.post(f"/api/chat/sessions/{session_id}/turns", headers=as_user(ELENA),
                        json={"clientTurnId": "turn-2", "text": "Any allergies?"})
    assert other.status_code == 403                          # the session belongs to another user
    summaries = client.get("/api/patients/1/chat/sessions", headers=as_user(OKAFOR)).json()["items"]
    assert summaries[0]["id"] == session_id and summaries[0]["turnCount"] == 2
    assert summaries[0]["firstQuestion"] == "Is she allergic to penicillin?"


def test_a_tell_with_no_fact_makes_no_message(client, full_copy):
    messages = scalar(full_copy, "SELECT COUNT(*) FROM Message")
    _, turn = ask(client, ELENA, 1, "Thank you for the help.")
    reply = turn["assistantTurn"]
    assert reply["kind"] == "tell" and reply["recordedIds"] == [] and reply["cards"] == []
    assert "no fact" in reply["text"]
    assert scalar(full_copy, "SELECT COUNT(*) FROM Message") == messages


def test_a_patient_tell_is_a_patient_report_in_the_chat(client, full_copy):
    _, turn = ask(client, ELENA, 1, "My mother has diabetes.")
    fact = turn["assistantTurn"]["cards"][0]["assertion"]
    assert (fact["source"], fact["verification"], fact["channel"], fact["origin"]) == (
        "Agent", "Unconfirmed", "Chat", "Patient")
    assert fact["author"]["staffId"] is None and fact["patientVisible"]
    assert scalar(full_copy, "SELECT StaffId IS NULL FROM Message WHERE Id = ?", fact["messageId"]) == 1


def llm_check_passes(monkeypatch):
    """Make the start check of the llm mode pass, with no litellm and no key."""
    from infrastructure.llm import litellm_client
    monkeypatch.setattr(litellm_client, "check_ready", lambda model: None)


def test_the_llm_mode_falls_back_to_the_fake_model(full_copy, monkeypatch, caplog):
    llm_check_passes(monkeypatch)                             # then each model call fails
    client = make_client(full_copy, llm_mode="llm", llm_model="triad-test/no-such-model")
    assert client.get("/api/health").json()["mode"] == "llm"
    session_id, turn = ask(client, OKAFOR, 1, "Is she allergic to penicillin?")
    assert turn["assistantTurn"]["text"] == "No. A physician ruled it out with an allergy test on Oct 2, 2026."
    saved = client.get(f"/api/chat/sessions/{session_id}", headers=as_user(OKAFOR)).json()
    assert (saved["mode"], saved["model"]) == ("llm", "triad-test/no-such-model")
    _, tell = ask(client, OKAFOR, 1, "Her father died of a heart attack.")
    assert tell["assistantTurn"]["kind"] == "tell"            # no open visit: nothing is saved, and no error
    assert tell["assistantTurn"]["recordedIds"] == []
    assert "This turn uses the fake model." in caplog.text


def test_the_llm_mode_with_no_api_key_runs_the_fake_mode(full_copy, monkeypatch, capsys):
    from infrastructure.llm import litellm_client
    monkeypatch.setattr(litellm_client, "check_ready", lambda model: f"no API key for {model} is set.")
    client = make_client(full_copy, llm_mode="llm", llm_model="gemini/gemini-3.8-flash")
    assert client.get("/api/health").json()["mode"] == "fake"
    session_id, _ = ask(client, OKAFOR, 1, "Is she allergic to penicillin?")
    saved = client.get(f"/api/chat/sessions/{session_id}", headers=as_user(OKAFOR)).json()
    assert (saved["mode"], saved["model"]) == ("fake", None)   # the badge shows the mode that really runs
    assert "TRIAD_LLM=llm, but no API key for gemini/gemini-3.8-flash is set." in capsys.readouterr().err


def test_no_api_key_text_goes_to_a_response_the_log_or_the_database(full_copy, monkeypatch, caplog):
    secret = "triad-test-secret-0123456789"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    llm_check_passes(monkeypatch)

    def fail(**request):                                      # each call of the ask loop and of the extractor
        raise RuntimeError(f"The provider does not accept the API key {secret}.")
    litellm = types.ModuleType("litellm")
    litellm.completion = fail
    monkeypatch.setitem(sys.modules, "litellm", litellm)
    client = make_client(full_copy, llm_mode="llm", llm_model="gemini/gemini-3.8-flash")
    texts = [client.get("/api/health").text]
    session_id, turn = ask(client, OKAFOR, 1, "Is she allergic to penicillin?")
    _, tell = ask(client, OKAFOR, 1, "Her father died of a heart attack.")
    texts += [json.dumps(turn), json.dumps(tell),
              client.get(f"/api/chat/sessions/{session_id}", headers=as_user(OKAFOR)).text]
    assert "RuntimeError" in caplog.text                     # the model call failed, and the log says so
    assert all(secret not in text for text in texts + [caplog.text])
    for path in (full_copy, full_copy.with_name(full_copy.name + "-wal")):
        if path.exists():
            assert secret.encode() not in path.read_bytes()


# ----- patients and the directory -----

def test_register_change_and_delete_a_patient(client):
    created = client.post("/api/patients", headers=as_user(SOFIA), json={
        "name": "Test Person", "dateOfBirth": "1990-01-02", "sex": "female", "address": {"city": "Worcester"}})
    assert created.status_code == 201, created.text
    patient = created.json()
    assert patient["identifiers"] == [{"system": "https://triad.example/fhir/sid/mrn", "value": "MRN-000002"}]
    assert client.get("/api/me", headers=as_user("Patient:MRN-000002")).json()["patientId"] == patient["id"]
    duplicate = client.post("/api/patients", headers=as_user(SOFIA),
                            json={"name": "Test Person", "dateOfBirth": "1990-01-02", "sex": "female"})
    assert duplicate.status_code == 409
    renamed = client.patch(f"/api/patients/{patient['id']}", headers=as_user(SOFIA), json={"name": "Other Name"})
    assert renamed.status_code == 422 and "name" in renamed.json()["fields"]
    moved = client.patch(f"/api/patients/{patient['id']}", headers=as_user(SOFIA),
                         json={"address": {"street": "1 Main Street"}}).json()
    assert moved["address"]["street"] == "1 Main Street" and moved["address"]["city"] == "Worcester"
    assert client.post("/api/patients", headers=as_user(PARK), json={
        "name": "X", "dateOfBirth": "1990-01-02", "sex": "male"}).status_code == 403
    assert client.delete(f"/api/patients/{B_ID}", headers=as_user(SOFIA)).status_code == 409
    assert client.delete(f"/api/patients/{patient['id']}", headers=as_user(SOFIA)).status_code == 204
    assert client.get(f"/api/patients/{patient['id']}", headers=as_user(SOFIA)).status_code == 404


def test_the_directory_rows(client):
    h = as_user(SOFIA)
    dept = client.post("/api/departments", headers=h, json={"name": "Radiology", "phoneNumber": "+1-508-555-0190"})
    assert dept.status_code == 201 and dept.json()["identifier"]["value"] == "TRIAD-GH-RADIOLOGY"
    dept_id = dept.json()["id"]
    room = client.post("/api/locations", headers=h, json={"name": "X-ray Room 1", "department": "radiology"}).json()
    assert room["department"] == "Radiology" and room["identifier"]["value"] == "X-RAY-ROOM-1" and not room["inUse"]
    renamed = client.patch(f"/api/departments/{dept_id}", headers=h, json={"name": "Imaging"}).json()
    assert renamed["name"] == "Imaging"
    imaging = client.get("/api/locations?department=Imaging", headers=h).json()["items"]
    assert [x["name"] for x in imaging] == ["X-ray Room 1"]
    assert client.delete(f"/api/departments/{dept_id}", headers=h).status_code == 409   # it has a location
    nurse = client.post("/api/staff", headers=h, json={"name": "Test Nurse", "role": "Nurse", "departmentId": dept_id,
                                                       "designation": "RPN", "languages": ["en", "fr"]})
    assert nurse.status_code == 201, nurse.text
    staff = nurse.json()
    assert staff["key"] == "Nurse:E1026" and staff["designation"] == "RPN"
    assert staff["departments"][0]["name"] == "Imaging" and staff["languages"] == ["en", "fr"]
    assert client.patch(f"/api/staff/{staff['id']}", headers=h, json={"desk": "Desk 1"}).status_code == 422
    assert client.patch(f"/api/staff/{staff['id']}", headers=h, json={"active": False}).json()["active"] is False
    assert client.delete(f"/api/staff/{staff['id']}", headers=h).status_code == 409    # works in a department
    used = next(x for x in client.get("/api/locations", headers=h).json()["items"] if x["inUse"])
    assert used["identifier"]["value"] == "ER-UNIT"                                      # the default ER location
    assert client.delete(f"/api/locations/{used['id']}", headers=h).status_code == 409   # a visit used it
    assert client.delete(f"/api/locations/{room['id']}", headers=h).status_code == 204
    med = client.post("/api/medications", headers=h, json={"code": "T-1", "codeSystem": "urn:test", "name": "Test"})
    assert med.status_code == 201
    assert client.post("/api/medications", headers=h,
                       json={"code": "T-1", "codeSystem": "urn:test", "name": "Again"}).status_code == 409
    metformin = client.get("/api/medications?q=860975", headers=h).json()["items"][0]
    assert client.delete(f"/api/medications/{metformin['id']}", headers=h).status_code == 409
    assert client.delete(f"/api/medications/{med.json()['id']}", headers=h).status_code == 204
    presets = client.get("/api/codes?category=Prescription", headers=as_user(OKAFOR)).json()
    assert {p["code"] for p in presets} == {"745752", "313988", "860975"}


def test_the_built_frontend_gets_index_html_for_deep_links(full_copy, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>TRIAD</html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    client = make_client(full_copy, frontend_dist=dist)
    assert client.get("/patients/81").text == "<html>TRIAD</html>"
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/api/no-such-path").json()["code"] == "not_found"
    assert client.get("/api/health").json()["status"] == "ok"
