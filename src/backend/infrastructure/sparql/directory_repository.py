"""Departments, locations, staff and medications on the knowledge graph (the DirectoryRepository port).

The same results as infrastructure/sqlite/directory_repository.py (SqliteDirectoryRepository): the same views, the
same order (the integer id of the IRI breaks the ties) and the same errors. The pattern of each method is the
pattern of users_repository.py and README.md: a template constant with "$name" placeholders, FROM $abox, and the
values in the bindings.

How the rows of SQLite are in the graph (models/semantic/ontology.md):
- A department, a location and a medication are individuals of their class. Each nullable column has an OPTIONAL.
- Location.Type holds the name of the department of the location (a value, not a foreign key): triad:locationType.
  A new department name changes the locationType of each location with the old name, as in SQLite.
- A staff member is ONE individual with two types: triad:Staff and its role (triad:Doctor, triad:Nurse or
  triad:MOA). The subtype values (licenseNumber, qualification, designation, certificationNumber, desk,
  phoneExtension) are on the same individual. StaffLanguage is the multivalued literal triad:language.
- WorksIn is an individual (kg:works-in/<Id>): triad:ofStaff, triad:atDepartment, triad:roleCode, triad:specialty.

The orders (the same as SQLite):
- departments and medications: by name (the text), then the id; locations: by the id;
- staff: the hospital staff (the employee identifier system) first, then by name, then the id;
- the departments of a staff member: by the id of the WorksIn individual;
- the languages of a staff member: by name. A set of literals has no order, so Python sorts them (plan 5.5).
  SQLite uses the same order ("ORDER BY Language").

The text rules:
- SQLite lower() lowers only the ASCII letters. An equality of names ("lower(Name) = lower(?)") selects the rows
  with LCASE in SPARQL (these rows include all rows of the SQLite rule), then Python applies the SQLite rule
  (ascii_lower). So department_by_name, department_name_exists and the department filters give the SQLite rows.
- The text search ("q") is CONTAINS(LCASE(...)) (rule 7). It is literal: "%" and "_" are not wildcards as in
  SQLite LIKE, and LCASE lowers all letters (README.md, "Known limits").

The writes go into the write buffer of the unit of work (one INSERT DATA for the new rows; one DELETE/INSERT WHERE
for each changed property). A NOT NULL or CHECK rule of the DDL gives the error of SQLite at once (Invalid, 422,
fields.database), in the order of the SQLite statements. The keys (UNIQUE) are guards (guards_directory.py), and
the foreign keys are the guard "foreign-keys" (guards.py): both give Conflict (409) at the commit.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from domain.records import Address
from domain.views import DepartmentView, Identifier, LocationView, MedicationView, StaffDepartment, StaffView

from application.paging import Page, PageRequest
from infrastructure.sparql import fragments, ids, paging, terms
from infrastructure.sparql.guards import check_failed
from infrastructure.sparql.terms import Term, id_of, iri
from infrastructure.sparql.unit_of_work import KgSession, WriteBuffer
from models.semantic import vocabulary as V

EMPLOYEE_SYSTEM = "https://triad.example/fhir/sid/employee"
ROLES = fragments.STAFF_ROLES


def _columns(table: str, columns: Sequence[str]) -> dict[str, str]:
    """The ontology property of each column of a table (vocabulary.py): {column: property}."""
    return {column: V.COLUMNS[(table, column)][0] for column in columns}


ADDRESS = ("Street", "City", "Region", "PostalCode", "Country")
DEPARTMENT = _columns("Department", ("IdentifierSystem", "IdentifierValue", "Name", "Type", "PhoneNumber", "Email")
                      + ADDRESS)
LOCATION = _columns("Location", ("IdentifierSystem", "IdentifierValue", "Name", "Type", "PhysicalType", "PhoneNumber")
                    + ADDRESS)
STAFF = _columns("Staff", ("IdentifierSystem", "IdentifierValue", "Name", "Sex", "Email", "PhoneNumber", "Active"))
STAFF_CHANGE = ("Sex", "Email", "PhoneNumber", "Active")        # the columns that update_staff can change
SUBTYPE = {"Doctor": _columns("Doctor", ("LicenseNumber", "Qualification")),
           "Nurse": _columns("Nurse", ("LicenseNumber", "Designation")),
           "MOA": _columns("MOA", ("CertificationNumber", "Desk", "PhoneExtension"))}
MEDICATION = _columns("Medication", ("Code", "CodeSystem", "Name", "Form", "Manufacturer"))

# The NOT NULL columns of each table, in the order of the DDL (SQLite reports the first one), and the CHECK rules
# with the text of the SQLite error ("CHECK constraint failed: <text>"). A column with a DEFAULT has it here.
NOT_NULL = {
    "Department": ("IdentifierSystem", "IdentifierValue", "Name"),
    "Location": ("IdentifierSystem", "IdentifierValue", "Name"),
    "Staff": ("IdentifierSystem", "IdentifierValue", "Name", "Active", "Role"),
    "Doctor": (), "Nurse": ("Designation",), "MOA": ("Desk",),
    "WorksIn": ("DepartmentId", "RoleCode"),
    "StaffLanguage": ("Language",),
    "Medication": ("Code", "CodeSystem", "Name"),
}
DEFAULTS = {"Staff": {"Active": 1}}
CHECKS = {
    "Staff": (("Sex", ("female", "male", "other", "unknown"), "Sex IN ('female', 'male', 'other', 'unknown')"),
              ("Active", (0, 1), "Active IN (0, 1)"),
              ("Role", ROLES, "Role IN ('Doctor', 'Nurse', 'MOA')")),
    "Nurse": (("Designation", ("RN", "LPN", "RPN", "NP"), "Designation IN ('RN', 'LPN', 'RPN', 'NP')"),),
}

_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def ascii_lower(text: str) -> str:
    """lower() of SQLite: only the ASCII letters A-Z become lower case."""
    return text.translate(_ASCII_LOWER)


def check_row(table: str, values: Mapping[str, Any], insert: bool) -> None:
    """The NOT NULL and CHECK rules of the DDL for one INSERT (insert=True) or UPDATE of a row of `table`.

    An INSERT checks each NOT NULL column (a missing column has its DEFAULT, or NULL). An UPDATE checks only the
    columns that it sets. SQLite checks NOT NULL first, then CHECK, each in the order of the columns.
    """
    row = {**DEFAULTS.get(table, {}), **values} if insert else dict(values)
    for column in NOT_NULL.get(table, ()):
        if (insert or column in row) and row.get(column) is None:
            raise check_failed(f"NOT NULL constraint failed: {table}.{column}")
    for column, allowed, text in CHECKS.get(table, ()):
        value = row.get(column)
        if value is not None and value not in allowed:
            raise check_failed(f"CHECK constraint failed: {text}")


def props(columns: Mapping[str, str], values: Mapping[str, Any]) -> dict[str, Any]:
    """{property: value} for the columns of `values` (None gives no triple)."""
    return {prop: values[column] for column, prop in columns.items() if column in values}


def replace_all(buf: WriteBuffer, subject: Term, columns: Mapping[str, str], values: Mapping[str, Any]) -> None:
    """One replace (one DELETE/INSERT WHERE at the commit) for each column of `values`. None removes the value."""
    for column, prop in columns.items():
        if column in values:
            buf.replace(subject, prop, values[column])


def buffered(buf: WriteBuffer, kind: str, subject: Term):
    """The new subject of this write with this IRI, or None (read your writes, as SQLite in one transaction)."""
    return next((new for new in buf.created(kind) if new.iri == subject), None)


def iri_list(values: Sequence[str]) -> Term:
    """The IRIs of a VALUES block: <a> <b> ... (VALUES has no commas)."""
    return Term(" ".join(v if v.startswith("<") else f"<{v}>" for v in values))


def empty_page(page: PageRequest) -> Page:
    return Page(items=[], total=0, limit=page.limit, offset=page.offset)


def row_pattern(subject: str, cls: str, required: Mapping[str, str], optional: Mapping[str, str],
                variable: str, extra: Sequence[str] = (), binds: Sequence[str] = ()) -> str:
    """The pattern of one row: the class and the NOT NULL values, then one OPTIONAL for each nullable value.

    `subject` is a variable or a placeholder ("$d"). For a placeholder, a BIND at the end gives `variable`.
    The keys of `required` and `optional` are the names of the variables; the values are the properties.
    `extra` comes after the NOT NULL values; `binds` at the end of the group (SPARQL writing rule 5).
    """
    values = " ; ".join(f"triad:{prop} ?{name}" for name, prop in required.items())
    lines = [f"  {subject} a triad:{cls} ; {values} .", *(f"  {line}" for line in extra)]
    lines += [f"  OPTIONAL {{ {subject} triad:{prop} ?{name} }}" for name, prop in optional.items()]
    if subject != variable:
        lines.append(f"  BIND ({subject} AS {variable})")
    lines += [f"  {line}" for line in binds]
    return "\n" + "\n".join(lines)


def select_of(variable: str, required: Mapping[str, str], optional: Mapping[str, str], *extra: str) -> str:
    return " ".join([variable, *(f"?{name}" for name in (*required, *optional)), *extra])


# ---------------------------------------------------------------------------------------------
# Departments

IDENT_VARS = {"system": "identifierSystem", "value": "identifierValue", "name": "name"}
ADDRESS_VARS = {"street": "street", "city": "city", "region": "region", "postalCode": "postalCode",
                "country": "country"}
DEPARTMENT_OPTIONAL = {"type": "departmentType", "phone": "phoneNumber", "email": "email", **ADDRESS_VARS}
DEPARTMENT_SELECT = select_of("?d", IDENT_VARS, DEPARTMENT_OPTIONAL)


def department_pattern(subject: str = "?d") -> str:
    return row_pattern(subject, "Department", IDENT_VARS, DEPARTMENT_OPTIONAL, "?d")


DEPARTMENT_ORDER = ["?name", fragments.id_order("?d", "department")]
DEPARTMENT_ONE = f"SELECT {DEPARTMENT_SELECT} FROM $abox WHERE {{{department_pattern('$d')}\n}}"
DEPARTMENT_BY_NAME = (f"SELECT {DEPARTMENT_SELECT} FROM $abox WHERE {{{department_pattern()}\n"
                      f"  FILTER (LCASE(?name) = LCASE($name))\n}}\nORDER BY {fragments.id_order('?d', 'department')}")
DEPARTMENT_NAMES = """
SELECT ?d ?name FROM $abox WHERE {
  ?d a triad:Department ; triad:name ?name .
  FILTER (LCASE(?name) = LCASE($name))
}"""
DEPARTMENT_KEYS = """
SELECT ?d ?name ?value FROM $abox WHERE {
  ?d a triad:Department ; triad:name ?name ; triad:identifierValue ?value .
}"""
# The staff count of each department: the staff members of its WorksIn individuals, each one time.
STAFF_COUNTS = """
SELECT ?d (COUNT(DISTINCT ?member) AS ?n) FROM $abox WHERE {
  VALUES ?d { $departments }
  ?w triad:atDepartment ?d ; triad:ofStaff ?member .
}
GROUP BY ?d"""
# department_use: (the staff members, each one time; the locations whose locationType is the name).
# Each branch binds ?x and a tag. (Oxigraph 0.3 counts an unbound ?x as one value in COUNT(DISTINCT ?x), so the
# branches do not use two variables.)
DEPARTMENT_USE = """
SELECT ?what (COUNT(DISTINCT ?x) AS ?n) FROM $abox WHERE {
  { ?w triad:atDepartment $d ; triad:ofStaff ?x .
    BIND ("staff" AS ?what) }
  UNION
  { $d triad:name ?name . ?x triad:locationType ?name ; a triad:Location .
    BIND ("locations" AS ?what) }
}
GROUP BY ?what"""
DEPARTMENT_NAME = "SELECT ?name FROM $abox WHERE { $d a triad:Department ; triad:name ?name }"
LOCATIONS_OF_TYPE = "SELECT ?l FROM $abox WHERE { ?l triad:locationType $type ; a triad:Location }"

# ---------------------------------------------------------------------------------------------
# Locations

LOCATION_OPTIONAL = {"type": "locationType", "physicalType": "physicalType", "phone": "phoneNumber", **ADDRESS_VARS}
LOCATION_SELECT = select_of("?l", IDENT_VARS, LOCATION_OPTIONAL)


def location_pattern(subject: str = "?l") -> str:
    return row_pattern(subject, "Location", IDENT_VARS, LOCATION_OPTIONAL, "?l")


LOCATION_ONE = f"SELECT {LOCATION_SELECT} FROM $abox WHERE {{{location_pattern('$l')}\n}}"
# The identifier value is the bound start; the system is compared in a FILTER (README.md, rule 4).
LOCATION_BY_IDENTIFIER = (f"SELECT {LOCATION_SELECT} FROM $abox WHERE {{\n  ?l triad:identifierValue $value ."
                          f"{location_pattern()}\n  FILTER (?system = $system)\n}}\n"
                          f"ORDER BY {fragments.id_order('?l', 'location')}")
# The locations of the page that a visit used (SQLite: EXISTS VisitLocation).
LOCATIONS_IN_USE = """
SELECT DISTINCT ?l FROM $abox WHERE {
  VALUES ?l { $locations }
  ?vl triad:atLocation ?l .
}"""
# The values for the department filter of the location list: the location types and the departments.
LOCATION_TYPES = """
SELECT DISTINCT ?type ?d ?name ?value FROM $abox WHERE {
  { ?l a triad:Location ; triad:locationType ?type }
  UNION
  { ?d a triad:Department ; triad:name ?name ; triad:identifierValue ?value }
}"""

# ---------------------------------------------------------------------------------------------
# Staff

STAFF_OPTIONAL = {"active": "active", "sex": "staffSex", "email": "email", "phone": "phoneNumber",
                  "license": "licenseNumber", "qualification": "qualification", "designation": "designation",
                  "certification": "certificationNumber", "desk": "desk", "extension": "phoneExtension"}
STAFF_SELECT = select_of("?s", IDENT_VARS, STAFF_OPTIONAL, "?role")


def staff_pattern(subject: str = "?s") -> str:
    """One staff row: ?roleClass is the subtype class (Doctor, Nurse or MOA) and ?role its name."""
    return row_pattern(subject, "Staff", IDENT_VARS, STAFF_OPTIONAL, "?s",
                       extra=(f"{subject} a ?roleClass .", fragments.classes_in("?roleClass", ROLES)),
                       binds=('BIND (STRAFTER(STR(?roleClass), "#") AS ?role)',))


STAFF_ORDER = ["IF(?system = $employee, 0, 1)", "?name", fragments.id_order("?s", "staff")]
STAFF_ONE = f"SELECT {STAFF_SELECT} FROM $abox WHERE {{{staff_pattern('$s')}\n}}"
# The identifier value is the bound start; the system is compared in a FILTER (README.md, rule 4).
STAFF_BY_IDENTIFIER = (f"SELECT {STAFF_SELECT} FROM $abox WHERE {{\n  ?s triad:identifierValue $value ."
                       f"{staff_pattern()}\n  FILTER (?system = $system)\n}}\n"
                       f"ORDER BY {fragments.id_order('?s', 'staff')}")
# The departments (WorksIn) and the languages of the staff members of a page: one query, Python orders them.
STAFF_DETAILS = """
SELECT ?s ?w ?dep ?depName ?roleCode ?specialty ?language FROM $abox WHERE {
  VALUES ?s { $staff }
  { ?w triad:ofStaff ?s ; triad:atDepartment ?dep ; triad:roleCode ?roleCode .
    ?dep triad:name ?depName .
    OPTIONAL { ?w triad:specialty ?specialty } }
  UNION
  { ?s triad:language ?language }
}"""
STAFF_ROLE = f"""
SELECT ?roleClass FROM $abox WHERE {{
  $s a ?roleClass .
  {fragments.classes_in('?roleClass', ROLES)}
}}"""
# staff_use: the messages that the staff member issued, its WorksIn individuals and its care-team memberships
# (a CareTeamMember holds the identifier of the staff member as values, not as a link).
STAFF_USE = """
SELECT ?what (COUNT(DISTINCT ?x) AS ?n) FROM $abox WHERE {
  { $s triad:issues ?x .
    BIND ("messages" AS ?what) }
  UNION
  { ?x triad:ofStaff $s .
    BIND ("departments" AS ?what) }
  UNION
  { $s triad:identifierSystem ?system ; triad:identifierValue ?value .
    ?x triad:memberValue ?value ; triad:memberSystem ?memberSystem .
    FILTER (?memberSystem = ?system)
    BIND ("careTeams" AS ?what) }
}
GROUP BY ?what"""

# ---------------------------------------------------------------------------------------------
# Medications

MEDICATION_REQUIRED = {"code": "code", "codeSystem": "codeSystem", "name": "name"}
MEDICATION_OPTIONAL = {"form": "form", "manufacturer": "manufacturer"}
MEDICATION_SELECT = select_of("?m", MEDICATION_REQUIRED, MEDICATION_OPTIONAL)


def medication_pattern(subject: str = "?m") -> str:
    return row_pattern(subject, "Medication", MEDICATION_REQUIRED, MEDICATION_OPTIONAL, "?m")


MEDICATION_ORDER = ["?name", fragments.id_order("?m", "medication")]
MEDICATION_ONE = f"SELECT {MEDICATION_SELECT} FROM $abox WHERE {{{medication_pattern('$m')}\n}}"
MEDICATION_IN_USE = "ASK FROM $abox WHERE { ?entry triad:prescribes $m }"


def name_or_identifier() -> str:
    """The search of a department or a location: part of the name or of the identifier value (any case)."""
    return f"\n  FILTER ({fragments.contains('?name', 'q')} || {fragments.contains('?value', 'q')})"


def address_of(r: Mapping[str, Any]) -> Address:
    return Address(street=r["street"], city=r["city"], region=r["region"], postal_code=r["postalCode"],
                   country=r["country"])


class SparqlDirectoryRepository:
    """The DirectoryRepository port on SPARQL."""

    def __init__(self, session: KgSession):
        self.session = session

    # ----- departments -----

    def _department_views(self, rows: list[dict]) -> list[DepartmentView]:
        if not rows:
            return []
        counts = {r["d"]: int(r["n"]) for r in self.session.select(
            STAFF_COUNTS, {"departments": iri_list([r["d"] for r in rows])})}
        return [DepartmentView(id=id_of(r["d"], "department"), identifier=Identifier(r["system"], r["value"]),
                               name=r["name"], type=r["type"], phone_number=r["phone"], email=r["email"],
                               address=address_of(r), staff_count=counts.get(r["d"], 0)) for r in rows]

    def departments(self, q: Optional[str], page: PageRequest) -> Page[DepartmentView]:
        where, bindings = department_pattern(), {}
        if q:
            where += name_or_identifier()
            bindings["q"] = q.lower()
        return paging.fetch_page(self.session.client, DEPARTMENT_SELECT, where, bindings, DEPARTMENT_ORDER, page,
                                 self._department_views)

    def department(self, department_id: int) -> Optional[DepartmentView]:
        views = self._department_views(self.session.select(DEPARTMENT_ONE, {"d": iri("department", department_id)}))
        return views[0] if views else None

    def department_by_name(self, name: str) -> Optional[DepartmentView]:
        """The department with this name (case is not important), the first by id."""
        rows = [r for r in self.session.select(DEPARTMENT_BY_NAME, {"name": name})
                if ascii_lower(r["name"]) == ascii_lower(name)]
        return self._department_views(rows[:1])[0] if rows else None

    def department_name_exists(self, name: str, except_id: Optional[int] = None) -> bool:
        return any(ascii_lower(r["name"]) == ascii_lower(name) and id_of(r["d"], "department") != except_id
                   for r in self.session.select(DEPARTMENT_NAMES, {"name": name}))

    def add_department(self, values: dict) -> int:
        buf = self.session.write_buffer()
        check_row("Department", values, insert=True)
        return buf.create("department", props(DEPARTMENT, values))

    def update_department(self, department_id: int, values: dict) -> None:
        buf = self.session.write_buffer()
        check_row("Department", values, insert=False)
        subject = iri("department", department_id)
        old = None
        if "Name" in values:
            new = buffered(buf, "department", subject)
            found = [{"name": new.get("name")}] if new else self.session.select(DEPARTMENT_NAME, {"d": subject})
            old = found[0]["name"] if found else None
        replace_all(buf, subject, DEPARTMENT, values)
        if old is not None and values["Name"] != old:
            # A location keeps the department name as a value. Change it with the department.
            for row in self.session.select(LOCATIONS_OF_TYPE, {"type": old}):
                buf.replace(Term(f"<{row['l']}>"), "locationType", values["Name"])
            for location_id in buf.find("location", locationType=old):
                buf.replace(iri("location", location_id), "locationType", values["Name"])

    def delete_department(self, department_id: int) -> None:
        self.session.write_buffer().delete_subject("department", department_id)

    def department_use(self, department_id: int) -> tuple[int, int]:
        found = {r["what"]: int(r["n"]) for r in self.session.select(DEPARTMENT_USE,
                                                                       {"d": iri("department", department_id)})}
        return found.get("staff", 0), found.get("locations", 0)

    def _matching_departments(self, text: str) -> list[Term]:
        """The departments of a filter: the name (case is not important), the identifier value or the id."""
        return [Term(f"<{r['d']}>") for r in self.session.select(DEPARTMENT_KEYS)
                if ascii_lower(r["name"]) == ascii_lower(text) or r["value"] == text
                or str(id_of(r["d"], "department")) == text]

    # ----- locations -----

    def _location_views(self, rows: list[dict]) -> list[LocationView]:
        if not rows:
            return []
        used = {r["l"] for r in self.session.select(LOCATIONS_IN_USE, {"locations": iri_list([r["l"] for r in rows])})}
        return [LocationView(id=id_of(r["l"], "location"), identifier=Identifier(r["system"], r["value"]),
                             name=r["name"], department=r["type"], physical_type=r["physicalType"],
                             phone_number=r["phone"], address=address_of(r), in_use=r["l"] in used) for r in rows]

    def _location_types(self, department: str) -> list[str]:
        """The location types of the department filter (SQLite: lower(l.Type) = lower(?) OR l.Type IN (SELECT Name
        FROM Department WHERE IdentifierValue = ? OR CAST(Id AS TEXT) = ?))."""
        types: set[str] = set()
        for r in self.session.select(LOCATION_TYPES):
            if r["type"] is not None and ascii_lower(r["type"]) == ascii_lower(department):
                types.add(r["type"])
            if r["d"] is not None and (r["value"] == department or str(id_of(r["d"], "department")) == department):
                types.add(r["name"])
        return sorted(types)

    def locations(self, department: Optional[str], q: Optional[str], page: PageRequest) -> Page[LocationView]:
        where, bindings = location_pattern(), {}
        if department:
            types = self._location_types(department)
            if not types:
                return empty_page(page)
            where += "\n  FILTER (?type IN ($types))"
            bindings["types"] = types
        if q:
            where += name_or_identifier()
            bindings["q"] = q.lower()
        return paging.fetch_page(self.session.client, LOCATION_SELECT, where, bindings,
                                 [fragments.id_order("?l", "location")], page, self._location_views)

    def location(self, location_id: int) -> Optional[LocationView]:
        views = self._location_views(self.session.select(LOCATION_ONE, {"l": iri("location", location_id)}))
        return views[0] if views else None

    def location_by_identifier(self, system: str, value: str) -> Optional[LocationView]:
        views = self._location_views(self.session.select(LOCATION_BY_IDENTIFIER, {"system": system, "value": value}))
        return views[0] if views else None

    def add_location(self, values: dict) -> int:
        buf = self.session.write_buffer()
        check_row("Location", values, insert=True)
        return buf.create("location", props(LOCATION, values))

    def update_location(self, location_id: int, values: dict) -> None:
        buf = self.session.write_buffer()
        check_row("Location", values, insert=False)
        replace_all(buf, iri("location", location_id), LOCATION, values)

    def delete_location(self, location_id: int) -> None:
        self.session.write_buffer().delete_subject("location", location_id)

    # ----- staff -----

    def _staff_views(self, rows: list[dict]) -> list[StaffView]:
        if not rows:
            return []
        works: dict[str, list[tuple[int, StaffDepartment]]] = {}
        languages: dict[str, set[str]] = {}
        for r in self.session.select(STAFF_DETAILS, {"staff": iri_list([r["s"] for r in rows])}):
            if r["w"] is not None:
                works.setdefault(r["s"], []).append((id_of(r["w"], "works-in"), StaffDepartment(
                    id_of(r["dep"], "department"), r["depName"], r["roleCode"], r["specialty"])))
            elif r["language"] is not None:
                languages.setdefault(r["s"], set()).add(r["language"])
        out = []
        for r in rows:
            role = r["role"]
            out.append(StaffView(
                id=id_of(r["s"], "staff"), key=f"{role}:{r['value']}", identifier=Identifier(r["system"], r["value"]),
                name=r["name"], role=role, sex=r["sex"], email=r["email"], phone_number=r["phone"],
                active=bool(r["active"]),
                departments=[dept for _, dept in sorted(works.get(r["s"], []), key=lambda item: item[0])],
                languages=sorted(languages.get(r["s"], ())),
                license_number=r["license"] if role in ("Doctor", "Nurse") else None,
                qualification=r["qualification"] if role == "Doctor" else None,
                designation=r["designation"] if role == "Nurse" else None,
                certification_number=r["certification"] if role == "MOA" else None,
                desk=r["desk"] if role == "MOA" else None,
                phone_extension=r["extension"] if role == "MOA" else None))
        return out

    def staff_list(self, role: Optional[str], department: Optional[str], q: Optional[str],
                   page: PageRequest) -> Page[StaffView]:
        """The staff of the hospital (employee identifiers) first, then the Synthea staff; by name in each group."""
        where, bindings = staff_pattern(), {"employee": EMPLOYEE_SYSTEM}
        if role:
            if role not in ROLES:
                return empty_page(page)
            where += "\n  FILTER (?roleClass = $roleClass)"
            bindings["roleClass"] = terms.class_term(role)
        if q:
            where += f"\n  FILTER ({fragments.contains('?name', 'q')} || ?value = $exact)"
            bindings.update(q=q.lower(), exact=q)
        if department:
            found = self._matching_departments(department)
            if not found:
                return empty_page(page)
            where += ("\n  FILTER EXISTS { ?w triad:ofStaff ?s ; triad:atDepartment ?dep . "
                      "FILTER (?dep IN ($departments)) }")
            bindings["departments"] = found
        return paging.fetch_page(self.session.client, STAFF_SELECT, where, bindings, STAFF_ORDER, page,
                                 self._staff_views)

    def staff(self, staff_id: int) -> Optional[StaffView]:
        views = self._staff_views(self.session.select(STAFF_ONE, {"s": iri("staff", staff_id)}))
        return views[0] if views else None

    def staff_by_identifier(self, system: str, value: str) -> Optional[StaffView]:
        views = self._staff_views(self.session.select(STAFF_BY_IDENTIFIER, {"system": system, "value": value}))
        return views[0] if views else None

    def add_staff(self, values: dict) -> int:
        """The staff individual (with its role as a second type, the subtype values and the languages) and one
        WorksIn individual. The checks come in the order of the SQLite statements: Staff, the subtype, WorksIn,
        StaffLanguage."""
        buf = self.session.write_buffer()
        check_row("Staff", values, insert=True)
        role = values["Role"]
        subtype = SUBTYPE[role]
        sub = {column: value for column, value in values.get("subtype", {}).items() if column in subtype}
        check_row(role, sub, insert=True)
        check_row("WorksIn", {"DepartmentId": values["department_id"], "RoleCode": values["role_code"]}, insert=True)
        languages = list(values.get("languages", []))
        for language in languages:
            check_row("StaffLanguage", {"Language": language}, insert=True)
        row = props(STAFF, values)
        row["active"] = bool(values.get("Active", DEFAULTS["Staff"]["Active"]))
        row.update(props(subtype, sub))
        row["language"] = languages
        staff_id = buf.create("staff", row, types=(role,))
        buf.create("works-in", {"ofStaff": iri("staff", staff_id), "atDepartment": iri("department",
                                                                                         values["department_id"]),
                                "roleCode": values["role_code"], "specialty": values.get("specialty")})
        return staff_id

    def update_staff(self, staff_id: int, values: dict) -> None:
        buf = self.session.write_buffer()
        subject = iri("staff", staff_id)
        change = {column: values[column] for column in STAFF_CHANGE if column in values}
        check_row("Staff", change, insert=False)
        if "Active" in change:
            change["Active"] = bool(change["Active"])
        replace_all(buf, subject, STAFF, change)
        if values.get("subtype"):
            new = buffered(buf, "staff", subject)
            if new:
                roles = [t for t in new.types if t in ROLES]
            else:
                roles = [terms.name_of(r["roleClass"]) for r in self.session.select(STAFF_ROLE, {"s": subject})]
            if roles:
                subtype = SUBTYPE[roles[0]]
                sub = {column: value for column, value in values["subtype"].items() if column in subtype}
                check_row(roles[0], sub, insert=False)
                replace_all(buf, subject, subtype, sub)
        if "languages" in values:
            languages = list(values["languages"])
            for language in languages:
                check_row("StaffLanguage", {"Language": language}, insert=True)
            buf.replace(subject, "language", languages)

    def staff_use(self, staff_id: int) -> dict[str, int]:
        found = {r["what"]: int(r["n"]) for r in self.session.select(STAFF_USE, {"s": iri("staff", staff_id)})}
        return {name: found.get(name, 0) for name in ("messages", "departments", "careTeams")}

    def delete_staff(self, staff_id: int) -> None:
        """Delete the staff individual: its types (also the role), its values (also the subtype values) and its
        languages, as SQLite deletes the StaffLanguage, Doctor, Nurse, MOA and Staff rows. A WorksIn individual or
        a message of the staff member stops the delete (the guard "foreign-keys": Conflict, as SQLite)."""
        self.session.write_buffer().delete_subject("staff", staff_id)

    # ----- medications -----

    @staticmethod
    def _medication(r: dict) -> MedicationView:
        return MedicationView(id=id_of(r["m"], "medication"), code=r["code"], code_system=r["codeSystem"],
                              name=r["name"], form=r["form"], manufacturer=r["manufacturer"])

    def medications(self, q: Optional[str], page: PageRequest) -> Page[MedicationView]:
        where, bindings = medication_pattern(), {}
        if q:
            where += f"\n  FILTER ({fragments.contains('?name', 'q')} || ?code = $exact)"
            bindings.update(q=q.lower(), exact=q)
        return paging.fetch_page(self.session.client, MEDICATION_SELECT, where, bindings, MEDICATION_ORDER, page,
                                 paging.each_row(self._medication))

    def medication(self, medication_id: int) -> Optional[MedicationView]:
        rows = self.session.select(MEDICATION_ONE, {"m": iri("medication", medication_id)})
        return self._medication(rows[0]) if rows else None

    def add_medication(self, values: dict) -> int:
        buf = self.session.write_buffer()
        check_row("Medication", values, insert=True)
        return buf.create("medication", props(MEDICATION, values))

    def update_medication(self, medication_id: int, values: dict) -> None:
        buf = self.session.write_buffer()
        check_row("Medication", values, insert=False)
        replace_all(buf, iri("medication", medication_id), MEDICATION, values)

    def medication_in_use(self, medication_id: int) -> bool:
        return self.session.ask(MEDICATION_IN_USE, {"m": iri("medication", medication_id)})

    def delete_medication(self, medication_id: int) -> None:
        self.session.write_buffer().delete_subject("medication", medication_id)

    # ----- identifiers (ids.py: they look in the write buffer first) -----

    def unique_identifier(self, table: str, system: str, base: str) -> str:
        return ids.unique_identifier(self.session, ids.TABLE_KIND[table], system, base)

    def next_identifier(self, table: str, system: str, prefix: str, width: int) -> str:
        return ids.next_identifier(self.session, ids.TABLE_KIND[table], system, prefix, width)
