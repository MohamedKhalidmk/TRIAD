"""The Care Assistant (doc/api.md section 3.5) and the audit log (section 3.6)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from api import schemas as s
from api.actor import get_actor, get_ctx
from api.paging import page_request
from application import audit
from application.chat import sessions, turns
from application.context import AppContext
from application.paging import PageRequest
from domain.access import Actor

router = APIRouter(prefix="/api", tags=["chat"])


@router.get("/patients/{patient_id}/chat/sessions", response_model=s.Page[s.ChatSessionSummary])
def list_sessions(patient_id: int, page: PageRequest = Depends(page_request), ctx: AppContext = Depends(get_ctx),
                  actor: Actor = Depends(get_actor)):
    return sessions.list_sessions(ctx, actor, patient_id, page)


@router.post("/patients/{patient_id}/chat/sessions", response_model=s.ChatSession, status_code=201)
def start_session(patient_id: int, ctx: AppContext = Depends(get_ctx), actor: Actor = Depends(get_actor)):
    return sessions.start_session(ctx, actor, patient_id)


@router.get("/chat/sessions/{session_id}", response_model=s.ChatSession)
def get_session(session_id: int, ctx: AppContext = Depends(get_ctx), actor: Actor = Depends(get_actor)):
    return sessions.get_session(ctx, actor, session_id)


@router.post("/chat/sessions/{session_id}/turns", response_model=s.TurnResult)
def post_turn(session_id: int, body: s.TurnIn, ctx: AppContext = Depends(get_ctx),
              actor: Actor = Depends(get_actor)):
    return turns.post_turn(ctx, actor, session_id, body.client_turn_id, body.text)


@router.get("/patients/{patient_id}/audit", response_model=s.AuditPage, tags=["audit"])
def patient_audit(patient_id: int, page: PageRequest = Depends(page_request), ctx: AppContext = Depends(get_ctx),
                  actor: Actor = Depends(get_actor)):
    return audit.patient_audit(ctx, actor, patient_id, page)
