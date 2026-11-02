#!/usr/bin/env python3
"""Download the pinned Synthea FHIR R4 sample and write the preprocessed NDJSON.

The script does these steps:
1. It downloads the sample zip to a ".part" file and checks the SHA-256.
2. It reads the zip in memory. It does not extract the files.
3. It reads the bundle files in name order and keeps the entry order of each bundle.
4. It removes the billing resources (Claim, ExplanationOfBenefit).
5. It writes one resource per line to a gzip file with fixed settings.
6. It writes a manifest with the counts and the checksums.

The output is the same on each run. The manifest keeps the SHA-256 of the
uncompressed NDJSON, because gzip bytes can change between zlib builds.

Use only the Python standard library. Python 3.9 or later.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import io
import json
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "src" / "backend" / "data" / "raw"
OUT_DIR = REPO_ROOT / "src" / "backend" / "data" / "preprocessed"

COMMIT = "84f59805d481b9f01f3141ef39e68bdbbeb80132"
URL = (
    "https://raw.githubusercontent.com/synthetichealth/synthea-sample-data/"
    f"{COMMIT}/downloads/latest/synthea_sample_data_fhir_latest.zip"
)
SHA256 = "66141b772671452f590f9b7bb999eb201f1f16beb94a84ab0885ed723b36b315"
ZIP_NAME = "synthea_sample_data_fhir_r4.zip"
BILLING_TYPES = ("Claim", "ExplanationOfBenefit")


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(url: str, target: Path) -> None:
    part = target.with_suffix(target.suffix + ".part")
    print(f"Download {url}")
    with urllib.request.urlopen(url, timeout=120) as response, open(part, "wb") as out:
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    os.replace(part, target)


def load_zip(url: str, expected_sha: str, refetch: bool) -> bytes:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    target = RAW_DIR / ZIP_NAME
    if refetch or not target.exists():
        download(url, target)
    data = target.read_bytes()
    actual = sha256_of(data)
    if actual != expected_sha:
        sys.exit(
            f"SHA-256 does not match.\n  expected {expected_sha}\n  actual   {actual}\n"
            "Do not continue. The committed preprocessed file stays valid."
        )
    print(f"SHA-256 is correct ({len(data):,} bytes).")
    return data


def build(data: bytes, include_billing: bool) -> tuple[bytes, dict]:
    archive = zipfile.ZipFile(io.BytesIO(data))
    names = sorted(n for n in archive.namelist() if n.endswith(".json"))
    lines: list[bytes] = []
    kept: collections.Counter = collections.Counter()
    excluded: collections.Counter = collections.Counter()
    seen: set[tuple[str, str]] = set()
    duplicates = 0
    entries_with_request = 0
    for name in names:
        bundle = json.loads(archive.read(name))
        for entry in bundle.get("entry", []):
            if "request" in entry:
                entries_with_request += 1
            resource = entry["resource"]
            rtype = resource["resourceType"]
            if rtype in BILLING_TYPES and not include_billing:
                excluded[rtype] += 1
                continue
            key = (rtype, resource.get("id", ""))
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            kept[rtype] += 1
            lines.append(
                json.dumps(resource, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            )
    ndjson = b"\n".join(lines) + b"\n"
    manifest = {
        "source": {
            "name": "Synthea 100 Sample Synthetic Patient Records, FHIR R4",
            "url": URL,
            "commit": COMMIT,
            "zipSha256": SHA256,
            "zipBytes": len(data),
            "bundleFiles": len(names),
            "citation": (
                "Walonoski J, et al. Synthea: An approach, method, and software mechanism "
                "for generating synthetic patients and the synthetic electronic health care "
                "record. JAMIA 2018;25(3):230-238. doi:10.1093/jamia/ocx079"
            ),
        },
        "output": {
            "file": "synthea_r4.ndjson.gz",
            "ndjsonSha256": sha256_of(ndjson),
            "resources": len(lines),
            "order": "Bundle files in name order; entries in bundle order.",
        },
        "keptCounts": dict(sorted(kept.items())),
        "excludedCounts": dict(sorted(excluded.items())),
        "excludedNote": (
            "Billing resources are not kept. Provenance resources still reference them. "
            "The reader accepts references to excluded types."
        ),
        "droppedWrappers": {
            "note": "Bundle entry fullUrl and request are not kept. They can be rebuilt from the resource.",
            "entriesWithRequest": entries_with_request,
        },
        "duplicateResourcesSkipped": duplicates,
    }
    return ndjson, manifest


def write_outputs(ndjson: bytes, manifest: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    gz_path = OUT_DIR / "synthea_r4.ndjson.gz"
    with open(gz_path, "wb") as raw, gzip.GzipFile(
        filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9
    ) as gz:
        gz.write(ndjson)
    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {gz_path.relative_to(REPO_ROOT)} ({gz_path.stat().st_size:,} bytes)")
    print(f"Wrote {manifest_path.relative_to(REPO_ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=URL, help="Source zip URL (default: the pinned commit).")
    parser.add_argument("--sha256", default=SHA256, help="Expected SHA-256 of the zip.")
    parser.add_argument("--refetch", action="store_true", help="Download the zip again.")
    parser.add_argument("--include-billing", action="store_true", help="Keep Claim and ExplanationOfBenefit.")
    args = parser.parse_args()
    data = load_zip(args.url, args.sha256, args.refetch)
    ndjson, manifest = build(data, args.include_billing)
    write_outputs(ndjson, manifest)
    print(f"Resources kept: {manifest['output']['resources']:,}")
    print(f"NDJSON SHA-256: {manifest['output']['ndjsonSha256']}")


if __name__ == "__main__":
    main()
