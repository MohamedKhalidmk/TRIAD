# TRIAD ontology (Milestone 5)

This folder holds the semantic model of TRIAD: the OWL 2 ontology, its mapping from the ER model and the relations, and the scripts that check and draw it.
It is the `dal/models/semantic/` folder of the course manual (Appendix A).

| File | Content |
|---|---|
| `ontology.md` | The ER → OWL mapping: the namespaces and graphs, the 28 classes, the object and datatype properties, the restrictions, the keys, the alignment, the rules that OWL cannot hold, and the coverage of each column of the DDL. Report page 3 uses it. |
| `triad.ttl` | The ontology: the hand-written Turtle source. Change this file, not `triad.owl`. |
| `triad.owl` | The ontology as RDF/XML (generated, committed). Load this file into Protégé and Virtuoso. |
| `build_ontology.py` | Checks `triad.ttl`, writes `triad.owl` and prints the counts. It also prints the W3C Direct Mapping example and compares a Protégé copy. |
| `vocabulary.py` | The namespaces, the graph IRIs, the class paths and the map from each DDL column to its term, as Python data. It imports no RDF library. |
| `build_figure.py` | Draws `TRIAD_ontology.drawio` from `triad.ttl`, with the classes at the positions of the ER diagram. |
| `TRIAD_ontology.drawio`, `.pdf`, `.png` | The ontology figure. |

**The ontology IRI** is `https://github.com/MohamedKhalidmk/TRIAD/ontology/triad` (version 5.0.0). The terms use the prefix `triad:` = `https://github.com/MohamedKhalidmk/TRIAD/ontology/triad#`.
The ontology goes into the named graph `https://github.com/MohamedKhalidmk/TRIAD/graph/tbox`. The data goes into `…/graph/abox`.

**Counts** (`triad:` terms only): 28 classes, 25 object properties (17 stored, 5 named inverses, 3 derived), 92 datatype properties, 18 keys on 17 classes, 100 cardinality restrictions, 17 closed value sets. `ontology.md` section 12 has all counts.

## Make the ontology again

Run these commands from the root folder of the repository, with the Python of the project (`requirements-kg.txt`):

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

To draw the figure again:

```bash
.venv/bin/python src/backend/models/semantic/build_figure.py
cd src/backend/models/semantic
drawio -x -f pdf --crop -o TRIAD_ontology.pdf TRIAD_ontology.drawio
drawio -x -p 1 -f png -s 2 -o TRIAD_ontology.png TRIAD_ontology.drawio
```

## Open the ontology in Protégé

1. Install Protégé 5.6 (desktop). It includes its own Java and the HermiT reasoner.
2. **File → Open**, and select `triad.owl`.
3. Look at the class tree (**Entities → Classes**). Staff has the subclasses Doctor, Nurse and MOA. ClinicalEntry has 8 subclasses. Protégé also shows `prov:Entity`, `prov:Agent` and `prov:Person`: TRIAD declares these PROV-O terms locally and does not import PROV-O.
4. Look at **Active ontology → Ontology metrics**. The counts include the PROV-O terms (3 classes, 2 object properties), so they are higher than the `triad:` counts above.
5. **Reasoner → HermiT**, then **Reasoner → Start reasoner**. The expected result: the ontology is consistent, and no class is unsatisfiable (no class under `owl:Nothing`).
6. **Do not save over `triad.owl`.** To check that Protégé reads the full graph, use **File → Save as…**, select **RDF/XML Syntax**, and save to a temporary file (for example `/tmp/triad_protege.owl`). Then run:

   ```bash
   .venv/bin/python src/backend/models/semantic/build_ontology.py --compare /tmp/triad_protege.owl
   TRIAD_PROTEGE_OWL=/tmp/triad_protege.owl .venv/bin/python -m pytest -q src/backend/tests/unit/test_ontology.py -k protege
   ```

   Both commands pass when the two graphs are isomorphic. Never commit the file that Protégé saved. Git ignores `catalog-v001.xml`.

**Dates and HermiT.** OWL 2 has no `xsd:date`, and HermiT stops on an `xsd:date` literal. The four date-only properties (`dateOfBirth`, `subjectDateOfBirth`, `roleStartDate`, `roleEndDate`) have the range `rdfs:Literal`, so the ontology alone is valid. The data keeps `xsd:date`. To run HermiT on data, use a copy of the data without these four properties (plan, Phase 2).

## The W3C Direct Mapping example

```bash
.venv/bin/python src/backend/models/semantic/build_ontology.py --direct-mapping-example
.venv/bin/python src/backend/models/semantic/build_ontology.py --direct-mapping-example --db src/backend/data/triad.db --assertion 3
```

It prints the W3C Direct Mapping of one Assertion row next to the triples of the TRIAD mapping, column by column, and lists the differences. The output is valid Turtle. By default it uses the scenario rows (`01_create_tables.sql` + `02_insert_seed.sql`) in memory. With `--db`, it opens the database read-only.

## Tests

```bash
.venv/bin/python -m pytest -q src/backend/tests/unit/test_ontology.py
```

The tests build the ontology and compare the bytes with `triad.owl`, check that `triad.owl` is the graph of `triad.ttl`, give each check a known error and expect it to stop, and compare the counts and the column map with `ontology.md`.

## Use of AI

Claude Code (Anthropic) wrote the first version of these files from the Milestone 5 plan. The team reviews and corrects them (course AI level D).
