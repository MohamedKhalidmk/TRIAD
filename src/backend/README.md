# TRIAD backend

The backend is the server of the TRIAD prototype. It has four parts:

- a FastAPI web API under `/api`. The contract of the API is [`doc/api.md`](../../doc/api.md).
- a SQLite database. The schema is [`models/relational/sql/ddl/01_create_tables.sql`](models/relational/sql/ddl/01_create_tables.sql).
- a knowledge graph (Milestone 5) in Virtuoso 7.2 or in the embedded store Oxigraph. The ontology, the mapping and
  the SPARQL scripts are in [`models/semantic/`](models/semantic/README.md).
- a command-line tool (`main.py`). It builds the database and the knowledge graph from the FHIR data and starts the server.

All data is synthetic. Do not put real patient data in the prototype.

## Layers

The backend uses Clean Architecture. Each layer can use only the layers below it.
Only `main.py` (the composition root) knows the concrete adapters.

```
api  ->  application  ->  domain
infrastructure  ->  application (ports) + domain
main.py  ->  all layers (it connects the adapters to the ports)
```

| Folder | Layer | Name in the course manual | What it holds |
|---|---|---|---|
| `domain/` | entities and rules | biz | Records, read models, value sets, errors. The access policy (`access.py`) and the rules (`rules.py`): the patient-visible rule, the author label, the head check, the plan visit and the clock rule. No I/O. |
| `application/` | use cases and ports | biz | One module for each area: `patients.py`, `visits.py`, `records.py`, `audit.py`, `directory.py`, `users.py`, `codes.py`, `chat/`, `assistant/`, `onboarding/`, `semantic/` (the build of the knowledge graph). `ports.py` holds the interfaces (Python `Protocol`) that the adapters implement. |
| `infrastructure/` | adapters | dal | `sqlite/`: the SQLite repositories and the unit of work (driver: `sqlite3`). `sparql/`: the SPARQL repositories, the write buffer and the guards (driver: SPARQLWrapper for Virtuoso, pyoxigraph for Oxigraph). `rdf/`: the R2RML export, the load and count checks, the SHACL check. `fhir/`: the FHIR reader and mappers. `llm/`: the fake model and the LiteLLM model. `clock.py`, `ids.py`, `config.py`. |
| `api/` | web interface | ui | The routers, the pydantic models (camelCase JSON), the error mapping and the user header. |
| `models/` | data models | dal/models | The ER diagram (`er/`), the relations and the SQL scripts (`relational/`), the ontology, the mapping, the shapes, the seed graph and the SPARQL scripts (`semantic/`). |

The frontend (`src/frontend/`) is also part of the ui layer.

The architecture figure ([PNG](../../doc/architecture.png), [PDF](../../doc/architecture.pdf)) shows the three layers, the request path, the onboarding path, the two sets of data adapters and the Care Assistant.
A solid arrow is a call. A dashed arrow with an open head means that an adapter implements a port. Grey parts are the TRIAD contribution, as in the ER diagram. A dashed box is a file, a tool or a service.
The script `src/scripts/build_architecture.py` makes the figure and the build figure of the knowledge graph ([`doc/kg_build.png`](../../doc/kg_build.png)). Its first lines give the commands that make them again.

![TRIAD architecture](../../doc/architecture.png)

## Why raw SQL and no ORM

- The schema in `ddl/01_create_tables.sql` is the single source of truth. An ORM would make a second copy of the schema in Python.
- The read side uses the same SQL as the report queries in `dml/03_select_queries.sql`:
  - The chart uses the current-state rule of Q1 (no assertion supersedes it).
  - The chain endpoint uses the recursive query of Q2 (`WITH RECURSIVE`).
  - The care-team check uses the logic of Q13 (Status = active, and nothing supersedes the entry).
  - The patient-visible rule is the rule of Q12. The chart query of a patient has the predicate of Q12 in its WHERE clause.
    A test shows that this predicate, `domain/rules.py` and Q12 give the same rows for each patient.
  - Each list endpoint gives one page (doc/api.md section 1.5): a `COUNT(*)` query and a query that ends with
    `ORDER BY ..., Id LIMIT ? OFFSET ?` (`infrastructure/sqlite/paging.py`). Q14 shows one page of a chart.
- The triggers and the CHECK constraints of the schema stay the last line of defense. The unit of work changes their errors into API errors (409 or 422).
- The repositories use the Python standard library `sqlite3`. Each value is a `?` parameter. Table and column names come only from fixed lists.
- The application layer uses ports, not SQL. The SPARQL adapters of Milestone 5 implement the same ports.

## How the API uses SQLite

- Each request opens one connection (`foreign_keys = ON`, `busy_timeout`). The database uses WAL mode.
- Each write starts with `BEGIN IMMEDIATE`. The access check runs before the write.
- When the rules stop an action about one patient, the backend writes an audit record (Outcome = Denied). Then it sends the 403.
- Each write gets a time that is after the latest time in the database. Thus the times always increase.
  With the computer clock (the default), the time is max(now, the latest time + 1 second).
  With a fixed `TRIAD_NOW`, the time is max(`TRIAD_NOW`, the latest time) + 1 minute (doc/api.md section 1.3).

## The knowledge-graph store

`TRIAD_STORE` selects the store of the API: `sqlite` (the default of the code), `virtuoso` or `oxigraph`.
`context_factory` in `main.py` connects the `sqlite/` adapters or the `sparql/` adapters to the same ports. The API, the use
cases, the domain and the frontend do not change. **The contract of the SPARQL adapters is in
[`infrastructure/sparql/README.md`](infrastructure/sparql/README.md)** (the template rule, the write buffer, how to add a
guard, the store fixtures, the known limits). This section gives the overview.

### The parts

| Folder or file | What it does |
|---|---|
| `infrastructure/sparql/client.py` | The driver. `HttpSparqlClient` uses **SPARQLWrapper 2.0.0** (the SPARQL 1.1 Protocol over HTTP): queries go to the anonymous `/sparql`, updates go to `/sparql-auth` with a digest login as `TRIAD_SPARQL_USER`. `EmbeddedSparqlClient` uses **pyoxigraph 0.3.22**: one shared Oxigraph store in the process. One conversion layer gives plain Python values for both. |
| `infrastructure/sparql/terms.py`, `fragments.py`, `paging.py` | The one escape function and the IRIs of the individuals; the shared patterns (`CURRENT`, `PATIENT_VISIBLE`, the assertion view); the pages (`COUNT` and `LIMIT`/`OFFSET` with the same pattern). |
| `infrastructure/sparql/unit_of_work.py`, `ids.py`, `change.py` | The write buffer, the write lock, the commit and the id counters of the meta graph. |
| `infrastructure/sparql/guards.py`, `guards_records.py`, `guards_chat.py`, `guards_directory.py` | The guards: the rules of the SQL triggers and constraints, in Python (see the table below). |
| `infrastructure/sparql/*_repository.py` | The repositories of the eight ports: users, patients, visits, records, chat, audit, directory. |
| `infrastructure/sparql/sparql_log.py` | The SPARQL log (`TRIAD_SPARQL_LOG`): the template of each request and its time, not the values. |
| `application/semantic/build_kg.py` | The build use case (`ensure-kg`, `load-kg`) and its ports. |
| `infrastructure/rdf/kg_export.py` | The export: Morph-KGC 2.10.0 runs the R2RML mapping on a copy of the database, then pyoxigraph writes `triad_kg.nt.gz` and `triad_kg.rdf.gz`. The counts of each predicate and class must equal the SQL counts. |
| `infrastructure/rdf/kg_store.py`, `oxigraph_store.py` | The store adapters of the build: Oxigraph loads the files in the process; Virtuoso loads them with `kg.sh load --no-export` (the bulk loader). |
| `infrastructure/rdf/logical_hash.py` | The hash of the SQLite data for the build marker (the rows, not the file). |
| `infrastructure/rdf/counts.py`, `shacl.py`, `sparql_script.py`, `protocol.py` | The count check after a load, the SHACL check (`validate-kg`), the runner of `kg.sh sparql`, a small SPARQL 1.1 Protocol client for the scripts. |

### The build marker and the start check

`main.py ensure-kg --store STORE` builds the graph of a store only if its build marker is not current. The marker is in
the meta graph. It holds a SHA-256 of a logical dump of the SQLite data, a SHA-256 of the R2RML mapping, the ontology
version and the scope. A build exports the data, clears the meta graph, loads `triad.owl` into the TBox graph and the
data into the ABox graph, compares the triples of each predicate with the export, seeds the id counters from
`sqlite_sequence`, and writes the marker last. **A rebuild deletes the writes that the app made in the knowledge
graph** (the writes of KG mode do not go to SQLite).

`main.py serve --store STORE` runs `ensure-db` and `ensure-kg` first. `create_app` stops with a clear message if the
store has no marker, or a marker of another ontology version or mapping. `GET /api/health` gives `store`,
`ontologyVersion` and `sparqlUrl` (doc/api.md section 1.6).

### The guards: from the triggers to Python

SQLite holds the rules in constraints and triggers. A triple store has no trigger, and an ASK cannot see the triples of
the same unit of work. So the unit of work runs Python guards on the buffered change, under the write lock, before it
sends an update. Each guard raises the same error class as SQLite, so the API gives the same status (409 or 422) and
the same text.

| SQLite rule | Guard (name, file) | Error |
|---|---|---|
| `TR_Assertion_NoUpdate`, `TR_Assertion_NoDelete`, `TR_AuditEvent_NoUpdate`, `TR_AuditEvent_NoDelete` (append-only) | `delete.allow-list` (`guards.py`): no replace, no delete and no new triple on a stored assertion or audit record; only the kinds of `DELETABLE` can be deleted | 422, the text of the trigger |
| FOREIGN KEY (RESTRICT) | `foreign-keys` (`guards.py`): a deleted node is not in use; each IRI of a new triple exists | 409 |
| `TR_Patient_Key_NoUpdate` | `patient.key-is-fixed` (`guards.py`) | 422 |
| `TR_Assertion_Supersede_Check` | `assertion.supersede-check` (`guards_records.py`): not newer (compared as instants), the same patient | 422 |
| `TR_Assertion_One_Head_Per_Entry` | `assertion.one-head-per-entry` (`guards_records.py`) | 422 |
| `TR_Assertion_One_Patient_Per_Message` | `assertion.one-patient-per-message` (`guards_records.py`) | 422 |
| `CHECK (SupersedesId <> Id)` | `assertion.supersedes-not-itself` (`guards_records.py`) | 422 |
| `TR_CareTeamMember_Staff_Check` | `care-team-member.is-staff` (`guards_records.py`) | 422 |
| `TR_Citation_Check` | `citation.check` (`guards_chat.py`) | 422 |
| `TR_AuditEvent_Subject_Check` | `audit-event.subject-check` (`guards_chat.py`) | 422 |
| UNIQUE keys (the 18 `owl:hasKey` keys) | `key.patient`, `key.medication`, `key.identifier`, `key.assertion`, `key.chat-turn`, `key.association` (`guards_directory.py`) | 409 |
| NOT NULL and `CHECK … IN` of the directory tables | `check_row` in `directory_repository.py` | 422 |
| The column types | the write buffer: each value must fit the datatype of its property (`terms.DATATYPES`) | 422 |

The SHACL shapes ([`models/semantic/shapes/`](models/semantic/shapes/README.md)) and `05_constraint_checks.sparql` hold the
same rules for a whole graph. The guards hold them for each write of the app.

### The transaction rule and the single-writer rule

- **No transaction of more than one operation.** Virtuoso does not run one request as one transaction: if a later
  operation fails, the earlier ones stay. Only one `INSERT DATA` (or one `DELETE DATA`) is all or nothing. So a write
  (`with ctx.uow.write() as now:`) puts its changes into a write buffer, and nothing goes to the store before the end
  of the block. The commit runs the guards, checks with one ASK that no new IRI exists, sends the replace and delete
  requests, and then sends **one `INSERT DATA`** with all new triples and the new counter values.
- **Compensation.** If a request fails after others were applied, the commit sends their inverse in the reverse order
  and raises the error. If the inverse also fails, it raises `HalfWriteError` and logs it: the store can then hold a
  half change.
- **One writer process for each store.** The write lock is in the process (a second thread waits up to 30 s). Two
  processes on one Virtuoso can make the same IRI: the ASK before the commit then gives a conflict (409), and the
  counters are seeded again. So run one TRIAD server for each store. A write inside a write raises `NestedWriteError`.

The other differences from SQLite (the text form of a time, the order of times on Virtuoso, the text search) are in
[`infrastructure/sparql/README.md`](infrastructure/sparql/README.md) section 8 and in the root README, section "Store switch".

## Install

You need Python 3.12 and [uv](https://docs.astral.sh/uv/). Run these commands from the root folder of the repository:

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

`requirements.txt` includes `requirements-kg.txt`: the packages of the knowledge graph (Morph-KGC, pyoxigraph, rdflib,
pyshacl, owlrl, SPARQLWrapper) with fixed versions. Keep them together: Morph-KGC 2.10.0 needs pyoxigraph < 0.4 and
rdflib < 7.3. The SQLite path of the app does not import them.

The LLM chat mode needs one more package. The default mode does not need it.
See [The LLM mode](#the-llm-mode).

```sh
uv pip install --python .venv/bin/python -r requirements-llm.txt
```

## Run

The quick way: `./src/scripts/quickstart.sh` (from any folder) makes `.venv`, builds the frontend, the database and the
knowledge graph, runs the fast tests and serves the app on http://127.0.0.1:8000. With no option, the store is Virtuoso
when Docker runs, else Oxigraph. `--store sqlite` gives the app of Milestone 4. Add `--reset-db` to build the database
again, and `--reset-kg` to build the knowledge graph again.

Build the database. The command builds it only if it is missing. It takes about 3 seconds.

```sh
.venv/bin/python src/backend/main.py ensure-db
```

To build the database again, add `--reset-db`.

Start the server on http://127.0.0.1:8000. The command runs `ensure-db` first (and `ensure-kg` for a knowledge-graph store).
The API documentation is at http://127.0.0.1:8000/docs.

```sh
.venv/bin/python src/backend/main.py serve                    # the store of TRIAD_STORE (default: sqlite)
.venv/bin/python src/backend/main.py serve --store oxigraph   # the knowledge graph in Oxigraph
.venv/bin/python src/backend/main.py serve --store virtuoso   # Virtuoso: run kg.sh up and kg.sh init first
```

If `src/frontend/dist/` exists, the server also serves the built frontend. Each path that does not start with `/api` gets `index.html`.

For development, use `dev.sh`. It starts the API with hot reload (port 8000) and the Vite frontend (port 5173). One Ctrl+C stops both.

```sh
./src/scripts/dev.sh
./src/scripts/dev.sh --reset-db
./src/scripts/dev.sh --store oxigraph
```

The other commands of `main.py`:

| Command | What it does |
|---|---|
| `init-db` | Creates the empty schema. |
| `onboard` | Loads the FHIR data into an empty schema. |
| `export-sql` | Writes `dml/02_insert_seed.sql` (the scenario data). |
| `export-kg [--scope all\|scenarios] [--out DIR]` | Writes the knowledge graph with the R2RML mapping (Morph-KGC): `triad_kg.nt.gz`, `triad_kg.rdf.gz` and `kg_report.json` in `TRIAD_KG_DIR` (default `src/backend/data/kg/`). About 10 s for the full data. |
| `ensure-kg --store oxigraph\|virtuoso [--reset-kg]` | Builds the graph of the store if its marker is not current (export, load, count check, id counters, marker). `--reset-kg` builds it again. |
| `load-kg --store oxigraph\|virtuoso [--seed]` | Loads the export of `TRIAD_KG_DIR` (or, with `--seed`, the seed graph `models/semantic/kg/triad_kg_seed.rdf`) with no new export. |
| `validate-kg [--file PATH]` | Checks a graph with the SHACL shapes (default: the seed graph). The exit code is 0 when the graph conforms. |

Virtuoso has its own script, `src/scripts/kg.sh` (`up`, `init`, `load`, `status`, `sparql FILE`, `open`, `down`, `reset`).
See `./src/scripts/kg.sh help` and the root README, section "Triple store setup".

## Settings and secrets (.env)

The backend reads its settings from environment variables. The file `src/backend/.env` can hold them.
`dev.sh` makes this file from [`.env.example`](.env.example) if it is missing (mode 600). Git ignores `.env`.

- The commands of `main.py` and `create_app()` load `.env` at the start (python-dotenv).
- The order is: a variable of the shell, then `.env`, then the default. So `TRIAD_LLM=fake ./src/scripts/dev.sh` works for one run.
- An empty value in `.env` has no effect.
- After you change `.env`, start `dev.sh` again. The hot reload watches only the Python files.
- The tests do not read `.env`. They give their own settings.
- Put the API keys only in `src/backend/.env`, never in `.env.example` and never in `src/frontend/`.

| Variable | Default | What it sets |
|---|---|---|
| `TRIAD_DB_PATH` | `src/backend/data/triad.db` | The SQLite database. A relative path starts at the root folder of the repository. |
| `TRIAD_NOW` | `system` | The clock. `system` uses the clock of the computer, in its local time zone. A fixed ISO 8601 time, for example `2026-10-30T09:00:00-04:00` (`triadNow` in `data/raw/hospital_profile.json`), gives the fixed demo time. The tests, the screenshots and the report use a fixed time. |
| `TRIAD_LLM` | `fake` | The chat mode. `fake` needs no network. `llm` uses LiteLLM. |
| `TRIAD_LLM_MODEL` | `gemini/gemini-3.8-flash` | The LiteLLM model of the `llm` mode. |
| `TRIAD_SQL_LOG` | `on` | The SQL log of the API: `off`, `on` or `params`. See [The SQL log](#the-sql-log). |
| `GEMINI_API_KEY` | — | The key for the Gemini models. Only LiteLLM reads it. For another provider, use the variable of that provider (for example `ANTHROPIC_API_KEY`). |
| `PORT` | `8000` | The port of `serve` and `dev.sh`. Set it in the shell. `dev.sh` reads it before Python starts, so `.env` cannot set it for `dev.sh`. |
| `TRIAD_STORE` | `sqlite` | The data store of the API: `sqlite`, `virtuoso` or `oxigraph`. `--store` of `serve` wins over it. |
| `TRIAD_SPARQL_QUERY_URL` | `http://127.0.0.1:8890/sparql` | The SPARQL query endpoint (no login). |
| `TRIAD_SPARQL_UPDATE_URL` | `http://127.0.0.1:8890/sparql-auth` | The SPARQL update endpoint (digest login). |
| `TRIAD_SPARQL_USER`, `TRIAD_SPARQL_PASSWORD` | `triad`, `triad` | The user of the update endpoint (values for local development; Virtuoso listens on 127.0.0.1 only). After a change of the password, run `kg.sh init`. |
| `TRIAD_SPARQL_LOG` | `on` | The SPARQL log of the API: `off`, `on` (the query text, the time and the rows) or `params` (also the values). |
| `TRIAD_KG_DIR` | `src/backend/data/kg` | The files of the export. Git ignores this folder. |
| `TRIAD_KG_OXIGRAPH_PATH` | `TRIAD_KG_DIR/oxigraph` | The embedded Oxigraph store. |
| `TRIAD_VIRTUOSO_DBA_PASSWORD` | `dba` | The password of the Virtuoso user `dba` (Conductor and `kg.sh`). Virtuoso takes it only at the first start of an empty volume: after a change, run `kg.sh reset` (this deletes the data of Virtuoso) and `kg.sh up`. |
| `KG_HTTP_PORT` | `8890` | The port of Virtuoso on 127.0.0.1. The default endpoint URLs use it. After a change, run `docker rm -f triad-virtuoso` and `kg.sh up`. |

## The SQL log

The API logs each SQL statement of a request, with its time. `TRIAD_SQL_LOG` sets the mode: `off`, `on` (the default) or `params`.
The lines go to stderr (logger `triad.sql`). `dev.sh` shows them with the prefix `[api]`:

```text
[api] [sql] GET /api/patients/1/chart  2.28 ms  8 rows  SELECT a.Id, a.ClinicalEntryId AS EntryId, a.MessageId, ...
[api] [sql] GET /api/patients/1/chart  0.19 ms  0 rows  COMMIT
[api] [sql] GET /api/patients/1/chart 200: 10 statements, 7.0 ms in SQL, 14.4 ms in all.
```

- Each statement gets one line: the request, the time, the number of rows (read or changed) and the SQL on one line.
- The time includes all the work of the statement. The wrapper reads all the rows before it stops the timer.
- At the end of each `/api` request, one line gives the status, the number of statements, the time in SQL and the time in all.
- Only the API connections use the log (`infrastructure/sqlite/sql_log.py`). The commands of `main.py` (for example `ensure-db`) do not.
- Privacy: `on` does not show the bound values and the query string, because they can be patient names and dates of birth.
  `params` shows them. The data of TRIAD is synthetic, but a real system must not log them.
- The tests use `off`. A test that checks the log sets the mode itself.

With a knowledge-graph store, `TRIAD_SPARQL_LOG` does the same for each SPARQL request (`infrastructure/sparql/sparql_log.py`).
`on` shows the template of the request, not the values.

## The LLM mode

1. Install the package: `uv pip install --python .venv/bin/python -r requirements-llm.txt`.
2. Get a Gemini API key at https://aistudio.google.com/apikey. The Gemini models have a free tier.
3. In `src/backend/.env`, set `TRIAD_LLM=llm` and `GEMINI_API_KEY=<your key>`.
4. Start `dev.sh` again. The chat shows "Mode: llm". A new chat session records the mode and the model.

For Claude, set `TRIAD_LLM_MODEL=anthropic/claude-opus-5-5` and `ANTHROPIC_API_KEY`.
For a model with a higher free-tier limit, use `gemini/gemini-3.5-flash-lite`.

- At the start, the server checks that `litellm` is installed, that the key of the model is set, and that the model can call tools
  (`litellm.supports_function_calling`). If not, it prints one line that tells what is missing, and it runs in the fake mode.
  The new sessions then show "Mode: fake". If the tool check itself fails, the server does not stop the llm mode.
- If a turn fails (for example, the free-tier limit), that turn uses the fake model, and the log gets one warning line.
  The line names only the error class, never the key.
- On the free tier, Google can use the prompts to improve its products. The data of TRIAD is synthetic.
  Do not put real patient data in the prototype.
- The free tier has a limit of requests per minute and per day. See https://aistudio.google.com/rate-limit.

**How the model selects a tool.** Each tool of `application/assistant/tools.py` has a name, a description and a JSON Schema
of its parameters (for example `get_allergies` with `substance`). LiteLLM sends them to the model with
`tools=[{"type": "function", "function": {...}}]` and `tool_choice="auto"`. The model reads the question and the descriptions,
and it gives tool calls: a name and JSON arguments (`message.tool_calls`). The backend checks each call against the schema,
runs the tool, and sends the result back as a message with `role: "tool"`. Then the model writes the answer.
The loop has at most 4 rounds (`application/assistant/agent.py`).

**The user and the patient are bound, not parameters.** The tools are closures over the user of the request (`X-Triad-User`)
and the patient of the chat session. The model cannot give a patient, a user or an id:

```python
def make_tools(ctx, actor, patient):        # actor: from the X-Triad-User header; patient: from the chat session
    def get_allergies(substance=None):      # the model calls this tool with words only
        return ctx.records.allergies(patient.id, words=words_of(substance), visible_only=actor.is_patient,
                                     limit=12)
```

- Each schema has `additionalProperties: false`. A call with an extra parameter (for example `patientId`), a wrong type or
  a bad enum value gets an error text, and no query runs.
- The tools call the repositories in the process (no HTTP call to the server). A patient gets only the patient-visible items.

**References in place of ids.** Each item of a tool result gets a reference (`E1`, `E2`, ...) for this turn only.
The backend keeps the map from the reference to `Assertion.Id`. The model sees the reference, the category, the display,
the statement, the verification, the author, the date and the subtype details. It never sees an id, the patient name,
the date of birth or an identifier. The model writes `[E1]` after each fact. The backend removes the references from the text
and cites their assertions. It drops an unknown reference. If the text has no reference, the turn cites all items of the tools.

**The fallback.** If the model fails, or it gives no final text in 4 rounds, the fake model does the turn again with the same
tools. The fake model selects one tool from the keywords of the question (`application/assistant/rule_model.py`), and the
templates of `application/assistant/answers.py` write the answer from the tool result.

## The Care Assistant

- An "ask" turn runs the loop of `application/assistant/agent.py`. The model selects the tools, and each tool is one targeted
  query (a WHERE clause on the patient and the filters, `ORDER BY`, `LIMIT 12`). No tool reads the full chart.
  The fake model and the LLM use the same tools and the same repository methods (SQL on SQLite, SPARQL on the knowledge graph).
  See [The LLM mode](#the-llm-mode) and `doc/api.md` section 3.5.
- The assistant cites only the assertions that the tools returned in that turn. Each card of an answer comes from one Citation row of the turn.
- The fake model knows these questions: allergies, medications, the plan, lab results, vital signs, diagnoses, visits and recommendations (for example "What did the nurse recommend?").
- A "tell" turn (a statement, not a question) goes to a fact extractor. Each fact becomes an assertion with Source = Agent and Verification = Unconfirmed, in one message with Channel = Chat. If the extractor finds no fact, the backend writes no message.
- In the `llm` mode, one more LiteLLM call extracts the facts of a "tell" turn (JSON that the code checks). If the call fails, the turn uses the fake extractor.
- Only `infrastructure/llm/litellm_client.py` imports `litellm`.

## Tests

Run the tests from the root folder of the repository:

```sh
.venv/bin/python -m pytest -q                                   # all tests (about 1,500, about 6 min); the Virtuoso tests are skipped
.venv/bin/python -m pytest -q -m "not slow and not virtuoso"    # the fast tests (about 1,200, about 1.5 min; quickstart.sh runs these)
.venv/bin/python -m pytest -q -m "not kg"                       # SQLite only
.venv/bin/python -m pytest -q -k oxigraph src/backend/tests/integration/test_store_users.py   # one file, Oxigraph only
```

**The markers** (`pytest.ini`): `slow` (the full Synthea data), `kg` (a knowledge-graph parameter of a store fixture),
`virtuoso` (needs a running Virtuoso), `stores(...)` (run a test only on these stores).

**The tests on each store.** The store fixtures `store` (the scenario data), `planted_store` (the planted data of
`tests/fixtures/plant.py`) and `full_store` (the full data, `slow`) run each test on each store of `TRIAD_TEST_STORES`
(default `sqlite,oxigraph`). The first `full_store` test builds the full graph (about 15 s) and keeps it in
`.pytest_cache/d/triad-kg/`; each test gets a new copy. See [`infrastructure/sparql/README.md`](infrastructure/sparql/README.md) section 6.

**The opt-in run on Virtuoso.** The Virtuoso tests run only when `TRIAD_TEST_STORES` names `virtuoso`, and they are
skipped when `TRIAD_SPARQL_QUERY_URL` does not answer. **They replace the TRIAD graphs of the container.**

```sh
./src/scripts/kg.sh up && ./src/scripts/kg.sh init
TRIAD_TEST_STORES=sqlite,oxigraph,virtuoso .venv/bin/python -m pytest -q -m virtuoso
.venv/bin/python src/backend/main.py ensure-kg --store virtuoso   # after the tests: build the graph of your database again
```

The SQL = SPARQL tests on Virtuoso need the graph of a known database in the ABox graph. See
[`models/semantic/sparql/README.md`](models/semantic/sparql/README.md), section "SQL = SPARQL: the tests"
(`TRIAD_KG_TEST_DB`).

| Test | What it checks |
|---|---|
| `tests/unit/test_access.py` | The permission matrix of `USER_FLOWS.md` section 2 (parametrized) and the supersede rules. |
| `tests/unit/test_rules.py` | The patient-visible rule, the author label, the head check, the plan visit and the clock. |
| `tests/unit/test_assistant.py` | Ask or tell, the intents, the tool call of the fake model and the fake fact extractor. |
| `tests/integration/test_assistant_tools.py` | Each assistant tool = the old Python selection on the full chart (Patient A, Patient B, the largest patient), no tool parameter is a patient, a user or an id, a call that is not correct runs no query, and a scripted fake `litellm`: the references and the citations, no id or patient data to the model, the patient-visible rule, the fallback and no full-chart query in a turn. |
| `tests/integration/test_hospital_visit.py` | The hospital-visit journey of `USER_FLOWS.md` section 3 (Use cases 0 to 9) through the API. |
| `tests/unit/test_settings.py` | The `.env` loader (the shell wins, empty values set nothing), the database path, the store settings, the `.env.example` files (no key values) and the start check of the LLM mode. |
| `tests/integration/test_pages.py` | The pages of each list endpoint: the slices, `total`, the order, the 422 for a bad `limit` or `offset`, the chart `counts` and search, the SQL patient-visible rule = `rules.py` = Q12 for each patient, and Q14. |
| `tests/integration/test_api.py` | Q12 = the patient chart, cards = Citation rows, the denied audit records, the errors, the LLM fallback and the start check, no key text in a response, the log or the database, the directory and the speed of the chart. |
| `tests/integration/test_schema.py`, `test_onboard.py` | The SQL scripts 01 to 05 and the FHIR onboarding. |
| `tests/unit/test_ontology.py` | The build of `triad.owl` (the same bytes), its checks (each check stops on a known error) and the counts of `ontology.md`. |
| `tests/integration/test_kg_export.py` | The R2RML mapping, the export files, the counts per predicate and per class, and the seed graph. |
| `tests/integration/test_kg_shacl.py` | The SHACL shapes: the seed graph conforms, and each of the 26 cases of `05_constraint_violations.sql` (and one error for each other rule) gives its violation. |
| `tests/integration/test_kg_queries.py` | SQL = SPARQL: Q1–Q14b on the scenario, planted and full data, on Oxigraph and (opt-in) Virtuoso; QA, QC, QD; `04` = SQL `04`; the checks of `05`. |
| `tests/integration/test_build_kg.py` | `ensure-kg`, `load-kg`, `validate-kg`, the build marker and the start check. |
| `tests/integration/test_store_*.py` | Each port on each store: the same results as SQLite on the same data, the writes and the guards. |
| `tests/integration/test_sparql_unit_of_work.py`, `test_sparql_fragments.py`, `test_sparql_log.py` | The write buffer, the commit and the compensation; the shared SPARQL patterns = the SQL fragments; the SPARQL log. |
| `tests/unit/test_sparql_client.py`, `test_sparql_terms.py`, `test_sparql_paging.py` | The driver (against a fake endpoint that answers like Virtuoso: digest, HTTP 500, `X-SPARQL-MaxRows`), the escape function and the IRIs, the pages. |
| `tests/integration/test_kg_virtuoso.py` | The client on a running Virtuoso (opt-in): a round trip on the scratch graph with the digest login. |
| `tests/unit/test_kg_scripts.py`, `test_run_scripts.py`, `test_dependency_rule.py` | `kg.sh` and the split rule of `kg.sh sparql`; `quickstart.sh` and `dev.sh` (syntax, help, a wrong store); only `infrastructure/`, `models/semantic/` and the tests import the RDF packages. |

The tests do not need the network or `litellm`. The integration tests use a copy of the database, so they do not change `data/triad.db`.

## Folders

```
src/backend/
  main.py            the composition root: the commands and create_app()
  domain/            records.py, views.py, enums.py, errors.py, access.py, rules.py
  application/       ports.py, context.py, guard.py and the use cases; chat/, assistant/, onboarding/, semantic/
  infrastructure/    config.py, clock.py, ids.py; sqlite/, sparql/, rdf/, fhir/, llm/
  api/               app.py, actor.py, errors.py, schemas.py, routers/
  models/            er/, relational/, semantic/
  data/              the FHIR source data, the database (triad.db) and the knowledge graph (kg/); git ignores the last two
  tests/             unit/, integration/, fixtures/ (the store fixtures and the planted data)
```

This backend was written with help from Claude Code (an AI tool). The team checked the code and the tests.
