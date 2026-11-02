"""Unit tests of the onboarding rules (no database)."""
from __future__ import annotations

import importlib.util

import pytest

from application.onboarding.derive_supersedes import derive_prescription_renewals
from domain import records as d
from infrastructure import config
from infrastructure.fhir.mappers import _Mapper
from infrastructure.fhir.reader import ResourceIndex, identifier_from_reference


def test_observation_components_are_flattened():
    obs = {"resourceType": "Observation", "component": [
        {"code": {"text": "Systolic blood pressure"}, "valueQuantity": {"value": 120.0, "unit": "mm[Hg]"}},
        {"code": {"text": "Diastolic blood pressure"}, "valueQuantity": {"value": 80, "unit": "mm[Hg]"}}]}
    assert _Mapper.observation_value(obs) == (
        "Systolic blood pressure: 120 mm[Hg]; Diastolic blood pressure: 80 mm[Hg]", None)


@pytest.mark.parametrize("resource,expected", [
    ({"resourceType": "Condition", "verificationStatus": {"coding": [{"code": "refuted"}]}}, "Refuted"),
    ({"resourceType": "Observation", "status": "final"}, "Confirmed"),
    ({"resourceType": "Observation", "status": "preliminary"}, "Provisional"),
    ({"resourceType": "MedicationRequest", "status": "entered-in-error"}, "EnteredInError"),
    ({"resourceType": "MedicationRequest", "status": "active"}, "Confirmed"),
])
def test_verification_mapping(resource, expected):
    assert _Mapper.verification(resource) == expected


def test_reference_forms_resolve():
    index = ResourceIndex([
        {"resourceType": "Practitioner", "id": "p1", "identifier": [{"system": "npi", "value": "123"}]},
        {"resourceType": "AllergyIntolerance", "id": "a1", "meta": {"versionId": "2"}},
        {"resourceType": "AllergyIntolerance", "id": "a1", "meta": {"versionId": "1"}},
    ], "test")
    assert index.resolve({"reference": "urn:uuid:p1"}) == ("Practitioner", "p1", None)
    assert index.resolve({"reference": "Practitioner?identifier=npi|123"}) == ("Practitioner", "p1", None)
    assert index.resolve({"type": "Practitioner", "identifier": {"system": "npi", "value": "123"}}) == ("Practitioner", "p1", None)
    assert index.resolve({"reference": "AllergyIntolerance/a1/_history/1"}) == ("AllergyIntolerance", "a1", "1")
    assert index.get("AllergyIntolerance", "a1")["meta"]["versionId"] == "2"   # the latest version
    assert identifier_from_reference({"reference": "Practitioner?identifier=npi|123"}) == ("npi", "123")


def test_prescription_renewals_form_one_chain_per_patient_and_medication():
    system = config.SYNTHEA_SYSTEM
    batch = d.OnboardBatch(visits=[d.Visit(("v", "1"), ("P", "2000-01-01"), "AMB", "2020-01-01T00:00:00+00:00")])
    for i, when in enumerate(["2021-01-01", "2020-01-01", "2022-01-01"]):
        batch.entries.append(d.ClinicalEntry((system, f"MedicationRequest/{i}"), ("v", "1"), "Prescription",
                                             "860975", "rxnorm", "metformin", f"{when}T00:00:00+00:00",
                                             medication=("860975", "rxnorm")))
        batch.assertions.append(d.Assertion(f"MR/{i}", ("m", "1"), i + 1, (system, f"MedicationRequest/{i}"),
                                            f"{when}T00:00:00+00:00", "Decision", "Human", "Confirmed", "metformin"))
    stats = derive_prescription_renewals(batch, system)
    by_key = {a.key: a.supersedes for a in batch.assertions}
    assert by_key == {"MR/1": None, "MR/0": "MR/1", "MR/2": "MR/0"}
    assert stats == {"renewalGroups": 1, "renewalLinks": 2}


def test_the_er_tree_check_stops_on_a_loop():
    spec = importlib.util.spec_from_file_location("build_erd", config.BACKEND_DIR / "models" / "er" / "build_erd.py")
    build_erd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_erd)
    model = build_erd.Model()
    model.end("Has", "Patient"), model.end("Has", "Visit")
    model.end("During", "Visit"), model.end("During", "ClinicalEntry")
    with pytest.raises(SystemExit):
        model.end("ConcernsPatient", "ClinicalEntry")
        model.end("ConcernsPatient", "Patient")
