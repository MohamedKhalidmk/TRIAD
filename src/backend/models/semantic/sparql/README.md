# TRIAD SPARQL scripts (Milestone 5)

The SPARQL 1.1 scripts of the knowledge graph. They are the SPARQL forms of the SQL scripts in `../../relational/sql/dml/` (course manual 5.3: INSERT, DELETE, LOAD, CLEAR; SELECT, CONSTRUCT, ASK, DESCRIBE).
Each file runs on Virtuoso 7.2 and on Oxigraph (pyoxigraph 0.3): the files use standard SPARQL 1.1 only, with the writing rules below.

| Order | File | Forms | What it does |
|---|---|---|---|
| 1 | `01_create_graphs.sparql` | `CREATE SILENT GRAPH`, `CLEAR GRAPH`, `LOAD`, `SELECT` | Makes the four TRIAD graphs, clears the TBox and scratch graphs, loads `triad.owl` from GitHub into the TBox graph, and counts the triples of each graph (G1–G4). |
| 2 | `02_insert_data.sparql` | `INSERT DATA` | The example of the manual for TRIAD: a new patient with no visit (I1), and a new fact of Patient A with its visit, front-desk message, allergy entry and assertion (I2). |
| 3 | `03_select_queries.sparql` | `SELECT`, `ASK`, `CONSTRUCT`, `DESCRIBE` | Q1–Q14b: the SQL queries of `03_select_queries.sql`, with the same numbers. QA (ASK): is Patient A allergic to penicillin now? QC (CONSTRUCT): the PROV-O view of the slide chain. QD (DESCRIBE): the current penicillin assertion. |
| 4 | `04_update_delete.sparql` | `DELETE/INSERT … WHERE`, `DELETE … WHERE`, `INSERT DATA`, `DELETE DATA`, `DELETE WHERE`, `INSERT … WHERE`, `CLEAR` | U1–U8: the cases of `04_update_delete.sql` (two **UPDATE**s, a delete with a foreign-key rule, a medication, a patient report), and U4 deletes the person of 02. |
| 5 | `05_constraint_checks.sparql` | `SELECT` | C1–C24: one check for each rule of the relational schema that OWL does not enforce (plan 5, section 1.7; the cases of `05_constraint_violations.sql`). Each check gives no row on valid data. |
| 6 | `06_debug.sparql` | `SELECT` | Appendix B of the manual: B.1 all graphs, B.2 all triples of one graph, B.3 the classes of one graph, B.4 the classes of all graphs; and the counts of each graph (B.1a) and of each class (B.5). |

**UPDATE.** SPARQL 1.1 has no UPDATE keyword. The UPDATE of SQL is `DELETE { old } INSERT { new } WHERE { … }`. U1 and U2 have the label "UPDATE (SPARQL 1.1 has no UPDATE keyword: DELETE/INSERT ... WHERE)".

## The graphs

| Graph | Content | Who can write it (after `kg.sh init`) |
|---|---|---|
| `https://github.com/MohamedKhalidmk/TRIAD/graph/tbox` | the ontology, `../triad.owl` (1,956 triples) | the user `triad` (write and LOAD), `dba` |
| `https://github.com/MohamedKhalidmk/TRIAD/graph/abox` | the data: the full graph (1,298,482 triples on a new clone) or the seed graph `../kg/triad_kg_seed.rdf` (1,125 triples) | `triad`, the account `SPARQL` (no login), `dba` |
| `https://github.com/MohamedKhalidmk/TRIAD/graph/scratch` | empty; the planted examples of the checks and the copies of the tests go here | `triad` (write and LOAD), the account `SPARQL`, `dba` |
| `https://github.com/MohamedKhalidmk/TRIAD/graph/meta` | the id counters and the build marker of the app | `triad`, `dba` |

**Access (measured on Virtuoso 7.2.17).** The anonymous account `SPARQL` (the endpoint `/sparql` and the Conductor SPARQL page) can INSERT and DELETE only in the ABox and the scratch graphs. It cannot write the TBox graph, and it cannot LOAD. The user `triad` (digest login on `/sparql-auth`; `kg.sh sparql` uses it for each update) can write the four graphs, and it can LOAD into the TBox and the scratch graphs. So:
- `01_create_graphs.sparql` runs with `kg.sh sparql`, but **not on the Conductor SPARQL page**. On the manual path, load the ontology with **Conductor → Linked Data → Quad Store Upload** (see "Load the graphs by hand").
- `02` to `06` run on the Conductor SPARQL page too.
- `kg.sh init --strict` removes the write permissions of the account `SPARQL`. Then `02` and `04` on the Conductor page give HTTP 500 (SR186).

## Run order

1. Start Virtuoso and load the graphs (from the root folder of the repository):

   ```bash
   ./src/scripts/kg.sh up       # the container triad-virtuoso on http://127.0.0.1:8890
   ./src/scripts/kg.sh init     # the user triad, the roles and the graph permissions
   ./src/scripts/kg.sh load     # triad.owl -> TBox graph, the full graph -> ABox graph (or: load --seed)
   ```

2. `01_create_graphs.sparql` (optional after `kg.sh load`): it makes the graphs again and loads `triad.owl` from GitHub.
3. `03_select_queries.sparql`, `05_constraint_checks.sparql` and `06_debug.sparql`: they only read.
4. `02_insert_data.sparql`, then `04_update_delete.sparql`: they change the ABox graph. To get the loaded graph back, run `kg.sh load` again (or `kg.sh load --seed`).

**The LOAD of G3.** G3 reads `https://raw.githubusercontent.com/MohamedKhalidmk/TRIAD/main/src/backend/models/semantic/triad.owl`. The file is on the `main` branch only after the merge of Milestone 5. Before the merge, G3 fails with "HT404 … not found", and the TBox graph is empty after G2: run `kg.sh load` to load the local `triad.owl`. The test `test_virtuoso_runs_01_with_the_scratch_graph_for_the_tbox` runs the same LOAD form with a small public RDF/XML file (`TRIAD_KG_TEST_LOAD_URL`, default the pizza ontology on GitHub) into the scratch graph; GitHub sends it as `text/plain`, and Virtuoso reads it as RDF/XML. Oxigraph also has LOAD, but it reads a `text/plain` file as Turtle, so it cannot load `triad.owl` from GitHub.

## Three ways to run a file

1. **`kg.sh sparql`** (all files):

   ```bash
   ./src/scripts/kg.sh sparql 03_select_queries.sparql               # all operations
   ./src/scripts/kg.sh sparql 03_select_queries.sparql --only Q2,QA  # some operations
   ./src/scripts/kg.sh sparql 05_constraint_checks.sparql --max-rows 0
   ```

   A marker line starts each operation: `# Q1. Title`, `# U1. …`, `# C1. …`, `# B.1 …` (see `infrastructure/rdf/sparql_script.py`). The PREFIX lines at the top of the file go before each operation. The queries go to `/sparql`; the updates go to `/sparql-auth` as the user `triad`. The output shows the time and the rows (or the message of the store) of each operation.
2. **The Conductor SPARQL page** (`02` to `06`): open http://127.0.0.1:8890/sparql, copy the PREFIX lines of the file and one operation into the query box, and select "Run Query". The page runs as the account `SPARQL`.
3. **isql** (all files, as the user `dba`): put the word `SPARQL` before each operation, and end it with `;`.

   ```bash
   docker exec -it triad-virtuoso isql 1111 dba dba
   SQL> SPARQL PREFIX triad: <https://github.com/MohamedKhalidmk/TRIAD/ontology/triad#>
        SELECT ?name FROM <https://github.com/MohamedKhalidmk/TRIAD/graph/abox>
        WHERE { ?p a triad:Patient ; triad:name ?name } LIMIT 5;
   ```

   The password is the one of `TRIAD_VIRTUOSO_DBA_PASSWORD` (the default is `dba`). `dba` can do all, so isql does not show the access rules of the other two ways. Without Docker, use the `isql` (or `isql-vt`) of the Virtuoso installation.

## Expected results

On the full graph (`kg.sh load` on a new clone) and on the seed graph (`kg.sh load --seed`):

| File | Full graph | Seed graph |
|---|---|---|
| 01 | G1: four times "already exists" (or the new graph). G2: done. G3: HT404 before the merge. G4: TBox 1,956, ABox 1,298,482, scratch 0, meta 0. | G4: ABox 1,125 |
| 02 | I1: 8 triples. I2: 46 triples. | the same |
| 03 | Q1 8 rows, Q2 3, Q3 1 ("No", "Physician"), Q4 0, Q5 3, Q6 6, Q7 1, Q8 17, Q9a 10, Q9b 5 (five chains of 222 assertions), Q10 1, Q11 4, Q12 7, Q13 2, Q14a 25, Q14b 1 (574 items). QA: false. QC: 18 triples. QD: the triples of `kg:assertion/3` (Virtuoso also gives the 2 links to it). | the same as the full graph, but Q8 13 rows, Q9a 1, Q9b 1 (3 assertions), Q14a 0, Q14b 1 (0 items) |
| 04 | U1, U2: delete 1, insert 1. U3: delete 11. U4: delete 8 (after 02; else 0). U5: insert 4, insert 1, delete 1, delete 6. U6: insert 17. U7: 2 rows (Lucas Brennan, then Patient). U8: done. | the same |
| 05 | C1–C24: "(no rows)" | the same |
| 06 | B.1a: TBox 1,956, ABox 1,298,482. B.3: 28 classes. B.3a: 31 classes (28 TRIAD, 3 PROV-O). B.5: for example Patient 113, Assertion 57,022. | B.1a: ABox 1,125. B.5: Patient 1, Assertion 10. |

`tests/integration/test_kg_queries.py` checks these numbers (the rows of each SQL query are in `EXPECTED_ROWS`).

## SQL = SPARQL: the tests

`tests/integration/test_kg_queries.py` runs each SQL query and its SPARQL query on the same data, and compares the rows:
- **The data:** the scenario database (its graph is the seed graph), the planted database (`tests/fixtures/plant.py`: nurse recommendations for Q4, a patient message with no issuer for the "Patient" branches, mixed time offsets and milliseconds), and the full database (marker `slow`). Each one in Oxigraph, and the full graph in Virtuoso (marker `virtuoso`), with copies of the scenario and planted graphs in the scratch graph of Virtuoso.
- **"The same rows" (plan 5, section 4.5):** the SPARQL variable is the SQL column name with a small first letter. Q2, Q4 and Q14a compare the order too (a total ORDER BY); the other queries compare the rows as multisets. A time compares as its instant (both stores write `+00:00` as `Z`). A NULL is an unbound variable. Numbers compare as numbers. There is no other mapping.
- **Result:** all 16 queries (Q1–Q14b) give the same rows on SQLite and on the knowledge graph, on Oxigraph (scenario, planted, full) and on Virtuoso (full, and the scenario and planted copies). QA, QC and QD give the result that SQL gives.
- **04 = SQL 04:** U1–U7 on the seed graph give the same triples of each predicate as the graph of the scenario database after `04_update_delete.sql`, and the same rows of Q1–Q14b.
- **05:** each check gives no row on the scenario, planted and full graphs, and gives its row when its planted example (bad triples in the scratch graph) is there.

**How the Virtuoso tests get their data.** The ABox graph of Virtuoso must hold the graph of one SQLite database. `TRIAD_KG_TEST_DB` names that database; without it, the tests use a new onboarding (the fixture `full_db`), which is the graph that `kg.sh load` loads on a new clone. A first check compares the triples of each predicate in Virtuoso with the SQL counts of that database. If they differ, the tests fail (with `TRIAD_KG_TEST_DB`) or are skipped (without it). The tests that write use only the scratch graph, and they empty it before and after. The tests are skipped when `TRIAD_SPARQL_QUERY_URL` does not answer.

```bash
./src/scripts/kg.sh up && ./src/scripts/kg.sh init && TRIAD_DB_PATH=/tmp/triad-kg-test.db ./src/scripts/kg.sh load
TRIAD_KG_TEST_DB=/tmp/triad-kg-test.db .venv/bin/python -m pytest -q -m virtuoso src/backend/tests/integration/test_kg_queries.py
```

### Times (the full graph, 1,298,482 triples)

Measured on one laptop (macOS on arm64) on 2026-11-15: SQLite 3 on the same database; Oxigraph 0.3.22 in the process (a store on disk); Virtuoso 7.2.17 in Docker over HTTP (the time includes the request and the JSON answer, about 4 ms). All times are in milliseconds. "First" is the first run of the query in the timing script: the Oxigraph store was opened again, and Virtuoso had run the tests before. "Best" is the best of 5 more runs. SQLite: the best of 5 runs.

| Query | Rows | SQLite | Oxigraph first | Oxigraph best | Virtuoso first | Virtuoso best |
|---|---|---|---|---|---|---|
| Q1 | 8 | 0.3 | 42.8 | 1.2 | 13.5 | 6.3 |
| Q2 | 3 | 0.3 | 2.2 | 1.0 | 7.1 | 6.0 |
| Q3 | 1 | 0.3 | 0.9 | 0.6 | 5.6 | 5.3 |
| Q4 | 0 | 2.8 | 0.5 | 0.1 | 7.5 | 4.9 |
| Q5 | 3 | 0.3 | 3.6 | 0.5 | 14.8 | 5.5 |
| Q6 | 6 | 0.3 | 1.9 | 0.8 | 9.8 | 5.8 |
| Q7 | 1 | 0.3 | 1.6 | 0.5 | 5.8 | 5.7 |
| Q8 | 17 | 0.4 | 77.5 | 7.1 | 10.1 | 6.7 |
| Q9a | 10 | 1.3 | 84.0 | 30.1 | 16.2 | 7.8 |
| Q9b | 5 | 3.0 | 70.0 | 58.3 | 22.9 | 12.4 |
| Q10 | 1 | 0.4 | 1.8 | 0.2 | 5.0 | 4.5 |
| Q11 | 4 | 0.3 | 7.1 | 3.9 | 5.1 | 4.2 |
| Q12 | 7 | 0.3 | 19.1 | 18.2 | 9.9 | 6.3 |
| Q13 | 2 | 0.3 | 2.0 | 0.8 | 9.2 | 5.5 |
| Q14a | 25 | 0.7 | 112.0 | 33.9 | 25.9 | 9.9 |
| Q14b | 1 | 0.5 | 37.4 | 33.4 | 11.4 | 7.8 |
| QA | false | — | 35.4 | 32.7 | 7.7 | 5.1 |
| QC | 18 triples | — | 2.3 | 0.6 | 7.7 | 5.5 |
| QD | 9 / 11 triples | — | 27.1 | 20.5 | 9.2 | 5.6 |

The 24 checks of `05` (best of 5, all together): Oxigraph 18.1 s, Virtuoso 2.4 s. The slowest on Oxigraph: C1 7.2 s, C3 3.4 s, C15 1.2 s; on Virtuoso the slowest is C15 (0.61 s).

## The writing rules

The rules of plan 5 hold for each file: dataset clauses (`FROM <…/abox>`), not `GRAPH <iri> { }`; a bound start for each property path; full IRIs (no `kg:patient/1`); simple literals (no `^^xsd:string`); `FILTER (?type IN (…))`, not `VALUES` in the middle of a pattern; `SUBSTR(STR(?t), 1, 10)` for the local date; `CONTAINS(LCASE(…))`, not `REGEX`; `BOUND(?s)` next to `EXISTS { ?s … }`. This work found more rules. Each one comes from a query that failed or gave a wrong answer:

| # | Rule | What happened |
|---|---|---|
| 10 | A `BIND` must not use a variable of another `BIND` of the same group. Write the expression again. | Virtuoso: the variable is unbound in the second `BIND`, with no error. Q3 gave no author label. |
| 11 | Compare two IRIs with `=`, not with `sameTerm()`. | Virtuoso: `sameTerm(?type, triad:Allergy)` is false also when `?type` is `triad:Allergy`. Q14a sorted all items into the last category. |
| 12 | Do not `COUNT` a variable that can be unbound. Use `SUM(IF(BOUND(?x), 1, 0))`. | Oxigraph 0.3: `COUNT(?x)` and `COUNT(DISTINCT ?x)` also count an unbound `?x`. An empty graph showed 1 triple. |
| 13 | An `IF` with an unbound value: give the value that SQL gives in each branch. For "SUM of NULL is NULL", use the unbound variable in the else branch. | `SUM(IF(?designation = "RN", 1, 0))` is unbound on Oxigraph (an error in the `IF`) but 0 on Virtuoso (it takes the else branch). Q8 differed. |
| 14 | In `FILTER NOT EXISTS`, split a sequence path: `?list rdf:rest* ?cell . ?cell rdf:first ?v`, not `rdf:rest*/rdf:first`. | Virtuoso gave no answer in 3 minutes for C7; the split form takes 0.06 s. |
| 15 | Find a small set first in a sub-select (the heads of the chains, the rules of the TBox), then join the large data to it. Measure: plan rule 5 prefers a flat group, but not for these queries. | Oxigraph 0.3: Q9b took 8 s in one flat group (the path started at each of the 2,517 assertions that supersede another one, before the FILTER NOT EXISTS) and 0.06 s with the sub-select of the 235 heads. C6 took 10 s and 0.1 s. |
| 16 | `DESCRIBE … FROM <g> { … }`: no keyword `WHERE` after the dataset clause. | Oxigraph 0.3 refuses `WHERE` there (a parse error). `WHERE` is optional in SPARQL 1.1. |
| 17 | Each `OPTIONAL` binds variables of its own. Do not join a second `OPTIONAL` on a variable that only an earlier `OPTIONAL` binds. | `OPTIONAL { ?s triad:issues ?m } OPTIONAL { ?s a ?role }` binds `?s` to any staff member when the message has no issuer (this is the SPARQL semantics, not a store error). Q12 lost the rows of the patient message (found with the planted database). |

## Load the graphs by hand (the manual path, manual 5.2.2)

Conductor (http://127.0.0.1:8890/conductor, user `dba`) → **Linked Data → Quad Store Upload**:
1. File `../triad.owl`, named graph IRI `https://github.com/MohamedKhalidmk/TRIAD/graph/tbox`.
2. File `../kg/triad_kg_seed.rdf` (the seed graph; the full graph is too large for the form), named graph IRI `https://github.com/MohamedKhalidmk/TRIAD/graph/abox`.
3. Check **Linked Data → Graphs**, then run B.1 and B.1a of `06_debug.sparql` on the SPARQL page.

Then run `02`, `03`, `04`, `05` and `06` on the SPARQL page (the account `SPARQL` can write the ABox graph after `kg.sh init`).
