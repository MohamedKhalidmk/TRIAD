#!/usr/bin/env python3
"""Generate the TRIAD ER diagram as a two-page draw.io file.

Page 1: the clinical core and the authorship model (the professor's comments).
Page 2: the agent layer (chat, citations), care teams, the audit log and the lineage store.

The layout is in this file, so the diagram can be made again after a model change:
    python3 src/backend/models/er/build_erd.py
    drawio -x -p 0 -f png -s 2 -o TRIAD_ERD_page1.png TRIAD_ERD.drawio

Notation (the same as the Milestone 2 diagram):
    box = entity; double box = weak entity; diamond = relationship;
    double diamond = identifying relationship; oval = attribute;
    double oval = multivalued attribute; solid underline = key; dashed underline = partial key;
    triangle = ISA (it points toward the subtypes); crow's feet = cardinality;
    grey = TRIAD contribution; dashed box = a copy of an entity from page 1.
"""
from __future__ import annotations

import html
from pathlib import Path

OUT = Path(__file__).resolve().parent / "TRIAD_ERD.drawio"

GREY = "#E6E6E6"
WHITE = "#FFFFFF"
BASE = "html=1;whiteSpace=wrap;strokeColor=#000000;fontColor=#000000;"
CARD = {
    "one": "ERmandOne",
    "zeroOne": "ERzeroToOne",
    "many": "ERzeroToMany",
    "oneMany": "ERoneToMany",
}


class Page:
    def __init__(self, name: str, width: int, height: int):
        self.name = name
        self.width = width
        self.height = height
        self.cells: list[str] = []
        self.ids: dict[str, str] = {}
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

    # Shapes are placed by their centre point.
    def entity(self, key: str, label: str, cx: float, cy: float, weak: bool = False, grey: bool = False,
               copy: bool = False, w: float = 180, h: float = 56) -> None:
        style = "rounded=0;fontStyle=1;fontSize=19;" + BASE + f"fillColor={GREY if grey else WHITE};"
        if weak:
            style = "shape=ext;double=1;margin=4;" + style
        if copy:
            style += "dashed=1;"
        self._vertex(label, style, cx - w / 2, cy - h / 2, w, h, key)

    def relation(self, key: str, label: str, cx: float, cy: float, identifying: bool = False,
                 grey: bool = False, w: float = 150, h: float = 72) -> None:
        style = "rhombus;fontSize=15;" + BASE + f"fillColor={GREY if grey else WHITE};"
        if identifying:
            style = "rhombus;double=1;fontSize=15;" + BASE + f"fillColor={GREY if grey else WHITE};"
        self._vertex(label, style, cx - w / 2, cy - h / 2, w, h, key)

    def isa(self, key: str, cx: float, cy: float, direction: str = "south", note: str = "Disjoint, total") -> None:
        style = f"triangle;direction={direction};fontSize=15;verticalAlign=top;spacingTop=2;" + BASE + "fillColor=#FFFFFF;"
        size = 70
        self._vertex("ISA", style, cx - size / 2, cy - size / 2, size, size, key)
        nx, ny = (cx - 60, cy + 40) if direction == "east" else (cx + 40, cy - 14)
        self._vertex(note, "text;html=1;align=left;verticalAlign=middle;fontSize=15;fontStyle=2;fontColor=#000000;",
                     nx, ny, 150, 28)

    def attr(self, owner: str, label: str, cx: float, cy: float, kind: str = "plain", grey: bool = False) -> None:
        width = max(112, 9.2 * len(label) + 34)
        style = "ellipse;fontSize=15;" + BASE + f"fillColor={GREY if grey else WHITE};"
        value = label
        if kind == "key":
            style += "fontStyle=4;"
        elif kind == "partial":
            value = f'<span style="border-bottom:1px dashed #000000;">{html.escape(label)}</span>'
        elif kind == "multi":
            style = "ellipse;shape=doubleEllipse;fontSize=15;" + BASE + f"fillColor={GREY if grey else WHITE};"
        aid = self._vertex(value, style, cx - width / 2, cy - 20, width, 40)
        self._edge(self.ids[owner], aid, "endArrow=none;startArrow=none;")

    def text(self, value: str, x: float, y: float, w: float, h: float, size: int = 15, style: str = "") -> None:
        self._vertex(value, f"text;html=1;align=left;verticalAlign=top;fontSize={size};fontColor=#000000;{style}",
                     x, y, w, h)

    def _edge(self, source: str, target: str, style: str, label: str = "", points: list[tuple[float, float]] | None = None) -> None:
        cid = self._id()
        pts = ""
        if points:
            pts = '<Array as="points">' + "".join(f'<mxPoint x="{x:.0f}" y="{y:.0f}"/>' for x, y in points) + "</Array>"
        self.cells.append(
            f'<mxCell id="{cid}" value="{html.escape(label, quote=True)}" '
            f'style="{style}endFill=0;endSize=14;html=1;strokeColor=#000000;fontSize=15;labelBackgroundColor=#FFFFFF;" '
            f'edge="1" parent="1" source="{source}" target="{target}">'
            f'<mxGeometry relative="1" as="geometry">{pts}</mxGeometry></mxCell>'
        )

    def link(self, rel: str, ent: str, card: str, label: str = "", points: list[tuple[float, float]] | None = None,
             exit_: tuple[float, float] | None = None, entry: tuple[float, float] | None = None, extra: str = "") -> None:
        style = f"endArrow={CARD[card]};startArrow=none;" + extra
        if exit_:
            style += f"exitX={exit_[0]};exitY={exit_[1]};exitDx=0;exitDy=0;"
        if entry:
            style += f"entryX={entry[0]};entryY={entry[1]};entryDx=0;entryDy=0;"
        if label:
            style += "fontStyle=2;"
        self._edge(self.ids[rel], self.ids[ent], style, label, points)

    def isa_link(self, parent: str, isa: str, children: list[str]) -> None:
        self._edge(self.ids[parent], self.ids[isa], "endArrow=none;startArrow=none;")
        for child in children:
            self._edge(self.ids[isa], self.ids[child], "endArrow=none;startArrow=none;")

    def legend(self, x: float, y: float, extra: list[str] | None = None) -> None:
        lines = [
            "<b>Legend</b>",
            "Box: entity. Double box: weak entity.",
            "Diamond: relationship. Double diamond: identifying relationship.",
            "Oval: attribute. Double oval: multivalued attribute.",
            "Solid underline: key. Dashed underline: partial key.",
            "Triangle (ISA): subtypes; it points toward the subtypes.",
            "Crow's feet: two bars = exactly one; circle and bar = zero or one;",
            "circle and crow's foot = zero or many; bar and crow's foot = one or many.",
            "Grey: TRIAD contribution (authorship, revision, agent layer).",
            "<i>Identifier</i> = System + Value (composite, the FHIR Identifier).",
            "<i>Address</i> = Street, City, Region, PostalCode, Country (composite).",
        ] + (extra or [])
        self._vertex("<br>".join(lines),
                     "text;html=1;align=left;verticalAlign=top;fontSize=14;fontColor=#000000;"
                     "strokeColor=#000000;fillColor=#FFFFFF;spacing=8;",
                     x, y, 600, 19 * len(lines) + 24)

    def xml(self, index: int) -> str:
        body = "".join(self.cells)
        return (
            f'<diagram name="{html.escape(self.name)}" id="page{index}">'
            f'<mxGraphModel dx="1600" dy="1000" grid="1" gridSize="10" guides="1" page="1" '
            f'pageWidth="{self.width}" pageHeight="{self.height}" background="#FFFFFF">'
            f'<root><mxCell id="0"/><mxCell id="1" parent="0"/>{body}</root></mxGraphModel></diagram>'
        )


def page_core() -> Page:
    p = Page("Core and authorship", 3400, 2150)
    p.text("<b>TRIAD ER diagram, page 1: clinical core and authorship</b>", 40, 20, 1200, 30, size=22)

    # ----- TRIAD core row -----
    p.entity("Message", "Message", 900, 760)
    p.relation("Contains", "Contains", 1200, 760, identifying=True, grey=True)
    p.entity("Assertion", "Assertion", 1500, 760, weak=True, grey=True)
    p.relation("About", "About", 1800, 760, grey=True)
    p.entity("ClinicalEntry", "ClinicalEntry", 2100, 760)
    p.relation("Supersedes", "Supersedes", 1500, 990, grey=True)

    p.link("Contains", "Message", "one")
    p.link("Contains", "Assertion", "many")
    p.link("About", "Assertion", "oneMany")
    p.link("About", "ClinicalEntry", "one")
    p.link("Supersedes", "Assertion", "zeroOne", "Replaces", exit_=(0, 0.5), entry=(0.15, 1))
    p.link("Supersedes", "Assertion", "zeroOne", "ReplacedBy", exit_=(1, 0.5), entry=(0.85, 1))

    for label, x, y, kind in [("Identifier", 760, 600, "key"), ("Channel", 900, 560, "plain"),
                              ("Origin", 1040, 600, "plain"), ("SentAt", 700, 680, "plain"),
                              ("Text", 1090, 680, "plain")]:
        p.attr("Message", label, x, y, kind)
    for label, x, y, kind in [("Seq", 1290, 610, "partial"), ("AssertedAt", 1380, 560, "plain"),
                              ("Intent", 1500, 530, "plain"), ("Source", 1620, 560, "plain"),
                              ("Verification", 1720, 610, "plain"), ("Statement", 1700, 670, "plain")]:
        p.attr("Assertion", label, x, y, kind, grey=True)
    for label, x, y, kind in [("Identifier", 1900, 610, "key"), ("Category", 1960, 560, "plain"),
                              ("Code", 2080, 530, "plain"), ("CodeSystem", 2210, 560, "plain"),
                              ("Display", 2300, 615, "plain"), ("Text", 2300, 670, "plain"),
                              ("RecordedAt", 1960, 680, "plain")]:
        p.attr("ClinicalEntry", label, x, y, kind)

    # ----- Patient and Visit -----
    p.entity("Patient", "Patient", 1500, 1300)
    p.relation("Sends", "Sends", 1100, 1140)
    p.relation("Discusses", "Discusses", 1290, 940)
    p.relation("ConcernsPatient", "Concerns\nPatient", 1860, 1060, w=160)
    p.link("Sends", "Message", "many")
    p.link("Sends", "Patient", "zeroOne")
    p.link("Discusses", "Message", "many")
    p.link("Discusses", "Patient", "one")
    p.link("ConcernsPatient", "ClinicalEntry", "many")
    p.link("ConcernsPatient", "Patient", "one")
    for label, x, y, kind in [("Name", 1340, 1440, "key"), ("DateOfBirth", 1490, 1470, "key"),
                              ("Sex", 1640, 1460, "plain"), ("PhoneNumber", 1750, 1405, "plain"),
                              ("Address", 1290, 1385, "plain"), ("Identifier", 1260, 1315, "multi")]:
        p.attr("Patient", label, x, y, kind)

    p.entity("Visit", "Visit", 2100, 1300)
    p.relation("During", "During", 2100, 1030)
    p.relation("Has", "Has", 1800, 1300)
    p.link("During", "ClinicalEntry", "many")
    p.link("During", "Visit", "zeroOne")
    p.link("Has", "Patient", "one")
    p.link("Has", "Visit", "many")
    for label, x, y, kind in [("Identifier", 2330, 1200, "key"), ("Class", 2350, 1250, "plain"),
                              ("Type", 2350, 1300, "plain"), ("Reason", 2350, 1350, "plain"),
                              ("StartDate", 2310, 1400, "plain"), ("EndDate", 2240, 1445, "plain")]:
        p.attr("Visit", label, x, y, kind)

    # ----- Location and Organization (bottom) -----
    p.entity("Location", "Location", 2100, 1820)
    p.relation("TakesPlaceIn", "TakesPlaceIn", 2100, 1580, w=160)
    p.link("TakesPlaceIn", "Visit", "many")
    p.link("TakesPlaceIn", "Location", "many")
    p.attr("TakesPlaceIn", "StartDate", 2300, 1560)
    p.attr("TakesPlaceIn", "EndDate", 2290, 1615)
    p.relation("Within", "Within", 2420, 1820)
    p.link("Within", "Location", "zeroOne", "Parent", exit_=(0.5, 0), entry=(1, 0.2))
    p.link("Within", "Location", "many", "Child", exit_=(0.5, 1), entry=(1, 0.8))
    for label, x, y, kind in [("Identifier", 1900, 1940, "key"), ("Name", 2030, 1980, "plain"),
                              ("Type", 2150, 1990, "plain"), ("PhysicalType", 2290, 1960, "plain"),
                              ("PhoneNumber", 1870, 1720, "plain"), ("Address", 2330, 1720, "plain")]:
        p.attr("Location", label, x, y, kind)

    p.entity("Organization", "Organization", 900, 1820)
    p.relation("ManagedBy", "ManagedBy", 1500, 1820)
    p.relation("ProvidedBy", "ProvidedBy", 1640, 1600)
    p.link("ManagedBy", "Location", "many")
    p.link("ManagedBy", "Organization", "zeroOne")
    p.link("ProvidedBy", "Visit", "many")
    p.link("ProvidedBy", "Organization", "zeroOne")
    p.relation("SubunitOf", "SubunitOf", 560, 1980)
    p.link("SubunitOf", "Organization", "zeroOne", "Parent", exit_=(0.5, 0), entry=(0, 0.3))
    p.link("SubunitOf", "Organization", "many", "Child", exit_=(1, 0.5), entry=(0.3, 1))
    for label, x, y, kind in [("Identifier", 1030, 1690, "key"), ("Name", 890, 1675, "plain"),
                              ("Type", 1180, 1650, "plain"), ("PhoneNumber", 1080, 1960, "plain"),
                              ("Email", 940, 2000, "plain"), ("Address", 800, 1960, "plain")]:
        p.attr("Organization", label, x, y, kind)

    # ----- Staff and its subtypes (left) -----
    p.entity("Staff", "Staff", 330, 1300)
    p.relation("Issues", "Issues", 620, 1030)
    p.link("Issues", "Staff", "zeroOne")
    p.link("Issues", "Message", "many")
    p.text("<b>XOR</b>: a message has exactly one sender<br>(Issues by Staff or Sends by Patient).",
           690, 1180, 330, 50, size=14)
    p.relation("WorksIn", "WorksIn", 560, 1600)
    p.link("WorksIn", "Staff", "many")
    p.link("WorksIn", "Organization", "oneMany")
    for label, x, y in [("RoleCode", 380, 1560), ("Specialty", 390, 1640), ("StartDate", 640, 1700), ("EndDate", 470, 1700)]:
        p.attr("WorksIn", label, x, y)
    for label, x, y, kind in [("Identifier", 140, 1230, "key"), ("Name", 120, 1290, "plain"),
                              ("Sex", 130, 1350, "plain"), ("Email", 160, 1410, "plain"),
                              ("PhoneNumber", 310, 1440, "plain"), ("Active", 470, 1420, "plain"),
                              ("Role", 520, 1360, "plain"), ("Language", 520, 1250, "multi")]:
        p.attr("Staff", label, x, y, kind)

    p.isa("StaffISA", 330, 800, direction="north")
    p.entity("Doctor", "Doctor", 140, 660, w=150)
    p.entity("Nurse", "Nurse", 330, 660, w=150)
    p.entity("MOA", "MOA", 520, 660, w=150)
    p.isa_link("Staff", "StaffISA", ["Doctor", "Nurse", "MOA"])
    # The attributes fan out above each subtype, so no edge crosses an oval.
    for owner, items in [("Doctor", [("LicenseNumber", -65, 560), ("Qualification", 60, 490)]),
                         ("Nurse", [("LicenseNumber", -65, 560), ("Designation", 60, 490)]),
                         ("MOA", [("Desk", -85, 565), ("PhoneExtension", 70, 495), ("CertificationNumber", -40, 420)])]:
        x0 = {"Doctor": 140, "Nurse": 330, "MOA": 520}[owner]
        for label, dx, y in items:
            p.attr(owner, label, x0 + dx, y)

    # ----- ClinicalEntry subtypes (right column) -----
    p.isa("EntryISA", 2440, 760, direction="east")
    subtypes = [
        ("Diagnosis", ["OnsetDate", "AbatementDate", "ClinicalStatus", "Severity"]),
        ("Procedure", ["PerformedDate", "Outcome"]),
        ("Allergy", ["Substance", "Type", "AllergyCategory", "Criticality"]),
        ("Observation", ["Value", "Unit"]),
        ("LabOrder", ["TestName", "Priority", "Specimen"]),
        ("LabReport", ["IssuedDate", "Conclusion"]),
        ("Prescription", ["Dosage", "Frequency", "Status"]),
    ]
    for i, (name, attrs) in enumerate(subtypes):
        cy = 180 + i * 165
        p.entity(name, name, 2760, cy, w=170)
        offsets = {2: [(3000, -25), (3000, 25)],
                   3: [(2995, -50), (3185, 0), (2995, 50)],
                   4: [(2995, -50), (3185, -22), (2995, 50), (3185, 22)]}[len(attrs)]
        for (x, dy), label in zip(offsets, attrs):
            p.attr(name, label, x, cy + dy)
    p.isa_link("ClinicalEntry", "EntryISA", [name for name, _ in subtypes])
    p.relation("Prescribes", "Prescribes", 2760, 1420)
    p.entity("Medication", "Medication", 2760, 1640)
    p.link("Prescribes", "Prescription", "many")
    p.link("Prescribes", "Medication", "one")
    for label, x, y, kind in [("Code", 2990, 1590, "key"), ("CodeSystem", 3020, 1650, "key"),
                              ("Name", 2990, 1710, "plain"), ("Form", 2620, 1760, "plain"),
                              ("Manufacturer", 2830, 1770, "plain")]:
        p.attr("Medication", label, x, y, kind)

    p.legend(40, 80, extra=["Page 2 shows the agent layer, care teams, the audit log and the lineage store."])
    return p


def page_agent() -> Page:
    p = Page("Agent layer, care teams, audit and lineage", 2900, 1900)
    p.text("<b>TRIAD ER diagram, page 2: agent layer, care teams, audit and lineage</b>", 40, 20, 1400, 30, size=22)

    # Dashed copies of page-1 entities.
    p.entity("Staff", "Staff", 300, 320, copy=True)
    p.entity("Message", "Message", 300, 860, copy=True)
    p.entity("Assertion", "Assertion", 1300, 860, weak=True, grey=True, copy=True)
    p.entity("Patient", "Patient", 1300, 1360, copy=True)
    p.entity("Visit", "Visit", 1900, 1720, copy=True)

    # Chat.
    p.entity("ChatSession", "ChatSession", 800, 320, grey=True)
    p.relation("Opens", "Opens", 550, 320, grey=True)
    p.link("Opens", "Staff", "zeroOne")
    p.link("Opens", "ChatSession", "many")
    p.relation("ChatsAbout", "ChatsAbout", 1600, 640, grey=True)
    p.link("ChatsAbout", "ChatSession", "many", points=[(1600, 320)])
    p.link("ChatsAbout", "Patient", "one", points=[(1600, 1360)])
    for label, x, y, kind in [("Identifier", 680, 180, "key"), ("StartedAt", 830, 160, "plain"),
                              ("UserRole", 980, 190, "plain"), ("Mode", 1010, 250, "plain"),
                              ("Model", 980, 420, "plain")]:
        p.attr("ChatSession", label, x, y, kind, grey=True)

    p.entity("ChatTurn", "ChatTurn", 800, 860, weak=True, grey=True)
    p.relation("Includes", "Includes", 800, 590, identifying=True, grey=True)
    p.link("Includes", "ChatSession", "one")
    p.link("Includes", "ChatTurn", "many")
    for label, x, y, kind in [("Seq", 660, 760, "partial"), ("Speaker", 960, 735, "plain"),
                              ("Text", 990, 990, "plain"), ("CreatedAt", 640, 990, "plain"),
                              ("ClientTurnId", 860, 1010, "plain")]:
        p.attr("ChatTurn", label, x, y, kind, grey=True)

    p.relation("Cites", "Cites", 1050, 860, grey=True)
    p.link("Cites", "ChatTurn", "many")
    p.link("Cites", "Assertion", "many")
    p.attr("Cites", "Rank", 1140, 960, grey=True)
    p.relation("Yields", "Yields", 550, 860, grey=True)
    p.link("Yields", "ChatTurn", "zeroOne")
    p.link("Yields", "Message", "zeroOne")

    # Audit.
    p.entity("AuditEvent", "AuditEvent", 800, 1360)
    p.relation("InTurn", "InTurn", 800, 1150)
    p.link("InTurn", "ChatTurn", "zeroOne")
    p.link("InTurn", "AuditEvent", "many")
    p.relation("AuditedPatient", "Audited\nPatient", 1050, 1360, w=150)
    p.link("AuditedPatient", "AuditEvent", "many")
    p.link("AuditedPatient", "Patient", "one")
    p.relation("DoneByStaff", "DoneBy\nStaff", 450, 1360, w=140)
    p.link("DoneByStaff", "AuditEvent", "many")
    p.link("DoneByStaff", "Staff", "zeroOne", points=[(120, 1360), (120, 334)], entry=(0, 0.75))
    p.relation("DoneByPatient", "DoneBy\nPatient", 1050, 1560, w=150)
    p.link("DoneByPatient", "AuditEvent", "many")
    p.link("DoneByPatient", "Patient", "zeroOne")
    p.text("<b>XOR</b>: exactly one actor<br>(DoneByStaff or DoneByPatient).", 960, 1625, 280, 50, size=14)
    for label, x, y, kind in [("Identifier", 640, 1490, "key"), ("At", 760, 1520, "plain"),
                              ("Action", 880, 1520, "plain"), ("Outcome", 600, 1260, "plain"),
                              ("UserRole", 980, 1270, "plain"), ("Path", 660, 1570, "plain")]:
        p.attr("AuditEvent", label, x, y, kind)

    # Care teams.
    p.entity("CareTeam", "CareTeam", 1300, 1720)
    p.relation("CaresFor", "CaresFor", 1300, 1545)
    p.link("CaresFor", "CareTeam", "many")
    p.link("CaresFor", "Patient", "one")
    p.relation("Covers", "Covers", 1600, 1720)
    p.link("Covers", "CareTeam", "many")
    p.link("Covers", "Visit", "zeroOne")
    p.relation("MemberOf", "MemberOf", 300, 1720)
    p.link("MemberOf", "CareTeam", "many")
    p.link("MemberOf", "Staff", "oneMany", points=[(60, 1720), (60, 309)], entry=(0, 0.3))
    p.attr("MemberOf", "Role", 300, 1830)
    for label, x, y, kind in [("Identifier", 1130, 1820, "key"), ("Name", 1260, 1850, "plain"),
                              ("Status", 1390, 1850, "plain"), ("StartDate", 1520, 1830, "plain"),
                              ("EndDate", 1480, 1630, "plain")]:
        p.attr("CareTeam", label, x, y, kind)

    # Lineage store (physical layer, shown as an inset).
    p.text("<b>Lineage store</b> (physical layer). It keeps every source FHIR resource as it came in,<br>"
           "so TRIAD can link to any FHIR server with almost no data loss.", 1950, 120, 900, 50, size=15)
    p.entity("FhirSource", "FhirSource", 2300, 330)
    p.relation("HoldsResource", "Holds\nResource", 2300, 560, identifying=True, w=150)
    p.entity("FhirResource", "FhirResource", 2300, 790, weak=True)
    p.link("HoldsResource", "FhirSource", "one")
    p.link("HoldsResource", "FhirResource", "many")
    for label, x, y, kind in [("Name", 2120, 250, "key"), ("BaseUrl", 2480, 250, "plain"),
                              ("FhirVersion", 2520, 320, "plain"), ("RetrievedAt", 2500, 390, "plain"),
                              ("Sha256", 2100, 400, "plain")]:
        p.attr("FhirSource", label, x, y, kind)
    for label, x, y, kind in [("ResourceType", 2080, 700, "partial"), ("LogicalId", 2090, 790, "partial"),
                              ("VersionId", 2100, 880, "partial"), ("LastUpdated", 2520, 740, "plain"),
                              ("Json", 2510, 840, "plain")]:
        p.attr("FhirResource", label, x, y, kind)
    p.relation("DerivedFrom", "DerivedFrom", 2300, 1030)
    p.entity("MappedEntity", "Any mapped entity", 2300, 1260, copy=True, w=230)
    p.link("DerivedFrom", "FhirResource", "zeroOne")
    p.link("DerivedFrom", "MappedEntity", "many")
    p.text("Mapped entities: Organization, Location, Staff, Patient, Visit, CareTeam,<br>"
           "ClinicalEntry (and subtypes), Medication, Message and Assertion.", 2040, 1310, 820, 50, size=14)

    p.legend(2080, 1440, extra=["Dashed box: a copy of an entity from page 1."])
    return p


def main() -> None:
    pages = [page_core(), page_agent()]
    xml = '<mxfile host="build_erd.py" type="device">' + "".join(pg.xml(i) for i, pg in enumerate(pages)) + "</mxfile>\n"
    OUT.write_text(xml, encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
