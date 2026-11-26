#!/usr/bin/env python3
"""Draw the TRIAD ontology figure (TRIAD_ontology.drawio) from triad.ttl.

Each class is at the position of its entity set (or relationship) in the ER diagram (../er/build_erd.py).
The object properties are labeled arrows from the domain to the range. The subclass links are blue and
have a hollow head, apart from the other links. The association classes and the value classes are boxes
with their own colours. A legend names the derived properties and the reused vocabularies (PROV-O, FHIR R4).

Make the figure again after a change of triad.ttl (from the root folder of the repository):
    .venv/bin/python src/backend/models/semantic/build_figure.py
    cd src/backend/models/semantic
    drawio -x -f pdf --crop -o TRIAD_ontology.pdf TRIAD_ontology.drawio
    drawio -x -p 1 -f png -s 2 -o TRIAD_ontology.png TRIAD_ontology.drawio
"""
from __future__ import annotations

import html
import re

try:
    from models.semantic import build_ontology as bo
except ImportError:  # run as a script: this folder is on sys.path
    import build_ontology as bo

OUT = bo.HERE / "TRIAD_ontology.drawio"
WIDTH, HEIGHT = 3300, 2080
BLUE = "#1F5FA8"
FILL = {"class": "#FFFFFF", "association": "#FFF2CC", "value": "#E2F0D9"}

# The class -> the key of its shape in build_erd.page_core(). Three association classes take the place
# of their relationship diamonds. CareTeamMember takes the place of the attribute CareTeam.Member.
ERD_KEY = {"WorksIn": "WorksIn", "VisitLocation": "TakesPlaceIn", "Citation": "Cites",
           "CareTeamMember": "CareTeamMember"}
# PatientIdentifier has no key in the ER script (the attribute Patient.Identifier); it goes below Patient.
FIXED = {"PatientIdentifier": (1380, 1660)}
ISA_POINTS = {"Staff": (330, 690), "ClinicalEntry": (2420, 900)}   # the ISA triangles of the ER diagram


def erd_positions() -> dict[str, tuple[float, float]]:
    """The centre of each shape of the ER diagram, by its key in build_erd.py."""
    erd = bo._load_module("build_erd", bo.BUILD_ERD_PATH)
    page = erd.page_core()
    cells = {re.search(r'id="(c\d+)"', c).group(1): c for c in page.cells}
    result = {}
    for key, cid in page.ids.items():
        x, y, w, h = (float(v) for v in re.search(
            r'x="([\d.-]+)" y="([\d.-]+)" width="([\d.]+)" height="([\d.]+)"', cells[cid]).groups())
        result[key] = (x + w / 2, y + h / 2)
    return result


class Figure:
    def __init__(self) -> None:
        self.cells: list[str] = []
        self.seq = 0
        self.ids: dict[str, str] = {}
        self.boxes: dict[str, tuple[float, float, float, float]] = {}

    def _id(self) -> str:
        self.seq += 1
        return f"o{self.seq}"

    def vertex(self, value: str, style: str, x: float, y: float, w: float, h: float, key: str | None = None) -> str:
        cid = self._id()
        if key:
            self.ids[key] = cid
            self.boxes[key] = (x, y, w, h)
        self.cells.append(
            f'<mxCell id="{cid}" value="{html.escape(value, quote=True)}" style="{style}" vertex="1" parent="1">'
            f'<mxGeometry x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" as="geometry"/></mxCell>')
        return cid

    def edge(self, source: str, target: str, style: str, label: str = "",
             points: list[tuple[float, float]] | None = None) -> None:
        cid = self._id()
        array = ""
        if points:
            array = '<Array as="points">' + "".join(f'<mxPoint x="{x:.0f}" y="{y:.0f}"/>' for x, y in points) + "</Array>"
        self.cells.append(
            f'<mxCell id="{cid}" value="{html.escape(label, quote=True)}" style="{style}html=1;fontSize=14;'
            f'labelBackgroundColor=#FFFFFF;" edge="1" parent="1" source="{self.ids[source]}" '
            f'target="{self.ids[target]}"><mxGeometry relative="1" as="geometry">{array}</mxGeometry></mxCell>')

    def text(self, value: str, x: float, y: float, w: float, h: float, size: int = 15, border: bool = False) -> None:
        style = f"text;html=1;align=left;verticalAlign=top;fontSize={size};fontColor=#000000;"
        if border:
            style += "strokeColor=#000000;fillColor=#FFFFFF;spacing=8;"
        self.vertex(value, style, x, y, w, h)

    def xml(self) -> str:
        return (f'<mxfile host="build_figure.py" type="device"><diagram name="TRIAD ontology" id="ontology">'
                f'<mxGraphModel dx="1600" dy="1000" grid="1" gridSize="10" guides="1" page="1" '
                f'pageWidth="{WIDTH}" pageHeight="{HEIGHT}" background="#FFFFFF"><root><mxCell id="0"/>'
                f'<mxCell id="1" parent="0"/>{"".join(self.cells)}</root></mxGraphModel></diagram></mxfile>\n')


def class_kind(name: str) -> str:
    if name in ("WorksIn", "VisitLocation", "Citation"):
        return "association"
    if name in ("PatientIdentifier", "CareTeamMember"):
        return "value"
    return "class"


def class_note(g, cls) -> list[str]:
    """The short lines under the name: the PROV-O superclass and the FHIR matches."""
    parts = [f"⊑ {bo.local(p)}" for p in sorted(g.objects(cls, bo.RDFS.subClassOf)) if str(p).startswith(str(bo.PROV))]
    parts += [f"≈ fhir:{str(m).rsplit('/', 1)[1]}" for m in sorted(g.objects(cls, bo.SKOS.closeMatch))]
    parts += [f"~ fhir:{str(m).rsplit('/', 1)[1]}" for m in sorted(g.objects(cls, bo.SKOS.relatedMatch))]
    return parts


def characteristics(g, prop) -> str:
    names = {bo.OWL.FunctionalProperty: "F", bo.OWL.InverseFunctionalProperty: "IF",
             bo.OWL.AsymmetricProperty: "Asym", bo.OWL.IrreflexiveProperty: "Irr"}
    found = [names[t] for t in names if (prop, bo.RDF.type, t) in g]
    return f" ({', '.join(found)})" if found else ""


def build() -> Figure:
    g = bo.load_graph()
    pos = erd_positions()
    fig = Figure()
    fig.text("<b>TRIAD ontology (Milestone 5): the classes and the object properties</b>", 40, 20, 1600, 30, size=22)

    # ----- Classes -----
    for cls in sorted(bo.classes(g), key=str):
        name = bo.local(cls)
        cx, cy = FIXED.get(name) or pos[ERD_KEY.get(name, name)]
        note = class_note(g, cls)
        w = max(170, max((8.0 * len(line) + 24 for line in note), default=0), 11.5 * len(name) + 30)
        h = 44 + 16 * len(note)
        label = f"<b>{html.escape(name)}</b>"
        if note:
            label += ('<br><span style="font-size:12px;color:#444444;">'
                      + "<br>".join(html.escape(line) for line in note) + "</span>")
        style = (f"rounded=1;arcSize=12;html=1;whiteSpace=wrap;fontSize=17;strokeColor=#000000;fontColor=#000000;"
                 f"fillColor={FILL[class_kind(name)]};")
        fig.vertex(label, style, cx - w / 2, cy - h / 2, w, h, key=name)

    # ----- Subclass links: subtype -> a junction (the ISA triangle of the ER diagram) -> parent -----
    for parent, (jx, jy) in ISA_POINTS.items():
        direction = "north" if parent == "Staff" else "east"
        junction = f"isa-{parent}"
        fig.vertex("", f"triangle;direction={direction};html=1;strokeColor={BLUE};fillColor=#FFFFFF;",
                   jx - 22, jy - 22, 44, 44, key=junction)
        nx, ny = (jx + 30, jy - 12) if parent == "Staff" else (jx - 90, jy + 30)
        fig.text(f'<span style="color:{BLUE};">disjointUnionOf</span>', nx, ny, 170, 26, size=14)
        fig.edge(junction, parent, f"endArrow=block;endFill=0;endSize=16;strokeColor={BLUE};strokeWidth=2;")
        for child in sorted(g.subjects(bo.RDFS.subClassOf, bo.TRIAD[parent]), key=str):
            if child in bo.classes(g):
                fig.edge(bo.local(child), junction, f"endArrow=none;strokeColor={BLUE};strokeWidth=2;")

    # ----- Object properties: domain -> range -----
    inverse_of = {stored: named for named, stored in bo.named_inverses(g).items()}
    for prop in sorted(bo.stored_properties(g), key=str):
        name = bo.local(prop)
        dom, rng = bo.local(g.value(prop, bo.RDFS.domain)), bo.local(g.value(prop, bo.RDFS.range))
        label = name + characteristics(g, prop)
        if prop in inverse_of:
            label += f"\n/ {bo.local(inverse_of[prop])}"
        style = "endArrow=block;endFill=1;endSize=10;strokeColor=#000000;strokeWidth=1.5;fontStyle=2;"
        if dom == rng:  # supersedes: a loop below the box
            x, y, w, h = fig.boxes[dom]
            style += ("edgeStyle=orthogonalEdgeStyle;exitX=0.25;exitY=1;exitDx=0;exitDy=0;"
                      "entryX=0.75;entryY=1;entryDx=0;entryDy=0;")
            fig.edge(dom, rng, style, label, points=[(x + w * 0.25, y + h + 70), (x + w * 0.75, y + h + 70)])
        else:
            fig.edge(dom, rng, style, label)

    # ----- Legend -----
    lines = [
        "<b>Legend</b>",
        "Box: class (owl:Class). Yellow box: association class (an M:N relationship with attributes).",
        "Green box: value class (one value of a multivalued composite attribute).",
        "Black arrow: a stored object property, from its domain to its range.",
        "(F) Functional, (IF) InverseFunctional, (Asym) Asymmetric, (Irr) Irreflexive.",
        "&quot;/ name&quot;: the named inverse (no triples in the store; the keys and the chains use it).",
        f'<span style="color:{BLUE};">Blue line with a hollow head: rdfs:subClassOf. '
        "The triangle: owl:disjointUnionOf (disjoint, total).</span>",
        "The 16 stored properties (without supersedes) and the 11 subclass links make a tree.",
        "<b>Derived properties</b> (OWL 2 property chains; a reasoner infers them):",
        "assertedBy = inMessage ∘ issuedBy (Assertion → Staff, ⊑ prov:wasAttributedTo);",
        "ofPatient = about ∘ during ∘ visitOf (Assertion → Patient);",
        "supersedesTransitively: transitive, supersedes ⊑ it.",
        "<b>Reused vocabularies</b> (declared locally, no owl:imports):",
        "PROV-O: Message, Assertion ⊑ prov:Entity; Staff ⊑ prov:Person;",
        "supersedes ⊑ prov:wasRevisionOf; issuedBy, assertedBy ⊑ prov:wasAttributedTo.",
        "FHIR R4: ≈ skos:closeMatch, ~ skos:relatedMatch (namespace http://hl7.org/fhir/).",
        "The datatype properties, keys and restrictions are in ontology.md (sections 4 to 6).",
    ]
    fig.text("<br>".join(lines), 560, 1560, 690, 17 * len(lines) + 20, size=14, border=True)
    return fig


def main() -> None:
    fig = build()
    OUT.write_text(fig.xml(), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
