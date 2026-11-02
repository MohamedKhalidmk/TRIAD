#!/usr/bin/env python3
"""Generate the TRIAD ER diagram as a two-page draw.io file.

Page 1: the clinical core and the authorship model (the professor's comments).
Page 2: the agent layer (chat, citations), the audit log and the lineage store.

The diagram is a tree: there is exactly one path between any two entity sets.
Only the unary relationship Supersedes points back to its own entity set.
The script checks this rule and stops if a relationship closes a loop.

Make the diagram again after a model change:
    python3 src/backend/models/er/build_erd.py
    drawio -x -f pdf -a --crop -o TRIAD_ERD.pdf TRIAD_ERD.drawio

Notation (the same as the Milestone 2 diagram):
    box = entity; double box = weak entity; diamond = relationship;
    double diamond = identifying relationship; oval = attribute;
    double oval = multivalued attribute; ovals on an oval = composite attribute;
    solid underline = key; dashed underline = partial key;
    triangle = ISA (it points toward the subtypes); crow's feet = cardinality;
    grey = TRIAD contribution; dashed box = a copy of an entity from page 1.
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "TRIAD_ERD.drawio"

GREY = "#E6E6E6"
WHITE = "#FFFFFF"
BASE = "html=1;whiteSpace=wrap;strokeColor=#000000;fontColor=#000000;"
CARD = {"one": "ERmandOne", "zeroOne": "ERzeroToOne", "many": "ERzeroToMany", "oneMany": "ERoneToMany"}


class Model:
    """The entity sets and their links, over all pages. It checks that the graph is a tree."""

    def __init__(self) -> None:
        self.parent: dict[str, str] = {}
        self.rel_ends: dict[str, set[str]] = {}

    def find(self, x: str) -> str:
        while self.parent.setdefault(x, x) != x:
            x = self.parent[x]
        return x

    def join(self, a: str, b: str, why: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            sys.exit(f"Loop found: {why} links {a} and {b}, which already have a path.")
        self.parent[ra] = rb

    def end(self, rel: str, entity: str) -> None:
        ends = self.rel_ends.setdefault(rel, set())
        if entity in ends:
            return  # a unary relationship (for example Supersedes)
        for other in ends:
            self.join(other, entity, rel)
        ends.add(entity)


MODEL = Model()


class Page:
    def __init__(self, name: str, width: int, height: int):
        self.name, self.width, self.height = name, width, height
        self.cells: list[str] = []
        self.ids: dict[str, str] = {}
        self.entity_of: dict[str, str] = {}
        self.seq = 0

    def _id(self) -> str:
        self.seq += 1
        return f"c{self.seq}"

    def _vertex(self, value: str, style: str, x: float, y: float, w: float, h: float, key: str | None = None) -> str:
        cid = self._id()
        if key:
            self.ids[key] = cid
        self.cells.append(
            f'<mxCell id="{cid}" value="{html.escape(value, quote=True)}" style="{style}" vertex="1" parent="1">'
            f'<mxGeometry x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" as="geometry"/></mxCell>'
        )
        return cid

    def entity(self, key: str, label: str, cx: float, cy: float, weak: bool = False, grey: bool = False,
               copy: bool = False, w: float = 180, h: float = 56) -> None:
        style = "rounded=0;fontStyle=1;fontSize=19;" + BASE + f"fillColor={GREY if grey else WHITE};"
        if weak:
            style = "shape=ext;double=1;margin=4;" + style
        if copy:
            style += "dashed=1;"
        self._vertex(label, style, cx - w / 2, cy - h / 2, w, h, key)
        self.entity_of[key] = key
        MODEL.find(key)

    def relation(self, key: str, label: str, cx: float, cy: float, identifying: bool = False,
                 grey: bool = False, w: float = 150, h: float = 72) -> None:
        style = ("rhombus;double=1;" if identifying else "rhombus;") + "fontSize=15;" + BASE + \
            f"fillColor={GREY if grey else WHITE};"
        self._vertex(label, style, cx - w / 2, cy - h / 2, w, h, key)

    def isa(self, key: str, cx: float, cy: float, direction: str = "south", note: str = "Disjoint, total") -> None:
        style = f"triangle;direction={direction};fontSize=15;verticalAlign=top;spacingTop=2;" + BASE + "fillColor=#FFFFFF;"
        self._vertex("ISA", style, cx - 35, cy - 35, 70, 70, key)
        nx, ny = (cx - 60, cy + 40) if direction == "east" else (cx + 40, cy - 14)
        self._vertex(note, "text;html=1;align=left;verticalAlign=middle;fontSize=15;fontStyle=2;fontColor=#000000;",
                     nx, ny, 150, 28)

    def attr(self, owner: str, label: str, cx: float, cy: float, kind: str = "plain", grey: bool = False,
             key: str | None = None) -> None:
        width = max(104, 9.2 * len(label) + 34)
        fill = GREY if grey else WHITE
        style = "ellipse;fontSize=15;" + BASE + f"fillColor={fill};"
        value = label
        if kind == "key":
            style += "fontStyle=4;"
        elif kind == "partial":
            value = f'<span style="border-bottom:1px dashed #000000;">{html.escape(label)}</span>'
        elif kind == "multi":
            style = "ellipse;shape=doubleEllipse;fontSize=15;" + BASE + f"fillColor={fill};"
        aid = self._vertex(value, style, cx - width / 2, cy - 20, width, 40, key)
        self._edge(self.ids[owner], aid, "endArrow=none;startArrow=none;")

    def text(self, value: str, x: float, y: float, w: float, h: float, size: int = 15) -> None:
        self._vertex(value, f"text;html=1;align=left;verticalAlign=top;fontSize={size};fontColor=#000000;", x, y, w, h)

    def _edge(self, source: str, target: str, style: str, label: str = "") -> None:
        cid = self._id()
        self.cells.append(
            f'<mxCell id="{cid}" value="{html.escape(label, quote=True)}" '
            f'style="{style}endFill=0;endSize=14;html=1;strokeColor=#000000;fontSize=15;labelBackgroundColor=#FFFFFF;" '
            f'edge="1" parent="1" source="{source}" target="{target}"><mxGeometry relative="1" as="geometry"/></mxCell>'
        )

    def link(self, rel: str, ent: str, card: str, label: str = "",
             exit_: tuple[float, float] | None = None, entry: tuple[float, float] | None = None) -> None:
        style = f"endArrow={CARD[card]};startArrow=none;"
        if exit_:
            style += f"exitX={exit_[0]};exitY={exit_[1]};exitDx=0;exitDy=0;"
        if entry:
            style += f"entryX={entry[0]};entryY={entry[1]};entryDx=0;entryDy=0;"
        if label:
            style += "fontStyle=2;"
        self._edge(self.ids[rel], self.ids[ent], style, label)
        MODEL.end(rel, self.entity_of[ent])

    def isa_link(self, parent: str, isa: str, children: list[str]) -> None:
        self._edge(self.ids[parent], self.ids[isa], "endArrow=none;startArrow=none;")
        for child in children:
            self._edge(self.ids[isa], self.ids[child], "endArrow=none;startArrow=none;")
            MODEL.join(self.entity_of[parent], self.entity_of[child], "ISA")

    def legend(self, x: float, y: float, extra: list[str] | None = None) -> None:
        lines = [
            "<b>Legend</b>",
            "Box: entity. Double box: weak entity.",
            "Diamond: relationship. Double diamond: identifying relationship.",
            "Oval: attribute. Double oval: multivalued attribute.",
            "Ovals on an oval: composite attribute.",
            "Solid underline: key. Dashed underline: partial key.",
            "Triangle (ISA): subtypes; it points toward the subtypes.",
            "Crow's feet: two bars = exactly one; circle and bar = zero or one;",
            "circle and crow's foot = zero or many; bar and crow's foot = one or many.",
            "Grey: TRIAD contribution (authorship, revision, agent layer).",
            "<i>Identifier</i> = System + Value (composite, the FHIR Identifier).",
            "<i>Address</i> = Street, City, Region, PostalCode, Country (composite).",
            "The diagram is a tree: one path between any two entity sets.",
        ] + (extra or [])
        self._vertex("<br>".join(lines),
                     "text;html=1;align=left;verticalAlign=top;fontSize=14;fontColor=#000000;"
                     "strokeColor=#000000;fillColor=#FFFFFF;spacing=8;",
                     x, y, 610, 19 * len(lines) + 24)

    def xml(self, index: int) -> str:
        return (
            f'<diagram name="{html.escape(self.name)}" id="page{index}">'
            f'<mxGraphModel dx="1600" dy="1000" grid="1" gridSize="10" guides="1" page="1" '
            f'pageWidth="{self.width}" pageHeight="{self.height}" background="#FFFFFF">'
            f'<root><mxCell id="0"/><mxCell id="1" parent="0"/>{"".join(self.cells)}</root></mxGraphModel></diagram>'
        )


def page_core() -> Page:
    p = Page("Core and authorship", 3300, 1980)
    p.text("<b>TRIAD ER diagram, page 1: clinical core and authorship</b>", 40, 20, 1200, 30, size=22)

    # ----- The authorship chain (the professor's comment 2) -----
    p.entity("Staff", "Staff", 330, 900)
    p.relation("Issues", "Issues", 620, 900)
    p.entity("Message", "Message", 920, 900)
    p.relation("Contains", "Contains", 1210, 900, identifying=True, grey=True)
    p.entity("Assertion", "Assertion", 1500, 900, weak=True, grey=True)
    p.relation("About", "About", 1790, 900, grey=True)
    p.entity("ClinicalEntry", "ClinicalEntry", 2080, 900)
    p.relation("Supersedes", "Supersedes", 1500, 1130, grey=True)

    p.link("Issues", "Staff", "zeroOne")
    p.link("Issues", "Message", "many")
    p.link("Contains", "Message", "one")
    p.link("Contains", "Assertion", "many")
    p.link("About", "Assertion", "oneMany")
    p.link("About", "ClinicalEntry", "one")
    p.link("Supersedes", "Assertion", "zeroOne", "Replaces", exit_=(0, 0.5), entry=(0.15, 1))
    p.link("Supersedes", "Assertion", "zeroOne", "ReplacedBy", exit_=(1, 0.5), entry=(0.85, 1))
    p.text("A message without an issuer has Origin = Patient:<br>the patient sent it through the app.",
           640, 1000, 360, 50, size=14)

    for label, x, y, kind in [("Identifier", 780, 740, "key"), ("Channel", 920, 700, "plain"),
                              ("Origin", 1060, 740, "plain"), ("SentAt", 760, 810, "plain"),
                              ("Text", 1080, 810, "plain")]:
        p.attr("Message", label, x, y, kind)
    for label, x, y, kind in [("Seq", 1310, 750, "partial"), ("AssertedAt", 1390, 700, "plain"),
                              ("Intent", 1510, 670, "plain"), ("Source", 1630, 700, "plain"),
                              ("Verification", 1720, 750, "plain"), ("Statement", 1690, 810, "plain")]:
        p.attr("Assertion", label, x, y, kind, grey=True)
    for label, x, y, kind in [("Identifier", 1880, 750, "key"), ("Category", 1950, 700, "plain"),
                              ("Code", 2070, 670, "plain"), ("CodeSystem", 2200, 700, "plain"),
                              ("Display", 2290, 755, "plain"), ("Text", 2290, 810, "plain"),
                              ("RecordedAt", 1940, 815, "plain")]:
        p.attr("ClinicalEntry", label, x, y, kind)

    # ----- Staff, its subtypes and its department -----
    for label, x, y, kind in [("Identifier", 140, 830, "key"), ("Name", 120, 890, "plain"),
                              ("Sex", 130, 950, "plain"), ("Email", 160, 1010, "plain"),
                              ("PhoneNumber", 230, 1080, "plain"), ("Role", 520, 960, "plain"),
                              ("Active", 510, 1020, "plain"), ("Language", 520, 830, "multi")]:
        p.attr("Staff", label, x, y, kind)
    p.isa("StaffISA", 330, 690, direction="north")
    p.entity("Doctor", "Doctor", 140, 540, w=150)
    p.entity("Nurse", "Nurse", 330, 540, w=150)
    p.entity("MOA", "MOA", 520, 540, w=150)
    p.isa_link("Staff", "StaffISA", ["Doctor", "Nurse", "MOA"])
    for owner, items in [("Doctor", [("LicenseNumber", -65, 440), ("Qualification", 60, 370)]),
                         ("Nurse", [("LicenseNumber", -65, 440), ("Designation", 60, 370)]),
                         ("MOA", [("Desk", -85, 445), ("PhoneExtension", 70, 375), ("CertificationNumber", -40, 300)])]:
        x0 = {"Doctor": 140, "Nurse": 330, "MOA": 520}[owner]
        for label, dx, y in items:
            p.attr(owner, label, x0 + dx, y)

    p.relation("WorksIn", "WorksIn", 330, 1250)
    p.entity("Department", "Department", 330, 1560)
    p.link("WorksIn", "Staff", "many")
    p.link("WorksIn", "Department", "oneMany")
    for label, x, y in [("RoleCode", 140, 1200), ("Specialty", 140, 1290), ("StartDate", 530, 1200), ("EndDate", 530, 1290)]:
        p.attr("WorksIn", label, x, y)
    for label, x, y, kind in [("Identifier", 130, 1500, "key"), ("Name", 130, 1580, "plain"),
                              ("Type", 200, 1660, "plain"), ("PhoneNumber", 360, 1690, "plain"),
                              ("Email", 530, 1650, "plain"), ("Address", 540, 1530, "plain")]:
        p.attr("Department", label, x, y, kind)

    # ----- Visit, Patient and Location (the professor's comment 3) -----
    p.relation("During", "During", 2080, 1170)
    p.entity("Visit", "Visit", 2080, 1430)
    p.link("During", "ClinicalEntry", "many")
    p.link("During", "Visit", "one")
    p.relation("Has", "Has", 1730, 1430)
    p.entity("Patient", "Patient", 1380, 1430)
    p.link("Has", "Patient", "one")
    p.link("Has", "Visit", "many")
    for label, x, y, kind in [("Identifier", 2310, 1330, "key"), ("Class", 2330, 1380, "plain"),
                              ("Type", 2330, 1430, "plain"), ("Reason", 2330, 1480, "plain"),
                              ("StartDate", 2290, 1530, "plain"), ("EndDate", 2240, 1580, "plain")]:
        p.attr("Visit", label, x, y, kind)
    for label, x, y, kind in [("Name", 1180, 1340, "key"), ("DateOfBirth", 1150, 1430, "key"),
                              ("Sex", 1190, 1520, "plain"), ("PhoneNumber", 1350, 1570, "plain"),
                              ("Address", 1540, 1550, "plain"), ("Identifier", 1390, 1300, "multi")]:
        p.attr("Patient", label, x, y, kind)
    p.relation("TakesPlaceIn", "TakesPlaceIn", 2080, 1680, w=160)
    p.entity("Location", "Location", 2080, 1860)
    p.link("TakesPlaceIn", "Visit", "many")
    p.link("TakesPlaceIn", "Location", "many")
    p.attr("TakesPlaceIn", "StartDate", 1860, 1650)
    p.attr("TakesPlaceIn", "EndDate", 1870, 1710)
    for label, x, y, kind in [("Identifier", 2320, 1760, "key"), ("Name", 2340, 1820, "plain"),
                              ("Type", 2340, 1880, "plain"), ("PhysicalType", 2310, 1940, "plain"),
                              ("PhoneNumber", 1860, 1860, "plain"), ("Address", 1900, 1940, "plain")]:
        p.attr("Location", label, x, y, kind)

    # ----- ClinicalEntry subtypes (right column) -----
    p.isa("EntryISA", 2420, 900, direction="east")
    subtypes = [
        ("Diagnosis", ["OnsetDate", "AbatementDate", "ClinicalStatus", "Severity"]),
        ("Procedure", ["PerformedDate", "Outcome"]),
        ("Allergy", ["Substance", "Type", "AllergyCategory", "Criticality"]),
        ("Observation", ["Value", "Unit"]),
        ("LabOrder", ["TestName", "Priority", "Specimen"]),
        ("LabReport", ["IssuedDate", "Conclusion"]),
        ("CareTeam", ["Name", "Status"]),
        ("Prescription", ["Dosage", "Frequency", "Status"]),
    ]
    for i, (name, attrs) in enumerate(subtypes):
        cy = 150 + i * 160
        p.entity(name, name, 2740, cy, w=170)
        offsets = {2: [(2980, -25), (2980, 25)],
                   3: [(2975, -50), (3165, 0), (2975, 50)],
                   4: [(2975, -50), (3165, -22), (2975, 50), (3165, 22)]}[len(attrs)]
        for (x, dy), label in zip(offsets, attrs):
            p.attr(name, label, x, cy + dy)
    # CareTeam.Member is a multivalued composite attribute (a FHIR Reference by identifier).
    p.attr("CareTeam", "Member", 3170, 1110, kind="multi", key="CareTeamMember")
    p.attr("CareTeamMember", "Role", 3090, 1180)
    p.attr("CareTeamMember", "Identifier", 3250, 1175)
    p.isa_link("ClinicalEntry", "EntryISA", [name for name, _ in subtypes])
    p.relation("Prescribes", "Prescribes", 2740, 1460)
    p.entity("Medication", "Medication", 2740, 1650)
    p.link("Prescribes", "Prescription", "many")
    p.link("Prescribes", "Medication", "one")
    for label, x, y, kind in [("Code", 2960, 1600, "key"), ("CodeSystem", 2990, 1660, "key"),
                              ("Name", 2960, 1720, "plain"), ("Form", 2560, 1700, "plain"),
                              ("Manufacturer", 2680, 1770, "plain")]:
        p.attr("Medication", label, x, y, kind)

    p.legend(640, 1640, extra=["Page 2 shows the agent layer, the audit log and the lineage store."])
    return p


def page_agent() -> Page:
    p = Page("Agent layer, audit and lineage", 2600, 1500)
    p.text("<b>TRIAD ER diagram, page 2: agent layer, audit log and lineage store</b>", 40, 20, 1400, 30, size=22)

    p.entity("Assertion", "Assertion", 330, 640, weak=True, grey=True, copy=True)
    p.relation("Cites", "Cites", 640, 640, grey=True)
    p.entity("ChatTurn", "ChatTurn", 960, 640, weak=True, grey=True)
    p.link("Cites", "ChatTurn", "many")
    p.link("Cites", "Assertion", "many")
    p.attr("Cites", "Rank", 640, 750, grey=True)
    for label, x, y, kind in [("Seq", 1180, 560, "partial"), ("Speaker", 1210, 620, "plain"),
                              ("Text", 1200, 680, "plain"), ("CreatedAt", 1170, 740, "plain"),
                              ("ClientTurnId", 800, 770, "plain")]:
        p.attr("ChatTurn", label, x, y, kind, grey=True)

    p.relation("Includes", "Includes", 960, 420, identifying=True, grey=True)
    p.entity("ChatSession", "ChatSession", 960, 210, grey=True)
    p.link("Includes", "ChatSession", "one")
    p.link("Includes", "ChatTurn", "many")
    for label, x, y, kind in [("Identifier", 720, 150, "key"), ("StartedAt", 720, 230, "plain"),
                              ("Mode", 760, 300, "plain"), ("Model", 1180, 320, "plain")]:
        p.attr("ChatSession", label, x, y, kind, grey=True)
    p.attr("ChatSession", "User", 1200, 150, grey=True, key="ChatUser")
    p.attr("ChatUser", "Role", 1350, 90, grey=True)
    p.attr("ChatUser", "Identifier", 1400, 150, grey=True)
    p.attr("ChatSession", "Subject", 1220, 235, grey=True, key="ChatSubject")
    p.attr("ChatSubject", "Name", 1390, 225, grey=True)
    p.attr("ChatSubject", "DateOfBirth", 1430, 290, grey=True)

    p.relation("InTurn", "InTurn", 960, 900)
    p.entity("AuditEvent", "AuditEvent", 960, 1120)
    p.link("InTurn", "ChatTurn", "zeroOne")
    p.link("InTurn", "AuditEvent", "many")
    for label, x, y, kind in [("Identifier", 730, 1060, "key"), ("At", 730, 1130, "plain"),
                              ("Action", 760, 1200, "plain"), ("Outcome", 930, 1250, "plain"),
                              ("Path", 1100, 1250, "plain")]:
        p.attr("AuditEvent", label, x, y, kind)
    p.attr("AuditEvent", "Actor", 1210, 1080, key="AuditActor")
    p.attr("AuditActor", "Role", 1370, 1030)
    p.attr("AuditActor", "Identifier", 1410, 1090)
    p.attr("AuditEvent", "Subject", 1220, 1160, key="AuditSubject")
    p.attr("AuditSubject", "Name", 1400, 1160)
    p.attr("AuditSubject", "DateOfBirth", 1410, 1220)
    p.text("Chat sessions and audit records are logs. They keep the user and the patient as values<br>"
           "(User, Actor, Subject). The values stay correct when a row changes, and they add no loop.",
           40, 1330, 1300, 50, size=15)

    # Lineage store (physical layer).
    p.text("<b>Lineage store</b> (physical layer). It keeps every source FHIR resource as it came in,<br>"
           "so TRIAD can link to any FHIR server with almost no data loss. Each mapped row keeps<br>"
           "the value FhirRef (ResourceType/LogicalId/VersionId) of its source resource.",
           1640, 80, 900, 80, size=15)
    p.entity("FhirSource", "FhirSource", 2000, 330)
    p.relation("HoldsResource", "Holds\nResource", 2000, 560, identifying=True)
    p.entity("FhirResource", "FhirResource", 2000, 790, weak=True)
    p.link("HoldsResource", "FhirSource", "one")
    p.link("HoldsResource", "FhirResource", "many")
    for label, x, y, kind in [("Name", 1820, 250, "key"), ("BaseUrl", 2180, 250, "plain"),
                              ("FhirVersion", 2220, 320, "plain"), ("RetrievedAt", 2200, 390, "plain"),
                              ("Sha256", 1800, 400, "plain")]:
        p.attr("FhirSource", label, x, y, kind)
    for label, x, y, kind in [("ResourceType", 1780, 700, "partial"), ("LogicalId", 1790, 790, "partial"),
                              ("VersionId", 1800, 880, "partial"), ("LastUpdated", 2220, 740, "plain"),
                              ("Json", 2210, 840, "plain")]:
        p.attr("FhirResource", label, x, y, kind)

    p.legend(1640, 1000, extra=["Dashed box: a copy of an entity from page 1."])
    return p


def main() -> None:
    pages = [page_core(), page_agent()]
    xml = '<mxfile host="build_erd.py" type="device">' + "".join(pg.xml(i) for i, pg in enumerate(pages)) + "</mxfile>\n"
    OUT.write_text(xml, encoding="utf-8")
    groups: dict[str, list[str]] = {}
    for entity in MODEL.parent:
        groups.setdefault(MODEL.find(entity), []).append(entity)
    print(f"Wrote {OUT}")
    print(f"Tree check passed: {len(MODEL.parent)} entity sets, no loop. Connected parts:")
    for members in groups.values():
        print("  -", ", ".join(sorted(members)))


if __name__ == "__main__":
    main()
