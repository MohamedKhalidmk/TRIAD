"""Patients (doc/api.md section 3.2)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Response

from api import schemas as s
from api.actor import get_actor, get_ctx
from api.paging import page_request
from application import patients
from application.context import AppContext
from application.paging import PageRequest
from domain.access import Actor

router = APIRouter(prefix="/api/patients", tags=["patients"])


@router.get("", response_model=s.Page[s.PatientSummary])
def search(q: Optional[str] = None, dob: Optional[str] = None, scope: str = "all",
           page: PageRequest = Depends(page_request), ctx: AppContext = Depends(get_ctx),
           actor: Actor = Depends(get_actor)):
    return patients.search(ctx, actor, q, dob, scope, page)


@router.post("", response_model=s.Patient, status_code=201)
def register(body: s.PatientCreate, ctx: AppContext = Depends(get_ctx), actor: Actor = Depends(get_actor)):
    address = body.address.model_dump(by_alias=False) if body.address else None
    return patients.register(ctx, actor, body.name, body.date_of_birth, body.sex, body.phone_number, address)


@router.get("/{patient_id}", response_model=s.Patient)
def get(patient_id: int, ctx: AppContext = Depends(get_ctx), actor: Actor = Depends(get_actor)):
    return patients.get(ctx, actor, patient_id)


@router.patch("/{patient_id}", response_model=s.Patient)
def change(patient_id: int, body: s.PatientPatch, ctx: AppContext = Depends(get_ctx),
           actor: Actor = Depends(get_actor)):
    return patients.change(ctx, actor, patient_id, body.model_dump(by_alias=False, exclude_unset=True))


@router.delete("/{patient_id}", status_code=204)
def delete(patient_id: int, ctx: AppContext = Depends(get_ctx), actor: Actor = Depends(get_actor)):
    patients.delete(ctx, actor, patient_id)
    return Response(status_code=204)
