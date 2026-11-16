"""Clinical entries, messages, assertions, chains and care teams on the knowledge graph (the RecordRepository port).

The same 21 methods and the same results as infrastructure/sqlite/records_repository.py (SqliteRecordRepository):
the same domain objects, the same order (a tie goes to the integer id) and the same errors.

How the reads work:
- An item query has two steps. Step 1 selects only the IRIs of the assertions (?a) with the filters, the order
  and LIMIT/OFFSET (the chart page, the lookups of the Care Assistant). Step 2 reads the assertion view of these
  IRIs with one query (VALUES ?a, then the patterns from ?a; `_views`). So the 22 OPTIONAL patterns of the
  details run only for the rows of the page, not for all items of the chart.
- `_Items` builds the WHERE text of step 1 from the filters of the chart (the SQLite `_item_filters`). It adds a
  pattern only when a filter or the order needs it.
- The patient-visible rule (Q12) and the author name of the text search use EXISTS in the FILTER, not the
  OPTIONAL staff pattern of fragments.PATIENT_VISIBLE: the store then reads the message and the staff member
  only for the rows that need them (on the largest chart: 223 ms, not 738 ms). The rule is the same.
- A chart page: one GROUP BY query gives the number of items of each category (the total). The page query then
  reads only the categories that the page touches, with the OFFSET from the first of them: the chart order is
  the category first, so these rows are the same rows. The first page of the largest chart sorts some hundred
  rows, not 12,471.
- The order variables are BIND results at the end of the group (?rank, ?n). An ORDER BY on the expressions
  themselves is much slower on Oxigraph (it computes them again in each comparison).
- The revision chain: one SELECT finds the head (a path with the bound end $start), and one SELECT gets the
  chain edges from the bound head. Python orders the chain (from the head back) and cuts the page.
- latest_observations: SPARQL has no window functions. One sub-select gives MAX(time) for each code, a second
  sub-select gives the observations, and the outer query keeps the ones with that time and takes MAX(id) for the
  ties (GROUP BY). Two sub-selects, so that Oxigraph joins them once (a hash join), not once for each code.
- An order that SPARQL cannot give is made in Python: the member text of a care team. SQLite gives the order of
  its covering index (CareTeamId, MemberSystem, MemberValue), so Python sorts by (system, value).

How the writes work: each add_* method puts its triples into the write buffer of the unit of work
(unit_of_work.WriteBuffer). The commit sends them in one INSERT DATA. next_identifier and medication_for look in the
buffer first (read your writes): three new entries of one message get three identifier values, and two
prescriptions with the same new medication code use one new Medication.

Known differences from SQLite (see also README.md, section 8):
- D11: Virtuoso orders xsd:dateTime by the text, not by the instant (the chart order, the lookups, the head of a
  care team). The order differs only for two times with different offsets that are less than 7 hours apart.
- The text search uses CONTAINS(LCASE(...)): "%" and "_" are not wildcards (SQLite LIKE), and LCASE lowers all
  letters (SQLite lower() lowers only ASCII letters).
- recommendations: SQLite orders by the text of AssertedAt (not julianday). The KG orders by STR(?at), the text of
  the store. The stores write "+00:00" as "Z" and drop the trailing zeros of the seconds, so the order differs
  only for two times with the same first 19 characters.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from domain.rules import author_label, is_patient_visible
from domain.views import AssertionView, Author, CareTeamMemberView, CareTeamVersion

from application.paging import Page, PageRequest
from application.ports import EntryInfo, NewEntryRow
from infrastructure.sparql import fragments, ids, paging, terms
from infrastructure.sparql.terms import Term, id_of, iri
from infrastructure.sparql.unit_of_work import KgSession
from models.semantic import vocabulary as V

CATEGORIES = frozenset(fragments.CATEGORIES)
NOT_REFUTED = ("Refuted", "EnteredInError")
ACTIVE_DIAGNOSIS = ("active", "recurrence", "relapse")
CURRENT_PRESCRIPTION = ("active", "draft")
CHUNK = 500                                    # the IRIs of one VALUES block (SQLite reads 500 ids at a time)
DATE_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}")

# The subtype columns of a new entry (SQLite SUBTYPE_COLUMNS) -> the ontology property (vocabulary.COLUMNS).
SUBTYPE_PROPERTIES: dict[str, dict[str, str]] = {}
for (_table, _column), (_term, _sort) in V.COLUMNS.items():
    if _table in fragments.CATEGORIES and _sort == V.ATTRIBUTE:
        SUBTYPE_PROPERTIES.setdefault(_table, {})[_column] = _term

BIND_N = fragments.bind_id("?a", "assertion", "?n")
NEWEST_FIRST = ["DESC(?at)", "DESC(?n)"]


def _iris(values: Iterable[str]) -> Term:
    """The text of a VALUES block of IRIs (with or without the angle brackets)."""
    return Term(" ".join(v if v.startswith("<") else f"<{v}>" for v in values))


# ---------------------------------------------------------------------------------------------
# Step 1: the WHERE text of an item query (the SPARQL form of SqliteRecordRepository._item_filters)

# The patient-visible rule of query Q12 (fragments.PATIENT_VISIBLE, SQLite PATIENT_VISIBLE). It includes CURRENT.
# It needs ?type and ?verification. The two EXISTS give "a doctor decision by a person" (s.Role = 'Doctor') and
# "a report that the patient sent" (m.StaffId IS NULL AND m.Origin = 'Patient'); their FILTERs use only their own
# variables, so the store runs them for each row with ?a bound.
VISIBLE = f"""{fragments.CURRENT}
  FILTER (?verification != "EnteredInError" && (
      (?type IN (triad:Observation, triad:LabReport) && ?verification = "Confirmed")
      || EXISTS {{ ?a triad:intent ?vIntent ; triad:source ?vSource . ?vMessage triad:contains ?a .
                  ?vStaff triad:issues ?vMessage ; a ?vRole .
                  FILTER (?vIntent = "Decision" && ?vSource = "Human" && ?vRole = triad:Doctor) }}
      || EXISTS {{ ?pMessage triad:contains ?a ; triad:origin ?pOrigin .
                  FILTER (?pOrigin = "Patient")
                  FILTER NOT EXISTS {{ ?pStaff triad:issues ?pMessage }} }}))"""

# The text search (SQLite: lower(e.Display) LIKE ? OR lower(a.Statement) LIKE ? OR lower(AUTHOR_NAME) LIKE ?).
# The author name is the staff member, or the patient for a message with no issuer. One small query first finds
# the authors whose name has the text (`_Authors`), so the filter of each row compares IRIs, not names.
TEXT = f"{fragments.contains('?display', 'q')} || {fragments.contains('?statement', 'q')}"
BY_STAFF = "EXISTS { ?tMessage triad:contains ?a . ?tStaff triad:issues ?tMessage . FILTER (?tStaff IN ($authors)) }"
BY_STAFF_NAME = f"""EXISTS {{ ?tMessage triad:contains ?a . ?tStaff triad:issues ?tMessage ; triad:name ?tName .
                  FILTER ({fragments.contains("?tName", "q")}) }}"""
BY_PATIENT = "NOT EXISTS { ?uMessage triad:contains ?a . ?uStaff triad:issues ?uMessage }"
AUTHORS = f"""
SELECT ?author FROM $abox WHERE {{
  {{ ?author a triad:Staff ; triad:name ?name . }}
  UNION
  {{ $patient triad:name ?name . BIND ($patient AS ?author) }}
  FILTER ({fragments.contains("?name", "q")})
}}"""
MAX_AUTHORS = 40          # more staff names with the text: compare the names in each row


@dataclass(frozen=True)
class _Authors:
    """The authors whose name has the search text: the staff members, and the patient of the chart."""
    staff: tuple[str, ...] = ()
    patient: bool = False

    def condition(self) -> str:
        parts = [TEXT]
        if len(self.staff) > MAX_AUTHORS:
            parts.append(BY_STAFF_NAME)
        elif self.staff:
            parts.append(BY_STAFF)
        if self.patient:
            parts.append(BY_PATIENT)
        return " || ".join(parts)

# The author role of the recommendations (SQLite: s.Role = ?).
AUTHOR_ROLE = """EXISTS { ?rMessage triad:contains ?a . ?rStaff triad:issues ?rMessage ; a ?rRole .
                FILTER (?rRole = $role) }"""


class _Items:
    """The patterns and filters of one item query of a patient, and their bindings.

    need() adds the pattern of a variable once. The text: the required patterns and their filters, then the
    OPTIONAL patterns and the filters on their variables ("late"), then the BIND lines (writing rule 5: each BIND
    at the end of the group). With an OPTIONAL, the required part is an inner group: then Oxigraph applies the
    type filter and NOT EXISTS before the OPTIONAL, not after it for all items of the patient (83 ms, not 283 ms).
    """

    PATTERNS = {
        "at": "?a triad:assertedAt ?at .",
        "seq": "?a triad:seq ?seq .",
        "intent": "?a triad:intent ?intent .",
        "verification": "?a triad:verification ?verification .",
        "statement": "?a triad:statement ?statement .",
        "display": "?e triad:display ?display .",
        "code": "?e triad:code ?code .",
        "prescriptionStatus": "?e triad:prescriptionStatus ?prescriptionStatus .",
    }
    OPTIONALS = {
        "substance": "OPTIONAL { ?e triad:substance ?substance }",
        "testName": "OPTIONAL { ?e triad:testName ?testName }",
        "conclusion": "OPTIONAL { ?e triad:conclusion ?conclusion }",
        "clinicalStatus": "OPTIONAL { ?e triad:clinicalStatus ?clinicalStatus }",
    }

    def __init__(self, patient_id: int, visit_id: Optional[int] = None):
        self.bindings: dict = {"patient": iri("patient", patient_id)}
        if visit_id is not None:
            self.bindings["visit"] = iri("visit", visit_id)
            start = "$patient triad:hasVisit $visit .\n  ?e triad:during $visit ."
        else:
            start = "$patient triad:hasVisit ?v .\n  ?e triad:during ?v ."
        self.required = [start, "?e a ?type .", "?a triad:about ?e ."]
        self.optional: list[str] = []
        self.filters: list[str] = []
        self.late: list[str] = []
        self.binds: list[str] = []
        self.done: set[str] = set()
        self.types: Sequence[str] = fragments.CATEGORIES
        self.words = 0

    def need(self, *names: str) -> "_Items":
        for name in names:
            if name not in self.done:
                self.done.add(name)
                (self.required if name in self.PATTERNS else self.optional).append(
                    self.PATTERNS.get(name) or self.OPTIONALS[name])
        return self

    def only_types(self, categories: Sequence[str]) -> "_Items":
        """Keep the entries of these categories (writing rule 5: FILTER (?type IN (...)))."""
        self.types = list(categories)
        return self

    def where(self, *, current_only: bool, visible_only: bool, text: Optional[str] = None,
              authors: _Authors = _Authors(), date_from: Optional[str] = None,
              date_to: Optional[str] = None) -> "_Items":
        """The filters of the chart. A patient-visible item is always current (Q12)."""
        if visible_only:
            self.need("verification")
            self.filters.append(VISIBLE)
        elif current_only:
            self.filters.append(fragments.CURRENT)
        if text:
            self.need("display", "statement").filter(authors.condition(), q=text.lower())
            if authors.staff and len(authors.staff) <= MAX_AUTHORS:       # FILTER (?tStaff IN (...))
                self.bindings["authors"] = terms.term_list(Term(f"<{s}>") for s in authors.staff)
        if date_from:
            self.need("at").filter(f"{fragments.local_date('?at')} >= $dateFrom", dateFrom=date_from)
        if date_to:
            self.need("at").filter(f"{fragments.local_date('?at')} <= $dateTo", dateTo=date_to)
        return self

    def filter(self, condition: str, late: bool = False, **bindings) -> "_Items":
        """Add a FILTER. `late`: it uses a variable of an OPTIONAL pattern."""
        (self.late if late else self.filters).append(f"FILTER ({condition})")
        self.bindings.update(bindings)
        return self

    def words_in(self, text_expression: str, words: Sequence[str]) -> "_Items":
        """One condition for each word: the word is in the text (case is not important; no wildcards).
        The text uses the variables of OPTIONAL patterns, so the filters are late."""
        for word in words:
            name = f"w{self.words}"
            self.words += 1
            self.filter(fragments.contains(text_expression, name), late=True, **{name: word.lower()})
        return self

    def bind(self, line: str) -> "_Items":
        self.binds.append(line)
        return self

    def text(self) -> str:
        inner = [*self.required, fragments.classes_in("?type", self.types), *self.filters]
        if self.optional:
            inner = ["{ " + "\n    ".join(inner) + " }", *self.optional, *self.late]
        return "\n  " + "\n  ".join([*inner, *self.binds])


def _rank(variable: str, categories: Sequence[str]) -> str:
    """The place of the category in a list (SQLite CASE e.Category WHEN ? THEN i ... END), at the end of a group."""
    return f"BIND ({fragments.rank(variable, categories)} AS ?rank)"


# ---------------------------------------------------------------------------------------------
# Step 2: the assertion view of a list of IRIs

VIEW_SELECT = f"{fragments.ASSERTION_SELECT} {fragments.DETAIL_SELECT}"
VIEW = f"""
SELECT {VIEW_SELECT} FROM $abox WHERE {{
  VALUES ?a {{ $ids }}
  ?a triad:about ?e ; triad:seq ?seq ; triad:assertedAt ?at ; triad:intent ?intent ; triad:source ?source ;
     triad:verification ?verification ; triad:statement ?statement .
  ?e triad:during ?v ; a ?type ; triad:code ?code ; triad:codeSystem ?codeSystem ; triad:display ?display .
  {fragments.TYPE_FILTER}
  ?p triad:hasVisit ?v ; triad:name ?patientName .
  ?m triad:contains ?a ; triad:channel ?channel ; triad:origin ?origin .
  OPTIONAL {{ ?s triad:issues ?m ; triad:name ?staffName ; a ?staffRole . {fragments.ROLE_FILTER} }}
  OPTIONAL {{ ?a triad:supersedes ?supersedes }}
  OPTIONAL {{ ?supersededBy triad:supersedes ?a }}{fragments.detail_optionals()}
}}"""

# The members of care-team entries, with the staff member of the identifier (SQLite: LEFT JOIN Staff ON
# IdentifierSystem = MemberSystem AND IdentifierValue = MemberValue). The OPTIONAL shares ?value and ?system with
# the member, and its FILTER uses only its own variable: then Oxigraph runs it for each member (2 ms, not 2 s).
MEMBERS = f"""
SELECT ?e ?member ?system ?value ?role ?staff ?staffName ?staffRole FROM $abox WHERE {{
  VALUES ?e {{ $entries }}
  ?e triad:member ?member .
  ?member triad:memberSystem ?system ; triad:memberValue ?value .
  OPTIONAL {{ ?member triad:memberRole ?role }}
  OPTIONAL {{ ?staff triad:identifierValue ?value ; triad:identifierSystem ?system ; triad:name ?staffName ;
             a ?staffRole . {fragments.ROLE_FILTER} }}
}}"""

# The departments of staff members, for the first one by WorksIn id (SQLite: ORDER BY w.Id LIMIT 1).
STAFF_DEPARTMENTS = """
SELECT ?staff ?w ?department FROM $abox WHERE {
  VALUES ?staff { $staff }
  ?w triad:ofStaff ?staff ; triad:atDepartment ?d .
  ?d triad:name ?department .
}"""

# Q2: the head of the chain of an assertion (the end of the path is bound), and the edges from the bound head.
HEAD = """
SELECT ?head FROM $abox WHERE {
  ?head triad:supersedes* $start .
  FILTER NOT EXISTS { ?newer triad:supersedes ?head }
}"""
CHAIN_EDGES = """
SELECT ?x ?older FROM $abox WHERE {
  $head triad:supersedes* ?x .
  ?x triad:about ?entry .
  OPTIONAL { ?x triad:supersedes ?older }
}"""

ENTRY = f"""
SELECT ?v ?p ?type ?head FROM $abox WHERE {{
  $entry triad:during ?v ; a ?type .
  {fragments.TYPE_FILTER}
  ?p triad:hasVisit ?v .
  OPTIONAL {{ ?head triad:about $entry . FILTER NOT EXISTS {{ ?newer triad:supersedes ?head }} }}
}}"""

# The medication of a (code, system). The code is the start: it is the most selective value. The system and the
# class are compared in a FILTER (README.md, rule 4: a shared constant as a pattern object is slow on Oxigraph).
MEDICATION = """
SELECT ?med FROM $abox WHERE {
  ?med triad:code $code ; triad:codeSystem ?system ; a ?class .
  FILTER (?system = $system && ?class = triad:Medication)
}"""

# The newest current care-team assertion of a visit (SQLite: ORDER BY julianday(AssertedAt) DESC, Id DESC LIMIT 1).
CARE_TEAM_HEAD = f"""
SELECT ?a FROM $abox WHERE {{
  ?e triad:during $visit ; a ?type .
  FILTER (?type = triad:CareTeam)
  ?a triad:about ?e ; triad:assertedAt ?at .
  {fragments.CURRENT}
  {BIND_N}
}}
ORDER BY DESC(?at) DESC(?n) LIMIT 1"""


def _author(source: str, origin: str, staff_id: Optional[int], staff_name: Optional[str],
            staff_role: Optional[str], patient_name: str) -> Author:
    """The author of an assertion (the same rule as author_of of the SQLite repository)."""
    return Author(name=staff_name if staff_id is not None else patient_name,
                  role=staff_role if staff_id is not None else "Patient", staff_id=staff_id,
                  label=author_label(source, origin, staff_id, staff_role))


def _role(value: Optional[str]) -> Optional[str]:
    return fragments.category_of(value) if value else None


def _to_view(r: dict, members: dict[str, Optional[str]]) -> AssertionView:
    category = fragments.category_of(r["type"])
    staff_id, staff_role = id_of(r["s"], "staff"), _role(r["staffRole"])
    is_current = r["supersededBy"] is None
    details = fragments.details_of(category, r)
    if category == "CareTeam":
        details["members"] = members.get(r["e"])
    return AssertionView(
        id=id_of(r["a"], "assertion"), entry_id=id_of(r["e"], "clinical-entry"),
        message_id=id_of(r["m"], "message"), seq=r["seq"], visit_id=id_of(r["v"], "visit"), category=category,
        code=r["code"], code_system=r["codeSystem"], display=r["display"], details=details,
        statement=r["statement"], intent=r["intent"], source=r["source"], verification=r["verification"],
        asserted_at=r["at"],
        author=_author(r["source"], r["origin"], staff_id, r["staffName"], staff_role, r["patientName"]),
        channel=r["channel"], origin=r["origin"], supersedes_id=id_of(r["supersedes"], "assertion"),
        superseded_by_id=id_of(r["supersededBy"], "assertion"), is_current=is_current,
        patient_visible=is_patient_visible(is_current=is_current, verification=r["verification"],
                                           intent=r["intent"], source=r["source"], author_role=staff_role,
                                           staff_id=staff_id, origin=r["origin"], category=category),
        patient_id=id_of(r["p"], "patient"))


def _subtype_value(prop: str, value):
    """The value of a subtype property of a new entry. A date-only value of a time property (the date fields of
    the record form send YYYY-MM-DD) becomes an xsd:date: the text stays as SQLite keeps it."""
    if isinstance(value, str) and terms.DATATYPES.get(prop) == "dateTime" and DATE_ONLY.fullmatch(value):
        return terms.date(value)
    return value


class SparqlRecordRepository:
    """The RecordRepository port on SPARQL."""

    def __init__(self, session: KgSession):
        self.session = session
        # The category counts of the last items_page: (its filters, the last write of the store, the counts).
        # The chart use case asks for the same counts at once (category_counts), so it uses them one time.
        self._last_counts: Optional[tuple[tuple, Optional[str], dict[str, int]]] = None

    def _write_buffer(self):
        self._last_counts = None
        return self.session.write_buffer()

    # ----- step 2: the views -----

    def _members(self, entries: Sequence[str]) -> list[dict]:
        rows: list[dict] = []
        for start in range(0, len(entries), CHUNK):
            rows += self.session.select(MEMBERS, {"entries": _iris(entries[start:start + CHUNK])})
        return sorted(rows, key=lambda r: id_of(r["member"], "care-team-member"))

    def _member_texts(self, entries: Sequence[str]) -> dict[str, Optional[str]]:
        """The member text of each care-team entry: the staff name (or the member value), joined with ", ",
        in the order (MemberSystem, MemberValue). An entry with no member has None (SQLite group_concat)."""
        if not entries:
            return {}
        found: dict[str, list[tuple[str, str, str]]] = {}
        for r in self._members(entries):
            found.setdefault(r["e"], []).append((r["system"], r["value"], r["staffName"] or r["value"]))
        return {e: ", ".join(name for _, _, name in sorted(items)) for e, items in found.items()}

    def _views(self, assertion_ids: Sequence[int]) -> dict[int, AssertionView]:
        unique = list(dict.fromkeys(assertion_ids))
        rows: list[dict] = []
        for start in range(0, len(unique), CHUNK):
            part = unique[start:start + CHUNK]
            rows += self.session.select(VIEW, {"ids": Term(" ".join(iri("assertion", i) for i in part))})
        teams = sorted({r["e"] for r in rows if fragments.category_of(r["type"]) == "CareTeam"})
        members = self._member_texts(teams)
        out: dict[int, AssertionView] = {}
        for r in rows:
            view = _to_view(r, members)
            out.setdefault(view.id, view)
        return out

    def _in_order(self, assertion_ids: Sequence[int]) -> list[AssertionView]:
        found = self._views(assertion_ids)
        return [found[i] for i in assertion_ids if i in found]

    # ----- step 1: the item queries -----

    def _select_ids(self, items: _Items, order_by: Sequence[str], limit: int) -> list[int]:
        rows = self.session.select(f"SELECT ?a FROM $abox WHERE {{{items.text()}\n}}\n"
                                   f"ORDER BY {' '.join(order_by)}\nLIMIT {int(limit)}", items.bindings)
        return [id_of(r["a"], "assertion") for r in rows]

    def _authors(self, patient_id: int, text: Optional[str]) -> _Authors:
        if not text:
            return _Authors()
        patient = terms.iri_text("patient", patient_id)
        rows = self.session.select(AUTHORS, {"patient": iri("patient", patient_id), "q": text.lower()})
        found = {r["author"] for r in rows}
        return _Authors(staff=tuple(sorted(found - {patient})), patient=patient in found)

    def _chart_items(self, patient_id: int, current_only: bool, visit_id: Optional[int], text: Optional[str],
                     visible_only: bool, date_from: Optional[str], date_to: Optional[str],
                     authors: Optional[_Authors] = None) -> _Items:
        authors = authors if authors is not None else self._authors(patient_id, text)
        return _Items(patient_id, visit_id).where(current_only=current_only, visible_only=visible_only, text=text,
                                                  authors=authors, date_from=date_from, date_to=date_to)

    def _counts(self, items: _Items) -> dict[str, int]:
        """The number of items of each category, in the order of the chart (no category: no key)."""
        rows = self.session.select(f"SELECT ?type (COUNT(*) AS ?items) FROM $abox WHERE {{{items.text()}\n}}\n"
                                   "GROUP BY ?type", items.bindings)
        found = {fragments.category_of(r["type"]): int(r["items"]) for r in rows}
        return {c: found[c] for c in fragments.CHART_CATEGORIES if c in found}

    def items_page(self, patient_id: int, *, current_only: bool = True, visit_id: Optional[int] = None,
                   category: Optional[str] = None, text: Optional[str] = None, visible_only: bool = False,
                   date_from: Optional[str] = None, date_to: Optional[str] = None,
                   page: PageRequest) -> Page[AssertionView]:
        """One page of the chart (query Q14), in the order of the chart: the category, the newest first, the id.

        The counts of the categories give the total and the categories of the page (see the module text)."""
        filters = (patient_id, current_only, visit_id, text, visible_only, date_from, date_to)
        empty = Page(items=[], total=0, limit=page.limit, offset=page.offset)
        if category and category not in CATEGORIES:        # SQLite: no row has this category
            return empty
        authors = self._authors(patient_id, text)
        counts = self._counts(self._chart_items(*filters, authors=authors))
        self._last_counts = (filters, self.session.state.last_write, counts)
        if category:
            counts = {category: counts.get(category, 0)}
        total = sum(counts.values())
        if page.offset >= total or page.limit <= 0:
            return Page(items=[], total=total, limit=page.limit, offset=page.offset)
        touched, first, position = [], 0, 0
        for name, number in counts.items():                # in the order of the chart
            if number and position < page.offset + page.limit and position + number > page.offset:
                if not touched:
                    first = position
                touched.append(name)
            position += number
        items = self._chart_items(*filters, authors=authors).only_types(touched).need("at")
        order = [*NEWEST_FIRST]
        if len(touched) > 1:
            items.bind(_rank("?type", fragments.CHART_CATEGORIES))
            order.insert(0, "?rank")
        items.bind(BIND_N)
        if not paging.ends_with_id(order, items.text()):
            raise ValueError("The order of a page must end with the integer id of the IRI.")
        part = PageRequest(page.limit, page.offset - first)
        rows = self.session.select(paging.page_query("?a", items.text(), order, part), items.bindings)
        return Page(items=self._in_order([id_of(r["a"], "assertion") for r in rows]), total=total,
                    limit=page.limit, offset=page.offset)

    def category_counts(self, patient_id: int, *, current_only: bool = True, visit_id: Optional[int] = None,
                        text: Optional[str] = None, visible_only: bool = False, date_from: Optional[str] = None,
                        date_to: Optional[str] = None) -> dict[str, int]:
        """The number of items of each category for the filters of the chart, in the order of the chart.

        Right after items_page with the same filters and no write between them, these are its counts."""
        filters = (patient_id, current_only, visit_id, text, visible_only, date_from, date_to)
        last, self._last_counts = self._last_counts, None
        if last is not None and last[0] == filters and last[1] == self.session.state.last_write \
                and self.session.buffer is None:
            return dict(last[2])
        return self._counts(self._chart_items(*filters))

    # ----- the lookups of the Care Assistant tools (step 1 with LIMIT, then the views) -----

    def _lookup(self, items: _Items, *, visible_only: bool, limit: int, current_only: bool = True,
                order_by: Optional[Sequence[str]] = None) -> list[AssertionView]:
        """The items of the filters, in the order `order_by` (default: the newest first, then the id)."""
        items.where(current_only=current_only, visible_only=visible_only).need("at").bind(BIND_N)
        return self._in_order(self._select_ids(items, order_by or NEWEST_FIRST, limit))

    def allergies(self, patient_id: int, *, words: Sequence[str] = (), visible_only: bool,
                  limit: int) -> list[AssertionView]:
        items = _Items(patient_id).only_types(["Allergy"])
        if words:
            items.need("display", "substance").words_in('CONCAT(?display, " ", COALESCE(?substance, ""))', words)
        return self._lookup(items, visible_only=visible_only, limit=limit)

    def prescriptions(self, patient_id: int, *, current_status: bool, visible_only: bool,
                      limit: int) -> list[AssertionView]:
        items = _Items(patient_id).only_types(["Prescription"])
        if current_status:
            items.need("prescriptionStatus", "verification")
            items.filter("?prescriptionStatus IN ($rxStatus)", rxStatus=list(CURRENT_PRESCRIPTION))
            items.filter("?verification NOT IN ($refuted)", refuted=list(NOT_REFUTED))
        return self._lookup(items, visible_only=visible_only, limit=limit)

    def diagnoses(self, patient_id: int, *, active_only: bool, visible_only: bool, limit: int) -> list[AssertionView]:
        items = _Items(patient_id).only_types(["Diagnosis"])
        if active_only:
            items.need("clinicalStatus", "verification")
            items.filter("!BOUND(?clinicalStatus) || ?clinicalStatus IN ($active)", late=True,
                         active=list(ACTIVE_DIAGNOSIS))
            items.filter("?verification NOT IN ($refuted)", refuted=list(NOT_REFUTED))
        return self._lookup(items, visible_only=visible_only, limit=limit)

    def lab_items(self, patient_id: int, *, words: Sequence[str] = (), visible_only: bool,
                  limit: int) -> list[AssertionView]:
        items = _Items(patient_id).only_types(["LabOrder", "LabReport"])
        if words:
            items.need("display", "testName", "conclusion").words_in(
                'CONCAT(?display, " ", COALESCE(?testName, ""), " ", COALESCE(?conclusion, ""))', words)
        return self._lookup(items, visible_only=visible_only, limit=limit)

    def visit_items(self, patient_id: int, visit_id: int, categories: Sequence[str], *, visible_only: bool,
                    limit: int) -> list[AssertionView]:
        known = [c for c in categories if c in CATEGORIES]
        if not known:                                      # SQLite: IN () or no row of these categories
            return []
        items = _Items(patient_id, visit_id).only_types(known).bind(_rank("?type", list(categories)))
        return self._lookup(items, visible_only=visible_only, limit=limit, order_by=["?rank", *NEWEST_FIRST])

    def latest_observations(self, patient_id: int, codes: Sequence[str], *, visible_only: bool,
                            limit: int) -> list[AssertionView]:
        """The newest current observation of each code, newest first. SQLite: ROW_NUMBER() OVER (PARTITION BY
        the code ORDER BY the time DESC, the id DESC) = 1. Here: MAX(time) for each code in a sub-select, then
        MAX(id) of the assertions with that time."""
        if not codes:
            return []

        def pattern() -> _Items:
            items = _Items(patient_id).only_types(["Observation"]).need("code", "at")
            items.filter("?code IN ($codes)", codes=list(codes))
            return items.where(current_only=True, visible_only=visible_only)

        inner, rows_of = pattern(), pattern().bind(BIND_N)
        text = (f"SELECT ?code ?latest (MAX(?n) AS ?id) FROM $abox WHERE {{\n"
                f"  {{ SELECT ?code (MAX(?at) AS ?latest) WHERE {{{inner.text()}\n  }} GROUP BY ?code }}\n"
                f"  {{ SELECT ?code ?at ?n WHERE {{{rows_of.text()}\n  }} }}\n"
                f"  FILTER (?at = ?latest)\n}}\nGROUP BY ?code ?latest\n"
                f"ORDER BY DESC(?latest) DESC(?id)\nLIMIT {int(limit)}")
        rows = self.session.select(text, {**inner.bindings, **rows_of.bindings})
        return self._in_order([int(r["id"]) for r in rows])

    def recommendations(self, patient_id: int, visit_id: int, *, author_role: Optional[str], visible_only: bool,
                        limit: int) -> list[AssertionView]:
        """The recommendations of one visit, current and superseded, oldest first. SQLite orders by the text of
        AssertedAt (not julianday), then Seq, then the id (newest first): the KG uses STR(?at)."""
        items = _Items(patient_id, visit_id).need("intent", "seq")
        items.filter('?intent = "Recommendation"')
        if author_role:
            if author_role not in fragments.STAFF_ROLES:   # SQLite: no staff member has this role
                return []
            items.filter(AUTHOR_ROLE, role=terms.class_term(author_role))
        return self._lookup(items, visible_only=visible_only, limit=limit, current_only=False,
                            order_by=["STR(?at)", "?seq", "DESC(?n)"])

    # ----- one assertion, a list, the chain -----

    def assertions_by_id(self, ids_: Sequence[int]) -> dict[int, AssertionView]:
        return self._views(list(ids_))

    def assertion(self, assertion_id: int) -> Optional[AssertionView]:
        return self._views([assertion_id]).get(assertion_id)

    def _head_id(self, assertion_id: int) -> int:
        """The head of the chain of an assertion (Q2: forward to the current one). The start itself if nothing
        supersedes it (also for an id that does not exist, as the SQLite CTE)."""
        rows = self.session.select(HEAD, {"start": iri("assertion", assertion_id)})
        found = [id_of(r["head"], "assertion") for r in rows if r.get("head")]
        return max(found) if found else assertion_id

    def _chain_ids(self, assertion_id: int) -> list[int]:
        """The ids of the chain of an assertion, from the head back to the first assertion (SQLite: by Depth)."""
        head = self._head_id(assertion_id)
        rows = self.session.select(CHAIN_EDGES, {"head": iri("assertion", head)})
        older = {r["x"]: r["older"] for r in rows}
        out: list[int] = []
        seen: set[str] = set()
        current = terms.iri_text("assertion", head)
        while current in older and current not in seen:       # a cycle stops the walk (the guards refuse one)
            seen.add(current)
            out.append(id_of(current, "assertion"))
            current = older[current]
        return out

    def chain(self, assertion_id: int) -> list[AssertionView]:
        return self._in_order(self._chain_ids(assertion_id))

    def chain_page(self, assertion_id: int, page: PageRequest) -> Page[AssertionView]:
        """One page of the chain of an assertion, newest first (the head first)."""
        chain = self._chain_ids(assertion_id)
        part = chain[page.offset:page.offset + page.limit] if page.offset < len(chain) else []
        return Page(items=self._in_order(part), total=len(chain), limit=page.limit, offset=page.offset)

    def chain_head(self, assertion_id: int) -> Optional[AssertionView]:
        """The current assertion (the head) of the chain of an assertion."""
        return self.assertion(self._head_id(assertion_id))

    def entry(self, entry_id: int) -> Optional[EntryInfo]:
        rows = self.session.select(ENTRY, {"entry": iri("clinical-entry", entry_id)})
        if not rows:
            return None
        r = rows[0]
        heads = [id_of(row["head"], "assertion") for row in rows if row.get("head")]
        return EntryInfo(id=entry_id, patient_id=id_of(r["p"], "patient"), visit_id=id_of(r["v"], "visit"),
                         category=fragments.category_of(r["type"]), head_id=max(heads) if heads else None)

    # ----- writes (inside a unit of work: the write buffer) -----

    def add_message(self, identifier: tuple[str, str], staff_id: Optional[int], channel: str, origin: str,
                    sent_at: str, text: str) -> int:
        buf = self._write_buffer()
        system, value = identifier
        message_id = buf.create("message", {"identifierSystem": system, "identifierValue": value,
                                            "channel": channel, "origin": origin, "sentAt": sent_at, "text": text})
        if staff_id is not None:                            # Issues: <staff> triad:issues <message>
            buf.add(iri("staff", staff_id), {"issues": iri("message", message_id)})
        return message_id

    def add_entry(self, identifier: tuple[str, str], entry: NewEntryRow) -> int:
        """A new clinical entry with its subtype values (one individual with two types), and the members of a
        care team (CareTeamMember individuals that hang on the entry with triad:member)."""
        buf = self._write_buffer()
        system, value = identifier
        properties = SUBTYPE_PROPERTIES[entry.category]
        values = {"identifierSystem": system, "identifierValue": value, "during": iri("visit", entry.visit_id),
                  "code": entry.code, "codeSystem": entry.code_system, "display": entry.display, "text": entry.text,
                  "recordedAt": entry.recorded_at}
        for column, prop in properties.items():
            values[prop] = _subtype_value(prop, entry.details.get(column))
        if entry.category == "Prescription" and entry.medication_id is not None:
            values["prescribes"] = iri("medication", entry.medication_id)
        entry_id = buf.create("clinical-entry", values, types=(entry.category,))
        if entry.category == "CareTeam":
            for member_system, member_value, role in entry.members:
                member = buf.create("care-team-member", {"memberSystem": member_system,
                                                         "memberValue": member_value, "memberRole": role})
                buf.add(iri("clinical-entry", entry_id), {"member": iri("care-team-member", member)})
        return entry_id

    def add_assertion(self, message_id: int, seq: int, entry_id: int, supersedes_id: Optional[int], at: str,
                      intent: str, source: str, verification: str, statement: str) -> int:
        buf = self._write_buffer()
        assertion_id = buf.create("assertion", {
            "seq": seq, "about": iri("clinical-entry", entry_id),
            "supersedes": iri("assertion", supersedes_id) if supersedes_id is not None else None,
            "assertedAt": at, "intent": intent, "source": source, "verification": verification,
            "statement": statement})
        buf.add(iri("message", message_id), {"contains": iri("assertion", assertion_id)})   # Contains
        return assertion_id

    def medication_for(self, code: str, code_system: str, name: str) -> int:
        """The Medication with this (code, system): new in this write, or stored. Add it if it does not exist."""
        buf = self._write_buffer()
        new = buf.find("medication", code=code, codeSystem=code_system)
        if new:
            return new[0]
        rows = self.session.select(MEDICATION, {"code": code, "system": code_system})
        if rows:
            return min(id_of(r["med"], "medication") for r in rows)
        return buf.create("medication", {"code": code, "codeSystem": code_system, "name": name})

    def next_identifier(self, table: str, system: str, prefix: str, width: int) -> str:
        """The next value `<prefix><number>` of a table (ids.next_identifier: the stored values and the buffer)."""
        return ids.next_identifier(self.session, ids.TABLE_KIND[table], system, prefix, width)

    # ----- care teams -----

    def care_team_versions(self, visit_id: int) -> list[CareTeamVersion]:
        """The chain of the newest care-team head of the visit, newest first."""
        rows = self.session.select(CARE_TEAM_HEAD, {"visit": iri("visit", visit_id)})
        if not rows:
            return []
        chain = self.chain(id_of(rows[0]["a"], "assertion"))
        entries = list(dict.fromkeys(terms.iri_text("clinical-entry", a.entry_id) for a in chain))
        member_rows = self._members(entries)
        staff = sorted({r["staff"] for r in member_rows if r.get("staff")})
        departments = self._first_departments(staff)
        members: dict[int, list[CareTeamMemberView]] = {}
        for r in member_rows:
            members.setdefault(id_of(r["e"], "clinical-entry"), []).append(CareTeamMemberView(
                system=r["system"], value=r["value"], role=r["role"], staff_id=id_of(r["staff"], "staff"),
                name=r["staffName"] or r["value"], staff_role=_role(r["staffRole"]),
                department=departments.get(r["staff"])))
        out = []
        for depth, a in enumerate(chain):
            status = a.details.get("status") or "active"
            out.append(CareTeamVersion(entry_id=a.entry_id, assertion_id=a.id, visit_id=a.visit_id,
                                       name=a.details.get("name"), status=status,
                                       members=members.get(a.entry_id, []), author=a.author,
                                       asserted_at=a.asserted_at, is_current=depth == 0 and status == "active"))
        return out

    def _first_departments(self, staff: Sequence[str]) -> dict[str, str]:
        """The department of the first WorksIn row (by id) of each staff member."""
        if not staff:
            return {}
        first: dict[str, tuple[int, str]] = {}
        for r in self.session.select(STAFF_DEPARTMENTS, {"staff": _iris(staff)}):
            number = id_of(r["w"], "works-in")
            if r["staff"] not in first or number < first[r["staff"]][0]:
                first[r["staff"]] = (number, r["department"])
        return {s: name for s, (_, name) in first.items()}

