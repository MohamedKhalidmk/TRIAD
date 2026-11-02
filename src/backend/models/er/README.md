# TRIAD ER model (Milestone 4)

This folder holds the conceptual model of TRIAD: the entity-relationship (ER) diagram and these notes.
The Milestone 2 draft stays in `assets/designing_erd/` as a record.

| File | Content |
|---|---|
| `TRIAD_ERD.drawio` | The diagram. It has one page: the clinical core, the authorship model, the agent layer and the audit log. |
| `TRIAD_ERD.pdf` | The diagram as PDF. |
| `TRIAD_ERD.png` | The diagram as PNG (2x scale). |
| `build_erd.py` | The script that makes `TRIAD_ERD.drawio`. It also checks that the diagram is a tree. |

To make the diagram again:

```bash
python3 src/backend/models/er/build_erd.py
cd src/backend/models/er
drawio -x -f pdf --crop -o TRIAD_ERD.pdf TRIAD_ERD.drawio
drawio -x -p 1 -f png -s 2 -o TRIAD_ERD.png TRIAD_ERD.drawio
```

## 1. How to read the diagram

| Symbol | Meaning |
|---|---|
| Box | Entity. |
| Double box | Weak entity. Its owner identifies it. |
| Diamond | Relationship. |
| Double diamond | Identifying relationship of a weak entity. |
| Oval | Attribute. |
| Double oval | Multivalued attribute. |
| Ovals on an oval | Composite attribute. |
| Solid underline | Key. |
| Dashed underline | Partial key. It identifies a weak entity together with the key of its owner. |
| Triangle (ISA) | Subtypes. The triangle points toward the subtypes. Both hierarchies are disjoint and total. |
| Crow's feet | Cardinality. Two bars: exactly one. Circle and bar: zero or one. Circle and crow's foot: zero or many. Bar and crow's foot: one or many. |
| Grey | TRIAD contribution: authorship, revision and the agent layer. |
| *Identifier* | A composite attribute: System + Value. It has the same structure as the FHIR `Identifier`. |
| *Address* | A composite attribute: Street, City, Region, PostalCode, Country. |

## 2. Design rules

1. **The diagram is a tree.** There is exactly one path between any two entity sets. Thus no fact can be reached by two paths that could disagree. The only exception is the unary relationship Supersedes, which links Assertion to Assertion (as in Milestone 2). `build_erd.py` checks this rule. If a new relationship closes a loop, the script stops.
2. **Keys follow FHIR.** An entity that has a FHIR resource has the key *Identifier* (System, Value). If the source resource has no identifier, the key is (source base URL, logical id). Two entities have other keys: Patient (Name + DateOfBirth) and Medication (Code + CodeSystem).
3. **An entity that has no real-world key gets an identifier that the hospital assigns.** Milestone 2 made such entities weak. Milestone 4 does not (see comment 3).
4. **Only two entities are weak:** Assertion (owned by Message) and ChatTurn (owned by ChatSession). Their partial key is *Seq*, the position in the owner.
5. **Logs keep values, not relationships.** A chat session and an audit record keep the user and the patient as attribute values (User, Actor, Subject). A log must stay correct when a row changes. These values also add no loop to the tree.
6. **No foreign keys at the conceptual level.** Relationships show all associations.
7. **Names are singular.** Each relationship has a unique name.
8. **Each message has at least one assertion** (`Contains` is total on the Message side). A message reaches its patient only through its assertions. Thus a message with no assertion would have no patient. An intake note becomes an Observation entry (chief complaint). If the agent finds no fact in a chat turn, no message is made.
9. **One entry, many claims.** An entry is recorded during the visit where it first appears. A later claim about the same fact (confirm, refute, a patient report, a test result) is a new assertion about the same entry. It needs no new visit. A claim with different content (a new code, for example asthma → heart failure, or a new care-team membership) is a new entry in the current visit. Its assertion supersedes the old one. FHIR versions of one resource (`meta.versionId`) become assertions about one entry.
10. **Each entry has at most one current assertion.** A new assertion about an entry that has a current assertion must supersede it.
11. **Current care team.** A care-team entry is current when its assertion is current (nothing supersedes it) and its Status is "active". A staff member can open a chart only if a current care-team entry of that patient has them as a Member.
12. **Values that hold a key are checked.** A Member must match exactly one Staff Identifier. The Name and DateOfBirth of a patient (the key that logs keep) cannot change after registration. The Subject of an audit record that points to a chat turn must equal the Subject of its chat session.
13. **WorksIn and TakesPlaceIn can repeat a pair.** A person can have two roles in one department (the key includes RoleCode). A visit can go back to a location at a later time (the key includes StartDate).

## 3. Changes from Milestone 2

### Comment 1: "Lack of sufficient attributes like for Department or Staff or MOA"

Each new attribute has a source field in FHIR R4. The onboarding step fills it from the data.

| Entity | Milestone 2 | Milestone 4 |
|---|---|---|
| Department | Name | Identifier, Name, Type, PhoneNumber, Email, Address |
| Staff | EmployeeNumber, Name | Identifier, Name, Sex, Email, PhoneNumber, Active, Role, Language (multivalued) |
| Doctor | LicenseNumber | LicenseNumber, Qualification |
| Nurse | LicenseNumber | LicenseNumber, Designation |
| MOA | (none) | CertificationNumber, Desk, PhoneExtension |
| Location | Name, Type | Identifier, Name, Type, PhysicalType, PhoneNumber, Address |

We also added attributes to other entities: Visit (Type, Reason), ClinicalEntry (Display, Text), Diagnosis (AbatementDate, ClinicalStatus, Severity), Allergy (Type, AllergyCategory, ClinicalStatus), LabOrder (Priority, Specimen), Prescription (Status) and Medication (Manufacturer).

### Comment 2: "Staff issue Message and a Message has Assertion … the identifying entity set for the weak Assertion is Message"

- We removed `Asserts` (Staff–Assertion) and `ExtractedFrom` (Assertion–Message).
- We added `Issues` (Staff–Message). A staff member issues zero or many messages.
- We added the identifying relationship `Contains` (Message–Assertion). This is the professor's "has". Message is now the owner of the weak entity Assertion. The partial key of Assertion is *Seq*, its position in the message.
- The author of an assertion is now the sender of its message. Each assertion takes its authorship from its message.
- A patient can also send a message through the app. Such a message has no issuer, and its Origin is "Patient". The patient comes from the entries of its assertions. We do not add a Patient–Message relationship, because it would close a loop.

### Comment 3: "The ternary Visit-Location-ClinicalEntry … the notation should not be like weak entity sets"

- Visit and ClinicalEntry are now **strong** entities. They have single boxes. `Has` and `During` have single diamonds.
- Visit stands in for the ternary relationship. Its binary relationships are `Has` (Patient), `TakesPlaceIn` (Location) and `During` (ClinicalEntry).
- The key of both entities is *Identifier* (FHIR `Encounter.identifier` or the resource id).
- **The data shows that the old partial keys are false.** In the Synthea sample, 27 (Patient, StartDate) pairs of Visit repeat. 291 (Visit, Code, RecordedAt) triples of ClinicalEntry repeat (207 Observation and 84 MedicationRequest). The old keys are now plain attributes.
- Each entry is recorded during exactly one visit. Phone calls, memos and app reports are visits too, as in Milestone 2 (Class: phone, virtual). The onboarding step puts a Synthea allergy, which has no encounter, in the visit that contains its record date (101 of 101 match).

### Other changes (with the reason)

| Change | Reason |
|---|---|
| The Patient key became Name + DateOfBirth. Identifier became multivalued. | Team decision. PHN is one identifier among others (MRN, SSN, licence numbers). We do not make up a PHN. |
| `WorksIn` became many-to-many with RoleCode, Specialty, StartDate and EndDate. | This is FHIR `PractitionerRole`. A person can have roles in more than one department. |
| The Message key became *Identifier*. Message got Origin. | Two staff can send on one channel at the same time, so Channel + SentAt is not a key. Origin keeps the source of the information (patient, staff, other clinic, PharmaNet, lab). |
| Assertion: Role became **Intent** (Report, Recommendation, Decision). | The role of the author now comes from Issues → Staff. A Role column would repeat that data. Intent keeps a patient report, a nurse recommendation and a doctor decision apart. |
| Assertion got Verification (from Diagnosis) and Statement. | A revision is per claim, so the verification belongs to the claim. |
| The Medication key became Code + CodeSystem. | FHIR `Medication.code`. It holds RxNorm codes (Synthea) and DIN codes (Canada). |
| New ClinicalEntry subtype: **CareTeam**, with the multivalued composite attribute Member (Identifier, Role). | FHIR `CareTeam` is a clinical resource. The access rule uses it: only staff on the current care team of a visit can open the chart. A change to the team is a new assertion that supersedes the old one, so each change has an author and a history. Member keeps the staff identifier as a value (a FHIR reference by identifier), because a Staff–CareTeam relationship would close a loop. |
| New: the agent layer (ChatSession, ChatTurn, `Includes`, `Cites`). | The Care Assistant keeps its conversations. Each answer cites the assertions that it used, so a wrong answer can be traced to a relationship. A "tell" turn creates a message. The answer to it cites the new assertions. |
| New: AuditEvent, with `InTurn` (ChatTurn). | FHIR `AuditEvent`. It records who read or changed the data of a patient, and the denied attempts. |
| Removed for now: a lineage store (a copy of each source FHIR resource in the database). | The model stays small. The source FHIR files stay in `src/backend/data/`, so the data can be loaded again. The Identifier of each row keeps the FHIR identifier or id of its source. |

## 4. Relationships and cardinalities

| Relationship | Entities | Reading |
|---|---|---|
| WorksIn | Staff – Department | Many-to-many (PractitionerRole), with RoleCode, Specialty, StartDate and EndDate. Each staff member works in one or many departments. |
| Issues | Staff – Message | A staff member issues zero or many messages. A message has zero or one issuer. With no issuer, Origin is "Patient". |
| Contains | Message – Assertion | Identifying. A message contains one or many assertions. Each assertion belongs to exactly one message. |
| About | Assertion – ClinicalEntry | Each assertion is about exactly one entry. Each entry has one or many assertions. |
| Supersedes | Assertion – Assertion | Unary. An assertion replaces zero or one assertion. Zero or one assertion replaces it. |
| During | ClinicalEntry – Visit | Each entry is recorded during exactly one visit. A visit has zero or many entries. |
| Has | Patient – Visit | A patient has zero or many visits. Each visit has exactly one patient. |
| TakesPlaceIn | Visit – Location | Many-to-many, with StartDate and EndDate. |
| Prescribes | Prescription – Medication | Each prescription names exactly one medication. |
| Includes | ChatSession – ChatTurn | Identifying. A session includes zero or many turns. |
| Cites | ChatTurn – Assertion | Many-to-many, with Rank. An answer cites the assertions that it used. |
| InTurn | AuditEvent – ChatTurn | An audit record can point to the chat turn that caused it. |

The tree has 23 entity sets (with the subtypes) in one part.
To reach the patient of an assertion, follow Assertion → ClinicalEntry → Visit → Patient. There is only one path.

## 5. FHIR R4 alignment

| TRIAD | FHIR R4 |
|---|---|
| Department | Organization (type "dept") |
| Location | Location |
| Staff, WorksIn | Practitioner, PractitionerRole |
| Patient | Patient |
| Visit | Encounter |
| Diagnosis | Condition |
| Procedure | Procedure |
| Allergy | AllergyIntolerance |
| Observation | Observation |
| LabOrder | ServiceRequest |
| LabReport | DiagnosticReport |
| Prescription | MedicationRequest |
| CareTeam | CareTeam |
| Medication | Medication |
| Message | Communication or DocumentReference |
| Assertion, Supersedes | Provenance (`entity.role` = source and revision) |
| AuditEvent | AuditEvent |
| ChatSession, ChatTurn, Cites | No FHIR resource. This is the TRIAD agent layer. |

FHIR also has links that TRIAD does not show as relationships, because they would close loops: `Encounter.serviceProvider`, `Location.managingOrganization`, `Location.partOf`, `Organization.partOf` and `Condition.subject`. The source FHIR files in `src/backend/data/` keep them.

## 6. The assertion pipeline

1. A message arrives: a phone note, a visit note, a copied record, a patient report or a chat turn.
2. A staff member issues the message, or the patient sends it through the app (Origin = Patient).
3. Each fact in the message becomes an assertion. The assertion points to the clinical entry that it is about. The entry belongs to a visit, and the visit belongs to a patient.
4. An agent can extract an assertion for a person. Then the source is "Agent" and the verification is "unconfirmed". The person stays accountable. If the agent finds no fact, it makes no message.
5. When a new assertion changes an earlier one, `Supersedes` links them. Care-team changes use the same rule.
6. The current record is the set of assertions that nothing supersedes. To read the history, follow `Supersedes` back. Each step names a person and a source message.
