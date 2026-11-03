"""The loop of an "ask" turn. The same loop runs for the fake model and for the LLM.

1. Give the question and the tool definitions (the name, the description and the JSON Schema) to the model.
2. The model gives tool calls (a name and JSON arguments) or the final text.
3. For each call, the ToolBox checks the name and the arguments against the schema, runs the bound tool
   and gives back the result. A call that is not correct (an unknown tool, an extra parameter such as
   patientId, a wrong type, a bad enum value) gets an error text, and no query runs.
4. At most 4 rounds. If the model gives no final text in 4 rounds, the turn fails (service.py then uses the
   fake model).

The citations: the model writes a reference such as [E1] after each fact. The server keeps only the
references of this turn, removes them from the text and cites their assertions in the order of the first
mention. An unknown reference is dropped. If the text names no reference of this turn, the turn cites the
items that the tools gave (at most 12).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from domain.access import Actor
from domain.views import AssertionView, PatientView

from application.assistant.tools import MAX_ITEMS, ToolBox, make_tools
from application.context import AppContext
from application.ports import ChatMessage, FinalText, LanguageModel

MAX_ROUNDS = 4

SYSTEM_PROMPT = (
    "You are the TRIAD Care Assistant in a hospital prototype with synthetic data. "
    "You answer one question of {audience} about the patient of this chat. "
    "Use the tools to find the facts in the record. The tools know the patient and the user, so they have no "
    "parameter for a patient, a user or an id. "
    "Use only the facts that the tools give. Do not add a fact, a number, a date or advice that is not in a "
    "tool result. If a tool gives an error, correct the call. "
    "Each item of a tool result has a reference, for example E1. After each fact that you use, write the "
    "reference of its item in square brackets, for example: A physician ruled it out on 2026-10-02 [E1]. "
    "If the tools give no item for the question, say that the record has no such item. "
    "Use short, clear sentences. Write plain text. For many items, write one line for each item."
)
AUDIENCE = {True: "the patient (write to the patient as \"you\")", False: "a clinician"}

# A reference such as [E1], or a group such as [E1, E2]. The spaces before it go too.
REFERENCE = re.compile(r"[ \t]*\[\s*(E\d+(?:\s*[,;]\s*E\d+)*)\s*\]", re.I)


class NoAnswer(RuntimeError):
    """The model gave no usable final text."""


@dataclass
class Reply:
    text: str
    cited: list[AssertionView]          # in the order of the rank


def system_prompt(actor: Actor) -> str:
    return SYSTEM_PROMPT.format(audience=AUDIENCE[actor.is_patient])


def cite(box: ToolBox, text: str) -> Reply:
    """Remove the references from the text, and cite the assertions of the known references."""
    named: list[str] = []

    def drop(match: re.Match) -> str:
        for ref in re.findall(r"E\d+", match.group(1).upper()):
            if ref in box.refs and ref not in named:
                named.append(ref)
        return ""

    if REFERENCE.search(text):
        text = REFERENCE.sub(drop, text).strip()
    if not text.strip():
        raise NoAnswer("The final text has no words.")
    cited = [box.refs[ref] for ref in named] if named else list(box.refs.values())[:MAX_ITEMS]
    return Reply(text=text, cited=cited)


def run(ctx: AppContext, model: LanguageModel, actor: Actor, patient: PatientView, question: str) -> Reply:
    """One "ask" turn with `model`. Each error of the model goes to the caller."""
    box = make_tools(ctx, actor, patient)
    messages = [ChatMessage("system", system_prompt(actor)), ChatMessage("user", question)]
    for _ in range(MAX_ROUNDS):
        step = model.next_step(messages, box.definitions)
        if isinstance(step, FinalText):
            return cite(box, step.text)
        if not step.calls:
            raise NoAnswer("The model gave no tool call and no final text.")
        messages.append(ChatMessage("assistant", step.text, tool_calls=tuple(step.calls)))
        for call in step.calls:
            result = box.run(call)
            messages.append(ChatMessage("tool", result.content, tool_call_id=call.call_id, name=call.name,
                                        result=result))
    raise NoAnswer(f"The model gave no final text in {MAX_ROUNDS} rounds.")
