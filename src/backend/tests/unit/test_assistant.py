"""The Care Assistant rules: ask or tell, the intents, and the fake fact extractor."""
from __future__ import annotations

import pytest

from application.assistant.intents import allergy_term, intent_of, kind_of
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


def test_the_fake_model_keeps_the_rule_draft():
    model = FakeLanguageModel()
    assert model.word_answer("q?", "The draft.", [], "clinician") == "The draft."
    assert len(model.extract_facts("My mother has diabetes.", "Patient")) == 1
