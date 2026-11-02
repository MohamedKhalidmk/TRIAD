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
