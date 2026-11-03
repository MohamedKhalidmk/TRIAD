"""Anti-corruption layer: map FHIR R4 resources to TRIAD domain records.

Two sources go in:
- the Synthea sample (NDJSON). Each encounter has one note (DocumentReference). The note is the
  message, and the clinical resources of the encounter are its assertions.
- the curated TRIAD bundle. A Provenance resource states each claim: its author, its source
  message (Communication) and the claim that it revises (Supersedes).

The mapping keeps the ER a tree. FHIR links that would close a loop (Encounter.serviceProvider,
Location.managingOrganization, Location.partOf, Organization.partOf) are not mapped. The source
files keep them. See doc/fhir_mapping.md.
"""
from __future__ import annotations

import base64
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from domain import records as d
from infrastructure.config import (AUDIT_EVENT_SYSTEM, CHAT_SESSION_SYSTEM, SYNTHEA_SYSTEM, TRIAD_SYSTEM)
from infrastructure.fhir.reader import ResourceIndex, identifier_from_reference, read_bundle, read_ndjson_gz

LOCAL_CODES = "https://triad.example/fhir/CodeSystem/local"
CLINICAL_TYPES = ("Condition", "Procedure", "AllergyIntolerance", "Observation", "ServiceRequest",
                  "DiagnosticReport", "MedicationRequest", "CareTeam")
CATEGORY = {"Condition": "Diagnosis", "Procedure": "Procedure", "AllergyIntolerance": "Allergy",
            "Observation": "Observation", "ServiceRequest": "LabOrder", "DiagnosticReport": "LabReport",
            "MedicationRequest": "Prescription", "CareTeam": "CareTeam"}
VERIFICATION = {"unconfirmed": "Unconfirmed", "provisional": "Provisional", "differential": "Differential",
                "confirmed": "Confirmed", "refuted": "Refuted", "entered-in-error": "EnteredInError"}
MEDIUM_TO_CHANNEL = {"FACE": "InPerson", "PHONE": "Phone", "VIDEOCONF": "Video", "EMAILWRIT": "Email",
                     "FAXWRIT": "Fax", "ELECTRONIC": "Transfer", "ONLINEWRIT": "Chat"}
STAFF_ROLE = {"doctor": "Doctor", "nurse": "Nurse", "moa": "MOA"}


# ----- small helpers -----

def first(items):
    return items[0] if items else None


def coding_of(concept: Optional[dict]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    if not concept:
        return (None, None, None)
    c = first(concept.get("coding") or []) or {}
    return (c.get("code"), c.get("system"), c.get("display") or concept.get("text"))


def text_of(concept: Optional[dict]) -> Optional[str]:
    if not concept:
        return None
    return concept.get("text") or coding_of(concept)[2]


def human_name(names: list) -> str:
    name = next((n for n in names or [] if n.get("use") == "official"), first(names or [])) or {}
    return " ".join((name.get("given") or []) + ([name["family"]] if name.get("family") else []))


def telecom(resource: dict, system: str) -> Optional[str]:
    return next((t.get("value") for t in resource.get("telecom", []) or [] if t.get("system") == system), None)


def address_of(value) -> d.Address:
    a = first(value) if isinstance(value, list) else value
    if not a:
        return d.Address()
    return d.Address(street=" ".join(a.get("line") or []) or None, city=a.get("city"), region=a.get("state"),
                     postal_code=a.get("postalCode"), country=a.get("country"))


def ident_of(resource: dict, source_system: str) -> d.Ident:
    ident = first(resource.get("identifier") or [])
    if ident and ident.get("system") and ident.get("value"):
        return (ident["system"], ident["value"])
    return (source_system, f"{resource['resourceType']}/{resource['id']}")


def entry_ident(resource: dict, source_system: str) -> d.Ident:
    return (source_system, f"{resource['resourceType']}/{resource['id']}")


def instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def number(value) -> str:
    return f"{value:g}" if isinstance(value, float) else str(value)


class FhirOnboardingSource:
    """Implements the OnboardingSource port for the Synthea NDJSON and the curated bundle."""

    def __init__(self, synthea_path: Path, scenarios_path: Path, demo_activity_path: Path, profile: dict):
        self.synthea_path = synthea_path
        self.scenarios_path = scenarios_path
        self.demo_activity_path = demo_activity_path
        self.profile = profile

    def load_batch(self) -> d.OnboardBatch:
        curated = ResourceIndex(read_bundle(self.scenarios_path), TRIAD_SYSTEM)
        synthea = ResourceIndex(list(read_ndjson_gz(self.synthea_path)), SYNTHEA_SYSTEM)
        activity = json.loads(Path(self.demo_activity_path).read_text(encoding="utf-8"))
        return _Mapper(self.profile, curated, synthea, activity).run()


class _Mapper:
    def __init__(self, profile: dict, curated: ResourceIndex, synthea: ResourceIndex, activity: dict):
        self.p = profile
        self.cur = curated
        self.syn = synthea
        self.activity = activity
        self.b = d.OnboardBatch()
        self.stats: dict = {"mappedByType": Counter(), "notMappedByType": Counter()}
        sid = profile["identifierSystems"]
        self.org_system, self.loc_system = sid["organization"], sid["location"]
        self.dept_ident: dict[str, d.Ident] = {}
        self.dept_name: dict[str, str] = {}
        self.default_location: dict[str, d.Ident] = {}
        self.loc_by_id: dict[str, d.Ident] = {}
        self.staff_by_id: dict[tuple[str, str], d.Ident] = {}
        self.patient_by_id: dict[tuple[str, str], d.PatientKey] = {}
        self.visit_by_id: dict[str, d.Ident] = {}           # encounter logical id -> visit ident
        self.visits_of_patient: dict[d.PatientKey, list[d.Visit]] = defaultdict(list)
        self.encounter_class: dict[str, str] = {}
        self.medications: dict[d.MedicationKey, d.Medication] = {}
        self.messages: dict[d.Ident, d.Message] = {}
        self.seq: Counter = Counter()
        self.note_by_encounter: dict[str, d.Ident] = {}
        self.no_encounter_message: dict[d.PatientKey, d.Ident] = {}

    # ----- run -----

    def run(self) -> d.OnboardBatch:
        self.departments()
        self.locations()
        self.patients()
        self.visits()
        self.staff()
        self.medication_resources()
        self.curated_messages()
        self.synthea_notes()
        self.curated_claims()
        self.synthea_claims()
        self.demo_activity()
        self.finish()
        return self.b

    # ----- directory -----

    def department_for(self, encounter: dict) -> str:
        rule = self.p["classToDepartment"].get(encounter["class"]["code"], "FAMMED")
        if isinstance(rule, str):
            return rule
        name = ""
        ref = self.syn.resolve(encounter.get("serviceProvider"), "Organization")
        if ref and ref[1]:
            org = self.syn.get("Organization", ref[1])
            name = (org or {}).get("name", "")
        for needle, dept in rule.get("providerNameContains", {}).items():
            if needle in name.upper():
                return dept
        return rule["default"]

    def departments(self) -> None:
        hospital = self.p["hospital"]["code"]
        for dept in self.p["departments"]:
            self.dept_ident[dept["code"]] = (self.org_system, f"{hospital}-{dept['code']}")
            self.dept_name[dept["code"]] = dept["name"]
        for org in self.cur.of_type("Organization"):
            type_code = coding_of(first(org.get("type") or []))[0]
            if type_code != "dept":
                self.stats["notMappedByType"]["Organization"] += 1
                continue
            self.b.departments.append(d.Department(
                ident=ident_of(org, TRIAD_SYSTEM), name=org["name"],
                type=text_of(first(org.get("type") or [])), phone=telecom(org, "phone"),
                email=telecom(org, "email"), address=address_of(org.get("address"))))
            self.stats["mappedByType"]["Organization"] += 1
        self.stats["notMappedByType"]["Organization"] += sum(1 for _ in self.syn.of_type("Organization"))

    def locations(self) -> None:
        dept_of_loc = {loc["code"]: loc["department"] for loc in self.p["locations"]}
        for loc in self.cur.of_type("Location"):
            ident = ident_of(loc, TRIAD_SYSTEM)
            self.loc_by_id[loc["id"]] = ident
            self.b.locations.append(d.Location(
                ident=ident, name=loc["name"], type=self.dept_name.get(dept_of_loc.get(ident[1], "")),
                physical_type=text_of(loc.get("physicalType")), phone=telecom(loc, "phone"),
                address=address_of(loc.get("address"))))
            self.stats["mappedByType"]["Location"] += 1
        for dept in self.p["departments"]:
            self.default_location[dept["code"]] = (self.loc_system, dept["defaultLocation"])
        self.stats["notMappedByType"]["Location"] += sum(1 for _ in self.syn.of_type("Location"))

    # ----- patients and visits -----

    def patients(self) -> None:
        for index, system in ((self.cur, TRIAD_SYSTEM), (self.syn, SYNTHEA_SYSTEM)):
            for pat in index.of_type("Patient"):
                idents = []
                for i in pat.get("identifier", []) or []:
                    pair = (i.get("system"), i.get("value"))
                    if pair[0] and pair[1] and pair not in idents:
                        idents.append(pair)
                record = d.Patient(name=human_name(pat.get("name")), birth_date=pat["birthDate"],
                                   sex=pat.get("gender", "unknown"), phone=telecom(pat, "phone"),
                                   address=address_of(pat.get("address")), identifiers=idents)
                self.patient_by_id[(system, pat["id"])] = record.key
                self.b.patients.append(record)
                self.stats["mappedByType"]["Patient"] += 1

    def patient_ref(self, index: ResourceIndex, ref: Optional[dict]) -> d.PatientKey:
        resolved = index.resolve(ref, "Patient")
        if resolved and (index.system, resolved[1]) in self.patient_by_id:
            return self.patient_by_id[(index.system, resolved[1])]
        for system in (TRIAD_SYSTEM, SYNTHEA_SYSTEM):  # a curated resource can point to a Synthea patient
            if resolved and (system, resolved[1]) in self.patient_by_id:
                return self.patient_by_id[(system, resolved[1])]
        raise ValueError(f"Unknown patient reference: {ref}")

    def visits(self) -> None:
        for index, system in ((self.cur, TRIAD_SYSTEM), (self.syn, SYNTHEA_SYSTEM)):
            for enc in index.of_type("Encounter"):
                period = enc.get("period") or {}
                visit = d.Visit(
                    ident=ident_of(enc, system), patient=self.patient_ref(index, enc.get("subject")),
                    visit_class=enc["class"]["code"], start=period["start"], end=period.get("end"),
                    type=text_of(first(enc.get("type") or [])),
                    reason=text_of(first(enc.get("reasonCode") or [])))
                if system == TRIAD_SYSTEM:
                    for item in enc.get("location", []) or []:
                        ref = index.resolve(item.get("location"), "Location")
                        lp = item.get("period") or period
                        visit.locations.append(d.VisitLocation(self.loc_by_id[ref[1]], lp.get("start", visit.start),
                                                               lp.get("end")))
                else:
                    dept = self.department_for(enc)
                    visit.locations.append(d.VisitLocation(self.default_location[dept], visit.start, visit.end))
                self.visit_by_id[enc["id"]] = visit.ident
                self.encounter_class[enc["id"]] = visit.visit_class
                self.visits_of_patient[visit.patient].append(visit)
                self.b.visits.append(visit)
                self.stats["mappedByType"]["Encounter"] += 1

    def visit_for_time(self, patient: d.PatientKey, when: str) -> d.Ident:
        """The visit that contains `when`; else the latest visit before it; else the first visit."""
        t = instant(when)
        visits = sorted(self.visits_of_patient[patient], key=lambda v: instant(v.start))
        inside = [v for v in visits if instant(v.start) <= t <= instant(v.end or v.start)]
        if inside:
            self.stats["allergyVisitInside"] = self.stats.get("allergyVisitInside", 0) + 1
            return inside[-1].ident
        before = [v for v in visits if instant(v.start) <= t]
        self.stats["allergyVisitNearest"] = self.stats.get("allergyVisitNearest", 0) + 1
        return (before[-1] if before else visits[0]).ident

    # ----- staff -----

    def staff(self) -> None:
        sid = self.p["identifierSystems"]
        roles_of: dict[str, list[dict]] = defaultdict(list)
        for role in self.cur.of_type("PractitionerRole"):
            ref = self.cur.resolve(role.get("practitioner"), "Practitioner")
            roles_of[ref[1]].append(role)
        for prac in self.cur.of_type("Practitioner"):
            roles = roles_of[prac["id"]]
            code = coding_of(first(roles[0].get("code") or []))[0]
            role_name = STAFF_ROLE[code]
            ids = {i["system"]: i["value"] for i in prac.get("identifier", [])}
            qual = first(prac.get("qualification") or []) or {}
            qual_ids = {i["system"]: i["value"] for i in qual.get("identifier", [])}
            staff = d.Staff(
                ident=ident_of(prac, TRIAD_SYSTEM), name=human_name(prac.get("name")), role=role_name,
                sex=prac.get("gender"), email=telecom(prac, "email"), phone=telecom(prac, "phone"),
                active=prac.get("active", True),
                languages=[coding_of(c)[0] for c in prac.get("communication", []) or []])
            for role in roles:
                org = self.cur.resolve(role.get("organization"), "Organization")
                org_res = self.cur.get("Organization", org[1])
                staff.works_in.append(d.WorksIn(
                    department=ident_of(org_res, TRIAD_SYSTEM), role_code=coding_of(first(role.get("code")))[0],
                    specialty=text_of(first(role.get("specialty") or [])),
                    start_date=(role.get("period") or {}).get("start")))
            if role_name == "Doctor":
                staff.license_number = ids.get(sid["doctorLicence"])
                staff.qualification = text_of(qual.get("code"))
            elif role_name == "Nurse":
                staff.license_number = ids.get(sid["nurseLicence"])
                staff.designation = text_of(qual.get("code"))
            else:
                staff.certification_number = qual_ids.get(sid["moaCertificate"])
                staff.desk = text_of({"text": (first(roles[0].get("location") or []) or {}).get("display")})
                staff.phone_extension = telecom(roles[0], "phone")
            self.staff_by_id[(TRIAD_SYSTEM, prac["id"])] = staff.ident
            self.b.staff.append(staff)
            self.stats["mappedByType"]["Practitioner"] += 1
            self.stats["mappedByType"]["PractitionerRole"] += len(roles)

        # Synthea doctors work in the department where they saw the most visits.
        visits_per_dept: dict[str, Counter] = defaultdict(Counter)
        for enc in self.syn.of_type("Encounter"):
            for part in enc.get("participant", []) or []:
                npi = identifier_from_reference(part.get("individual"))
                if npi:
                    visits_per_dept[npi[1]][self.department_for(enc)] += 1
        order = [dept["code"] for dept in self.p["departments"]]
        syn_roles: dict[str, dict] = {}
        for role in self.syn.of_type("PractitionerRole"):
            npi = identifier_from_reference(role.get("practitioner"))
            if npi:
                syn_roles[npi[1]] = role
        for prac in self.syn.of_type("Practitioner"):
            ident = ident_of(prac, SYNTHEA_SYSTEM)
            counts = visits_per_dept.get(ident[1], Counter())
            dept = min(counts, key=lambda c: (-counts[c], order.index(c))) if counts else "FAMMED"
            role = syn_roles.get(ident[1], {})
            code, _, display = coding_of(first(role.get("code") or []))
            staff = d.Staff(ident=ident, name=human_name(prac.get("name")), role="Doctor",
                            sex=prac.get("gender"), email=telecom(prac, "email"), phone=telecom(prac, "phone"),
                            active=prac.get("active", True), qualification=display,
                            works_in=[d.WorksIn(self.dept_ident[dept], code or "doctor",
                                                text_of(first(role.get("specialty") or [])))])
            self.staff_by_id[(SYNTHEA_SYSTEM, prac["id"])] = ident
            self.b.staff.append(staff)
            self.stats["mappedByType"]["Practitioner"] += 1
            self.stats["mappedByType"]["PractitionerRole"] += 1 if role else 0

    def staff_ident(self, index: ResourceIndex, ref: Optional[dict]) -> Optional[d.Ident]:
        resolved = index.resolve(ref, "Practitioner")
        if resolved and resolved[1]:
            return self.staff_by_id.get((index.system, resolved[1]))
        return None

    # ----- medications -----

    def medication_resources(self) -> None:
        for index in (self.cur, self.syn):
            for med in index.of_type("Medication"):
                self.add_medication(med.get("code"), text_of(med.get("form")))
                self.stats["mappedByType"]["Medication"] += 1

    def add_medication(self, concept: Optional[dict], form: Optional[str] = None) -> d.MedicationKey:
        code, system, display = coding_of(concept)
        key = (code, system)
        if key not in self.medications:
            self.medications[key] = d.Medication(code=code, code_system=system, name=display or code, form=form)
        return key

    # ----- messages -----

    def add_message(self, message: d.Message) -> d.Ident:
        self.messages[message.ident] = message
        return message.ident

    def curated_messages(self) -> None:
        origin_url = self.p["extensions"]["origin"]
        for comm in self.cur.of_type("Communication"):
            origin = next((e["valueCode"] for e in comm.get("extension", []) if e["url"] == origin_url), "Staff")
            medium = coding_of(first(comm.get("medium") or []))[0]
            self.add_message(d.Message(
                ident=ident_of(comm, TRIAD_SYSTEM), staff=self.staff_ident(self.cur, comm.get("sender")),
                channel=MEDIUM_TO_CHANNEL.get(medium, "Transfer"), origin=origin, sent_at=comm["sent"],
                text=first(comm.get("payload") or [{}]).get("contentString", "")))
            self.stats["mappedByType"]["Communication"] += 1

    def synthea_notes(self) -> None:
        for doc in self.syn.of_type("DocumentReference"):
            enc = self.syn.resolve(first((doc.get("context") or {}).get("encounter") or []), "Encounter")
            data = first(doc.get("content") or [{}])["attachment"].get("data", "")
            text = base64.b64decode(data).decode("utf-8") if data else ""
            ident = self.add_message(d.Message(
                ident=ident_of(doc, SYNTHEA_SYSTEM), staff=self.staff_ident(self.syn, first(doc.get("author") or [])),
                channel="Video" if self.encounter_class.get(enc[1]) == "VR" else "InPerson",
                origin="Staff", sent_at=doc["date"], text=text.strip()))
            self.note_by_encounter[enc[1]] = ident
            self.stats["mappedByType"]["DocumentReference"] += 1

    def records_message(self, patient: d.PatientKey, patient_id: str) -> d.Ident:
        """One message per patient for Synthea entries with no encounter (built from the Synthea Provenance)."""
        if patient in self.no_encounter_message:
            return self.no_encounter_message[patient]
        prov = next((p for p in self.syn.of_type("Provenance")
                     if any(t.get("reference", "").endswith(patient_id) for t in p.get("target", []))), None)
        author = next((a for a in (prov or {}).get("agent", [])
                       if coding_of(a.get("type"))[0] == "author"), None)
        ident = self.add_message(d.Message(
            ident=(SYNTHEA_SYSTEM, f"Provenance/{prov['id']}"),
            staff=self.staff_ident(self.syn, (author or {}).get("who")), channel="Transfer", origin="Staff",
            sent_at=prov["recorded"], text="Records without an encounter (from the Synthea record of this patient)."))
        self.no_encounter_message[patient] = ident
        self.stats["mappedByType"]["Provenance"] += 1
        return ident

    # ----- clinical entries and assertions -----

    def build_entry(self, res: dict, system: str, visit: d.Ident, index: ResourceIndex,
                    ident: Optional[d.Ident] = None) -> d.ClinicalEntry:
        rtype = res["resourceType"]
        category = CATEGORY[rtype]
        medication = None
        if rtype == "MedicationRequest":
            concept = res.get("medicationCodeableConcept")
            if not concept:
                ref = index.resolve(res.get("medicationReference"), "Medication")
                concept = (index.get("Medication", ref[1]) or {}).get("code")
            medication = self.add_medication(concept)
            code, code_system, display = coding_of(concept)
        elif rtype == "CareTeam":
            code, code_system, display = "care-team", LOCAL_CODES, res.get("name") or "Care team"
        else:
            code, code_system, display = coding_of(res.get("code"))
        recorded = {
            "Condition": res.get("recordedDate") or res.get("onsetDateTime"),
            "Procedure": (res.get("performedPeriod") or {}).get("start") or res.get("performedDateTime"),
            "AllergyIntolerance": res.get("recordedDate"),
            "Observation": res.get("effectiveDateTime") or res.get("issued"),
            "ServiceRequest": res.get("authoredOn"),
            "DiagnosticReport": res.get("issued") or res.get("effectiveDateTime"),
            "MedicationRequest": res.get("authoredOn"),
            "CareTeam": (res.get("period") or {}).get("start"),
        }[rtype]
        entry = d.ClinicalEntry(ident=ident or entry_ident(res, system), visit=visit, category=category,
                                code=code, code_system=code_system, display=display or code,
                                recorded_at=recorded, text=text_of(res.get("code")), medication=medication)
        entry.details = self.details(res, entry)
        if rtype == "CareTeam":
            for part in res.get("participant", []) or []:
                member = part.get("member") or {}
                ref_text = member.get("reference", "")
                if member.get("type") == "Practitioner" or ref_text.startswith("Practitioner"):
                    pair = identifier_from_reference(member)
                    if pair and pair[0] and pair[1]:
                        entry.members.append(d.CareTeamMember(pair, text_of(first(part.get("role") or []))))
        return entry

    def details(self, res: dict, entry: d.ClinicalEntry) -> dict:
        rtype = res["resourceType"]
        if rtype == "Condition":
            return {"OnsetDate": res.get("onsetDateTime"), "AbatementDate": res.get("abatementDateTime"),
                    "ClinicalStatus": coding_of(res.get("clinicalStatus"))[0] or "unknown",
                    "Severity": text_of(res.get("severity"))}
        if rtype == "Procedure":
            return {"PerformedDate": entry.recorded_at, "Outcome": text_of(res.get("outcome"))}
        if rtype == "AllergyIntolerance":
            return {"Substance": entry.display, "Type": res.get("type"),
                    "AllergyCategory": first(res.get("category") or []),
                    "Criticality": res.get("criticality"),
                    "ClinicalStatus": coding_of(res.get("clinicalStatus"))[0]}
        if rtype == "Observation":
            return dict(zip(("Value", "Unit"), self.observation_value(res)))
        if rtype == "ServiceRequest":
            return {"TestName": entry.display, "Priority": res.get("priority", "routine"),
                    "Specimen": (first(res.get("specimen") or []) or {}).get("display")}
        if rtype == "DiagnosticReport":
            return {"IssuedDate": res.get("issued") or entry.recorded_at, "Conclusion": res.get("conclusion")}
        if rtype == "MedicationRequest":
            dosage = first(res.get("dosageInstruction") or []) or {}
            dose = (first(dosage.get("doseAndRate") or []) or {}).get("doseQuantity") or {}
            dose_text = " ".join(x for x in (number(dose["value"]) if "value" in dose else None,
                                             dose.get("unit")) if x) or dosage.get("text")
            rep = (dosage.get("timing") or {}).get("repeat") or {}
            freq = (f"{number(rep['frequency'])} per {number(rep.get('period', 1))} {rep.get('periodUnit', '')}".strip()
                    if "frequency" in rep else None)
            return {"Dosage": dose_text, "Frequency": freq, "Status": res.get("status", "unknown")}
        if rtype == "CareTeam":
            return {"Name": res.get("name"), "Status": res.get("status", "active")}
        return {}

    @staticmethod
    def observation_value(res: dict) -> tuple[str, Optional[str]]:
        def one(item: dict) -> tuple[str, Optional[str]]:
            if "valueQuantity" in item:
                q = item["valueQuantity"]
                return number(q.get("value")), q.get("unit") or q.get("code")
            if "valueCodeableConcept" in item:
                return text_of(item["valueCodeableConcept"]) or "", None
            for key in ("valueString", "valueBoolean", "valueInteger", "valueDateTime"):
                if key in item:
                    return str(item[key]), None
            return "", None
        if res.get("component"):
            parts = []
            for comp in res["component"]:
                value, unit = one(comp)
                parts.append(f"{text_of(comp.get('code'))}: {value}{' ' + unit if unit else ''}")
            return "; ".join(parts), None
        return one(res)

    @staticmethod
    def verification(res: dict) -> str:
        rtype = res["resourceType"]
        if rtype in ("Condition", "AllergyIntolerance"):
            return VERIFICATION.get(coding_of(res.get("verificationStatus"))[0], "Unconfirmed")
        status = res.get("status")
        if status == "entered-in-error":
            return "EnteredInError"
        if rtype in ("Observation", "DiagnosticReport"):
            if status in ("final", "amended", "corrected", "appended"):
                return "Confirmed"
            return "Provisional" if status in ("preliminary", "registered", "partial") else "Unconfirmed"
        return "Confirmed"

    @staticmethod
    def intent(rtype: str) -> str:
        return "Report" if rtype in ("Observation", "DiagnosticReport", "CareTeam") else "Decision"

    @staticmethod
    def statement(res: dict, entry: d.ClinicalEntry) -> str:
        note = first(res.get("note") or [])
        if note and note.get("text"):
            return note["text"]
        if entry.category == "Observation":
            unit = entry.details.get("Unit")
            return f"{entry.display}: {entry.details['Value']}{' ' + unit if unit else ''}"
        if entry.category == "Prescription" and entry.details.get("Dosage"):
            return f"{entry.display} ({entry.details['Dosage']})"
        return entry.display

    def next_seq(self, message: d.Ident) -> int:
        self.seq[message] += 1
        return self.seq[message]

    def curated_claims(self) -> None:
        """Curated data: each Provenance is one assertion. Versions of a resource are claims about one entry."""
        intent_url = self.p["extensions"]["intent"]
        provenances = list(self.cur.of_type("Provenance"))
        key_of_target: dict[tuple, str] = {}
        claims_of: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for prov in provenances:
            target = self.cur.resolve(first(prov["target"]))
            key_of_target[target] = f"Provenance/{prov['id']}"
            key_of_target.setdefault((target[0], target[1], None), f"Provenance/{prov['id']}")
            claims_of[(target[0], target[1])].append(prov)
        done = set()
        for res in self.cur.order:
            rtype, rid = res["resourceType"], res["id"]
            if rtype not in CLINICAL_TYPES or (rtype, rid) in done:
                continue
            done.add((rtype, rid))
            versions = self.cur.versions[(rtype, rid)]
            first_version, latest = versions[0], versions[-1]
            enc_ref = first_version.get("encounter")
            visit = self.visit_by_id[self.cur.resolve(enc_ref, "Encounter")[1]]
            entry = self.build_entry(latest, TRIAD_SYSTEM, visit, self.cur)
            self.b.entries.append(entry)
            self.stats["mappedByType"][rtype] += len(versions)
            for prov in claims_of[(rtype, rid)]:
                target = self.cur.resolve(first(prov["target"]))
                version = self.cur.get(rtype, rid, target[2]) or latest
                source = next(e for e in prov["entity"] if e["role"] == "source")
                message = ident_of(self.cur.get("Communication", self.cur.resolve(source["what"])[1]), TRIAD_SYSTEM)
                revision = next((e for e in prov["entity"] if e["role"] == "revision"), None)
                supersedes = key_of_target.get(self.cur.resolve(revision["what"])) if revision else None
                agent_is_device = any("Device" in ((a.get("who") or {}).get("reference") or "") for a in prov["agent"])
                self.b.assertions.append(d.Assertion(
                    key=f"Provenance/{prov['id']}", message=message, seq=self.next_seq(message),
                    entry=entry.ident, asserted_at=prov["recorded"],
                    intent=next((e["valueCode"] for e in prov.get("extension", []) if e["url"] == intent_url), "Report"),
                    source="Agent" if agent_is_device else "Human", verification=self.verification(version),
                    statement=self.statement(version, entry), supersedes=supersedes))
                self.stats["mappedByType"]["Provenance"] += 1

    def synthea_claims(self) -> None:
        """Synthea data: the note of the encounter is the message; each clinical resource is one assertion."""
        for res in self.syn.order:
            rtype = res["resourceType"]
            if rtype not in CLINICAL_TYPES:
                if rtype not in ("Patient", "Encounter", "Practitioner", "PractitionerRole", "Organization",
                                 "Location", "Medication", "DocumentReference", "Provenance"):
                    self.stats["notMappedByType"][rtype] += 1
                continue
            if rtype == "DiagnosticReport" and coding_of(first(res.get("category") or []))[0] != "LAB":
                self.stats["notMappedByType"]["DiagnosticReport (not LAB)"] += 1
                continue
            patient = self.patient_ref(self.syn, res.get("subject") or res.get("patient"))
            enc = self.syn.resolve(res.get("encounter"), "Encounter")
            if enc:
                visit = self.visit_by_id[enc[1]]
                message = self.note_by_encounter[enc[1]]
            else:
                visit = self.visit_for_time(patient, res.get("recordedDate"))
                patient_id = self.syn.resolve(res.get("patient") or res.get("subject"), "Patient")[1]
                message = self.records_message(patient, patient_id)
            entry = self.build_entry(res, SYNTHEA_SYSTEM, visit, self.syn)
            self.b.entries.append(entry)
            self.b.assertions.append(d.Assertion(
                key=f"{rtype}/{res['id']}", message=message, seq=self.next_seq(message), entry=entry.ident,
                asserted_at=entry.recorded_at, intent=self.intent(rtype), source="Human",
                verification=self.verification(res), statement=self.statement(res, entry)))
            self.stats["mappedByType"][rtype] += 1

    # ----- demo activity (chat and audit logs) -----

    def demo_activity(self) -> None:
        for s in self.activity.get("chatSessions", []):
            session = d.ChatSession(
                ident=(CHAT_SESSION_SYSTEM, s["identifier"]), user_role=s["user"]["role"],
                user=(s["user"]["identifier"]["system"], s["user"]["identifier"]["value"]),
                subject=(s["subject"]["name"], s["subject"]["birthDate"]), started_at=s["startedAt"],
                mode=s["mode"], model=s.get("model"))
            for t in s["turns"]:
                session.turns.append(d.ChatTurn(
                    seq=t["seq"], client_turn_id=t["clientTurnId"], speaker=t["speaker"], text=t["text"],
                    created_at=t["createdAt"],
                    citations=[(c["provenance"], c["rank"]) for c in t.get("citations", [])]))
            self.b.chat_sessions.append(session)
        for a in self.activity.get("auditEvents", []):
            turn = None
            if a.get("chatTurn"):
                session_id, seq = a["chatTurn"].split("#")
                turn = ((CHAT_SESSION_SYSTEM, session_id), int(seq))
            self.b.audit_events.append(d.AuditEvent(
                ident=(AUDIT_EVENT_SYSTEM, a["identifier"]), at=a["at"], action=a["action"],
                outcome=a["outcome"], actor_role=a["actor"]["role"],
                actor=(a["actor"]["identifier"]["system"], a["actor"]["identifier"]["value"]),
                subject=(a["subject"]["name"], a["subject"]["birthDate"]), path=a["path"], chat_turn=turn))

    # ----- finish -----

    def finish(self) -> None:
        used = {a.message for a in self.b.assertions}
        self.b.messages = [m for m in self.messages.values() if m.ident in used]
        self.stats["messagesWithoutFacts"] = len(self.messages) - len(self.b.messages)
        self.b.medications = list(self.medications.values())
        self.stats["mappedByType"] = dict(sorted(self.stats["mappedByType"].items()))
        self.stats["notMappedByType"] = dict(sorted(self.stats["notMappedByType"].items()))
        self.b.stats = self.stats
