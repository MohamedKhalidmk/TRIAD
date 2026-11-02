# TRIAD relational schema (Milestone 4)

This file maps the ER diagram (`../er/TRIAD_ERD.png`) to 29 relations.
The SQL is in `sql/01_create_tables.sql`. Report page 3 uses this list.

## Notation

- Each relation has a surrogate primary key **Id** (`INTEGER PRIMARY KEY AUTOINCREMENT`).
- **CK** is a candidate key (`UNIQUE` and `NOT NULL`). Each key of the ER diagram is a CK.
- **FK** is a foreign key. It points to the `Id` of the target relation. No foreign key cascades.
- `?` marks a column that can be NULL. All other columns are NOT NULL.
- **Ident** = IdentifierSystem, IdentifierValue (the FHIR Identifier of the entity).
- **Addr** = Street?, City?, Region?, PostalCode?, Country? (the composite attribute Address).
- Names: PascalCase. Constraints: `UK_<Table>_<Columns>`, `FK_<Table>_<Column>_2_<Target>_<Column>`.

## Relations

| # | Relation | Keys and foreign keys | Checks |
|---|---|---|---|
| 1 | Department(Id, Ident, Name, Type?, PhoneNumber?, Email?, Addr) | CK (IdentifierSystem, IdentifierValue) | — |
| 2 | Location(Id, Ident, Name, Type?, PhysicalType?, PhoneNumber?, Addr) | CK Ident | — |
| 3 | Staff(Id, Ident, Name, Sex?, Email?, PhoneNumber?, Active, Role) | CK Ident; CK (Id, Role) for the subtypes | Role ∈ {Doctor, Nurse, MOA}; Active ∈ {0, 1} |
| 4 | StaffLanguage(Id, StaffId, Language) | CK (StaffId, Language); FK StaffId → Staff | — |
| 5 | WorksIn(Id, StaffId, DepartmentId, RoleCode, Specialty?, StartDate?, EndDate?) | CK (StaffId, DepartmentId, RoleCode); FK StaffId → Staff; FK DepartmentId → Department | EndDate ≥ StartDate |
| 6 | Doctor(Id, StaffId, Role, LicenseNumber?, Qualification?) | CK StaffId; FK (StaffId, Role) → Staff (Id, Role) | Role = 'Doctor' |
| 7 | Nurse(Id, StaffId, Role, LicenseNumber?, Designation) | CK StaffId; FK (StaffId, Role) → Staff (Id, Role) | Role = 'Nurse'; Designation ∈ {RN, LPN, RPN, NP} |
| 8 | MOA(Id, StaffId, Role, CertificationNumber?, Desk, PhoneExtension?) | CK StaffId; FK (StaffId, Role) → Staff (Id, Role) | Role = 'MOA' |
| 9 | Patient(Id, Name, DateOfBirth, Sex, PhoneNumber?, Addr) | CK (Name, DateOfBirth) | DateOfBirth is a date; Sex ∈ {female, male, other, unknown} |
| 10 | PatientIdentifier(Id, PatientId, System, Value) | CK (System, Value); FK PatientId → Patient | — |
| 11 | Visit(Id, Ident, PatientId, Class, Type?, Reason?, StartDate, EndDate?) | CK Ident; FK PatientId → Patient (Has) | Class ∈ {AMB, EMER, IMP, HH, VR}; EndDate ≥ StartDate |
| 12 | VisitLocation(Id, VisitId, LocationId, StartDate, EndDate?) | CK (VisitId, LocationId, StartDate); FK VisitId → Visit; FK LocationId → Location (TakesPlaceIn) | EndDate ≥ StartDate |
| 13 | ClinicalEntry(Id, Ident, VisitId, Category, Code, CodeSystem, Display, Text?, RecordedAt) | CK Ident; CK (Id, Category) for the subtypes; FK VisitId → Visit (During, total) | Category ∈ the 8 subtypes |
| 14 | Diagnosis(Id, ClinicalEntryId, Category, OnsetDate?, AbatementDate?, ClinicalStatus, Severity?) | CK ClinicalEntryId; FK (ClinicalEntryId, Category) → ClinicalEntry (Id, Category) | Category = 'Diagnosis' |
| 15 | Procedure(Id, ClinicalEntryId, Category, PerformedDate, Outcome?) | as in 14 | Category = 'Procedure' |
| 16 | Allergy(Id, ClinicalEntryId, Category, Substance, Type?, AllergyCategory?, Criticality?, ClinicalStatus?) | as in 14 | Category = 'Allergy' |
| 17 | Observation(Id, ClinicalEntryId, Category, Value, Unit?) | as in 14 | Category = 'Observation' |
| 18 | LabOrder(Id, ClinicalEntryId, Category, TestName, Priority, Specimen?) | as in 14 | Priority ∈ {routine, urgent, asap, stat} |
| 19 | LabReport(Id, ClinicalEntryId, Category, IssuedDate, Conclusion?) | as in 14 | Category = 'LabReport' |
| 20 | Medication(Id, Code, CodeSystem, Name, Form?, Manufacturer?) | CK (Code, CodeSystem) | — |
| 21 | Prescription(Id, ClinicalEntryId, Category, MedicationId, Dosage?, Frequency?, Status) | as in 14; FK MedicationId → Medication (Prescribes) | Category = 'Prescription' |
| 22 | CareTeam(Id, ClinicalEntryId, Category, Name?, Status) | as in 14 | Status ∈ {proposed, active, suspended, inactive, entered-in-error} |
| 23 | CareTeamMember(Id, CareTeamId, MemberSystem, MemberValue, Role?) | CK (CareTeamId, MemberSystem, MemberValue); FK CareTeamId → CareTeam | the member is a staff Identifier (trigger) |
| 24 | Message(Id, Ident, StaffId?, Channel, Origin, SentAt, Text) | CK Ident; FK StaffId → Staff (Issues) | StaffId IS NOT NULL OR Origin = 'Patient' |
| 25 | Assertion(Id, MessageId, Seq, ClinicalEntryId, SupersedesId?, AssertedAt, Intent, Source, Verification, Statement) | CK (MessageId, Seq) (weak entity); CK SupersedesId (nullable, one-to-one); FK MessageId → Message (Contains); FK ClinicalEntryId → ClinicalEntry (About); FK SupersedesId → Assertion (Supersedes) | SupersedesId ≠ Id; Intent, Source and Verification value sets |
| 26 | ChatSession(Id, Ident, UserRole, UserSystem, UserValue, SubjectName, SubjectDateOfBirth, StartedAt, Mode, Model?) | CK Ident | Mode ∈ {rules, fake, llm}; user and subject are values |
| 27 | ChatTurn(Id, ChatSessionId, Seq, ClientTurnId, Speaker, Text, CreatedAt) | CK (ChatSessionId, Seq) (weak entity); CK (ChatSessionId, ClientTurnId); FK ChatSessionId → ChatSession (Includes) | Speaker ∈ {User, Assistant} |
| 28 | Citation(Id, ChatTurnId, AssertionId, Rank) | CK (ChatTurnId, AssertionId); FK ChatTurnId → ChatTurn; FK AssertionId → Assertion (Cites) | Rank ≥ 1 |
| 29 | AuditEvent(Id, Ident, At, Action, Outcome, ActorRole, ActorSystem, ActorValue, SubjectName, SubjectDateOfBirth, Path, ChatTurnId?) | CK Ident; FK ChatTurnId → ChatTurn (InTurn) | Outcome ∈ {Allowed, Denied}; actor and subject are values |

## Triggers

A CHECK constraint cannot read other rows. These triggers hold the rules that need other rows.

| Trigger | Rule |
|---|---|
| TR_Assertion_NoUpdate, TR_Assertion_NoDelete | Assertions are append-only. A correction is a new assertion that supersedes the old one. |
| TR_Assertion_Supersede_Check | The superseded assertion is not newer, and it is about the same patient (Entry → Visit → Patient). |
| TR_Assertion_One_Head_Per_Entry | Each entry has at most one current assertion. A new assertion about an entry with a current assertion must supersede it. |
| TR_Assertion_One_Patient_Per_Message | All assertions of a message are about one patient. |
| TR_CareTeamMember_Staff_Check | A care-team member matches one staff Identifier. |
| TR_Citation_Check | Only an assistant turn cites, and the cited assertion is about the patient of the session. |
| TR_AuditEvent_NoUpdate, TR_AuditEvent_NoDelete | Audit records are append-only. |
| TR_AuditEvent_Subject_Check | The subject of an audit record of a chat turn is the patient of that session. |
| TR_Patient_Key_NoUpdate | The name and the date of birth of a patient cannot change (the logs keep them). |

The application layer holds two more rules: each message has at least one assertion, and each clinical entry has at least one assertion. It creates them in one transaction.

## ER element → relation

| ER element | Relation(s) | Mapping rule (course manual §4.1) |
|---|---|---|
| Entity sets Department, Location, Staff, Patient, Visit, ClinicalEntry, Medication, Message, ChatSession, AuditEvent | 1, 2, 3, 9, 11, 13, 20, 24, 26, 29 | Each entity set is a relation. Its key is a CK. |
| Weak entity sets Assertion (owner Message), ChatTurn (owner ChatSession) | 25, 27 | The owner key (an FK) and the partial key *Seq* form a CK. |
| ISA Staff → Doctor, Nurse, MOA | 6, 7, 8 | One relation per subtype. The FK (StaffId, Role) makes it disjoint. |
| ISA ClinicalEntry → 8 subtypes | 14–19, 21, 22 | The same pattern with (ClinicalEntryId, Category). |
| Multivalued attributes Staff.Language, Patient.Identifier, CareTeam.Member | 4, 10, 23 | A separate relation with an FK to the owner. |
| Composite attributes Address, Identifier, User, Actor, Subject | columns | One column per component. |
| WorksIn (M:N, with attributes) | 5 | A separate relation with two FKs. |
| TakesPlaceIn (M:N, with attributes) | 12 | A separate relation with two FKs. |
| Cites (M:N, with Rank) | 28 | A separate relation with two FKs. |
| Has, During, Issues, About, Prescribes, InTurn (M:1) | FK columns in 11, 13, 24, 25, 21, 29 | An FK on the many side. |
| Contains, Includes (identifying) | FK columns in 25, 27 | An FK that is part of the weak-entity CK. |
| Supersedes (unary, 1:1) | 25 (SupersedesId) | A nullable FK with a UNIQUE constraint. |
