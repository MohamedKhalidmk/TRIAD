"""The directory: departments, locations, staff and medications (doc/api.md section 3.7)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Response

from api import schemas as s
from api.actor import get_actor, get_ctx
from api.paging import page_request
from application import directory as d
from application.context import AppContext
from application.paging import PageRequest
from domain.access import Actor

router = APIRouter(prefix="/api", tags=["directory"])


def given(body) -> dict:
    """The fields that the request gives, in snake_case."""
    return body.model_dump(by_alias=False, exclude_unset=True)


# ----- departments -----

@router.get("/departments", response_model=s.Page[s.Department])
def departments(q: Optional[str] = None, page: PageRequest = Depends(page_request),
                ctx: AppContext = Depends(get_ctx), actor: Actor = Depends(get_actor)):
    return d.departments(ctx, actor, q, page)


@router.post("/departments", response_model=s.Department, status_code=201)
def create_department(body: s.DepartmentIn, ctx: AppContext = Depends(get_ctx), actor: Actor = Depends(get_actor)):
    return d.create_department(ctx, actor, given(body))


@router.patch("/departments/{department_id}", response_model=s.Department)
def change_department(department_id: int, body: s.DepartmentIn, ctx: AppContext = Depends(get_ctx),
                      actor: Actor = Depends(get_actor)):
    return d.change_department(ctx, actor, department_id, given(body))


@router.delete("/departments/{department_id}", status_code=204)
def delete_department(department_id: int, ctx: AppContext = Depends(get_ctx), actor: Actor = Depends(get_actor)):
    d.delete_department(ctx, actor, department_id)
    return Response(status_code=204)


# ----- locations -----

@router.get("/locations", response_model=s.Page[s.Location])
def locations(department: Optional[str] = None, q: Optional[str] = None, page: PageRequest = Depends(page_request),
              ctx: AppContext = Depends(get_ctx), actor: Actor = Depends(get_actor)):
    return d.locations(ctx, actor, department, q, page)


@router.post("/locations", response_model=s.Location, status_code=201)
def create_location(body: s.LocationIn, ctx: AppContext = Depends(get_ctx), actor: Actor = Depends(get_actor)):
    return d.create_location(ctx, actor, given(body))


@router.patch("/locations/{location_id}", response_model=s.Location)
def change_location(location_id: int, body: s.LocationIn, ctx: AppContext = Depends(get_ctx),
                    actor: Actor = Depends(get_actor)):
    return d.change_location(ctx, actor, location_id, given(body))


@router.delete("/locations/{location_id}", status_code=204)
def delete_location(location_id: int, ctx: AppContext = Depends(get_ctx), actor: Actor = Depends(get_actor)):
    d.delete_location(ctx, actor, location_id)
    return Response(status_code=204)


# ----- staff -----

@router.get("/staff", response_model=s.Page[s.Staff])
def staff_list(role: Optional[str] = None, department: Optional[str] = None, q: Optional[str] = None,
               page: PageRequest = Depends(page_request), ctx: AppContext = Depends(get_ctx),
               actor: Actor = Depends(get_actor)):
    return d.staff_list(ctx, actor, role, department, q, page)


@router.post("/staff", response_model=s.Staff, status_code=201)
def create_staff(body: s.StaffCreate, ctx: AppContext = Depends(get_ctx), actor: Actor = Depends(get_actor)):
    return d.create_staff(ctx, actor, given(body))


@router.patch("/staff/{staff_id}", response_model=s.Staff)
def change_staff(staff_id: int, body: s.StaffPatch, ctx: AppContext = Depends(get_ctx),
                 actor: Actor = Depends(get_actor)):
    return d.change_staff(ctx, actor, staff_id, given(body))


@router.delete("/staff/{staff_id}", status_code=204)
def delete_staff(staff_id: int, ctx: AppContext = Depends(get_ctx), actor: Actor = Depends(get_actor)):
    d.delete_staff(ctx, actor, staff_id)
    return Response(status_code=204)


# ----- medications -----

@router.get("/medications", response_model=s.Page[s.Medication])
def medications(q: Optional[str] = None, page: PageRequest = Depends(page_request),
                ctx: AppContext = Depends(get_ctx), actor: Actor = Depends(get_actor)):
    return d.medications(ctx, actor, q, page)


@router.post("/medications", response_model=s.Medication, status_code=201)
def create_medication(body: s.MedicationIn, ctx: AppContext = Depends(get_ctx), actor: Actor = Depends(get_actor)):
    return d.create_medication(ctx, actor, given(body))


@router.patch("/medications/{medication_id}", response_model=s.Medication)
def change_medication(medication_id: int, body: s.MedicationIn, ctx: AppContext = Depends(get_ctx),
                      actor: Actor = Depends(get_actor)):
    return d.change_medication(ctx, actor, medication_id, given(body))


@router.delete("/medications/{medication_id}", status_code=204)
def delete_medication(medication_id: int, ctx: AppContext = Depends(get_ctx), actor: Actor = Depends(get_actor)):
    d.delete_medication(ctx, actor, medication_id)
    return Response(status_code=204)
