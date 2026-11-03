"""The chart, the chains and new records (doc/api.md section 3.4)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from api import schemas as s
from api.actor import get_actor, get_ctx
from api.paging import page_request
from application import records
from application.context import AppContext
from application.paging import PageRequest
from domain.access import Actor

router = APIRouter(prefix="/api", tags=["records"])


@router.get("/patients/{patient_id}/chart", response_model=s.Chart)
def chart(patient_id: int, visit_id: Optional[int] = Query(default=None, alias="visitId"),
          category: Optional[str] = None, history: bool = False, q: Optional[str] = None,
          page: PageRequest = Depends(page_request), ctx: AppContext = Depends(get_ctx),
          actor: Actor = Depends(get_actor)):
    return records.chart(ctx, actor, patient_id, visit_id, category, history, q, page)


@router.get("/assertions/{assertion_id}/chain", response_model=s.Chain)
def chain(assertion_id: int, page: PageRequest = Depends(page_request), ctx: AppContext = Depends(get_ctx),
          actor: Actor = Depends(get_actor)):
    return records.chain(ctx, actor, assertion_id, page)


def to_command(body: s.NewMessage) -> records.NewMessageCmd:
    return records.NewMessageCmd(
        patient_id=body.patient_id, text=body.text, visit_id=body.visit_id, channel=body.channel,
        assertions=[records.NewAssertionCmd(
            intent=a.intent, verification=a.verification, statement=a.statement, entry_id=a.entry_id,
            supersedes_id=a.supersedes_id,
            new_entry=records.NewEntryCmd(**a.new_entry.model_dump(by_alias=False)) if a.new_entry else None)
            for a in body.assertions])


@router.post("/messages", response_model=s.RecordResult, status_code=201)
def post_message(body: s.NewMessage, ctx: AppContext = Depends(get_ctx), actor: Actor = Depends(get_actor)):
    return records.post_message(ctx, actor, to_command(body))
