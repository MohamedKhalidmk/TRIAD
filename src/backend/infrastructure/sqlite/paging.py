"""One page of a list query (doc/api.md section 1.5): a COUNT(*) query and a LIMIT/OFFSET query.

Each list method of a repository uses `fetch_page`. Both queries use the same FROM and WHERE text and the same
parameters, so `total` counts the rows of all pages with the same filters.
"""
from __future__ import annotations

import sqlite3
from typing import Callable, Sequence, TypeVar

from application.paging import Page, PageRequest

T = TypeVar("T")


def where(clauses: Sequence[str]) -> str:
    """The WHERE clause of the conditions, or no text if there is no condition."""
    return " WHERE " + " AND ".join(clauses) if clauses else ""


def each_row(view: Callable[[sqlite3.Row], T]) -> Callable[[list[sqlite3.Row]], list[T]]:
    """A `build` function that makes one view from each row."""
    return lambda rows: [view(r) for r in rows]


def fetch_page(conn: sqlite3.Connection, columns: str, source: str, args: Sequence, order_by: str,
               page: PageRequest, build: Callable[[list[sqlite3.Row]], list[T]],
               order_args: Sequence = ()) -> Page[T]:
    """Run the two queries of one page and make the views of its rows.

    - `source`: the FROM clause, the joins and the WHERE clause. `args` are its parameters.
    - `order_by`: the order of the list. It must end with the Id of the table, so the order is stable
      (a row cannot show on two pages, and no row is missed). `order_args` are its parameters.
    - `build`: makes the views from the rows of the page (one call for all rows of the page).
    """
    total = conn.execute(f"SELECT COUNT(*) {source}", tuple(args)).fetchone()[0]
    rows = conn.execute(f"SELECT {columns} {source} ORDER BY {order_by} LIMIT ? OFFSET ?",
                        (*args, *order_args, page.limit, page.offset)).fetchall()
    return Page(items=build(rows), total=total, limit=page.limit, offset=page.offset)
