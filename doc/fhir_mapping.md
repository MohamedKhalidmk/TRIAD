# FHIR R4 onboarding: the mapping to TRIAD

This document tells how the onboarding step (`python src/backend/main.py ensure-db`) loads FHIR R4
data into the TRIAD database. The code is in `src/backend/infrastructure/fhir/mappers.py` and
`src/backend/application/onboarding/`. The counts are in
`src/backend/data/preprocessed/onboard_report.json`.

## Sources

| Source | File | Identifier system for resources with no identifier |
|---|---|---|
| Synthea 100-sample, FHIR R4 (US Core), commit `84f5980` | `data/preprocessed/synthea_r4.ndjson.gz` | `https://github.com/synthetichealth/synthea` |
| TRIAD curated bundle (hospital, staff, Patient A, care teams) | `data/raw/triad_scenarios.fhir.json` | `https://triad.example/fhir` |
| Demo chat and audit rows | `data/raw/demo_activity.json` | — |

A resource with no identifier gets the key (source system, `ResourceType/id`).

## Resource → relation

| FHIR R4 | TRIAD | Rule |
|---|---|---|
| Organization (type `dept`) | Department | Only the TRIAD General departments. The hospital root and the Synthea providers are not mapped. |
| Location | Location | Only the TRIAD General locations. `Location.Type` holds the department name. The Synthea sites are not mapped. |
| Practitioner + PractitionerRole | Staff, StaffLanguage, WorksIn, Doctor / Nurse / MOA | The role code selects the subtype (`doctor` or NUCC 20x → Doctor, `nurse` → Nurse, `moa` → MOA). A Synthea doctor works in the department where they saw the most visits. |
| Patient | Patient, PatientIdentifier | Name = given names + family name. All identifiers are kept. |
| Encounter | Visit, VisitLocation | **Re-homed**: a Synthea visit goes to the default location of the department for its class (EMER → Emergency, IMP → Inpatient Medicine, HH → Home Health, VR → Virtual Care, AMB → Urgent Care for urgent-care providers, else Family Medicine). |
| DocumentReference (Synthea visit note) | Message | Issued by its author. The clinical resources of the same encounter become the assertions of this message (Seq in file order). |
| Communication (curated) | Message | `sender` → Issues; the origin extension → Origin; `medium` → Channel. |
| Condition, Procedure, AllergyIntolerance, Observation, ServiceRequest, DiagnosticReport (LAB), MedicationRequest, CareTeam | ClinicalEntry + subtype + Assertion | One entry per resource. For CareTeam, the Practitioner participants become Member values. |
| Provenance (curated) | Assertion | The author, the source message (`entity.role = source`) and the superseded claim (`entity.role = revision`). The intent extension → Intent. |
| Medication, `medicationCodeableConcept` | Medication | The key is (Code, CodeSystem). |

## Rules

1. **One entry, many claims.** FHIR versions of one resource (`meta.versionId`) are assertions about one entry. The entry takes its attributes from the latest version and its visit from the first version.
2. **Entries with no encounter.** A Synthea AllergyIntolerance has no encounter. It goes to the visit of the patient that contains its `recordedDate` (101 of 101 match). Its assertion goes into one message per patient, made from the Synthea Provenance of that patient.
3. **Intent.** Observation, LabReport and CareTeam claims are reports. The other claims are decisions.
4. **Verification.** Condition and AllergyIntolerance: their `verificationStatus`. Observation and DiagnosticReport: `final`, `amended`, `corrected` → Confirmed; `preliminary` → Provisional. Other types: Confirmed. Any `entered-in-error` → EnteredInError.
5. **Observation components** become one value, for example "Systolic blood pressure: 152 mm[Hg]; Diastolic blood pressure: 96 mm[Hg]".
6. **Derived Supersedes links (Synthea).** Synthea states no revisions. For one patient and one medication, a later prescription supersedes the earlier one (order: AssertedAt, then the entry identifier). This gives 234 chains with 2,515 links. The curated data states its links in Provenance.
7. **Messages with no fact.** A visit note whose encounter has no mapped clinical resource is not stored (226 notes). Each message in TRIAD has at least one assertion.

## Not mapped

These resources and links stay in the source files. They would close a loop in the ER tree, or the
prototype does not use them yet.

| Item | Count |
|---|---|
| Synthea Organization and Location (providers and sites), hospital root Organization | 268 and 268 |
| DiagnosticReport that is not LAB (visit notes and questionnaires) | 7,138 |
| Immunization, CarePlan, Device, ImagingStudy, MedicationAdministration, SupplyDelivery | 1,521, 327, 507, 377, 571, 2,507 |
| Claim, ExplanationOfBenefit (not in the preprocessed file) | 8,308 and 8,308 |
| Links: `Encounter.serviceProvider`, `Encounter.participant`, `Location.managingOrganization`, `Location.partOf`, `Organization.partOf`, the CareTeam participants that are not practitioners | — |

## Link another FHIR server

1. Export the data of the server as NDJSON with FHIR Bulk Data (`$export`).
2. Put the files in one gzip NDJSON file, in the same form as `synthea_r4.ndjson.gz`.
3. Point `SYNTHEA_PATH` in `src/backend/infrastructure/config.py` to the new file, and give the source its own identifier system.
4. Run `python src/backend/main.py ensure-db --reset-db`.

The mapper reads any FHIR R4 resource of the types above. A server that uses other reference forms
needs a change in `infrastructure/fhir/reader.py` only.
