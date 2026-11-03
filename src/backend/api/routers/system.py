"""System and users (doc/api.md section 3.1)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

from api import schemas as s
from api.actor import get_actor, get_ctx
from application import codes, users
from application.context import AppContext
from domain.access import Actor

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health", response_model=s.Health)
def health(ctx: AppContext = Depends(get_ctx)):
    return s.Health(status="ok", schema_version=ctx.schema_version, mode=ctx.chat_mode, now=ctx.uow.now(),
                    clock=ctx.clock_mode)


@router.get("/users", response_model=list[s.UserView])
def list_users(role: Optional[str] = None, q: Optional[str] = None, limit: int = 50,
               ctx: AppContext = Depends(get_ctx)):
    return users.list_users(ctx, role, q, limit)


@router.get("/users/{key}", response_model=s.UserView)
def get_user(key: str, ctx: AppContext = Depends(get_ctx)):
    return users.get_user(ctx, key)


@router.get("/me", response_model=s.UserView)
def me(ctx: AppContext = Depends(get_ctx), actor: Actor = Depends(get_actor)):
    return users.me(ctx, actor)


@router.get("/codes", response_model=list[s.CodePreset])
def code_presets(category: Optional[str] = None, actor: Actor = Depends(get_actor)):
    return codes.code_presets(actor, category)
