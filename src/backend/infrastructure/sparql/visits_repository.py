"""Visits and their locations on the knowledge graph (the VisitRepository port).

The same results as SqliteVisitRepository (infrastructure/sqlite/patients_repository.py), on the terms of the
ontology (models/semantic/vocabulary.py):

    SQLite                                   knowledge graph
    Visit.PatientId                          ?p triad:hasVisit ?v
    Visit.IdentifierSystem, ...Value         ?v triad:identifierSystem, triad:identifierValue
    Visit.Class, Type, Reason                ?v triad:visitClass, triad:visitType, triad:reason
    Visit.StartDate, EndDate                 ?v triad:startDate, triad:endDate (xsd:dateTime)
    VisitLocation (VisitId, LocationId)      ?vl triad:ofVisit ?v ; triad:atLocation ?l
    VisitLocation.StartDate, EndDate         ?vl triad:startDate, triad:endDate
    Location.Name, Type                      ?l triad:name, triad:locationType

The orders of SQLite use julianday(), the instant of a time. Virtuoso orders xsd:dateTime by the text (D11), and
the data has three offsets (+00:00 Synthea, -04:00 the scenario, and the offset of the clock of the app). So
Python makes these orders, with the instant and then the id (`newest_first`, `oldest_first`): a patient has a
small number of visits (the most in the full data: 382), and a visit has a small number of locations.
- The visits of a patient (a page): the latest start first, then the largest id. One query gives the
  (visit, start) pairs of the patient; Python sorts them and cuts the page; a second query reads the page.
- The locations of a visit: the earliest start first, then the smallest id. The department of a visit is
  the type of its last location (as in SQLite).
- visit_rows() is in the order of the id (the SQLite rows come from the index on PatientId, in rowid order).
- move() and end() set the end of each open location of the visit (an UPDATE ... WHERE EndDate IS NULL):
  one replace for each open location.
"""
from __future__ import annotations

from typing import Callable, Optional, Sequence, TypeVar

from domain.rules import parse_time
from domain.views import Identifier, VisitLocationView, VisitView

from application.paging import Page, PageRequest
from infrastructure.sparql import ids, terms
from infrastructure.sparql.terms import Term, id_of, iri
from infrastructure.sparql.unit_of_work import KgSession

T = TypeVar("T")

VISITS_OF_PATIENT = """
SELECT ?v ?start FROM $abox WHERE {
  $patient triad:hasVisit ?v .
  ?v triad:startDate ?start .
}"""

VISIT_ROWS = """
SELECT ?v ?class ?start ?end FROM $abox WHERE {
  $patient triad:hasVisit ?v .
  ?v triad:visitClass ?class ; triad:startDate ?start .
  OPTIONAL { ?v triad:endDate ?end }
}"""

VISITS = """
SELECT ?v ?p ?system ?value ?class ?type ?reason ?start ?end FROM $abox WHERE {
  VALUES ?v { $visits }
  ?v a triad:Visit ; triad:identifierSystem ?system ; triad:identifierValue ?value ; triad:visitClass ?class ;
     triad:startDate ?start .
  ?p triad:hasVisit ?v .
  OPTIONAL { ?v triad:visitType ?type }
  OPTIONAL { ?v triad:reason ?reason }
  OPTIONAL { ?v triad:endDate ?end }
}"""

LOCATIONS = """
SELECT ?vl ?v ?l ?name ?type ?start ?end FROM $abox WHERE {
  VALUES ?v { $visits }
  ?vl triad:ofVisit ?v ; triad:atLocation ?l ; triad:startDate ?start .
  ?l triad:name ?name .
  OPTIONAL { ?l triad:locationType ?type }
  OPTIONAL { ?vl triad:endDate ?end }
}"""

OPEN_VISITS = """
SELECT ?v ?start FROM $abox WHERE {
  $patient triad:hasVisit ?v .
  ?v triad:startDate ?start .
  OPTIONAL { ?v triad:endDate ?end }
  FILTER (!BOUND(?end))
}"""

OPEN_LOCATIONS = """
SELECT ?vl FROM $abox WHERE {
  ?vl triad:ofVisit $visit .
  OPTIONAL { ?vl triad:endDate ?end }
  FILTER (!BOUND(?end))
}"""


# ---------------------------------------------------------------------------------------------
# The orders by time (the instant, then the id; see the module text). The audit and chat repositories use them.

def newest_first(rows: Sequence[T], time: Callable[[T], str], number: Callable[[T], int]) -> list[T]:
    """ORDER BY julianday(<time>) DESC, Id DESC."""
    return sorted(rows, key=lambda r: (parse_time(time(r)), number(r)), reverse=True)


def oldest_first(rows: Sequence[T], time: Callable[[T], str], number: Callable[[T], int]) -> list[T]:
    """ORDER BY julianday(<time>), Id."""
    return sorted(rows, key=lambda r: (parse_time(time(r)), number(r)))


def page_slice(rows: Sequence[T], page: PageRequest) -> list[T]:
    """The rows of one page (LIMIT and OFFSET) of a list in its final order."""
    return list(rows[page.offset:page.offset + page.limit])


def iri_list(values) -> Term:
    """The IRIs of the rows for a VALUES block. A value is the text of an IRI of a client row (no angle brackets);
    each one is made again from its kind and id (terms.iri), so only the IRI of a TRIAD individual can go in."""
    return Term(" ".join(terms.iri(*terms.split_iri(v)) for v in values))


class SparqlVisitRepository:
    """The VisitRepository port on SPARQL."""

    def __init__(self, session: KgSession):
        self.session = session

    def _views(self, visit_iris: Sequence[str]) -> list[VisitView]:
        """The views of the visits, in the order of `visit_iris` (a visit that does not exist has no view)."""
        if not visit_iris:
            return []
        listed = iri_list(visit_iris)
        rows = {r["v"]: r for r in self.session.select(VISITS, {"visits": listed})}
        places: dict[str, list[dict]] = {}
        for r in self.session.select(LOCATIONS, {"visits": listed}):
            places.setdefault(r["v"], []).append(r)
        out = []
        for v in visit_iris:
            r = rows.get(v)
            if r is None:
                continue
            locs = [VisitLocationView(id_of(p["l"], "location"), p["name"], p["type"], p["start"], p["end"])
                    for p in oldest_first(places.get(v, []), lambda p: p["start"],
                                          lambda p: id_of(p["vl"], "visit-location"))]
            out.append(VisitView(id=id_of(v, "visit"), patient_id=id_of(r["p"], "patient"),
                                 identifier=Identifier(r["system"], r["value"]), visit_class=r["class"],
                                 type=r["type"], reason=r["reason"], start_date=r["start"], end_date=r["end"],
                                 is_open=r["end"] is None, department=locs[-1].department if locs else None,
                                 locations=locs))
        return out

    def _newest_visits(self, patient_id: int) -> list[str]:
        rows = self.session.select(VISITS_OF_PATIENT, {"patient": iri("patient", patient_id)})
        return [r["v"] for r in newest_first(rows, lambda r: r["start"], lambda r: id_of(r["v"], "visit"))]

    def for_patient(self, patient_id: int) -> list[VisitView]:
        return self._views(self._newest_visits(patient_id))

    def for_patient_page(self, patient_id: int, page: PageRequest) -> Page[VisitView]:
        """One page of the visits of the patient, newest first."""
        visits = self._newest_visits(patient_id)
        return Page(items=self._views(page_slice(visits, page)), total=len(visits), limit=page.limit,
                    offset=page.offset)

    def get(self, visit_id: int) -> Optional[VisitView]:
        if visit_id < 0:                    # no IRI has a negative id (SQLite: no row)
            return None
        views = self._views([iri("visit", visit_id)[1:-1]])
        return views[0] if views else None

    def open_visit_id(self, patient_id: int) -> Optional[int]:
        rows = self.session.select(OPEN_VISITS, {"patient": iri("patient", patient_id)})
        newest = newest_first(rows, lambda r: r["start"], lambda r: id_of(r["v"], "visit"))
        return id_of(newest[0]["v"], "visit") if newest else None

    def visit_rows(self, patient_id: int) -> list[tuple[int, str, str, Optional[str]]]:
        rows = self.session.select(VISIT_ROWS, {"patient": iri("patient", patient_id)})
        return sorted((id_of(r["v"], "visit"), r["class"], r["start"], r["end"]) for r in rows)

    def create(self, patient_id: int, identifier: tuple[str, str], visit_class: str, type_: Optional[str],
               reason: Optional[str], start: str, location_id: Optional[int], end: Optional[str] = None) -> int:
        buf = self.session.write_buffer()
        system, value = identifier
        visit_id = buf.create("visit", {"identifierSystem": system, "identifierValue": value,
                                        "visitClass": visit_class, "visitType": type_, "reason": reason,
                                        "startDate": start, "endDate": end})
        buf.add(iri("patient", patient_id), {"hasVisit": iri("visit", visit_id)})
        if location_id is not None:
            buf.create("visit-location", {"ofVisit": iri("visit", visit_id), "atLocation": iri("location", location_id),
                                          "startDate": start, "endDate": end})
        return visit_id

    def _end_open_locations(self, visit_id: int, now: str) -> None:
        """UPDATE VisitLocation SET EndDate = now WHERE VisitId = ? AND EndDate IS NULL. The store does not see the
        write buffer, so a stored location that this write ended already (a second move) is not open."""
        buf = self.session.write_buffer()
        ended = {r.subject for r in buf.change().replaced("visit-location") if r.prop == "endDate" and r.values}
        for r in self.session.select(OPEN_LOCATIONS, {"visit": iri("visit", visit_id)}):
            location = iri("visit-location", id_of(r["vl"], "visit-location"))
            if location not in ended:
                buf.replace(location, "endDate", now)
        for new in buf.created("visit-location"):        # a location of this write (not in the store yet)
            if new.get("ofVisit") == iri("visit", visit_id) and new.get("endDate") is None:
                buf.replace(new.iri, "endDate", now)

    def move(self, visit_id: int, location_id: int, now: str) -> None:
        self._end_open_locations(visit_id, now)
        buf = self.session.write_buffer()
        buf.create("visit-location", {"ofVisit": iri("visit", visit_id), "atLocation": iri("location", location_id),
                                      "startDate": now})

    def end(self, visit_id: int, now: str) -> None:
        buf = self.session.write_buffer()
        buf.replace(iri("visit", visit_id), "endDate", now)
        self._end_open_locations(visit_id, now)

    def next_identifier(self, system: str, prefix: str, width: int) -> str:
        return ids.next_identifier(self.session, "visit", system, prefix, width)
