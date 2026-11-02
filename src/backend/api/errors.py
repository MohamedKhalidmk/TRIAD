"""Error mapping: each error has the body { code, message, fields? } (doc/api.md section 1.2)."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from domain.errors import Conflict, DomainError, Forbidden, Invalid, NotFound, NoUser

STATUS = {NoUser: 401, Forbidden: 403, NotFound: 404, Conflict: 409, Invalid: 422}
CODE_OF_STATUS = {401: "no_user", 403: "forbidden", 404: "not_found", 409: "conflict"}


def body(code: str, message: str, fields: dict | None = None) -> dict:
    out = {"code": code, "message": message}
    if fields:
        out["fields"] = fields
    return out


def field_name(loc: tuple) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header")]
    name = ""
    for part in parts:
        name += f"[{part}]" if part.isdigit() else (f".{part}" if name else part)
    return name or "body"


def install(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    def domain_error(request: Request, error: DomainError) -> JSONResponse:
        status = next((s for cls, s in STATUS.items() if isinstance(error, cls)), 422)
        return JSONResponse(body(error.code, error.message, error.fields), status_code=status)

    @app.exception_handler(RequestValidationError)
    def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        fields = {}
        for item in error.errors():
            fields.setdefault(field_name(tuple(item.get("loc", ()))), item.get("msg", "This value is not correct."))
        return JSONResponse(body("validation", "The input is not correct.", fields), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    def http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        code = CODE_OF_STATUS.get(error.status_code, "validation")
        message = "The page or the row does not exist." if error.status_code == 404 else str(error.detail)
        return JSONResponse(body(code, message), status_code=error.status_code)
