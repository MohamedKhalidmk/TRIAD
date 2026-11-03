"""Request dependencies: the context of the request and the current user (header X-Triad-User).

The composition root gives the context factory (app.state.open_context). The API layer does not know the adapters.
"""
from __future__ import annotations

from typing import Iterator, Optional

from fastapi import Depends, Header, Request

from application.context import AppContext
from application.users import resolve_actor
from domain.access import Actor


def get_ctx(request: Request) -> Iterator[AppContext]:
    ctx = request.app.state.open_context()
    try:
        yield ctx
    finally:
        ctx.close()


def get_actor(ctx: AppContext = Depends(get_ctx),
              x_triad_user: Optional[str] = Header(default=None, alias="X-Triad-User")) -> Actor:
    return resolve_actor(ctx, x_triad_user)
