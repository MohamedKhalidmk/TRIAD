"""The language model step of the Care Assistant, with the fallback to the fake model.

The rules always select the evidence. The language model only words the answer from the cited
statements, and it extracts facts from a "tell" turn. If the model fails, the fake model does the turn.
"""
from __future__ import annotations

from application.assistant.answers import Answer
from application.context import AppContext
from application.ports import ExtractedFact


def word_answer(ctx: AppContext, question: str, answer: Answer, audience: str) -> str:
    """The final text of an answer. With no evidence, the draft stays (the model cannot add facts)."""
    if answer.evidence:
        try:
            text = ctx.llm.word_answer(question, answer.text, answer.evidence, audience)
            if text and text.strip():
                return text.strip()
        except Exception:  # noqa: BLE001 - any failure of the model gives the fake answer
            pass
    return ctx.fallback_llm.word_answer(question, answer.text, answer.evidence, audience)


def extract_facts(ctx: AppContext, text: str, speaker_role: str) -> list[ExtractedFact]:
    try:
        return list(ctx.llm.extract_facts(text, speaker_role))
    except Exception:  # noqa: BLE001
        return list(ctx.fallback_llm.extract_facts(text, speaker_role))
