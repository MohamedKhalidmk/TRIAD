"""Use case: one turn of the Care Assistant (POST /api/chat/sessions/{id}/turns).

1. Store the user turn and commit. The clientTurnId makes the request idempotent.
2. Sort the turn into "ask" or "tell". Find the evidence and the text outside a transaction.
3. In one transaction: the assistant turn, its citations and its audit record.
   A "tell" also writes one message (Channel = Chat) with the new assertions (Source = Agent,
   Verification = Unconfirmed). The reply cites the new assertions: that is the trace from the turn to the record.
"""
from __future__ import annotations

from typing import Optional

from domain.access import Actor, record_intents
from domain.errors import Invalid
from domain.views import PatientView, TurnResult

from application.assistant.answers import answer_question
from application.assistant.intents import kind_of
from application.assistant.service import extract_facts, word_answer
from application.chat.sessions import load_session, require_session_user, session_patient, turn_views
from application.context import AppContext
from application.guard import require, subject_of
from application.records import (NewAssertionCmd, NewEntryCmd, PreparedAssertion, new_entry_row,
                                 visit_for_new_entries, write)

TURNS_PATH = "/api/chat/sessions/{session}/turns"
REPLY_SUFFIX = ":reply"


def post_turn(ctx: AppContext, actor: Actor, session_id: int, client_turn_id: str, text: str) -> TurnResult:
    client_turn_id, text = (client_turn_id or "").strip(), (text or "").strip()
    if not client_turn_id or not text:
        raise Invalid("The turn is not correct.", {"text": "Write a question or a fact.",
                                                   "clientTurnId": "Give a client turn id."})
    session = load_session(ctx, session_id)
    patient = session_patient(ctx, session)
    kind = kind_of(text)
    require_session_user(ctx, actor, session, patient, kind, TURNS_PATH)
    team = require(ctx, actor, patient, "chat" if kind == "ask" else "tell", kind, TURNS_PATH)

    user_turn = ctx.chat.turn_by_client_id(session_id, client_turn_id)
    if user_turn is not None:
        reply = ctx.chat.turn_by_client_id(session_id, client_turn_id + REPLY_SUFFIX)
        if reply is not None:
            return result(ctx, actor, session_id, user_turn.id, reply.id)
        kind = kind_of(user_turn.text)
        text = user_turn.text
    else:
        with ctx.uow.write() as now:
            ctx.chat.add_turn(session_id, client_turn_id, "User", text, now)
        user_turn = ctx.chat.turn_by_client_id(session_id, client_turn_id)

    if kind == "ask":
        reply_id = answer(ctx, actor, patient, session_id, client_turn_id, text)
    else:
        reply_id = tell(ctx, actor, patient, session_id, client_turn_id, text, team)
    return result(ctx, actor, session_id, user_turn.id, reply_id)


def result(ctx: AppContext, actor: Actor, session_id: int, user_id: int, reply_id: int) -> TurnResult:
    rows = {row.id: row for row in ctx.chat.turns(session_id) if row.id in (user_id, reply_id)}
    user_view, reply_view = turn_views(ctx, actor, [rows[user_id], rows[reply_id]])
    return TurnResult(user_turn=user_view, assistant_turn=reply_view)


def save_reply(ctx: AppContext, actor: Actor, patient: PatientView, session_id: int, client_turn_id: str,
               kind: str, text: str, cited: list[int], now: str) -> int:
    reply_id = ctx.chat.add_turn(session_id, client_turn_id + REPLY_SUFFIX, "Assistant", text, now)
    if cited:
        ctx.chat.add_citations(reply_id, cited)
    ctx.audit.add(now, kind, "Allowed", actor, subject_of(patient), TURNS_PATH, chat_turn_id=reply_id)
    return reply_id


def answer(ctx: AppContext, actor: Actor, patient: PatientView, session_id: int, client_turn_id: str,
           question: str) -> int:
    found = answer_question(ctx, actor, patient, question)
    audience = "patient" if actor.is_patient else "clinician"
    text = word_answer(ctx, question, found, audience)
    with ctx.uow.write() as now:
        return save_reply(ctx, actor, patient, session_id, client_turn_id, "ask", text,
                          [a.id for a in found.evidence], now)


def tell(ctx: AppContext, actor: Actor, patient: PatientView, session_id: int, client_turn_id: str, text: str,
         team: bool) -> int:
    facts = extract_facts(ctx, text, actor.role)
    prepared: list[PreparedAssertion] = []
    labels: list[str] = []
    for fact in facts:
        cmd = NewAssertionCmd(intent="Report", verification="Unconfirmed", statement=fact.statement or text,
                              new_entry=NewEntryCmd(category=fact.category, code=fact.code,
                                                    code_system=fact.code_system, display=fact.display,
                                                    details=dict(fact.details)))
        try:
            row, medication, dates = new_entry_row(cmd.new_entry, cmd.statement)
        except Invalid:
            continue                       # a fact that is not correct is not recorded
        prepared.append(PreparedAssertion(cmd, None, row, medication, dates))
        labels.append(fact.display)
    reply: Optional[str] = None
    visit_id, needs_visit = None, False
    if not prepared:
        reply = "I found no fact to record. I did not save anything."
    elif "Report" not in record_intents(actor.role, actor.is_self(patient.id), team):
        reply = "Your role cannot record a report for this patient. I did not save anything."
    else:
        try:
            visit_id, needs_visit = visit_for_new_entries(ctx, actor, patient, None)
        except Invalid:
            reply = "The patient has no open visit. Check in a visit first. I did not save anything."
    with ctx.uow.write() as now:
        cited: list[int] = []
        if reply is None:
            _, cited = write(ctx, actor, patient, prepared, visit_id, needs_visit, "Chat", text, "Agent", now)
            reply = recorded_text(actor, labels)
        return save_reply(ctx, actor, patient, session_id, client_turn_id, "tell", reply, cited, now)


def recorded_text(actor: Actor, labels: list[str]) -> str:
    count = "1 new item" if len(labels) == 1 else f"{len(labels)} new items"
    items = "; ".join(labels)
    review = "Your care team must review it." if actor.is_patient else "A clinician must confirm it."
    if len(labels) > 1:
        review = review.replace("it.", "them.")
    return f"I recorded {count} as unconfirmed: {items}. {review}"

