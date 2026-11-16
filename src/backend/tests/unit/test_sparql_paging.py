"""The pages of a SPARQL list (infrastructure/sparql/paging.py): the same WHERE for COUNT and the page, a total
order that ends with the integer id, and LIMIT/OFFSET as integers."""
from __future__ import annotations

import pytest

from application.paging import PageRequest
from infrastructure.sparql import fragments, paging


class FakeClient:
    def __init__(self, total: int):
        self.total = total
        self.queries = []

    def select(self, template, bindings=None, *, raw=False):
        self.queries.append((template, dict(bindings or {})))
        if "COUNT(" in template:
            return [{"total": self.total}]
        return [{"a": i} for i in range(3)]


WHERE = "\n  ?a triad:name $name ."
ORDER = ["LCASE(?name)", fragments.id_order("?a", "assertion")]


def test_the_count_and_the_page_use_the_same_where_and_bindings():
    client = FakeClient(total=40)
    page = paging.fetch_page(client, "?a ?name", WHERE, {"name": "x"}, ORDER, PageRequest(3, 6),
                             paging.each_row(lambda r: r["a"]))
    assert (page.items, page.total, page.limit, page.offset) == ([0, 1, 2], 40, 3, 6)
    (count, count_bindings), (rows, row_bindings) = client.queries
    assert count.startswith("SELECT (COUNT(*) AS ?total) FROM $abox WHERE {") and WHERE in count
    assert rows.startswith("SELECT ?a ?name FROM $abox WHERE {") and WHERE in rows
    assert rows.endswith("LIMIT 3 OFFSET 6") and count_bindings == row_bindings == {"name": "x"}
    assert f"ORDER BY LCASE(?name) {ORDER[1]}" in rows


def test_an_offset_after_the_end_gives_no_items_and_the_total():
    client = FakeClient(total=5)
    page = paging.fetch_page(client, "?a", WHERE, {}, ORDER, PageRequest(3, 5), paging.each_row(lambda r: r["a"]))
    assert (page.items, page.total) == ([], 5) and len(client.queries) == 1


def test_the_order_must_end_with_the_integer_id():
    for order in (["?name"], ["STR(?a)"], [], ["?a"], [fragments.id_order("?a", "assertion"), "?name"]):
        with pytest.raises(ValueError, match="integer id"):
            paging.fetch_page(FakeClient(1), "?a", WHERE, {}, order, PageRequest(), list)
    assert paging.ends_with_id([f"DESC({fragments.id_order('?a', 'patient')})"])
    union = f"{{ ?u a triad:Patient . {fragments.bind_id('?u', 'patient')} }} UNION " \
            f"{{ ?u a triad:Staff . {fragments.bind_id('?u', 'staff')} }}"
    assert paging.ends_with_id(["?name", "?n"], union) and paging.ends_with_id(["DESC(?n)"], union)
    assert not paging.ends_with_id(["?m"], union)


def test_count_distinct():
    client = FakeClient(total=2)
    paging.fetch_page(client, "DISTINCT ?a", WHERE, {}, ORDER, PageRequest(), list, count="DISTINCT ?a")
    assert client.queries[0][0].startswith("SELECT (COUNT(DISTINCT ?a) AS ?total)")
