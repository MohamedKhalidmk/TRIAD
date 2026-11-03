"""The fake language model (TRIAD_LLM=fake, the default). It needs no network.

- next_step: the rules of the application select one tool and write the answer from its result
  (application/assistant/rule_model.py). main.py gives these rules to the fake model.
- extract_facts: a small set of patterns finds facts in a "tell" turn: family history, an allergy,
  and vital signs. If no pattern matches, it finds no fact.
"""
from __future__ import annotations

import re
from typing import Protocol, Sequence

from application.ports import ChatMessage, ExtractedFact, FinalText, ToolCalls, ToolDefinition

LOINC = "http://loinc.org"
LOCAL = "https://triad.example/fhir/CodeSystem/local"

RELATIVES = ("father", "mother", "brother", "sister", "son", "daughter", "grandfather", "grandmother", "uncle",
             "aunt", "parent")
FAMILY = re.compile(
    r"\b(" + "|".join(RELATIVES) + r")\b[^.]*?\b(?:died of|died from|had|has|suffered from|suffers from|"
    r"passed away from)\s+(?:a |an |the )?([a-z][a-z' -]*?)\s*(?:\bat\b|\bwhen\b|\bin\b|[.,;!]|$)", re.I)
ALLERGY = re.compile(r"\b(?:is|am|are|was)?\s*allergic to\s+([a-z][a-z -]*?)\s*(?:[.,;!]|$)", re.I)
NEGATION = re.compile(r"\b(?:not|no|never)\b[^.]*\ballerg", re.I)
VITALS = (
    (re.compile(r"\bheart rate\s+(?:is\s+|of\s+|was\s+)?(\d{2,3})", re.I), "8867-4", "Heart rate", "/min"),
    (re.compile(r"\bblood pressure\s+(?:is\s+|of\s+|was\s+)?(\d{2,3}\s*/\s*\d{2,3})", re.I), "85354-9",
     "Blood pressure panel with all children optional", "mm[Hg]"),
    (re.compile(r"\b(?:oxygen saturation|spo2|o2 sat(?:uration)?)\s+(?:is\s+|of\s+|was\s+)?(\d{2,3})\s*%?", re.I),
     "2708-6", "Oxygen saturation in Arterial blood", "%"),
    (re.compile(r"\btemperature\s+(?:is\s+|of\s+|was\s+)?(\d{2}(?:\.\d)?)", re.I), "8310-5", "Body temperature",
     "Cel"),
)


def sentence(text: str) -> str:
    text = " ".join(text.split())
    return text if text.endswith((".", "!", "?")) else text + "."


def extract(text: str) -> list[ExtractedFact]:
    facts: list[ExtractedFact] = []
    statement = sentence(text.strip())
    for match in FAMILY.finditer(text):
        relative, condition = match.group(1).lower(), match.group(2).strip().lower()
        if not condition:
            continue
        value = sentence(match.group(0).strip(" .,;!").capitalize())
        facts.append(ExtractedFact(
            category="Observation", code="family-history", code_system=LOCAL,
            display=f"Family history of {condition} ({relative})", statement=statement,
            details={"value": value, "unit": None}))
    if not NEGATION.search(text):
        for match in ALLERGY.finditer(text):
            substance = match.group(1).strip()
            if substance:
                facts.append(ExtractedFact(
                    category="Allergy", code=f"allergy-{re.sub(r'[^a-z0-9]+', '-', substance.lower()).strip('-')}",
                    code_system=LOCAL, display=f"Allergy to {substance.lower()}", statement=statement,
                    details={"substance": substance.capitalize(), "clinicalStatus": "active"}))
    for pattern, code, display, unit in VITALS:
        match = pattern.search(text)
        if match:
            facts.append(ExtractedFact(category="Observation", code=code, code_system=LOINC, display=display,
                                       statement=statement,
                                       details={"value": re.sub(r"\s+", "", match.group(1)), "unit": unit}))
    return facts


class AskSteps(Protocol):
    def next_step(self, messages: Sequence[ChatMessage], tools: Sequence[ToolDefinition]) -> ToolCalls | FinalText:
        ...


class FakeLanguageModel:
    name = "fake"

    def __init__(self, ask_steps: AskSteps):
        self.ask_steps = ask_steps

    def next_step(self, messages: Sequence[ChatMessage], tools: Sequence[ToolDefinition]) -> ToolCalls | FinalText:
        return self.ask_steps.next_step(messages, tools)

    def extract_facts(self, text: str, speaker_role: str) -> list[ExtractedFact]:
        return extract(text)
