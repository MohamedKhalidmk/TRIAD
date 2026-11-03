"""The tools of the Care Assistant (application/assistant/tools.py) and the loop (agent.py), on the full database.

- Each tool is one targeted query. Its result is the same as the old Python selection on the full chart
  (the rules of answers.py before the tools), for Patient A, Patient B and the largest Synthea patient.
- No tool parameter is a patient, a user or an id, and each schema has additionalProperties = false.
- A scripted fake `litellm` module gives tool calls. It checks the arguments, the references and the citations,
  that no id and no patient data go to the model, the patient-visible rule and the fallback to the fake model.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import types
import uuid
from types import SimpleNamespace

import pytest

import main
from application.assistant import agent, service, tools
from application.assistant.tools import MAX_ITEMS, PLAN_ORDER, VITAL_SIGNS, make_tools
from application.ports import ToolCall
from domain.access import Actor
from domain.rules import plan_visit
from infrastructure import config
from infrastructure.llm.litellm_client import LiteLlmLanguageModel
from tests.conftest import DEMO_NOW, as_user, make_client

pytestmark = pytest.mark.slow

ELENA_ID, B_ID = 1, 81
OKAFOR = "Doctor:E1005"
PENICILLIN_ANSWER = "No. A physician ruled it out with an allergy test on Oct 2, 2026."
FORBIDDEN_NAMES = {"patient", "user", "mrn", "name", "dob", "identifier"}
ALL_CALLS = [("get_allergies", {}), ("get_medications", {"status": "all"}), ("get_diagnoses", {}),
             ("get_plan", {}), ("get_lab_results", {}), ("get_vital_signs", {}), ("get_visits", {}),
             ("get_recommendations", {}), ("search_record", {"text": "a"})]


def open_ctx(db_path):
    settings = config.Settings(db_path=db_path, now=DEMO_NOW, llm_mode="fake", llm_model="triad-test",
                               frontend_dist=None)
    return main.context_factory(settings)()


@pytest.fixture(scope="module")
def ctx(full_db):
    """A context on the full database, for reads only."""
    context = open_ctx(full_db)
    yield context
    context.close()


@pytest.fixture
def fresh_ctx(full_db):
    """A context that a test can change (for example the model or a spy on a repository)."""
    context = open_ctx(full_db)
    yield context
    context.close()


def largest_patient(ctx) -> int:
    """The Synthea patient with the most current items (12,471)."""
    return ctx.records.conn.execute(
        "SELECT v.PatientId FROM Visit v JOIN ClinicalEntry e ON e.VisitId = v.Id "
        "JOIN Assertion a ON a.ClinicalEntryId = e.Id "
        "WHERE NOT EXISTS (SELECT 1 FROM Assertion n WHERE n.SupersedesId = a.Id) "
        "GROUP BY v.PatientId ORDER BY COUNT(*) DESC LIMIT 1").fetchone()[0]


def doctor(ctx) -> Actor:
    return ctx.users.actor("Doctor", "E1005")


def patient_actor(patient) -> Actor:
    return Actor(role="Patient", key=f"Patient:test-{patient.id}", name=patient.name, system="test",
                 value=str(patient.id), patient_id=patient.id)


@pytest.fixture(scope="module", params=["A", "B", "largest"])
def patient(request, ctx):
    pid = {"A": ELENA_ID, "B": B_ID, "largest": largest_patient(ctx)}[request.param]
    return ctx.patients.get(pid)


@pytest.fixture(scope="module", params=["clinician", "patient"])
def case(request, ctx, patient):
    """(the actor, the patient, the full current chart that the actor can see, newest first)."""
    actor = doctor(ctx) if request.param == "clinician" else patient_actor(patient)
    items = ctx.records.assertions(patient.id, current_only=True)
    if actor.is_patient:
        items = [a for a in items if a.patient_visible]
    return actor, patient, items


def ids(items) -> list[int]:
    return [a.id for a in items]


def call(box, name: str, **arguments):
    result = box.run(ToolCall(call_id="test", name=name, arguments=json.dumps(arguments)))
    assert result.error is None, result.error
    return result


# ----- the old Python selection on the full chart (the rules of answers.py before the tools) -----

def old_term_matches(term: str, a) -> bool:
    words = [w for w in term.split() if len(w) >= 3]
    text = f"{a.display} {a.details.get('substance') or ''}".lower()
    return bool(words) and all(w in text for w in words)


def old_medications(items, current=True):
    return [a for a in items if a.category == "Prescription" and (not current or (
        a.details.get("status") in ("active", "draft") and a.verification not in ("Refuted", "EnteredInError")))]


def old_diagnoses(items, current=True):
    return [a for a in items if a.category == "Diagnosis" and (not current or (
        a.details.get("clinicalStatus") in (None, "active", "recurrence", "relapse")
        and a.verification not in ("Refuted", "EnteredInError")))]


def old_vitals(items):
    seen, found = set(), []
    for a in items:
        if a.category == "Observation" and a.code in VITAL_SIGNS and a.code not in seen:
            seen.add(a.code)
            found.append(a)
    return found


def old_recommendations(ctx, actor, patient, role):
    visit_id = plan_visit(ctx.visits.visit_rows(patient.id))
    found = ctx.records.assertions(patient.id, current_only=False, visit_id=visit_id)
    if actor.is_patient:
        found = [a for a in found if a.patient_visible]
    found = [a for a in found if a.intent == "Recommendation" and (not role or a.author.role == role)]
    found.sort(key=lambda a: (a.asserted_at, a.seq))
    return found


# ----- each tool = the old selection -----

def test_get_allergies(ctx, case):
    actor, patient, items = case
    box = make_tools(ctx, actor, patient)
    allergy = [a for a in items if a.category == "Allergy"]
    assert ids(call(box, "get_allergies").items) == ids(allergy[:MAX_ITEMS])
    terms = {"penicillin", "ox", "peanut allergy"} | {a.display.split()[-1].lower() for a in allergy[:3]}
    for term in sorted(terms):
        expected = [a for a in allergy if old_term_matches(term, a)][:MAX_ITEMS]
        assert ids(call(box, "get_allergies", substance=term).items) == ids(expected), term


def test_get_medications_and_get_diagnoses(ctx, case):
    actor, patient, items = case
    box = make_tools(ctx, actor, patient)
    assert ids(call(box, "get_medications").items) == ids(old_medications(items)[:MAX_ITEMS])
    assert ids(call(box, "get_medications", status="all").items) == ids(old_medications(items, False)[:MAX_ITEMS])
    assert ids(call(box, "get_diagnoses").items) == ids(old_diagnoses(items)[:MAX_ITEMS])
    assert ids(call(box, "get_diagnoses", status="all").items) == ids(old_diagnoses(items, False)[:MAX_ITEMS])


def test_get_plan(ctx, case):
    actor, patient, items = case
    result = call(make_tools(ctx, actor, patient), "get_plan")
    visit_id = plan_visit(ctx.visits.visit_rows(patient.id))
    chosen = [a for a in items if a.visit_id == visit_id and a.category in PLAN_ORDER]
    chosen.sort(key=lambda a: PLAN_ORDER.index(a.category))
    assert result.visit.id == visit_id
    assert ids(result.items) == ids(chosen[:MAX_ITEMS])


def test_get_lab_results(ctx, case):
    actor, patient, items = case
    box = make_tools(ctx, actor, patient)
    labs = [a for a in items if a.category in ("LabOrder", "LabReport")]
    assert ids(call(box, "get_lab_results").items) == ids(labs[:MAX_ITEMS])
    for term in {"troponin", "glucose"} | {a.display.split()[0].lower() for a in labs[:2]}:
        words = [w for w in term.split() if len(w) >= 3]

        def matches(a):
            text = f"{a.display} {a.details.get('testName') or ''} {a.details.get('conclusion') or ''}".lower()
            return all(w in text for w in words)
        expected = [a for a in labs if matches(a)] if words else []
        assert ids(call(box, "get_lab_results", test=term).items) == ids(expected[:MAX_ITEMS]), term


def test_get_vital_signs_gives_the_latest_value_of_each_code(ctx, case):
    actor, patient, items = case
    result = call(make_tools(ctx, actor, patient), "get_vital_signs")
    assert ids(result.items) == ids(old_vitals(items))
    assert len({a.code for a in result.items}) == len(result.items)


def test_get_visits(ctx, case):
    actor, patient, _ = case
    result = call(make_tools(ctx, actor, patient), "get_visits")
    assert [v.id for v in result.visits] == [v.id for v in ctx.visits.for_patient(patient.id)[:5]]
    assert result.items == [] and result.total == len(ctx.visits.visit_rows(patient.id))


def test_get_recommendations(ctx, case):
    actor, patient, _ = case
    box = make_tools(ctx, actor, patient)
    for role in (None, "Nurse", "Doctor"):
        expected = old_recommendations(ctx, actor, patient, role)[:MAX_ITEMS]
        arguments = {"role": role} if role else {}
        assert ids(call(box, "get_recommendations", **arguments).items) == ids(expected), role


def test_search_record(ctx, case):
    actor, patient, items = case
    box = make_tools(ctx, actor, patient)
    chart_order = ("Allergy", "Diagnosis", "Prescription", "Observation", "LabOrder", "LabReport", "Procedure",
                   "CareTeam")
    for text, category in (("blood", None), ("pain", "Observation"), ("care team", None), ("visit", "CareTeam")):
        expected = [a for a in items if (category is None or a.category == category)
                    and any(text in s.lower() for s in (a.display, a.statement, a.author.name))]
        expected.sort(key=lambda a: chart_order.index(a.category))
        arguments = {"text": text, **({"category": category} if category else {})}
        result = call(box, "search_record", **arguments)
        assert ids(result.items) == ids(expected[:MAX_ITEMS]) and result.total == len(expected), text


def test_a_patient_gets_only_patient_visible_items(ctx, patient):
    box = make_tools(ctx, patient_actor(patient), patient)
    for name, arguments in ALL_CALLS + [("get_medications", {})]:
        assert all(a.patient_visible and a.is_current for a in call(box, name, **arguments).items), name


# ----- the schemas and the checks of a call -----

def test_no_tool_parameter_is_a_patient_a_user_or_an_id(ctx):
    definitions = make_tools(ctx, doctor(ctx), ctx.patients.get(ELENA_ID)).definitions
    assert len({d.name for d in definitions}) == len(definitions) == 9
    for d in definitions:
        schema = d.parameters
        assert schema["type"] == "object" and schema["additionalProperties"] is False, d.name
        assert set(schema.get("required", [])) <= set(schema["properties"])
        for name, spec in schema["properties"].items():
            assert not name.lower().endswith("id") and name.lower() not in FORBIDDEN_NAMES, (d.name, name)
            assert spec["type"] == "string", (d.name, name)


class Spy:
    """A repository that counts the calls of its methods."""

    def __init__(self, inner, calls: list):
        self._inner, self._calls = inner, calls

    def __getattr__(self, name):
        value = getattr(self._inner, name)
        if not callable(value):
            return value

        def counted(*args, **kwargs):
            self._calls.append(name)
            return value(*args, **kwargs)
        return counted


def spy_on(ctx) -> list:
    calls: list = []
    ctx.records, ctx.visits = Spy(ctx.records, calls), Spy(ctx.visits, calls)
    return calls


@pytest.mark.parametrize("name,arguments,message", [
    ("get_allergies", '{"patientId": 81, "substance": "penicillin"}', "has no parameter patientId"),
    ("get_patient", "{}", "There is no tool get_patient"),
    ("get_medications", '{"status": "stopped"}', "must be one of: current, all"),
    ("get_allergies", '{"substance": 5}', "must be a string"),
    ("search_record", "{}", "needs the parameter text"),
    ("search_record", '{"text": "  "}', "Give a word"),
    ("get_plan", "not json", "not correct JSON"),
    ("get_plan", "[1]", "must be a JSON object"),
])
def test_a_call_that_is_not_correct_gets_an_error_text_and_runs_no_query(fresh_ctx, name, arguments, message):
    calls = spy_on(fresh_ctx)
    box = make_tools(fresh_ctx, doctor(fresh_ctx), fresh_ctx.patients.get(B_ID))
    result = box.run(ToolCall(call_id="bad", name=name, arguments=arguments))
    assert message in json.loads(result.content)["error"] and result.items == []
    assert calls == [] and box.refs == {}
    call(box, "get_allergies", substance="penicillin")
    assert calls == ["allergies"]                             # a correct call runs its one query


def test_the_same_item_keeps_its_reference_in_a_turn(ctx):
    box = make_tools(ctx, doctor(ctx), ctx.patients.get(ELENA_ID))
    first = json.loads(call(box, "get_allergies").content)["items"]
    again = json.loads(call(box, "get_allergies", substance="penicillin").content)["items"]
    assert [i["ref"] for i in first] == [f"E{n}" for n in range(1, len(first) + 1)]
    penicillin = next(i["ref"] for i in first if "penicillin" in i["display"].lower())
    assert [i["ref"] for i in again] == [penicillin]
    assert box.refs[penicillin].display == "Allergy to penicillin"


# ----- the loop with a scripted fake litellm module -----

def response(text=None, calls=()):
    """A response of litellm.completion: the tool calls (name, arguments) or the final text."""
    tool_calls = [SimpleNamespace(id=f"call_{n}", type="function", provider_specific_fields=None,
                                  function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))
                  for n, (name, arguments) in enumerate(calls, 1)]
    message = SimpleNamespace(role="assistant", content=text, tool_calls=tool_calls or None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message,
                                                    finish_reason="tool_calls" if calls else "stop")])


class ScriptedLitellm:
    """A fake litellm module. Each completion call gives the next step of the script."""

    def __init__(self, monkeypatch, steps, on_call=None):
        self.steps, self.requests, self.on_call = list(steps), [], on_call
        module = types.ModuleType("litellm")
        module.completion = self.completion
        module.validate_environment = lambda model: {"keys_in_environment": True, "missing_keys": []}
        module.supports_function_calling = lambda model: True
        monkeypatch.setitem(sys.modules, "litellm", module)

    def completion(self, **request):
        if self.on_call:
            self.on_call()
        self.requests.append(json.loads(json.dumps(request)))     # only JSON can go to the provider
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    def tool_contents(self) -> list[dict]:
        """The tool results in the last request (each request holds all messages of the turn)."""
        return [json.loads(m["content"]) for m in self.requests[-1]["messages"] if m["role"] == "tool"]


def with_llm(ctx):
    ctx.llm = LiteLlmLanguageModel("gemini/gemini-3.8-flash")
    return ctx


def test_an_extra_patient_id_gets_an_error_and_runs_no_query(fresh_ctx, monkeypatch):
    calls = spy_on(fresh_ctx)
    seen: list[int] = []
    script = ScriptedLitellm(monkeypatch, [
        response(calls=[("get_allergies", {"patientId": B_ID, "substance": "penicillin"})]),
        response(calls=[("get_allergies", {"substance": "penicillin"})]),
        response("No. A physician ruled it out on 2026-10-02 [E1]."),
    ], on_call=lambda: seen.append(len(calls)))
    patient = fresh_ctx.patients.get(ELENA_ID)
    reply = service.answer(with_llm(fresh_ctx), doctor(fresh_ctx), patient, "Is she allergic to penicillin?")
    assert seen[0] == seen[1] < seen[2]                          # the call with patientId ran no query
    error, found = script.tool_contents()[:2]
    assert "has no parameter patientId" in error["error"]
    assert [i["display"] for i in found["items"]] == ["Allergy to penicillin"]
    assert reply.text == "No. A physician ruled it out on 2026-10-02."
    assert [(a.display, a.verification, a.is_current) for a in reply.cited] == [
        ("Allergy to penicillin", "Refuted", True)]


def test_an_unknown_reference_is_dropped(fresh_ctx, monkeypatch):
    ScriptedLitellm(monkeypatch, [
        response(calls=[("get_medications", {})]),
        response("She takes [E2] and [E99, E1]. Also [e2]."),
    ])
    patient = fresh_ctx.patients.get(B_ID)
    reply = service.answer(with_llm(fresh_ctx), doctor(fresh_ctx), patient, "What medications?")
    meds = call(make_tools(fresh_ctx, doctor(fresh_ctx), patient), "get_medications").items
    assert len(meds) < 99 and ids(reply.cited) == [meds[1].id, meds[0].id]   # the first mention; no E99
    assert reply.text == "She takes and. Also."


def test_no_reference_cites_the_items_of_the_tools(fresh_ctx, monkeypatch):
    ScriptedLitellm(monkeypatch, [response(calls=[("get_medications", {})]), response("Two medications.")])
    patient = fresh_ctx.patients.get(B_ID)
    reply = service.answer(with_llm(fresh_ctx), doctor(fresh_ctx), patient, "What medications?")
    meds = call(make_tools(fresh_ctx, doctor(fresh_ctx), patient), "get_medications").items
    assert reply.text == "Two medications." and ids(reply.cited) == ids(meds)


def keys_of(value) -> list[str]:
    if isinstance(value, dict):
        return [k for k in value] + [k for v in value.values() for k in keys_of(v)]
    if isinstance(value, list):
        return [k for v in value for k in keys_of(v)]
    return []


@pytest.mark.parametrize("pid", [ELENA_ID, B_ID])
def test_no_id_and_no_patient_data_go_to_the_model(fresh_ctx, monkeypatch, pid):
    calls = ALL_CALLS + [("search_record", {"text": "care team"}), ("get_allergies", {"substance": "penicillin"})]
    script = ScriptedLitellm(monkeypatch, [response(calls=calls), response("Done [E1].")])
    patient = fresh_ctx.patients.get(pid)
    reply = service.answer(with_llm(fresh_ctx), doctor(fresh_ctx), patient, "Summarize the record.")
    assert reply.text == "Done." and reply.cited
    sent = json.dumps(script.requests)
    private = [patient.name, *patient.name.split(), patient.date_of_birth, *(i.value for i in patient.identifiers)]
    assert not [value for value in private if value.lower() in sent.lower()]
    contents = script.tool_contents()
    assert len(contents) == len(calls) and not any("error" in c for c in contents)
    for request in script.requests:
        for tool in request["tools"]:
            assert not [k for k in keys_of(tool["function"]["parameters"]) if k.lower().endswith("id")]
    assert not [k for c in contents for k in keys_of(c) if k.lower().endswith("id")]
    # The record ids of the items: the ids of Patient A are small numbers, so only Patient B is checked here.
    box = make_tools(fresh_ctx, doctor(fresh_ctx), patient)
    record_ids = {n for name, arguments in calls for a in call(box, name, **arguments).items
                  for n in (a.id, a.entry_id, a.message_id, a.visit_id)}
    if pid == B_ID:
        assert record_ids and all(n > 1000 for n in record_ids)
        assert not [n for n in record_ids if re.search(rf"(?<![\d.]){n}(?![\d.])", sent)]


def test_a_patient_gets_only_patient_visible_items_in_the_loop(fresh_ctx, monkeypatch):
    boxes = []

    def keep(*args):
        boxes.append(tools.make_tools(*args))
        return boxes[-1]
    monkeypatch.setattr(agent, "make_tools", keep)
    ScriptedLitellm(monkeypatch, [response(calls=ALL_CALLS), response("Here is your record.")])
    patient = fresh_ctx.patients.get(ELENA_ID)
    reply = service.answer(with_llm(fresh_ctx), patient_actor(patient), patient, "What is in my record?")
    assert boxes[0].refs and all(a.patient_visible for a in boxes[0].refs.values())
    assert reply.cited and all(a.patient_visible for a in reply.cited)
    clinician = make_tools(fresh_ctx, doctor(fresh_ctx), patient)
    hidden = {a.id for name, arguments in ALL_CALLS for a in call(clinician, name, **arguments).items
              if not a.patient_visible}
    assert hidden and not hidden & {a.id for a in boxes[0].refs.values()}


@pytest.mark.parametrize("steps,error", [
    ([RuntimeError("The provider does not accept the API key triad-test-secret-42.")], "RuntimeError"),
    ([response(calls=[("get_allergies", {})])] * 4, "NoAnswer"),          # the 4 rounds run out
    ([response("")], "LlmError"),                                          # no text
])
def test_a_failure_of_the_model_gives_the_fake_answer(fresh_ctx, monkeypatch, caplog, steps, error):
    ScriptedLitellm(monkeypatch, steps)
    caplog.set_level(logging.WARNING, logger="triad.chat")
    patient = fresh_ctx.patients.get(ELENA_ID)
    reply = service.answer(with_llm(fresh_ctx), doctor(fresh_ctx), patient, "Is she allergic to penicillin?")
    assert reply.text == PENICILLIN_ANSWER and [a.display for a in reply.cited] == ["Allergy to penicillin"]
    warnings = [r.getMessage() for r in caplog.records if r.name == "triad.chat"]
    assert warnings == [f"The language model failed to answer the question ({error}). This turn uses the fake model."]
    assert "triad-test-secret-42" not in caplog.text


def test_the_llm_mode_answers_through_the_api_with_the_tools(full_copy, monkeypatch):
    script = ScriptedLitellm(monkeypatch, [
        response(calls=[("get_allergies", {"substance": "penicillin"})]),
        response("No. A physician ruled it out with an allergy test on 2026-10-02 [E1]."),
    ])
    client = make_client(full_copy, llm_mode="llm", llm_model="gemini/gemini-3.8-flash")
    session = client.post(f"/api/patients/{ELENA_ID}/chat/sessions", headers=as_user(OKAFOR)).json()
    assert (session["mode"], session["model"]) == ("llm", "gemini/gemini-3.8-flash")
    turn = client.post(f"/api/chat/sessions/{session['id']}/turns", headers=as_user(OKAFOR),
                       json={"clientTurnId": str(uuid.uuid4()), "text": "Is she allergic to penicillin?"}).json()
    reply = turn["assistantTurn"]
    assert reply["text"] == "No. A physician ruled it out with an allergy test on 2026-10-02."
    assert [(c["rank"], c["assertion"]["display"], c["assertion"]["verification"]) for c in reply["cards"]] == [
        (1, "Allergy to penicillin", "Refuted")]
    assert [a["author"]["label"] for a in reply["cards"][0]["supersedes"]] == ["Front desk", "Other clinic"]
    first = script.requests[0]
    assert first["tool_choice"] == "auto" and "temperature" not in first
    assert [m["role"] for m in first["messages"]] == ["system", "user"]
    assert "the patient of this chat" in first["messages"][0]["content"]
    assert [m["role"] for m in script.requests[1]["messages"]] == ["system", "user", "assistant", "tool"]


def test_a_turn_reads_no_full_chart(full_copy, capsys):
    """Each SQL statement of a turn that reads the items of the patient has a LIMIT (the SQL log)."""
    client = make_client(full_copy, sql_log="on")
    session = client.post(f"/api/patients/{ELENA_ID}/chat/sessions", headers=as_user(OKAFOR)).json()
    for question in ("Is she allergic to penicillin?", "What is the plan?", "What are her vital signs?",
                     "What did the nurse recommend?", "Any lab results?"):
        capsys.readouterr()
        turn = client.post(f"/api/chat/sessions/{session['id']}/turns", headers=as_user(OKAFOR),
                           json={"clientTurnId": str(uuid.uuid4()), "text": question})
        assert turn.status_code == 200, turn.text
        lines = [line for line in capsys.readouterr().err.splitlines() if line.startswith("[sql] POST")]
        chart_reads = [line for line in lines if "JOIN Assertion a ON a.ClinicalEntryId = e.Id" in line
                       and "v.PatientId = ?" in line]
        assert chart_reads, question
        assert all(line.endswith("LIMIT ?") for line in chart_reads), question
