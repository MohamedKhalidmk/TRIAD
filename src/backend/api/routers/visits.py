"""Visits and care teams (doc/api.md section 3.3)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from api import schemas as s
from api.actor import get_actor, get_ctx
from application import visits
from application.context import AppContext
from domain.access import Actor

router = APIRouter(prefix="/api", tags=["visits"])


@router.get("/patients/{patient_id}/visits", response_model=list[s.Visit])
def list_visits(patient_id: int, ctx: AppContext = Depends(get_ctx), actor: Actor = Depends(get_actor)):
    return visits.list_visits(ctx, actor, patient_id)


@router.post("/patients/{patient_id}/visits", response_model=s.Visit, status_code=201)
def check_in(patient_id: int, body: s.VisitCreate, ctx: AppContext = Depends(get_ctx),
             actor: Actor = Depends(get_actor)):
    return visits.check_in(ctx, actor, patient_id, body.visit_class, body.reason, body.type, body.location_id)


@router.post("/visits/{visit_id}/locations", response_model=s.Visit)
def move(visit_id: int, body: s.LocationMove, ctx: AppContext = Depends(get_ctx), actor: Actor = Depends(get_actor)):
    return visits.move(ctx, actor, visit_id, body.location_id)


@router.post("/visits/{visit_id}/end", response_model=s.Visit)
def end(visit_id: int, ctx: AppContext = Depends(get_ctx), actor: Actor = Depends(get_actor)):
    return visits.end(ctx, actor, visit_id)


@router.get("/visits/{visit_id}/care-team", response_model=s.CareTeam)
def get_care_team(visit_id: int, ctx: AppContext = Depends(get_ctx), actor: Actor = Depends(get_actor)):
    return visits.get_care_team(ctx, actor, visit_id)


@router.put("/visits/{visit_id}/care-team", response_model=s.CareTeam)
def set_care_team(visit_id: int, body: s.CareTeamPut, ctx: AppContext = Depends(get_ctx),
                  actor: Actor = Depends(get_actor)):
    return visits.set_care_team(ctx, actor, visit_id, [m.model_dump(by_alias=False) for m in body.members], body.name)
