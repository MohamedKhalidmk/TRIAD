# TRIAD SQL scripts (SQLite 3.43 or later)

The scripts are in two folders, by the class of SQL statement (course manual §4.2):

- **`ddl/`**: Data Definition Language. These statements define the schema (`CREATE TABLE`, `CREATE INDEX`, `CREATE TRIGGER`).
- **`dml/`**: Data Manipulation Language. These statements add, read, change and delete rows (`INSERT`, `SELECT`, `UPDATE`, `DELETE`). The manual puts `SELECT` with DML, and we do the same.

The number at the start of each file name gives the run order.

| Order | File | Class | What it does |
|---|---|---|---|
| 1 | `ddl/01_create_tables.sql` | DDL | Creates the 29 relations, their keys and checks, 14 indexes and 11 triggers. Sets `PRAGMA user_version`. |
| 2 | `dml/02_insert_seed.sql` | DML | Inserts the scenario data into all 29 tables. `python src/backend/main.py export-sql` makes this file. Do not edit it by hand. |
| 3 | `dml/03_select_queries.sql` | DML (query) | Q1–Q14: the SELECT queries of the report. Q14 is one page of a chart (`LIMIT 25 OFFSET 25`) and its `COUNT(*)`, as the API runs them. |
| 4 | `dml/04_update_delete.sql` | DML | INSERT, UPDATE and DELETE examples. Each statement must succeed. |
| 5 | `dml/05_constraint_violations.sql` | DML | Statements that must fail. Each case shows the error that a key, check or trigger gives. |

## Run the scripts

Run these commands from this folder (`src/backend/models/relational/sql`):

```sh
sqlite3 triad.db < ddl/01_create_tables.sql
sqlite3 triad.db < dml/02_insert_seed.sql
sqlite3 -header -column triad.db < dml/03_select_queries.sql

# 04 and 05 change the data. Run them on a copy.
cp triad.db demo.db  && sqlite3 demo.db  < dml/04_update_delete.sql
cp triad.db check.db && sqlite3 check.db < dml/05_constraint_violations.sql
```

The full data set (112 Synthea patients) does not come from these scripts. The onboarding step
(`python src/backend/main.py ensure-db`) runs `ddl/01_create_tables.sql` and then loads the FHIR data.
The queries in `dml/03_select_queries.sql` also run on that database.

The mapping from the ER diagram to these relations is in `../relations.md`.
