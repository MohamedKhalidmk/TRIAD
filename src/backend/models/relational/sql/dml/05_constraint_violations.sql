-- TRIAD constraint checks (Milestone 4). Each CASE below MUST FAIL with the EXPECT error.
-- Run this file on a COPY of the scenario database (01 + 02). The shell prints one error per case:
--     cp triad.db check.db && sqlite3 check.db < dml/05_constraint_violations.sql
-- The test src/backend/tests/integration/test_schema.py runs each case on a new copy.
-- Some cases first add a test patient. Each case uses its own test names, so the cases do not clash.

PRAGMA foreign_keys = ON;

-- CASE: duplicate patient key (Name, DateOfBirth)
-- EXPECT: UNIQUE constraint failed: Patient.Name, Patient.DateOfBirth
INSERT INTO Patient (Name, DateOfBirth, Sex) VALUES ('Elena Marsh', '1971-05-14', 'female');

-- CASE: duplicate patient identifier
-- EXPECT: UNIQUE constraint failed: PatientIdentifier.System, PatientIdentifier.Value
INSERT INTO PatientIdentifier (PatientId, System, Value)
VALUES ((SELECT Id FROM Patient WHERE Name = 'Elena Marsh'), 'https://triad.example/fhir/sid/mrn', 'MRN-000001');

-- CASE: a visit for a patient that does not exist
-- EXPECT: FOREIGN KEY constraint failed
INSERT INTO Visit (IdentifierSystem, IdentifierValue, PatientId, Class, StartDate)
VALUES ('https://triad.example/fhir', 'Encounter/no-patient', 99999, 'AMB', '2026-10-30T08:00:00-04:00');

-- CASE: ISA mismatch (a Nurse row for a staff member whose role is Doctor)
-- EXPECT: FOREIGN KEY constraint failed
INSERT INTO Nurse (StaffId, Designation)
VALUES ((SELECT Id FROM Staff WHERE IdentifierValue = 'E1005'), 'RN');

-- CASE: a subtype row with the wrong role value
-- EXPECT: CHECK constraint failed
INSERT INTO Doctor (StaffId, Role) VALUES ((SELECT Id FROM Staff WHERE IdentifierValue = 'E1002'), 'Nurse');

-- CASE: a nurse designation that is not in the value set
-- EXPECT: CHECK constraint failed
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E9001', 'Test Nurse', 'Nurse');
INSERT INTO Nurse (StaffId, Designation) VALUES ((SELECT Id FROM Staff WHERE IdentifierValue = 'E9001'), 'Chief');

-- CASE: a message with no issuer that does not come from the patient
-- EXPECT: CHECK constraint failed
INSERT INTO Message (IdentifierSystem, IdentifierValue, StaffId, Channel, Origin, SentAt, Text)
VALUES ('https://triad.example/fhir/sid/message', 'MSG-NO-ISSUER', NULL, 'Phone', 'Staff',
        '2026-10-30T08:00:00-04:00', 'No issuer.');

-- CASE: a channel that is not in the value set
-- EXPECT: CHECK constraint failed
INSERT INTO Message (IdentifierSystem, IdentifierValue, StaffId, Channel, Origin, SentAt, Text)
VALUES ('https://triad.example/fhir/sid/message', 'MSG-PIGEON', (SELECT Id FROM Staff WHERE IdentifierValue = 'E1001'),
        'Pigeon', 'Staff', '2026-10-30T08:00:00-04:00', 'Bad channel.');

-- CASE: a visit that ends before it starts
-- EXPECT: CHECK constraint failed
INSERT INTO Visit (IdentifierSystem, IdentifierValue, PatientId, Class, StartDate, EndDate)
VALUES ('https://triad.example/fhir', 'Encounter/bad-dates', (SELECT Id FROM Patient WHERE Name = 'Elena Marsh'),
        'AMB', '2026-10-30T10:00:00-04:00', '2026-10-30T09:00:00-04:00');

-- CASE: a visit class that is not in the value set
-- EXPECT: CHECK constraint failed
INSERT INTO Visit (IdentifierSystem, IdentifierValue, PatientId, Class, StartDate)
VALUES ('https://triad.example/fhir', 'Encounter/bad-class', (SELECT Id FROM Patient WHERE Name = 'Elena Marsh'),
        'XYZ', '2026-10-30T10:00:00-04:00');

-- CASE: a date of birth that is not a date
-- EXPECT: CHECK constraint failed
INSERT INTO Patient (Name, DateOfBirth, Sex) VALUES ('Test Patient Date', 'not a date', 'female');

-- CASE: change an assertion (assertions are append-only)
-- EXPECT: Assertion is append-only
UPDATE Assertion SET Statement = 'Changed.' WHERE Id = (SELECT MIN(Id) FROM Assertion);

-- CASE: delete an assertion (assertions are append-only)
-- EXPECT: Assertion is append-only
DELETE FROM Assertion WHERE Id = (SELECT MIN(Id) FROM Assertion);

-- CASE: a new claim about an entry that has a current assertion, without superseding it
-- EXPECT: The entry has a current assertion. The new assertion must supersede it.
INSERT INTO Assertion (MessageId, Seq, ClinicalEntryId, SupersedesId, AssertedAt, Intent, Source, Verification, Statement)
VALUES ((SELECT Id FROM Message WHERE IdentifierValue = 'MSG-ELENA-2026-10-02'), 99,
        (SELECT Id FROM ClinicalEntry WHERE IdentifierValue = 'AllergyIntolerance/ai-elena-penicillin'),
        NULL, '2026-10-30T08:00:00-04:00', 'Report', 'Human', 'Unconfirmed', 'Rash again.');

-- CASE: supersede an assertion that is newer than the new assertion
-- EXPECT: The superseded assertion is newer than the new assertion.
INSERT INTO Assertion (MessageId, Seq, ClinicalEntryId, SupersedesId, AssertedAt, Intent, Source, Verification, Statement)
VALUES ((SELECT Id FROM Message WHERE IdentifierValue = 'MSG-ELENA-2026-10-02'), 99,
        (SELECT Id FROM ClinicalEntry WHERE IdentifierValue = 'AllergyIntolerance/ai-elena-penicillin'),
        (SELECT a.Id FROM Assertion a JOIN ClinicalEntry e ON e.Id = a.ClinicalEntryId
         WHERE e.IdentifierValue = 'AllergyIntolerance/ai-elena-penicillin'
           AND NOT EXISTS (SELECT 1 FROM Assertion n WHERE n.SupersedesId = a.Id)),
        '2020-01-01T08:00:00-05:00', 'Report', 'Human', 'Unconfirmed', 'Old claim.');

-- CASE: a second assertion that supersedes the same assertion (Supersedes is one-to-one)
-- EXPECT: UNIQUE constraint failed: Assertion.SupersedesId
INSERT INTO ClinicalEntry (IdentifierSystem, IdentifierValue, VisitId, Category, Code, CodeSystem, Display, RecordedAt)
VALUES ('https://triad.example/fhir', 'Observation/test-second-superseder',
        (SELECT Id FROM Visit WHERE IdentifierValue = 'ENC-ELENA-2026-10-02'), 'Observation', '8867-4',
        'http://loinc.org', 'Heart rate', '2026-10-30T08:00:00-04:00');
INSERT INTO Assertion (MessageId, Seq, ClinicalEntryId, SupersedesId, AssertedAt, Intent, Source, Verification, Statement)
VALUES ((SELECT Id FROM Message WHERE IdentifierValue = 'MSG-ELENA-2026-10-02'), 99,
        (SELECT Id FROM ClinicalEntry WHERE IdentifierValue = 'Observation/test-second-superseder'),
        (SELECT MIN(a.Id) FROM Assertion a JOIN ClinicalEntry e ON e.Id = a.ClinicalEntryId
         WHERE e.IdentifierValue = 'AllergyIntolerance/ai-elena-penicillin'),
        '2026-10-30T08:00:00-04:00', 'Report', 'Human', 'Unconfirmed', 'A second superseder.');

-- CASE: supersede an assertion of another patient
-- EXPECT: The superseded assertion is about another patient.
INSERT INTO Patient (Name, DateOfBirth, Sex) VALUES ('Test Patient One', '1980-01-01', 'male');
INSERT INTO Visit (IdentifierSystem, IdentifierValue, PatientId, Class, StartDate)
VALUES ('https://triad.example/fhir', 'Encounter/test-one', (SELECT Id FROM Patient WHERE Name = 'Test Patient One'),
        'AMB', '2026-10-30T08:00:00-04:00');
INSERT INTO ClinicalEntry (IdentifierSystem, IdentifierValue, VisitId, Category, Code, CodeSystem, Display, RecordedAt)
VALUES ('https://triad.example/fhir', 'Observation/test-one', (SELECT Id FROM Visit WHERE IdentifierValue = 'Encounter/test-one'),
        'Observation', '8867-4', 'http://loinc.org', 'Heart rate', '2026-10-30T08:05:00-04:00');
INSERT INTO Message (IdentifierSystem, IdentifierValue, StaffId, Channel, Origin, SentAt, Text)
VALUES ('https://triad.example/fhir/sid/message', 'MSG-TEST-ONE', (SELECT Id FROM Staff WHERE IdentifierValue = 'E1002'),
        'InPerson', 'Staff', '2026-10-30T08:06:00-04:00', 'Heart rate 88.');
INSERT INTO Assertion (MessageId, Seq, ClinicalEntryId, SupersedesId, AssertedAt, Intent, Source, Verification, Statement)
VALUES ((SELECT Id FROM Message WHERE IdentifierValue = 'MSG-TEST-ONE'), 1,
        (SELECT Id FROM ClinicalEntry WHERE IdentifierValue = 'Observation/test-one'),
        (SELECT a.Id FROM Assertion a JOIN ClinicalEntry e ON e.Id = a.ClinicalEntryId
         WHERE e.IdentifierValue = 'AllergyIntolerance/ai-elena-penicillin'
           AND NOT EXISTS (SELECT 1 FROM Assertion n WHERE n.SupersedesId = a.Id)),
        '2026-10-30T08:06:00-04:00', 'Report', 'Human', 'Confirmed', 'Heart rate 88.');

-- CASE: one message with assertions about two patients
-- EXPECT: All assertions of a message must be about one patient.
INSERT INTO Patient (Name, DateOfBirth, Sex) VALUES ('Test Patient Two', '1981-02-02', 'female');
INSERT INTO Visit (IdentifierSystem, IdentifierValue, PatientId, Class, StartDate)
VALUES ('https://triad.example/fhir', 'Encounter/test-two', (SELECT Id FROM Patient WHERE Name = 'Test Patient Two'),
        'AMB', '2026-10-30T08:00:00-04:00');
INSERT INTO ClinicalEntry (IdentifierSystem, IdentifierValue, VisitId, Category, Code, CodeSystem, Display, RecordedAt)
VALUES ('https://triad.example/fhir', 'Observation/test-two', (SELECT Id FROM Visit WHERE IdentifierValue = 'Encounter/test-two'),
        'Observation', '8867-4', 'http://loinc.org', 'Heart rate', '2026-10-30T08:05:00-04:00');
INSERT INTO Assertion (MessageId, Seq, ClinicalEntryId, SupersedesId, AssertedAt, Intent, Source, Verification, Statement)
VALUES ((SELECT Id FROM Message WHERE IdentifierValue = 'MSG-ELENA-2026-10-02'), 99,
        (SELECT Id FROM ClinicalEntry WHERE IdentifierValue = 'Observation/test-two'),
        NULL, '2026-10-30T08:06:00-04:00', 'Report', 'Human', 'Confirmed', 'Heart rate 90.');

-- CASE: a care-team member that is not a staff member
-- EXPECT: The care-team member is not a staff member.
INSERT INTO CareTeamMember (CareTeamId, MemberSystem, MemberValue, Role)
VALUES ((SELECT MIN(Id) FROM CareTeam), 'https://triad.example/fhir/sid/employee', 'E0000', 'Nurse');

-- CASE: a citation from a user turn (only the assistant cites)
-- EXPECT: Only an assistant turn can cite an assertion.
INSERT INTO Citation (ChatTurnId, AssertionId, Rank)
VALUES ((SELECT Id FROM ChatTurn WHERE Speaker = 'User' LIMIT 1), (SELECT MIN(Id) FROM Assertion), 1);

-- CASE: a citation of an assertion about another patient
-- EXPECT: The cited assertion is not about the patient of the chat session.
INSERT INTO Patient (Name, DateOfBirth, Sex) VALUES ('Test Patient Three', '1982-03-03', 'male');
INSERT INTO Visit (IdentifierSystem, IdentifierValue, PatientId, Class, StartDate)
VALUES ('https://triad.example/fhir', 'Encounter/test-three', (SELECT Id FROM Patient WHERE Name = 'Test Patient Three'),
        'AMB', '2026-10-30T08:00:00-04:00');
INSERT INTO ClinicalEntry (IdentifierSystem, IdentifierValue, VisitId, Category, Code, CodeSystem, Display, RecordedAt)
VALUES ('https://triad.example/fhir', 'Observation/test-three', (SELECT Id FROM Visit WHERE IdentifierValue = 'Encounter/test-three'),
        'Observation', '8867-4', 'http://loinc.org', 'Heart rate', '2026-10-30T08:05:00-04:00');
INSERT INTO Message (IdentifierSystem, IdentifierValue, StaffId, Channel, Origin, SentAt, Text)
VALUES ('https://triad.example/fhir/sid/message', 'MSG-TEST-THREE', (SELECT Id FROM Staff WHERE IdentifierValue = 'E1002'),
        'InPerson', 'Staff', '2026-10-30T08:06:00-04:00', 'Heart rate 70.');
INSERT INTO Assertion (MessageId, Seq, ClinicalEntryId, SupersedesId, AssertedAt, Intent, Source, Verification, Statement)
VALUES ((SELECT Id FROM Message WHERE IdentifierValue = 'MSG-TEST-THREE'), 1,
        (SELECT Id FROM ClinicalEntry WHERE IdentifierValue = 'Observation/test-three'),
        NULL, '2026-10-30T08:06:00-04:00', 'Report', 'Human', 'Confirmed', 'Heart rate 70.');
INSERT INTO Citation (ChatTurnId, AssertionId, Rank)
VALUES ((SELECT Id FROM ChatTurn WHERE Speaker = 'Assistant' LIMIT 1),
        (SELECT a.Id FROM Assertion a JOIN Message m ON m.Id = a.MessageId WHERE m.IdentifierValue = 'MSG-TEST-THREE'), 2);

-- CASE: an audit record of a chat turn with another patient as subject
-- EXPECT: The audit subject is not the patient of the chat session.
INSERT INTO AuditEvent (IdentifierSystem, IdentifierValue, At, Action, Outcome, ActorRole, ActorSystem, ActorValue,
                        SubjectName, SubjectDateOfBirth, Path, ChatTurnId)
VALUES ('https://triad.example/fhir/sid/audit-event', 'AUDIT-TEST', '2026-10-30T08:00:00-04:00', 'ask', 'Allowed',
        'Doctor', 'https://triad.example/fhir/sid/employee', 'E1005', 'Someone Else', '1990-01-01',
        '/api/chat', (SELECT Id FROM ChatTurn WHERE Speaker = 'Assistant' LIMIT 1));

-- CASE: change an audit record (audit records are append-only)
-- EXPECT: AuditEvent is append-only.
UPDATE AuditEvent SET Path = '/changed' WHERE Id = (SELECT MIN(Id) FROM AuditEvent);

-- CASE: change the key of a patient (the logs keep Name and DateOfBirth as values)
-- EXPECT: The name and the date of birth of a patient cannot change.
UPDATE Patient SET Name = 'Elena M.' WHERE Name = 'Elena Marsh' AND DateOfBirth = '1971-05-14';

-- CASE: delete a patient who has visits (the app shows 409)
-- EXPECT: FOREIGN KEY constraint failed
DELETE FROM Patient WHERE Name = 'Elena Marsh' AND DateOfBirth = '1971-05-14';

-- CASE: delete a department that has staff (the app shows 409; journey Use case 8)
-- EXPECT: FOREIGN KEY constraint failed
DELETE FROM Department WHERE IdentifierValue = 'TRIAD-GH-EMER';
