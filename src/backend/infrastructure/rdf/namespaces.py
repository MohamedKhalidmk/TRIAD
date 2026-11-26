"""The IRIs of the TRIAD ontology and the knowledge graph (plan 5, section 1.1).

Only text constants: this module imports no RDF library. Generated SPARQL writes full IRIs,
for example <https://github.com/MohamedKhalidmk/TRIAD/kg/assertion/10>: a prefixed name such as
kg:assertion/10 is not valid SPARQL 1.1.
"""
from __future__ import annotations

BASE = "https://github.com/MohamedKhalidmk/TRIAD/"

# The terms of the ontology (classes and properties), for example TRIAD + "Patient".
TRIAD = BASE + "ontology/triad#"

# The ontology itself, and its version.
ONTOLOGY_IRI = BASE + "ontology/triad"
ONTOLOGY_VERSION = "5.0.0"
ONTOLOGY_VERSION_IRI = f"{ONTOLOGY_IRI}/{ONTOLOGY_VERSION}"

# The individuals: KG + "<class path>/<Id>", for example KG + "patient/42".
KG = BASE + "kg/"

# The named graphs.
GRAPH = BASE + "graph/"
TBOX_GRAPH = GRAPH + "tbox"         # the ontology (TBox)
ABOX_GRAPH = GRAPH + "abox"         # the data (ABox)
SCRATCH_GRAPH = GRAPH + "scratch"   # the scratch graph of the SPARQL scripts and the planted checks
META_GRAPH = GRAPH + "meta"         # the id counters and the build marker
GRAPHS = (TBOX_GRAPH, ABOX_GRAPH, SCRATCH_GRAPH, META_GRAPH)

# The subjects of the meta graph (plan 3.5 and 5.3). They are not individuals of the ontology.
# An id counter: <KG counter/<class path>> triad:issued N. Each write adds a fact; the current value is the MAX.
COUNTER = KG + "counter/"
# The build marker of ensure-kg: the hashes of the data and of the mapping, the ontology version, the scope.
BUILD_MARKER = KG + "build-marker"
