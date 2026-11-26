# TRIAD semantic model (Milestone 5)

This folder holds the semantic model of TRIAD: the OWL 2 ontology, the R2RML mapping from the relations to RDF, the
SHACL shapes, the seed graph and the SPARQL scripts. It is the `dal/models/semantic/` folder of the course manual
(Appendix A): the ontology `*.owl`, the knowledge-graph triples `*.rdf` and the DML queries `*.sparql`.

## The folder

| Item | Content | More information |
|---|---|---|
| [`ontology.md`](ontology.md) | The ER → OWL mapping: the namespaces and graphs, the 28 classes, the object and datatype properties, the restrictions, the keys, the alignment, the rules that OWL cannot hold, and the coverage of each column of the DDL. Report page 3 uses it. | — |
| [`triad.ttl`](triad.ttl) | The ontology: the hand-written Turtle source. Change this file, not `triad.owl`. | [The ontology](#the-ontology) |
| [`triad.owl`](triad.owl) | The ontology as RDF/XML (generated, committed; 1,956 triples). Load this file into Protégé and Virtuoso. | [The ontology](#the-ontology) |
| `build_ontology.py` | Checks `triad.ttl`, writes `triad.owl` and prints the counts. It also prints the W3C Direct Mapping example and compares a Protégé copy. | [The ontology](#the-ontology) |
| `vocabulary.py` | The namespaces, the graph IRIs, the class paths and the map from each DDL column to its term, as Python data. It imports no RDF library. | — |
| `build_figure.py`, `TRIAD_ontology.drawio`, `.pdf`, `.png` | The ontology figure, with the classes at the positions of the ER diagram. | [The figure](#the-figure) |
| [`mapping/`](mapping/) | `triad.r2rml.ttl`: the W3C R2RML mapping (35 TriplesMaps). `build_mapping.py` writes it from `vocabulary.py` and the DDL. | [The mapping](#the-mapping-mapping) |
| [`shapes/`](shapes/README.md) | `triad.shacl.ttl`: the W3C SHACL shapes (29 node shapes, 28 SHACL-SPARQL constraints). `build_shapes.py` writes the generated part. | [`shapes/README.md`](shapes/README.md) |
| [`kg/`](kg/) | `triad_kg_seed.rdf`: the seed graph (RDF/XML, 1,125 triples), the scenario data for the upload by hand. | [The seed graph](#the-seed-graph-kg) |
| [`sparql/`](sparql/README.md) | `01_create_graphs.sparql` to `06_debug.sparql`: the SPARQL 1.1 scripts, their run order, the expected results, the measured times and the writing rules. | [`sparql/README.md`](sparql/README.md) |

**The ontology IRI** is `https://github.com/MohamedKhalidmk/TRIAD/ontology/triad` (version 5.0.0). The terms use the prefix `triad:` = `https://github.com/MohamedKhalidmk/TRIAD/ontology/triad#`.
The individuals are `https://github.com/MohamedKhalidmk/TRIAD/kg/<class path>/<Id>`.
The ontology goes into the named graph `https://github.com/MohamedKhalidmk/TRIAD/graph/tbox`. The data goes into `…/graph/abox`.

**Counts** (`triad:` terms only): 28 classes, 25 object properties (17 stored, 5 named inverses, 3 derived), 92 datatype properties, 18 keys on 17 classes, 100 cardinality restrictions, 17 closed value sets. `ontology.md` section 12 has all counts.

## Make the files again

Run these commands from the root folder of the repository, with the Python of the project (`requirements-kg.txt`).
Each `--check` stops with an error if its file is not current. The order follows the inputs of each file.

```bash
.venv/bin/python src/backend/models/semantic/build_ontology.py                    # triad.ttl -> triad.owl
.venv/bin/python src/backend/models/semantic/mapping/build_mapping.py             # vocabulary.py + DDL -> mapping/triad.r2rml.ttl
.venv/bin/python src/backend/models/semantic/shapes/build_shapes.py               # triad.ttl + DDL -> shapes/triad.shacl.ttl (part 1)
PYTHONPATH=src/backend .venv/bin/python -m infrastructure.rdf.kg_export --seed    # SQL scripts 01 + 02 -> kg/triad_kg_seed.rdf
npm --prefix src/frontend run build:sparql                                        # sparql/03 -> the queries of the Demo guide
```

```bash
.venv/bin/python src/backend/models/semantic/build_ontology.py --check
.venv/bin/python src/backend/models/semantic/mapping/build_mapping.py --check
.venv/bin/python src/backend/models/semantic/shapes/build_shapes.py --check
npm --prefix src/frontend run check:demo                                          # also compares sparql_queries.json with sparql/03
```

The full knowledge graph is not in git. `python src/backend/main.py export-kg` writes it into `src/backend/data/kg/`
(see the root README, "Knowledge graph (Milestone 5)").

## The ontology

```bash
.venv/bin/python src/backend/models/semantic/build_ontology.py           # check triad.ttl, then write triad.owl
.venv/bin/python src/backend/models/semantic/build_ontology.py --check   # check only; stop if triad.owl is old
```

The script stops with a clear message when a check fails:
- **Coverage:** each table, column, foreign key and UNIQUE constraint of `01_create_tables.sql` maps to a term, or `vocabulary.py` gives the reason. Each NOT NULL column has its cardinality restriction. Each value set equals the `CHECK … IN` list of its column.
- **Tree:** the stored object properties and the subclass links make a tree. It uses the check of `../er/build_erd.py`.
- **OWL 2 DL:** each datatype is in the OWL 2 datatype map (no `xsd:date`); no characteristic or cardinality on a non-simple property; one `rdfs:domain` and one `rdfs:range` for each property; no closed range on a shared property; one declaration for each term; no `owl:imports`.
- **Labels:** each class and property has `rdfs:label`, `rdfs:comment` and `rdfs:isDefinedBy`.

`triad.owl` is the same, byte for byte, on each run. The script makes the blank nodes canonical (rdflib), sorts the triples and writes RDF/XML with pyoxigraph 0.3. Then it reads the file back and compares.

### The figure

```bash
.venv/bin/python src/backend/models/semantic/build_figure.py
cd src/backend/models/semantic
drawio -x -f pdf --crop -o TRIAD_ontology.pdf TRIAD_ontology.drawio
drawio -x -p 1 -f png -s 2 -o TRIAD_ontology.png TRIAD_ontology.drawio
```

## The mapping (`mapping/`)

`mapping/triad.r2rml.ttl` is the W3C R2RML mapping: 35 TriplesMaps (29 for the tables, 6 for the foreign keys in the
reverse direction). Morph-KGC 2.10.0 runs it on a copy of the SQLite database (`main.py export-kg`,
`infrastructure/rdf/kg_export.py`). The export compares the triples of each predicate and of each class with the SQL
counts, and it writes no file if one count differs. Do not edit the mapping by hand: `build_mapping.py` writes it.
Two rules of the mapping come from failed tests (the comment at the top of the file gives all rules):
- It reads only tables and columns, with no `rr:sqlQuery`. In a query, Morph-KGC turns a NULL into the literal `"None"`,
  and a nullable integer foreign key into an IRI that ends in `.0`.
- The care-team members need a join: `CareTeamMember.CareTeamId` holds `CareTeam.Id`, not the entry Id
  (`rr:parentTriplesMap` and `rr:joinCondition`; `ontology.md` section 1).

## The seed graph (`kg/`)

`kg/triad_kg_seed.rdf` is the graph of the scenario data (the SQL scripts `01` and `02`): Patient A, 25 staff members,
the departments and the locations. It is RDF/XML, 1,125 triples, and small enough for the Quad Store Upload of Conductor.
The command of [Make the files again](#make-the-files-again) writes it again, the same bytes on each run. Load it with
`./src/scripts/kg.sh load --seed` (Virtuoso), `python src/backend/main.py load-kg --store oxigraph --seed` (Oxigraph),
or by hand in Conductor. `python src/backend/main.py validate-kg` checks it with the SHACL shapes.

## Open the ontology in Protégé

These steps are for a team member. They were done on 2026-11-17 with Protégé 5.6 and HermiT 1.4.3.456 (issue 6);
the results are below each step, and the screenshots are in `doc/screenshots/m5/protege_*.png`.

1. Install Protégé 5.6 (desktop). It includes its own Java and the HermiT reasoner.
2. **File → Open**, and select `triad.owl`.
3. Look at the class tree (**Entities → Classes**). Staff has the subclasses Doctor, Nurse and MOA. ClinicalEntry has 8 subclasses. Protégé also shows `prov:Entity`, `prov:Agent` and `prov:Person`: TRIAD declares these PROV-O terms locally and does not import PROV-O.
4. Look at **Active ontology → Ontology metrics**. The counts include the PROV-O terms (3 classes, 2 object properties), so they are higher than the `triad:` counts above.
   Result: 32 classes (28 + 3 PROV-O + `owl:Thing`), 27 object properties (25 + 2 PROV-O), 92 data properties.
5. **Reasoner → HermiT**, then **Reasoner → Start reasoner**. The expected result: the ontology is consistent, and no class is unsatisfiable (no class under `owl:Nothing`).
   Result: consistent; the inferred class tree equals the asserted tree.
6. **The seed graph with the ontology.** Do not open `kg/triad_kg_seed.rdf` alone: it has no ontology header, so
   Protégé reads its 104 properties as annotation properties, and HermiT ignores the data. An import added in
   Protégé afterwards does not change this. Make a copy of the seed graph with a header that imports `triad.owl`
   (put it in a folder outside the repository), and open the copy:

   ```xml
   <owl:Ontology xmlns:owl="http://www.w3.org/2002/07/owl#" rdf:about="urn:triad:test:seed">
     <owl:imports rdf:resource="file:/ABSOLUTE/PATH/TO/src/backend/models/semantic/triad.owl"/>
   </owl:Ontology>
   ```

   (the lines go right after the `<rdf:RDF …>` tag). Then the metrics show 92 data properties and 1,627 logical
   axioms (502 + 1,125). Start HermiT, then **DL Query**: `'asserted by' some Staff`, with **Instances** selected.
   Result: consistent, and the query gives the 10 assertions of the seed graph (the property chain
   `inMessage` → `issuedBy`).
7. **Do not save over `triad.owl`.** To check that Protégé reads the full graph, use **File → Save as…**, select **RDF/XML Syntax**, and save to a temporary file (for example `/tmp/triad_protege.owl`). Then run:

   ```bash
   .venv/bin/python src/backend/models/semantic/build_ontology.py --compare /tmp/triad_protege.owl
   TRIAD_PROTEGE_OWL=/tmp/triad_protege.owl .venv/bin/python -m pytest -q src/backend/tests/unit/test_ontology.py -k protege
   ```

   Both commands pass when the two graphs are isomorphic. Never commit the file that Protégé saved. Git ignores `catalog-v001.xml`.
   Result: the commands report 838 different triples, but the axioms are the same. Protégé adds `rdf:type rdf:List`
   to the 72 list nodes, and it writes 3 `owl:inverseOf` axioms from the other side (`hasVisit`/`visitOf`,
   `contains`/`inMessage`, `member`/`memberOf`). So the test fails on a Protégé re-save until it removes these
   differences before it compares.
8. Take the screenshots for `doc/screenshots/m5/`: the class tree, the ontology metrics and the HermiT result.

**Dates and HermiT.** OWL 2 has no `xsd:date` (it is not in the OWL 2 datatype map). The four date-only properties (`dateOfBirth`, `subjectDateOfBirth`, `roleStartDate`, `roleEndDate`) have the range `rdfs:Literal`, so the ontology alone is valid. The data keeps `xsd:date` (31 values in the seed graph). In Protégé 5.6, HermiT 1.4.3.456 does not stop on them: it finishes on the seed graph in about 2 s with no error and no warning in the log, so it does not check these values. An earlier review reported that HermiT stops on them; this did not happen in Protégé. To check the dates with a reasoner, store them as `xsd:dateTime`.

## The W3C Direct Mapping example

```bash
.venv/bin/python src/backend/models/semantic/build_ontology.py --direct-mapping-example
.venv/bin/python src/backend/models/semantic/build_ontology.py --direct-mapping-example --db src/backend/data/triad.db --assertion 3
```

It prints the W3C Direct Mapping of one Assertion row next to the triples of the TRIAD mapping, column by column, and lists the differences. The output is valid Turtle. By default it uses the scenario rows (`01_create_tables.sql` + `02_insert_seed.sql`) in memory. With `--db`, it opens the database read-only.

## Tests

```bash
.venv/bin/python -m pytest -q src/backend/tests/unit/test_ontology.py            # the ontology build and its checks
.venv/bin/python -m pytest -q src/backend/tests/integration/test_kg_export.py    # the mapping, the export and the seed graph
.venv/bin/python -m pytest -q src/backend/tests/integration/test_kg_shacl.py     # the shapes
.venv/bin/python -m pytest -q src/backend/tests/integration/test_kg_queries.py   # SQL = SPARQL (the scripts of sparql/)
```

`test_ontology.py` builds the ontology and compares the bytes with `triad.owl`, checks that `triad.owl` is the graph of `triad.ttl`, gives each check a known error and expects it to stop, and compares the counts and the column map with `ontology.md`.

## Use of AI

Claude Code (Anthropic) wrote the first version of these files from the Milestone 5 plan. The team reviews and corrects them (course AI level D).
