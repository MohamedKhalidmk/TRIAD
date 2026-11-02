#!/usr/bin/env python3
"""Build the TRIAD scenario data from the hospital profile.

Inputs:
  src/backend/data/raw/hospital_profile.json
  src/backend/data/preprocessed/synthea_r4.ndjson.gz

Outputs:
  src/backend/data/raw/triad_scenarios.fhir.json   (a FHIR R4 collection Bundle)
  src/backend/data/raw/demo_activity.json          (chat and audit rows for the demo)

The script uses a fixed seed. It writes the same output on each run.
It also checks that the pinned Patient B still meets the selection criteria.

Use only the Python standard library. Python 3.9 or later.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "src" / "backend" / "data" / "raw"
SYNTHEA = REPO_ROOT / "src" / "backend" / "data" / "preprocessed" / "synthea_r4.ndjson.gz"

SNOMED = "http://snomed.info/sct"
LOINC = "http://loinc.org"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
UCUM = "http://unitsofmeasure.org"
LOCAL = "https://triad.example/fhir/CodeSystem/local"
ROLE_CS = "http://terminology.hl7.org/CodeSystem/practitioner-role"
ORG_TYPE_CS = "http://terminology.hl7.org/CodeSystem/organization-type"
LOC_TYPE_CS = "http://terminology.hl7.org/CodeSystem/location-physical-type"
ACT_CODE = "http://terminology.hl7.org/CodeSystem/v3-ActCode"
PART_MODE = "http://terminology.hl7.org/CodeSystem/v3-ParticipationMode"
LANG = "urn:ietf:bcp:47"

FIRST_NAMES = [
    "Aisha", "Ben", "Carmen", "Daniel", "Eva", "Farid", "Grace", "Hugo", "Ines", "Jamal",
    "Kira", "Liam", "Maya", "Nikhil", "Olivia", "Pablo", "Quinn", "Rosa", "Samir", "Tara",
    "Umar", "Vera", "Wei", "Ximena", "Yusuf", "Zoe", "Anika", "Bruno", "Chloe", "Dmitri",
    "Elif", "Felix", "Hana", "Ivan", "Lena", "Mateo", "Noor", "Oscar", "Sana", "Theo",
]
LAST_NAMES = [
    "Abbott", "Bauer", "Castillo", "Dubois", "Ellis", "Fischer", "Garcia", "Haddad", "Ivanova", "Jensen",
    "Kowalski", "Lindqvist", "Moreau", "Novak", "Ortega", "Petrov", "Quaid", "Rossi", "Sato", "Tanaka",
    "Usman", "Varga", "Wagner", "Xu", "Yilmaz", "Zhang", "Adeyemi", "Bianchi", "Chen", "Dlamini",
]
EXTRA_LANGUAGES = ["fr", "es", "zh", "pa", "tl", "ar", "vi", "hi", "ko", "pt"]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def coding(system: str, code: str, display: str | None = None) -> dict:
    out = {"system": system, "code": code}
    if display:
        out["display"] = display
    return out


def concept(system: str, code: str, display: str) -> dict:
    return {"coding": [coding(system, code, display)], "text": display}


def ref(rtype: str, rid: str, display: str | None = None) -> dict:
    out = {"reference": f"{rtype}/{rid}"}
    if display:
        out["display"] = display
    return out


class Builder:
    def __init__(self, profile: dict):
        self.p = profile
        self.rng = random.Random(profile["seed"])
        self.sid = profile["identifierSystems"]
        self.ext = profile["extensions"]
        self.base = profile["baseUrl"]
        self.entries: list[dict] = []
        self.staff: list[dict] = []  # summary rows for the demo users and checks
        self.employee_seq = 1000

    # ----- helpers -----
    def add(self, resource: dict) -> dict:
        self.entries.append({
            "fullUrl": f"{self.base}/{resource['resourceType']}/{resource['id']}",
            "resource": resource,
        })
        return resource

    def next_employee(self) -> str:
        self.employee_seq += 1
        return f"E{self.employee_seq}"

    def dept_name(self, code: str) -> str:
        return next(d["name"] for d in self.p["departments"] if d["code"] == code)

    def loc_name(self, code: str) -> str:
        return next(loc["name"] for loc in self.p["locations"] if loc["code"] == code)

    # ----- organizations and locations -----
    def organizations(self) -> None:
        h = self.p["hospital"]
        self.add({
            "resourceType": "Organization", "id": "org-triad-gh",
            "identifier": [{"system": self.sid["organization"], "value": h["code"]}],
            "active": True,
            "type": [concept(ORG_TYPE_CS, "prov", "Healthcare Provider")],
            "name": h["name"],
            "telecom": [{"system": "phone", "value": h["phone"]}, {"system": "email", "value": h["email"]}],
            "address": [h["address"]],
        })
        for d in self.p["departments"]:
            self.add({
                "resourceType": "Organization", "id": f"org-{d['code'].lower()}",
                "identifier": [{"system": self.sid["organization"], "value": f"{h['code']}-{d['code']}"}],
                "active": True,
                "type": [concept(ORG_TYPE_CS, "dept", "Hospital Department")],
                "name": d["name"],
                "telecom": [{"system": "phone", "value": d["phone"]}],
                "address": [h["address"]],
                "partOf": ref("Organization", "org-triad-gh", h["name"]),
            })

    def locations(self) -> None:
        names = {
            "wi": "Wing", "wa": "Ward", "ro": "Room", "bd": "Bed",
            "area": "Area", "ho": "House", "vi": "Virtual",
        }
        for loc in self.p["locations"]:
            res = {
                "resourceType": "Location", "id": f"loc-{loc['code'].lower()}",
                "identifier": [{"system": self.sid["location"], "value": loc["code"]}],
                "status": "active",
                "name": loc["name"],
                "physicalType": concept(LOC_TYPE_CS, loc["physicalType"], names[loc["physicalType"]]),
                "managingOrganization": ref("Organization", f"org-{loc['department'].lower()}"),
            }
            if loc.get("partOf"):
                res["partOf"] = ref("Location", f"loc-{loc['partOf'].lower()}", self.loc_name(loc["partOf"]))
            if loc["physicalType"] not in ("ho", "vi"):
                res["address"] = self.p["hospital"]["address"]
            self.add(res)

    # ----- staff -----
    def practitioner(self, person: dict) -> None:
        role = person["role"]
        emp = self.next_employee()
        pid = f"prac-{emp.lower()}"
        given, family = person["given"], person["family"]
        email = f"{given.lower()}.{family.lower()}@triad-general.example"
        phone = f"+1-508-555-{2000 + self.employee_seq - 1000:04d}"
        identifiers = [{"system": self.sid["employee"], "value": emp}]
        qualification = []
        if role == "Doctor":
            lic = f"MD-{self.rng.randint(10000, 99999)}"
            identifiers.append({"system": self.sid["doctorLicence"], "value": lic})
            qualification.append({
                "identifier": [{"system": self.sid["doctorLicence"], "value": lic}],
                "code": {"text": "MD"},
            })
        elif role == "Nurse":
            lic = f"RN-{self.rng.randint(10000, 99999)}"
            identifiers.append({"system": self.sid["nurseLicence"], "value": lic})
            qualification.append({
                "identifier": [{"system": self.sid["nurseLicence"], "value": lic}],
                "code": {"text": person["designation"]},
            })
        elif role == "MOA" and person.get("certified", True):
            cert = f"MOA-{self.rng.randint(1000, 9999)}"
            qualification.append({
                "identifier": [{"system": self.sid["moaCertificate"], "value": cert}],
                "code": {"text": "Medical office assistant certificate"},
            })
        prac = {
            "resourceType": "Practitioner", "id": pid,
            "identifier": identifiers,
            "active": True,
            "name": [{"use": "official", "family": family, "given": [given],
                      **({"prefix": ["Dr."]} if role == "Doctor" else {})}],
            "telecom": [{"system": "email", "value": email, "use": "work"},
                        {"system": "phone", "value": phone, "use": "work"}],
            "gender": person["gender"],
            "communication": [concept(LANG, lang, lang) for lang in person["languages"]],
        }
        if qualification:
            prac["qualification"] = qualification
        self.add(prac)

        dept = person["department"]
        if role == "Doctor":
            code = concept(ROLE_CS, "doctor", "Doctor")
        elif role == "Nurse":
            code = concept(ROLE_CS, "nurse", "Nurse")
        else:
            code = concept(self.ext["staffRole"], "moa", "Medical office assistant")
        start = f"{self.rng.randint(2008, 2024)}-{self.rng.randint(1, 12):02d}-{self.rng.randint(1, 28):02d}"
        prole = {
            "resourceType": "PractitionerRole", "id": f"role-{emp.lower()}",
            "active": True,
            "period": {"start": start},
            "practitioner": ref("Practitioner", pid, f"{given} {family}"),
            "organization": ref("Organization", f"org-{dept.lower()}", self.dept_name(dept)),
            "code": [code],
        }
        if role == "Doctor":
            prole["specialty"] = [{"text": person["specialty"]}]
        if role == "MOA":
            desk = self.p["moaDesks"][dept]
            prole["location"] = [ref("Location", f"loc-{desk.lower()}", self.loc_name(desk))]
            prole["telecom"] = [{"system": "phone", "value": f"ext. {2100 + len(self.staff)}", "use": "work"}]
        self.add(prole)
        self.staff.append({"key": person.get("key"), "role": role, "department": dept,
                           "id": pid, "employee": emp, "name": f"{given} {family}"})

    def seeded_people(self) -> list[dict]:
        used = {(u.get("given"), u.get("family")) for u in self.p["demoUsers"]}
        people = []
        demo_counts: Counter = Counter()
        for u in self.p["demoUsers"]:
            if u["role"] in ("Nurse", "MOA"):
                demo_counts[(u["role"], u["department"])] += 1
        for role_key, role in (("nurse", "Nurse"), ("moa", "MOA")):
            for dept in sorted(self.p["staffCounts"][role_key], key=self.dept_order):
                need = self.p["staffCounts"][role_key][dept] - demo_counts[(role, dept)]
                for _ in range(need):
                    while True:
                        given = self.rng.choice(FIRST_NAMES)
                        family = self.rng.choice(LAST_NAMES)
                        if (given, family) not in used:
                            used.add((given, family))
                            break
                    langs = ["en"] + ([self.rng.choice(EXTRA_LANGUAGES)] if self.rng.random() < 0.5 else [])
                    person = {"role": role, "given": given, "family": family,
                              "gender": self.rng.choice(["female", "male"]),
                              "department": dept, "languages": langs}
                    if role == "Nurse":
                        person["designation"] = self.rng.choice(["RN", "RN", "RN", "LPN", "NP"])
                    else:
                        person["certified"] = self.rng.random() < 0.6
                    people.append(person)
        return people

    def dept_order(self, code: str) -> int:
        return [d["code"] for d in self.p["departments"]].index(code)

    def all_staff(self) -> None:
        for u in self.p["demoUsers"]:
            if u["role"] != "Patient":
                self.practitioner(u)
        for person in self.seeded_people():
            self.practitioner(person)

    def staff_by_key(self, key: str) -> dict:
        return next(s for s in self.staff if s["key"] == key)

    def nurses_in(self, dept: str) -> list[dict]:
        return [s for s in self.staff if s["role"] == "Nurse" and s["department"] == dept]

    # ----- Patient A (the 3MT slide patient) -----
    def patient_a(self) -> None:
        sofia = self.staff_by_key("sofia")
        okafor = self.staff_by_key("okafor")
        brennan = self.staff_by_key("brennan")
        pat_id = "pat-elena-marsh"
        pat_ref = ref("Patient", pat_id, "Elena Marsh")
        self.add({
            "resourceType": "Patient", "id": pat_id,
            "identifier": [
                {"system": self.sid["mrn"], "value": "MRN-000001",
                 "type": concept("http://terminology.hl7.org/CodeSystem/v2-0203", "MR", "Medical record number")},
                {"system": self.sid["bcPhn"], "value": synthetic_phn(self.rng),
                 "type": {"text": "BC Personal Health Number (synthetic)"}},
            ],
            "name": [{"use": "official", "family": "Marsh", "given": ["Elena"]}],
            "telecom": [{"system": "phone", "value": "+1-508-555-0142", "use": "mobile"}],
            "gender": "female",
            "birthDate": "1971-05-14",
            "address": [{"line": ["42 Elm Street"], "city": "Worcester", "state": "MA",
                         "postalCode": "01609", "country": "US"}],
            "communication": [{"language": concept(LANG, "en", "English")}],
        })
        self.add({
            "resourceType": "Medication", "id": "med-amlodipine-5mg",
            "code": concept(RXNORM, "197361", "Amlodipine 5 MG Oral Tablet"),
            "form": concept(SNOMED, "385055001", "Tablet"),
        })

        def encounter(eid: str, start: str, end: str, dept: str, loc: str, doctor: dict, reason: str) -> None:
            self.add({
                "resourceType": "Encounter", "id": eid,
                "identifier": [{"system": f"{self.base}/sid/encounter", "value": eid.upper()}],
                "status": "finished",
                "class": coding(ACT_CODE, "AMB", "ambulatory"),
                "type": [{"text": reason}],
                "subject": pat_ref,
                "participant": [{"individual": ref("Practitioner", doctor["id"], doctor["name"])}],
                "period": {"start": start, "end": end},
                "reasonCode": [{"text": reason}],
                "location": [{"location": ref("Location", f"loc-{loc.lower()}", self.loc_name(loc)),
                              "period": {"start": start, "end": end}}],
                "serviceProvider": ref("Organization", f"org-{dept.lower()}", self.dept_name(dept)),
            })

        encounter("enc-elena-2025-08-20", "2025-08-20T09:30:00-04:00", "2025-08-20T10:00:00-04:00",
                  "CARD", "CARD-401", brennan, "Blood pressure check")
        encounter("enc-elena-2026-10-02", "2026-10-02T10:00:00-04:00", "2026-10-02T11:30:00-04:00",
                  "FAMMED", "FAMMED-ROOM1", okafor, "Penicillin allergy test")

        def message(mid: str, sender: dict, sent: str, medium: str, origin: str, text: str) -> None:
            self.add({
                "resourceType": "Communication", "id": mid,
                "identifier": [{"system": self.sid["message"], "value": mid.upper()}],
                "extension": [{"url": self.ext["origin"], "valueCode": origin}],
                "status": "completed",
                "medium": [concept(PART_MODE, medium, medium.title())],
                "subject": pat_ref,
                "sent": sent,
                "sender": ref("Practitioner", sender["id"], sender["name"]),
                "payload": [{"contentString": text}],
            })

        message("msg-elena-2019-06-12", sofia, "2019-06-12T10:15:00-04:00", "PHONE", "Patient",
                "Phone call. The patient says that she had a rash after penicillin as a child.")
        message("msg-elena-2024-03-05", sofia, "2024-03-05T14:00:00-05:00", "ELECTRONIC", "OtherClinic",
                "Records copied from Lakeside Family Clinic. The records list a penicillin allergy.")
        message("msg-elena-2025-08-20", brennan, "2025-08-20T10:05:00-04:00", "FACE", "Staff",
                "Visit note. Blood pressure is high on two readings. Diagnosis: essential hypertension. "
                "Start amlodipine 5 mg daily. Order a lipid panel.")
        message("msg-elena-2025-08-22", brennan, "2025-08-22T16:00:00-04:00", "ELECTRONIC", "Lab",
                "Lipid panel result received. LDL cholesterol is 112 mg/dL.")
        message("msg-elena-2026-10-02", okafor, "2026-10-02T11:40:00-04:00", "FACE", "Staff",
                "Visit note. The penicillin skin test and the oral challenge are negative. "
                "The patient is not allergic to penicillin.")

        # The penicillin allergy has three versions. Each version is one claim.
        allergy_id = "ai-elena-penicillin"
        versions = [
            ("1", "2019-06-12T10:15:00-04:00", "active", "unconfirmed", None,
             "Patient report: rash after penicillin as a child.", sofia),
            ("2", "2024-03-05T14:00:00-05:00", "active", "unconfirmed", None,
             "Penicillin allergy (copied from Lakeside Family Clinic).", sofia),
            ("3", "2026-10-02T11:30:00-04:00", "inactive", "refuted", "enc-elena-2026-10-02",
             "Not allergic. Allergy test negative.", okafor),
        ]
        for vid, when, clinical, verification, enc, note, who in versions:
            res = {
                "resourceType": "AllergyIntolerance", "id": allergy_id,
                "meta": {"versionId": vid, "lastUpdated": when},
                "clinicalStatus": concept("http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                                          clinical, clinical.title()),
                "verificationStatus": concept("http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                                              verification, verification.title()),
                "type": "allergy",
                "category": ["medication"],
                "criticality": "low",
                "code": concept(SNOMED, "91936005", "Allergy to penicillin"),
                "patient": pat_ref,
                "recordedDate": "2019-06-12T10:15:00-04:00",
                "recorder": ref("Practitioner", who["id"], who["name"]),
                "note": [{"text": note}],
            }
            if enc:
                res["encounter"] = ref("Encounter", enc)
            self.add(res)

        enc1 = ref("Encounter", "enc-elena-2025-08-20")
        enc2 = ref("Encounter", "enc-elena-2026-10-02")
        self.add({
            "resourceType": "Observation", "id": "obs-elena-bp-2025-08-20", "status": "final",
            "category": [concept("http://terminology.hl7.org/CodeSystem/observation-category", "vital-signs", "Vital Signs")],
            "code": concept(LOINC, "85354-9", "Blood pressure panel with all children optional"),
            "subject": pat_ref, "encounter": enc1, "effectiveDateTime": "2025-08-20T09:40:00-04:00",
            "component": [
                {"code": concept(LOINC, "8480-6", "Systolic blood pressure"),
                 "valueQuantity": {"value": 152, "unit": "mm[Hg]", "system": UCUM, "code": "mm[Hg]"}},
                {"code": concept(LOINC, "8462-4", "Diastolic blood pressure"),
                 "valueQuantity": {"value": 96, "unit": "mm[Hg]", "system": UCUM, "code": "mm[Hg]"}},
            ],
        })
        self.add({
            "resourceType": "Condition", "id": "cond-elena-hypertension",
            "clinicalStatus": concept("http://terminology.hl7.org/CodeSystem/condition-clinical", "active", "Active"),
            "verificationStatus": concept("http://terminology.hl7.org/CodeSystem/condition-ver-status", "confirmed", "Confirmed"),
            "severity": concept(SNOMED, "6736007", "Moderate"),
            "code": concept(SNOMED, "59621000", "Essential hypertension"),
            "subject": pat_ref, "encounter": enc1,
            "onsetDateTime": "2025-08-20T09:40:00-04:00", "recordedDate": "2025-08-20T10:00:00-04:00",
            "recorder": ref("Practitioner", brennan["id"], brennan["name"]),
            "note": [{"text": "Essential hypertension. Two high readings."}],
        })
        self.add({
            "resourceType": "MedicationRequest", "id": "mr-elena-amlodipine", "status": "active", "intent": "order",
            "medicationReference": ref("Medication", "med-amlodipine-5mg", "Amlodipine 5 MG Oral Tablet"),
            "subject": pat_ref, "encounter": enc1, "authoredOn": "2025-08-20T10:00:00-04:00",
            "requester": ref("Practitioner", brennan["id"], brennan["name"]),
            "dosageInstruction": [{
                "text": "5 mg by mouth once a day",
                "timing": {"repeat": {"frequency": 1, "period": 1, "periodUnit": "d"}},
                "doseAndRate": [{"doseQuantity": {"value": 5, "unit": "mg", "system": UCUM, "code": "mg"}}],
            }],
            "note": [{"text": "Start amlodipine 5 mg daily."}],
        })
        self.add({
            "resourceType": "ServiceRequest", "id": "sr-elena-lipid-panel", "status": "completed", "intent": "order",
            "priority": "routine",
            "category": [concept(SNOMED, "108252007", "Laboratory procedure")],
            "code": concept(LOINC, "57698-3", "Lipid panel with direct LDL - Serum or Plasma"),
            "subject": pat_ref, "encounter": enc1, "authoredOn": "2025-08-20T10:00:00-04:00",
            "requester": ref("Practitioner", brennan["id"], brennan["name"]),
            "specimen": [{"display": "Serum"}],
        })
        self.add({
            "resourceType": "DiagnosticReport", "id": "dr-elena-lipid-panel", "status": "final",
            "basedOn": [ref("ServiceRequest", "sr-elena-lipid-panel")],
            "category": [concept("http://terminology.hl7.org/CodeSystem/v2-0074", "LAB", "Laboratory")],
            "code": concept(LOINC, "57698-3", "Lipid panel with direct LDL - Serum or Plasma"),
            "subject": pat_ref, "encounter": enc1,
            "effectiveDateTime": "2025-08-21T08:00:00-04:00", "issued": "2025-08-22T15:30:00-04:00",
            "conclusion": "LDL cholesterol is 112 mg/dL. It is in the target range.",
        })
        self.add({
            "resourceType": "Procedure", "id": "proc-elena-penicillin-test", "status": "completed",
            "code": concept(LOCAL, "penicillin-allergy-test", "Penicillin skin test and oral challenge"),
            "subject": pat_ref, "encounter": enc2,
            "performedPeriod": {"start": "2026-10-02T10:10:00-04:00", "end": "2026-10-02T11:20:00-04:00"},
            "performer": [{"actor": ref("Practitioner", okafor["id"], okafor["name"])}],
            "outcome": {"text": "Negative. No reaction."},
        })

        # One Provenance per claim. The bundle order gives the position (Seq) in each message.
        def provenance(pid: str, target: str, recorded: str, who: dict, source: str, intent: str,
                       revision: str | None = None) -> None:
            entity = [{"role": "source", "what": {"reference": f"Communication/{source}"}}]
            if revision:
                entity.append({"role": "revision", "what": {"reference": revision}})
            self.add({
                "resourceType": "Provenance", "id": pid,
                "extension": [{"url": self.ext["intent"], "valueCode": intent}],
                "target": [{"reference": target}],
                "recorded": recorded,
                "agent": [{
                    "type": concept("http://terminology.hl7.org/CodeSystem/provenance-participant-type", "author", "Author"),
                    "who": ref("Practitioner", who["id"], who["name"]),
                }],
                "entity": entity,
            })

        allergy = f"AllergyIntolerance/{allergy_id}/_history"
        provenance("prov-elena-pen-1", f"{allergy}/1", "2019-06-12T10:15:00-04:00", sofia,
                   "msg-elena-2019-06-12", "Report")
        provenance("prov-elena-pen-2", f"{allergy}/2", "2024-03-05T14:00:00-05:00", sofia,
                   "msg-elena-2024-03-05", "Report", revision=f"{allergy}/1")
        provenance("prov-elena-bp", "Observation/obs-elena-bp-2025-08-20", "2025-08-20T10:05:00-04:00", brennan,
                   "msg-elena-2025-08-20", "Report")
        provenance("prov-elena-hypertension", "Condition/cond-elena-hypertension", "2025-08-20T10:05:00-04:00",
                   brennan, "msg-elena-2025-08-20", "Decision")
        provenance("prov-elena-amlodipine", "MedicationRequest/mr-elena-amlodipine", "2025-08-20T10:05:00-04:00",
                   brennan, "msg-elena-2025-08-20", "Decision")
        provenance("prov-elena-lipid-order", "ServiceRequest/sr-elena-lipid-panel", "2025-08-20T10:05:00-04:00",
                   brennan, "msg-elena-2025-08-20", "Decision")
        provenance("prov-elena-lipid-report", "DiagnosticReport/dr-elena-lipid-panel", "2025-08-22T16:00:00-04:00",
                   brennan, "msg-elena-2025-08-22", "Report")
        provenance("prov-elena-penicillin-test", "Procedure/proc-elena-penicillin-test", "2026-10-02T11:40:00-04:00",
                   okafor, "msg-elena-2026-10-02", "Decision")
        provenance("prov-elena-pen-3", f"{allergy}/3", "2026-10-02T11:40:00-04:00", okafor,
                   "msg-elena-2026-10-02", "Decision", revision=f"{allergy}/2")

        self.care_team("ct-elena", "CT-ELENA", pat_ref, [okafor, brennan], "2025-08-20T09:30:00-04:00",
                       "Elena Marsh care team")

    def care_team(self, cid: str, value: str, subject: dict, members: list[dict], start: str, name: str) -> None:
        participants = []
        for m in members:
            if "npi" in m:
                member = {"reference": f"Practitioner?identifier={self.sid['npi']}|{m['npi']}"}
                role = "Doctor"
            else:
                member = ref("Practitioner", m["id"], m["name"])
                role = m["role"]
            participants.append({"role": [{"text": role}], "member": member})
        self.add({
            "resourceType": "CareTeam", "id": cid,
            "identifier": [{"system": self.sid["careTeam"], "value": value}],
            "status": "active",
            "name": name,
            "subject": subject,
            "period": {"start": start},
            "participant": participants,
            "managingOrganization": [ref("Organization", "org-triad-gh")],
        })

    # ----- care teams for Synthea patients -----
    def synthea_care_teams(self, synthea: dict) -> None:
        for pid in sorted(synthea["patients"]):
            if pid in synthea["activeCareTeam"]:
                continue
            latest = synthea["latestEncounter"].get(pid)
            if latest is None:
                continue
            dept = self.department_for(latest["class"], latest["providerName"])
            nurses = self.nurses_in(dept) or self.nurses_in("FAMMED")
            nurse = nurses[int(hashlib.sha256(pid.encode()).hexdigest(), 16) % len(nurses)]
            members: list[dict] = []
            if latest["npi"]:
                members.append({"npi": latest["npi"]})
            members.append(nurse)
            self.care_team(f"ct-syn-{pid[:8]}", f"CT-SYN-{pid[:8].upper()}", ref("Patient", pid),
                           members, latest["start"], "Generated care team (latest visit)")

    def department_for(self, act_class: str, provider_name: str) -> str:
        rule = self.p["classToDepartment"].get(act_class, "FAMMED")
        if isinstance(rule, str):
            return rule
        for needle, dept in rule.get("providerNameContains", {}).items():
            if needle in (provider_name or "").upper():
                return dept
        return rule["default"]

    # ----- demo activity (chat and audit) -----
    def demo_activity(self) -> dict:
        okafor = self.staff_by_key("okafor")
        jun = self.staff_by_key("jun")
        elena = "Patient/pat-elena-marsh"
        return {
            "description": "Demo rows for the agent tables. The loader maps the FHIR references to rows.",
            "chatSessions": [{
                "identifier": "CHAT-0001",
                "patient": elena,
                "staff": f"Practitioner/{okafor['id']}",
                "userRole": "Doctor",
                "startedAt": "2026-10-29T15:00:00-04:00",
                "mode": "rules",
                "model": None,
                "turns": [
                    {"seq": 1, "clientTurnId": "demo-0001-1", "speaker": "User",
                     "text": "Is she allergic to penicillin?", "createdAt": "2026-10-29T15:00:05-04:00"},
                    {"seq": 2, "clientTurnId": "demo-0001-2", "speaker": "Assistant",
                     "text": "No. A physician ruled it out with an allergy test on Oct 2, 2026.",
                     "createdAt": "2026-10-29T15:00:06-04:00",
                     "citations": [{"provenance": "Provenance/prov-elena-pen-3", "rank": 1}]},
                ],
            }],
            "auditEvents": [
                {"identifier": "AUDIT-0001", "at": "2026-10-29T14:59:00-04:00", "action": "read",
                 "outcome": "Allowed", "userRole": "Doctor", "actorStaff": f"Practitioner/{okafor['id']}",
                 "patient": elena, "path": "/api/patients/{patient}/chart"},
                {"identifier": "AUDIT-0002", "at": "2026-10-29T15:00:06-04:00", "action": "ask",
                 "outcome": "Allowed", "userRole": "Doctor", "actorStaff": f"Practitioner/{okafor['id']}",
                 "patient": elena, "path": "/api/chat/sessions/{session}/turns", "chatTurn": "CHAT-0001#2"},
                {"identifier": "AUDIT-0003", "at": "2026-10-29T16:20:00-04:00", "action": "read",
                 "outcome": "Denied", "userRole": "Nurse", "actorStaff": f"Practitioner/{jun['id']}",
                 "patient": elena, "path": "/api/patients/{patient}/chart"},
                {"identifier": "AUDIT-0004", "at": "2026-10-29T18:00:00-04:00", "action": "read",
                 "outcome": "Allowed", "userRole": "Patient", "actorPatient": elena,
                 "patient": elena, "path": "/api/audit"},
            ],
        }

    def bundle(self) -> dict:
        return {
            "resourceType": "Bundle",
            "id": "triad-scenarios",
            "meta": {"lastUpdated": self.p["triadNow"]},
            "type": "collection",
            "timestamp": self.p["triadNow"],
            "entry": self.entries,
        }


def synthetic_phn(rng: random.Random) -> str:
    """Return a 10-digit number in the BC PHN format. It is synthetic."""
    weights = [2, 4, 8, 5, 10, 9, 7, 3]
    while True:
        body = [rng.randint(0, 9) for _ in range(8)]
        total = sum((d * w) % 11 for d, w in zip(body, weights))
        check = 11 - (total % 11)
        if check < 10:
            return "9" + "".join(str(d) for d in body) + str(check)


def scan_synthea(profile: dict) -> dict:
    """Read the Synthea NDJSON once. Collect the facts that this script needs."""
    now_date = profile["triadNow"][:10]
    adult_limit = f"{int(now_date[:4]) - 18}{now_date[4:]}"
    patients: dict = {}
    counts: Counter = Counter()
    meds = defaultdict(list)
    allergies = defaultdict(list)
    active_ct: set = set()
    encounters = defaultdict(list)
    org_names: dict = {}

    def pid_of(reference: str) -> str:
        return reference.split(":")[-1].split("/")[-1]

    with gzip.open(SYNTHEA, "rt", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            t = r["resourceType"]
            if t == "Patient":
                patients[r["id"]] = r
                counts[r["id"]] += 1
                continue
            if t == "Organization":
                for ident in r.get("identifier", []):
                    org_names[ident["value"]] = r.get("name", "")
                continue
            subject = (r.get("subject") or r.get("patient") or {}).get("reference")
            if not subject:
                continue
            p = pid_of(subject)
            counts[p] += 1
            if t == "MedicationRequest":
                cc = r.get("medicationCodeableConcept") or {}
                text = cc.get("text") or (cc.get("coding") or [{}])[0].get("display") or ""
                meds[p].append((r.get("status"), text))
            elif t == "AllergyIntolerance":
                allergies[p].append((r.get("code") or {}).get("text") or "")
            elif t == "CareTeam" and r.get("status") == "active":
                active_ct.add(p)
            elif t == "Encounter":
                npi = None
                for part in r.get("participant", []):
                    reference = (part.get("individual") or {}).get("reference", "")
                    if "us-npi|" in reference:
                        npi = reference.split("|")[-1]
                        break
                provider = (r.get("serviceProvider") or {}).get("reference", "").split("|")[-1]
                encounters[p].append({"start": r["period"]["start"], "class": r["class"]["code"],
                                      "npi": npi, "providerId": provider})
    latest = {}
    for p, items in encounters.items():
        last = max(items, key=lambda e: (e["start"], e["providerId"]))
        last["providerName"] = org_names.get(last["providerId"], "")
        latest[p] = last

    eligible = []
    for p, r in patients.items():
        alive = "deceasedDateTime" not in r
        adult = r["birthDate"] <= adult_limit
        metformin = any(s == "active" and "metformin" in text.lower() for s, text in meds[p])
        penicillin = any("penicillin" in a.lower() for a in allergies[p])
        if alive and adult and metformin and not penicillin:
            eligible.append((counts[p], p))
    eligible.sort()
    return {"patients": patients, "activeCareTeam": active_ct, "latestEncounter": latest,
            "patientB": eligible[0][1] if eligible else None, "eligibleCount": len(eligible)}


def main() -> None:
    profile = load_json(RAW_DIR / "hospital_profile.json")
    synthea = scan_synthea(profile)

    pinned = profile["patientB"]["pinned"]
    chosen = synthea["patientB"]
    if chosen != pinned["id"]:
        sys.exit(f"Patient B changed: the scan gives {chosen}, the profile pins {pinned['id']}.")
    b = synthea["patients"][chosen]
    name = " ".join(b["name"][0].get("given", []) + [b["name"][0].get("family", "")])
    if name != pinned["name"] or b["birthDate"] != pinned["birthDate"]:
        sys.exit("Patient B name or birth date does not match the pinned values.")
    print(f"Patient B is correct: {name}, {b['birthDate']} ({synthea['eligibleCount']} eligible).")

    builder = Builder(profile)
    builder.organizations()
    builder.locations()
    builder.all_staff()
    builder.patient_a()
    builder.synthea_care_teams(synthea)

    jun = builder.staff_by_key("jun")
    for entry in builder.entries:
        res = entry["resource"]
        if res["resourceType"] == "CareTeam" and res["subject"]["reference"].endswith(chosen):
            members = [p["member"].get("reference", "") for p in res["participant"]]
            if any(m.endswith(jun["id"]) for m in members):
                sys.exit("Jun Park must not be on a care team of Patient B.")

    bundle = builder.bundle()
    (RAW_DIR / "triad_scenarios.fhir.json").write_text(
        json.dumps(bundle, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (RAW_DIR / "demo_activity.json").write_text(
        json.dumps(builder.demo_activity(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    types = Counter(e["resource"]["resourceType"] for e in bundle["entry"])
    roles = Counter(s["role"] for s in builder.staff)
    print("Bundle entries:", dict(sorted(types.items())))
    print("Staff:", dict(roles))
    print("Demo users:", {s["key"]: s["employee"] for s in builder.staff if s["key"]})


if __name__ == "__main__":
    main()
