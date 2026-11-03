"""Read FHIR R4 resources from NDJSON (gzip) files and from Bundles, and resolve references."""
from __future__ import annotations

import gzip
import json
from collections import defaultdict
from pathlib import Path
from typing import Iterator, Optional

Ref = tuple[str, str, Optional[str]]  # (ResourceType, logical id, versionId or None)


def read_ndjson_gz(path: Path) -> Iterator[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def read_bundle(path: Path) -> list[dict]:
    bundle = json.loads(Path(path).read_text(encoding="utf-8"))
    return [entry["resource"] for entry in bundle.get("entry", [])]


class ResourceIndex:
    """An index of resources from one source. It keeps the input order and all versions."""

    def __init__(self, resources: list[dict], system: str):
        self.system = system
        self.order: list[dict] = resources
        self.versions: dict[tuple[str, str], list[dict]] = defaultdict(list)
        self.type_of: dict[str, str] = {}
        self.by_identifier: dict[tuple[str, str, str], str] = {}
        for r in resources:
            rtype, rid = r["resourceType"], r["id"]
            self.versions[(rtype, rid)].append(r)
            self.type_of[rid] = rtype
            for ident in r.get("identifier", []) or []:
                if ident.get("system") and ident.get("value"):
                    self.by_identifier[(rtype, ident["system"], ident["value"])] = rid
        for items in self.versions.values():
            items.sort(key=lambda r: int((r.get("meta") or {}).get("versionId", "1")))

    def of_type(self, rtype: str) -> Iterator[dict]:
        """The latest version of each resource of one type, in input order."""
        seen = set()
        for r in self.order:
            if r["resourceType"] == rtype and r["id"] not in seen:
                seen.add(r["id"])
                yield self.versions[(rtype, r["id"])][-1]

    def get(self, rtype: str, rid: str, version: Optional[str] = None) -> Optional[dict]:
        items = self.versions.get((rtype, rid))
        if not items:
            return None
        if version is None:
            return items[-1]
        return next((r for r in items if (r.get("meta") or {}).get("versionId", "1") == version), None)

    def resolve(self, ref: Optional[dict], expected_type: Optional[str] = None) -> Optional[Ref]:
        """Resolve a FHIR Reference: urn:uuid, Type/id, Type/id/_history/n,
        Type?identifier=system|value, or a reference by identifier only."""
        if not ref:
            return None
        text = ref.get("reference")
        if text:
            if text.startswith("urn:uuid:"):
                rid = text[len("urn:uuid:"):]
                rtype = self.type_of.get(rid, expected_type)
                return (rtype, rid, None) if rtype else None
            if "?identifier=" in text:
                rtype, query = text.split("?identifier=", 1)
                system, _, value = query.partition("|")
                rid = self.by_identifier.get((rtype, system, value))
                return (rtype, rid, None) if rid else None
            parts = text.split("/")
            if len(parts) >= 2:
                version = parts[3] if len(parts) >= 4 and parts[2] == "_history" else None
                return (parts[0], parts[1], version)
            return None
        ident = ref.get("identifier")
        rtype = ref.get("type") or expected_type
        if ident and rtype:
            rid = self.by_identifier.get((rtype, ident.get("system"), ident.get("value")))
            return (rtype, rid, None) if rid else None
        return None


def identifier_from_reference(ref: Optional[dict]) -> Optional[tuple[str, str]]:
    """The (system, value) of a reference by identifier, for example Practitioner?identifier=npi|123."""
    if not ref:
        return None
    if ref.get("identifier"):
        return (ref["identifier"].get("system"), ref["identifier"].get("value"))
    text = ref.get("reference") or ""
    if "?identifier=" in text:
        system, _, value = text.split("?identifier=", 1)[1].partition("|")
        return (system, value)
    return None
