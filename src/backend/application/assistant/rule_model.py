"""The rules of the fake model for an "ask" turn. They are not a language model, and they need no network.

The fake model uses the same tools and the same SQL as the LLM. Only the step that selects the tool is rules:
- round 1: the keyword intent of the question (intents.py) gives one tool call with its arguments,
  for example "Is she allergic to penicillin?" gives get_allergies(substance="penicillin");
- round 2: a template of answers.py writes the text from the result of that call.
A question with no known intent gets the help text, with no tool call.

The rules read the server-side items of the tool result (ChatMessage.result) to fill the templates.
The final text has no reference, so the turn cites all items of the tool result.
"""
from __future__ import annotations

import json
from typing import Optional, Sequence

from application.assistant.answers import HELP_TEXT, answer_text
from application.assistant.intents import allergy_term, asks_about_nurse, intent_of
from application.assistant.tools import ToolResult
from application.ports import ChatMessage, FinalText, ToolCall, ToolCalls, ToolDefinition

# The tool of each intent, with no arguments. The allergy and recommendation intents can add one argument.
INTENT_TOOLS = {
    "allergy": "get_allergies", "medications": "get_medications", "plan": "get_plan", "labs": "get_lab_results",
    "vitals": "get_vital_signs", "diagnoses": "get_diagnoses", "visits": "get_visits",
    "recommendations": "get_recommendations",
}


def tool_for(question: str) -> Optional[tuple[str, dict]]:
    """The one tool call of a question (the name and the arguments), or None for an unknown intent."""
    intent = intent_of(question)
    if intent not in INTENT_TOOLS:
        return None
    arguments: dict = {}
    if intent == "allergy" and allergy_term(question):
        arguments["substance"] = allergy_term(question)
    if intent == "recommendations" and asks_about_nurse(question):
        arguments["role"] = "Nurse"
    return INTENT_TOOLS[intent], arguments


class RuleModel:
    """The "ask" step of the fake model (the next_step of the LanguageModel port)."""

    def next_step(self, messages: Sequence[ChatMessage], tools: Sequence[ToolDefinition]) -> ToolCalls | FinalText:
        results = [m.result for m in messages if m.role == "tool"]
        if results:
            result = results[-1]
            if not isinstance(result, ToolResult) or result.error:
                raise RuntimeError("The tool call of the fake model failed.")
            return FinalText(answer_text(result))
        question = next(m.content for m in messages if m.role == "user")
        call = tool_for(question)
        if call is None:
            return FinalText(HELP_TEXT)
        name, arguments = call
        return ToolCalls([ToolCall(call_id="fake-1", name=name, arguments=json.dumps(arguments))])
