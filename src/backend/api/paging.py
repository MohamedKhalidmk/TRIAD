"""The page parameters of each list endpoint (doc/api.md section 1.5).

A value out of range, or a value that is not an integer, gives 422 `validation` with `fields.limit` or
`fields.offset` (the RequestValidationError handler of api/errors.py).
"""
from __future__ import annotations

from fastapi import Query

from application.paging import DEFAULT_LIMIT, MAX_LIMIT, PageRequest


def page_request(limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT,
                                    description=f"The number of rows of the page (1 to {MAX_LIMIT})."),
                 offset: int = Query(default=0, ge=0,
                                     description="The number of rows before the page (0 or more).")) -> PageRequest:
    return PageRequest(limit=limit, offset=offset)
