"""Reusable SPARQL pattern text: CURRENT, PATIENT_VISIBLE, the assertion view, the id order and the type filters.

These are the SPARQL forms of the shared SQL fragments of infrastructure/sqlite/records_repository.py
(CURRENT, PATIENT_VISIBLE, ASSERTION_COLUMNS/ASSERTION_FROM, CHART_ORDER) and of the queries Q1, Q12 and Q13 of
dml/03_select_queries.sql. A test runs each fragment on the planted data of both stores and compares the rows.

The text follows the SPARQL writing rules of the plan:
- rule 1: the fragments are group patterns; the query around them has the dataset clause (FROM $abox);
- rule 5: a type restriction is FILTER (?type IN (...)), never VALUES in the middle; each BIND is at the end;
- rule 6: the local date of a time is SUBSTR(STR(?t), 1, 10) (local_date);
- rule 7: a text search is CONTAINS(LCASE(...)) (contains);
- rule 8: an EXISTS on an OPTIONAL variable needs BOUND (the PATIENT_VISIBLE predicate does this).

The assertion view: assertion_view() binds these variables (the columns of ASSERTION_COLUMNS in SQLite):

    variable        SQLite column            note
    ?a              Assertion.Id             the IRI; terms.id_of(row["a"]) gives the id
    ?e              ClinicalEntryId          the IRI of the entry
    ?m              MessageId                the IRI of the message
    ?v              Visit.Id                 the IRI of the visit
    ?p              Visit.PatientId          the IRI of the patient (or the bound IRI of the patient)
    ?patientName    Patient.Name
    ?type           ClinicalEntry.Category   the IRI of the subtype class; category_of(row["type"]) gives the name
    ?code ?codeSystem ?display               ClinicalEntry.Code, CodeSystem, Display
    ?seq ?at ?intent ?source ?verification ?statement      Assertion.Seq, AssertedAt, Intent, Source, ...
    ?channel ?origin                         Message.Channel, Origin
    ?s ?staffName ?staffRole                 Message.StaffId, Staff.Name, Staff.Role (OPTIONAL: none for a
                                             patient report); ?staffRole is the IRI of Doctor, Nurse or MOA
    ?supersedes ?supersededBy                Assertion.SupersedesId, the Id of the newer assertion (OPTIONAL)
The details of the subtype (Allergy.Substance, ...) are in DETAILS; detail_optionals() reads them.
"""
from __future__ import annotations

from typing import Iterable, Sequence

from infrastructure.rdf.namespaces import KG
from infrastructure.sparql import terms

# The categories (the subtypes of ClinicalEntry) and the staff roles (the subtypes of Staff).
CATEGORIES = ("Diagnosis", "Procedure", "Allergy", "Observation", "LabOrder", "LabReport", "Prescription",
              "CareTeam")
STAFF_ROLES = ("Doctor", "Nurse", "MOA")
# The order of the categories in the chart (CHART_CATEGORIES of the SQLite repository).
CHART_CATEGORIES = ("Allergy", "Diagnosis", "Prescription", "Observation", "LabOrder", "LabReport", "Procedure",
                    "CareTeam")


def classes_in(variable: str, classes: Iterable[str]) -> str:
    """FILTER (?x IN (triad:A, triad:B, ...)): the type restriction of rule 5."""
    return f"FILTER ({variable} IN ({terms.term_list(terms.class_term(c) for c in classes)}))"


TYPE_FILTER = classes_in("?type", CATEGORIES)
ROLE_FILTER = classes_in("?staffRole", STAFF_ROLES)


def category_of(type_iri: str) -> str:
    """The category name of the IRI of a subtype class: ...triad#Allergy -> 'Allergy'."""
    return terms.name_of(type_iri)


def current(assertion: str = "?a", newer: str = "?newer") -> str:
    """CURRENT: no assertion supersedes the assertion (SQLite: NOT EXISTS ... SupersedesId = a.Id)."""
    return f"FILTER NOT EXISTS {{ {newer} triad:supersedes {assertion} }}"


CURRENT = current()

# PATIENT_VISIBLE: the predicate of query Q12 (USER_FLOWS.md section 2.1). It includes CURRENT.
# It needs the variables of the assertion view. A patient report has no issuer (?s is not bound).
# Two IRIs compare with "=", not with sameTerm() (SPARQL writing rule 11: false on Virtuoso for equal IRIs).
PATIENT_VISIBLE = CURRENT + """
FILTER (?verification != "EnteredInError" && (
    (?intent = "Decision" && ?source = "Human" && BOUND(?staffRole) && ?staffRole = triad:Doctor)
    || (?type IN (triad:Observation, triad:LabReport) && ?verification = "Confirmed")
    || (!BOUND(?s) && ?origin = "Patient")))"""


def id_order(variable: str, kind: str) -> str:
    """The integer id of an individual IRI, for ORDER BY: xsd:integer(STRAFTER(STR(?x), ".../kg/<kind>/")).

    A total order ends with this expression (the IRI text sorts "/10" before "/9"). paging.fetch_page checks it.
    """
    if kind not in terms.KINDS:
        raise terms.TermError(f"{kind!r} is not a class path.")
    return f'xsd:integer(STRAFTER(STR({variable}), "{KG}{kind}/"))'


def bind_id(subject: str, kind: str, target: str = "?n") -> str:
    """BIND the integer id of an individual to a variable: for a union of two kinds, each branch binds ?n.

    paging.fetch_page accepts an order that ends with a variable that such a BIND gives.
    """
    return f"BIND ({id_order(subject, kind)} AS {target})"


def rank(variable: str, classes: Sequence[str]) -> str:
    """The place of a class IRI in a list, for ORDER BY: IF(?x = triad:A, 0, IF(..., 1, ... n)).

    The IF compares the IRIs with "=" (SPARQL writing rule 11): on Virtuoso 7.2, sameTerm(?type, triad:Allergy) in
    a BIND has no value, so all items got the last place, and the chart order was the time only."""
    text = str(len(classes))
    for index in range(len(classes) - 1, -1, -1):
        text = f"IF({variable} = {terms.class_term(classes[index])}, {index}, {text})"
    return text


CHART_RANK = rank("?type", CHART_CATEGORIES)


def local_date(variable: str) -> str:
    """The local date of a time (rule 6): the first 10 characters of its text, not the UTC date."""
    return f"SUBSTR(STR({variable}), 1, 10)"


def instant(variable: str) -> str:
    """A time for ORDER BY by the instant (as SQLite julianday): xsd:dateTime(STR(?t)). Put it in a BIND.

    Virtuoso 7.2 orders a STORED xsd:dateTime by its local time (the text), not by the instant: 16:05-04:00 came
    before 14:30-07:00. Its comparisons (<, =), MAX and MIN, and the order of a cast value use the instant.
    Oxigraph uses the instant in all cases, so the cast changes nothing there.
    """
    return f"xsd:dateTime(STR({variable}))"


def lower(text_expression: str) -> str:
    """The text in lower case: LCASE(STR(...)).

    STR is necessary on Virtuoso 7.2. With FILTER (LCASE(?name) = "x") (also UCASE, STRLEN) and an ORDER BY that
    does not have ?name, Virtuoso gives the correct rows but a wrong ?name: the value of one other row, in all rows
    (department_by_name("Inpatient Medicine") gave the name "Emergency"). LCASE(STR(?name)) gives the correct value.
    Use it on a variable. Compare it with a text that Python lowers (str.lower(), the Unicode lower case, as LCASE):
    on Virtuoso, LCASE(STR("ÉQUIPE")) of a constant is "" (an empty text) when the text has a non-ASCII letter.
    """
    return f"LCASE(STR({text_expression}))"


def contains(text_expression: str, placeholder: str) -> str:
    """A case-free text search (rule 7). Give the binding in lower case: {"q": text.lower()}."""
    return f"CONTAINS({lower(text_expression)}, ${placeholder})"


# ---------------------------------------------------------------------------------------------
# The assertion view

def assertion_view(patient: str = "?p", assertion: str = "?a") -> str:
    """The pattern of one row of the SQLite assertion view (see the module text for the variables).

    `patient` and `assertion` are variables or placeholders. A bound start makes the query fast: give
    "$patient" (an IRI binding) for the chart of a patient, or "$assertion" for one assertion. When `assertion`
    is not "?a", the pattern still binds ?a with a BIND at the end.
    """
    a = assertion
    bind = "" if a == "?a" else f"\n  BIND ({a} AS ?a)"
    p_bind = "" if patient == "?p" else f"\n  BIND ({patient} AS ?p)"
    return f"""
  {patient} triad:hasVisit ?v ; triad:name ?patientName .
  ?e triad:during ?v ; a ?type ; triad:code ?code ; triad:codeSystem ?codeSystem ; triad:display ?display .
  {TYPE_FILTER}
  {a} triad:about ?e ; triad:seq ?seq ; triad:assertedAt ?at ; triad:intent ?intent ; triad:source ?source ;
     triad:verification ?verification ; triad:statement ?statement .
  ?m triad:contains {a} ; triad:channel ?channel ; triad:origin ?origin .
  OPTIONAL {{ ?s triad:issues ?m ; triad:name ?staffName ; a ?staffRole . {ROLE_FILTER} }}
  OPTIONAL {{ {a} triad:supersedes ?supersedes }}
  OPTIONAL {{ ?supersededBy triad:supersedes {a} }}{bind}{p_bind}"""


def assertion_view_from_assertion(assertion: str = "$assertion") -> str:
    """The assertion view with a bound assertion first (assertions_by_id, chain): the patient is a variable."""
    a = assertion
    return f"""
  {a} triad:about ?e ; triad:seq ?seq ; triad:assertedAt ?at ; triad:intent ?intent ; triad:source ?source ;
     triad:verification ?verification ; triad:statement ?statement .
  ?e triad:during ?v ; a ?type ; triad:code ?code ; triad:codeSystem ?codeSystem ; triad:display ?display .
  {TYPE_FILTER}
  ?p triad:hasVisit ?v ; triad:name ?patientName .
  ?m triad:contains {a} ; triad:channel ?channel ; triad:origin ?origin .
  OPTIONAL {{ ?s triad:issues ?m ; triad:name ?staffName ; a ?staffRole . {ROLE_FILTER} }}
  OPTIONAL {{ {a} triad:supersedes ?supersedes }}
  OPTIONAL {{ ?supersededBy triad:supersedes {a} }}
  BIND ({a} AS ?a)"""


ASSERTION_VARIABLES = ("?a", "?e", "?m", "?v", "?p", "?patientName", "?type", "?code", "?codeSystem", "?display",
                       "?seq", "?at", "?intent", "?source", "?verification", "?statement", "?channel", "?origin",
                       "?s", "?staffName", "?staffRole", "?supersedes", "?supersededBy")
ASSERTION_SELECT = " ".join(ASSERTION_VARIABLES)

# The subtype values of each category: (the key in AssertionView.details, the property of the entry).
# The keys are the keys of DETAIL_KEYS in the SQLite repository. "medication" is the name of the Medication of
# the prescription (triad:prescribes, then triad:name). "members" of a care team is not here: SPARQL does not fix
# the order of GROUP_CONCAT, so the repository builds the text in Python (plan 5.5).
DETAILS: dict[str, tuple[tuple[str, str], ...]] = {
    "Diagnosis": (("onsetDate", "onsetDate"), ("abatementDate", "abatementDate"),
                  ("clinicalStatus", "clinicalStatus"), ("severity", "severity")),
    "Procedure": (("performedDate", "performedDate"), ("outcome", "procedureOutcome")),
    "Allergy": (("substance", "substance"), ("type", "allergyType"), ("allergyCategory", "allergyCategory"),
                ("criticality", "criticality"), ("clinicalStatus", "clinicalStatus")),
    "Observation": (("value", "value"), ("unit", "unit")),
    "LabOrder": (("testName", "testName"), ("priority", "priority"), ("specimen", "specimen")),
    "LabReport": (("issuedDate", "issuedDate"), ("conclusion", "conclusion")),
    "Prescription": (("medication", "medication"), ("dosage", "dosage"), ("frequency", "frequency"),
                     ("status", "prescriptionStatus")),
    "CareTeam": (("name", "name"), ("status", "careTeamStatus")),
}
DETAIL_PROPERTIES = tuple(sorted({prop for pairs in DETAILS.values() for _, prop in pairs} - {"medication"}))


def detail_optionals(entry: str = "?e") -> str:
    """OPTIONAL patterns for all subtype values of an entry: ?d_<property> (and ?d_medication)."""
    lines = [f"  OPTIONAL {{ {entry} triad:{prop} ?d_{prop} }}" for prop in DETAIL_PROPERTIES]
    lines.append(f"  OPTIONAL {{ {entry} triad:prescribes ?med . ?med triad:name ?d_medication }}")
    return "\n" + "\n".join(lines)


DETAIL_SELECT = " ".join(f"?d_{prop}" for prop in DETAIL_PROPERTIES) + " ?d_medication"


def details_of(category: str, row: dict) -> dict:
    """The details dict of AssertionView for a row with the ?d_ variables (the keys of DETAILS)."""
    return {key: row.get(f"d_{prop}") for key, prop in DETAILS.get(category, ())}
