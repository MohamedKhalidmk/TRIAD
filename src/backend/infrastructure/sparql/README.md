# The SPARQL adapters (the knowledge-graph store of the backend)

This folder holds the adapters of the knowledge graph (Milestone 5, plan section 5). They implement the same
ports as `infrastructure/sqlite/` (`application/ports.py`), so the API, the use cases and the domain do not change.
`TRIAD_STORE` selects the store: `sqlite` (the default), `virtuoso` or `oxigraph`. Only `main.py`
(`context_factory`) knows the adapters.

## 1. The parts

| File | What it does |
|---|---|
| `client.py` | The driver. `SparqlClient` has `select(template, bindings)`, `ask(...)` and `update(...)`. `HttpSparqlClient` (SPARQLWrapper 2.0.0) sends the queries to the anonymous `/sparql` and the updates to `/sparql-auth` with a digest login. `EmbeddedSparqlClient` uses the one shared pyoxigraph `Store` of a folder. One conversion layer gives plain Python values. |
| `terms.py` | The one escape function (`literal`), the IRIs of the individuals (`iri(kind, id)`, `id_of`), the ontology terms (`term`, `class_term`), the datatypes of the properties (`DATATYPES`) and `render(template, bindings)`. |
| `fragments.py` | Shared pattern text: `CURRENT`, `PATIENT_VISIBLE` (the predicate of Q12), the assertion view, `id_order`, `bind_id`, `CHART_RANK`, `classes_in`, `local_date`, `contains`, `DETAILS`. |
| `paging.py` | `fetch_page`: the COUNT query and the LIMIT/OFFSET query with the same pattern. The order must end with the integer id. |
| `unit_of_work.py` | `SparqlUnitOfWork` (the `UnitOfWork` port), `KgSession` (one for each request), `WriteBuffer` (the writes of one unit of work), `StoreState` (the write lock and the latest time of a store). |
| `ids.py` | The id counters of the meta graph, and `next_identifier` / `unique_identifier` that read the write buffer first. |
| `change.py` | The read-only view of a buffered change for the guards. |
| `guards.py` | The guard framework and the guards of agent A. `guards_records.py` (B), `guards_chat.py` (C), `guards_directory.py` (D) hold the other guards. |
| `sparql_log.py` | The SPARQL log (`TRIAD_SPARQL_LOG`): the template of each request, not the values. |
| `users_repository.py` | `SparqlUserRepository`: complete. It is the worked example below. |
| `*_repository.py` | The other repositories (agents B, C and D): the same methods and results as `infrastructure/sqlite/`. |

The build of the graph is in `application/semantic/build_kg.py` (the use case and its ports) and
`infrastructure/rdf/kg_store.py`, `infrastructure/rdf/logical_hash.py` (the adapters).

## 2. Who writes which file

| Agent | Files | Methods |
|---|---|---|
| A (done) | `client.py`, `terms.py`, `fragments.py`, `paging.py`, `unit_of_work.py`, `ids.py`, `change.py`, `guards.py`, `sparql_log.py`, `users_repository.py`, `tests/fixtures/stores.py`, the store fixtures of `tests/conftest.py` | UserRepository: 3 |
| B | `records_repository.py` (`SparqlRecordRepository`), `guards_records.py` | RecordRepository: 21 |
| C | `patients_repository.py`, `visits_repository.py`, `audit_repository.py`, `chat_repository.py` (5b), `guards_chat.py` | Patient 9, Visit 8, Audit 3, Chat 8 (28) |
| D | `directory_repository.py` (`SparqlDirectoryRepository`), `guards_directory.py` | DirectoryRepository: 29 |

Each agent changes only its own files. If you need a change in a file of agent A (a new fragment, a new buffer
method), write it in your own file first and say so in your report.

## 3. The pattern of a repository method (a worked example)

`SparqlUserRepository.actor` (in `users_repository.py`) gives the same `Actor` as the SQLite repository:

```python
STAFF_ACTOR = f"""
SELECT ?s ?name ?system FROM $abox WHERE {{
  ?s triad:identifierValue $value ; a $role ; triad:name ?name ; triad:identifierSystem ?system .
}}
ORDER BY {fragments.id_order("?s", "staff")} LIMIT 1"""

def actor(self, role, value):
    rows = self.session.select(STAFF_ACTOR, {"value": value, "role": terms.class_term(role)})
    if not rows:
        return None
    r = rows[0]
    return Actor(role=role, key=f"{role}:{value}", name=r["name"], system=r["system"], value=value,
                 staff_id=id_of(r["s"], "staff"))
```

The rules:

1. **A template and its bindings.** A template is a constant of the code. `$name` is a placeholder; `render()`
   puts the SPARQL form of the binding there. Never put a value into the text yourself (no f-string with a value).
   A template never uses `$` for a SPARQL variable (write `?x`).
2. **The values.** A `str` becomes a simple literal (escaped). An `int` becomes `xsd:integer`, a `bool`
   `xsd:boolean`. A date or a dateTime in a query needs `terms.date(...)` or `terms.date_time(...)`.
   An individual is `terms.iri(kind, id)` (an integer id only). A class is `terms.class_term("Doctor")`.
   A list becomes `a, b, c` (for `IN (...)` or `VALUES`). `None` is an error: leave the pattern out.
3. **The dataset clause.** Each query has `FROM $abox` (SPARQL writing rule 1). `client.select` refuses a query
   with no `FROM`. `$abox`, `$tbox`, `$meta` and `$scratch` need no binding.
4. **The writing rules of the plan** hold: a bound start for a property path; `FILTER (?t IN (...))`, not `VALUES`
   in the middle; each `BIND` at the end of its group; the local date with `fragments.local_date`; text search with
   `fragments.contains` (give the text in lower case); `BOUND(?s)` before `EXISTS` on an OPTIONAL variable.
   **Measured on the full graph (Oxigraph):** a constant that many subjects share (for example the Synthea
   identifier system: about 62,000 individuals) makes Oxigraph start the pattern there. Start with the bound
   subject and compare the constant in a FILTER: `?i triad:identifierValue ?v ; triad:identifierSystem ?sys .
   FILTER (?sys = $system)`. The users list went from 15 s to 8 ms. Test each new query on `full_store` once.
5. **The rows.** `select` gives a list of dicts. An IRI is a `str` (no angle brackets): `id_of(row["s"])` gives the
   id. A dateTime comes back with `+00:00`, not `Z` (D11); the stores drop the trailing zeros of the seconds, so
   compare times as instants (`domain.rules.parse_time`). An unbound variable is `None`.
6. **The same domain objects.** Map each row to the view of the SQLite repository (`UserView`, `AssertionView`,
   ...). Keep the order of SQLite. An order that SPARQL cannot give (a `GROUP_CONCAT`, the order of a set of
   literals) is made in Python in a stated order (see `_departments`).
7. **Pages.** Use `paging.fetch_page(self.session.client, select, where, bindings, order_by, page, build)`. The last
   condition of `order_by` must be `fragments.id_order("?x", kind)` (or `DESC(...)` of it), or a variable that a
   `fragments.bind_id(...)` of the pattern gives (for a UNION of two kinds). LIMIT and OFFSET are integers in the
   text. `count="DISTINCT ?x"` if the pattern can give a row two times.

The variables of the assertion view and the SQLite columns that they replace are in the text of `fragments.py`.
`test_sparql_fragments.py` shows that the view, `CURRENT`, `PATIENT_VISIBLE` and the chart order give the SQLite
rows on the planted data.

## 4. How to write (the write buffer)

The use cases do not change: `with ctx.uow.write() as now:`. In a write method of a repository, get the buffer of
the current write. Nothing goes to the store before the end of the `with` block.

```python
def create(self, name, date_of_birth, sex, phone, address, identifiers):      # PatientRepository.create
    buf = self.session.write_buffer()            # RuntimeError outside ctx.uow.write()
    patient_id = buf.create("patient", {"name": name, "dateOfBirth": date_of_birth, "patientSex": sex,
                                        "phoneNumber": phone, "street": address.street, ...})
    for system, value in identifiers:
        ident = buf.create("patient-identifier", {"identifierSystem": system, "identifierValue": value})
        buf.add(iri("patient", patient_id), {"identifier": iri("patient-identifier", ident)})
    return patient_id
```

| Method | What it does | At the commit |
|---|---|---|
| `buf.create(kind, values, types=(), id=None) -> int` | A new individual: `rdf:type` the class of the kind (and `types`, for example `("Doctor",)` or `("Allergy",)`), and the values. The id comes from the counter. | in the one `INSERT DATA` |
| `buf.add(subject, values)` | More triples on a subject (new or stored), for example the reverse-direction links `hasVisit`, `contains`, `issues`, `includes`, `identifier`, `member`. | in the one `INSERT DATA` |
| `buf.replace(subject, prop, value)` | New values of one property (a list for a multivalued property such as `language`; `None` removes it). A subject that does not exist gets no triple (as an UPDATE of no row). | one `DELETE/INSERT ... WHERE` |
| `buf.delete_subject(kind, id)` | Delete the triples of a subject and the links of its parent to it. Only the kinds of `guards.DELETABLE`. | one delete request |
| `buf.new_id(kind)` | The next id of a kind, if you need it before `create`. | the counter fact |
| `buf.find(kind, **match)`, `buf.values(kind, prop, **match)`, `buf.created(kind)` | Read your writes: the new subjects of this write. | — |
| `ids.next_identifier(session, kind, system, prefix, width)`, `ids.unique_identifier(session, kind, system, base)` | The identifier values; they look in the buffer first (three new entries of one message get three values). `ids.TABLE_KIND` maps the table names of the ports to the kinds. | — |

- `values` maps a property name of the ontology (`terms.PROPERTIES`) to a value. The datatype comes from
  `terms.DATATYPES` (the `rr:datatype` of the R2RML mapping): a time is a `str` in ISO 8601, a date `YYYY-MM-DD`.
  A value of an object property is an IRI (`iri(kind, id)`). `None` gives no triple. An unknown property is
  `ValueError` (an error of the code). A wrong value (for example a time that is not ISO 8601) is `Invalid` (422),
  as a failed CHECK in SQLite.
- The kinds are the 17 class paths: `department`, `location`, `staff`, `patient`, `patient-identifier`, `visit`,
  `visit-location`, `clinical-entry`, `care-team-member`, `medication`, `message`, `assertion`, `chat-session`,
  `chat-turn`, `citation`, `audit-event`, `works-in`. A subtype is a second type of the same individual: a Doctor is
  `create("staff", {...}, types=("Doctor",))`; an allergy is `create("clinical-entry", {...}, types=("Allergy",))`.
- `CareTeamMember` hangs on the care-team entry: `buf.add(iri("clinical-entry", entry), {"member": iri("care-team-member", m)})`.
- A read inside the write block reads the store, not the buffer (except the helpers above). The use cases read
  the new rows after the block (for example `assertions_by_id` after `post_message`).

The commit (in this order, under the process-wide write lock): the guards; one ASK that no new IRI exists
(else Conflict, and the counters are seeded again); the `replace` requests; the deletes; one `INSERT DATA` of the
new triples and the counters. If a request fails after others were applied, the commit sends their inverse in the
reverse order and raises the error. `write()` inside `write()` raises `NestedWriteError` at once.

## 5. How to add a guard

A guard holds a rule that SQLite holds in a constraint or a trigger. It runs in Python at the commit, on the
buffered change, under the lock. Put it in your own file (`guards_records.py`, `guards_chat.py`,
`guards_directory.py`); each file has registered stubs with the SQLite rule and the exact error in the docstring.

```python
from infrastructure.sparql.change import Change
from infrastructure.sparql.guards import Facts, register, trigger_failed

@register("assertion.one-head-per-entry", kinds=("assertion",), owner="B")
def one_head_per_entry(change: Change, facts: Facts) -> None:
    for new in change.created("assertion"):
        entry = new.get("about")                     # a Term: <.../clinical-entry/12>
        rows = facts.select("SELECT ?head FROM $abox WHERE { ?head triad:about $e . "
                            "FILTER NOT EXISTS { ?n triad:supersedes ?head } }", {"e": entry})
        ...
        raise trigger_failed("The entry has a current assertion. The new assertion must supersede it.")
```

- `change.created(kind)` gives `NewSubject` objects (`.id`, `.iri`, `.types`, `.get(prop)`, `.all(prop)`);
  `change.added(prop)`, `change.replaced(kind)`, `change.deleted(kind)`, `change.links_to(iri, prop)`,
  `change.is_new(iri)`, `change.is_deleted(iri)`.
- `facts.select(template, bindings)` reads stored facts (one SELECT; it cannot see the buffer, so look in the change
  too). `facts.existing(iris)` gives the IRIs that exist.
- Raise the SQLite error (plan 1.7): `unique_conflict(table, columns)` (409, `fields.key` such as
  `Medication.Code, Medication.CodeSystem`), `foreign_key_conflict()` (409), `check_failed(text)` (422,
  `fields.database`), `trigger_failed(text)` (422, the text of the trigger).
- `kinds`: the guard runs only when the change touches one of these kinds. The guards run in the order of
  registration (agent A first), then in the order of `guards.EXTENSIONS`: the assertion guards (B, the triggers
  of SQLite) before the chat guards (C) and the key guards (D, UNIQUE), because SQLite runs the BEFORE INSERT
  triggers of a row before its UNIQUE constraints. `test_store_guards.py` checks the order, and the guard table
  (each case of `05_constraint_violations.sql` that the API can reach) on each store.
- The guards of agent A: `delete.allow-list` (Assertion and AuditEvent are append-only: no replace, no delete, no
  new triple on a stored one), `foreign-keys` (a deleted row is not in use; each IRI of a new triple exists), and
  the example `patient.key-is-fixed`.

## 6. How to run the tests of one port on both stores

The store fixtures are in `tests/conftest.py` (code in `tests/fixtures/stores.py`):

| Fixture | Data | Note |
|---|---|---|
| `store` | the scenario data (01 + 02) | fast |
| `planted_store` | the planted data (`tests/fixtures/plant.py`) | fast |
| `full_store` | the full data (the onboarding) | marker `slow`; the first run builds the full graph (about 15 s) |
| `module_full_store` | the full data, ONE copy for all tests of a module | marker `slow`; for tests that share their data (the journey `test_hospital_visit.py`, `test_pages.py`, `test_assistant_tools.py`). pytest runs the tests of the module for one store, then for the next. Do not use `full_store` in the same module (on Virtuoso its load replaces the data of the module). |

Each one is parametrized over `TRIAD_TEST_STORES` (default `sqlite,oxigraph`). A handle gives `store.client()`
(a TestClient), `store.open_ctx()` (an `AppContext`), `store.reference()` (a SQLite context on the same data),
`store.probe` (the stored rows), `store.db_path`, `store.name`, `store.is_kg` and `store.time_limit(seconds)`.

To change an existing test to both stores, change the fixture and the SQL reads:

```python
def test_a_denied_chart_read_is_in_the_audit_log(full_store):                  # was: (client, full_copy)
    client = full_store.client()
    before = full_store.probe.count("audit-event", auditOutcome="Denied")      # was: SELECT COUNT(*) ...
    ...
    last = full_store.probe.last("audit-event")                               # {"actorValue": ..., "subjectName": ...}
```

The probe uses the ontology terms: `count(kind, **match)`, `rows(kind, **match)`, `row(kind, id)`, `last(kind)`.
An FK term gives the integer id of the target (for a reverse-direction term, the parent: `issues` of a message is
the staff id). `count(kind)` with no match is one COUNT, and `row(kind, id)` reads one subject: use them on the
full data (`probe.count("message")`). The probe reads the kinds of `ids.KIND_TABLE` (the subtype columns, for
example `OnsetDate`, are not in it). `tests/integration/test_store_users.py` is the example file.

The other patterns of the converted tests (`test_api.py`, `test_pages.py`, `test_assistant_tools.py`):
- A query of the scripts runs in the language of the store: the SQL of `dml/03_select_queries.sql` on SQLite, the
  SPARQL of `models/semantic/sparql/03_select_queries.sparql` on a KG store (`q12_ids`, `q14` of the tests).
- The expected result of a full chart comes from `store.reference()` (the port has no method that reads a full
  chart); the input rows that a test does not change (for example the head of the longest chain) come from the
  SQLite copy `store.db_path`.
- A check of the SQL text runs only on SQLite (`@pytest.mark.stores("sqlite")`); its KG form checks the SPARQL log
  (`sparql_log="on"`: the template of each request, for example the LIMIT of each chart read of a chat turn).
- Times compare as instants (`domain.rules.parse_time`).

```
.venv/bin/python -m pytest -q src/backend/tests/integration/test_store_users.py      # sqlite and oxigraph
.venv/bin/python -m pytest -q -k oxigraph src/backend/tests/...                       # Oxigraph only
.venv/bin/python -m pytest -q -m "not kg"                                             # SQLite only
TRIAD_TEST_STORES=sqlite,oxigraph,virtuoso .venv/bin/python -m pytest -q -m virtuoso  # with Virtuoso
```

- `@pytest.mark.stores("oxigraph", "virtuoso")` runs a test only on these stores (the other parameters are
  deselected).
- The built Oxigraph store stays in `.pytest_cache/d/triad-kg/<marker>/`. Each test gets a new copy (pyoxigraph
  `backup()`). A change of the data, the mapping or the ontology version gives a new marker, and a new build.
  Remove the folder to build again.
- **Virtuoso:** the tests use the one store of the container and REPLACE its TRIAD graphs (the seed graph for
  `store`; the export of the data for `planted_store` and `full_store`, which writes into `TRIAD_KG_DIR`). The
  fixture loads the data again when the marker differs or when the last test wrote. After the tests, run
  `python src/backend/main.py ensure-kg --store virtuoso` to build the graph of your database again.

## 7. The commands

```
python src/backend/main.py ensure-kg --store oxigraph [--reset-kg]   # build if the marker is not current
python src/backend/main.py load-kg --store oxigraph [--seed]          # load the export of TRIAD_KG_DIR, or the seed
python src/backend/main.py validate-kg [--file PATH]                  # SHACL (infrastructure/rdf/shacl.py)
python src/backend/main.py serve --store oxigraph                     # ensure-db, ensure-kg, then serve
```

For Virtuoso: `./src/scripts/kg.sh up`, `./src/scripts/kg.sh init`, then
`python src/backend/main.py ensure-kg --store virtuoso`. ensure-kg exports into `TRIAD_KG_DIR` and runs
`kg.sh load --no-export` (the bulk loader of Virtuoso and the checks of kg.sh). `kg.sh load` alone writes no
marker; the next ensure-kg then builds again. A rebuild deletes the writes that the app made in the knowledge graph.

The start check: with a KG store, `create_app` needs a build marker with the ontology version and the mapping
hash of the code. `GET /api/health` gives `store` and `ontologyVersion` (doc/api.md section 1.6).

## 8. Known limits

- **Virtuoso is not tested here.** The HTTP client is tested against a fake endpoint that answers like Virtuoso
  7.2 (digest, HTTP 500, `X-SPARQL-MaxRows`). The Virtuoso load path (`kg.sh load --no-export`) is tested only with
  a fake runner.
- **D11:** Virtuoso orders and compares `xsd:dateTime` by the text, not by the instant. The order differs only
  for two times with different offsets that are less than 7 hours apart. The latest time of the store (the clock)
  uses `MAX`, so it has the same limit on Virtuoso.
- **Times:** a stored time comes back with `+00:00` for `Z`, and with no trailing zeros of the seconds
  (`.100` becomes `.1`). The offset does not change. The API thus can give another text of the same instant.
- **The times of the details** (`onsetDate`, `abatementDate`, `performedDate`, `issuedDate`; range `xsd:dateTime`):
  the use case keeps each one in the full ISO 8601 form on both stores (`domain.rules.full_time`; a date of the
  record form is midnight UTC; doc/api.md section 3.4). So the export, the graph of a KG store and the shapes agree,
  and a short form gives 201 with the same text on both stores. A time in another form is `Invalid` (422) in the
  write buffer. The limit: a SQLite database that an earlier version changed can hold a date-only text in these
  columns. Its export has `"2026-09-01"^^xsd:dateTime`, which is not a valid `xsd:dateTime`; pyshacl (rdflib reads
  the text with Python `fromisoformat`) and check C8 do not report it (`test_store_detail_times.py`).
- **Text search:** `CONTAINS(LCASE(...))` is literal: `%` and `_` are not wildcards as in SQLite `LIKE`, and LCASE
  lowers all letters (SQLite `lower()` lowers only ASCII).
- **One writer process for each store.** The lock is in the process. A second process can mint the same IRI; the
  ASK before the commit then gives Conflict, and the counters are seeded again.
- **A failure of the inverse** (the compensation) raises `HalfWriteError` and logs it: the store can then hold a
  half change. A timeout of the one `INSERT DATA` gives an unknown state (the store can hold the new triples).
- **The meta graph** holds `triad:issued`, `triad:dataHash`, ... (plan 5.3). These terms are not in the ontology.
- `next_identifier` reads all identifier values of a system with the prefix (the SQLite version reads them too).
