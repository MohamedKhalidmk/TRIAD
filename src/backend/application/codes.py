"""Use case: the code presets of the record form and of the journey (doc/api.md section 4)."""
from __future__ import annotations

from typing import Optional

from domain.access import Actor
from domain.enums import ENTRY_CATEGORIES
from domain.errors import Invalid
from domain.views import CodePreset

from application.guard import require_role

LOINC = "http://loinc.org"
SNOMED = "http://snomed.info/sct"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
LOCAL = "https://triad.example/fhir/CodeSystem/local"


def _rx(code: str, name: str, dosage: Optional[str], frequency: Optional[str], status: str = "active") -> CodePreset:
    return CodePreset("Prescription", code, RXNORM, name,
                      {"medicationCode": code, "medicationSystem": RXNORM, "medicationName": name,
                       "dosage": dosage, "frequency": frequency, "status": status})


PRESETS: tuple[CodePreset, ...] = (
    # Observations: vital signs, the intake note and family history
    CodePreset("Observation", "8867-4", LOINC, "Heart rate", {"value": None, "unit": "/min"}),
    CodePreset("Observation", "85354-9", LOINC, "Blood pressure panel with all children optional",
               {"value": None, "unit": "mm[Hg]"}),
    CodePreset("Observation", "2708-6", LOINC, "Oxygen saturation in Arterial blood", {"value": None, "unit": "%"}),
    CodePreset("Observation", "8310-5", LOINC, "Body temperature", {"value": None, "unit": "Cel"}),
    CodePreset("Observation", "9279-1", LOINC, "Respiratory rate", {"value": None, "unit": "/min"}),
    CodePreset("Observation", "8661-1", LOINC, "Chief complaint", {"value": None, "unit": None}),
    CodePreset("Observation", "family-history", LOCAL, "Family history", {"value": None, "unit": None}),
    # Diagnoses
    CodePreset("Diagnosis", "195967001", SNOMED, "Asthma attack", {"clinicalStatus": "active", "severity": None}),
    CodePreset("Diagnosis", "84114007", SNOMED, "Heart failure", {"clinicalStatus": "active", "severity": None}),
    CodePreset("Diagnosis", "59621000", SNOMED, "Essential hypertension",
               {"clinicalStatus": "active", "severity": None}),
    # Prescriptions
    _rx("745752", "Salbutamol inhaler (albuterol 0.09 MG/ACTUAT inhaler)", "2 puffs", "every 4 hours as needed",
        "draft"),
    _rx("313988", "Furosemide 40 MG Oral Tablet", "40 mg", "once a day"),
    _rx("860975", "24 HR Metformin hydrochloride 500 MG Extended Release Oral Tablet", "500 mg", "once a day"),
    # Lab orders and lab results
    CodePreset("LabOrder", "89579-7", LOINC,
               "Troponin I.cardiac [Mass/volume] in Serum or Plasma by High sensitivity method",
               {"testName": "Troponin I (high sensitivity)", "priority": "stat", "specimen": "Blood"}),
    CodePreset("LabReport", "89579-7", LOINC,
               "Troponin I.cardiac [Mass/volume] in Serum or Plasma by High sensitivity method",
               {"issuedDate": None, "conclusion": None}),
    # Procedures and allergies
    CodePreset("Procedure", "29303009", SNOMED, "Electrocardiographic procedure", {"performedDate": None,
                                                                                   "outcome": None}),
    CodePreset("Allergy", "91936005", SNOMED, "Allergy to penicillin",
               {"substance": "Penicillin", "type": "allergy", "allergyCategory": "medication",
                "criticality": None, "clinicalStatus": "active"}),
)


def code_presets(actor: Actor, category: Optional[str]) -> list[CodePreset]:
    require_role(actor, "read_codes")
    if category and category not in ENTRY_CATEGORIES:
        raise Invalid("The category is not correct.", {"category": f"Use one of {', '.join(ENTRY_CATEGORIES)}."})
    return [p for p in PRESETS if not category or p.category == category]
