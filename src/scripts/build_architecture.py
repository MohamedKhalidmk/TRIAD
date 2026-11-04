#!/usr/bin/env python3
"""Generate the TRIAD architecture figure as a one-page draw.io file (doc/architecture.drawio).

The figure shows the three layers of the course manual (UI, logic, data) with their Clean Architecture
names, the request path, the onboarding path, the SQL scripts path and the Care Assistant.

- A solid arrow is a call or a request. It points from the caller to the part that it calls.
- A dashed arrow with an open head means "implements": an adapter of infrastructure/ implements a port
  of application/. Thus all code dependencies point to the logic layer (the dependency rule).
  The ports bar also tells that only main.py (the composition root) connects the adapters to the ports.
- Grey shows the TRIAD contribution, as in the ER diagram: the authorship and revision model (domain rules),
  the access and audit layer, and the agent layer (Care Assistant, language model).
- A dashed box is a file or a service outside the code.

The figure goes in the report at column width (about 8.5 cm). Thus it has few boxes and large text:
the drawing is about 650 units wide, so the text size 24 is about 9 pt in print.

Make the figure again after a change (from the root folder of the repository):
    python3 src/scripts/build_architecture.py
    drawio -x -f png --scale 2 --crop -o doc/architecture.png doc/architecture.drawio
    drawio -x -f pdf --crop -o doc/architecture.pdf doc/architecture.drawio
"""
from __future__ import annotations

import html
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "doc" / "architecture.drawio"

GREY = "#E6E6E6"           # the same grey as the ER diagram
WHITE = "#FFFFFF"
FONT = 24                  # about 9 pt at column width
LINE_HEIGHT = 1.1          # the text lines of a box
LINE = FONT * LINE_HEIGHT  # the height of one text line
BASE = (f"html=1;whiteSpace=wrap;strokeColor=#000000;fontColor=#000000;fontSize={FONT};"
        "fontFamily=Helvetica;spacing=3;")

# The grid: three columns in each layer band.
LEFT, RIGHT = 0, 652
COLS = {1: (10, 220), 2: (240, 172), 3: (422, 220)}   # column -> (x, width)
# The lowest row of the data band has its own grid of four boxes: a file, the database, a file, a service.
LOW = {"files": (10, 166), "db": (186, 136), "sql": (346, 148), "provider": (504, 138)}
PAD = 18                   # from a band line to the boxes
GAP = 22                   # between two bands
GAP_PORTS = 32             # between logic and data: room for the label "implements"
ARROW = 26                 # the space for a short arrow between two boxes


def span(first: int, last: int | None = None) -> tuple[float, float]:
    """The x and the width of a box that spans the columns first to last."""
    last = last or first
    x0 = COLS[first][0]
    return x0, COLS[last][0] + COLS[last][1] - x0


def middle(column: int) -> float:
    x, w = span(column)
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
        elif shape == "bar":
            style = "rounded=0;fontStyle=2;" + style
        else:
            style = "rounded=1;arcSize=6;" + style
        if dashed:
            style += "dashed=1;dashPattern=5 4;"
        self._vertex(value, style, x, y, w, h, key)

    def at(self, key: str, value: str, column: int, y: float, h: float, **kw) -> None:
        """A box in one column of the grid."""
        x, w = span(column)
        self.box(key, value, x, y, w, h, **kw)

    def low(self, key: str, value: str, y: float, h: float, **kw) -> None:
        """A box in the lowest row of the data band."""
        x, w = LOW[key]
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

    def xml(self, width: int, height: int) -> str:
        return (
            '<mxfile host="build_architecture.py" type="device">'
            '<diagram name="TRIAD architecture" id="architecture">'
            f'<mxGraphModel dx="1200" dy="900" grid="1" gridSize="10" guides="1" page="1" '
            f'pageWidth="{width}" pageHeight="{height}" background="#FFFFFF">'
            f'<root><mxCell id="0"/><mxCell id="1" parent="0"/>{"".join(self.cells)}</root>'
            "</mxGraphModel></diagram></mxfile>\n"
        )


def build() -> tuple[Figure, float]:
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
    h_bar = 34
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
    f.box("ports", "ports (Python Protocols); main.py connects the adapters", x, floor, w, h_bar, shape="bar")
    f.arrow("routers", "access", middle(3))
    f.arrow("access", "domain", side=((0, 0.5), (1, round(h_access / 2 / h_domain, 4))))
    f.arrow("access", "usecases", middle(2))
    f.arrow("access", "agent", middle(3))
    y = floor + h_bar + 10

    # ----- data: infrastructure/ (adapters) and SQLite 3 -----
    y += GAP_PORTS
    f.text("<i>implements</i>", middle(1) + 14, y - GAP_PORTS, 200, GAP_PORTS)
    top = y + PAD
    h_adapter = tall(3)
    f.at("fhir", lines("<b>FHIR reader</b>", "+ mappers", "(anti-corruption)"), 1, top, h_adapter)
    f.at("repos", lines("<b>Repositories</b>", "raw sqlite3", "LIMIT/OFFSET"), 2, top, h_adapter)
    f.at("llm", lines("<b>Language model</b>", "fake (default)", "or LiteLLM"), 3, top, h_adapter, grey=True)
    low = top + h_adapter + ARROW
    h_low = tall(3)
    h_db = h_low + 22                                # the caps of the cylinder need room
    f.low("files", lines("<b>FHIR R4 files</b>", "Synthea,", "TRIAD bundle"), low, h_low, dashed=True)
    f.low("db", lines("<b>SQLite 3</b>", "29 relations", "11 triggers"), low, h_db, shape="cylinder")
    f.low("sql", lines("<b>SQL scripts</b>", "01–05 via", "sqlite3 CLI"), low, h_low, dashed=True)
    f.low("provider", lines("<b>Provider</b>", "for example", "Gemini"), low, h_low, dashed=True)
    bottom = low + h_db + PAD + 2
    f.band("<b>data</b> (dal) · infrastructure/, SQLite 3", y, bottom - y, label_at_bottom=True)

    for adapter, column in (("fhir", 1), ("repos", 2), ("llm", 3)):
        f.arrow(adapter, "ports", middle(column), implements=True)
    f.arrow("fhir", "files", LOW["files"][0] + LOW["files"][1] / 2)
    f.arrow("repos", "db", (COLS[2][0] + LOW["db"][0] + LOW["db"][1]) / 2)     # where the two boxes overlap
    f.arrow("llm", "provider", LOW["provider"][0] + LOW["provider"][1] / 2)
    f.arrow("sql", "db", side=((0, 0.5), (1, 0.5)))
    y = bottom + 20

    # ----- legend: one row -----
    f.box("legend_grey", "", 10, y + 4, 34, 24, grey=True)
    f.text("TRIAD contribution", 52, y, 230, 32)
    f.box("legend_dashed", "", 290, y + 4, 34, 24, dashed=True)
    f.text("file or service", 332, y, 200, 32)
    return f, y + 32


def main() -> None:
    fig, height = build()
    OUT.write_text(fig.xml(RIGHT, int(height) + 10), encoding="utf-8")
    print(f"Wrote {OUT} ({RIGHT} x {height:.0f} units).")


if __name__ == "__main__":
    main()
