# Source data

This folder holds the source data of the TRIAD prototype.
All data is synthetic. It does not contain real patient data.

## Synthea FHIR R4 sample

| Item | Value |
|---|---|
| Dataset | Synthea "100 Sample Synthetic Patient Records, FHIR R4" (US Core profiles) |
| URL | `https://raw.githubusercontent.com/synthetichealth/synthea-sample-data/84f59805d481b9f01f3141ef39e68bdbbeb80132/downloads/latest/synthea_sample_data_fhir_latest.zip` |
| Commit | `84f59805d481b9f01f3141ef39e68bdbbeb80132` |
| Zip size | 24,052,464 bytes |
| Zip SHA-256 | `66141b772671452f590f9b7bb999eb201f1f16beb94a84ab0885ed723b36b315` |
| Patients | 112 |
| Resources kept | 81,957 (all types except Claim and ExplanationOfBenefit) |

The zip file is not in git. The preprocessed file is in git:
`../preprocessed/synthea_r4.ndjson.gz`. The onboarding step reads that file.
It does not use the network.

### Get the data again

```bash
python3 src/scripts/fetch_synthea.py            # uses the zip in this folder, or downloads it
python3 src/scripts/fetch_synthea.py --refetch  # always downloads the zip again
```

The script checks the SHA-256 of the zip. If the SHA-256 does not match, the script stops.
The script writes the same output on each run.
`../preprocessed/manifest.json` records the SHA-256 of the uncompressed NDJSON.
Use that value to check a new output.

### Licence and citation

The Synthea software has the Apache 2.0 licence. The sample data repository does not state a licence.
The TRIAD licences do not cover the data in `src/backend/data/`.
If you use this data, cite Synthea:

> Walonoski J, Kramer M, Nichols J, et al. Synthea: An approach, method, and software mechanism
> for generating synthetic patients and the synthetic electronic health care record.
> *Journal of the American Medical Informatics Association* 2018;25(3):230–238.
> doi:10.1093/jamia/ocx079

## TRIAD scenario data

These files format the Synthea data to fit the user flows in `USER_FLOWS.md`.
They do not change the Synthea data.

| File | Kind | Content |
|---|---|---|
| `hospital_profile.json` | Written by hand | The one hospital (TRIAD General Hospital), its departments and locations, the rule that moves each Synthea visit to a department, the staff counts, the demo users and the pinned Patient B. |
| `triad_scenarios.fhir.json` | Made by a script | A FHIR R4 collection bundle: the hospital and its departments, the locations, the seeded staff (doctors, nurses, MOAs), Patient A and the history of Patient A, and the care teams of Synthea patients that do not have an active care team. |
| `demo_activity.json` | Made by a script | One saved chat of Patient A, with a citation, and four audit records (one denied access). |

### Make the scenario files again

```bash
python3 src/scripts/build_scenarios.py
```

The script uses a fixed seed. It writes the same files on each run.
It also checks that the pinned Patient B still meets the criteria.
If Patient B changes, the script stops.

### How the bundle shows TRIAD assertions in FHIR

- A `Communication` is a TRIAD message. The `sender` is the author. An extension gives the origin of the information (patient, staff, other clinic, PharmaNet or lab).
- A `Provenance` is a TRIAD assertion. The `target` is the clinical resource. The entity with the role `source` is the message.
- The entity with the role `revision` gives the earlier claim. This is the TRIAD "Supersedes" link.
- The penicillin allergy of Patient A has three versions (`meta.versionId` 1, 2 and 3). Each version is one claim: the 2019 phone report, the 2024 copy from another clinic, and the 2026 allergy test.

All 147 entries pass the FHIR R4B model checks of the `fhir.resources` Python package.
