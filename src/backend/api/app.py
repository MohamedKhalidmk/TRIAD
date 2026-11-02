"""The FastAPI application: the routers, the error mapping and the built frontend (an SPA).

`build_app` gets a function that opens the context of one request. Only main.py knows the adapters.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse

from api import errors
from api.routers import chat, directory, patients, records, system, visits
from application.context import AppContext
from domain.errors import NotFound


def build_app(open_context: Callable[[], AppContext], frontend_dist: Optional[Path] = None) -> FastAPI:
    app = FastAPI(title="TRIAD API", version="1.0",
                  description="The API of the TRIAD prototype. The contract is doc/api.md.")
    app.state.open_context = open_context
    errors.install(app)
    for module in (system, patients, visits, records, chat, directory):
        app.include_router(module.router)
    if frontend_dist and (frontend_dist / "index.html").is_file():
        mount_spa(app, frontend_dist.resolve())
    return app


def mount_spa(app: FastAPI, dist: Path) -> None:
    """Serve the files of the built frontend. Each other path that does not start with /api gets index.html."""
    index = dist / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path == "api" or path.startswith("api/"):
            raise NotFound("The page or the row does not exist.")
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and dist in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)
