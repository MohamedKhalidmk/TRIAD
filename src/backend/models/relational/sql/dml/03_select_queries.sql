-- TRIAD SELECT queries (Milestone 4). They run on the scenario data (01 + 02)
-- and on the full database (main.py ensure-db). Patient A is Elena Marsh (born 1971-05-14).
-- To reach the patient of a fact, follow Assertion -> ClinicalEntry -> Visit -> Patient (one path).
-- The current fact is the assertion that no assertion supersedes.

PRAGMA foreign_keys = ON;

-- Q1. The current record of one patient: each assertion that nothing supersedes,
--     with its entry, its visit, its message and its author.
SELECT e.Category, e.Display, a.Verification, a.Intent,
       COALESCE(s.Name, 'Patient') AS Author, m.Origin, date(v.StartDate) AS VisitDate, a.Statement
FROM Patient p
JOIN Visit v ON v.PatientId = p.Id
JOIN ClinicalEntry e ON e.VisitId = v.Id
JOIN Assertion a ON a.ClinicalEntryId = e.Id
JOIN Message m ON m.Id = a.MessageId
LEFT JOIN Staff s ON s.Id = m.StaffId
WHERE p.Name = 'Elena Marsh' AND p.DateOfBirth = '1971-05-14'
  AND NOT EXISTS (SELECT 1 FROM Assertion n WHERE n.SupersedesId = a.Id)
ORDER BY e.Category, a.AssertedAt;

-- Q2. The revision chain of one fact: start at the current assertion and follow Supersedes back.
WITH RECURSIVE chain (Id, SupersedesId, Depth) AS (
    SELECT a.Id, a.SupersedesId, 0
    FROM Assertion a
    JOIN ClinicalEntry e ON e.Id = a.ClinicalEntryId
    JOIN Allergy al ON al.ClinicalEntryId = e.Id
    JOIN Visit v ON v.Id = e.VisitId
    JOIN Patient p ON p.Id = v.PatientId
    WHERE p.Name = 'Elena Marsh' AND p.DateOfBirth = '1971-05-14'
      AND lower(al.Substance) LIKE '%penicillin%'
      AND NOT EXISTS (SELECT 1 FROM Assertion n WHERE n.SupersedesId = a.Id)
    UNION ALL
    SELECT a.Id, a.SupersedesId, c.Depth + 1
    FROM Assertion a JOIN chain c ON a.Id = c.SupersedesId
)
SELECT c.Depth, date(a.AssertedAt) AS Date, COALESCE(s.Name, 'Patient') AS Author, s.Role,
       m.Origin, a.Verification, a.Statement
FROM chain c
JOIN Assertion a ON a.Id = c.Id
JOIN Message m ON m.Id = a.MessageId
LEFT JOIN Staff s ON s.Id = m.StaffId
ORDER BY c.Depth;

-- Q3. The 3MT slide question: "Is she allergic to penicillin?" The answer comes from the current assertion.
--     The author label follows the slide: Physician, Front desk, Other clinic.
SELECT CASE a.Verification WHEN 'Refuted' THEN 'No' WHEN 'Confirmed' THEN 'Yes' ELSE 'Possibly' END AS Answer,
       CASE WHEN m.Origin = 'OtherClinic' THEN 'Other clinic'
            WHEN m.Origin = 'PharmaNet' THEN 'PharmaNet'
            WHEN m.StaffId IS NULL THEN 'Patient'
            WHEN s.Role = 'Doctor' THEN 'Physician'
            WHEN s.Role = 'MOA' THEN 'Front desk'
            ELSE s.Role END AS AuthorLabel,
       date(a.AssertedAt) AS Date, a.Statement
FROM Patient p
JOIN Visit v ON v.PatientId = p.Id
JOIN ClinicalEntry e ON e.VisitId = v.Id
JOIN Allergy al ON al.ClinicalEntryId = e.Id
JOIN Assertion a ON a.ClinicalEntryId = e.Id
JOIN Message m ON m.Id = a.MessageId
LEFT JOIN Staff s ON s.Id = m.StaffId
WHERE p.Name = 'Elena Marsh' AND p.DateOfBirth = '1971-05-14'
  AND lower(al.Substance) LIKE '%penicillin%'
  AND NOT EXISTS (SELECT 1 FROM Assertion n WHERE n.SupersedesId = a.Id);

-- Q4. Nurse recommendations by outcome. "accepted": a doctor decision on the same entry confirms it.
--     "revised": another assertion supersedes it. "open": nothing supersedes it.
SELECT CASE WHEN n.Id IS NULL THEN 'open'
            WHEN n.ClinicalEntryId = r.ClinicalEntryId AND n.Intent = 'Decision'
                 AND n.Verification = 'Confirmed' AND ns.Role = 'Doctor' THEN 'accepted'
            ELSE 'revised' END AS Outcome,
       COUNT(*) AS Recommendations
FROM Assertion r
JOIN Message rm ON rm.Id = r.MessageId
JOIN Staff rs ON rs.Id = rm.StaffId AND rs.Role = 'Nurse'
LEFT JOIN Assertion n ON n.SupersedesId = r.Id
LEFT JOIN Message nm ON nm.Id = n.MessageId
LEFT JOIN Staff ns ON ns.Id = nm.StaffId
WHERE r.Intent = 'Recommendation'
GROUP BY Outcome
ORDER BY Outcome;

-- Q5. The visit timeline of one patient, with the locations (M:N TakesPlaceIn).
--     Location.Type gives the department of the location.
SELECT date(v.StartDate) AS VisitDate, v.Class, v.Reason, l.Name AS Location, l.Type AS Department,
       vl.StartDate AS ArrivedAt, vl.EndDate AS LeftAt
FROM Patient p
JOIN Visit v ON v.PatientId = p.Id
JOIN VisitLocation vl ON vl.VisitId = v.Id
JOIN Location l ON l.Id = vl.LocationId
WHERE p.Name = 'Elena Marsh' AND p.DateOfBirth = '1971-05-14'
ORDER BY vl.StartDate;

-- Q6. The messages about one patient: the sender (a staff member, or the patient), the channel,
--     and the number of assertions per source (human or agent).
SELECT m.IdentifierValue AS Message, COALESCE(s.Name, 'Patient') AS Sender, m.Channel, m.Origin,
       SUM(a.Source = 'Human') AS HumanAssertions, SUM(a.Source = 'Agent') AS AgentAssertions
FROM Message m
LEFT JOIN Staff s ON s.Id = m.StaffId
JOIN Assertion a ON a.MessageId = m.Id
JOIN ClinicalEntry e ON e.Id = a.ClinicalEntryId
JOIN Visit v ON v.Id = e.VisitId
JOIN Patient p ON p.Id = v.PatientId
WHERE p.Name = 'Elena Marsh' AND p.DateOfBirth = '1971-05-14'
GROUP BY m.Id
ORDER BY m.SentAt;

-- Q7. The current active medications of one patient.
SELECT med.Name AS Medication, pr.Dosage, pr.Frequency, pr.Status, COALESCE(s.Name, 'Patient') AS Author,
       date(a.AssertedAt) AS Date
FROM Patient p
JOIN Visit v ON v.PatientId = p.Id
JOIN ClinicalEntry e ON e.VisitId = v.Id
JOIN Prescription pr ON pr.ClinicalEntryId = e.Id
JOIN Medication med ON med.Id = pr.MedicationId
JOIN Assertion a ON a.ClinicalEntryId = e.Id
JOIN Message m ON m.Id = a.MessageId
LEFT JOIN Staff s ON s.Id = m.StaffId
WHERE p.Name = 'Elena Marsh' AND p.DateOfBirth = '1971-05-14'
  AND pr.Status = 'active'
  AND a.Verification NOT IN ('Refuted', 'EnteredInError')
  AND NOT EXISTS (SELECT 1 FROM Assertion n WHERE n.SupersedesId = a.Id);

-- Q8. Staff by department and role (ISA: each staff member has one subtype row).
SELECT d.Name AS Department, s.Role, COUNT(*) AS Staff,
       SUM(n.Designation = 'RN') AS RegisteredNurses,
       SUM(mo.CertificationNumber IS NOT NULL) AS CertifiedMOAs
FROM Department d
JOIN WorksIn w ON w.DepartmentId = d.Id
JOIN Staff s ON s.Id = w.StaffId
LEFT JOIN Doctor dr ON dr.StaffId = s.Id
LEFT JOIN Nurse n ON n.StaffId = s.Id
LEFT JOIN MOA mo ON mo.StaffId = s.Id
GROUP BY d.Id, s.Role
ORDER BY d.Name, s.Role;

-- Q9a. The most common current diagnoses (over all patients).
SELECT e.Display AS Diagnosis, COUNT(DISTINCT v.PatientId) AS Patients
FROM ClinicalEntry e
JOIN Diagnosis dg ON dg.ClinicalEntryId = e.Id
JOIN Visit v ON v.Id = e.VisitId
JOIN Assertion a ON a.ClinicalEntryId = e.Id
WHERE dg.ClinicalStatus = 'active'
  AND NOT EXISTS (SELECT 1 FROM Assertion n WHERE n.SupersedesId = a.Id)
GROUP BY e.Code, e.CodeSystem
ORDER BY Patients DESC, Diagnosis
LIMIT 10;

-- Q9b. The longest revision chains (for example, the renewals of one medication).
WITH RECURSIVE chain (HeadId, Id, Length) AS (
    SELECT a.Id, a.Id, 1 FROM Assertion a
    WHERE a.SupersedesId IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM Assertion n WHERE n.SupersedesId = a.Id)
    UNION ALL
    SELECT c.HeadId, a.SupersedesId, c.Length + 1
    FROM chain c JOIN Assertion a ON a.Id = c.Id
    WHERE a.SupersedesId IS NOT NULL
)
SELECT e.Display AS CurrentFact, p.Name AS Patient, MAX(c.Length) AS ChainLength
FROM chain c
JOIN Assertion h ON h.Id = c.HeadId
JOIN ClinicalEntry e ON e.Id = h.ClinicalEntryId
JOIN Visit v ON v.Id = e.VisitId
JOIN Patient p ON p.Id = v.PatientId
GROUP BY c.HeadId
ORDER BY ChainLength DESC
LIMIT 5;

-- Q10. Trace an answer of the Care Assistant: chat turn -> citations -> assertion -> message -> author.
SELECT cs.IdentifierValue AS Session, t.Seq AS Turn, t.Text AS Answer, ct.Rank,
       e.Display AS Fact, a.Verification, COALESCE(s.Name, 'Patient') AS Author, m.Origin,
       date(a.AssertedAt) AS Date
FROM ChatSession cs
JOIN ChatTurn t ON t.ChatSessionId = cs.Id AND t.Speaker = 'Assistant'
JOIN Citation ct ON ct.ChatTurnId = t.Id
JOIN Assertion a ON a.Id = ct.AssertionId
JOIN ClinicalEntry e ON e.Id = a.ClinicalEntryId
JOIN Message m ON m.Id = a.MessageId
LEFT JOIN Staff s ON s.Id = m.StaffId
ORDER BY cs.Id, t.Seq, ct.Rank;

-- Q11. The access log of one patient on a fixed date: who read the record, and the denied attempts.
SELECT ae.At, ae.Action, ae.Outcome, ae.ActorRole, COALESCE(s.Name, ae.ActorValue) AS Actor, ae.Path
FROM AuditEvent ae
LEFT JOIN Staff s ON s.IdentifierSystem = ae.ActorSystem AND s.IdentifierValue = ae.ActorValue
WHERE ae.SubjectName = 'Elena Marsh' AND ae.SubjectDateOfBirth = '1971-05-14'
  AND date(ae.At) = '2026-10-29'
ORDER BY ae.At;

-- Q12. What the patient can see (the patient-visible rule). An item is visible when it is current,
--      it is not entered in error, and it is a doctor decision by a person, a confirmed
--      observation or lab result, or a report that the patient sent.
SELECT e.Category, e.Display, a.Verification, date(a.AssertedAt) AS Date, a.Statement
FROM Patient p
JOIN Visit v ON v.PatientId = p.Id
JOIN ClinicalEntry e ON e.VisitId = v.Id
JOIN Assertion a ON a.ClinicalEntryId = e.Id
JOIN Message m ON m.Id = a.MessageId
LEFT JOIN Staff s ON s.Id = m.StaffId
WHERE p.Name = 'Elena Marsh' AND p.DateOfBirth = '1971-05-14'
  AND NOT EXISTS (SELECT 1 FROM Assertion n WHERE n.SupersedesId = a.Id)
  AND a.Verification <> 'EnteredInError'
  AND ((a.Intent = 'Decision' AND a.Source = 'Human' AND s.Role = 'Doctor')
       OR (e.Category IN ('Observation', 'LabReport') AND a.Verification = 'Confirmed')
       OR (m.StaffId IS NULL AND m.Origin = 'Patient'))
ORDER BY e.Category, a.AssertedAt;

-- Q13. The current care team of a patient: care-team entries that nothing supersedes and that are
--      active, with the members joined to Staff by their identifier values.
SELECT date(v.StartDate) AS VisitDate, ct.Name AS CareTeam, s.Name AS Member, s.Role, ctm.Role AS TeamRole
FROM Patient p
JOIN Visit v ON v.PatientId = p.Id
JOIN ClinicalEntry e ON e.VisitId = v.Id
JOIN CareTeam ct ON ct.ClinicalEntryId = e.Id AND ct.Status = 'active'
JOIN Assertion a ON a.ClinicalEntryId = e.Id
JOIN CareTeamMember ctm ON ctm.CareTeamId = ct.Id
JOIN Staff s ON s.IdentifierSystem = ctm.MemberSystem AND s.IdentifierValue = ctm.MemberValue
WHERE p.Name = 'Elena Marsh' AND p.DateOfBirth = '1971-05-14'
  AND NOT EXISTS (SELECT 1 FROM Assertion n WHERE n.SupersedesId = a.Id)
ORDER BY VisitDate, s.Name;

-- Q14a. One page of the current chart of Patient B (Marlin805 Reggie481 Nienow652, born 1966-02-18):
--       the second page of 25 items (items 26 to 50). The API gives each list in pages (doc/api.md section 1.5).
--       The order is the order of the chart: the category, then the newest first, then the Id.
--       The Id is the last key, so the order is stable: an item cannot show on two pages.
--       Patient B is in the full database only (main.py ensure-db). On the scenario data (01 + 02), the page is empty.
SELECT e.Category, e.Display, a.Verification, date(a.AssertedAt) AS Date,
       CASE WHEN m.StaffId IS NULL THEN p.Name ELSE s.Name END AS Author
FROM Patient p
JOIN Visit v ON v.PatientId = p.Id
JOIN ClinicalEntry e ON e.VisitId = v.Id
JOIN Assertion a ON a.ClinicalEntryId = e.Id
JOIN Message m ON m.Id = a.MessageId
LEFT JOIN Staff s ON s.Id = m.StaffId
WHERE p.Name = 'Marlin805 Reggie481 Nienow652' AND p.DateOfBirth = '1966-02-18'
  AND NOT EXISTS (SELECT 1 FROM Assertion n WHERE n.SupersedesId = a.Id)
ORDER BY CASE e.Category WHEN 'Allergy' THEN 0 WHEN 'Diagnosis' THEN 1 WHEN 'Prescription' THEN 2
                         WHEN 'Observation' THEN 3 WHEN 'LabOrder' THEN 4 WHEN 'LabReport' THEN 5
                         WHEN 'Procedure' THEN 6 WHEN 'CareTeam' THEN 7 ELSE 8 END,
         julianday(a.AssertedAt) DESC, a.Id DESC
LIMIT 25 OFFSET 25;

-- Q14b. The number of items on all pages of Q14a: the same FROM and WHERE clauses, with COUNT(*).
SELECT COUNT(*) AS Items
FROM Patient p
JOIN Visit v ON v.PatientId = p.Id
JOIN ClinicalEntry e ON e.VisitId = v.Id
JOIN Assertion a ON a.ClinicalEntryId = e.Id
JOIN Message m ON m.Id = a.MessageId
LEFT JOIN Staff s ON s.Id = m.StaffId
WHERE p.Name = 'Marlin805 Reggie481 Nienow652' AND p.DateOfBirth = '1966-02-18'
  AND NOT EXISTS (SELECT 1 FROM Assertion n WHERE n.SupersedesId = a.Id);
