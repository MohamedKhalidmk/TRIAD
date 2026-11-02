-- TRIAD INSERT, UPDATE and DELETE examples (Milestone 4).
-- Run this file on a COPY of the database, because it changes the data:
--     cp triad.db demo.db && sqlite3 demo.db < dml/04_update_delete.sql
-- Each statement must succeed. 05_constraint_violations.sql shows the statements that must fail.

PRAGMA foreign_keys = ON;

-- 1. UPDATE: a patient gives a new phone number (journey step 1). The key (Name, DateOfBirth) does not change.
UPDATE Patient SET PhoneNumber = '+1-508-555-0199'
WHERE Name = 'Elena Marsh' AND DateOfBirth = '1971-05-14';

-- 2. UPDATE: a staff member gets a new phone number (journey step 8).
UPDATE Staff SET PhoneNumber = '+1-508-555-2999'
WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1001';

-- 3. DELETE: remove a location that no visit uses (journey step 8).
DELETE FROM Location
WHERE IdentifierSystem = 'https://triad.example/fhir/sid/location' AND IdentifierValue = 'STORE-OLD'
  AND NOT EXISTS (SELECT 1 FROM VisitLocation vl WHERE vl.LocationId = Location.Id);

-- 4. INSERT, UPDATE and DELETE of a medication that no prescription uses.
INSERT INTO Medication (Code, CodeSystem, Name, Form)
VALUES ('00000000', 'http://hl7.org/fhir/NamingSystem/ca-hc-din', 'Test medication 10 mg tablet', NULL);
UPDATE Medication SET Form = 'Tablet'
WHERE Code = '00000000' AND CodeSystem = 'http://hl7.org/fhir/NamingSystem/ca-hc-din';
DELETE FROM Medication
WHERE Code = '00000000' AND CodeSystem = 'http://hl7.org/fhir/NamingSystem/ca-hc-din';

-- 5. INSERT (TRIAD): the patient reports a fact through the app. The message has no staff issuer
--    (Origin = 'Patient'). The new assertion is about the amlodipine entry, and it supersedes the
--    current assertion of that entry. The old assertion stays; nothing is overwritten.
INSERT INTO Message (IdentifierSystem, IdentifierValue, StaffId, Channel, Origin, SentAt, Text)
VALUES ('https://triad.example/fhir/sid/message', 'MSG-ELENA-APP-0001', NULL, 'App', 'Patient',
        '2026-10-30T08:30:00-04:00', 'I take amlodipine every morning.');

INSERT INTO Assertion (MessageId, Seq, ClinicalEntryId, SupersedesId, AssertedAt, Intent, Source,
                       Verification, Statement)
VALUES ((SELECT Id FROM Message WHERE IdentifierSystem = 'https://triad.example/fhir/sid/message'
                                  AND IdentifierValue = 'MSG-ELENA-APP-0001'),
        1,
        (SELECT Id FROM ClinicalEntry WHERE IdentifierSystem = 'https://triad.example/fhir'
                                        AND IdentifierValue = 'MedicationRequest/mr-elena-amlodipine'),
        (SELECT a.Id FROM Assertion a
             JOIN ClinicalEntry e ON e.Id = a.ClinicalEntryId
         WHERE e.IdentifierValue = 'MedicationRequest/mr-elena-amlodipine'
           AND NOT EXISTS (SELECT 1 FROM Assertion n WHERE n.SupersedesId = a.Id)),
        '2026-10-30T08:30:00-04:00', 'Report', 'Human', 'Unconfirmed', 'I take amlodipine every morning.');

-- 6. Check the result: the amlodipine entry now has a chain of two assertions.
SELECT a.Id, a.AssertedAt, COALESCE(s.Name, 'Patient') AS Author, a.Intent, a.Verification,
       a.SupersedesId, a.Statement
FROM Assertion a
JOIN ClinicalEntry e ON e.Id = a.ClinicalEntryId
JOIN Message m ON m.Id = a.MessageId
LEFT JOIN Staff s ON s.Id = m.StaffId
WHERE e.IdentifierValue = 'MedicationRequest/mr-elena-amlodipine'
ORDER BY a.AssertedAt;
