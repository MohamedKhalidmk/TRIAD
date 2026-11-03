"""Pages of a list (doc/api.md section 1.5): the request (limit, offset) and the page that a use case gives.

The API checks the range of `limit` and `offset`. The repositories run the page in SQL (LIMIT ? OFFSET ?).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Sequence, TypeVar

T = TypeVar("T")

DEFAULT_LIMIT = 25
MAX_LIMIT = 200


@dataclass(frozen=True)
class PageRequest:
    """The rows offset + 1 to offset + limit of a list."""
    limit: int = DEFAULT_LIMIT
    offset: int = 0

    def __post_init__(self) -> None:
        if self.limit < 1 or self.offset < 0:
            raise ValueError("A page needs limit >= 1 and offset >= 0.")


@dataclass
class Page(Generic[T]):
    """One page of a list. `total` is the number of rows that match the filters, on all pages."""
    items: list[T]
    total: int
    limit: int
    offset: int


def page_of(rows: Sequence[T], page: PageRequest) -> Page[T]:
    """A page of a short list that is in memory already (for example, the own record of a patient)."""
    return Page(items=list(rows[page.offset:page.offset + page.limit]), total=len(rows), limit=page.limit,
                offset=page.offset)
