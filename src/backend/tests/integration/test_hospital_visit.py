"""The hospital-visit journey of USER_FLOWS.md section 3 (Steps 0 to 9), through the API.

The test uses a copy of the full database, the fake chat mode and the fixed demo time.
The steps share one database, so they run in the order of this file.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import uuid

import pytest

from domain.access import CARE_TEAM_DENIED
from tests.conftest import all_items, as_user, make_client

pytestmark = pytest.mark.slow

PATIENT_A = "Patient:MRN-000001"
PATIENT_B = "Patient:0c1b260c-7f32-fdd5-15dd-1160caf24c2b"
SOFIA, NAIR, BECKER, PARK, OKAFOR = "MOA:E1001", "Nurse:E1002", "Nurse:E1003", "Nurse:E1004", "Doctor:E1005"
EMPLOYEE = "https://triad.example/fhir/sid/employee"
LOINC, SNOMED = "http://loinc.org", "http://snomed.info/sct"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
OLD_WORDS = ("asthma", "inhaler", "albuterol", "salbutamol")


class Journey:
    """The client and the ids that the steps share."""

    def __init__(self, client, db_path):
        self.client, self.db_path = client, db_path
        self.ids: dict[str, int] = {}
        self.sessions: dict[tuple[str, int], int] = {}

    def call(self, method: str, url: str, user: str, expect: int = 200, **kwargs):
        response = self.client.request(method, url, headers=as_user(user), **kwargs)
        assert response.status_code == expect, response.text
        return response.json() if response.content else None

    def get(self, url, user, expect=200, **kwargs):
        return self.call("GET", url, user, expect, **kwargs)

    def post(self, url, user, expect=200, **kwargs):
        return self.call("POST", url, user, expect, **kwargs)

    def items(self, url: str, user: str, **params) -> list[dict]:
        """All rows of a paged list (all pages)."""
        return all_items(self.client, url, user, **params)

    def ask(self, user: str, patient_id: int, text: str) -> dict:
        key = (user, patient_id)
        if key not in self.sessions:
            self.sessions[key] = self.post(f"/api/patients/{patient_id}/chat/sessions", user, 201)["id"]
        result = self.post(f"/api/chat/sessions/{self.sessions[key]}/turns", user,
                           json={"clientTurnId": str(uuid.uuid4()), "text": text})
        assert result["userTurn"]["text"] == text and result["userTurn"]["speaker"] == "User"
        return result["assistantTurn"]

    def record(self, user: str, text: str, *assertions: dict) -> dict:
        body = {"patientId": self.ids["B"], "text": text, "assertions": list(assertions)}
        return self.post("/api/messages", user, 201, json=body)

    def location(self, code: str) -> int:
        return next(loc["id"] for loc in self.items("/api/locations", SOFIA) if loc["identifier"]["value"] == code)

    def chain(self, assertion_id: int, user: str = OKAFOR) -> list[dict]:
        return self.get(f"/api/assertions/{assertion_id}/chain", user)["items"]

    def care_team(self, *values: str) -> dict:
        return self.call("PUT", f"/api/visits/{self.ids['visit']}/care-team", SOFIA,
                         json={"members": [{"system": EMPLOYEE, "value": v} for v in values]})

    def sql(self, query: str, *args):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(query, args).fetchall()
        finally:
            conn.close()


def new_entry(category, code, system, display, statement, intent, verification, details=None, supersedes=None):
    item = {"newEntry": {"category": category, "code": code, "codeSystem": system, "display": display,
                         "details": details or {}},
            "intent": intent, "verification": verification, "statement": statement}
    if supersedes is not None:
        item["supersedesId"] = supersedes
    return item


@pytest.fixture(scope="module")
def j(full_db, tmp_path_factory) -> Journey:
    path = tmp_path_factory.mktemp("journey") / "journey.db"
    shutil.copy(full_db, path)
    return Journey(make_client(path), path)


def test_step0_the_3mt_slide(j):
    turn = j.ask(OKAFOR, 1, "Is she allergic to penicillin?")
    assert turn["kind"] == "ask"
    assert turn["text"] == "No. A physician ruled it out with an allergy test on Oct 2, 2026."
    assert len(turn["cards"]) == 1
    card = turn["cards"][0]
    assert card["rank"] == 1
    assert card["assertion"]["verification"] == "Refuted" and card["assertion"]["isCurrent"]
    assert card["assertion"]["author"]["label"] == "Physician"
    struck = card["supersedes"]                   # oldest first, as on the slide
    assert [(a["author"]["label"], a["assertedAt"][:4]) for a in struck] == [("Front desk", "2019"),
                                                                            ("Other clinic", "2024")]
    assert not any(a["isCurrent"] for a in struck)


def test_step1_arrival_at_the_front_desk(j):
    found = j.get("/api/patients", SOFIA, params={"q": "marlin", "dob": "1966-02-18", "scope": "all"})["items"]
    assert [p["name"] for p in found] == ["Marlin805 Reggie481 Nienow652"]
    j.ids["B"] = b = found[0]["id"]

    patient = j.call("PATCH", f"/api/patients/{b}", SOFIA, json={"phoneNumber": "+1-508-555-0199"})
    assert patient["phoneNumber"] == "+1-508-555-0199"
    assert patient["permissions"]["checkIn"] and not patient["permissions"]["viewChart"]

    visit = j.post(f"/api/patients/{b}/visits", SOFIA, 201,
                   json={"class": "EMER", "reason": "Shortness of breath", "locationId": j.location("ER-WAIT")})
    j.ids["visit"] = visit["id"]
    assert visit["isOpen"] and visit["class"] == "EMER" and visit["department"] == "Emergency"
    assert [(loc["name"], loc["endDate"]) for loc in visit["locations"]] == [("ER Waiting", None)]
    j.post(f"/api/patients/{b}/visits", SOFIA, 409, json={"class": "EMER", "locationId": j.location("ER-WAIT")})

    j.care_team("E1002", "E1005")
    j.care_team("E1002", "E1005", "E1004")       # Jun Park by mistake
    team = j.care_team("E1002", "E1005")         # remove Jun Park
    assert {m["value"] for m in team["current"]["members"]} == {"E1002", "E1005"}
    assert [{m["value"] for m in v["members"]} for v in team["chain"]] == [
        {"E1002", "E1005"}, {"E1002", "E1005", "E1004"}, {"E1002", "E1005"}]
    assert all(v["author"]["name"] == "Sofia Alvarez" for v in team["chain"])
    assert [v["isCurrent"] for v in team["chain"]] == [True, False, False]
    assert team["chain"][0]["assertedAt"] > team["chain"][1]["assertedAt"] > team["chain"][2]["assertedAt"]
    assert j.get(f"/api/visits/{j.ids['visit']}/care-team", SOFIA) == team

    intake = j.record(SOFIA, "Shortness of breath since this morning.", new_entry(
        "Observation", "8661-1", LOINC, "Chief complaint", "Shortness of breath since this morning.", "Report",
        "Confirmed", {"value": "Shortness of breath since this morning."}))
    note = intake["assertions"][0]
    assert (note["category"], note["code"], note["visitId"]) == ("Observation", "8661-1", j.ids["visit"])
    assert note["author"]["name"] == "Sofia Alvarez" and note["origin"] == "Staff"
    latest = j.get(f"/api/patients/{b}/visits", SOFIA)["items"][0]
    assert latest["id"] == j.ids["visit"] and latest["isOpen"] and latest["locations"][-1]["name"] == "ER Waiting"


def test_step2_waiting_room_patient_report(j):
    b = j.ids["B"]
    turn = j.ask(PATIENT_B, b, "What medications am I taking?")
    assert "metformin" in turn["text"].lower()
    assert any(c["assertion"]["code"] == "860975" for c in turn["cards"])
    assert all(c["supersedes"] == [] for c in turn["cards"])

    items = j.items(f"/api/patients/{b}/chart", PATIENT_B)
    assert all(a["patientVisible"] and a["isCurrent"] for a in items)
    metformin = next(a for a in items if a["category"] == "Prescription" and a["code"] == "860975")
    j.ids["metformin"] = metformin["id"]

    result = j.post("/api/messages", PATIENT_B, 201, json={
        "patientId": b, "text": "I stopped taking metformin.",
        "assertions": [{"entryId": metformin["entryId"], "supersedesId": metformin["id"], "intent": "Report",
                        "verification": "Unconfirmed", "statement": "I stopped taking metformin."}]})
    report = result["assertions"][0]
    j.ids["report"] = report["id"]
    assert report["entryId"] == metformin["entryId"] and report["supersedesId"] == metformin["id"]
    assert (report["channel"], report["origin"]) == ("App", "Patient")
    assert report["author"] == {"name": "Marlin805 Reggie481 Nienow652", "role": "Patient", "staffId": None,
                                "label": "Patient"}
    assert j.sql("SELECT StaffId, Origin, Channel FROM Message WHERE Id = ?", result["messageId"]) == [
        (None, "Patient", "App")]
    assert [a["id"] for a in j.chain(report["id"])][:2] == [report["id"], metformin["id"]]
    assert [a["id"] for a in j.chain(report["id"], PATIENT_B)] == [report["id"]]   # a patient sees the head only


def test_step3_triage_by_the_nurse(j):
    b = j.ids["B"]
    assert b in [p["id"] for p in j.get("/api/patients", NAIR, params={"scope": "care-team"})["items"]]
    assert j.get(f"/api/patients/{b}/visits", NAIR)["total"] > 1

    vitals = j.record(NAIR, "Triage vital signs.",
                      new_entry("Observation", "8867-4", LOINC, "Heart rate", "Heart rate 112 /min.", "Report",
                                "Confirmed", {"value": 112, "unit": "/min"}),
                      new_entry("Observation", "85354-9", LOINC, "Blood pressure panel", "Blood pressure 150/95.",
                                "Report", "Confirmed", {"value": "150/95", "unit": "mm[Hg]"}),
                      new_entry("Observation", "2708-6", LOINC, "Oxygen saturation", "Oxygen saturation 91 %.",
                                "Report", "Confirmed", {"value": 91, "unit": "%"}))
    assert [a["code"] for a in vitals["assertions"]] == ["8867-4", "85354-9", "2708-6"]
    assert {a["messageId"] for a in vitals["assertions"]} == {vitals["messageId"]}
    assert [a["seq"] for a in vitals["assertions"]] == [1, 2, 3]

    asthma = j.record(NAIR, "Assessment at triage.", new_entry(
        "Diagnosis", "195967001", SNOMED, "Asthma attack", "Possible asthma attack.", "Recommendation",
        "Provisional", {"clinicalStatus": "active"}))["assertions"][0]
    inhaler = j.record(NAIR, "Recommend an inhaler.", new_entry(
        "Prescription", "745752", RXNORM, "Salbutamol inhaler", "Recommend a salbutamol inhaler, 2 puffs as needed.",
        "Recommendation", "Provisional", {"status": "draft", "dosage": "2 puffs",
                                          "frequency": "every 4 hours as needed"}))["assertions"][0]
    j.ids.update(asthma=asthma["id"], inhaler=inhaler["id"])
    assert (asthma["intent"], asthma["verification"]) == ("Recommendation", "Provisional")
    assert inhaler["details"]["status"] == "draft" and inhaler["intent"] == "Recommendation"

    visit = j.post(f"/api/visits/{j.ids['visit']}/locations", NAIR, json={"locationId": j.location("ER-BED-2")})
    assert [loc["name"] for loc in visit["locations"]] == ["ER Waiting", "ER Bed 2"]
    assert visit["locations"][0]["endDate"] == visit["locations"][1]["startDate"]

    turn = j.ask(NAIR, b, "Any allergies?")
    assert "no allergy is recorded" in turn["text"].lower()
    assert turn["cards"] == []

    chart = j.items(f"/api/patients/{b}/chart", NAIR, visitId=j.ids["visit"])
    mine = [a for a in chart if a["author"]["name"] == "Priya Nair"]
    assert {a["id"] for a in mine} >= {asthma["id"], inhaler["id"]} | {a["id"] for a in vitals["assertions"]}


def test_step4_the_physician(j):
    b = j.ids["B"]
    turn = j.ask(OKAFOR, b, "What did the nurse recommend?")
    assert {c["assertion"]["id"] for c in turn["cards"]} == {j.ids["asthma"], j.ids["inhaler"]}

    order = j.record(OKAFOR, "Order a troponin test.", new_entry(
        "LabOrder", "89579-7", LOINC, "Troponin I (high sensitivity)", "Order a troponin test, stat.", "Decision",
        "Confirmed", {"priority": "stat", "specimen": "Blood"}))["assertions"][0]
    result = j.record(OKAFOR, "The troponin result.", new_entry(
        "LabReport", "89579-7", LOINC, "Troponin I (high sensitivity)", "Troponin I is above the reference range.",
        "Report", "Confirmed", {"conclusion": "Troponin I 0.09 ng/mL (high)."}))["assertions"][0]
    chart = {a["id"]: a for a in j.items(f"/api/patients/{b}/chart", OKAFOR)}
    assert chart[order["id"]]["category"] == "LabOrder" and chart[result["id"]]["category"] == "LabReport"

    failure = j.record(OKAFOR, "Revise the assessment.", new_entry(
        "Diagnosis", "84114007", SNOMED, "Heart failure", "Possible heart failure.", "Decision", "Provisional",
        {"clinicalStatus": "active"}, supersedes=j.ids["asthma"]))["assertions"][0]
    assert [a["id"] for a in j.chain(failure["id"])] == [failure["id"], j.ids["asthma"]]

    tell = j.ask(OKAFOR, b, "The patient's father died of a heart attack.")
    assert tell["kind"] == "tell" and len(tell["recordedIds"]) == 1
    fact = tell["cards"][0]["assertion"]
    assert fact["id"] == tell["recordedIds"][0]
    assert (fact["category"], fact["source"], fact["verification"], fact["intent"]) == (
        "Observation", "Agent", "Unconfirmed", "Report")
    assert (fact["channel"], fact["origin"], fact["author"]["staffId"]) == ("Chat", "Staff", 5)

    confirm = j.record(OKAFOR, "Confirm the family history.", {
        "entryId": fact["entryId"], "supersedesId": fact["id"], "intent": "Decision", "verification": "Confirmed",
        "statement": "Confirmed: the father died of a heart attack."})["assertions"][0]
    assert confirm["entryId"] == fact["entryId"] and confirm["supersedesId"] == fact["id"]
    assert confirm["source"] == "Human" and confirm["verification"] == "Confirmed"

    furosemide = j.record(OKAFOR, "Prescribe furosemide.", new_entry(
        "Prescription", "313988", RXNORM, "Furosemide 40 MG Oral Tablet", "Start furosemide 40 mg once a day.",
        "Decision", "Confirmed", {"status": "active", "dosage": "40 mg", "frequency": "once a day"},
        supersedes=j.ids["inhaler"]))["assertions"][0]
    assert [a["id"] for a in j.chain(furosemide["id"])] == [furosemide["id"], j.ids["inhaler"]]

    stop = j.record(OKAFOR, "Resolve metformin.", new_entry(
        "Prescription", "860975", RXNORM, "24 HR Metformin hydrochloride 500 MG Extended Release Oral Tablet",
        "Stop metformin.", "Decision", "Confirmed", {"status": "stopped"}, supersedes=j.ids["report"]))["assertions"][0]
    assert stop["details"]["status"] == "stopped"
    chain = j.chain(stop["id"])
    assert [a["id"] for a in chain[:3]] == [stop["id"], j.ids["report"], j.ids["metformin"]]
    assert [a["author"]["label"] for a in chain[:3]] == ["Physician", "Patient", "Physician"]
    j.ids.update(order=order["id"], result=result["id"], failure=failure["id"], fact=fact["id"],
                 confirm=confirm["id"], furosemide=furosemide["id"], stop=stop["id"])


def test_step5_transfer(j):
    visit = j.post(f"/api/visits/{j.ids['visit']}/locations", NAIR, json={"locationId": j.location("CARD-401")})
    names = [loc["name"] for loc in visit["locations"]]
    assert names == ["ER Waiting", "ER Bed 2", "Cardiology Room 401"]
    assert all(loc["endDate"] for loc in visit["locations"][:-1]) and visit["locations"][-1]["endDate"] is None
    assert visit["department"] == "Cardiology"

    team = j.care_team("E1002", "E1005", "E1003")
    assert {m["value"] for m in team["current"]["members"]} == {"E1002", "E1005", "E1003"}
    assert len(team["chain"]) == 4
    assert j.chain(team["chain"][0]["assertionId"])[1]["id"] == team["chain"][1]["assertionId"]
    assert j.get(f"/api/patients/{j.ids['B']}/chart", BECKER)["items"]


def test_step6_evening_plan_of_the_patient(j):
    turn = j.ask(PATIENT_B, j.ids["B"], "What is my plan?")
    text = turn["text"].lower()
    assert "heart failure" in text and "furosemide" in text
    cards = json.dumps(turn["cards"]).lower()
    for word in OLD_WORDS:
        assert word not in text and word not in cards
    assert turn["cards"]
    assert all(c["assertion"]["isCurrent"] and c["assertion"]["patientVisible"] and c["supersedes"] == []
               for c in turn["cards"])
    assert {j.ids["failure"], j.ids["furosemide"]} <= {c["assertion"]["id"] for c in turn["cards"]}


def test_step7_privacy_check(j):
    response = j.client.get(f"/api/patients/{j.ids['B']}/chart", headers=as_user(PARK))
    assert response.status_code == 403
    assert response.json() == {"code": "forbidden", "message": CARE_TEAM_DENIED}
    audit = j.get(f"/api/patients/{j.ids['B']}/audit", PATIENT_B)
    denied = [e for e in audit["items"] if e["outcome"] == "Denied"]
    assert audit["denied"] >= len(denied) >= 1
    assert denied and denied[0]["actorKey"] == PARK and denied[0]["actorName"] == "Jun Park"
    assert denied[0]["path"] == "/api/patients/{patient}/chart" and denied[0]["action"] == "read"


def test_step8_directory(j):
    park = j.get("/api/staff", SOFIA, params={"q": "Jun Park"})["items"][0]
    changed = j.call("PATCH", f"/api/staff/{park['id']}", SOFIA, json={"phoneNumber": "+1-508-555-2999"})
    assert changed["phoneNumber"] == "+1-508-555-2999"
    assert j.get("/api/staff", SOFIA, params={"q": "Jun Park"})["items"][0]["phoneNumber"] == "+1-508-555-2999"

    emergency = next(d for d in j.items("/api/departments", SOFIA) if d["identifier"]["value"] == "TRIAD-GH-EMER")
    error = j.call("DELETE", f"/api/departments/{emergency['id']}", SOFIA, 409)
    assert error["code"] == "conflict" and error["message"] == "The department has staff. You cannot delete it."

    store = j.location("STORE-OLD")
    j.call("DELETE", f"/api/locations/{store}", SOFIA, 204)
    assert "STORE-OLD" not in [loc["identifier"]["value"] for loc in j.items("/api/locations", SOFIA)]


def test_step9_discharge(j):
    visit = j.post(f"/api/visits/{j.ids['visit']}/end", OKAFOR)
    assert visit["endDate"] and not visit["isOpen"]
    assert visit["locations"][-1]["endDate"] == visit["endDate"]
    history = {a["id"]: a for a in j.items(f"/api/patients/{j.ids['B']}/chart", OKAFOR, history="true")}
    journey_ids = {v for k, v in j.ids.items() if k not in ("B", "visit")}
    assert journey_ids <= set(history)
    assert all(history[i]["author"]["name"] for i in journey_ids)
    assert not history[j.ids["asthma"]]["isCurrent"] and not history[j.ids["inhaler"]]["isCurrent"]
    # Each write gets a later time than the demo time, so the times always increase.
    assert all(history[i]["assertedAt"] > "2026-10-30T09:00:00-04:00" for i in journey_ids if i != j.ids["metformin"])
