#!/usr/bin/env python3
"""Generate the TRIAD architecture figures as one-page draw.io files.

doc/architecture.drawio: the three layers of the course manual (UI, logic, data) with their Clean Architecture
names, the request path, the onboarding path, the script paths and the Care Assistant. The data layer has two sets
of adapters for the same ports. TRIAD_STORE selects one set:
- sqlite/: the relational database of Milestone 4 (the driver: the Python module sqlite3);
- sparql/: the knowledge graph of Milestone 5. The driver of Virtuoso 7.2 is SPARQLWrapper (the SPARQL 1.1
  Protocol over HTTP). The driver of the embedded store Oxigraph (the tests, and a computer with no Docker) is
  pyoxigraph.
Each box of the data layer names its driver, as the architecture figure of the SEKE 2015 paper does.

doc/kg_build.drawio: the build line of the knowledge graph. The data: FHIR R4 files -> onboarding -> SQLite ->
the R2RML mapping (Morph-KGC) -> the RDF files -> the bulk loader -> Virtuoso (the ABox graph). The ontology:
triad.ttl -> build_ontology.py -> triad.owl (RDF/XML) -> the TBox graph, and the check by hand in Protege.

- A solid arrow is a call, a request or a flow of data. It points from the caller to the part that it calls.
- A dashed arrow with an open head means "implements": an adapter of infrastructure/ implements a port
  of application/. Thus all code dependencies point to the logic layer (the dependency rule).
  The ports bar also tells that only main.py (the composition root) connects the adapters to the ports.
- Grey shows the TRIAD contribution, as in the ER diagram: the authorship and revision model (domain rules),
  the access and audit layer, and the agent layer (Care Assistant, language model).
- A dashed box is a file, a tool or a service outside the code. A cylinder is a data store.

The figures go in the report at column width (about 8.5 cm). Thus they have few boxes and large text:
each drawing is about 650 units wide, so the text size 24 is about 9 pt in print.

Make the figures again after a change (from the root folder of the repository):
    python3 src/scripts/build_architecture.py
    drawio -x -f png --scale 2 --crop -o doc/architecture.png doc/architecture.drawio
    drawio -x -f pdf --crop -o doc/architecture.pdf doc/architecture.drawio
    drawio -x -f png --scale 2 --crop -o doc/kg_build.png doc/kg_build.drawio
    drawio -x -f pdf --crop -o doc/kg_build.pdf doc/kg_build.drawio
"""
from __future__ import annotations

import html
from pathlib import Path

DOC = Path(__file__).resolve().parents[2] / "doc"
OUT = DOC / "architecture.drawio"
OUT_KG = DOC / "kg_build.drawio"

GREY = "#E6E6E6"           # the same grey as the ER diagram
WHITE = "#FFFFFF"
FONT = 24                  # about 9 pt at column width
LINE_HEIGHT = 1.1          # the text lines of a box
LINE = FONT * LINE_HEIGHT  # the height of one text line
BASE = (f"html=1;whiteSpace=wrap;strokeColor=#000000;fontColor=#000000;fontSize={FONT};"
        "fontFamily=Helvetica;spacing=3;")

# The grid of the UI and logic bands: three columns.
LEFT, RIGHT = 0, 652
COLS = {1: (10, 220), 2: (240, 172), 3: (422, 220)}   # column -> (x, width)
# The grid of the data band: four columns (x, width). Column 3 is the Virtuoso lane, column 4 the Oxigraph lane.
DATA = {1: (10, 120), 2: (140, 136), 3: (286, 220), 4: (516, 126)}
PAD = 18                   # from a band line to the boxes
GAP = 22                   # between two bands
GAP_PORTS = 32             # between logic and data: room for the label "implements"
ARROW = 26                 # the space for a short arrow between two boxes
CYLINDER = 22              # the extra height of a cylinder: its caps need room


def span(first: int, last: int | None = None, grid: dict = COLS) -> tuple[float, float]:
    """The x and the width of a box that spans the columns first to last."""
    last = last or first
    x0 = grid[first][0]
    return x0, grid[last][0] + grid[last][1] - x0


def middle(column: int, grid: dict = COLS) -> float:
    x, w = span(column, grid=grid)
    return x + w / 2


def lines(*parts: str) -> str:
    return f'<div style="line-height:{LINE_HEIGHT}">' + "<br>".join(parts) + "</div>"


def tall(n: int) -> int:
    """The height of a box with n text lines."""
    return round(n * LINE + 12)


class Figure:
    def __init__(self) -> None:
        self.cells: list[str] = []
        self.geo: dict[str, tuple[float, float, float, float]] = {}
        self.ids: dict[str, str] = {}
        self.seq = 0

    def _id(self) -> str:
        self.seq += 1
        return f"a{self.seq}"

    def _vertex(self, value: str, style: str, x: float, y: float, w: float, h: float, key: str | None = None) -> str:
        cid = self._id()
        if key:
            self.ids[key] = cid
            self.geo[key] = (x, y, w, h)
        self.cells.append(
            f'<mxCell id="{cid}" value="{html.escape(value, quote=True)}" style="{style}" vertex="1" parent="1">'
            f'<mxGeometry x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" as="geometry"/></mxCell>'
        )
        return cid

    def band(self, title: str, y: float, h: float, label_at_bottom: bool = False) -> None:
        """A layer band: a frame with its name on the top line (or on the bottom line)."""
        self._vertex("", "rounded=1;arcSize=2;fillColor=none;strokeColor=#000000;strokeWidth=1.5;html=1;",
                     LEFT, y, RIGHT - LEFT, h)
        y_label = y + h if label_at_bottom else y
        self._vertex(title, f"text;html=1;align=left;verticalAlign=middle;fontSize={FONT};fontFamily=Helvetica;"
                     "fontColor=#000000;labelBackgroundColor=#FFFFFF;spacingLeft=0;",
                     14, y_label - 16, RIGHT - 28, 32)

    def box(self, key: str, value: str, x: float, y: float, w: float, h: float, grey: bool = False,
            dashed: bool = False, shape: str = "rect") -> None:
        style = BASE + f"fillColor={GREY if grey else WHITE};"
        if shape == "cylinder":
            style = "shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=8;" + style
        elif shape == "bar":        # a port bar or a driver: square corners, italic text
            style = "rounded=0;fontStyle=2;" + style
        else:
            style = "rounded=1;arcSize=6;" + style
        if dashed:
            style += "dashed=1;dashPattern=5 4;"
        self._vertex(value, style, x, y, w, h, key)

    def at(self, key: str, value: str, column: int, y: float, h: float, grid: dict = COLS, **kw) -> None:
        """A box in one column of a grid."""
        x, w = span(column, grid=grid)
        self.box(key, value, x, y, w, h, **kw)

    def text(self, value: str, x: float, y: float, w: float, h: float, align: str = "left") -> None:
        self._vertex(value, f"text;html=1;align={align};verticalAlign=middle;fontSize={FONT};"
                     "fontFamily=Helvetica;fontColor=#000000;whiteSpace=wrap;spacing=0;", x, y, w, h)

    def _rel(self, key: str, x_abs: float) -> float:
        x, _, w, _ = self.geo[key]
        return round((x_abs - x) / w, 4)

    def arrow(self, source: str, target: str, x_abs: float | None = None, implements: bool = False,
              side: tuple[tuple[float, float], tuple[float, float]] | None = None) -> None:
        """A vertical arrow at x_abs from the bottom of source to the top of target (upward for "implements"),
        or an arrow between the given relative points of the two boxes (side)."""
        if side:
            (ex, ey), (nx, ny) = side
        elif implements:      # from the top of the adapter up to the bottom of the ports bar
            ex, ey, nx, ny = self._rel(source, x_abs), 0, self._rel(target, x_abs), 1
        else:
            ex, ey, nx, ny = self._rel(source, x_abs), 1, self._rel(target, x_abs), 0
        style = ("startArrow=none;html=1;strokeColor=#000000;strokeWidth=1.5;endSize=10;"
                 f"exitX={ex};exitY={ey};exitDx=0;exitDy=0;entryX={nx};entryY={ny};entryDx=0;entryDy=0;")
        style += "endArrow=block;endFill=0;dashed=1;dashPattern=5 4;" if implements else "endArrow=block;endFill=1;"
        self.cells.append(
            f'<mxCell id="{self._id()}" value="" style="{style}" edge="1" parent="1" '
            f'source="{self.ids[source]}" target="{self.ids[target]}"><mxGeometry relative="1" as="geometry"/></mxCell>'
        )

    def legend(self, y: float, items: list[tuple[str, dict, int]]) -> float:
        """One legend row: a small box and its text for each item (text, box options, text width)."""
        x = 10
        for i, (label, options, width) in enumerate(items):
            self.box(f"legend_{i}", "", x, y + 4, 34, 24, **options)
            self.text(label, x + 42, y, width, 32)
            x += 42 + width + 8
        return y + 32

    def xml(self, name: str, diagram_id: str, width: int, height: int) -> str:
        return (
            '<mxfile host="build_architecture.py" type="device">'
            f'<diagram name="{name}" id="{diagram_id}">'
            f'<mxGraphModel dx="1200" dy="900" grid="1" gridSize="10" guides="1" page="1" '
            f'pageWidth="{width}" pageHeight="{height}" background="#FFFFFF">'
            f'<root><mxCell id="0"/><mxCell id="1" parent="0"/>{"".join(self.cells)}</root>'
            "</mxGraphModel></diagram></mxfile>\n"
        )


def build() -> tuple[Figure, float]:
    """The architecture figure: the three layers, with the relational and the semantic data layer."""
    f = Figure()

    # ----- UI: the React frontend and the api/ layer -----
    y = 16
    h = tall(3)
    f.band("<b>UI</b> · presentation: React frontend, api/", y, PAD + h + PAD - 6)
    f.at("browser", lines("<b>Browser</b>", "React 19, TS, Vite", "TanStack Query"), 1, y + PAD, h)
    f.at("routers", lines("<b>FastAPI</b> routers", "(api/), get_actor:", "acting-as user"), 3, y + PAD, h)
    f.arrow("browser", "routers", side=((1, 0.5), (0, 0.5)))
    x, w = span(2)
    f.text("HTTP JSON /api", x - 8, y + PAD + h / 2 - 32, w + 16, 28, align="center")
    f.text("X-Triad-User", x - 8, y + PAD + h / 2 + 4, w + 16, 28, align="center")
    y += PAD + h + PAD - 6

    # ----- logic: application/ (use cases, ports) and domain/ (entities, rules) -----
    y += GAP
    top = y + PAD
    h_domain, h_onboard = tall(3), tall(2)
    h_access, h_case = tall(2), tall(3)
    floor = top + max(h_domain + ARROW + h_onboard, h_access + ARROW + h_case)   # the top of the ports bar
    h_bar = tall(2)
    f.band("<b>logic</b> (biz) · application/, domain/", y, floor + h_bar + 10 - y)
    f.at("domain", lines("<b>domain/</b> rules:", "supersede, current", "state, patient-visible"), 1, top, h_domain,
         grey=True)
    x_access = span(1)[0] + span(1)[1] + 32          # room for the arrow to domain/
    f.box("access", lines("<b>Access check</b>: care-team rule", "denied → AuditEvent (audit log)"),
          x_access, top, RIGHT - 10 - x_access, h_access, grey=True)
    f.at("onboard", lines("<b>Onboarding</b>", "use case (CLI)"), 1, floor - h_onboard, h_onboard)
    f.at("usecases", lines("<b>Use cases</b>", "patients, visits,", "records, audit"), 2, floor - h_case, h_case)
    f.at("agent", lines("<b>Care Assistant</b>", "agent loop → tools", "refs E1, E2; no ids"), 3, floor - h_case,
         h_case, grey=True)
    x, w = span(1, 3)
    f.box("ports", lines("ports (Python Protocols); main.py connects the adapters",
                         "TRIAD_STORE: the sqlite/ or the sparql/ adapters"), x, floor, w, h_bar, shape="bar")
    f.arrow("routers", "access", middle(3))
    f.arrow("access", "domain", side=((0, 0.5), (1, round(h_access / 2 / h_domain, 4))))
    f.arrow("access", "usecases", middle(2))
    f.arrow("access", "agent", middle(3))
    y = floor + h_bar + 10

    # ----- data: infrastructure/ (the adapters and their drivers), SQLite 3, Virtuoso 7.2, Oxigraph -----
    y += GAP_PORTS
    h3 = tall(3)
    h_store = h3 + CYLINDER
    # Row A: the FHIR reader, and the language model with its provider. The sqlite/ and sparql/ adapters are in
    # row B; their "implements" arrows go up through the free space of row A (x_sqlite and x_sparql).
    row_a = y + PAD
    x_sqlite = middle(2, DATA)
    x_sparql = DATA[3][0] + 44
    x_llm, w_llm = 372, 120
    x_provider = x_llm + w_llm + ARROW
    f.at("fhir", lines("<b>FHIR</b>", "reader +", "mappers"), 1, row_a, h3, grid=DATA)
    f.box("llm", lines("<b>LLM</b>", "fake, or", "LiteLLM"), x_llm, row_a, w_llm, h3, grey=True)
    f.box("provider", lines("<b>Provider</b>", "(Gemini)"), x_provider, row_a, RIGHT - 10 - x_provider, h3,
          dashed=True)
    # Row B: the FHIR files, and the two sets of repositories (the same ports).
    row_b = row_a + h3 + ARROW
    f.at("files", lines("<b>FHIR R4</b>", "files", "(Synthea)"), 1, row_b, h3, grid=DATA, dashed=True)
    f.at("repos", lines("<b>sqlite/</b>", "repositories", "raw sqlite3"), 2, row_b, h3, grid=DATA)
    x, w = span(3, 4, DATA)
    f.box("sparql", lines("<b>sparql/</b> repositories", "write buffer, guards,", "one INSERT DATA"),
          x, row_b, w, h3)
    # Row C: the SQL scripts and SQLite; the two drivers of the knowledge graph.
    row_c = row_b + h3 + ARROW
    f.box("sql", lines("<b>SQL</b>", "scripts", "01–05"), DATA[1][0], row_c, 100, h3, dashed=True)
    f.at("db", lines("<b>SQLite 3</b>", "29 relations", "11 triggers"), 2, row_c, h_store, grid=DATA,
         shape="cylinder")
    f.at("wrapper", lines("SPARQLWrapper", "SPARQL 1.1", "Protocol (HTTP)"), 3, row_c, h3, grid=DATA, shape="bar")
    f.at("pyoxigraph", lines("pyoxigraph", "embedded"), 4, row_c, h3, grid=DATA, shape="bar")
    # Row D: the SPARQL scripts and the two triple stores.
    row_d = row_c + h_store + 20
    f.box("sparql_scripts", lines("<b>SPARQL scripts</b>", "01–06: kg.sh,", "Conductor"), DATA[1][0], row_d,
          240, h3, dashed=True)
    f.at("virtuoso", lines("<b>Virtuoso 7.2</b>", "in Docker", "TBox, ABox graphs"), 3, row_d, h_store, grid=DATA,
         shape="cylinder")
    f.at("oxigraph", lines("<b>Oxigraph</b>", "tests,", "no Docker"), 4, row_d, h_store, grid=DATA,
         shape="cylinder")
    bottom = row_d + h_store + PAD + 2
    f.band("<b>data</b> (dal) · infrastructure/, SQLite 3, Virtuoso 7.2", y, bottom - y, label_at_bottom=True)

    for adapter, x_abs in (("fhir", middle(1, DATA)), ("repos", x_sqlite), ("sparql", x_sparql),
                           ("llm", x_llm + w_llm / 2)):
        f.arrow(adapter, "ports", x_abs, implements=True)
    f.text("<i>implements</i>", x_llm + w_llm / 2 + 14, y - GAP_PORTS, 180, GAP_PORTS)
    f.arrow("fhir", "files", middle(1, DATA))
    f.arrow("llm", "provider", side=((1, 0.5), (0, 0.5)))
    f.arrow("repos", "db", x_sqlite)
    f.arrow("sparql", "wrapper", middle(3, DATA))
    f.arrow("sparql", "pyoxigraph", middle(4, DATA))
    f.arrow("wrapper", "virtuoso", middle(3, DATA))
    f.arrow("pyoxigraph", "oxigraph", middle(4, DATA))
    f.arrow("sql", "db", side=((1, 0.5), (0, round(h3 / 2 / h_store, 4))))
    f.arrow("sparql_scripts", "virtuoso", side=((1, 0.5), (0, round(h3 / 2 / h_store, 4))))
    y = bottom + 20

    # ----- legend: one row -----
    end = f.legend(y, [("TRIAD contribution", {"grey": True}, 230),
                       ("file, tool or service", {"dashed": True}, 250)])
    return f, end


# The grid of the build figure: three lanes (x, width). Lane 1: the data (ABox). Lane 2: the mapping and the
# check by hand. Lane 3: the ontology (TBox). The gaps between the lanes hold the side arrows.
LANES = {1: (10, 208), 2: (242, 170), 3: (436, 206)}
STEP_GAP = 30                # the space for the arrow between two rows


def build_kg() -> tuple[Figure, float]:
    """The build line of the knowledge graph: from the FHIR files and triad.ttl to the two graphs of the store."""
    f = Figure()
    h2, h3 = tall(2), tall(3)

    y = 10
    f.at("fhir_files", lines("<b>FHIR R4 files</b>", "Synthea,", "TRIAD bundle"), 1, y, h3, grid=LANES, dashed=True)
    f.at("ttl", lines("<b>triad.ttl</b>", "Turtle source,", "by hand"), 3, y, h3, grid=LANES, dashed=True)

    y += h3 + STEP_GAP
    f.at("onboarding", lines("<b>Onboarding</b>", "main.py ensure-db"), 1, y, h2, grid=LANES)
    f.at("build_owl", lines("<b>Build, checks</b>", "build_ontology.py"), 3, y, h2, grid=LANES)

    y += h2 + STEP_GAP
    f.at("sqlite", lines("<b>SQLite 3</b>", "188,312 rows"), 1, y, h2 + CYLINDER, grid=LANES, shape="cylinder")
    f.at("protege", lines("<b>Protégé 5.6</b>", "HermiT check", "(by hand)"), 2, y, h3, grid=LANES, dashed=True)
    f.at("owl", lines("<b>triad.owl</b>", "RDF/XML,", "1,956 triples"), 3, y, h3, grid=LANES, dashed=True)

    y += h3 + STEP_GAP
    f.at("r2rml", lines("<b>R2RML</b> mapping", "Morph-KGC 2.10", "main.py export-kg"), 1, y, h3, grid=LANES)
    f.at("mapping", lines("<b>triad.r2rml.ttl</b>", "W3C R2RML,", "35 TriplesMaps"), 2, y, h3, grid=LANES,
         dashed=True)

    y += h3 + STEP_GAP
    f.at("rdf", lines("<b>RDF files</b>", ".nt.gz, .rdf.gz", "1,298,482 triples"), 1, y, h3, grid=LANES,
         dashed=True)

    y += h3 + STEP_GAP
    x, w = span(1, 3, LANES)
    f.box("load", lines("<b>main.py ensure-kg</b>: load, count check, marker",
                        "bulk loader (kg.sh load), or pyoxigraph"), x, y, w, h2)

    y += h2 + STEP_GAP
    h_store = h3 + CYLINDER
    x, w = span(1, 2, LANES)
    f.box("virtuoso", lines("<b>Virtuoso 7.2</b>", "graph/tbox ← triad.owl", "graph/abox ← RDF files"),
          x, y, w, h_store, shape="cylinder")
    f.at("oxigraph", lines("<b>Oxigraph</b>", "embedded,", "same graphs"), 3, y, h_store, grid=LANES,
         shape="cylinder")

    f.arrow("fhir_files", "onboarding", middle(1, LANES))
    f.arrow("onboarding", "sqlite", middle(1, LANES))
    f.arrow("sqlite", "r2rml", middle(1, LANES))
    f.arrow("r2rml", "rdf", middle(1, LANES))
    f.arrow("rdf", "load", middle(1, LANES))
    f.arrow("mapping", "r2rml", side=((0, 0.5), (1, 0.5)))
    f.arrow("ttl", "build_owl", middle(3, LANES))
    f.arrow("build_owl", "owl", middle(3, LANES))
    f.arrow("owl", "protege", side=((0, 0.5), (1, 0.5)))
    f.arrow("owl", "load", middle(3, LANES))
    f.arrow("load", "virtuoso", middle(1, LANES))
    f.arrow("load", "oxigraph", middle(3, LANES))

    y += h_store + 20
    end = f.legend(y, [("step (a command)", {}, 200), ("file or tool", {"dashed": True}, 150)])
    return f, end


def main() -> None:
    for out, make, name, diagram_id in ((OUT, build, "TRIAD architecture", "architecture"),
                                        (OUT_KG, build_kg, "TRIAD knowledge-graph build", "kg-build")):
        fig, height = make()
        out.write_text(fig.xml(name, diagram_id, RIGHT, int(height) + 10), encoding="utf-8")
        print(f"Wrote {out} ({RIGHT} x {height:.0f} units).")


if __name__ == "__main__":
    main()
