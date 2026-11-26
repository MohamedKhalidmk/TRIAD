"""One page of a list query (doc/api.md section 1.5) on the knowledge graph: a COUNT query and a LIMIT/OFFSET query.

The SPARQL form of infrastructure/sqlite/paging.py. Both queries use the same WHERE text and the same bindings, so
`total` counts the rows of all pages with the same filters.

The order must be total: its last condition is the integer id of the IRI (fragments.id_order). The text of an IRI
is not a correct order ("/10" sorts before "/9"), and the data has many ties (6,701 on the patient and the time of
an assertion), so without the id a row could show on two pages. fetch_page refuses an order that does not end
with an id. LIMIT and OFFSET are integers in the text (a typed literal is not valid there).

Virtuoso fails (HTTP 500, SR353) when OFFSET + LIMIT is above MaxSortedTopRows (kg.sh sets 100,000).
"""
from __future__ import annotations

import re
from typing import Any, Callable, Mapping, Optional, Sequence, TypeVar

from application.paging import Page, PageRequest
from infrastructure.rdf.namespaces import KG

T = TypeVar("T")

_ID = (r"xsd:integer\(STRAFTER\(STR\([?$][A-Za-z_][A-Za-z0-9_]*\), \"" + re.escape(KG)
       + r"[a-z][a-z-]*/\"\)\)")
_ID_ORDER = re.compile(r"(?:(?:ASC|DESC)\()?" + _ID + r"\)?")
_VARIABLE_ORDER = re.compile(r"(?:(?:ASC|DESC)\()?(\?[A-Za-z_][A-Za-z0-9_]*)\)?")


def ends_with_id(order_by: Sequence[str], where: str = "") -> bool:
    """True if the last condition is the integer id of an IRI: fragments.id_order(...), or a variable that a
    BIND of fragments.bind_id(...) gives in `where` (in each branch of a UNION)."""
    if not order_by:
        return False
    last = order_by[-1].strip()
    if _ID_ORDER.fullmatch(last):
        return True
    match = _VARIABLE_ORDER.fullmatch(last)
    return bool(match) and re.search(r"BIND \(" + _ID + r" AS " + re.escape(match.group(1)) + r"\)", where) is not None


def each_row(view: Callable[[dict], T]) -> Callable[[list[dict]], list[T]]:
    """A `build` function that makes one view from each row."""
    return lambda rows: [view(r) for r in rows]


def count_query(where: str, count: str = "*") -> str:
    return f"SELECT (COUNT({count}) AS ?total) FROM $abox WHERE {{{where}\n}}"


def page_query(select: str, where: str, order_by: Sequence[str], page: PageRequest) -> str:
    return (f"SELECT {select} FROM $abox WHERE {{{where}\n}}\nORDER BY {' '.join(order_by)}\n"
            f"LIMIT {int(page.limit)} OFFSET {int(page.offset)}")


def fetch_page(client: Any, select: str, where: str, bindings: Optional[Mapping[str, Any]],
               order_by: Sequence[str], page: PageRequest, build: Callable[[list[dict]], list[T]],
               count: str = "*") -> Page[T]:
    """Run the two queries of one page and make the views of its rows.

    - `select`: the projection, for example "?a ?name" (or "DISTINCT ?a ?name").
    - `where`: the group pattern (the text between the braces of WHERE). `bindings` are its values.
    - `order_by`: the ORDER BY conditions. The last one must be fragments.id_order(...) (or DESC() of it).
    - `build`: makes the views from the rows of the page (one call for all rows of the page).
    - `count`: the argument of COUNT, for example "DISTINCT ?a" when the pattern can give a row two times.
    """
    if not ends_with_id(order_by, where):
        raise ValueError("The order of a page must end with the integer id of the IRI (fragments.id_order).")
    rows = client.select(count_query(where, count), bindings)
    total = int(rows[0]["total"]) if rows and rows[0].get("total") is not None else 0
    page_rows = client.select(page_query(select, where, order_by, page), bindings) if page.offset < total else []
    return Page(items=build(page_rows), total=total, limit=page.limit, offset=page.offset)
