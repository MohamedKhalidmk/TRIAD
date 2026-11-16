"""Patients on the knowledge graph (the PatientRepository port).

The same results as SqlitePatientRepository (infrastructure/sqlite/patients_repository.py), on the terms of the
ontology (models/semantic/vocabulary.py):

    SQLite                               knowledge graph
    Patient.Name, DateOfBirth, Sex       ?p triad:name, triad:dateOfBirth (xsd:date), triad:patientSex
    Patient.PhoneNumber, Street, ...     ?p triad:phoneNumber, triad:street, triad:city, triad:region, ...
    PatientIdentifier (System, Value)    ?p triad:identifier ?i . ?i triad:identifierSystem, triad:identifierValue
    Visit.PatientId                      ?p triad:hasVisit ?v

The rules of the SQLite repository:
- The open visit of a patient (OPEN_VISIT_SQL) is its visit with no end date and the latest start (the instant,
  as julianday), then the largest id. Python selects it from the open visits of the patient, so the result is
  the same on each store (Virtuoso orders xsd:dateTime by the text, D11).
- The identifiers of a patient are in the order of their id.
- The search: `lower(Name) LIKE %q%` is CONTAINS(LCASE(?name), q) (SPARQL writing rule 7; README "Known limits":
  `%` and `_` are not wildcards); the order is the name (the code points, as the BINARY collation), then the id.
- The care team of query Q13 (CARE_TEAM_PATIENTS_SQL): a care-team entry with the status "active" that has the
  member (memberSystem, memberValue), during a visit of the patient, and an assertion about the entry that
  nothing supersedes.
- update() takes the SQLite column names of the use case (patients.change): Sex, PhoneNumber, Street, ...
- delete() deletes the identifiers, then the patient. A patient with visits is in use: the foreign-key guard
  gives Conflict (409), as the FOREIGN KEY of Visit.PatientId in SQLite. The use case checks it first.
The constraint names, the keys and their errors are in the guards (guards.py, guards_directory.py).
"""
from __future__ import annotations

from typing import Optional

from domain.records import Address
from domain.rules import parse_time
from domain.views import Identifier, PatientSummary, PatientView

from application.paging import Page, PageRequest
from infrastructure.sparql import fragments, ids, paging, terms
from infrastructure.sparql.terms import id_of, iri
from infrastructure.sparql.unit_of_work import KgSession
from infrastructure.sparql.visits_repository import iri_list

# The SQLite column of the use case -> the property of the patient.
PATIENT_PROPERTIES = {"Sex": "patientSex", "PhoneNumber": "phoneNumber", "Street": "street", "City": "city",
                      "Region": "region", "PostalCode": "postalCode", "Country": "country"}

# One patient in one request: the values (part "patient"), the identifiers (part "identifier") and the open
# visits (part "open"). ?x is the IRI of the identifier or of the visit.
PATIENT = """
SELECT ?part ?x ?name ?dob ?sex ?phone ?street ?city ?region ?postalCode ?country ?system ?value ?start
FROM $abox WHERE {
  { $patient a triad:Patient ; triad:name ?name ; triad:dateOfBirth ?dob ; triad:patientSex ?sex .
    OPTIONAL { $patient triad:phoneNumber ?phone }
    OPTIONAL { $patient triad:street ?street }
    OPTIONAL { $patient triad:city ?city }
    OPTIONAL { $patient triad:region ?region }
    OPTIONAL { $patient triad:postalCode ?postalCode }
    OPTIONAL { $patient triad:country ?country }
    BIND ("patient" AS ?part) }
  UNION
  { $patient triad:identifier ?x .
    ?x triad:identifierSystem ?system ; triad:identifierValue ?value .
    BIND ("identifier" AS ?part) }
  UNION
  { $patient triad:hasVisit ?x .
    ?x triad:startDate ?start .
    OPTIONAL { ?x triad:endDate ?end }
    FILTER (!BOUND(?end))
    BIND ("open" AS ?part) }
}"""

# The open visits of some patients (the page of a search).
OPEN_VISITS = """
SELECT ?p ?v ?start FROM $abox WHERE {
  VALUES ?p { $patients }
  ?p triad:hasVisit ?v .
  ?v triad:startDate ?start .
  OPTIONAL { ?v triad:endDate ?end }
  FILTER (!BOUND(?end))
}"""

SEARCH = """
  ?p a triad:Patient ; triad:name ?name ; triad:dateOfBirth ?dob ; triad:patientSex ?sex .
  OPTIONAL { ?p triad:phoneNumber ?phone }"""
SEARCH_COLUMNS = "?p ?name ?dob ?sex ?phone ?n"


def care_team(patient: str) -> str:
    """The pattern "the current care team of `patient` has the member" (query Q13). Needs $memberSystem and
    $memberValue.

    - The member value starts the pattern: a staff member is in some care teams. The member system and the status
      are compared in a FILTER (README, rule 4: a shared constant as a triple-pattern object is slow).
    - "Current" (nothing supersedes the assertion about the entry) is OPTIONAL + !BOUND, not FILTER NOT EXISTS:
      measured on the full graph (Oxigraph), FILTER NOT EXISTS here takes 30 ms and OPTIONAL + !BOUND 0.1 ms.
      The two forms give the same rows.
    """
    return f"""
  ?member triad:memberValue $memberValue ; triad:memberSystem ?memberSystem .
  FILTER (?memberSystem = $memberSystem)
  ?team triad:member ?member ; triad:careTeamStatus ?teamStatus ; triad:during ?teamVisit .
  FILTER (?teamStatus = "active")
  {patient} triad:hasVisit ?teamVisit .
  ?teamAssertion triad:about ?team .
  OPTIONAL {{ ?newerTeamAssertion triad:supersedes ?teamAssertion }}
  FILTER (!BOUND(?newerTeamAssertion))"""


ON_CARE_TEAM = f"ASK FROM $abox WHERE {{{care_team('$patient')}\n}}"

KEY_EXISTS = """
ASK FROM $abox WHERE { ?p triad:name $name ; triad:dateOfBirth $dob ; a triad:Patient . }"""

HAS_VISITS = "ASK FROM $abox WHERE { $patient triad:hasVisit ?v }"

IDENTIFIERS = "SELECT ?i FROM $abox WHERE { $patient triad:identifier ?i }"


def open_visit(visits: list[tuple[str, str]]) -> Optional[int]:
    """The open visit of OPEN_VISIT_SQL: the latest start (as an instant), then the largest id. `visits` holds
    (the IRI of the visit, the start) pairs."""
    if not visits:
        return None
    best = max(visits, key=lambda v: (parse_time(v[1]), id_of(v[0], "visit")))
    return id_of(best[0], "visit")


class SparqlPatientRepository:
    """The PatientRepository port on SPARQL."""

    def __init__(self, session: KgSession):
        self.session = session

    def get(self, patient_id: int) -> Optional[PatientView]:
        if patient_id < 0:                  # no IRI has a negative id (SQLite: no row)
            return None
        rows = self.session.select(PATIENT, {"patient": iri("patient", patient_id)})
        values = next((r for r in rows if r["part"] == "patient"), None)
        if values is None:
            return None
        found = sorted((id_of(r["x"], "patient-identifier"), r["system"], r["value"])
                       for r in rows if r["part"] == "identifier")
        visits = [(r["x"], r["start"]) for r in rows if r["part"] == "open"]
        return PatientView(id=patient_id, name=values["name"], date_of_birth=values["dob"], sex=values["sex"],
                           phone_number=values["phone"], open_visit_id=open_visit(visits),
                           address=Address(street=values["street"], city=values["city"], region=values["region"],
                                           postal_code=values["postalCode"], country=values["country"]),
                           identifiers=[Identifier(system, value) for _, system, value in found])

    def _summaries(self, rows: list[dict]) -> list[PatientSummary]:
        if not rows:
            return []
        visits: dict[str, list[tuple[str, str]]] = {}
        for r in self.session.select(OPEN_VISITS, {"patients": iri_list(r["p"] for r in rows)}):
            visits.setdefault(r["p"], []).append((r["v"], r["start"]))
        return [PatientSummary(id_of(r["p"], "patient"), r["name"], r["dob"], r["sex"], r["phone"],
                               open_visit(visits.get(r["p"], []))) for r in rows]

    def search(self, q: Optional[str], dob: Optional[str], scope: str, member: Optional[tuple[str, str]],
               page: PageRequest) -> Page[PatientSummary]:
        where, bindings = SEARCH, {}
        select, count = SEARCH_COLUMNS, "*"
        if q:
            where += "\n  FILTER (" + fragments.contains("?name", "q") + ")"
            bindings["q"] = q.lower()
        if dob:
            where += "\n  FILTER (?dob = $dob)"
            bindings["dob"] = terms.date(dob)
        if scope == "open-visits":
            where += ("\n  FILTER EXISTS { ?p triad:hasVisit ?openVisit . "
                      "FILTER NOT EXISTS { ?openVisit triad:endDate ?openEnd } }")
        if scope == "care-team" and member:
            # A join, not FILTER EXISTS: the member starts the pattern. A patient can have two such care teams.
            where += care_team("?p")
            bindings.update(memberSystem=member[0], memberValue=member[1])
            select, count = "DISTINCT " + SEARCH_COLUMNS, "DISTINCT ?p"
        # The order ends with the id of the patient. ?n is in the projection: with DISTINCT, an ORDER BY
        # expression that is not in the projection can fail on a store that writes SQL (Virtuoso).
        where += "\n  " + fragments.bind_id("?p", "patient", "?n")
        return paging.fetch_page(self.session.client, select, where, bindings, ["?name", "?n"], page,
                                 self._summaries, count=count)

    def key_exists(self, name: str, date_of_birth: str) -> bool:
        return self.session.ask(KEY_EXISTS, {"name": name, "dob": terms.date(date_of_birth)})

    def create(self, name: str, date_of_birth: str, sex: str, phone: Optional[str], address: Address,
               identifiers: list[tuple[str, str]]) -> int:
        buf = self.session.write_buffer()
        patient_id = buf.create("patient", {
            "name": name, "dateOfBirth": date_of_birth, "patientSex": sex, "phoneNumber": phone,
            "street": address.street, "city": address.city, "region": address.region,
            "postalCode": address.postal_code, "country": address.country})
        for system, value in identifiers:
            ident = buf.create("patient-identifier", {"identifierSystem": system, "identifierValue": value})
            buf.add(iri("patient", patient_id), {"identifier": iri("patient-identifier", ident)})
        return patient_id

    def update(self, patient_id: int, changes: dict) -> None:
        buf = self.session.write_buffer()
        for column, prop in PATIENT_PROPERTIES.items():
            if column in changes:
                buf.replace(iri("patient", patient_id), prop, changes[column])

    def has_visits(self, patient_id: int) -> bool:
        return self.session.ask(HAS_VISITS, {"patient": iri("patient", patient_id)})

    def delete(self, patient_id: int) -> None:
        buf = self.session.write_buffer()
        for r in self.session.select(IDENTIFIERS, {"patient": iri("patient", patient_id)}):
            buf.delete_subject("patient-identifier", id_of(r["i"], "patient-identifier"))
        buf.delete_subject("patient", patient_id)

    def on_care_team(self, patient_id: int, system: str, value: str) -> bool:
        return self.session.ask(ON_CARE_TEAM, {"patient": iri("patient", patient_id), "memberSystem": system,
                                               "memberValue": value})

    def next_identifier(self, system: str, prefix: str, width: int) -> str:
        return ids.next_identifier(self.session, "patient-identifier", system, prefix, width)
