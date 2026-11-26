"""The users of the picker on the knowledge graph: patients and staff (the UserRepository port).

This is the worked example of a SPARQL repository (README.md, "The pattern of a repository method"):
- each query is a template constant with "$name" placeholders and FROM $abox (SPARQL writing rule 1);
- the values go in the bindings: text as it is (terms.literal makes a simple literal), an individual as
  terms.iri(kind, id), a class as terms.class_term(name);
- a list uses paging.fetch_page (a COUNT query and a LIMIT/OFFSET query with the same pattern; the order ends
  with the integer id of the IRI);
- the rows become the same domain objects as in infrastructure/sqlite/users_repository.py.

The rules of the SQLite repository:
- A patient user has the key "Patient:<value>": the value of its first identifier in the order MRN, then
  Synthea. A patient with neither identifier is not a user. The detail is "born <date of birth>".
- A staff user has the key "<Role>:<identifier value>". The role is the subtype class (Doctor, Nurse, MOA).
  The detail is the names of its departments (WorksIn), each one time, by name, joined with ", ".
  SPARQL does not fix the order of GROUP_CONCAT, so Python makes this text (plan 5.5).
- The order: the demo users first (in the order of `pinned_keys`), then the name (case is not important), then
  the key, then the id.
"""
from __future__ import annotations

from typing import Optional, Sequence

from domain.access import Actor
from domain.views import UserView

from application.paging import Page, PageRequest
from infrastructure.sparql import fragments, paging, terms
from infrastructure.sparql.terms import Term, id_of, iri
from infrastructure.sparql.unit_of_work import KgSession

MRN_SYSTEM = "https://triad.example/fhir/sid/mrn"
SYNTHEA_SYSTEM = "https://github.com/synthetichealth/synthea"


def patient_users(subject: str = "?u") -> str:
    """The pattern of the patient users: ?u ?role ?name ?detail ?key ?n (the id). Needs $mrn and $synthea.

    The system is compared in a FILTER, not as a constant of the triple pattern: about 62,000 individuals have the
    Synthea system, and Oxigraph then starts the OPTIONAL there (15 s on the full graph instead of 8 ms).
    """
    return f"""
    {subject} a triad:Patient ; triad:name ?name ; triad:dateOfBirth ?dob .
    OPTIONAL {{ {subject} triad:identifier ?mrnIdentifier .
               ?mrnIdentifier triad:identifierValue ?mrnValue ; triad:identifierSystem ?mrnSystem .
               FILTER (?mrnSystem = $mrn) }}
    OPTIONAL {{ {subject} triad:identifier ?syntheaIdentifier .
               ?syntheaIdentifier triad:identifierValue ?syntheaValue ; triad:identifierSystem ?syntheaSystem .
               FILTER (?syntheaSystem = $synthea) }}
    BIND ("Patient" AS ?role)
    BIND (CONCAT("born ", STR(?dob)) AS ?detail)
    BIND (CONCAT("Patient:", COALESCE(?mrnValue, ?syntheaValue)) AS ?key)
    {fragments.bind_id(subject, "patient", "?n")}"""


def staff_users(subject: str = "?u") -> str:
    """The pattern of the staff users: ?u ?role ?name ?key ?n (the detail comes from a second query).

    The BIND of ?key writes the expression of ?role again (SPARQL writing rule 10): on Virtuoso, a BIND that
    reads the variable of another BIND of the same group sees no value, with no error (the key was ":E1001")."""
    return f"""
    {subject} a triad:Staff ; a ?roleClass ; triad:name ?name ; triad:identifierValue ?value .
    {fragments.classes_in("?roleClass", fragments.STAFF_ROLES)}
    BIND (STRAFTER(STR(?roleClass), "#") AS ?role)
    BIND (CONCAT(STRAFTER(STR(?roleClass), "#"), ":", ?value) AS ?key)
    {fragments.bind_id(subject, "staff", "?n")}"""


# All users in one pattern: the patients, then the staff. A user with no key is not in the list.
USERS = f"""
  {{ {patient_users()}
  }}
  UNION
  {{ {staff_users()}
  }}
  FILTER (BOUND(?key))"""

USER_COLUMNS = "?u ?role ?name ?detail ?key ?n"

PATIENT_ACTOR = """
SELECT ?p ?name ?system FROM $abox WHERE {
  ?identifier triad:identifierValue $value ; triad:identifierSystem ?system .
  FILTER (?system IN ($mrn, $synthea))
  ?p triad:identifier ?identifier ; a triad:Patient ; triad:name ?name .
}
ORDER BY IF(?system = $mrn, 0, 1) LIMIT 1"""

STAFF_ACTOR = f"""
SELECT ?s ?name ?system FROM $abox WHERE {{
  ?s triad:identifierValue $value ; a $role ; triad:name ?name ; triad:identifierSystem ?system .
}}
ORDER BY {fragments.id_order("?s", "staff")} LIMIT 1"""

DEPARTMENTS = """
SELECT DISTINCT ?u ?department FROM $abox WHERE {
  VALUES ?u { $staff }
  ?w triad:ofStaff ?u ; triad:atDepartment ?d .
  ?d triad:name ?department .
}"""


def pinned_rank(pinned_keys: Sequence[str]) -> str:
    """The ORDER BY key of the demo users: their place in `pinned_keys` (bindings $pin0 ...), then all others."""
    text = str(len(pinned_keys))
    for index in range(len(pinned_keys) - 1, -1, -1):
        text = f"IF(?key = $pin{index}, {index}, {text})"
    return text


def pin_bindings(pinned_keys: Sequence[str]) -> dict:
    return {f"pin{i}": key for i, key in enumerate(pinned_keys)}


class SparqlUserRepository:
    def __init__(self, session: KgSession):
        self.session = session

    def actor(self, role: str, value: str) -> Optional[Actor]:
        if role == "Patient":
            rows = self.session.select(PATIENT_ACTOR, {"value": value, "mrn": MRN_SYSTEM,
                                                       "synthea": SYNTHEA_SYSTEM})
            if not rows:
                return None
            r = rows[0]
            return Actor(role="Patient", key=f"Patient:{value}", name=r["name"], system=r["system"], value=value,
                         patient_id=id_of(r["p"], "patient"))
        if role not in fragments.STAFF_ROLES:
            return None
        rows = self.session.select(STAFF_ACTOR, {"value": value, "role": terms.class_term(role)})
        if not rows:
            return None
        r = rows[0]
        return Actor(role=role, key=f"{role}:{value}", name=r["name"], system=r["system"], value=value,
                     staff_id=id_of(r["s"], "staff"))

    def _departments(self, staff_iris: Sequence[str]) -> dict[str, str]:
        """The detail of each staff user: the names of its departments, each one time, by name."""
        if not staff_iris:
            return {}
        names: dict[str, set[str]] = {}
        rows = self.session.select(DEPARTMENTS, {"staff": Term(" ".join(f"<{u}>" for u in staff_iris))})
        for r in rows:
            names.setdefault(r["u"], set()).add(r["department"])
        return {u: ", ".join(sorted(found)) for u, found in names.items()}

    def _views(self, rows: list[dict], pinned_keys: Sequence[str]) -> list[UserView]:
        staff = [r["u"] for r in rows if r["role"] != "Patient"]
        details = self._departments(staff)
        out = []
        for r in rows:
            is_patient = r["role"] == "Patient"
            out.append(UserView(key=r["key"], role=r["role"], name=r["name"],
                                detail=r["detail"] if is_patient else details.get(r["u"], ""),
                                pinned=r["key"] in pinned_keys,
                                patient_id=id_of(r["u"], "patient") if is_patient else None,
                                staff_id=None if is_patient else id_of(r["u"], "staff")))
        return out

    def users(self, role: Optional[str], q: Optional[str], pinned_keys: Sequence[str],
              page: PageRequest) -> Page[UserView]:
        """One page of the users: the demo users first (in the order of `pinned_keys`), then by name, then key."""
        where = USERS
        bindings: dict = {"mrn": MRN_SYSTEM, "synthea": SYNTHEA_SYSTEM, **pin_bindings(pinned_keys)}
        if role:
            where += "\n  FILTER (?role = $role)"
            bindings["role"] = role
        if q:
            where += "\n  FILTER (" + fragments.contains("?name", "q") + ")"
            bindings["q"] = q.lower()
        order = [pinned_rank(pinned_keys), "LCASE(?name)", "?key", "?n"]
        return paging.fetch_page(self.session.client, USER_COLUMNS, where, bindings, order, page,
                                 lambda rows: self._views(rows, pinned_keys))

    def user(self, role: str, value: str, pinned_keys: Sequence[str]) -> Optional[UserView]:
        actor = self.actor(role, value)
        if actor is None:
            return None
        if actor.is_patient:
            pattern, subject = patient_users("$user"), iri("patient", actor.patient_id)
        else:
            pattern, subject = staff_users("$user"), iri("staff", actor.staff_id)
        rows = self.session.select(
            f"SELECT {USER_COLUMNS} FROM $abox WHERE {{{pattern}\n    BIND ($user AS ?u)\n    FILTER (BOUND(?key))\n}}",
            {"user": subject, "mrn": MRN_SYSTEM, "synthea": SYNTHEA_SYSTEM})
        rows = [r for r in rows if r["role"] == role]
        return self._views(rows[:1], pinned_keys)[0] if rows else None

