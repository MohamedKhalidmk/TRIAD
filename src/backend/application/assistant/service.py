"""The language model steps of the Care Assistant, with the fallback to the fake model.

- answer: an "ask" turn. The loop of agent.py runs with the model of the chat mode. The model selects the
  tools, and the tools do the lookups. If the model fails, the fake model does the turn again with the same tools.
- extract_facts: a "tell" turn. The model extracts the facts. If it fails, the fake patterns extract them.

Each failure gives one warning line in the log. The line names only the error class, because the text
of a provider error can contain a part of the API key.
"""
from __future__ import annotations

import logging

from domain.access import Actor
from domain.views import PatientView

from application.assistant import agent
from application.context import AppContext
from application.ports import ExtractedFact

log = logging.getLogger("triad.chat")


def _warn(step: str, error: Exception) -> None:
    log.warning("The language model failed to %s (%s). This turn uses the fake model.", step, type(error).__name__)


def answer(ctx: AppContext, actor: Actor, patient: PatientView, question: str) -> agent.Reply:
    """The text and the cited assertions of an "ask" turn."""
    if ctx.llm is not ctx.fallback_llm:
        try:
            return agent.run(ctx, ctx.llm, actor, patient, question)
        except Exception as error:  # noqa: BLE001 - any failure of the model gives the fake answer
            _warn("answer the question", error)
    return agent.run(ctx, ctx.fallback_llm, actor, patient, question)


def extract_facts(ctx: AppContext, text: str, speaker_role: str) -> list[ExtractedFact]:
    try:
        return list(ctx.llm.extract_facts(text, speaker_role))
    except Exception as error:  # noqa: BLE001
        _warn("extract the facts", error)
        return list(ctx.fallback_llm.extract_facts(text, speaker_role))
