# TRIAD ontology (Milestone 5): the ER → OWL mapping

This file maps the ER model (`../er/README.md`, `../er/TRIAD_ERD.png`) and the 29 relations (`../relational/relations.md`) to an RDFS and OWL 2 DL ontology.
The Turtle source is `triad.ttl`. `build_ontology.py` checks it and writes `triad.owl` (RDF/XML). `vocabulary.py` holds the column map of section 10 as Python data. A test checks that this file, `vocabulary.py` and `triad.ttl` agree.
Report page 3 uses this file.

## Notation

- `triad:Patient` is a term of the ontology. `kg:patient/1` is an individual of the data (an IRI). In this file only, `kg:patient/1` is a short form of `https://github.com/MohamedKhalidmk/TRIAD/kg/patient/1`. Turtle and SPARQL do not allow `/` in a prefixed name, so a query writes the full IRI.
- **Domain → Range** of a property. A shared property has one domain: the union (`owl:unionOf`) of its classes.
- Characteristics: **F** Functional, **IF** InverseFunctional, **Asym** Asymmetric, **Irr** Irreflexive, **Trans** Transitive.
- Restrictions: `=1 p` is `owl:cardinality 1`, `≥1 p` is `owl:minCardinality 1`, `≤1 p` is `owl:maxCardinality 1`. `=1 p.C` and `≥1 p.C` are the qualified forms (`owl:qualifiedCardinality`, `owl:minQualifiedCardinality` with `owl:onClass C`). `inverse(p)` is the anonymous inverse `[ owl:inverseOf p ]`.
- **Stored**: the store holds the triples of the property. **Named inverse** and **derived**: the store holds no triples; a reasoner infers them.
- **date**: a date-only value. The data uses `xsd:date`. OWL 2 has no `xsd:date`, so the TBox range is `rdfs:Literal` (section 4.3).
- **closed**: a closed value set (`owl:oneOf` on a datatype, decision D10).
- All counts are for `triad:` terms only. Protégé also shows the PROV-O terms (section 7).

## 1. Namespaces, IRIs and graphs

| Prefix | IRI | Use |
|---|---|---|
| `triad:` | `https://github.com/MohamedKhalidmk/TRIAD/ontology/triad#` | The terms (classes and properties). |
| — | `https://github.com/MohamedKhalidmk/TRIAD/ontology/triad` | The ontology IRI. The version IRI is `…/ontology/triad/5.0.0`. |
| `kg:` | `https://github.com/MohamedKhalidmk/TRIAD/kg/` | The individuals: `kg:<class path>/<Id>` (decision D6). |
| — | `https://github.com/MohamedKhalidmk/TRIAD/graph/tbox` | The named graph of the ontology (TBox). |
| — | `https://github.com/MohamedKhalidmk/TRIAD/graph/abox` | The named graph of the data (ABox). |
| — | `https://github.com/MohamedKhalidmk/TRIAD/graph/scratch` | The scratch graph of the scripts 02, 04 and 05 and of the planted checks. |
| — | `https://github.com/MohamedKhalidmk/TRIAD/graph/meta` | The id counters and the build marker. |
| `prov:` | `http://www.w3.org/ns/prov#` | PROV-O alignment (section 7). |
| `dcterms:`, `skos:` | `http://purl.org/dc/terms/`, `http://www.w3.org/2004/02/skos/core#` | Metadata and the links to FHIR. Declared as `owl:AnnotationProperty`. |
| `fhir:` | `http://hl7.org/fhir/` | The namespace of the FHIR R4 Turtle. Only annotation values use it. |
| `xsd:`, `rdf:`, `rdfs:`, `owl:` | the W3C IRIs | — |

**The subject IRI of each table** (`vocabulary.SUBJECT`). The 17 class paths are the ones of plan 1.1.

| Table | Class (`rdf:type`) | Subject IRI of its triples |
|---|---|---|
| Department, Location, Staff, Patient, Visit, ClinicalEntry, Medication, Message, Assertion, ChatSession, ChatTurn, AuditEvent | the class of the same name | `kg:department/{Id}`, `kg:location/{Id}`, `kg:staff/{Id}`, `kg:patient/{Id}`, `kg:visit/{Id}`, `kg:clinical-entry/{Id}`, `kg:medication/{Id}`, `kg:message/{Id}`, `kg:assertion/{Id}`, `kg:chat-session/{Id}`, `kg:chat-turn/{Id}`, `kg:audit-event/{Id}` |
| WorksIn, VisitLocation, Citation | `triad:WorksIn`, `triad:VisitLocation`, `triad:Citation` | `kg:works-in/{Id}`, `kg:visit-location/{Id}`, `kg:citation/{Id}` |
| PatientIdentifier, CareTeamMember | `triad:PatientIdentifier`, `triad:CareTeamMember` | `kg:patient-identifier/{Id}`, `kg:care-team-member/{Id}` |
| Doctor, Nurse, MOA | `triad:Doctor`, `triad:Nurse`, `triad:MOA` (a second type) | `kg:staff/{StaffId}`: the same individual as the Staff row |
| Diagnosis, Procedure, Allergy, Observation, LabOrder, LabReport, Prescription, CareTeam | the subtype class (a second type) | `kg:clinical-entry/{ClinicalEntryId}`: the same individual as the ClinicalEntry row |
| StaffLanguage | — (no individual) | `kg:staff/{StaffId}`: each row is one `triad:language` triple |

Rules:
- **A subtype row is the same individual as its parent row.** `kg:staff/2` is a `triad:Staff` and a `triad:Nurse`. The subtype relation has its own Id in SQLite. That Id gets no IRI.
- **The care-team trap.** `CareTeamMember.CareTeamId` holds `CareTeam.Id`, not the entry Id. The two differ in all 369 CareTeam rows. The mapping must join CareTeam to get `kg:clinical-entry/{CareTeam.ClinicalEntryId}` (`vocabulary.FK_JOINS`; plan 3.1).
- The relational Id is the last part of the IRI. The ontology has no `id` property. To sort as SQLite does, a query uses `xsd:integer(STRAFTER(STR(?x), "/assertion/"))`.
- The data has no blank nodes. No IRI holds a name or a date of birth.
- **Ontology metadata:** `owl:versionIRI`, `owl:versionInfo "5.0.0"`, `rdfs:label`, `rdfs:comment`, `dcterms:title`, `dcterms:creator` (the two team members), `dcterms:license` (`https://creativecommons.org/licenses/by-nc-sa/4.0/`, the licence of the repository), `dcterms:source` (the ER README and the DDL on GitHub). No `owl:imports`.

## 2. Classes (28)

| # | Class | ER element (relation) | Kind | Superclass | FHIR R4 (`skos:`) | Key |
|---|---|---|---|---|---|---|
| 1 | `Department` | entity set (1) | top class | — | closeMatch `Organization` | Identifier |
| 2 | `Location` | entity set (2) | top class | — | closeMatch `Location` | Identifier |
| 3 | `Staff` | entity set (3) | top class | `prov:Person` | closeMatch `Practitioner` | Identifier |
| 4 | `Doctor` | ISA subtype (6) | subtype | `Staff` | — | (of Staff) |
| 5 | `Nurse` | ISA subtype (7) | subtype | `Staff` | — | (of Staff) |
| 6 | `MOA` | ISA subtype (8) | subtype | `Staff` | — | (of Staff) |
| 7 | `WorksIn` | relationship WorksIn, M:N with attributes (5) | association class | — | closeMatch `PractitionerRole` | (ofStaff, atDepartment, roleCode) |
| 8 | `Patient` | entity set (9) | top class | — | closeMatch `Patient` | (name, dateOfBirth) |
| 9 | `PatientIdentifier` | multivalued composite attribute Patient.Identifier (10) | value class | — | closeMatch `Identifier` | (identifierSystem, identifierValue) |
| 10 | `Visit` | entity set (11) | top class | — | closeMatch `Encounter` | Identifier |
| 11 | `VisitLocation` | relationship TakesPlaceIn, M:N with attributes (12) | association class | — | — | (ofVisit, atLocation, startDate) |
| 12 | `ClinicalEntry` | entity set (13) | top class | — | — | Identifier |
| 13 | `Diagnosis` | ISA subtype (14) | subtype | `ClinicalEntry` | closeMatch `Condition` | (of ClinicalEntry) |
| 14 | `Procedure` | ISA subtype (15) | subtype | `ClinicalEntry` | closeMatch `Procedure` | (of ClinicalEntry) |
| 15 | `Allergy` | ISA subtype (16) | subtype | `ClinicalEntry` | closeMatch `AllergyIntolerance` | (of ClinicalEntry) |
| 16 | `Observation` | ISA subtype (17) | subtype | `ClinicalEntry` | closeMatch `Observation` | (of ClinicalEntry) |
| 17 | `LabOrder` | ISA subtype (18) | subtype | `ClinicalEntry` | closeMatch `ServiceRequest` | (of ClinicalEntry) |
| 18 | `LabReport` | ISA subtype (19) | subtype | `ClinicalEntry` | closeMatch `DiagnosticReport` | (of ClinicalEntry) |
| 19 | `Prescription` | ISA subtype (21) | subtype | `ClinicalEntry` | closeMatch `MedicationRequest` | (of ClinicalEntry) |
| 20 | `CareTeam` | ISA subtype (22) | subtype | `ClinicalEntry` | closeMatch `CareTeam` | (of ClinicalEntry) |
| 21 | `CareTeamMember` | multivalued composite attribute CareTeam.Member (23) | value class | — | — | (memberOf, memberSystem, memberValue) |
| 22 | `Medication` | entity set (20) | top class | — | closeMatch `Medication` | (code, codeSystem) |
| 23 | `Message` | entity set (24) | top class | `prov:Entity` | closeMatch `Communication`, relatedMatch `DocumentReference` | Identifier |
| 24 | `Assertion` | weak entity set, owner Message (25) | top class | `prov:Entity` | relatedMatch `Provenance` | (inMessage, seq) |
| 25 | `ChatSession` | entity set (26) | top class | — | — (agent layer) | Identifier |
| 26 | `ChatTurn` | weak entity set, owner ChatSession (27) | top class | — | — (agent layer) | (inSession, seq) and (inSession, clientTurnId) |
| 27 | `Citation` | relationship Cites, M:N with Rank (28) | association class | — | — (agent layer) | (byTurn, citedAssertion) |
| 28 | `AuditEvent` | entity set (29) | top class | — | closeMatch `AuditEvent` | Identifier |

"Identifier" is the key (`identifierSystem`, `identifierValue`).

**Class axioms:**
- `triad:Staff owl:disjointUnionOf (Doctor Nurse MOA)`: the ISA is disjoint and total.
- `triad:ClinicalEntry owl:disjointUnionOf (Diagnosis Procedure Allergy Observation LabOrder LabReport Prescription CareTeam)`.
- Each subtype also has an explicit `rdfs:subClassOf` of its parent, so the asserted view of Protégé shows the tree.
- `owl:AllDisjointClasses` with 17 members: the 12 top classes, the 3 association classes and the 2 value classes. OWL has no Unique Name Assumption, so this axiom catches a typing error (one IRI with two of these classes). It is valid OWL 2 DL.
- **The discriminators** `Staff.Role` and `ClinicalEntry.Category` give no property: `rdf:type` holds them. The data has both types (for example `triad:Staff` and `triad:Nurse`), because Virtuoso does no OWL reasoning. SHACL checks "exactly one subtype" (plan 3.4).
- **Count:** 23 entity sets (with the subtypes) + 3 association classes + 2 value classes = **28 classes** = 29 relations − StaffLanguage. The 11 subtype relations stay classes, but their rows become extra types of the parent individuals. StaffLanguage becomes the multivalued datatype property `triad:language`.

## 3. Object properties (25)

The direction follows the ER README §4 and the crow's feet of the ERD. The names are lowerCamelCase. The ER `Has` becomes `hasVisit`. The n-ary participant properties do not repeat a class name: `ofStaff`, `atDepartment`, `ofVisit`, `atLocation`, `byTurn`, `citedAssertion`.

### 3.1 The 17 stored properties (one per foreign-key column)

The last column is the triple in the store. **This is the list that the R2RML mapping (plan 3.1) needs.** "Reverse" means that the subject of the triple is the row of the FK target, not the row that holds the FK.

| Property | ER relationship | Domain → Range | Char. | Restrictions | Column (direction) | Triple in the store |
|---|---|---|---|---|---|---|
| `issues` | Issues (0..1 issuer) | Staff → Message | IF | Message ⊑ `≤1 issuedBy` | Message.StaffId (reverse) | `kg:staff/{StaffId} triad:issues kg:message/{Id}` |
| `contains` | Contains (identifying) | Message → Assertion | IF | Message ⊑ `≥1 contains`; Assertion ⊑ `=1 inMessage.Message` | Assertion.MessageId (reverse) | `kg:message/{MessageId} triad:contains kg:assertion/{Id}` |
| `about` | About | Assertion → ClinicalEntry | F | Assertion ⊑ `=1 about`; ClinicalEntry ⊑ `≥1 inverse(about).Assertion` | Assertion.ClinicalEntryId | `kg:assertion/{Id} triad:about kg:clinical-entry/{ClinicalEntryId}` |
| `supersedes` | Supersedes (unary 1:1) | Assertion → Assertion | F, IF, Asym, Irr; ⊑ `supersedesTransitively`, ⊑ `prov:wasRevisionOf` | Assertion ⊑ `≤1 supersedes` | Assertion.SupersedesId | `kg:assertion/{Id} triad:supersedes kg:assertion/{SupersedesId}` |
| `during` | During (total) | ClinicalEntry → Visit | F | ClinicalEntry ⊑ `=1 during` | ClinicalEntry.VisitId | `kg:clinical-entry/{Id} triad:during kg:visit/{VisitId}` |
| `hasVisit` | Has | Patient → Visit | IF | Visit ⊑ `=1 visitOf.Patient` | Visit.PatientId (reverse) | `kg:patient/{PatientId} triad:hasVisit kg:visit/{Id}` |
| `ofVisit` | TakesPlaceIn | VisitLocation → Visit | F | VisitLocation ⊑ `=1 ofVisit` | VisitLocation.VisitId | `kg:visit-location/{Id} triad:ofVisit kg:visit/{VisitId}` |
| `atLocation` | TakesPlaceIn | VisitLocation → Location | F | VisitLocation ⊑ `=1 atLocation` | VisitLocation.LocationId | `kg:visit-location/{Id} triad:atLocation kg:location/{LocationId}` |
| `ofStaff` | WorksIn | WorksIn → Staff | F | WorksIn ⊑ `=1 ofStaff`; **Staff ⊑ `≥1 inverse(ofStaff).WorksIn`** | WorksIn.StaffId | `kg:works-in/{Id} triad:ofStaff kg:staff/{StaffId}` |
| `atDepartment` | WorksIn | WorksIn → Department | F | WorksIn ⊑ `=1 atDepartment` | WorksIn.DepartmentId | `kg:works-in/{Id} triad:atDepartment kg:department/{DepartmentId}` |
| `prescribes` | Prescribes | Prescription → Medication | F | Prescription ⊑ `=1 prescribes` | Prescription.MedicationId | `kg:clinical-entry/{ClinicalEntryId} triad:prescribes kg:medication/{MedicationId}` |
| `includes` | Includes (identifying) | ChatSession → ChatTurn | IF | ChatTurn ⊑ `=1 inSession.ChatSession` | ChatTurn.ChatSessionId (reverse) | `kg:chat-session/{ChatSessionId} triad:includes kg:chat-turn/{Id}` |
| `byTurn` | Cites | Citation → ChatTurn | F | Citation ⊑ `=1 byTurn` | Citation.ChatTurnId | `kg:citation/{Id} triad:byTurn kg:chat-turn/{ChatTurnId}` |
| `citedAssertion` | Cites | Citation → Assertion | F | Citation ⊑ `=1 citedAssertion` | Citation.AssertionId | `kg:citation/{Id} triad:citedAssertion kg:assertion/{AssertionId}` |
| `inTurn` | InTurn | AuditEvent → ChatTurn | F | — (the FK is nullable) | AuditEvent.ChatTurnId | `kg:audit-event/{Id} triad:inTurn kg:chat-turn/{ChatTurnId}` |
| `identifier` | Patient.Identifier (multivalued) | Patient → PatientIdentifier | IF | PatientIdentifier ⊑ `=1 inverse(identifier).Patient` | PatientIdentifier.PatientId (reverse) | `kg:patient/{PatientId} triad:identifier kg:patient-identifier/{Id}` |
| `member` | CareTeam.Member (multivalued) | CareTeam → CareTeamMember | IF | CareTeamMember ⊑ `=1 memberOf.CareTeam` | CareTeamMember.CareTeamId (reverse, **join**) | `kg:clinical-entry/{CareTeam.ClinicalEntryId} triad:member kg:care-team-member/{Id}` |

Notes:
- **`Staff ⊑ ≥1 inverse(ofStaff).WorksIn` is a new rule.** Milestone 4 did not enforce it. The data has it (292 of 292 staff members). SHACL also checks it.
- No restriction on Visit for TakesPlaceIn: the ER participation is partial. (The data has exactly one VisitLocation per visit: 5,090 of 5,090.)
- Message ⊑ `≤1 issuedBy` repeats the Functional characteristic of `issuedBy`. It shows the construct `owl:maxCardinality`.

### 3.2 The 5 named inverses (no triples in the store)

| Property | Inverse of | Domain → Range | Char. | Used by |
|---|---|---|---|---|
| `inMessage` | `contains` | Assertion → Message | F | the key of Assertion; the chain of `assertedBy`; the restriction `=1 inMessage.Message` |
| `inSession` | `includes` | ChatTurn → ChatSession | F | the two keys of ChatTurn; `=1 inSession.ChatSession` |
| `issuedBy` | `issues` | Message → Staff | F; ⊑ `prov:wasAttributedTo` | the chain of `assertedBy`; `≤1 issuedBy` |
| `visitOf` | `hasVisit` | Visit → Patient | F | the chain of `ofPatient`; `=1 visitOf.Patient` |
| `memberOf` | `member` | CareTeamMember → CareTeam | F | the key of CareTeamMember; `=1 memberOf.CareTeam` |

The subject of each `owl:inverseOf` triple is the named inverse. The Functional characteristic of a named inverse is the same fact as the InverseFunctional characteristic of its stored property.

### 3.3 The 3 derived properties (OWL 2 property chains; a reasoner infers them, the store does not)

| Property | Axiom | Domain → Range | Note |
|---|---|---|---|
| `assertedBy` | `owl:propertyChainAxiom (inMessage issuedBy)`; ⊑ `prov:wasAttributedTo` | Assertion → Staff | Decision D5 (Mohamed's review point 1). An assertion of a patient message has no value. |
| `ofPatient` | `owl:propertyChainAxiom (about during visitOf)` | Assertion → Patient | The one path Assertion → ClinicalEntry → Visit → Patient of the tree. |
| `supersedesTransitively` | `owl:TransitiveProperty`; `supersedes` ⊑ it | Assertion → Assertion | The history of an assertion. |

Both chains are regular (OWL 2 §11.2).

### 3.4 Simple and non-simple properties

- A property is **composite** when it has a property chain or it is transitive: `assertedBy`, `ofPatient`, `supersedesTransitively`.
- A property is **non-simple** when a composite property is below it in the sub-property hierarchy (OWL 2 §11.1). So `prov:wasAttributedTo` is non-simple too (`assertedBy` ⊑ it), and so are the inverses of these four.
- `supersedes`, `issues`, `issuedBy`, `contains` and `inMessage` stay simple. So their characteristics (F, IF, Asym, Irr) and cardinality restrictions are valid OWL 2 DL.
- `owl:hasKey` has no simple-property rule, so the keys on the named inverses are valid.
- OWL 2 DL does not allow Irreflexive on the transitive `supersedesTransitively`. So a reasoner cannot find a supersedes cycle of 3 or more (section 8).

## 4. Datatype properties (92)

### 4.1 Rules

- **One property for each ER attribute**, in lowerCamelCase. A composite single-valued attribute (Identifier, Address, User, Actor, Subject) gives one property per part, so each part can be in an `owl:hasKey`.
- **Each single-valued attribute is `owl:FunctionalProperty`** (91 properties). **`triad:language`** is the only multivalued attribute: a staff member has one triple per language.
- **NOT NULL gives `owl:minCardinality 1`** on the class of the table (81 restrictions; section 5).
- **Names that must differ:**
  - A closed range is never shared (decision D10): `careTeamStatus` (closed) and `prescriptionStatus` (text); `auditOutcome` (closed) and `procedureOutcome` (text). For the same reason Staff.Sex and Patient.Sex become `staffSex` and `patientSex` (section 13).
  - The `Type` columns become `departmentType`, `locationType`, `visitType`, `allergyType`. `Visit.Class` becomes `visitClass`. The names `triad:type` and `triad:class` read like `rdf:type`.
  - The WorksIn dates become `roleStartDate` and `roleEndDate` (dates). They differ from `startDate` and `endDate` of Visit and VisitLocation (dateTimes).
  - `CareTeamMember.Role` becomes `memberRole`, next to `memberSystem` and `memberValue`.

### 4.2 The datatype properties of each class

**Bold**: the column is NOT NULL, so the class has `≥1` on the property. The range is `xsd:string` unless the brackets give another one.

| Class | Datatype properties |
|---|---|
| Department | **identifierSystem**, **identifierValue**, **name**, departmentType, phoneNumber, email, street, city, region, postalCode, country |
| Location | **identifierSystem**, **identifierValue**, **name**, locationType, physicalType, phoneNumber, street, city, region, postalCode, country |
| Staff | **identifierSystem**, **identifierValue**, **name**, staffSex (closed), email, phoneNumber, **active** (boolean), language (multivalued, from StaffLanguage) |
| WorksIn | **roleCode**, specialty, roleStartDate (date), roleEndDate (date) |
| Doctor | licenseNumber, qualification |
| Nurse | licenseNumber, **designation** (closed) |
| MOA | certificationNumber, **desk**, phoneExtension |
| Patient | **name**, **dateOfBirth** (date), **patientSex** (closed), phoneNumber, street, city, region, postalCode, country |
| PatientIdentifier | **identifierSystem**, **identifierValue** |
| Visit | **identifierSystem**, **identifierValue**, **visitClass** (closed), visitType, reason, **startDate** (dateTime), endDate (dateTime) |
| VisitLocation | **startDate** (dateTime), endDate (dateTime) |
| ClinicalEntry | **identifierSystem**, **identifierValue**, **code**, **codeSystem**, **display**, text, **recordedAt** (dateTime) |
| Diagnosis | onsetDate (dateTime), abatementDate (dateTime), **clinicalStatus**, severity |
| Procedure | **performedDate** (dateTime), procedureOutcome |
| Allergy | **substance**, allergyType, allergyCategory, criticality, clinicalStatus |
| Observation | **value**, unit |
| LabOrder | **testName**, **priority** (closed), specimen |
| LabReport | **issuedDate** (dateTime), conclusion |
| Medication | **code**, **codeSystem**, **name**, form, manufacturer |
| Prescription | dosage, frequency, **prescriptionStatus** |
| CareTeam | name, **careTeamStatus** (closed) |
| CareTeamMember | **memberSystem**, **memberValue**, memberRole |
| Message | **identifierSystem**, **identifierValue**, **channel** (closed), **origin** (closed), **sentAt** (dateTime), **text** |
| Assertion | **seq** (integer ≥ 1), **assertedAt** (dateTime), **intent** (closed), **source** (closed), **verification** (closed), **statement** |
| ChatSession | **identifierSystem**, **identifierValue**, **userRole** (closed), **userSystem**, **userValue**, **subjectName**, **subjectDateOfBirth** (date), **startedAt** (dateTime), **mode** (closed), model |
| ChatTurn | **seq** (integer ≥ 1), **clientTurnId**, **speaker** (closed), **text**, **createdAt** (dateTime) |
| Citation | **rank** (integer ≥ 1) |
| AuditEvent | **identifierSystem**, **identifierValue**, **at** (dateTime), **action** (closed), **auditOutcome** (closed), **actorRole** (closed), **actorSystem**, **actorValue**, **subjectName**, **subjectDateOfBirth** (date), **path** |

### 4.3 Ranges

| Range | Properties |
|---|---|
| `xsd:dateTime` | `startDate`, `endDate` (Visit, VisitLocation), `recordedAt`, `onsetDate`, `abatementDate`, `performedDate`, `issuedDate`, `sentAt`, `assertedAt`, `startedAt`, `createdAt`, `at`. The data has a time in every row of OnsetDate, AbatementDate, PerformedDate and IssuedDate, so they are dateTimes, not dates. |
| date: `rdfs:Literal` in the TBox, `xsd:date` in the data | `dateOfBirth`, `subjectDateOfBirth`, `roleStartDate`, `roleEndDate`. **OWL 2 has no `xsd:date`** (Structural Specification §4), and HermiT stops on it. So the TBox range is `rdfs:Literal`, the `rdfs:comment` says "an xsd:date", and SHACL holds `sh:datatype xsd:date`. (WorksIn.EndDate is NULL in every row of the data.) |
| `xsd:integer [≥ 1]` | `seq`, `rank`: a datatype restriction `owl:onDatatype xsd:integer; owl:withRestrictions ([xsd:minInclusive 1])`. It holds `CHECK (Seq >= 1)` and `CHECK (Rank >= 1)`. The R2RML mapping gives `rr:datatype xsd:integer`, because Morph-KGC infers no SQLite types. |
| `xsd:boolean` | `active`. The values `1` and `0` of SQLite are valid `xsd:boolean` forms. |
| closed (`owl:oneOf`) | the 17 value sets of section 4.4 |
| `xsd:string` | all other properties. `Observation.value` stays `xsd:string` (a value can be a number, a code or a text), and `unit` is a separate property. |

### 4.4 Closed value sets (17)

Each one equals the `CHECK … IN` list of its column. `build_ontology.py` compares the two lists.

| Property | Column | Values |
|---|---|---|
| `staffSex` | Staff.Sex | female, male, other, unknown |
| `patientSex` | Patient.Sex | female, male, other, unknown |
| `designation` | Nurse.Designation | RN, LPN, RPN, NP |
| `visitClass` | Visit.Class | AMB, EMER, IMP, HH, VR |
| `priority` | LabOrder.Priority | routine, urgent, asap, stat |
| `careTeamStatus` | CareTeam.Status | proposed, active, suspended, inactive, entered-in-error |
| `channel` | Message.Channel | InPerson, Phone, Video, Email, Fax, Transfer, Chat, App |
| `origin` | Message.Origin | Patient, Staff, OtherClinic, PharmaNet, Lab, Agent |
| `intent` | Assertion.Intent | Report, Recommendation, Decision |
| `source` | Assertion.Source | Human, Agent |
| `verification` | Assertion.Verification | Unconfirmed, Provisional, Differential, Confirmed, Refuted, EnteredInError |
| `userRole` | ChatSession.UserRole | Patient, Doctor, Nurse, MOA |
| `mode` | ChatSession.Mode | rules, fake, llm |
| `speaker` | ChatTurn.Speaker | User, Assistant |
| `action` | AuditEvent.Action | read, create, update, delete, ask, tell |
| `auditOutcome` | AuditEvent.Outcome | Allowed, Denied |
| `actorRole` | AuditEvent.ActorRole | Patient, Doctor, Nurse, MOA |

The values are simple literals (`xsd:string`), as in the data (SPARQL writing rule 4). `Staff.Active IN (0, 1)` becomes `xsd:boolean`, not a value set.

### 4.5 Shared properties (20; one domain: the union)

| Property | Domain (`owl:unionOf`) | Range |
|---|---|---|
| `identifierSystem`, `identifierValue` | Department, Location, Staff, Visit, ClinicalEntry, Message, ChatSession, AuditEvent, PatientIdentifier | `xsd:string` |
| `name` | Department, Location, Staff, Patient, Medication, CareTeam | `xsd:string` |
| `phoneNumber` | Department, Location, Staff, Patient | `xsd:string` |
| `email` | Department, Staff | `xsd:string` |
| `street`, `city`, `region`, `postalCode`, `country` | Department, Location, Patient | `xsd:string` |
| `startDate`, `endDate` | Visit, VisitLocation | `xsd:dateTime` |
| `code`, `codeSystem` | ClinicalEntry, Medication | `xsd:string` |
| `text` | ClinicalEntry, Message, ChatTurn | `xsd:string` |
| `seq` | Assertion, ChatTurn | `xsd:integer [≥ 1]` |
| `clinicalStatus` | Diagnosis, Allergy | `xsd:string` |
| `licenseNumber` | Doctor, Nurse | `xsd:string` |
| `subjectName` | ChatSession, AuditEvent | `xsd:string` |
| `subjectDateOfBirth` | ChatSession, AuditEvent | date (`rdfs:Literal`) |

Two `rdfs:domain` axioms would mean the intersection of the classes, so each shared property has exactly one domain. No shared property has a closed range.

**Optional (cut 2), not in this version:** codes as Linked Open Data (`triad:concept` → SNOMED CT, LOINC and RxNorm IRIs). Plan 1.4 gives the IRI patterns.

## 5. Restrictions (100)

| Rule of the relational schema | OWL construct | Count |
|---|---|---|
| NOT NULL attribute column | `owl:minCardinality 1` (unqualified) on the class of the table | 81 |
| NOT NULL FK in the stored direction (mandatory and single) | `owl:cardinality 1` (unqualified; the range fixes the class) | 9 |
| NOT NULL FK in the reverse direction | `owl:qualifiedCardinality 1` on the named or anonymous inverse, with `owl:onClass` | 5 |
| Nullable FK with one value | `owl:maxCardinality 1` (Message `≤1 issuedBy`, Assertion `≤1 supersedes`) | 2 |
| ER participation "one or many" (no column) | `owl:minCardinality 1` (Message `≥1 contains`) or `owl:minQualifiedCardinality 1` on an inverse (ClinicalEntry `≥1 inverse(about).Assertion`, Staff `≥1 inverse(ofStaff).WorksIn`) | 3 |
| Total | | **100** |

The 19 restrictions on object properties are in section 3.1. The 81 restrictions on datatype properties are the `≥1` rows of section 10.
The unqualified forms apply where `rdfs:range` already fixes the class. The qualified forms apply only on the inverse paths.
The report table says: NOT NULL → `minCardinality 1`; an optional single value → `maxCardinality 1` (= Functional); mandatory and single → `cardinality 1`.
Under the Open World Assumption (OWA), a missing value is unknown, not an error. So these restrictions describe the model; SHACL checks the data (section 8).

## 6. Keys (`owl:hasKey`: 18 axioms on 17 classes)

| Class | Key | DDL constraint |
|---|---|---|
| Department, Location, Staff, Visit, ClinicalEntry, Message, ChatSession, AuditEvent | (`identifierSystem`, `identifierValue`) | `UK_<Table>_Identifier` |
| Patient | (`name`, `dateOfBirth`) | `UK_Patient_Name_DateOfBirth` |
| PatientIdentifier | (`identifierSystem`, `identifierValue`) | `UK_PatientIdentifier_System_Value` |
| Medication | (`code`, `codeSystem`) | `UK_Medication_Code_CodeSystem` |
| Assertion (weak) | (`inMessage`, `seq`) | `UK_Assertion_MessageId_Seq` |
| ChatTurn (weak) | (`inSession`, `seq`) and (`inSession`, `clientTurnId`) | `UK_ChatTurn_ChatSessionId_Seq`, `UK_ChatTurn_ChatSessionId_ClientTurnId` |
| WorksIn | (`ofStaff`, `atDepartment`, `roleCode`) | `UK_WorksIn_StaffId_DepartmentId_RoleCode` |
| VisitLocation | (`ofVisit`, `atLocation`, `startDate`) | `UK_VisitLocation_VisitId_LocationId_StartDate` |
| Citation | (`byTurn`, `citedAssertion`) | `UK_Citation_ChatTurnId_AssertionId` |
| CareTeamMember | (`memberOf`, `memberSystem`, `memberValue`) | `UK_CareTeamMember_CareTeamId_Member` |

**The UNIQUE constraints that give no key** (`build_ontology.UNIQUE_NOT_KEY`):

| Constraint | Reason |
|---|---|
| `UK_Staff_Id_Role`, `UK_ClinicalEntry_Id_Category` | The target of the composite FK of the subtypes. The Id is in the IRI. |
| `UK_<Subtype>_StaffId`, `UK_<Subtype>_ClinicalEntryId` (11) | The subtype row is the same individual as its parent row. |
| `UK_StaffLanguage_StaffId_Language` | A graph holds each triple once, so a language cannot repeat. |
| `UK_Assertion_SupersedesId` | `owl:InverseFunctionalProperty` on `triad:supersedes`. |

**What `owl:hasKey` does:**
- Two named individuals of the class with the same key values are the same individual (`owl:sameAs`). The second one is not an error.
- It becomes an error (an inconsistency) only when the merged individual then has two values of a Functional property, or two disjoint types.
- SHACL and `05_constraint_checks.sparql` find duplicate keys, and the app guards them (plan 5.4).
- The report links this to the professor's own use of `owl:sameAs` for duplicate incidents.

## 7. Alignment and annotations

**PROV-O** (declared locally in `triad.ttl`; no `owl:imports`):

| TRIAD | PROV-O | Reason |
|---|---|---|
| `Message`, `Assertion` | ⊑ `prov:Entity` | A message and a claim are things with a fixed form. |
| `Staff` | ⊑ `prov:Person` (⊑ `prov:Agent`) | A staff member is a responsible person. |
| `supersedes` | ⊑ `prov:wasRevisionOf` | The new assertion is a revision of the old one (the direction is correct). |
| `issuedBy`, `assertedBy` | ⊑ `prov:wasAttributedTo` | The issuer and the author are the responsible agents. |

The local declarations: `prov:Entity`, `prov:Agent`, `prov:Person` (classes), `prov:wasAttributedTo` (Entity → Agent), `prov:wasRevisionOf` (Entity → Entity), with `rdfs:isDefinedBy <http://www.w3.org/ns/prov-o#>`.

**FHIR R4:** `skos:closeMatch` and `skos:relatedMatch` to `fhir:` (section 2). Assertion → `skos:relatedMatch fhir:Provenance`, not closeMatch: an assertion is one claim, and a FHIR Provenance describes one resource version. ClinicalEntry, the Staff subtypes, VisitLocation, CareTeamMember and the agent layer have no FHIR resource of their own.

**Annotations:** each class and property has one `rdfs:label` (English), an `rdfs:comment` in ASD-STE100 and `rdfs:isDefinedBy` the ontology IRI. The comment of each property names its columns. `build_ontology.py` checks this.

## 8. What OWL cannot hold, and where each rule goes

| Milestone 4 rule (SQLite) | OWL? | Milestone 5 place |
|---|---|---|
| NOT NULL | `minCardinality 1` (OWA: a missing value is unknown, not an error) | SHACL `sh:minCount 1`; 05 query |
| CHECK … IN | A closed range: a wrong value makes the ontology inconsistent for a reasoner | SHACL `sh:in`; the app validation |
| CHECK (Seq ≥ 1), CHECK (Rank ≥ 1) | A datatype facet `xsd:integer [≥ 1]`: a reasoner finds a wrong value | SHACL `sh:minInclusive 1` |
| A date column (CHECK date(…)) | No: OWL 2 has no `xsd:date` (range `rdfs:Literal`) | SHACL `sh:datatype xsd:date` |
| UNIQUE / CK | `owl:hasKey` infers `owl:sameAs`, no error | **App guard (Conflict 409) for each key that only the database enforces today:** Medication (code, codeSystem), the client-given identifiers of a department, location or staff member, Assertion.supersedes (one new assertion per old one), ChatTurn (session, clientTurnId), Patient (name, dateOfBirth). SHACL-SPARQL; 05 query. |
| FK | A dangling IRI gets a type from the range, no error. A target of a disjoint class (for example `about` → a Visit) is an inconsistency. | SHACL `sh:class`; 05 query |
| EndDate ≥ StartDate | No | SHACL `sh:lessThanOrEquals` |
| `StaffId IS NOT NULL OR Origin = 'Patient'` | No | SHACL `sh:or` |
| `SupersedesId <> Id` | Irreflexive (a reasoner finds it) | Guard; 05 query |
| No cycle in Supersedes | No: OWL 2 DL forbids Irreflexive on the transitive property, so a cycle of 3 or more is not found | Guard; 05: `ASK { ?a triad:supersedes+ ?a }` (the outer pattern binds a start) |
| Append-only (Assertion, AuditEvent) | No (a store has no "update" event) | The SPARQL delete helper takes an **allow-list of class paths**. A unit test gives it `assertion` and `audit-event` and expects a refusal. The guarantee moves from the database to the application. |
| Supersede check, one head per entry, one patient per message, care-team member, citation check, audit subject | No (negation as failure, or rows of other tables) | Guards in Python on the buffered change, with one SELECT under the lock for stored facts (plan 5.4); 05 queries |
| The patient key cannot change | No | The use case refuses it (`patients.py`); the adapter refuses it too |
| ≥1 assertion per message and per entry | `minCardinality 1` (OWA: not checked) | The use case (as now); SHACL on the inverse path; 05 query |
| Staff works in ≥1 department (new) | `≥1 inverse(ofStaff).WorksIn` | SHACL `sh:minCount 1` on `^triad:ofStaff` |
| "The current assertion" | **No:** under OWA, "no triple" does not mean "false" | `FILTER NOT EXISTS { ?n triad:supersedes ?a }` |

**The error mapping today** (the KG guards raise the same errors):

| Rule in SQLite | Exception | HTTP | Code | Message / fields |
|---|---|---|---|---|
| UNIQUE | Conflict | 409 | `conflict` | "A row with the same key exists already.", `{key}` |
| FOREIGN KEY | Conflict | 409 | `conflict` | "The row is in use, or it points to a row that does not exist." |
| CHECK / NOT NULL | Invalid | 422 | `validation` | "The input is not correct.", `{database}` |
| Trigger RAISE | Invalid | 422 | `validation` | the trigger text |

## 9. The tree

The ER model is a tree (ER README, design rule 1). The ontology keeps it:
- **Nodes:** the 28 classes. **Edges:** the 16 stored object properties without the `supersedes` loop (domain–range) and the 11 `rdfs:subClassOf` edges between TRIAD classes. 28 nodes, 27 edges, one connected part: a tree.
- The named inverses, the derived properties and the PROV-O super-properties are not edges. Each derived property is a shortcut along the one path.
- `build_ontology.py` checks this with the `Model` class of `../er/build_erd.py`. A test gives it a known loop and expects the check to stop.

## 10. Coverage: each table and column of the DDL

`01_create_tables.sql` has 29 tables and 209 columns. **155 columns give a property** (138 attribute columns for the 92 datatype properties, 17 FK columns for the 17 stored object properties). **54 columns give no property**, with the reason in the last column. `build_ontology.py` stops when a column has no row here (in `vocabulary.py`), when a row names a column that does not exist, and when a NOT NULL column has no restriction.

Kind: **attribute** = `<row> triad:p "value"`; **FK** = `<row> triad:p <target>`; **FK, reverse** = `<target> triad:p <row>`; **IRI** = the last part of the subject IRI; **type** = `rdf:type` holds it; **subject** = it selects the subject IRI; **none** = no triple.

| Column | Term | Kind | Range | NOT NULL → restriction, or the reason |
|---|---|---|---|---|
| Department.Id | — | IRI | — | The Id is the last part of the IRI of the row. |
| Department.IdentifierSystem | `triad:identifierSystem` | attribute | xsd:string | `≥1` |
| Department.IdentifierValue | `triad:identifierValue` | attribute | xsd:string | `≥1` |
| Department.Name | `triad:name` | attribute | xsd:string | `≥1` |
| Department.Type | `triad:departmentType` | attribute | xsd:string | — |
| Department.PhoneNumber | `triad:phoneNumber` | attribute | xsd:string | — |
| Department.Email | `triad:email` | attribute | xsd:string | — |
| Department.Street | `triad:street` | attribute | xsd:string | — |
| Department.City | `triad:city` | attribute | xsd:string | — |
| Department.Region | `triad:region` | attribute | xsd:string | — |
| Department.PostalCode | `triad:postalCode` | attribute | xsd:string | — |
| Department.Country | `triad:country` | attribute | xsd:string | — |
| Location.Id | — | IRI | — | The Id is the last part of the IRI of the row. |
| Location.IdentifierSystem | `triad:identifierSystem` | attribute | xsd:string | `≥1` |
| Location.IdentifierValue | `triad:identifierValue` | attribute | xsd:string | `≥1` |
| Location.Name | `triad:name` | attribute | xsd:string | `≥1` |
| Location.Type | `triad:locationType` | attribute | xsd:string | — |
| Location.PhysicalType | `triad:physicalType` | attribute | xsd:string | — |
| Location.PhoneNumber | `triad:phoneNumber` | attribute | xsd:string | — |
| Location.Street | `triad:street` | attribute | xsd:string | — |
| Location.City | `triad:city` | attribute | xsd:string | — |
| Location.Region | `triad:region` | attribute | xsd:string | — |
| Location.PostalCode | `triad:postalCode` | attribute | xsd:string | — |
| Location.Country | `triad:country` | attribute | xsd:string | — |
| Staff.Id | — | IRI | — | The Id is the last part of the IRI of the row. |
| Staff.IdentifierSystem | `triad:identifierSystem` | attribute | xsd:string | `≥1` |
| Staff.IdentifierValue | `triad:identifierValue` | attribute | xsd:string | `≥1` |
| Staff.Name | `triad:name` | attribute | xsd:string | `≥1` |
| Staff.Sex | `triad:staffSex` | attribute | closed (`owl:oneOf`) | — |
| Staff.Email | `triad:email` | attribute | xsd:string | — |
| Staff.PhoneNumber | `triad:phoneNumber` | attribute | xsd:string | — |
| Staff.Active | `triad:active` | attribute | xsd:boolean | `≥1` |
| Staff.Role | — | type | — | The discriminator: rdf:type holds it. |
| StaffLanguage.Id | — | none | — | A StaffLanguage row has no IRI: it becomes one triad:language triple. |
| StaffLanguage.StaffId | — | subject | — | The subject of the triad:language triple. |
| StaffLanguage.Language | `triad:language` | attribute | xsd:string | — (multivalued) |
| WorksIn.Id | — | IRI | — | The Id is the last part of the IRI of the row. |
| WorksIn.StaffId | `triad:ofStaff` | FK | WorksIn → Staff | `=1 ofStaff` |
| WorksIn.DepartmentId | `triad:atDepartment` | FK | WorksIn → Department | `=1 atDepartment` |
| WorksIn.RoleCode | `triad:roleCode` | attribute | xsd:string | `≥1` |
| WorksIn.Specialty | `triad:specialty` | attribute | xsd:string | — |
| WorksIn.StartDate | `triad:roleStartDate` | attribute | date (rdfs:Literal) | — |
| WorksIn.EndDate | `triad:roleEndDate` | attribute | date (rdfs:Literal) | — |
| Doctor.Id | — | none | — | The subtype row has no IRI of its own: it is the same individual as its parent row. |
| Doctor.StaffId | — | subject | — | The parent Id: it is the subject of the subtype triples (the same individual). |
| Doctor.Role | — | type | — | A copy of the discriminator (for the composite FK): rdf:type holds it. |
| Doctor.LicenseNumber | `triad:licenseNumber` | attribute | xsd:string | — |
| Doctor.Qualification | `triad:qualification` | attribute | xsd:string | — |
| Nurse.Id | — | none | — | The subtype row has no IRI of its own: it is the same individual as its parent row. |
| Nurse.StaffId | — | subject | — | The parent Id: it is the subject of the subtype triples (the same individual). |
| Nurse.Role | — | type | — | A copy of the discriminator (for the composite FK): rdf:type holds it. |
| Nurse.LicenseNumber | `triad:licenseNumber` | attribute | xsd:string | — |
| Nurse.Designation | `triad:designation` | attribute | closed (`owl:oneOf`) | `≥1` |
| MOA.Id | — | none | — | The subtype row has no IRI of its own: it is the same individual as its parent row. |
| MOA.StaffId | — | subject | — | The parent Id: it is the subject of the subtype triples (the same individual). |
| MOA.Role | — | type | — | A copy of the discriminator (for the composite FK): rdf:type holds it. |
| MOA.CertificationNumber | `triad:certificationNumber` | attribute | xsd:string | — |
| MOA.Desk | `triad:desk` | attribute | xsd:string | `≥1` |
| MOA.PhoneExtension | `triad:phoneExtension` | attribute | xsd:string | — |
| Patient.Id | — | IRI | — | The Id is the last part of the IRI of the row. |
| Patient.Name | `triad:name` | attribute | xsd:string | `≥1` |
| Patient.DateOfBirth | `triad:dateOfBirth` | attribute | date (rdfs:Literal) | `≥1` |
| Patient.Sex | `triad:patientSex` | attribute | closed (`owl:oneOf`) | `≥1` |
| Patient.PhoneNumber | `triad:phoneNumber` | attribute | xsd:string | — |
| Patient.Street | `triad:street` | attribute | xsd:string | — |
| Patient.City | `triad:city` | attribute | xsd:string | — |
| Patient.Region | `triad:region` | attribute | xsd:string | — |
| Patient.PostalCode | `triad:postalCode` | attribute | xsd:string | — |
| Patient.Country | `triad:country` | attribute | xsd:string | — |
| PatientIdentifier.Id | — | IRI | — | The Id is the last part of the IRI of the row. |
| PatientIdentifier.PatientId | `triad:identifier` | FK, reverse | Patient → PatientIdentifier | `=1 inverse(identifier).Patient` |
| PatientIdentifier.System | `triad:identifierSystem` | attribute | xsd:string | `≥1` |
| PatientIdentifier.Value | `triad:identifierValue` | attribute | xsd:string | `≥1` |
| Visit.Id | — | IRI | — | The Id is the last part of the IRI of the row. |
| Visit.IdentifierSystem | `triad:identifierSystem` | attribute | xsd:string | `≥1` |
| Visit.IdentifierValue | `triad:identifierValue` | attribute | xsd:string | `≥1` |
| Visit.PatientId | `triad:hasVisit` | FK, reverse | Patient → Visit | `=1 visitOf.Patient` |
| Visit.Class | `triad:visitClass` | attribute | closed (`owl:oneOf`) | `≥1` |
| Visit.Type | `triad:visitType` | attribute | xsd:string | — |
| Visit.Reason | `triad:reason` | attribute | xsd:string | — |
| Visit.StartDate | `triad:startDate` | attribute | xsd:dateTime | `≥1` |
| Visit.EndDate | `triad:endDate` | attribute | xsd:dateTime | — |
| VisitLocation.Id | — | IRI | — | The Id is the last part of the IRI of the row. |
| VisitLocation.VisitId | `triad:ofVisit` | FK | VisitLocation → Visit | `=1 ofVisit` |
| VisitLocation.LocationId | `triad:atLocation` | FK | VisitLocation → Location | `=1 atLocation` |
| VisitLocation.StartDate | `triad:startDate` | attribute | xsd:dateTime | `≥1` |
| VisitLocation.EndDate | `triad:endDate` | attribute | xsd:dateTime | — |
| ClinicalEntry.Id | — | IRI | — | The Id is the last part of the IRI of the row. |
| ClinicalEntry.IdentifierSystem | `triad:identifierSystem` | attribute | xsd:string | `≥1` |
| ClinicalEntry.IdentifierValue | `triad:identifierValue` | attribute | xsd:string | `≥1` |
| ClinicalEntry.VisitId | `triad:during` | FK | ClinicalEntry → Visit | `=1 during` |
| ClinicalEntry.Category | — | type | — | The discriminator: rdf:type holds it. |
| ClinicalEntry.Code | `triad:code` | attribute | xsd:string | `≥1` |
| ClinicalEntry.CodeSystem | `triad:codeSystem` | attribute | xsd:string | `≥1` |
| ClinicalEntry.Display | `triad:display` | attribute | xsd:string | `≥1` |
| ClinicalEntry.Text | `triad:text` | attribute | xsd:string | — |
| ClinicalEntry.RecordedAt | `triad:recordedAt` | attribute | xsd:dateTime | `≥1` |
| Diagnosis.Id | — | none | — | The subtype row has no IRI of its own: it is the same individual as its parent row. |
| Diagnosis.ClinicalEntryId | — | subject | — | The parent Id: it is the subject of the subtype triples (the same individual). |
| Diagnosis.Category | — | type | — | A copy of the discriminator (for the composite FK): rdf:type holds it. |
| Diagnosis.OnsetDate | `triad:onsetDate` | attribute | xsd:dateTime | — |
| Diagnosis.AbatementDate | `triad:abatementDate` | attribute | xsd:dateTime | — |
| Diagnosis.ClinicalStatus | `triad:clinicalStatus` | attribute | xsd:string | `≥1` |
| Diagnosis.Severity | `triad:severity` | attribute | xsd:string | — |
| Procedure.Id | — | none | — | The subtype row has no IRI of its own: it is the same individual as its parent row. |
| Procedure.ClinicalEntryId | — | subject | — | The parent Id: it is the subject of the subtype triples (the same individual). |
| Procedure.Category | — | type | — | A copy of the discriminator (for the composite FK): rdf:type holds it. |
| Procedure.PerformedDate | `triad:performedDate` | attribute | xsd:dateTime | `≥1` |
| Procedure.Outcome | `triad:procedureOutcome` | attribute | xsd:string | — |
| Allergy.Id | — | none | — | The subtype row has no IRI of its own: it is the same individual as its parent row. |
| Allergy.ClinicalEntryId | — | subject | — | The parent Id: it is the subject of the subtype triples (the same individual). |
| Allergy.Category | — | type | — | A copy of the discriminator (for the composite FK): rdf:type holds it. |
| Allergy.Substance | `triad:substance` | attribute | xsd:string | `≥1` |
| Allergy.Type | `triad:allergyType` | attribute | xsd:string | — |
| Allergy.AllergyCategory | `triad:allergyCategory` | attribute | xsd:string | — |
| Allergy.Criticality | `triad:criticality` | attribute | xsd:string | — |
| Allergy.ClinicalStatus | `triad:clinicalStatus` | attribute | xsd:string | — |
| Observation.Id | — | none | — | The subtype row has no IRI of its own: it is the same individual as its parent row. |
| Observation.ClinicalEntryId | — | subject | — | The parent Id: it is the subject of the subtype triples (the same individual). |
| Observation.Category | — | type | — | A copy of the discriminator (for the composite FK): rdf:type holds it. |
| Observation.Value | `triad:value` | attribute | xsd:string | `≥1` |
| Observation.Unit | `triad:unit` | attribute | xsd:string | — |
| LabOrder.Id | — | none | — | The subtype row has no IRI of its own: it is the same individual as its parent row. |
| LabOrder.ClinicalEntryId | — | subject | — | The parent Id: it is the subject of the subtype triples (the same individual). |
| LabOrder.Category | — | type | — | A copy of the discriminator (for the composite FK): rdf:type holds it. |
| LabOrder.TestName | `triad:testName` | attribute | xsd:string | `≥1` |
| LabOrder.Priority | `triad:priority` | attribute | closed (`owl:oneOf`) | `≥1` |
| LabOrder.Specimen | `triad:specimen` | attribute | xsd:string | — |
| LabReport.Id | — | none | — | The subtype row has no IRI of its own: it is the same individual as its parent row. |
| LabReport.ClinicalEntryId | — | subject | — | The parent Id: it is the subject of the subtype triples (the same individual). |
| LabReport.Category | — | type | — | A copy of the discriminator (for the composite FK): rdf:type holds it. |
| LabReport.IssuedDate | `triad:issuedDate` | attribute | xsd:dateTime | `≥1` |
| LabReport.Conclusion | `triad:conclusion` | attribute | xsd:string | — |
| Medication.Id | — | IRI | — | The Id is the last part of the IRI of the row. |
| Medication.Code | `triad:code` | attribute | xsd:string | `≥1` |
| Medication.CodeSystem | `triad:codeSystem` | attribute | xsd:string | `≥1` |
| Medication.Name | `triad:name` | attribute | xsd:string | `≥1` |
| Medication.Form | `triad:form` | attribute | xsd:string | — |
| Medication.Manufacturer | `triad:manufacturer` | attribute | xsd:string | — |
| Prescription.Id | — | none | — | The subtype row has no IRI of its own: it is the same individual as its parent row. |
| Prescription.ClinicalEntryId | — | subject | — | The parent Id: it is the subject of the subtype triples (the same individual). |
| Prescription.Category | — | type | — | A copy of the discriminator (for the composite FK): rdf:type holds it. |
| Prescription.MedicationId | `triad:prescribes` | FK | Prescription → Medication | `=1 prescribes` |
| Prescription.Dosage | `triad:dosage` | attribute | xsd:string | — |
| Prescription.Frequency | `triad:frequency` | attribute | xsd:string | — |
| Prescription.Status | `triad:prescriptionStatus` | attribute | xsd:string | `≥1` |
| CareTeam.Id | — | none | — | The subtype row has no IRI of its own: it is the same individual as its parent row. |
| CareTeam.ClinicalEntryId | — | subject | — | The parent Id: it is the subject of the subtype triples (the same individual). |
| CareTeam.Category | — | type | — | A copy of the discriminator (for the composite FK): rdf:type holds it. |
| CareTeam.Name | `triad:name` | attribute | xsd:string | — |
| CareTeam.Status | `triad:careTeamStatus` | attribute | closed (`owl:oneOf`) | `≥1` |
| CareTeamMember.Id | — | IRI | — | The Id is the last part of the IRI of the row. |
| CareTeamMember.CareTeamId | `triad:member` | FK, reverse | CareTeam → CareTeamMember | `=1 memberOf.CareTeam` |
| CareTeamMember.MemberSystem | `triad:memberSystem` | attribute | xsd:string | `≥1` |
| CareTeamMember.MemberValue | `triad:memberValue` | attribute | xsd:string | `≥1` |
| CareTeamMember.Role | `triad:memberRole` | attribute | xsd:string | — |
| Message.Id | — | IRI | — | The Id is the last part of the IRI of the row. |
| Message.IdentifierSystem | `triad:identifierSystem` | attribute | xsd:string | `≥1` |
| Message.IdentifierValue | `triad:identifierValue` | attribute | xsd:string | `≥1` |
| Message.StaffId | `triad:issues` | FK, reverse | Staff → Message | `≤1 issuedBy` (nullable) |
| Message.Channel | `triad:channel` | attribute | closed (`owl:oneOf`) | `≥1` |
| Message.Origin | `triad:origin` | attribute | closed (`owl:oneOf`) | `≥1` |
| Message.SentAt | `triad:sentAt` | attribute | xsd:dateTime | `≥1` |
| Message.Text | `triad:text` | attribute | xsd:string | `≥1` |
| Assertion.Id | — | IRI | — | The Id is the last part of the IRI of the row. |
| Assertion.MessageId | `triad:contains` | FK, reverse | Message → Assertion | `=1 inMessage.Message` |
| Assertion.Seq | `triad:seq` | attribute | xsd:integer [≥ 1] | `≥1` |
| Assertion.ClinicalEntryId | `triad:about` | FK | Assertion → ClinicalEntry | `=1 about` |
| Assertion.SupersedesId | `triad:supersedes` | FK | Assertion → Assertion | `≤1 supersedes` (nullable) |
| Assertion.AssertedAt | `triad:assertedAt` | attribute | xsd:dateTime | `≥1` |
| Assertion.Intent | `triad:intent` | attribute | closed (`owl:oneOf`) | `≥1` |
| Assertion.Source | `triad:source` | attribute | closed (`owl:oneOf`) | `≥1` |
| Assertion.Verification | `triad:verification` | attribute | closed (`owl:oneOf`) | `≥1` |
| Assertion.Statement | `triad:statement` | attribute | xsd:string | `≥1` |
| ChatSession.Id | — | IRI | — | The Id is the last part of the IRI of the row. |
| ChatSession.IdentifierSystem | `triad:identifierSystem` | attribute | xsd:string | `≥1` |
| ChatSession.IdentifierValue | `triad:identifierValue` | attribute | xsd:string | `≥1` |
| ChatSession.UserRole | `triad:userRole` | attribute | closed (`owl:oneOf`) | `≥1` |
| ChatSession.UserSystem | `triad:userSystem` | attribute | xsd:string | `≥1` |
| ChatSession.UserValue | `triad:userValue` | attribute | xsd:string | `≥1` |
| ChatSession.SubjectName | `triad:subjectName` | attribute | xsd:string | `≥1` |
| ChatSession.SubjectDateOfBirth | `triad:subjectDateOfBirth` | attribute | date (rdfs:Literal) | `≥1` |
| ChatSession.StartedAt | `triad:startedAt` | attribute | xsd:dateTime | `≥1` |
| ChatSession.Mode | `triad:mode` | attribute | closed (`owl:oneOf`) | `≥1` |
| ChatSession.Model | `triad:model` | attribute | xsd:string | — |
| ChatTurn.Id | — | IRI | — | The Id is the last part of the IRI of the row. |
| ChatTurn.ChatSessionId | `triad:includes` | FK, reverse | ChatSession → ChatTurn | `=1 inSession.ChatSession` |
| ChatTurn.Seq | `triad:seq` | attribute | xsd:integer [≥ 1] | `≥1` |
| ChatTurn.ClientTurnId | `triad:clientTurnId` | attribute | xsd:string | `≥1` |
| ChatTurn.Speaker | `triad:speaker` | attribute | closed (`owl:oneOf`) | `≥1` |
| ChatTurn.Text | `triad:text` | attribute | xsd:string | `≥1` |
| ChatTurn.CreatedAt | `triad:createdAt` | attribute | xsd:dateTime | `≥1` |
| Citation.Id | — | IRI | — | The Id is the last part of the IRI of the row. |
| Citation.ChatTurnId | `triad:byTurn` | FK | Citation → ChatTurn | `=1 byTurn` |
| Citation.AssertionId | `triad:citedAssertion` | FK | Citation → Assertion | `=1 citedAssertion` |
| Citation.Rank | `triad:rank` | attribute | xsd:integer [≥ 1] | `≥1` |
| AuditEvent.Id | — | IRI | — | The Id is the last part of the IRI of the row. |
| AuditEvent.IdentifierSystem | `triad:identifierSystem` | attribute | xsd:string | `≥1` |
| AuditEvent.IdentifierValue | `triad:identifierValue` | attribute | xsd:string | `≥1` |
| AuditEvent.At | `triad:at` | attribute | xsd:dateTime | `≥1` |
| AuditEvent.Action | `triad:action` | attribute | closed (`owl:oneOf`) | `≥1` |
| AuditEvent.Outcome | `triad:auditOutcome` | attribute | closed (`owl:oneOf`) | `≥1` |
| AuditEvent.ActorRole | `triad:actorRole` | attribute | closed (`owl:oneOf`) | `≥1` |
| AuditEvent.ActorSystem | `triad:actorSystem` | attribute | xsd:string | `≥1` |
| AuditEvent.ActorValue | `triad:actorValue` | attribute | xsd:string | `≥1` |
| AuditEvent.SubjectName | `triad:subjectName` | attribute | xsd:string | `≥1` |
| AuditEvent.SubjectDateOfBirth | `triad:subjectDateOfBirth` | attribute | date (rdfs:Literal) | `≥1` |
| AuditEvent.Path | `triad:path` | attribute | xsd:string | `≥1` |
| AuditEvent.ChatTurnId | `triad:inTurn` | FK | AuditEvent → ChatTurn | — (nullable; Functional) |

### 10.1 The columns that give no property (for the count check of plan 3.3)

| Group | Columns | Count |
|---|---|---|
| Id of a table with its own IRI | Department, Location, Staff, WorksIn, Patient, PatientIdentifier, Visit, VisitLocation, ClinicalEntry, Medication, CareTeamMember, Message, Assertion, ChatSession, ChatTurn, Citation, AuditEvent `.Id` | 17 |
| Id of a subtype table, and StaffLanguage.Id | Doctor, Nurse, MOA, Diagnosis, Procedure, Allergy, Observation, LabOrder, LabReport, Prescription, CareTeam `.Id`; StaffLanguage.Id | 12 |
| Discriminator | Staff.Role, ClinicalEntry.Category | 2 |
| Copy of the discriminator in a subtype | Doctor/Nurse/MOA `.Role`; the 8 entry subtypes `.Category` | 11 |
| Parent FK of a subtype | Doctor/Nurse/MOA `.StaffId`; the 8 entry subtypes `.ClinicalEntryId` | 11 |
| The subject of `triad:language` | StaffLanguage.StaffId | 1 |
| Total | | **54** |

**The counts of a new clone** (`main.py export-kg` with this column map; `kg_report.json`, 2026-11-17). The plan counted a development database with 31 more rows (1,298,807 triples), see `doc/ai_review_log.md`:
- `rdf:type` triples = the rows of all tables except StaffLanguage = **188,271**. A subtype row adds a second type to an existing individual.
- Attribute triples = the non-NULL cells of the 138 attribute columns = **911,697** (with the 41 `triad:language` triples).
- FK triples = the non-NULL cells of the 17 FK columns = **198,514**.
- Total **1,298,482** triples (the build marker is in the meta graph, not in this count). Individuals: 188,312 rows − 57,312 subtype rows − 41 StaffLanguage rows = **130,959**.

### 10.2 Each ER relationship, its property and its cardinality

| ER relationship (ER README §4) | Property | ER cardinality | OWL restriction, or the reason for none |
|---|---|---|---|
| WorksIn | `ofStaff`, `atDepartment` (class `WorksIn`) | Staff 1..N : Department 0..N | WorksIn `=1 ofStaff`, `=1 atDepartment`; Staff `≥1 inverse(ofStaff).WorksIn`. Department: partial, no restriction. |
| Issues | `issues` / `issuedBy` | Staff 0..N : Message 0..1 | Message `≤1 issuedBy`. Staff: partial, no restriction. |
| Contains | `contains` / `inMessage` | Message 1..N : Assertion 1 | Message `≥1 contains`; Assertion `=1 inMessage.Message` |
| About | `about` | Assertion 1 : ClinicalEntry 1..N | Assertion `=1 about`; ClinicalEntry `≥1 inverse(about).Assertion` |
| Supersedes | `supersedes` | 0..1 : 0..1 | F and IF; Assertion `≤1 supersedes` |
| During | `during` | ClinicalEntry 1 : Visit 0..N | ClinicalEntry `=1 during`. Visit: partial, no restriction. |
| Has | `hasVisit` / `visitOf` | Patient 0..N : Visit 1 | Visit `=1 visitOf.Patient`. Patient: partial, no restriction. |
| TakesPlaceIn | `ofVisit`, `atLocation` (class `VisitLocation`) | Visit 0..N : Location 0..N | VisitLocation `=1 ofVisit`, `=1 atLocation`. Visit and Location: partial, no restriction. |
| Prescribes | `prescribes` | Prescription 1 : Medication 0..N | Prescription `=1 prescribes`. Medication: partial, no restriction. |
| Includes | `includes` / `inSession` | ChatSession 0..N : ChatTurn 1 | ChatTurn `=1 inSession.ChatSession`. ChatSession: partial, no restriction. |
| Cites | `byTurn`, `citedAssertion` (class `Citation`) | ChatTurn 0..N : Assertion 0..N | Citation `=1 byTurn`, `=1 citedAssertion`. Both ends partial. |
| InTurn | `inTurn` | AuditEvent 0..1 : ChatTurn 0..N | F only (the FK is nullable). ChatTurn: partial, no restriction. |
| Patient.Identifier (multivalued) | `identifier` | Patient 0..N : PatientIdentifier 1 | PatientIdentifier `=1 inverse(identifier).Patient`. Patient: partial. |
| CareTeam.Member (multivalued) | `member` / `memberOf` | CareTeam 0..N : CareTeamMember 1 | CareTeamMember `=1 memberOf.CareTeam`. CareTeam: partial. |
| Staff.Language (multivalued) | `language` (datatype) | Staff 0..N | Not Functional. No restriction (partial). |

## 11. ER/relational element → OWL construct → example triple

The examples use the scenario rows (all synthetic). Patient A is `kg:patient/1`; her penicillin allergy is `kg:clinical-entry/1`.

| ER / relational element | OWL construct | Example (Turtle) |
|---|---|---|
| Entity set | `owl:Class` | `triad:Patient a owl:Class .` |
| Entity (a row) | A named individual; the IRI comes from the surrogate key | `kg:patient/1 a triad:Patient .` |
| Simple attribute | `owl:DatatypeProperty`, Functional | `kg:patient/1 triad:name "Elena Marsh" .` |
| Date attribute | Range `rdfs:Literal` (TBox), `xsd:date` (ABox) | `kg:patient/1 triad:dateOfBirth "1971-05-14"^^xsd:date .` |
| Time attribute | Range `xsd:dateTime` | `kg:assertion/3 triad:assertedAt "2026-10-02T11:40:00-04:00"^^xsd:dateTime .` |
| Composite attribute (Address) | One property per part | `kg:patient/1 triad:city "Worcester" .` |
| Multivalued attribute (Language) | A non-functional property: many triples | `kg:staff/2 triad:language "en" , "hi" .` |
| Multivalued composite attribute (Identifier) | A value class and an InverseFunctional property | `kg:patient/1 triad:identifier kg:patient-identifier/1 .` |
| Key | `owl:hasKey` | `triad:Patient owl:hasKey ( triad:name triad:dateOfBirth ) .` |
| Weak entity and partial key | `owl:hasKey` with the named inverse of the owner | `triad:Assertion owl:hasKey ( triad:inMessage triad:seq ) .` |
| IS-A (disjoint, total) | `rdfs:subClassOf` and `owl:disjointUnionOf` | `triad:Nurse rdfs:subClassOf triad:Staff .` |
| Discriminator (Role, Category) | `rdf:type` (no property) | `kg:staff/2 a triad:Staff , triad:Nurse .` |
| 1:N relationship (M:1 FK) | `owl:ObjectProperty`, Functional, `=1` | `kg:assertion/3 triad:about kg:clinical-entry/1 .` |
| Identifying relationship | InverseFunctional, and `=1` on the named inverse | `kg:message/5 triad:contains kg:assertion/3 .` |
| Unary 1:1 relationship | F, IF, Asymmetric, Irreflexive | `kg:assertion/3 triad:supersedes kg:assertion/2 .` |
| M:N relationship with attributes | An association class with two Functional properties (W3C n-ary pattern) | `kg:works-in/2 triad:ofStaff kg:staff/2 ; triad:atDepartment kg:department/1 ; triad:roleCode "nurse" .` |
| NOT NULL | `owl:minCardinality 1` | `triad:Patient rdfs:subClassOf [ owl:onProperty triad:name ; owl:minCardinality 1 ] .` |
| CHECK … IN | A closed datatype (`owl:oneOf`) | `triad:intent rdfs:range [ owl:oneOf ( "Report" "Recommendation" "Decision" ) ] .` |
| CHECK (x ≥ 1) | A datatype facet | `triad:rank rdfs:range [ owl:onDatatype xsd:integer ; owl:withRestrictions ( [ xsd:minInclusive 1 ] ) ] .` |
| A path of FKs (Assertion → Patient) | A property chain | `triad:ofPatient owl:propertyChainAxiom ( triad:about triad:during triad:visitOf ) .` |
| Authorship (Message → Staff) | A property chain and PROV-O | `triad:assertedBy owl:propertyChainAxiom ( triad:inMessage triad:issuedBy ) .` |
| Trigger, CHECK across columns | Not OWL: SHACL, the 05 queries and the app guards | section 8 |

**The W3C Direct Mapping** (plan 3.6; manual 5.1.2) is the automatic mapping of a relational database to RDF. `build_ontology.py --direct-mapping-example` prints the Direct Mapping of one Assertion row next to the triples of this mapping. The differences:
- The Direct Mapping makes the IRI from the table and the key (`<Assertion/Id=3>`). This mapping uses the class path (`kg:assertion/3`).
- The Direct Mapping gives a literal triple for each column, with the Id and each FK (`<Assertion#MessageId> 5`), and one `ref-` triple for each FK. This mapping gives no Id triple and one object property for each FK.
- The Direct Mapping keeps the FK direction (Assertion → Message). This mapping stores `contains` from the message to the assertion, in the ER direction.
- The Direct Mapping keeps the SQL types: a time is a plain string. This mapping gives `xsd:dateTime`.
- The Direct Mapping has no class axioms. Its class is the table name. A subtype row (Nurse) becomes a second node (`<Nurse/Id=2>`). This mapping makes it a second type of the same individual, and the ontology adds the keys, the restrictions, the disjointness, the chains and the PROV-O and FHIR links.

## 12. Counts

`build_ontology.py` prints these counts. A test checks that they equal this table.

| Count | Value |
|---|---|
| Classes | 28 |
| Object properties | 25 |
| Stored object properties | 17 |
| Named inverses | 5 |
| Derived object properties | 3 |
| Datatype properties | 92 |
| Closed value sets | 17 |
| Keys (owl:hasKey axioms) | 18 |
| Classes with a key | 17 |
| Restrictions | 100 |
| Restrictions on object properties | 19 |
| Restrictions on datatype properties | 81 |
| Subclass edges between TRIAD classes | 11 |
| Disjointness axioms | 3 |
| Tree nodes | 28 |
| Tree edges | 27 |

## 13. Design notes (decisions that the plan does not state)

- **`staffSex` and `patientSex`.** The plan does not name these two. Staff.Sex and Patient.Sex have the same value set, but a closed range is never shared (decision D10, the check of plan Phase 2). So each column gets its own property, with the class prefix of `careTeamStatus`.
- **`memberRole`** for `CareTeamMember.Role`. A `triad:role` would read like the discriminator `Staff.Role`.
- **`xsd:integer [≥ 1]` for `seq` and `rank`.** The plan gives `xsd:integer`. The facet keeps `xsd:integer` as the base, and it also holds the CHECK of the DDL. HermiT supports `xsd:minInclusive`.
- **Functional on the named inverses.** It is the same fact as the InverseFunctional characteristic of the stored property. It is valid, because the named inverses stay simple.
- **PROV-O domains and ranges.** The local copy of `prov:wasAttributedTo` and `prov:wasRevisionOf` has the domain and the range of PROV-O.
- **Licence of the ontology:** `dcterms:license` is CC BY-NC-SA 4.0, the licence of the repository (`LICENSE`). Open question 5 of the plan can change it.
- **More checks than the plan lists:** the value sets equal the DDL; each NOT NULL column has its restriction; each UNIQUE constraint is a key or has a reason; the domain of each datatype property is exactly the classes of its columns; each FK property has the domain and the range of its FK.
