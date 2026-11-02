# TRIAD ER model (Milestone 4)

This folder holds the conceptual model of TRIAD: the entity-relationship (ER) diagram and these notes.
The Milestone 2 draft stays in `assets/designing_erd/` as a record.

| File | Content |
|---|---|
| `TRIAD_ERD.drawio` | The diagram. It has two pages. |
| `TRIAD_ERD.pdf` | Both pages as PDF. |
| `TRIAD_ERD_page1.png` | Page 1: the clinical core and the authorship model. |
| `TRIAD_ERD_page2.png` | Page 2: the agent layer, the care teams, the audit log and the lineage store. |
| `build_erd.py` | The script that makes `TRIAD_ERD.drawio`. |

To make the diagram again:

```bash
python3 src/backend/models/er/build_erd.py
cd src/backend/models/er
drawio -x -f pdf -a --crop -o TRIAD_ERD.pdf TRIAD_ERD.drawio
drawio -x -p 1 -f png -s 2 -o TRIAD_ERD_page1.png TRIAD_ERD.drawio
drawio -x -p 2 -f png -s 2 -o TRIAD_ERD_page2.png TRIAD_ERD.drawio
```

## 1. How to read the diagram

| Symbol | Meaning |
|---|---|
| Box | Entity. |
| Double box | Weak entity. Its owner identifies it. |
| Dashed box | A copy of an entity from page 1. |
| Diamond | Relationship. |
| Double diamond | Identifying relationship of a weak entity. |
| Oval | Attribute. |
| Double oval | Multivalued attribute. |
| Solid underline | Key. |
| Dashed underline | Partial key. It identifies a weak entity together with the key of its owner. |
| Triangle (ISA) | Subtypes. The triangle points toward the subtypes. Both hierarchies are disjoint and total. |
| Crow's feet | Cardinality. Two bars: exactly one. Circle and bar: zero or one. Circle and crow's foot: zero or many. Bar and crow's foot: one or many. |
| Grey | TRIAD contribution: authorship, revision and the agent layer. |
| *Identifier* | A composite attribute: System + Value. It has the same structure as the FHIR `Identifier`. |
| *Address* | A composite attribute: Street, City, Region, PostalCode, Country. |
| XOR note | Exactly one of the two relationships applies to each instance. |

## 2. Design rules

1. **Keys follow FHIR.** An entity that has a FHIR resource has the key *Identifier* (System, Value). If the source resource has no identifier, the key is (source base URL, logical id). Two entities have other keys: Patient (Name + DateOfBirth) and Medication (Code + CodeSystem).
2. **An entity that has no real-world key gets an identifier that the hospital assigns.** Milestone 2 made such entities weak. Milestone 4 does not (see comment 3).
3. **Only two entities are weak:** Assertion (owned by Message) and ChatTurn (owned by ChatSession). Their partial key is *Seq*, the position in the owner.
4. **No foreign keys at the conceptual level.** Relationships show all associations.
5. **The current assertion is the single source of truth for each fact.** The current assertion is the one that no assertion supersedes. Milestone 2 had the rule "the diagram is acyclic". We removed that rule, because FHIR references make a graph (for example, Organization, Location and Visit).
6. **Names are singular.** Each relationship has a unique name.

## 3. Changes from Milestone 2

### Comment 1: "Lack of sufficient attributes like for Department or Staff or MOA"

Each new attribute has a source field in FHIR R4. The onboarding step fills it from the data.

| Entity | Milestone 2 | Milestone 4 |
|---|---|---|
| Department → Organization | Name | Identifier, Name, Type, PhoneNumber, Email, Address |
| Staff | EmployeeNumber, Name | Identifier, Name, Sex, Email, PhoneNumber, Active, Role, Language (multivalued) |
| Doctor | LicenseNumber | LicenseNumber, Qualification |
| Nurse | LicenseNumber | LicenseNumber, Designation |
| MOA | (none) | CertificationNumber, Desk, PhoneExtension |
| Location | Name, Type | Identifier, Name, Type, PhysicalType, PhoneNumber, Address |

We also added attributes to other entities: Visit (Type, Reason), ClinicalEntry (Display, Text), Diagnosis (AbatementDate, ClinicalStatus, Severity), Allergy (Type, AllergyCategory), LabOrder (Priority, Specimen), Prescription (Status) and Medication (Manufacturer).

### Comment 2: "Staff issue Message and a Message has Assertion … the identifying entity set for the weak Assertion is Message"

- We removed `Asserts` (Staff–Assertion) and `ExtractedFrom` (Assertion–Message).
- We added `Issues` (Staff–Message). A staff member issues zero or many messages.
- We added the identifying relationship `Contains` (Message–Assertion). This is the professor's "has". Message is now the owner of the weak entity Assertion. The partial key of Assertion is *Seq*, its position in the message.
- The author of an assertion is now the sender of its message. Each assertion takes its authorship from its message.
- We added `Sends` (Patient–Message), so a patient can report a fact through the app. This follows the professor's comment for staff and extends it to patients. It matches FHIR `Communication.sender`. An XOR rule applies: each message has exactly one sender, a staff member (`Issues`) or a patient (`Sends`).
- We added `Discusses` (Message–Patient), the subject of the message.

### Comment 3: "The ternary Visit-Location-ClinicalEntry … the notation should not be like weak entity sets"

- Visit and ClinicalEntry are now **strong** entities. They have single boxes. `Has` and `During` have single diamonds.
- Visit stands in for the ternary relationship. Its binary relationships are `Has` (Patient), `TakesPlaceIn` (Location) and `During` (ClinicalEntry).
- The key of both entities is *Identifier* (FHIR `Encounter.identifier` or the resource id).
- **The data shows that the old partial keys are false.** In the Synthea sample, 27 (Patient, StartDate) pairs of Visit repeat. 291 (Visit, Code, RecordedAt) triples of ClinicalEntry repeat (207 Observation and 84 MedicationRequest). The old keys are now plain attributes.
- `During` is now zero or one. FHIR makes the encounter of a clinical resource optional. For example, none of the 101 Synthea allergies has an encounter. A patient report from home also has no visit. A new relationship, `ConcernsPatient`, links each ClinicalEntry to exactly one patient.

### Other changes (with the reason)

| Change | Reason |
|---|---|
| Department became **Organization**, with the unary `SubunitOf`. | FHIR shows departments as child Organizations (`partOf`). The hospital and its departments fit one entity. |
| `WorksIn` became many-to-many with RoleCode, Specialty, StartDate and EndDate. | This is FHIR `PractitionerRole`. A person can have roles in more than one organization. |
| Location got `Within` (unary) and `ManagedBy` (Organization). | FHIR `Location.partOf` (ward, room, bed) and `Location.managingOrganization`. |
| Visit got `ProvidedBy` (Organization). | FHIR `Encounter.serviceProvider`. |
| The Patient key became Name + DateOfBirth. Identifier became multivalued. | Team decision. PHN is one identifier among others (MRN, SSN, licence numbers). We do not make up a PHN. |
| The Message key became *Identifier*. Message got Origin. | Two staff can send on one channel at the same time, so Channel + SentAt is not a key. Origin keeps the source of the information (patient, staff, other clinic, PharmaNet, lab). |
| Assertion: Role became **Intent** (Report, Recommendation, Decision). | The role of the author now comes from Issues → Staff. A Role column would repeat that data. Intent keeps a patient report, a nurse recommendation and a doctor decision apart. |
| Assertion got Verification (from Diagnosis) and Statement. | A revision is per claim, so the verification belongs to the claim. |
| The Medication key became Code + CodeSystem. | FHIR `Medication.code`. It holds RxNorm codes (Synthea) and DIN codes (Canada). |
| New: CareTeam with `CaresFor`, `Covers` and `MemberOf`. | FHIR `CareTeam`. The access rule uses it: only staff on a care team can open a chart. |
| New: the agent layer (ChatSession, ChatTurn, `Cites`, `Yields`). | The Care Assistant keeps its conversations. Each answer cites the assertions that it used, so a wrong answer can be traced to a relationship. |
| New: AuditEvent. | FHIR `AuditEvent`. It records who read or changed the data of a patient, and the denied attempts. |
| New: the lineage store (FhirSource, FhirResource, `DerivedFrom`). | It keeps every source FHIR resource. TRIAD can then link to any FHIR server with almost no data loss. It is a physical layer, so page 2 shows it as an inset. |

## 4. Relationships and cardinalities

| Relationship | Entities | Reading |
|---|---|---|
| Issues | Staff – Message | A staff member issues zero or many messages. A message has zero or one staff sender (XOR with Sends). |
| Sends | Patient – Message | A patient sends zero or many messages. A message has zero or one patient sender (XOR with Issues). |
| Discusses | Message – Patient | Each message is about exactly one patient. |
| Contains | Message – Assertion | Identifying. A message contains zero or many assertions. Each assertion belongs to exactly one message. |
| About | Assertion – ClinicalEntry | Each assertion is about exactly one entry. Each entry has one or many assertions. |
| Supersedes | Assertion – Assertion | Unary. An assertion replaces zero or one assertion. Zero or one assertion replaces it. |
| ConcernsPatient | ClinicalEntry – Patient | Each entry concerns exactly one patient. |
| During | ClinicalEntry – Visit | An entry is recorded during zero or one visit. |
| Has | Patient – Visit | A patient has zero or many visits. Each visit has exactly one patient. |
| TakesPlaceIn | Visit – Location | Many-to-many, with StartDate and EndDate. |
| ProvidedBy | Visit – Organization | A visit has zero or one provider organization. |
| ManagedBy | Location – Organization | A location has zero or one managing organization. |
| SubunitOf | Organization – Organization | Unary. An organization has zero or one parent. |
| Within | Location – Location | Unary. A location is in zero or one parent location. |
| WorksIn | Staff – Organization | Many-to-many (PractitionerRole), with RoleCode, Specialty, StartDate and EndDate. |
| Prescribes | Prescription – Medication | Each prescription names exactly one medication. |
| CaresFor | CareTeam – Patient | Each care team is for exactly one patient. |
| Covers | CareTeam – Visit | A care team covers zero or one visit. |
| MemberOf | Staff – CareTeam | Many-to-many, with Role. |
| Opens | Staff – ChatSession | A staff member opens zero or many sessions. A patient user opens no session through this relationship. |
| ChatsAbout | ChatSession – Patient | Each session is about exactly one patient. |
| Includes | ChatSession – ChatTurn | Identifying. A session includes zero or many turns. |
| Cites | ChatTurn – Assertion | Many-to-many, with Rank. An answer cites the assertions that it used. |
| Yields | ChatTurn – Message | One-to-one, optional. A "tell" turn yields one clinical message. |
| AuditedPatient | AuditEvent – Patient | Each audit record is about exactly one patient. |
| DoneByStaff, DoneByPatient | AuditEvent – Staff or Patient | XOR: each audit record has exactly one actor. |
| InTurn | AuditEvent – ChatTurn | An audit record can point to the chat turn that caused it. |
| HoldsResource | FhirSource – FhirResource | Identifying. A source holds many resources. |
| DerivedFrom | mapped entity – FhirResource | A row comes from zero or one source resource. |

## 5. FHIR R4 alignment

| TRIAD | FHIR R4 |
|---|---|
| Organization | Organization |
| Location | Location |
| Staff, WorksIn | Practitioner, PractitionerRole |
| Patient | Patient |
| Visit | Encounter |
| CareTeam | CareTeam |
| Diagnosis | Condition |
| Procedure | Procedure |
| Allergy | AllergyIntolerance |
| Observation | Observation |
| LabOrder | ServiceRequest |
| LabReport | DiagnosticReport |
| Prescription | MedicationRequest |
| Medication | Medication |
| Message | Communication or DocumentReference |
| Assertion, Supersedes | Provenance (`entity.role` = source and revision) |
| AuditEvent | AuditEvent |
| ChatSession, ChatTurn, Cites | No FHIR resource. This is the TRIAD agent layer. |

## 6. The assertion pipeline

1. A message arrives: a phone note, a visit note, a copied record, a patient report or a chat turn.
2. The message has exactly one sender: a staff member or the patient.
3. Each fact in the message becomes an assertion. The assertion points to the clinical entry that it is about.
4. An agent can extract an assertion for a person. Then the source is "Agent" and the verification is "unconfirmed". The person stays accountable.
5. When a new assertion changes an earlier one, `Supersedes` links them.
6. The current record is the set of assertions that nothing supersedes. To read the history, follow `Supersedes` back. Each step names a person and a source message.
