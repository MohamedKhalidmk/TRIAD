"""Use cases: the directory of departments, locations, staff and medications (doc/api.md section 3.7).

All staff can read the directory. Only an MOA can create, change and delete rows.
The directory is not about one patient, so these use cases write no audit record.
"""
from __future__ import annotations

import re
from typing import Optional

from domain.access import Actor
from domain.enums import STAFF_ROLES
from domain.errors import Conflict, Invalid, NotFound
from domain.views import DepartmentView, LocationView, MedicationView, StaffView

from application.context import AppContext
from application.guard import require_role

ADDRESS_COLUMNS = {"street": "Street", "city": "City", "region": "Region", "postal_code": "PostalCode",
                   "country": "Country"}
DESIGNATIONS = ("RN", "LPN", "RPN", "NP")
SUBTYPE_FIELDS = {
    "Doctor": {"license_number": "LicenseNumber", "qualification": "Qualification"},
    "Nurse": {"license_number": "LicenseNumber", "designation": "Designation"},
    "MOA": {"certification_number": "CertificationNumber", "desk": "Desk", "phone_extension": "PhoneExtension"},
}


def slug(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-") or "ROW"


def blank(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def required_text(values: dict, key: str, field: str) -> str:
    text = blank(values.get(key))
    if text is None:
        raise Invalid("A value is missing.", {field: "This value is missing."})
    return text


def address_values(address: Optional[dict]) -> dict:
    if not address:
        return {}
    return {column: blank(address.get(key)) for key, column in ADDRESS_COLUMNS.items() if key in address}


def identifier_of(values: dict) -> Optional[tuple[str, str]]:
    ident = values.get("identifier")
    if not ident:
        return None
    system, value = blank(ident.get("system")), blank(ident.get("value"))
    if not system or not value:
        raise Invalid("The identifier is not correct.", {"identifier": "Give a system and a value."})
    return (system, value)


# ----- departments -----

def departments(ctx: AppContext, actor: Actor) -> list[DepartmentView]:
    require_role(actor, "read_directory")
    return ctx.directory.departments()


def load_department(ctx: AppContext, department_id: int) -> DepartmentView:
    found = ctx.directory.department(department_id)
    if found is None:
        raise NotFound(f"Department {department_id} does not exist.")
    return found


def department_values(values: dict, partial: bool) -> dict:
    out = {}
    if not partial or "name" in values:
        out["Name"] = required_text(values, "name", "name")
    for key, column in (("type", "Type"), ("phone_number", "PhoneNumber"), ("email", "Email")):
        if key in values:
            out[column] = blank(values[key])
    out.update(address_values(values.get("address")))
    return out


def create_department(ctx: AppContext, actor: Actor, values: dict) -> DepartmentView:
    require_role(actor, "manage_directory")
    row = department_values(values, partial=False)
    if ctx.directory.department_name_exists(row["Name"]):
        raise Conflict("A department with this name exists already.", {"name": "This name is in use."})
    ident = identifier_of(values)
    with ctx.uow.write():
        if ident is None:
            ident = (ctx.identity.organization, ctx.directory.unique_identifier(
                "Department", ctx.identity.organization, f"{ctx.identity.hospital_code}-{slug(row['Name'])}"))
        row["IdentifierSystem"], row["IdentifierValue"] = ident
        department_id = ctx.directory.add_department(row)
    return load_department(ctx, department_id)


def change_department(ctx: AppContext, actor: Actor, department_id: int, values: dict) -> DepartmentView:
    require_role(actor, "manage_directory")
    load_department(ctx, department_id)
    row = department_values(values, partial=True)
    if "Name" in row and ctx.directory.department_name_exists(row["Name"], except_id=department_id):
        raise Conflict("A department with this name exists already.", {"name": "This name is in use."})
    ident = identifier_of(values)
    if ident:
        row["IdentifierSystem"], row["IdentifierValue"] = ident
    with ctx.uow.write():
        if row:
            ctx.directory.update_department(department_id, row)
    return load_department(ctx, department_id)


def delete_department(ctx: AppContext, actor: Actor, department_id: int) -> None:
    require_role(actor, "manage_directory")
    load_department(ctx, department_id)
    staff, locations = ctx.directory.department_use(department_id)
    if staff:
        raise Conflict("The department has staff. You cannot delete it.", {"staffCount": str(staff)})
    if locations:
        raise Conflict("The department has locations. You cannot delete it.", {"locations": str(locations)})
    with ctx.uow.write():
        ctx.directory.delete_department(department_id)


# ----- locations -----

def locations(ctx: AppContext, actor: Actor, department: Optional[str]) -> list[LocationView]:
    require_role(actor, "read_directory")
    return ctx.directory.locations(blank(department))


def load_location(ctx: AppContext, location_id: int) -> LocationView:
    found = ctx.directory.location(location_id)
    if found is None:
        raise NotFound(f"Location {location_id} does not exist.")
    return found


def location_values(ctx: AppContext, values: dict, partial: bool) -> dict:
    out = {}
    if not partial or "name" in values:
        out["Name"] = required_text(values, "name", "name")
    if "department" in values:
        name = blank(values["department"])
        if name is not None:
            match = next((d.name for d in ctx.directory.departments() if d.name.lower() == name.lower()), None)
            if match is None:
                raise Invalid("The department does not exist.", {"department": f"{name} is not a department."})
            name = match
        out["Type"] = name
    for key, column in (("physical_type", "PhysicalType"), ("phone_number", "PhoneNumber")):
        if key in values:
            out[column] = blank(values[key])
    out.update(address_values(values.get("address")))
    return out


def create_location(ctx: AppContext, actor: Actor, values: dict) -> LocationView:
    require_role(actor, "manage_directory")
    row = location_values(ctx, values, partial=False)
    ident = identifier_of(values)
    with ctx.uow.write():
        if ident is None:
            ident = (ctx.identity.location,
                     ctx.directory.unique_identifier("Location", ctx.identity.location, slug(row["Name"])))
        row["IdentifierSystem"], row["IdentifierValue"] = ident
        location_id = ctx.directory.add_location(row)
    return load_location(ctx, location_id)


def change_location(ctx: AppContext, actor: Actor, location_id: int, values: dict) -> LocationView:
    require_role(actor, "manage_directory")
    load_location(ctx, location_id)
    row = location_values(ctx, values, partial=True)
    ident = identifier_of(values)
    if ident:
        row["IdentifierSystem"], row["IdentifierValue"] = ident
    with ctx.uow.write():
        if row:
            ctx.directory.update_location(location_id, row)
    return load_location(ctx, location_id)


def delete_location(ctx: AppContext, actor: Actor, location_id: int) -> None:
    require_role(actor, "manage_directory")
    location = load_location(ctx, location_id)
    if location.in_use:
        raise Conflict("A visit used the location. You cannot delete it.")
    with ctx.uow.write():
        ctx.directory.delete_location(location_id)


# ----- staff -----

def staff_list(ctx: AppContext, actor: Actor, role: Optional[str], department: Optional[str], q: Optional[str],
               limit: int) -> list[StaffView]:
    require_role(actor, "read_directory")
    if role and role not in STAFF_ROLES:
        raise Invalid("The role is not correct.", {"role": f"Use one of {', '.join(STAFF_ROLES)}."})
    return ctx.directory.staff_list(role or None, blank(department), blank(q), max(1, min(limit, 1000)))


def load_staff(ctx: AppContext, staff_id: int) -> StaffView:
    found = ctx.directory.staff(staff_id)
    if found is None:
        raise NotFound(f"Staff member {staff_id} does not exist.")
    return found


def subtype_values(role: str, values: dict, errors: dict) -> dict:
    allowed = SUBTYPE_FIELDS[role]
    out = {}
    for fields in SUBTYPE_FIELDS.values():
        for key in fields:
            if key in values and key not in allowed and values[key] is not None:
                errors[key] = f"A {role} has no {key.replace('_', ' ')}."
    for key, column in allowed.items():
        if key in values:
            out[column] = blank(values[key])
    if "Designation" in out and out["Designation"] not in DESIGNATIONS:
        errors["designation"] = f"Use one of {', '.join(DESIGNATIONS)}."
    if "Desk" in out and out["Desk"] is None:
        errors["desk"] = "An MOA needs a desk."
    return out


def common_staff_values(values: dict, errors: dict) -> dict:
    out = {}
    for key, column in (("email", "Email"), ("phone_number", "PhoneNumber")):
        if key in values:
            out[column] = blank(values[key])
    if "sex" in values:
        sex = blank(values["sex"])
        if sex is not None and sex not in ("female", "male", "other", "unknown"):
            errors["sex"] = "Use female, male, other or unknown."
        out["Sex"] = sex
    if "active" in values and values["active"] is not None:
        out["Active"] = 1 if values["active"] else 0
    if "languages" in values and values["languages"] is not None:
        out["languages"] = [x for x in dict.fromkeys(blank(v) for v in values["languages"]) if x]
    return out


def create_staff(ctx: AppContext, actor: Actor, values: dict) -> StaffView:
    require_role(actor, "manage_directory")
    errors: dict[str, str] = {}
    name = blank(values.get("name"))
    role = values.get("role")
    if not name:
        errors["name"] = "This value is missing."
    if role not in STAFF_ROLES:
        errors["role"] = f"Use one of {', '.join(STAFF_ROLES)}."
        raise Invalid("The input is not correct.", errors)
    department_id = values.get("department_id")
    department = ctx.directory.department(department_id) if department_id is not None else None
    if department is None:
        errors["departmentId"] = "Select a department."
    row = common_staff_values(values, errors)
    sub = subtype_values(role, values, errors)
    if role == "Nurse" and not sub.get("Designation"):
        sub["Designation"] = "RN"
    if role == "MOA" and not sub.get("Desk"):
        sub["Desk"] = f"{department.name} Desk" if department else "Main Front Desk"
        errors.pop("desk", None)
    if errors:
        raise Invalid("The input is not correct.", errors)
    ident = identifier_of(values)
    with ctx.uow.write():
        if ident is None:
            ident = (ctx.identity.employee,
                     ctx.directory.next_identifier("Staff", ctx.identity.employee, "E", 4))
        row.update({"IdentifierSystem": ident[0], "IdentifierValue": ident[1], "Name": name, "Role": role,
                    "subtype": sub, "department_id": department_id,
                    "role_code": blank(values.get("role_code")) or role.lower(),
                    "specialty": blank(values.get("specialty"))})
        row.setdefault("Active", 1)
        staff_id = ctx.directory.add_staff(row)
    return load_staff(ctx, staff_id)


def change_staff(ctx: AppContext, actor: Actor, staff_id: int, values: dict) -> StaffView:
    require_role(actor, "manage_directory")
    staff = load_staff(ctx, staff_id)
    errors: dict[str, str] = {}
    values = {k: v for k, v in values.items() if k != "sex"}
    row = common_staff_values(values, errors)
    sub = subtype_values(staff.role, values, errors)
    if errors:
        raise Invalid("The input is not correct.", errors)
    if sub:
        row["subtype"] = sub
    with ctx.uow.write():
        if row:
            ctx.directory.update_staff(staff_id, row)
    return load_staff(ctx, staff_id)


def delete_staff(ctx: AppContext, actor: Actor, staff_id: int) -> None:
    require_role(actor, "manage_directory")
    load_staff(ctx, staff_id)
    use = ctx.directory.staff_use(staff_id)
    if use["messages"]:
        raise Conflict("The staff member issued messages. You cannot delete the staff member.")
    if use["departments"]:
        raise Conflict("The staff member works in a department. You cannot delete the staff member.")
    if use["careTeams"]:
        raise Conflict("The staff member is on a care team. You cannot delete the staff member.")
    with ctx.uow.write():
        ctx.directory.delete_staff(staff_id)


# ----- medications -----

def medications(ctx: AppContext, actor: Actor, q: Optional[str], limit: int) -> list[MedicationView]:
    require_role(actor, "read_directory")
    return ctx.directory.medications(blank(q), max(1, min(limit, 1000)))


def load_medication(ctx: AppContext, medication_id: int) -> MedicationView:
    found = ctx.directory.medication(medication_id)
    if found is None:
        raise NotFound(f"Medication {medication_id} does not exist.")
    return found


def medication_values(values: dict, partial: bool) -> dict:
    out = {}
    for key, column, needed in (("code", "Code", True), ("code_system", "CodeSystem", True), ("name", "Name", True),
                                ("form", "Form", False), ("manufacturer", "Manufacturer", False)):
        if needed and (not partial or key in values):
            out[column] = required_text(values, key, {"code_system": "codeSystem"}.get(key, key))
        elif key in values:
            out[column] = blank(values[key])
    return out


def create_medication(ctx: AppContext, actor: Actor, values: dict) -> MedicationView:
    require_role(actor, "manage_directory")
    row = medication_values(values, partial=False)
    with ctx.uow.write():
        medication_id = ctx.directory.add_medication(row)
    return load_medication(ctx, medication_id)


def change_medication(ctx: AppContext, actor: Actor, medication_id: int, values: dict) -> MedicationView:
    require_role(actor, "manage_directory")
    load_medication(ctx, medication_id)
    row = medication_values(values, partial=True)
    with ctx.uow.write():
        if row:
            ctx.directory.update_medication(medication_id, row)
    return load_medication(ctx, medication_id)


def delete_medication(ctx: AppContext, actor: Actor, medication_id: int) -> None:
    require_role(actor, "manage_directory")
    load_medication(ctx, medication_id)
    if ctx.directory.medication_in_use(medication_id):
        raise Conflict("A prescription uses the medication. You cannot delete it.")
    with ctx.uow.write():
        ctx.directory.delete_medication(medication_id)
