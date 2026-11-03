"""Use cases: chat sessions of the Care Assistant (doc/api.md section 3.5)."""
from __future__ import annotations

from domain.access import Actor
from domain.errors import NotFound
from domain.views import Card, ChatSessionSummary, ChatSessionView, ChatTurnView, PatientView

from application.context import AppContext
from application.guard import deny, load_patient, require, subject_of
from application.paging import Page, PageRequest
from application.ports import ChatSessionRow, ChatTurnRow
from application.records import supersedes_for

SESSIONS_PATH = "/api/patients/{patient}/chat/sessions"
SESSION_PATH = "/api/chat/sessions/{session}"


def list_sessions(ctx: AppContext, actor: Actor, patient_id: int,
                  page: PageRequest = PageRequest()) -> Page[ChatSessionSummary]:
    """One page of the sessions of this user about this patient, newest first."""
    patient = load_patient(ctx, patient_id)
    require(ctx, actor, patient, "chat", "read", SESSIONS_PATH)
    return ctx.chat.sessions(actor, subject_of(patient), page)


def start_session(ctx: AppContext, actor: Actor, patient_id: int) -> ChatSessionView:
    patient = load_patient(ctx, patient_id)
    require(ctx, actor, patient, "chat", "create", SESSIONS_PATH)
    with ctx.uow.write() as now:
        ident = (ctx.identity.chat_session, ctx.chat.next_identifier(ctx.identity.chat_session, "CHAT-", 4))
        session_id = ctx.chat.create_session(ident, actor, subject_of(patient), now, ctx.chat_mode, ctx.chat_model)
        ctx.audit.add(now, "create", "Allowed", actor, subject_of(patient), SESSIONS_PATH)
    return session_view(ctx, actor, load_session(ctx, session_id))


def load_session(ctx: AppContext, session_id: int) -> ChatSessionRow:
    session = ctx.chat.session(session_id)
    if session is None:
        raise NotFound(f"Chat session {session_id} does not exist.")
    return session


def session_patient(ctx: AppContext, session: ChatSessionRow) -> PatientView:
    if session.patient_id is None:
        raise NotFound("The patient of the chat session does not exist.")
    return load_patient(ctx, session.patient_id)


def is_session_user(actor: Actor, session: ChatSessionRow) -> bool:
    return (session.user_role, session.user_system, session.user_value) == (actor.role, actor.system, actor.value)


def require_session_user(ctx: AppContext, actor: Actor, session: ChatSessionRow, patient: PatientView,
                         audit_action: str, path: str) -> None:
    if not is_session_user(actor, session):
        deny(ctx, actor, patient, audit_action, path,
             "This chat session belongs to another user. This attempt is in the audit log.")


def get_session(ctx: AppContext, actor: Actor, session_id: int) -> ChatSessionView:
    session = load_session(ctx, session_id)
    patient = session_patient(ctx, session)
    require_session_user(ctx, actor, session, patient, "read", SESSION_PATH)
    return session_view(ctx, actor, session)


def turn_views(ctx: AppContext, actor: Actor, rows: list[ChatTurnRow]) -> list[ChatTurnView]:
    """Build the turns. The cards come only from the Citation rows of each turn."""
    ids = sorted({aid for row in rows for aid, _ in row.citations})
    found = ctx.records.assertions_by_id(ids) if ids else {}
    views = []
    for row in rows:
        cards = [Card(rank=rank, assertion=found[aid], supersedes=supersedes_for(ctx, actor, found[aid]))
                 for aid, rank in sorted(row.citations, key=lambda c: c[1]) if aid in found]
        recorded = [c.assertion.id for c in cards] if row.kind == "tell" else []
        views.append(ChatTurnView(id=row.id, seq=row.seq, speaker=row.speaker, text=row.text,
                                  created_at=row.created_at, kind=row.kind if row.speaker == "Assistant" else None,
                                  cards=cards, recorded_ids=recorded))
    return views


def session_view(ctx: AppContext, actor: Actor, session: ChatSessionRow) -> ChatSessionView:
    return ChatSessionView(id=session.id, identifier=session.identifier, patient_id=session.patient_id,
                           started_at=session.started_at, mode=session.mode, model=session.model,
                           turns=turn_views(ctx, actor, ctx.chat.turns(session.id)))
