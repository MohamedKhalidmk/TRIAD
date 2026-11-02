-- TRIAD relational schema (Milestone 4). SQLite 3.43 or later.
-- This script creates all 29 relations, their keys, the checks and the triggers.
-- Run it on a new, empty database:
--     sqlite3 triad.db < 01_create_tables.sql
-- The foreign keys follow the relationships of the ER diagram (a tree).
-- Values that hold a key (CareTeamMember, ChatSession, AuditEvent) have no foreign key. Triggers check them.

PRAGMA foreign_keys = ON;
PRAGMA user_version = 1;

-- ---------------------------------------------------------------------------
-- Directory: departments, locations, staff
-- ---------------------------------------------------------------------------

CREATE TABLE Department (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    IdentifierSystem TEXT NOT NULL,
    IdentifierValue TEXT NOT NULL,
    Name TEXT NOT NULL,
    Type TEXT,
    PhoneNumber TEXT,
    Email TEXT,
    Street TEXT,
    City TEXT,
    Region TEXT,
    PostalCode TEXT,
    Country TEXT,
    CONSTRAINT UK_Department_Identifier UNIQUE (IdentifierSystem, IdentifierValue)
);

CREATE TABLE Location (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    IdentifierSystem TEXT NOT NULL,
    IdentifierValue TEXT NOT NULL,
    Name TEXT NOT NULL,
    Type TEXT,
    PhysicalType TEXT,
    PhoneNumber TEXT,
    Street TEXT,
    City TEXT,
    Region TEXT,
    PostalCode TEXT,
    Country TEXT,
    CONSTRAINT UK_Location_Identifier UNIQUE (IdentifierSystem, IdentifierValue)
);

CREATE TABLE Staff (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    IdentifierSystem TEXT NOT NULL,
    IdentifierValue TEXT NOT NULL,
    Name TEXT NOT NULL,
    Sex TEXT CHECK (Sex IN ('female', 'male', 'other', 'unknown')),
    Email TEXT,
    PhoneNumber TEXT,
    Active INTEGER NOT NULL DEFAULT 1 CHECK (Active IN (0, 1)),
    Role TEXT NOT NULL CHECK (Role IN ('Doctor', 'Nurse', 'MOA')),
    CONSTRAINT UK_Staff_Identifier UNIQUE (IdentifierSystem, IdentifierValue),
    CONSTRAINT UK_Staff_Id_Role UNIQUE (Id, Role)
);

-- Multivalued attribute Staff.Language.
CREATE TABLE StaffLanguage (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    StaffId INTEGER NOT NULL,
    Language TEXT NOT NULL,
    CONSTRAINT UK_StaffLanguage_StaffId_Language UNIQUE (StaffId, Language),
    CONSTRAINT FK_StaffLanguage_StaffId_2_Staff_Id FOREIGN KEY (StaffId) REFERENCES Staff (Id)
);

-- Relationship WorksIn (M:N, FHIR PractitionerRole).
CREATE TABLE WorksIn (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    StaffId INTEGER NOT NULL,
    DepartmentId INTEGER NOT NULL,
    RoleCode TEXT NOT NULL,
    Specialty TEXT,
    StartDate TEXT CHECK (StartDate IS NULL OR julianday(StartDate) IS NOT NULL),
    EndDate TEXT CHECK (EndDate IS NULL OR julianday(EndDate) IS NOT NULL),
    CONSTRAINT UK_WorksIn_StaffId_DepartmentId_RoleCode UNIQUE (StaffId, DepartmentId, RoleCode),
    CONSTRAINT FK_WorksIn_StaffId_2_Staff_Id FOREIGN KEY (StaffId) REFERENCES Staff (Id),
    CONSTRAINT FK_WorksIn_DepartmentId_2_Department_Id FOREIGN KEY (DepartmentId) REFERENCES Department (Id),
    CHECK (EndDate IS NULL OR StartDate IS NULL OR julianday(EndDate) >= julianday(StartDate))
);

-- ISA Staff -> Doctor | Nurse | MOA (disjoint, total).
-- The composite foreign key (StaffId, Role) makes a subtype row match Staff.Role.
CREATE TABLE Doctor (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    StaffId INTEGER NOT NULL,
    Role TEXT NOT NULL DEFAULT 'Doctor' CHECK (Role = 'Doctor'),
    LicenseNumber TEXT,
    Qualification TEXT,
    CONSTRAINT UK_Doctor_StaffId UNIQUE (StaffId),
    CONSTRAINT FK_Doctor_StaffId_Role_2_Staff_Id_Role FOREIGN KEY (StaffId, Role) REFERENCES Staff (Id, Role)
);

CREATE TABLE Nurse (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    StaffId INTEGER NOT NULL,
    Role TEXT NOT NULL DEFAULT 'Nurse' CHECK (Role = 'Nurse'),
    LicenseNumber TEXT,
    Designation TEXT NOT NULL CHECK (Designation IN ('RN', 'LPN', 'RPN', 'NP')),
    CONSTRAINT UK_Nurse_StaffId UNIQUE (StaffId),
    CONSTRAINT FK_Nurse_StaffId_Role_2_Staff_Id_Role FOREIGN KEY (StaffId, Role) REFERENCES Staff (Id, Role)
);

CREATE TABLE MOA (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    StaffId INTEGER NOT NULL,
    Role TEXT NOT NULL DEFAULT 'MOA' CHECK (Role = 'MOA'),
    CertificationNumber TEXT,
    Desk TEXT NOT NULL,
    PhoneExtension TEXT,
    CONSTRAINT UK_MOA_StaffId UNIQUE (StaffId),
    CONSTRAINT FK_MOA_StaffId_Role_2_Staff_Id_Role FOREIGN KEY (StaffId, Role) REFERENCES Staff (Id, Role)
);

-- ---------------------------------------------------------------------------
-- Patients and visits
-- ---------------------------------------------------------------------------

CREATE TABLE Patient (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    Name TEXT NOT NULL,
    DateOfBirth TEXT NOT NULL CHECK (date(DateOfBirth) IS NOT NULL),
    Sex TEXT NOT NULL CHECK (Sex IN ('female', 'male', 'other', 'unknown')),
    PhoneNumber TEXT,
    Street TEXT,
    City TEXT,
    Region TEXT,
    PostalCode TEXT,
    Country TEXT,
    CONSTRAINT UK_Patient_Name_DateOfBirth UNIQUE (Name, DateOfBirth)
);

-- Multivalued composite attribute Patient.Identifier (PHN, MRN, SSN, ...).
CREATE TABLE PatientIdentifier (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    PatientId INTEGER NOT NULL,
    System TEXT NOT NULL,
    Value TEXT NOT NULL,
    CONSTRAINT UK_PatientIdentifier_System_Value UNIQUE (System, Value),
    CONSTRAINT FK_PatientIdentifier_PatientId_2_Patient_Id FOREIGN KEY (PatientId) REFERENCES Patient (Id)
);

-- Relationship Has (Patient 1 : Visit N) is the foreign key PatientId.
CREATE TABLE Visit (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    IdentifierSystem TEXT NOT NULL,
    IdentifierValue TEXT NOT NULL,
    PatientId INTEGER NOT NULL,
    Class TEXT NOT NULL CHECK (Class IN ('AMB', 'EMER', 'IMP', 'HH', 'VR')),
    Type TEXT,
    Reason TEXT,
    StartDate TEXT NOT NULL CHECK (julianday(StartDate) IS NOT NULL),
    EndDate TEXT CHECK (EndDate IS NULL OR julianday(EndDate) IS NOT NULL),
    CONSTRAINT UK_Visit_Identifier UNIQUE (IdentifierSystem, IdentifierValue),
    CONSTRAINT FK_Visit_PatientId_2_Patient_Id FOREIGN KEY (PatientId) REFERENCES Patient (Id),
    CHECK (EndDate IS NULL OR julianday(EndDate) >= julianday(StartDate))
);

-- Relationship TakesPlaceIn (Visit M : Location N).
CREATE TABLE VisitLocation (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    VisitId INTEGER NOT NULL,
    LocationId INTEGER NOT NULL,
    StartDate TEXT NOT NULL CHECK (julianday(StartDate) IS NOT NULL),
    EndDate TEXT CHECK (EndDate IS NULL OR julianday(EndDate) IS NOT NULL),
    CONSTRAINT UK_VisitLocation_VisitId_LocationId_StartDate UNIQUE (VisitId, LocationId, StartDate),
    CONSTRAINT FK_VisitLocation_VisitId_2_Visit_Id FOREIGN KEY (VisitId) REFERENCES Visit (Id),
    CONSTRAINT FK_VisitLocation_LocationId_2_Location_Id FOREIGN KEY (LocationId) REFERENCES Location (Id),
    CHECK (EndDate IS NULL OR julianday(EndDate) >= julianday(StartDate))
);

-- ---------------------------------------------------------------------------
-- Clinical entries (ISA, disjoint and total) and medications
-- ---------------------------------------------------------------------------

-- Relationship During (ClinicalEntry N : Visit 1, total) is the foreign key VisitId.
CREATE TABLE ClinicalEntry (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    IdentifierSystem TEXT NOT NULL,
    IdentifierValue TEXT NOT NULL,
    VisitId INTEGER NOT NULL,
    Category TEXT NOT NULL CHECK (Category IN ('Diagnosis', 'Procedure', 'Allergy', 'Observation',
                                               'LabOrder', 'LabReport', 'Prescription', 'CareTeam')),
    Code TEXT NOT NULL,
    CodeSystem TEXT NOT NULL,
    Display TEXT NOT NULL,
    Text TEXT,
    RecordedAt TEXT NOT NULL CHECK (julianday(RecordedAt) IS NOT NULL),
    CONSTRAINT UK_ClinicalEntry_Identifier UNIQUE (IdentifierSystem, IdentifierValue),
    CONSTRAINT UK_ClinicalEntry_Id_Category UNIQUE (Id, Category),
    CONSTRAINT FK_ClinicalEntry_VisitId_2_Visit_Id FOREIGN KEY (VisitId) REFERENCES Visit (Id)
);

CREATE TABLE Diagnosis (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    ClinicalEntryId INTEGER NOT NULL,
    Category TEXT NOT NULL DEFAULT 'Diagnosis' CHECK (Category = 'Diagnosis'),
    OnsetDate TEXT,
    AbatementDate TEXT,
    ClinicalStatus TEXT NOT NULL,
    Severity TEXT,
    CONSTRAINT UK_Diagnosis_ClinicalEntryId UNIQUE (ClinicalEntryId),
    CONSTRAINT FK_Diagnosis_ClinicalEntryId_Category_2_ClinicalEntry_Id_Category
        FOREIGN KEY (ClinicalEntryId, Category) REFERENCES ClinicalEntry (Id, Category)
);

CREATE TABLE Procedure (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    ClinicalEntryId INTEGER NOT NULL,
    Category TEXT NOT NULL DEFAULT 'Procedure' CHECK (Category = 'Procedure'),
    PerformedDate TEXT NOT NULL CHECK (julianday(PerformedDate) IS NOT NULL),
    Outcome TEXT,
    CONSTRAINT UK_Procedure_ClinicalEntryId UNIQUE (ClinicalEntryId),
    CONSTRAINT FK_Procedure_ClinicalEntryId_Category_2_ClinicalEntry_Id_Category
        FOREIGN KEY (ClinicalEntryId, Category) REFERENCES ClinicalEntry (Id, Category)
);

CREATE TABLE Allergy (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    ClinicalEntryId INTEGER NOT NULL,
    Category TEXT NOT NULL DEFAULT 'Allergy' CHECK (Category = 'Allergy'),
    Substance TEXT NOT NULL,
    Type TEXT,
    AllergyCategory TEXT,
    Criticality TEXT,
    ClinicalStatus TEXT,
    CONSTRAINT UK_Allergy_ClinicalEntryId UNIQUE (ClinicalEntryId),
    CONSTRAINT FK_Allergy_ClinicalEntryId_Category_2_ClinicalEntry_Id_Category
        FOREIGN KEY (ClinicalEntryId, Category) REFERENCES ClinicalEntry (Id, Category)
);

CREATE TABLE Observation (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    ClinicalEntryId INTEGER NOT NULL,
    Category TEXT NOT NULL DEFAULT 'Observation' CHECK (Category = 'Observation'),
    Value TEXT NOT NULL,
    Unit TEXT,
    CONSTRAINT UK_Observation_ClinicalEntryId UNIQUE (ClinicalEntryId),
    CONSTRAINT FK_Observation_ClinicalEntryId_Category_2_ClinicalEntry_Id_Category
        FOREIGN KEY (ClinicalEntryId, Category) REFERENCES ClinicalEntry (Id, Category)
);

CREATE TABLE LabOrder (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    ClinicalEntryId INTEGER NOT NULL,
    Category TEXT NOT NULL DEFAULT 'LabOrder' CHECK (Category = 'LabOrder'),
    TestName TEXT NOT NULL,
    Priority TEXT NOT NULL CHECK (Priority IN ('routine', 'urgent', 'asap', 'stat')),
    Specimen TEXT,
    CONSTRAINT UK_LabOrder_ClinicalEntryId UNIQUE (ClinicalEntryId),
    CONSTRAINT FK_LabOrder_ClinicalEntryId_Category_2_ClinicalEntry_Id_Category
        FOREIGN KEY (ClinicalEntryId, Category) REFERENCES ClinicalEntry (Id, Category)
);

CREATE TABLE LabReport (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    ClinicalEntryId INTEGER NOT NULL,
    Category TEXT NOT NULL DEFAULT 'LabReport' CHECK (Category = 'LabReport'),
    IssuedDate TEXT NOT NULL CHECK (julianday(IssuedDate) IS NOT NULL),
    Conclusion TEXT,
    CONSTRAINT UK_LabReport_ClinicalEntryId UNIQUE (ClinicalEntryId),
    CONSTRAINT FK_LabReport_ClinicalEntryId_Category_2_ClinicalEntry_Id_Category
        FOREIGN KEY (ClinicalEntryId, Category) REFERENCES ClinicalEntry (Id, Category)
);

CREATE TABLE Medication (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    Code TEXT NOT NULL,
    CodeSystem TEXT NOT NULL,
    Name TEXT NOT NULL,
    Form TEXT,
    Manufacturer TEXT,
    CONSTRAINT UK_Medication_Code_CodeSystem UNIQUE (Code, CodeSystem)
);

-- Relationship Prescribes (Prescription N : Medication 1) is the foreign key MedicationId.
CREATE TABLE Prescription (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    ClinicalEntryId INTEGER NOT NULL,
    Category TEXT NOT NULL DEFAULT 'Prescription' CHECK (Category = 'Prescription'),
    MedicationId INTEGER NOT NULL,
    Dosage TEXT,
    Frequency TEXT,
    Status TEXT NOT NULL,
    CONSTRAINT UK_Prescription_ClinicalEntryId UNIQUE (ClinicalEntryId),
    CONSTRAINT FK_Prescription_ClinicalEntryId_Category_2_ClinicalEntry_Id_Category
        FOREIGN KEY (ClinicalEntryId, Category) REFERENCES ClinicalEntry (Id, Category),
    CONSTRAINT FK_Prescription_MedicationId_2_Medication_Id FOREIGN KEY (MedicationId) REFERENCES Medication (Id)
);

CREATE TABLE CareTeam (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    ClinicalEntryId INTEGER NOT NULL,
    Category TEXT NOT NULL DEFAULT 'CareTeam' CHECK (Category = 'CareTeam'),
    Name TEXT,
    Status TEXT NOT NULL CHECK (Status IN ('proposed', 'active', 'suspended', 'inactive', 'entered-in-error')),
    CONSTRAINT UK_CareTeam_ClinicalEntryId UNIQUE (ClinicalEntryId),
    CONSTRAINT FK_CareTeam_ClinicalEntryId_Category_2_ClinicalEntry_Id_Category
        FOREIGN KEY (ClinicalEntryId, Category) REFERENCES ClinicalEntry (Id, Category)
);

-- Multivalued composite attribute CareTeam.Member (Identifier, Role).
-- The member is a staff Identifier as a value (a FHIR reference by identifier). A trigger checks it.
CREATE TABLE CareTeamMember (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    CareTeamId INTEGER NOT NULL,
    MemberSystem TEXT NOT NULL,
    MemberValue TEXT NOT NULL,
    Role TEXT,
    CONSTRAINT UK_CareTeamMember_CareTeamId_Member UNIQUE (CareTeamId, MemberSystem, MemberValue),
    CONSTRAINT FK_CareTeamMember_CareTeamId_2_CareTeam_Id FOREIGN KEY (CareTeamId) REFERENCES CareTeam (Id)
);

-- ---------------------------------------------------------------------------
-- Authorship: messages and assertions (TRIAD core)
-- ---------------------------------------------------------------------------

-- Relationship Issues (Staff 0..1 : Message N) is the foreign key StaffId.
-- A message with no issuer comes from the patient (Origin = 'Patient').
CREATE TABLE Message (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    IdentifierSystem TEXT NOT NULL,
    IdentifierValue TEXT NOT NULL,
    StaffId INTEGER,
    Channel TEXT NOT NULL CHECK (Channel IN ('InPerson', 'Phone', 'Video', 'Email', 'Fax', 'Transfer', 'Chat', 'App')),
    Origin TEXT NOT NULL CHECK (Origin IN ('Patient', 'Staff', 'OtherClinic', 'PharmaNet', 'Lab', 'Agent')),
    SentAt TEXT NOT NULL CHECK (julianday(SentAt) IS NOT NULL),
    Text TEXT NOT NULL,
    CONSTRAINT UK_Message_Identifier UNIQUE (IdentifierSystem, IdentifierValue),
    CONSTRAINT FK_Message_StaffId_2_Staff_Id FOREIGN KEY (StaffId) REFERENCES Staff (Id),
    CHECK (StaffId IS NOT NULL OR Origin = 'Patient')
);

-- Weak entity Assertion: owner Message (identifying relationship Contains), partial key Seq.
-- About (Assertion N : ClinicalEntry 1) and Supersedes (unary, 1:1) are foreign keys.
CREATE TABLE Assertion (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    MessageId INTEGER NOT NULL,
    Seq INTEGER NOT NULL CHECK (Seq >= 1),
    ClinicalEntryId INTEGER NOT NULL,
    SupersedesId INTEGER,
    AssertedAt TEXT NOT NULL CHECK (julianday(AssertedAt) IS NOT NULL),
    Intent TEXT NOT NULL CHECK (Intent IN ('Report', 'Recommendation', 'Decision')),
    Source TEXT NOT NULL CHECK (Source IN ('Human', 'Agent')),
    Verification TEXT NOT NULL CHECK (Verification IN ('Unconfirmed', 'Provisional', 'Differential',
                                                       'Confirmed', 'Refuted', 'EnteredInError')),
    Statement TEXT NOT NULL,
    CONSTRAINT UK_Assertion_MessageId_Seq UNIQUE (MessageId, Seq),
    CONSTRAINT UK_Assertion_SupersedesId UNIQUE (SupersedesId),
    CONSTRAINT FK_Assertion_MessageId_2_Message_Id FOREIGN KEY (MessageId) REFERENCES Message (Id),
    CONSTRAINT FK_Assertion_ClinicalEntryId_2_ClinicalEntry_Id FOREIGN KEY (ClinicalEntryId) REFERENCES ClinicalEntry (Id),
    CONSTRAINT FK_Assertion_SupersedesId_2_Assertion_Id FOREIGN KEY (SupersedesId) REFERENCES Assertion (Id),
    CHECK (SupersedesId IS NULL OR SupersedesId <> Id)
);

-- ---------------------------------------------------------------------------
-- Agent layer and audit log
-- ---------------------------------------------------------------------------

-- A chat session is a log. It keeps the user and the patient (Subject) as values.
CREATE TABLE ChatSession (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    IdentifierSystem TEXT NOT NULL,
    IdentifierValue TEXT NOT NULL,
    UserRole TEXT NOT NULL CHECK (UserRole IN ('Patient', 'Doctor', 'Nurse', 'MOA')),
    UserSystem TEXT NOT NULL,
    UserValue TEXT NOT NULL,
    SubjectName TEXT NOT NULL,
    SubjectDateOfBirth TEXT NOT NULL,
    StartedAt TEXT NOT NULL CHECK (julianday(StartedAt) IS NOT NULL),
    Mode TEXT NOT NULL CHECK (Mode IN ('rules', 'fake', 'llm')),
    Model TEXT,
    CONSTRAINT UK_ChatSession_Identifier UNIQUE (IdentifierSystem, IdentifierValue)
);

-- Weak entity ChatTurn: owner ChatSession (identifying relationship Includes), partial key Seq.
CREATE TABLE ChatTurn (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    ChatSessionId INTEGER NOT NULL,
    Seq INTEGER NOT NULL CHECK (Seq >= 1),
    ClientTurnId TEXT NOT NULL,
    Speaker TEXT NOT NULL CHECK (Speaker IN ('User', 'Assistant')),
    Text TEXT NOT NULL,
    CreatedAt TEXT NOT NULL CHECK (julianday(CreatedAt) IS NOT NULL),
    CONSTRAINT UK_ChatTurn_ChatSessionId_Seq UNIQUE (ChatSessionId, Seq),
    CONSTRAINT UK_ChatTurn_ChatSessionId_ClientTurnId UNIQUE (ChatSessionId, ClientTurnId),
    CONSTRAINT FK_ChatTurn_ChatSessionId_2_ChatSession_Id FOREIGN KEY (ChatSessionId) REFERENCES ChatSession (Id)
);

-- Relationship Cites (ChatTurn M : Assertion N), with the attribute Rank.
CREATE TABLE Citation (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    ChatTurnId INTEGER NOT NULL,
    AssertionId INTEGER NOT NULL,
    Rank INTEGER NOT NULL CHECK (Rank >= 1),
    CONSTRAINT UK_Citation_ChatTurnId_AssertionId UNIQUE (ChatTurnId, AssertionId),
    CONSTRAINT FK_Citation_ChatTurnId_2_ChatTurn_Id FOREIGN KEY (ChatTurnId) REFERENCES ChatTurn (Id),
    CONSTRAINT FK_Citation_AssertionId_2_Assertion_Id FOREIGN KEY (AssertionId) REFERENCES Assertion (Id)
);

-- An audit record is a log. It keeps the actor and the patient (Subject) as values.
-- Relationship InTurn (AuditEvent N : ChatTurn 0..1) is the foreign key ChatTurnId.
CREATE TABLE AuditEvent (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    IdentifierSystem TEXT NOT NULL,
    IdentifierValue TEXT NOT NULL,
    At TEXT NOT NULL CHECK (julianday(At) IS NOT NULL),
    Action TEXT NOT NULL CHECK (Action IN ('read', 'create', 'update', 'delete', 'ask', 'tell')),
    Outcome TEXT NOT NULL CHECK (Outcome IN ('Allowed', 'Denied')),
    ActorRole TEXT NOT NULL CHECK (ActorRole IN ('Patient', 'Doctor', 'Nurse', 'MOA')),
    ActorSystem TEXT NOT NULL,
    ActorValue TEXT NOT NULL,
    SubjectName TEXT NOT NULL,
    SubjectDateOfBirth TEXT NOT NULL,
    Path TEXT NOT NULL,
    ChatTurnId INTEGER,
    CONSTRAINT UK_AuditEvent_Identifier UNIQUE (IdentifierSystem, IdentifierValue),
    CONSTRAINT FK_AuditEvent_ChatTurnId_2_ChatTurn_Id FOREIGN KEY (ChatTurnId) REFERENCES ChatTurn (Id)
);

-- ---------------------------------------------------------------------------
-- Indexes on foreign keys and on frequent searches
-- ---------------------------------------------------------------------------

CREATE INDEX IX_WorksIn_DepartmentId ON WorksIn (DepartmentId);
CREATE INDEX IX_PatientIdentifier_PatientId ON PatientIdentifier (PatientId);
CREATE INDEX IX_Visit_PatientId ON Visit (PatientId);
CREATE INDEX IX_VisitLocation_LocationId ON VisitLocation (LocationId);
CREATE INDEX IX_ClinicalEntry_VisitId ON ClinicalEntry (VisitId);
CREATE INDEX IX_ClinicalEntry_Category_Code ON ClinicalEntry (Category, Code);
CREATE INDEX IX_Prescription_MedicationId ON Prescription (MedicationId);
CREATE INDEX IX_CareTeamMember_Member ON CareTeamMember (MemberSystem, MemberValue);
CREATE INDEX IX_Message_StaffId ON Message (StaffId);
CREATE INDEX IX_Assertion_ClinicalEntryId ON Assertion (ClinicalEntryId);
CREATE INDEX IX_Citation_AssertionId ON Citation (AssertionId);
CREATE INDEX IX_AuditEvent_Subject ON AuditEvent (SubjectName, SubjectDateOfBirth);
CREATE INDEX IX_AuditEvent_ChatTurnId ON AuditEvent (ChatTurnId);
CREATE INDEX IX_ChatSession_Subject ON ChatSession (SubjectName, SubjectDateOfBirth);

-- ---------------------------------------------------------------------------
-- Triggers (rules that a CHECK cannot hold, because a CHECK cannot read other rows)
-- ---------------------------------------------------------------------------

-- Assertions are append-only. A correction is a new assertion that supersedes the old one.
CREATE TRIGGER TR_Assertion_NoUpdate BEFORE UPDATE ON Assertion
BEGIN
    SELECT RAISE(ABORT, 'Assertion is append-only. Add a new assertion that supersedes it.');
END;

CREATE TRIGGER TR_Assertion_NoDelete BEFORE DELETE ON Assertion
BEGIN
    SELECT RAISE(ABORT, 'Assertion is append-only. Add a new assertion that supersedes it.');
END;

-- The superseded assertion is not newer, and it is about the same patient.
CREATE TRIGGER TR_Assertion_Supersede_Check BEFORE INSERT ON Assertion
WHEN NEW.SupersedesId IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'The superseded assertion is newer than the new assertion.')
    WHERE (SELECT julianday(AssertedAt) FROM Assertion WHERE Id = NEW.SupersedesId) > julianday(NEW.AssertedAt);
    SELECT RAISE(ABORT, 'The superseded assertion is about another patient.')
    WHERE (SELECT v.PatientId FROM Assertion a
               JOIN ClinicalEntry e ON e.Id = a.ClinicalEntryId
               JOIN Visit v ON v.Id = e.VisitId
           WHERE a.Id = NEW.SupersedesId)
       <> (SELECT v.PatientId FROM ClinicalEntry e JOIN Visit v ON v.Id = e.VisitId
           WHERE e.Id = NEW.ClinicalEntryId);
END;

-- Each entry has at most one current assertion: a new assertion about an entry
-- that has a current assertion must supersede that assertion.
CREATE TRIGGER TR_Assertion_One_Head_Per_Entry BEFORE INSERT ON Assertion
BEGIN
    SELECT RAISE(ABORT, 'The entry has a current assertion. The new assertion must supersede it.')
    WHERE EXISTS (
        SELECT 1 FROM Assertion h
        WHERE h.ClinicalEntryId = NEW.ClinicalEntryId
          AND NOT EXISTS (SELECT 1 FROM Assertion s WHERE s.SupersedesId = h.Id)
          AND (NEW.SupersedesId IS NULL OR NEW.SupersedesId <> h.Id)
    );
END;

-- All assertions of one message are about one patient.
CREATE TRIGGER TR_Assertion_One_Patient_Per_Message BEFORE INSERT ON Assertion
BEGIN
    SELECT RAISE(ABORT, 'All assertions of a message must be about one patient.')
    WHERE EXISTS (
        SELECT 1 FROM Assertion a
            JOIN ClinicalEntry e ON e.Id = a.ClinicalEntryId
            JOIN Visit v ON v.Id = e.VisitId
        WHERE a.MessageId = NEW.MessageId
          AND v.PatientId <> (SELECT v2.PatientId FROM ClinicalEntry e2 JOIN Visit v2 ON v2.Id = e2.VisitId
                              WHERE e2.Id = NEW.ClinicalEntryId)
    );
END;

-- A care-team member must be one staff member (the value holds the staff key).
CREATE TRIGGER TR_CareTeamMember_Staff_Check BEFORE INSERT ON CareTeamMember
BEGIN
    SELECT RAISE(ABORT, 'The care-team member is not a staff member.')
    WHERE NOT EXISTS (SELECT 1 FROM Staff
                      WHERE IdentifierSystem = NEW.MemberSystem AND IdentifierValue = NEW.MemberValue);
END;

-- A citation comes from an assistant turn, and the cited assertion is about the patient of the session.
CREATE TRIGGER TR_Citation_Check BEFORE INSERT ON Citation
BEGIN
    SELECT RAISE(ABORT, 'Only an assistant turn can cite an assertion.')
    WHERE (SELECT Speaker FROM ChatTurn WHERE Id = NEW.ChatTurnId) <> 'Assistant';
    SELECT RAISE(ABORT, 'The cited assertion is not about the patient of the chat session.')
    WHERE NOT EXISTS (
        SELECT 1 FROM ChatTurn t
            JOIN ChatSession s ON s.Id = t.ChatSessionId
            JOIN Assertion a ON a.Id = NEW.AssertionId
            JOIN ClinicalEntry e ON e.Id = a.ClinicalEntryId
            JOIN Visit v ON v.Id = e.VisitId
            JOIN Patient p ON p.Id = v.PatientId
        WHERE t.Id = NEW.ChatTurnId
          AND p.Name = s.SubjectName AND p.DateOfBirth = s.SubjectDateOfBirth
    );
END;

-- Audit records are append-only. An audit record of a chat turn has the patient of that session.
CREATE TRIGGER TR_AuditEvent_NoUpdate BEFORE UPDATE ON AuditEvent
BEGIN
    SELECT RAISE(ABORT, 'AuditEvent is append-only.');
END;

CREATE TRIGGER TR_AuditEvent_NoDelete BEFORE DELETE ON AuditEvent
BEGIN
    SELECT RAISE(ABORT, 'AuditEvent is append-only.');
END;

CREATE TRIGGER TR_AuditEvent_Subject_Check BEFORE INSERT ON AuditEvent
WHEN NEW.ChatTurnId IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'The audit subject is not the patient of the chat session.')
    WHERE NOT EXISTS (
        SELECT 1 FROM ChatTurn t JOIN ChatSession s ON s.Id = t.ChatSessionId
        WHERE t.Id = NEW.ChatTurnId
          AND s.SubjectName = NEW.SubjectName AND s.SubjectDateOfBirth = NEW.SubjectDateOfBirth
    );
END;

-- The patient key (Name, DateOfBirth) does not change, because the logs keep it as a value.
CREATE TRIGGER TR_Patient_Key_NoUpdate BEFORE UPDATE OF Name, DateOfBirth ON Patient
WHEN NEW.Name <> OLD.Name OR NEW.DateOfBirth <> OLD.DateOfBirth
BEGIN
    SELECT RAISE(ABORT, 'The name and the date of birth of a patient cannot change.');
END;
