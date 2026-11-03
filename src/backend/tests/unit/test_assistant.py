"""The Care Assistant rules: ask or tell, the intents, the tool of the fake model and the fake fact extractor."""
from __future__ import annotations

import json

import pytest

from application.assistant.answers import HELP_TEXT
from application.assistant.intents import allergy_term, intent_of, kind_of
from application.assistant.rule_model import RuleModel, tool_for
from application.assistant.tools import ToolResult
from application.ports import ChatMessage, FinalText, ToolCalls
from infrastructure.llm.fake_client import LOCAL, FakeLanguageModel, extract


@pytest.mark.parametrize("text,kind", [
    ("Is she allergic to penicillin?", "ask"),
    ("Any allergies?", "ask"),
    ("What is my plan?", "ask"),
    ("Show the latest labs", "ask"),
    ("Tell me about the medications", "ask"),
    ("The patient's father died of a heart attack.", "tell"),
    ("I stopped taking metformin.", "tell"),
    ("Heart rate is 112.", "tell"),
])
def test_ask_or_tell(text, kind):
    assert kind_of(text) == kind


@pytest.mark.parametrize("text,intent", [
    ("Is she allergic to penicillin?", "allergy"),
    ("Any allergies?", "allergy"),
    ("What medications am I taking?", "medications"),
    ("What is my plan?", "plan"),
    ("What did the nurse recommend?", "recommendations"),
    ("Any lab results?", "labs"),
    ("What was the troponin?", "labs"),
    ("What are her vital signs?", "vitals"),
    ("What is the blood pressure?", "vitals"),
    ("What are the diagnoses?", "diagnoses"),
    ("Show the earlier visits", "visits"),
    ("What is the weather?", "unknown"),
])
def test_the_intent_of_a_question(text, intent):
    assert intent_of(text) == intent


def test_the_substance_of_an_allergy_question():
    assert allergy_term("Is she allergic to penicillin?") == "penicillin"
    assert allergy_term("Any peanut allergy?") == "peanut"
    assert allergy_term("Any allergies?") is None
    assert allergy_term("Does he have any known allergies?") is None


def test_the_fake_extractor_finds_the_family_history():
    facts = extract("The patient's father died of a heart attack.")
    assert len(facts) == 1
    fact = facts[0]
    assert (fact.category, fact.code, fact.code_system) == ("Observation", "family-history", LOCAL)
    assert fact.display == "Family history of heart attack (father)"
    assert fact.details["value"] == "Father died of a heart attack."
    assert fact.statement == "The patient's father died of a heart attack."


def test_the_fake_extractor_finds_allergies_and_vital_signs():
    allergy = extract("She is allergic to peanuts.")
    assert [(f.category, f.details["substance"]) for f in allergy] == [("Allergy", "Peanuts")]
    vitals = extract("Heart rate is 112 and blood pressure 150/95, SpO2 91%.")
    assert [(f.code, f.details["value"]) for f in vitals] == [("8867-4", "112"), ("85354-9", "150/95"),
                                                              ("2708-6", "91")]


@pytest.mark.parametrize("text", ["I stopped taking metformin.", "She is not allergic to penicillin.",
                                  "Thank you.", "The weather is cold."])
def test_the_fake_extractor_finds_no_fact(text):
    assert extract(text) == []


@pytest.mark.parametrize("text,call", [
    ("Is she allergic to penicillin?", ("get_allergies", {"substance": "penicillin"})),
    ("Any allergies?", ("get_allergies", {})),
    ("What medications am I taking?", ("get_medications", {})),
    ("What is my plan?", ("get_plan", {})),
    ("What did the nurse recommend?", ("get_recommendations", {"role": "Nurse"})),
    ("What do you recommend?", ("get_recommendations", {})),
    ("What was the troponin?", ("get_lab_results", {})),
    ("What is the blood pressure?", ("get_vital_signs", {})),
    ("What are the diagnoses?", ("get_diagnoses", {})),
    ("Show the earlier visits", ("get_visits", {})),
    ("What is the weather?", None),
])
def test_the_fake_model_maps_the_intent_to_one_tool_call(text, call):
    assert tool_for(text) == call


def test_the_fake_model_calls_one_tool_then_gives_the_text():
    model = FakeLanguageModel(RuleModel())
    question = [ChatMessage("system", "..."), ChatMessage("user", "Is she allergic to penicillin?")]
    step = model.next_step(question, [])
    assert isinstance(step, ToolCalls) and len(step.calls) == 1
    assert (step.calls[0].name, json.loads(step.calls[0].arguments)) == ("get_allergies", {"substance": "penicillin"})
    result = ToolResult(name="get_allergies", arguments={"substance": "penicillin"})
    answer = model.next_step([*question, ChatMessage("tool", "{}", result=result)], [])
    assert answer == FinalText("No penicillin allergy is recorded for this patient.")
    help_text = model.next_step([ChatMessage("user", "What is the weather?")], [])
    assert help_text == FinalText(HELP_TEXT)
    assert len(model.extract_facts("My mother has diabetes.", "Patient")) == 1
