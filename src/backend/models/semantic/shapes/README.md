# SHACL shapes of the TRIAD knowledge graph (Milestone 5)

This folder holds the W3C SHACL shapes of the knowledge graph (plan 5, section 3.4).
The shapes hold the closed-world rules of the SQLite schema (`../../relational/sql/ddl/01_create_tables.sql`): NOT NULL, `CHECK … IN`, the foreign keys, the UNIQUE constraints, the CHECKs across columns and the triggers.
OWL cannot hold these rules, because OWL uses the Open World Assumption: a missing triple is unknown, not an error (`../ontology.md`, section 8).

| File | Content |
|---|---|
| `triad.shacl.ttl` | The shapes (Turtle). Part 1 is generated. Part 2 (after the `END OF THE GENERATED PART` line) is hand-written. |
| `build_shapes.py` | Writes part 1 from `../triad.ttl`, `../vocabulary.py` and the DDL. It keeps part 2 as it is. |

**Counts:** 29 node shapes (one for each of the 28 classes, and one for the issuer rule), 181 property shapes, 28 SHACL-SPARQL constraints (18 keys and 10 rules of the triggers and the CHECKs).
Each shape and constraint has an `sh:message` that names the rule. The comment above it names the SQL constraint or trigger that it replaces.

## The kinds of rules

| SQL rule | SHACL construct | Shapes |
|---|---|---|
| NOT NULL | `sh:minCount 1` | `shape:<Class>-<property>` |
| One value in a cell (a Functional property) | `sh:maxCount 1` | the same |
| The column type and the date CHECKs | `sh:datatype` (`xsd:date` for the 4 date-only properties; OWL 2 has no `xsd:date`) | the same |
| `CHECK … IN` (17 value sets) | `sh:in` | the same |
| `CHECK (Seq >= 1)`, `CHECK (Rank >= 1)` | `sh:minInclusive 1` | `shape:Assertion-seq`, `shape:ChatTurn-seq`, `shape:Citation-rank` |
| FOREIGN KEY | `sh:class` and `sh:nodeKind sh:IRI`; a reverse FK also on the inverse path (`shape:<Class>-inverse-<property>`) | the same; `shape:language-subject` for StaffLanguage |
| UNIQUE (18 `owl:hasKey` keys) | SHACL-SPARQL: another node of the class has the same key values | `shape:UK_<constraint>` |
| `UK_Assertion_SupersedesId` | `sh:maxCount 1` on `^triad:supersedes` | `shape:Assertion-inverse-supersedes` |
| `Role`, `Category` and the subtype tables (ISA, disjoint and total) | exactly one subtype: `sh:qualifiedValueShape` on `rdf:type`; each subtype also has the parent type (`sh:hasValue`) | `shape:Staff-subtype`, `shape:ClinicalEntry-subtype`, `shape:<Subtype>-type` |
| `CHECK (EndDate >= StartDate)` | `sh:lessThanOrEquals` (it compares the instants of two times with different offsets) | `shape:Visit-dates`, `shape:VisitLocation-dates`, `shape:WorksIn-dates` |
| `CHECK (StaffId IS NOT NULL OR Origin = 'Patient')` | `sh:or` | `shape:MessageIssuerShape` |
| `CHECK (SupersedesId <> Id)`; no cycle (new) | SHACL-SPARQL | `shape:Assertion-supersedes-not-reflexive`, `shape:Assertion-supersedes-no-cycle` |
| `TR_Assertion_Supersede_Check` | SHACL-SPARQL | `shape:Assertion-supersedes-not-newer`, `shape:Assertion-supersedes-same-patient` |
| `TR_Assertion_One_Head_Per_Entry` | SHACL-SPARQL: at most one assertion about the entry that nothing supersedes | `shape:ClinicalEntry-one-head` |
| `TR_Assertion_One_Patient_Per_Message` | SHACL-SPARQL | `shape:Message-one-patient` |
| `TR_CareTeamMember_Staff_Check` | SHACL-SPARQL | `shape:CareTeamMember-staff` |
| `TR_Citation_Check` | SHACL-SPARQL | `shape:Citation-assistant-turn`, `shape:Citation-patient` |
| `TR_AuditEvent_Subject_Check` | SHACL-SPARQL | `shape:AuditEvent-subject` |
| ER participation and the new rule of Milestone 5 (no column) | `sh:minCount 1` | `shape:Message-contains`, `shape:ClinicalEntry-inverse-about`, `shape:Staff-inverse-ofStaff` |

**No shape:** the append-only triggers (`TR_Assertion_NoUpdate`, `TR_Assertion_NoDelete`, `TR_AuditEvent_NoUpdate`, `TR_AuditEvent_NoDelete`) and `TR_Patient_Key_NoUpdate`. A graph has no "update" event. The SPARQL delete helper and the use cases hold these rules (plan 1.7 and 5.4).
`UK_StaffLanguage_StaffId_Language` needs no shape: a graph holds each triple once.

## Run the shapes

From the root folder of the repository, with the Python of the project (`requirements-kg.txt`):

```bash
PYTHONPATH=src/backend .venv/bin/python -m infrastructure.rdf.shacl                   # the seed graph
PYTHONPATH=src/backend .venv/bin/python -m infrastructure.rdf.shacl path/to/graph.ttl # another graph (.rdf, .ttl, .nt, also .gz)
.venv/bin/python src/backend/models/semantic/shapes/build_shapes.py                   # write part 1 again
.venv/bin/python src/backend/models/semantic/shapes/build_shapes.py --check           # stop if part 1 is old
.venv/bin/python -m pytest -q src/backend/tests/integration/test_kg_shacl.py
```

The command prints the violations and the count for each rule. Its exit code is 0 when the graph conforms, 1 when it does not conform, and 2 when it cannot run.
In Python, `infrastructure.rdf.shacl.validate(graph_or_file)` gives the result: `conforms`, and a list of (focus node, shape or constraint, message).

**The full graph uses the SPARQL checks, not the shapes.** pyshacl keeps all of the graph in memory and runs each SPARQL constraint once for each focus node. On the full graph (1.3 M triples) it needs about 6 minutes and 3.5 GB of memory (the measurement of plan 3.4). On the seed graph (1,125 triples) it needs about 0.2 s (`shacl.py` gives pyshacl a view of the data that parses each SPARQL text once; without it, 0.5 s). So the tests validate the seed graph only, and the full graph uses `05_constraint_checks.sparql` (plan 4.4) in the triple store.

**Limits of rdflib (pyshacl reads the data with rdflib 7.2):**
- rdflib reads some texts that are not valid `xsd:dateTime` values as valid, for example `"2026-10-30 10:00"`. SQLite `julianday()` also accepts this text. All times of the data have the full form with an offset (checked on the dev database).
- rdflib changes the text of some literals to a canonical form: `Z` becomes `+00:00`, and `.165` becomes `.165000`. So two texts of the same time are one value for the shapes. This can change the result of one rule only: the key of VisitLocation (`startDate` is a part of it). SQLite compares the texts.

## The cases of 05_constraint_violations.sql

`../../relational/sql/dml/05_constraint_violations.sql` has 26 cases. Each case must fail in SQLite. The test `test_kg_shacl.py` (`SQL_CASES`) plants the RDF form of each case in a copy of the seed graph and expects that the result includes the (focus node, shape) pair. The test also checks that this table has the cases of the SQL file in the same order.

| # | SQL case | RDF form | Shape or constraint (focus node) |
|---|---|---|---|
| 1 | duplicate patient key (Name, DateOfBirth) | a second patient with the same name and date of birth | `shape:UK_Patient_Name_DateOfBirth` (both patients) |
| 2 | duplicate patient identifier | a second identifier with the same system and value | `shape:UK_PatientIdentifier_System_Value` (both identifiers) |
| 3 | a visit for a patient that does not exist | `triad:hasVisit` from an IRI with no type | `shape:Visit-inverse-hasVisit`, `sh:class` (the visit) |
| 4 | ISA mismatch (a Nurse row for a staff member whose role is Doctor) | a doctor with the type `triad:Nurse` too | `shape:Staff-subtype`, qualified max count (the staff member) |
| 5 | a subtype row with the wrong role value | the row gives a second subtype; `Role` gives no triple | `shape:Staff-subtype` (the staff member) |
| 6 | a nurse designation that is not in the value set | `triad:designation "Chief"` | `shape:Nurse-designation`, `sh:in` |
| 7 | a message with no issuer that does not come from the patient | no `triad:issues`, `triad:origin "Staff"` | `shape:MessageIssuerShape`, `sh:or` |
| 8 | a channel that is not in the value set | `triad:channel "Pigeon"` | `shape:Message-channel`, `sh:in` |
| 9 | a visit that ends before it starts | `triad:endDate` before `triad:startDate` | `shape:Visit-dates`, `sh:lessThanOrEquals` |
| 10 | a visit class that is not in the value set | `triad:visitClass "XYZ"` | `shape:Visit-visitClass`, `sh:in` |
| 11 | a date of birth that is not a date | `"not a date"^^xsd:date` (an ill-typed literal) | `shape:Patient-dateOfBirth`, `sh:datatype` |
| 12 | change an assertion (assertions are append-only) | no RDF form: a graph has no update event | — (the SPARQL delete helper and the use cases) |
| 13 | delete an assertion (assertions are append-only) | no RDF form: a graph has no delete event | — (the allow-list of the SPARQL delete helper) |
| 14 | a new claim about an entry that has a current assertion, without superseding it | a second assertion about the entry that nothing supersedes | `shape:ClinicalEntry-one-head` (the entry) |
| 15 | supersede an assertion that is newer than the new assertion | `triad:supersedes` to a newer assertion | `shape:Assertion-supersedes-not-newer` (the new assertion) |
| 16 | a second assertion that supersedes the same assertion (Supersedes is one-to-one) | two assertions with `triad:supersedes` to one assertion | `shape:Assertion-inverse-supersedes`, `sh:maxCount` (the old assertion) |
| 17 | supersede an assertion of another patient | `triad:supersedes` to an assertion about another patient | `shape:Assertion-supersedes-same-patient` (the new assertion) |
| 18 | one message with assertions about two patients | `triad:contains` to assertions about two patients | `shape:Message-one-patient` (the message) |
| 19 | a care-team member that is not a staff member | a member value that is no staff identifier | `shape:CareTeamMember-staff` (the member) |
| 20 | a citation from a user turn (only the assistant cites) | `triad:byTurn` to a user turn | `shape:Citation-assistant-turn` (the citation) |
| 21 | a citation of an assertion about another patient | `triad:citedAssertion` about another patient | `shape:Citation-patient` (the citation) |
| 22 | an audit record of a chat turn with another patient as subject | `triad:inTurn` with another subject | `shape:AuditEvent-subject` (the audit event) |
| 23 | change an audit record (audit records are append-only) | no RDF form: a graph has no update event | — (the SPARQL delete helper and the use cases) |
| 24 | change the key of a patient (the logs keep Name and DateOfBirth as values) | no update event; the state after the change breaks the citation rule | `shape:Citation-patient` (the existing citation); the use case and the adapter refuse the change |
| 25 | delete a patient who has visits (the app shows 409) | the triples of the patient go (also `triad:hasVisit`) | `shape:Visit-inverse-hasVisit`, `sh:minCount` (each visit) |
| 26 | delete a department that has staff (the app shows 409; journey Use case 8) | the triples of the department go | `shape:WorksIn-atDepartment`, `sh:class` (each role in the department) |

The test also plants one error for each of the other rules: each NOT NULL, each value set, each datatype, each foreign key, each single value, each subtype rule, each of the 18 keys, the date pairs with mixed offsets and milliseconds, a supersedes loop and cycle, a message or an entry with no assertion, a staff member with no department, and a language of a node that is not a staff member.
