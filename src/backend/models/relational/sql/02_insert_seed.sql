-- TRIAD scenario data (Milestone 4). This file is made by:
--     python src/backend/main.py export-sql
-- Do not edit it by hand. Run it after 01_create_tables.sql on a new database:
--     sqlite3 triad.db < 01_create_tables.sql
--     sqlite3 triad.db < 02_insert_seed.sql
-- It holds the TRIAD General directory, Patient A (Elena Marsh) and the demo chat and audit rows.
-- Each foreign key is a subselect on the natural key of the target row (no row ids).
-- The full data set (112 Synthea patients) comes from the onboarding step (main.py ensure-db).

PRAGMA foreign_keys = ON;
BEGIN TRANSACTION;

-- Department (8 rows)
INSERT INTO Department (IdentifierSystem, IdentifierValue, Name, Type, PhoneNumber, Email, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/organization', 'TRIAD-GH-EMER', 'Emergency', 'Hospital Department', '+1-508-555-0110', NULL, '1 Triad Way', 'Worcester', 'MA', '01608', 'US');
INSERT INTO Department (IdentifierSystem, IdentifierValue, Name, Type, PhoneNumber, Email, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/organization', 'TRIAD-GH-INPAT', 'Inpatient Medicine', 'Hospital Department', '+1-508-555-0120', NULL, '1 Triad Way', 'Worcester', 'MA', '01608', 'US');
INSERT INTO Department (IdentifierSystem, IdentifierValue, Name, Type, PhoneNumber, Email, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/organization', 'TRIAD-GH-FAMMED', 'Family Medicine', 'Hospital Department', '+1-508-555-0130', NULL, '1 Triad Way', 'Worcester', 'MA', '01608', 'US');
INSERT INTO Department (IdentifierSystem, IdentifierValue, Name, Type, PhoneNumber, Email, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/organization', 'TRIAD-GH-URGENT', 'Urgent Care', 'Hospital Department', '+1-508-555-0140', NULL, '1 Triad Way', 'Worcester', 'MA', '01608', 'US');
INSERT INTO Department (IdentifierSystem, IdentifierValue, Name, Type, PhoneNumber, Email, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/organization', 'TRIAD-GH-HOME', 'Home Health', 'Hospital Department', '+1-508-555-0150', NULL, '1 Triad Way', 'Worcester', 'MA', '01608', 'US');
INSERT INTO Department (IdentifierSystem, IdentifierValue, Name, Type, PhoneNumber, Email, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/organization', 'TRIAD-GH-VIRT', 'Virtual Care', 'Hospital Department', '+1-508-555-0160', NULL, '1 Triad Way', 'Worcester', 'MA', '01608', 'US');
INSERT INTO Department (IdentifierSystem, IdentifierValue, Name, Type, PhoneNumber, Email, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/organization', 'TRIAD-GH-CARD', 'Cardiology', 'Hospital Department', '+1-508-555-0170', NULL, '1 Triad Way', 'Worcester', 'MA', '01608', 'US');
INSERT INTO Department (IdentifierSystem, IdentifierValue, Name, Type, PhoneNumber, Email, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/organization', 'TRIAD-GH-FRONT', 'Front Office', 'Hospital Department', '+1-508-555-0180', NULL, '1 Triad Way', 'Worcester', 'MA', '01608', 'US');

-- Location (19 rows)
INSERT INTO Location (IdentifierSystem, IdentifierValue, Name, Type, PhysicalType, PhoneNumber, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/location', 'ER-UNIT', 'Emergency Unit', 'Emergency', 'Wing', NULL, '1 Triad Way', 'Worcester', 'MA', '01608', 'US');
INSERT INTO Location (IdentifierSystem, IdentifierValue, Name, Type, PhysicalType, PhoneNumber, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/location', 'ER-WAIT', 'ER Waiting', 'Emergency', 'Area', NULL, '1 Triad Way', 'Worcester', 'MA', '01608', 'US');
INSERT INTO Location (IdentifierSystem, IdentifierValue, Name, Type, PhysicalType, PhoneNumber, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/location', 'ER-BED-1', 'ER Bed 1', 'Emergency', 'Bed', NULL, '1 Triad Way', 'Worcester', 'MA', '01608', 'US');
INSERT INTO Location (IdentifierSystem, IdentifierValue, Name, Type, PhysicalType, PhoneNumber, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/location', 'ER-BED-2', 'ER Bed 2', 'Emergency', 'Bed', NULL, '1 Triad Way', 'Worcester', 'MA', '01608', 'US');
INSERT INTO Location (IdentifierSystem, IdentifierValue, Name, Type, PhysicalType, PhoneNumber, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/location', 'ER-BED-3', 'ER Bed 3', 'Emergency', 'Bed', NULL, '1 Triad Way', 'Worcester', 'MA', '01608', 'US');
INSERT INTO Location (IdentifierSystem, IdentifierValue, Name, Type, PhysicalType, PhoneNumber, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/location', 'ER-BED-4', 'ER Bed 4', 'Emergency', 'Bed', NULL, '1 Triad Way', 'Worcester', 'MA', '01608', 'US');
INSERT INTO Location (IdentifierSystem, IdentifierValue, Name, Type, PhysicalType, PhoneNumber, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/location', 'CARD-WARD', 'Cardiology Ward', 'Cardiology', 'Ward', NULL, '1 Triad Way', 'Worcester', 'MA', '01608', 'US');
INSERT INTO Location (IdentifierSystem, IdentifierValue, Name, Type, PhysicalType, PhoneNumber, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/location', 'CARD-401', 'Cardiology Room 401', 'Cardiology', 'Room', NULL, '1 Triad Way', 'Worcester', 'MA', '01608', 'US');
INSERT INTO Location (IdentifierSystem, IdentifierValue, Name, Type, PhysicalType, PhoneNumber, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/location', 'CARD-402', 'Cardiology Room 402', 'Cardiology', 'Room', NULL, '1 Triad Way', 'Worcester', 'MA', '01608', 'US');
INSERT INTO Location (IdentifierSystem, IdentifierValue, Name, Type, PhysicalType, PhoneNumber, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/location', 'FAMMED-ROOM1', 'Family Medicine Room 1', 'Family Medicine', 'Room', NULL, '1 Triad Way', 'Worcester', 'MA', '01608', 'US');
INSERT INTO Location (IdentifierSystem, IdentifierValue, Name, Type, PhysicalType, PhoneNumber, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/location', 'URGENT-ROOM1', 'Urgent Care Room 1', 'Urgent Care', 'Room', NULL, '1 Triad Way', 'Worcester', 'MA', '01608', 'US');
INSERT INTO Location (IdentifierSystem, IdentifierValue, Name, Type, PhysicalType, PhoneNumber, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/location', 'INPAT-WARD3', 'Inpatient Ward 3', 'Inpatient Medicine', 'Ward', NULL, '1 Triad Way', 'Worcester', 'MA', '01608', 'US');
INSERT INTO Location (IdentifierSystem, IdentifierValue, Name, Type, PhysicalType, PhoneNumber, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/location', 'PATIENT-HOME', 'Patient Home', 'Home Health', 'House', NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO Location (IdentifierSystem, IdentifierValue, Name, Type, PhysicalType, PhoneNumber, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/location', 'VIRTUAL-VISIT', 'Virtual Visit', 'Virtual Care', 'Virtual', NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO Location (IdentifierSystem, IdentifierValue, Name, Type, PhysicalType, PhoneNumber, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/location', 'DESK-MAIN', 'Main Front Desk', 'Front Office', 'Area', NULL, '1 Triad Way', 'Worcester', 'MA', '01608', 'US');
INSERT INTO Location (IdentifierSystem, IdentifierValue, Name, Type, PhysicalType, PhoneNumber, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/location', 'DESK-ER', 'Emergency Registration Desk', 'Emergency', 'Area', NULL, '1 Triad Way', 'Worcester', 'MA', '01608', 'US');
INSERT INTO Location (IdentifierSystem, IdentifierValue, Name, Type, PhysicalType, PhoneNumber, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/location', 'DESK-FAMMED', 'Family Medicine Desk', 'Family Medicine', 'Area', NULL, '1 Triad Way', 'Worcester', 'MA', '01608', 'US');
INSERT INTO Location (IdentifierSystem, IdentifierValue, Name, Type, PhysicalType, PhoneNumber, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/location', 'DESK-CARD', 'Cardiology Desk', 'Cardiology', 'Area', NULL, '1 Triad Way', 'Worcester', 'MA', '01608', 'US');
INSERT INTO Location (IdentifierSystem, IdentifierValue, Name, Type, PhysicalType, PhoneNumber, Street, City, Region, PostalCode, Country)
VALUES ('https://triad.example/fhir/sid/location', 'STORE-OLD', 'Old Storage Room', 'Front Office', 'Room', NULL, '1 Triad Way', 'Worcester', 'MA', '01608', 'US');

-- Staff (25 rows)
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E1001', 'Sofia Alvarez', 'female', 'sofia.alvarez@triad-general.example', '+1-508-555-2001', 1, 'MOA');
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E1002', 'Priya Nair', 'female', 'priya.nair@triad-general.example', '+1-508-555-2002', 1, 'Nurse');
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E1003', 'Tom Becker', 'male', 'tom.becker@triad-general.example', '+1-508-555-2003', 1, 'Nurse');
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E1004', 'Jun Park', 'male', 'jun.park@triad-general.example', '+1-508-555-2004', 1, 'Nurse');
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E1005', 'Amara Okafor', 'female', 'amara.okafor@triad-general.example', '+1-508-555-2005', 1, 'Doctor');
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E1006', 'Lucas Brennan', 'male', 'lucas.brennan@triad-general.example', '+1-508-555-2006', 1, 'Doctor');
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E1007', 'Wei Dlamini', 'male', 'wei.dlamini@triad-general.example', '+1-508-555-2007', 1, 'Nurse');
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E1008', 'Farid Bauer', 'male', 'farid.bauer@triad-general.example', '+1-508-555-2008', 1, 'Nurse');
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E1009', 'Theo Haddad', 'female', 'theo.haddad@triad-general.example', '+1-508-555-2009', 1, 'Nurse');
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E1010', 'Aisha Ortega', 'female', 'aisha.ortega@triad-general.example', '+1-508-555-2010', 1, 'Nurse');
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E1011', 'Elif Sato', 'female', 'elif.sato@triad-general.example', '+1-508-555-2011', 1, 'Nurse');
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E1012', 'Farid Dubois', 'female', 'farid.dubois@triad-general.example', '+1-508-555-2012', 1, 'Nurse');
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E1013', 'Felix Moreau', 'female', 'felix.moreau@triad-general.example', '+1-508-555-2013', 1, 'Nurse');
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E1014', 'Farid Castillo', 'female', 'farid.castillo@triad-general.example', '+1-508-555-2014', 1, 'Nurse');
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E1015', 'Nikhil Novak', 'female', 'nikhil.novak@triad-general.example', '+1-508-555-2015', 1, 'Nurse');
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E1016', 'Grace Bianchi', 'male', 'grace.bianchi@triad-general.example', '+1-508-555-2016', 1, 'Nurse');
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E1017', 'Ivan Rossi', 'female', 'ivan.rossi@triad-general.example', '+1-508-555-2017', 1, 'Nurse');
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E1018', 'Carmen Xu', 'male', 'carmen.xu@triad-general.example', '+1-508-555-2018', 1, 'Nurse');
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E1019', 'Dmitri Ellis', 'female', 'dmitri.ellis@triad-general.example', '+1-508-555-2019', 1, 'Nurse');
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E1020', 'Samir Wagner', 'male', 'samir.wagner@triad-general.example', '+1-508-555-2020', 1, 'Nurse');
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E1021', 'Ximena Yilmaz', 'male', 'ximena.yilmaz@triad-general.example', '+1-508-555-2021', 1, 'MOA');
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E1022', 'Eva Garcia', 'male', 'eva.garcia@triad-general.example', '+1-508-555-2022', 1, 'MOA');
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E1023', 'Liam Chen', 'male', 'liam.chen@triad-general.example', '+1-508-555-2023', 1, 'MOA');
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E1024', 'Samir Dlamini', 'male', 'samir.dlamini@triad-general.example', '+1-508-555-2024', 1, 'MOA');
INSERT INTO Staff (IdentifierSystem, IdentifierValue, Name, Sex, Email, PhoneNumber, Active, Role)
VALUES ('https://triad.example/fhir/sid/employee', 'E1025', 'Quinn Dubois', 'female', 'quinn.dubois@triad-general.example', '+1-508-555-2025', 1, 'MOA');

-- StaffLanguage (41 rows)
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1001'), 'en');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1001'), 'es');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1002'), 'en');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1002'), 'hi');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1003'), 'en');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1003'), 'de');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1004'), 'en');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1004'), 'ko');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1005'), 'en');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1005'), 'fr');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1006'), 'en');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1007'), 'en');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1008'), 'en');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1008'), 'vi');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1009'), 'en');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1009'), 'vi');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1010'), 'en');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1011'), 'en');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1012'), 'en');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1013'), 'en');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1013'), 'fr');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1014'), 'en');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1014'), 'ar');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1015'), 'en');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1016'), 'en');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1016'), 'tl');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1017'), 'en');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1017'), 'ar');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1018'), 'en');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1019'), 'en');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1019'), 'fr');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1020'), 'en');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1021'), 'en');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1021'), 'pa');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1022'), 'en');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1022'), 'tl');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1023'), 'en');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1023'), 'pa');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1024'), 'en');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1025'), 'en');
INSERT INTO StaffLanguage (StaffId, Language)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1025'), 'ar');

-- WorksIn (25 rows)
INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1001'), (SELECT Id FROM Department WHERE IdentifierSystem = 'https://triad.example/fhir/sid/organization' AND IdentifierValue = 'TRIAD-GH-FRONT'), 'moa', NULL, '2015-09-11', NULL);
INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1002'), (SELECT Id FROM Department WHERE IdentifierSystem = 'https://triad.example/fhir/sid/organization' AND IdentifierValue = 'TRIAD-GH-EMER'), 'nurse', NULL, '2009-12-26', NULL);
INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1003'), (SELECT Id FROM Department WHERE IdentifierSystem = 'https://triad.example/fhir/sid/organization' AND IdentifierValue = 'TRIAD-GH-CARD'), 'nurse', NULL, '2016-11-09', NULL);
INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1004'), (SELECT Id FROM Department WHERE IdentifierSystem = 'https://triad.example/fhir/sid/organization' AND IdentifierValue = 'TRIAD-GH-HOME'), 'nurse', NULL, '2018-05-14', NULL);
INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1005'), (SELECT Id FROM Department WHERE IdentifierSystem = 'https://triad.example/fhir/sid/organization' AND IdentifierValue = 'TRIAD-GH-EMER'), 'doctor', 'Emergency medicine', '2012-03-03', NULL);
INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1006'), (SELECT Id FROM Department WHERE IdentifierSystem = 'https://triad.example/fhir/sid/organization' AND IdentifierValue = 'TRIAD-GH-CARD'), 'doctor', 'Cardiology', '2017-03-22', NULL);
INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1007'), (SELECT Id FROM Department WHERE IdentifierSystem = 'https://triad.example/fhir/sid/organization' AND IdentifierValue = 'TRIAD-GH-EMER'), 'nurse', NULL, '2017-03-15', NULL);
INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1008'), (SELECT Id FROM Department WHERE IdentifierSystem = 'https://triad.example/fhir/sid/organization' AND IdentifierValue = 'TRIAD-GH-EMER'), 'nurse', NULL, '2018-03-09', NULL);
INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1009'), (SELECT Id FROM Department WHERE IdentifierSystem = 'https://triad.example/fhir/sid/organization' AND IdentifierValue = 'TRIAD-GH-EMER'), 'nurse', NULL, '2010-01-13', NULL);
INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1010'), (SELECT Id FROM Department WHERE IdentifierSystem = 'https://triad.example/fhir/sid/organization' AND IdentifierValue = 'TRIAD-GH-INPAT'), 'nurse', NULL, '2009-09-12', NULL);
INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1011'), (SELECT Id FROM Department WHERE IdentifierSystem = 'https://triad.example/fhir/sid/organization' AND IdentifierValue = 'TRIAD-GH-INPAT'), 'nurse', NULL, '2015-02-08', NULL);
INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1012'), (SELECT Id FROM Department WHERE IdentifierSystem = 'https://triad.example/fhir/sid/organization' AND IdentifierValue = 'TRIAD-GH-INPAT'), 'nurse', NULL, '2011-02-04', NULL);
INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1013'), (SELECT Id FROM Department WHERE IdentifierSystem = 'https://triad.example/fhir/sid/organization' AND IdentifierValue = 'TRIAD-GH-FAMMED'), 'nurse', NULL, '2013-11-21', NULL);
INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1014'), (SELECT Id FROM Department WHERE IdentifierSystem = 'https://triad.example/fhir/sid/organization' AND IdentifierValue = 'TRIAD-GH-FAMMED'), 'nurse', NULL, '2023-09-08', NULL);
INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1015'), (SELECT Id FROM Department WHERE IdentifierSystem = 'https://triad.example/fhir/sid/organization' AND IdentifierValue = 'TRIAD-GH-URGENT'), 'nurse', NULL, '2022-12-10', NULL);
INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1016'), (SELECT Id FROM Department WHERE IdentifierSystem = 'https://triad.example/fhir/sid/organization' AND IdentifierValue = 'TRIAD-GH-URGENT'), 'nurse', NULL, '2014-12-17', NULL);
INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1017'), (SELECT Id FROM Department WHERE IdentifierSystem = 'https://triad.example/fhir/sid/organization' AND IdentifierValue = 'TRIAD-GH-HOME'), 'nurse', NULL, '2009-01-21', NULL);
INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1018'), (SELECT Id FROM Department WHERE IdentifierSystem = 'https://triad.example/fhir/sid/organization' AND IdentifierValue = 'TRIAD-GH-VIRT'), 'nurse', NULL, '2013-11-08', NULL);
INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1019'), (SELECT Id FROM Department WHERE IdentifierSystem = 'https://triad.example/fhir/sid/organization' AND IdentifierValue = 'TRIAD-GH-CARD'), 'nurse', NULL, '2010-11-22', NULL);
INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1020'), (SELECT Id FROM Department WHERE IdentifierSystem = 'https://triad.example/fhir/sid/organization' AND IdentifierValue = 'TRIAD-GH-CARD'), 'nurse', NULL, '2010-05-10', NULL);
INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1021'), (SELECT Id FROM Department WHERE IdentifierSystem = 'https://triad.example/fhir/sid/organization' AND IdentifierValue = 'TRIAD-GH-EMER'), 'moa', NULL, '2024-04-10', NULL);
INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1022'), (SELECT Id FROM Department WHERE IdentifierSystem = 'https://triad.example/fhir/sid/organization' AND IdentifierValue = 'TRIAD-GH-FAMMED'), 'moa', NULL, '2009-08-20', NULL);
INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1023'), (SELECT Id FROM Department WHERE IdentifierSystem = 'https://triad.example/fhir/sid/organization' AND IdentifierValue = 'TRIAD-GH-CARD'), 'moa', NULL, '2022-08-18', NULL);
INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1024'), (SELECT Id FROM Department WHERE IdentifierSystem = 'https://triad.example/fhir/sid/organization' AND IdentifierValue = 'TRIAD-GH-FRONT'), 'moa', NULL, '2019-06-20', NULL);
INSERT INTO WorksIn (StaffId, DepartmentId, RoleCode, Specialty, StartDate, EndDate)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1025'), (SELECT Id FROM Department WHERE IdentifierSystem = 'https://triad.example/fhir/sid/organization' AND IdentifierValue = 'TRIAD-GH-FRONT'), 'moa', NULL, '2013-12-14', NULL);

-- Doctor (2 rows)
INSERT INTO Doctor (StaffId, Role, LicenseNumber, Qualification)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1005'), 'Doctor', 'MD-28590', 'MD');
INSERT INTO Doctor (StaffId, Role, LicenseNumber, Qualification)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1006'), 'Doctor', 'MD-13282', 'MD');

-- Nurse (17 rows)
INSERT INTO Nurse (StaffId, Role, LicenseNumber, Designation)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1002'), 'Nurse', 'RN-63979', 'RN');
INSERT INTO Nurse (StaffId, Role, LicenseNumber, Designation)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1003'), 'Nurse', 'RN-77753', 'RN');
INSERT INTO Nurse (StaffId, Role, LicenseNumber, Designation)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1004'), 'Nurse', 'RN-26179', 'LPN');
INSERT INTO Nurse (StaffId, Role, LicenseNumber, Designation)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1007'), 'Nurse', 'RN-97689', 'RN');
INSERT INTO Nurse (StaffId, Role, LicenseNumber, Designation)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1008'), 'Nurse', 'RN-26860', 'RN');
INSERT INTO Nurse (StaffId, Role, LicenseNumber, Designation)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1009'), 'Nurse', 'RN-32786', 'RN');
INSERT INTO Nurse (StaffId, Role, LicenseNumber, Designation)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1010'), 'Nurse', 'RN-14686', 'RN');
INSERT INTO Nurse (StaffId, Role, LicenseNumber, Designation)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1011'), 'Nurse', 'RN-48680', 'NP');
INSERT INTO Nurse (StaffId, Role, LicenseNumber, Designation)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1012'), 'Nurse', 'RN-27595', 'RN');
INSERT INTO Nurse (StaffId, Role, LicenseNumber, Designation)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1013'), 'Nurse', 'RN-93822', 'RN');
INSERT INTO Nurse (StaffId, Role, LicenseNumber, Designation)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1014'), 'Nurse', 'RN-27451', 'RN');
INSERT INTO Nurse (StaffId, Role, LicenseNumber, Designation)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1015'), 'Nurse', 'RN-62180', 'RN');
INSERT INTO Nurse (StaffId, Role, LicenseNumber, Designation)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1016'), 'Nurse', 'RN-36002', 'RN');
INSERT INTO Nurse (StaffId, Role, LicenseNumber, Designation)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1017'), 'Nurse', 'RN-45421', 'RN');
INSERT INTO Nurse (StaffId, Role, LicenseNumber, Designation)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1018'), 'Nurse', 'RN-16615', 'LPN');
INSERT INTO Nurse (StaffId, Role, LicenseNumber, Designation)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1019'), 'Nurse', 'RN-26778', 'LPN');
INSERT INTO Nurse (StaffId, Role, LicenseNumber, Designation)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1020'), 'Nurse', 'RN-85187', 'RN');

-- MOA (6 rows)
INSERT INTO MOA (StaffId, Role, CertificationNumber, Desk, PhoneExtension)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1001'), 'MOA', 'MOA-9934', 'Main Front Desk', 'ext. 2100');
INSERT INTO MOA (StaffId, Role, CertificationNumber, Desk, PhoneExtension)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1021'), 'MOA', NULL, 'Emergency Registration Desk', 'ext. 2120');
INSERT INTO MOA (StaffId, Role, CertificationNumber, Desk, PhoneExtension)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1022'), 'MOA', 'MOA-4793', 'Family Medicine Desk', 'ext. 2121');
INSERT INTO MOA (StaffId, Role, CertificationNumber, Desk, PhoneExtension)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1023'), 'MOA', NULL, 'Cardiology Desk', 'ext. 2122');
INSERT INTO MOA (StaffId, Role, CertificationNumber, Desk, PhoneExtension)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1024'), 'MOA', NULL, 'Main Front Desk', 'ext. 2123');
INSERT INTO MOA (StaffId, Role, CertificationNumber, Desk, PhoneExtension)
VALUES ((SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1025'), 'MOA', 'MOA-5025', 'Main Front Desk', 'ext. 2124');

-- Patient (1 rows)
INSERT INTO Patient (Name, DateOfBirth, Sex, PhoneNumber, Street, City, Region, PostalCode, Country)
VALUES ('Elena Marsh', '1971-05-14', 'female', '+1-508-555-0142', '42 Elm Street', 'Worcester', 'MA', '01609', 'US');

-- PatientIdentifier (2 rows)
INSERT INTO PatientIdentifier (PatientId, System, Value)
VALUES ((SELECT Id FROM Patient WHERE Name = 'Elena Marsh' AND DateOfBirth = '1971-05-14'), 'https://triad.example/fhir/sid/mrn', 'MRN-000001');
INSERT INTO PatientIdentifier (PatientId, System, Value)
VALUES ((SELECT Id FROM Patient WHERE Name = 'Elena Marsh' AND DateOfBirth = '1971-05-14'), 'https://fhir.infoway-inforoute.ca/NamingSystem/ca-bc-patient-healthcare-id', '9995267502');

-- Visit (3 rows)
INSERT INTO Visit (IdentifierSystem, IdentifierValue, PatientId, Class, Type, Reason, StartDate, EndDate)
VALUES ('https://triad.example/fhir/sid/encounter', 'ENC-ELENA-2019-06-12', (SELECT Id FROM Patient WHERE Name = 'Elena Marsh' AND DateOfBirth = '1971-05-14'), 'VR', 'Phone call', 'Phone call', '2019-06-12T10:10:00-04:00', '2019-06-12T10:20:00-04:00');
INSERT INTO Visit (IdentifierSystem, IdentifierValue, PatientId, Class, Type, Reason, StartDate, EndDate)
VALUES ('https://triad.example/fhir/sid/encounter', 'ENC-ELENA-2025-08-20', (SELECT Id FROM Patient WHERE Name = 'Elena Marsh' AND DateOfBirth = '1971-05-14'), 'AMB', 'Blood pressure check', 'Blood pressure check', '2025-08-20T09:30:00-04:00', '2025-08-20T10:00:00-04:00');
INSERT INTO Visit (IdentifierSystem, IdentifierValue, PatientId, Class, Type, Reason, StartDate, EndDate)
VALUES ('https://triad.example/fhir/sid/encounter', 'ENC-ELENA-2026-10-02', (SELECT Id FROM Patient WHERE Name = 'Elena Marsh' AND DateOfBirth = '1971-05-14'), 'AMB', 'Penicillin allergy test', 'Penicillin allergy test', '2026-10-02T10:00:00-04:00', '2026-10-02T11:30:00-04:00');

-- VisitLocation (3 rows)
INSERT INTO VisitLocation (VisitId, LocationId, StartDate, EndDate)
VALUES ((SELECT Id FROM Visit WHERE IdentifierSystem = 'https://triad.example/fhir/sid/encounter' AND IdentifierValue = 'ENC-ELENA-2019-06-12'), (SELECT Id FROM Location WHERE IdentifierSystem = 'https://triad.example/fhir/sid/location' AND IdentifierValue = 'VIRTUAL-VISIT'), '2019-06-12T10:10:00-04:00', '2019-06-12T10:20:00-04:00');
INSERT INTO VisitLocation (VisitId, LocationId, StartDate, EndDate)
VALUES ((SELECT Id FROM Visit WHERE IdentifierSystem = 'https://triad.example/fhir/sid/encounter' AND IdentifierValue = 'ENC-ELENA-2025-08-20'), (SELECT Id FROM Location WHERE IdentifierSystem = 'https://triad.example/fhir/sid/location' AND IdentifierValue = 'CARD-401'), '2025-08-20T09:30:00-04:00', '2025-08-20T10:00:00-04:00');
INSERT INTO VisitLocation (VisitId, LocationId, StartDate, EndDate)
VALUES ((SELECT Id FROM Visit WHERE IdentifierSystem = 'https://triad.example/fhir/sid/encounter' AND IdentifierValue = 'ENC-ELENA-2026-10-02'), (SELECT Id FROM Location WHERE IdentifierSystem = 'https://triad.example/fhir/sid/location' AND IdentifierValue = 'FAMMED-ROOM1'), '2026-10-02T10:00:00-04:00', '2026-10-02T11:30:00-04:00');

-- ClinicalEntry (8 rows)
INSERT INTO ClinicalEntry (IdentifierSystem, IdentifierValue, VisitId, Category, Code, CodeSystem, Display, Text, RecordedAt)
VALUES ('https://triad.example/fhir', 'AllergyIntolerance/ai-elena-penicillin', (SELECT Id FROM Visit WHERE IdentifierSystem = 'https://triad.example/fhir/sid/encounter' AND IdentifierValue = 'ENC-ELENA-2019-06-12'), 'Allergy', '91936005', 'http://snomed.info/sct', 'Allergy to penicillin', 'Allergy to penicillin', '2019-06-12T10:15:00-04:00');
INSERT INTO ClinicalEntry (IdentifierSystem, IdentifierValue, VisitId, Category, Code, CodeSystem, Display, Text, RecordedAt)
VALUES ('https://triad.example/fhir', 'Observation/obs-elena-bp-2025-08-20', (SELECT Id FROM Visit WHERE IdentifierSystem = 'https://triad.example/fhir/sid/encounter' AND IdentifierValue = 'ENC-ELENA-2025-08-20'), 'Observation', '85354-9', 'http://loinc.org', 'Blood pressure panel with all children optional', 'Blood pressure panel with all children optional', '2025-08-20T09:40:00-04:00');
INSERT INTO ClinicalEntry (IdentifierSystem, IdentifierValue, VisitId, Category, Code, CodeSystem, Display, Text, RecordedAt)
VALUES ('https://triad.example/fhir', 'Condition/cond-elena-hypertension', (SELECT Id FROM Visit WHERE IdentifierSystem = 'https://triad.example/fhir/sid/encounter' AND IdentifierValue = 'ENC-ELENA-2025-08-20'), 'Diagnosis', '59621000', 'http://snomed.info/sct', 'Essential hypertension', 'Essential hypertension', '2025-08-20T10:00:00-04:00');
INSERT INTO ClinicalEntry (IdentifierSystem, IdentifierValue, VisitId, Category, Code, CodeSystem, Display, Text, RecordedAt)
VALUES ('https://triad.example/fhir', 'MedicationRequest/mr-elena-amlodipine', (SELECT Id FROM Visit WHERE IdentifierSystem = 'https://triad.example/fhir/sid/encounter' AND IdentifierValue = 'ENC-ELENA-2025-08-20'), 'Prescription', '197361', 'http://www.nlm.nih.gov/research/umls/rxnorm', 'Amlodipine 5 MG Oral Tablet', NULL, '2025-08-20T10:00:00-04:00');
INSERT INTO ClinicalEntry (IdentifierSystem, IdentifierValue, VisitId, Category, Code, CodeSystem, Display, Text, RecordedAt)
VALUES ('https://triad.example/fhir', 'ServiceRequest/sr-elena-lipid-panel', (SELECT Id FROM Visit WHERE IdentifierSystem = 'https://triad.example/fhir/sid/encounter' AND IdentifierValue = 'ENC-ELENA-2025-08-20'), 'LabOrder', '57698-3', 'http://loinc.org', 'Lipid panel with direct LDL - Serum or Plasma', 'Lipid panel with direct LDL - Serum or Plasma', '2025-08-20T10:00:00-04:00');
INSERT INTO ClinicalEntry (IdentifierSystem, IdentifierValue, VisitId, Category, Code, CodeSystem, Display, Text, RecordedAt)
VALUES ('https://triad.example/fhir', 'DiagnosticReport/dr-elena-lipid-panel', (SELECT Id FROM Visit WHERE IdentifierSystem = 'https://triad.example/fhir/sid/encounter' AND IdentifierValue = 'ENC-ELENA-2025-08-20'), 'LabReport', '57698-3', 'http://loinc.org', 'Lipid panel with direct LDL - Serum or Plasma', 'Lipid panel with direct LDL - Serum or Plasma', '2025-08-22T15:30:00-04:00');
INSERT INTO ClinicalEntry (IdentifierSystem, IdentifierValue, VisitId, Category, Code, CodeSystem, Display, Text, RecordedAt)
VALUES ('https://triad.example/fhir', 'Procedure/proc-elena-penicillin-test', (SELECT Id FROM Visit WHERE IdentifierSystem = 'https://triad.example/fhir/sid/encounter' AND IdentifierValue = 'ENC-ELENA-2026-10-02'), 'Procedure', 'penicillin-allergy-test', 'https://triad.example/fhir/CodeSystem/local', 'Penicillin skin test and oral challenge', 'Penicillin skin test and oral challenge', '2026-10-02T10:10:00-04:00');
INSERT INTO ClinicalEntry (IdentifierSystem, IdentifierValue, VisitId, Category, Code, CodeSystem, Display, Text, RecordedAt)
VALUES ('https://triad.example/fhir', 'CareTeam/ct-elena', (SELECT Id FROM Visit WHERE IdentifierSystem = 'https://triad.example/fhir/sid/encounter' AND IdentifierValue = 'ENC-ELENA-2026-10-02'), 'CareTeam', 'care-team', 'https://triad.example/fhir/CodeSystem/local', 'Elena Marsh care team', NULL, '2026-10-02T12:00:00-04:00');

-- Diagnosis (1 rows)
INSERT INTO Diagnosis (ClinicalEntryId, Category, OnsetDate, AbatementDate, ClinicalStatus, Severity)
VALUES ((SELECT Id FROM ClinicalEntry WHERE IdentifierSystem = 'https://triad.example/fhir' AND IdentifierValue = 'Condition/cond-elena-hypertension'), 'Diagnosis', '2025-08-20T09:40:00-04:00', NULL, 'active', 'Moderate');

-- Procedure (1 rows)
INSERT INTO Procedure (ClinicalEntryId, Category, PerformedDate, Outcome)
VALUES ((SELECT Id FROM ClinicalEntry WHERE IdentifierSystem = 'https://triad.example/fhir' AND IdentifierValue = 'Procedure/proc-elena-penicillin-test'), 'Procedure', '2026-10-02T10:10:00-04:00', 'Negative. No reaction.');

-- Allergy (1 rows)
INSERT INTO Allergy (ClinicalEntryId, Category, Substance, Type, AllergyCategory, Criticality, ClinicalStatus)
VALUES ((SELECT Id FROM ClinicalEntry WHERE IdentifierSystem = 'https://triad.example/fhir' AND IdentifierValue = 'AllergyIntolerance/ai-elena-penicillin'), 'Allergy', 'Allergy to penicillin', 'allergy', 'medication', 'low', 'inactive');

-- Observation (1 rows)
INSERT INTO Observation (ClinicalEntryId, Category, Value, Unit)
VALUES ((SELECT Id FROM ClinicalEntry WHERE IdentifierSystem = 'https://triad.example/fhir' AND IdentifierValue = 'Observation/obs-elena-bp-2025-08-20'), 'Observation', 'Systolic blood pressure: 152 mm[Hg]; Diastolic blood pressure: 96 mm[Hg]', NULL);

-- LabOrder (1 rows)
INSERT INTO LabOrder (ClinicalEntryId, Category, TestName, Priority, Specimen)
VALUES ((SELECT Id FROM ClinicalEntry WHERE IdentifierSystem = 'https://triad.example/fhir' AND IdentifierValue = 'ServiceRequest/sr-elena-lipid-panel'), 'LabOrder', 'Lipid panel with direct LDL - Serum or Plasma', 'routine', 'Serum');

-- LabReport (1 rows)
INSERT INTO LabReport (ClinicalEntryId, Category, IssuedDate, Conclusion)
VALUES ((SELECT Id FROM ClinicalEntry WHERE IdentifierSystem = 'https://triad.example/fhir' AND IdentifierValue = 'DiagnosticReport/dr-elena-lipid-panel'), 'LabReport', '2025-08-22T15:30:00-04:00', 'LDL cholesterol is 112 mg/dL. It is in the target range.');

-- Medication (1 rows)
INSERT INTO Medication (Code, CodeSystem, Name, Form, Manufacturer)
VALUES ('197361', 'http://www.nlm.nih.gov/research/umls/rxnorm', 'Amlodipine 5 MG Oral Tablet', 'Tablet', NULL);

-- Prescription (1 rows)
INSERT INTO Prescription (ClinicalEntryId, Category, MedicationId, Dosage, Frequency, Status)
VALUES ((SELECT Id FROM ClinicalEntry WHERE IdentifierSystem = 'https://triad.example/fhir' AND IdentifierValue = 'MedicationRequest/mr-elena-amlodipine'), 'Prescription', (SELECT Id FROM Medication WHERE Code = '197361' AND CodeSystem = 'http://www.nlm.nih.gov/research/umls/rxnorm'), '5 mg', '1 per 1 d', 'active');

-- CareTeam (1 rows)
INSERT INTO CareTeam (ClinicalEntryId, Category, Name, Status)
VALUES ((SELECT Id FROM ClinicalEntry WHERE IdentifierSystem = 'https://triad.example/fhir' AND IdentifierValue = 'CareTeam/ct-elena'), 'CareTeam', 'Elena Marsh care team', 'active');

-- CareTeamMember (2 rows)
INSERT INTO CareTeamMember (CareTeamId, MemberSystem, MemberValue, Role)
VALUES ((SELECT Id FROM CareTeam WHERE ClinicalEntryId = (SELECT Id FROM ClinicalEntry WHERE IdentifierSystem = 'https://triad.example/fhir' AND IdentifierValue = 'CareTeam/ct-elena')), 'https://triad.example/fhir/sid/employee', 'E1005', 'Doctor');
INSERT INTO CareTeamMember (CareTeamId, MemberSystem, MemberValue, Role)
VALUES ((SELECT Id FROM CareTeam WHERE ClinicalEntryId = (SELECT Id FROM ClinicalEntry WHERE IdentifierSystem = 'https://triad.example/fhir' AND IdentifierValue = 'CareTeam/ct-elena')), 'https://triad.example/fhir/sid/employee', 'E1006', 'Doctor');

-- Message (6 rows)
INSERT INTO Message (IdentifierSystem, IdentifierValue, StaffId, Channel, Origin, SentAt, Text)
VALUES ('https://triad.example/fhir/sid/message', 'MSG-ELENA-2019-06-12', (SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1001'), 'Phone', 'Patient', '2019-06-12T10:15:00-04:00', 'Phone call. The patient says that she had a rash after penicillin as a child.');
INSERT INTO Message (IdentifierSystem, IdentifierValue, StaffId, Channel, Origin, SentAt, Text)
VALUES ('https://triad.example/fhir/sid/message', 'MSG-ELENA-2024-03-05', (SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1001'), 'Transfer', 'OtherClinic', '2024-03-05T14:00:00-05:00', 'Records copied from Lakeside Family Clinic. The records list a penicillin allergy.');
INSERT INTO Message (IdentifierSystem, IdentifierValue, StaffId, Channel, Origin, SentAt, Text)
VALUES ('https://triad.example/fhir/sid/message', 'MSG-ELENA-2025-08-20', (SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1006'), 'InPerson', 'Staff', '2025-08-20T10:05:00-04:00', 'Visit note. Blood pressure is high on two readings. Diagnosis: essential hypertension. Start amlodipine 5 mg daily. Order a lipid panel.');
INSERT INTO Message (IdentifierSystem, IdentifierValue, StaffId, Channel, Origin, SentAt, Text)
VALUES ('https://triad.example/fhir/sid/message', 'MSG-ELENA-2025-08-22', (SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1006'), 'Transfer', 'Lab', '2025-08-22T16:00:00-04:00', 'Lipid panel result received. LDL cholesterol is 112 mg/dL.');
INSERT INTO Message (IdentifierSystem, IdentifierValue, StaffId, Channel, Origin, SentAt, Text)
VALUES ('https://triad.example/fhir/sid/message', 'MSG-ELENA-2026-10-02', (SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1005'), 'InPerson', 'Staff', '2026-10-02T11:40:00-04:00', 'Visit note. The penicillin skin test and the oral challenge are negative. The patient is not allergic to penicillin.');
INSERT INTO Message (IdentifierSystem, IdentifierValue, StaffId, Channel, Origin, SentAt, Text)
VALUES ('https://triad.example/fhir/sid/message', 'MSG-CT-ELENA', (SELECT Id FROM Staff WHERE IdentifierSystem = 'https://triad.example/fhir/sid/employee' AND IdentifierValue = 'E1001'), 'Transfer', 'Staff', '2026-10-02T12:00:00-04:00', 'Care team set: Amara Okafor, Lucas Brennan.');

-- Assertion (10 rows)
INSERT INTO Assertion (MessageId, Seq, ClinicalEntryId, SupersedesId, AssertedAt, Intent, Source, Verification, Statement)
VALUES ((SELECT Id FROM Message WHERE IdentifierSystem = 'https://triad.example/fhir/sid/message' AND IdentifierValue = 'MSG-ELENA-2019-06-12'), 1, (SELECT Id FROM ClinicalEntry WHERE IdentifierSystem = 'https://triad.example/fhir' AND IdentifierValue = 'AllergyIntolerance/ai-elena-penicillin'), NULL, '2019-06-12T10:15:00-04:00', 'Report', 'Human', 'Unconfirmed', 'Patient report: rash after penicillin as a child.');
INSERT INTO Assertion (MessageId, Seq, ClinicalEntryId, SupersedesId, AssertedAt, Intent, Source, Verification, Statement)
VALUES ((SELECT Id FROM Message WHERE IdentifierSystem = 'https://triad.example/fhir/sid/message' AND IdentifierValue = 'MSG-ELENA-2024-03-05'), 1, (SELECT Id FROM ClinicalEntry WHERE IdentifierSystem = 'https://triad.example/fhir' AND IdentifierValue = 'AllergyIntolerance/ai-elena-penicillin'), (SELECT Id FROM Assertion WHERE MessageId = (SELECT Id FROM Message WHERE IdentifierSystem = 'https://triad.example/fhir/sid/message' AND IdentifierValue = 'MSG-ELENA-2019-06-12') AND Seq = 1), '2024-03-05T14:00:00-05:00', 'Report', 'Human', 'Unconfirmed', 'Penicillin allergy (copied from Lakeside Family Clinic).');
INSERT INTO Assertion (MessageId, Seq, ClinicalEntryId, SupersedesId, AssertedAt, Intent, Source, Verification, Statement)
VALUES ((SELECT Id FROM Message WHERE IdentifierSystem = 'https://triad.example/fhir/sid/message' AND IdentifierValue = 'MSG-ELENA-2026-10-02'), 1, (SELECT Id FROM ClinicalEntry WHERE IdentifierSystem = 'https://triad.example/fhir' AND IdentifierValue = 'AllergyIntolerance/ai-elena-penicillin'), (SELECT Id FROM Assertion WHERE MessageId = (SELECT Id FROM Message WHERE IdentifierSystem = 'https://triad.example/fhir/sid/message' AND IdentifierValue = 'MSG-ELENA-2024-03-05') AND Seq = 1), '2026-10-02T11:40:00-04:00', 'Decision', 'Human', 'Refuted', 'Not allergic. Allergy test negative.');
INSERT INTO Assertion (MessageId, Seq, ClinicalEntryId, SupersedesId, AssertedAt, Intent, Source, Verification, Statement)
VALUES ((SELECT Id FROM Message WHERE IdentifierSystem = 'https://triad.example/fhir/sid/message' AND IdentifierValue = 'MSG-ELENA-2025-08-20'), 1, (SELECT Id FROM ClinicalEntry WHERE IdentifierSystem = 'https://triad.example/fhir' AND IdentifierValue = 'Observation/obs-elena-bp-2025-08-20'), NULL, '2025-08-20T10:05:00-04:00', 'Report', 'Human', 'Confirmed', 'Blood pressure panel with all children optional: Systolic blood pressure: 152 mm[Hg]; Diastolic blood pressure: 96 mm[Hg]');
INSERT INTO Assertion (MessageId, Seq, ClinicalEntryId, SupersedesId, AssertedAt, Intent, Source, Verification, Statement)
VALUES ((SELECT Id FROM Message WHERE IdentifierSystem = 'https://triad.example/fhir/sid/message' AND IdentifierValue = 'MSG-ELENA-2025-08-20'), 2, (SELECT Id FROM ClinicalEntry WHERE IdentifierSystem = 'https://triad.example/fhir' AND IdentifierValue = 'Condition/cond-elena-hypertension'), NULL, '2025-08-20T10:05:00-04:00', 'Decision', 'Human', 'Confirmed', 'Essential hypertension. Two high readings.');
INSERT INTO Assertion (MessageId, Seq, ClinicalEntryId, SupersedesId, AssertedAt, Intent, Source, Verification, Statement)
VALUES ((SELECT Id FROM Message WHERE IdentifierSystem = 'https://triad.example/fhir/sid/message' AND IdentifierValue = 'MSG-ELENA-2025-08-20'), 3, (SELECT Id FROM ClinicalEntry WHERE IdentifierSystem = 'https://triad.example/fhir' AND IdentifierValue = 'MedicationRequest/mr-elena-amlodipine'), NULL, '2025-08-20T10:05:00-04:00', 'Decision', 'Human', 'Confirmed', 'Start amlodipine 5 mg daily.');
INSERT INTO Assertion (MessageId, Seq, ClinicalEntryId, SupersedesId, AssertedAt, Intent, Source, Verification, Statement)
VALUES ((SELECT Id FROM Message WHERE IdentifierSystem = 'https://triad.example/fhir/sid/message' AND IdentifierValue = 'MSG-ELENA-2025-08-20'), 4, (SELECT Id FROM ClinicalEntry WHERE IdentifierSystem = 'https://triad.example/fhir' AND IdentifierValue = 'ServiceRequest/sr-elena-lipid-panel'), NULL, '2025-08-20T10:05:00-04:00', 'Decision', 'Human', 'Confirmed', 'Lipid panel with direct LDL - Serum or Plasma');
INSERT INTO Assertion (MessageId, Seq, ClinicalEntryId, SupersedesId, AssertedAt, Intent, Source, Verification, Statement)
VALUES ((SELECT Id FROM Message WHERE IdentifierSystem = 'https://triad.example/fhir/sid/message' AND IdentifierValue = 'MSG-ELENA-2025-08-22'), 1, (SELECT Id FROM ClinicalEntry WHERE IdentifierSystem = 'https://triad.example/fhir' AND IdentifierValue = 'DiagnosticReport/dr-elena-lipid-panel'), NULL, '2025-08-22T16:00:00-04:00', 'Report', 'Human', 'Confirmed', 'Lipid panel with direct LDL - Serum or Plasma');
INSERT INTO Assertion (MessageId, Seq, ClinicalEntryId, SupersedesId, AssertedAt, Intent, Source, Verification, Statement)
VALUES ((SELECT Id FROM Message WHERE IdentifierSystem = 'https://triad.example/fhir/sid/message' AND IdentifierValue = 'MSG-ELENA-2026-10-02'), 2, (SELECT Id FROM ClinicalEntry WHERE IdentifierSystem = 'https://triad.example/fhir' AND IdentifierValue = 'Procedure/proc-elena-penicillin-test'), NULL, '2026-10-02T11:40:00-04:00', 'Decision', 'Human', 'Confirmed', 'Penicillin skin test and oral challenge');
INSERT INTO Assertion (MessageId, Seq, ClinicalEntryId, SupersedesId, AssertedAt, Intent, Source, Verification, Statement)
VALUES ((SELECT Id FROM Message WHERE IdentifierSystem = 'https://triad.example/fhir/sid/message' AND IdentifierValue = 'MSG-CT-ELENA'), 1, (SELECT Id FROM ClinicalEntry WHERE IdentifierSystem = 'https://triad.example/fhir' AND IdentifierValue = 'CareTeam/ct-elena'), NULL, '2026-10-02T12:00:00-04:00', 'Report', 'Human', 'Confirmed', 'Elena Marsh care team');

-- ChatSession (1 rows)
INSERT INTO ChatSession (IdentifierSystem, IdentifierValue, UserRole, UserSystem, UserValue, SubjectName, SubjectDateOfBirth, StartedAt, Mode, Model)
VALUES ('https://triad.example/fhir/sid/chat-session', 'CHAT-0001', 'Doctor', 'https://triad.example/fhir/sid/employee', 'E1005', 'Elena Marsh', '1971-05-14', '2026-10-29T15:00:00-04:00', 'rules', NULL);

-- ChatTurn (2 rows)
INSERT INTO ChatTurn (ChatSessionId, Seq, ClientTurnId, Speaker, Text, CreatedAt)
VALUES ((SELECT Id FROM ChatSession WHERE IdentifierSystem = 'https://triad.example/fhir/sid/chat-session' AND IdentifierValue = 'CHAT-0001'), 1, 'demo-0001-1', 'User', 'Is she allergic to penicillin?', '2026-10-29T15:00:05-04:00');
INSERT INTO ChatTurn (ChatSessionId, Seq, ClientTurnId, Speaker, Text, CreatedAt)
VALUES ((SELECT Id FROM ChatSession WHERE IdentifierSystem = 'https://triad.example/fhir/sid/chat-session' AND IdentifierValue = 'CHAT-0001'), 2, 'demo-0001-2', 'Assistant', 'No. A physician ruled it out with an allergy test on Oct 2, 2026.', '2026-10-29T15:00:06-04:00');

-- Citation (1 rows)
INSERT INTO Citation (ChatTurnId, AssertionId, Rank)
VALUES ((SELECT Id FROM ChatTurn WHERE ChatSessionId = (SELECT Id FROM ChatSession WHERE IdentifierSystem = 'https://triad.example/fhir/sid/chat-session' AND IdentifierValue = 'CHAT-0001') AND Seq = 2), (SELECT Id FROM Assertion WHERE MessageId = (SELECT Id FROM Message WHERE IdentifierSystem = 'https://triad.example/fhir/sid/message' AND IdentifierValue = 'MSG-ELENA-2026-10-02') AND Seq = 1), 1);

-- AuditEvent (4 rows)
INSERT INTO AuditEvent (IdentifierSystem, IdentifierValue, At, Action, Outcome, ActorRole, ActorSystem, ActorValue, SubjectName, SubjectDateOfBirth, Path, ChatTurnId)
VALUES ('https://triad.example/fhir/sid/audit-event', 'AUDIT-0001', '2026-10-29T14:59:00-04:00', 'read', 'Allowed', 'Doctor', 'https://triad.example/fhir/sid/employee', 'E1005', 'Elena Marsh', '1971-05-14', '/api/patients/{patient}/chart', NULL);
INSERT INTO AuditEvent (IdentifierSystem, IdentifierValue, At, Action, Outcome, ActorRole, ActorSystem, ActorValue, SubjectName, SubjectDateOfBirth, Path, ChatTurnId)
VALUES ('https://triad.example/fhir/sid/audit-event', 'AUDIT-0002', '2026-10-29T15:00:06-04:00', 'ask', 'Allowed', 'Doctor', 'https://triad.example/fhir/sid/employee', 'E1005', 'Elena Marsh', '1971-05-14', '/api/chat/sessions/{session}/turns', (SELECT Id FROM ChatTurn WHERE ChatSessionId = (SELECT Id FROM ChatSession WHERE IdentifierSystem = 'https://triad.example/fhir/sid/chat-session' AND IdentifierValue = 'CHAT-0001') AND Seq = 2));
INSERT INTO AuditEvent (IdentifierSystem, IdentifierValue, At, Action, Outcome, ActorRole, ActorSystem, ActorValue, SubjectName, SubjectDateOfBirth, Path, ChatTurnId)
VALUES ('https://triad.example/fhir/sid/audit-event', 'AUDIT-0003', '2026-10-29T16:20:00-04:00', 'read', 'Denied', 'Nurse', 'https://triad.example/fhir/sid/employee', 'E1004', 'Elena Marsh', '1971-05-14', '/api/patients/{patient}/chart', NULL);
INSERT INTO AuditEvent (IdentifierSystem, IdentifierValue, At, Action, Outcome, ActorRole, ActorSystem, ActorValue, SubjectName, SubjectDateOfBirth, Path, ChatTurnId)
VALUES ('https://triad.example/fhir/sid/audit-event', 'AUDIT-0004', '2026-10-29T18:00:00-04:00', 'read', 'Allowed', 'Patient', 'https://triad.example/fhir/sid/mrn', 'MRN-000001', 'Elena Marsh', '1971-05-14', '/api/audit', NULL);

COMMIT;
