# TRIAD user flows

This file describes what the TRIAD prototype shows to each user type.
It is a living document. We change it when the app changes.
The flows in this file drive the dataset, the database, the API and the screens.

**Status:** version 3 (2026-11-01). The team approved sections 0.1 and 0.2. Version 2 follows the tree-shaped ER model: care-team changes are assertions, and the arrival step comes before the waiting-room step. Version 3 adds the review fixes: the current care team is active and not superseded, the MOA can supersede care-team entries, a patient report about an item is an assertion about that item, and each message has at least one fact.

---

## 0. The prototype world

### 0.1 One hospital

The prototype has one hospital: **TRIAD General Hospital**. The hospital is fictional.
It has many patients and many providers.

The data comes from the Synthea FHIR R4 sample (112 patients).
Synthea spreads these patients over 234 providers in Massachusetts.
The loader moves ("re-homes") all of them into TRIAD General Hospital:

- Each Synthea visit goes to the default location of one department. The visit class selects the department. The department of a visit is the department of its location.
- Each Synthea doctor works in the department where they saw the most visits.
- The original Synthea providers and sites stay in the source FHIR files (`src/backend/data/`). The database keeps only TRIAD General.

| Synthea visit class | Department |
|---|---|
| EMER (emergency) | Emergency |
| IMP (inpatient) | Inpatient Medicine |
| AMB at a clinic | Family Medicine |
| AMB at an urgent-care site | Urgent Care |
| HH (home health) | Home Health |
| VR (virtual) | Virtual Care |

The journey also needs two departments that Synthea does not give:
**Cardiology** (for the transfer) and **Front Office** (for the front desk).

**Decision:** the team approved the re-homing and the department list.

### 0.2 Staff mix

Synthea gives doctors only (267 general practice physicians).
The flows also need nurses and front-desk staff (MOAs).

**Decision:** the team selected method A (seeded staff). The two methods were:

- **A. Seeded staff (selected).** A script with a fixed seed writes FHIR Practitioner, PractitionerRole and CareTeam resources. Each department gets nurses and MOAs (see 0.3). Each patient gets a care team.
- **B. Curated staff.** We write a few nurses and MOAs by hand. Only the demo patients get full care teams.

### 0.3 Data requirements

The dataset must give the items in this table. Phase 2 of the plan builds them.

| Item | Requirement |
|---|---|
| Departments | Emergency, Inpatient Medicine, Family Medicine, Urgent Care, Home Health, Virtual Care, Cardiology, Front Office. All are part of TRIAD General Hospital. |
| Locations | Emergency Unit, ER Waiting, ER Bed 1 to ER Bed 4 and the Emergency Registration Desk; Cardiology Ward, Cardiology Room 401, Cardiology Room 402 and the Cardiology Desk; Family Medicine Room 1 and the Family Medicine Desk; Urgent Care Room 1; Inpatient Ward 3; Patient Home; Virtual Visit; Main Front Desk; Old Storage Room (not used, for the delete step). Each department has one default location for re-homed visits. |
| Doctors | The 234 Synthea doctors that the visits use, plus the demo doctors in 0.4. |
| Nurses (method A) | Emergency 4, Inpatient Medicine 3, Cardiology 3, Family Medicine 2, Urgent Care 2, Home Health 2, Virtual Care 1. |
| MOAs (method A) | Front Office 3, Emergency 1, Family Medicine 1, Cardiology 1. |
| Care teams | Every patient has at least one care-team entry. The entry is a clinical entry (FHIR CareTeam) in a visit, with its message and its assertion. Use the Synthea care team if one is active. If not, use the doctor of the latest visit and one nurse of that department. A Front Office MOA is the author. |
| Staff languages | Each staff member has one or more languages. |
| Patient A | A curated patient with the penicillin history from the 3MT slide (see 0.4). |
| Patient B | A Synthea patient. The patient is alive and is an adult on the demo date. The patient has an active metformin prescription and no penicillin allergy. Of the 3 eligible patients, Patient B has the fewest resources (879). |
| Demo activity | Patient A has one saved chat with citations. The audit log has some reads and one denied access. |
| Demo date | `TRIAD_NOW = 2026-10-30T09:00:00-04:00` (Eastern time, because the hospital is in Worcester, MA). This date is after the Synthea build date (2026-10-21). It is before the time change on 2026-11-01. |

### 0.4 Demo users (pinned at the top of the picker)

All names are fictional.

| Role | Name | Department | Use in the journey |
|---|---|---|---|
| Patient | Elena Marsh (Patient A) | — | The 3MT slide patient |
| Patient | Marlin805 Reggie481 Nienow652 (Patient B), born 1966-02-18 | — | Walks the hospital visit. Synthea names keep their digits. |
| MOA | Sofia Alvarez | Front Office | Front desk |
| Nurse | Priya Nair | Emergency | Triage nurse, on B's care team |
| Nurse | Tom Becker | Cardiology | Ward nurse, added at transfer |
| Nurse | Jun Park | Home Health | **Not** on B's care team (privacy check) |
| Doctor | Dr. Amara Okafor | Emergency | ER doctor, on B's and A's care teams |
| Doctor | Dr. Lucas Brennan | Cardiology | Cardiologist |

---

## 1. The user picker (no login)

- The app has no login. This is a prototype. Do not put real patient data in it.
- In the top bar, select a **user type**: Patient, Doctor, Nurse or MOA.
- Then select a **user**. Patients show their name and date of birth. Staff show their department.
- The demo users show at the top of the list.
- The app keeps your choice in the browser. It sends the choice with each request in the `X-Triad-User` header.
- The link parameter `?as=<role>:<identifier>` also sets the user. Use it to open more than one user in more than one tab.
- When you change the user, the app goes to the home page of the new role.

---

## 2. Permissions

The backend checks each action. A denied action gives a 403 message and an audit record.

| Action | Patient | MOA | Nurse | Doctor |
|---|---|---|---|---|
| Search patients by name and date of birth | self | all | all | all |
| Register a patient, edit demographics | read self | all | — | — |
| Open the clinical chart | self, visible items only | — | care team | care team |
| Check in a visit, end a visit | — | yes | — | end visit, care team |
| Assign or move the visit location | — | yes | care team | care team |
| Add or remove care-team members | — | yes | — | if on the team |
| Record assertions (allowed intent) | Report (own) | Report | Report, Recommendation, Observation and lab results | any |
| Supersede an assertion | own reports, items in "My record" | care-team entries | Reports, Recommendations | any |
| Ask the Care Assistant | about self, visible items | — | care team | care team |
| Tell the Care Assistant a fact (LLM or fake LLM) | own reports | — | yes | yes |
| Manage the directory (departments, locations, staff, medications) | — | yes | — | — |
| View the audit log | own | — | — | care-team patients |

### 2.1 Rules

- **Care team rule.** A nurse or a doctor can open a chart only if they are a member of a current care-team entry of that patient. A care-team entry is current when nothing supersedes its assertion and its status is "active". A change to the care team is a new entry that supersedes the earlier one, so each change has an author and a date. The Care team tab shows the current team of the open visit only.
- **Patient reports.** A report that a patient sends through the app is a message with no staff issuer. Its origin is "Patient" and its channel is "App".
  - A report about an item that exists (for example "I stopped taking metformin") is a new assertion about that item. It needs no new visit.
  - A report about a new fact goes into the open visit. If no visit is open, the app opens a virtual visit (class VR) that ends at once, so it never becomes the open visit.
- **Each message has at least one fact.** An intake note becomes an observation (chief complaint). If the Care Assistant finds no fact in a "tell" turn, it makes no message.
- **Supersede guard.** When the current item is visible to the patient, only a doctor decision or the patient's own report can supersede it.
- **Patient-visible rule.** A patient sees an item only if all of these are true:
  - It is the current item. Nothing supersedes it.
  - Its verification is not "entered in error".
  - It is one of these:
    - a doctor decision that a person (not the agent) made;
    - a confirmed observation or lab result;
    - a report that the patient sent.
- **Chain view for patients.** A patient sees the current item only. A patient does not see the items that it superseded.
- **Synthea items.** Synthea diagnoses, prescriptions, procedures and allergies count as doctor decisions. Synthea observations and lab reports count as reports. They are confirmed when their status is final.
- **"What is my plan?"** The answer uses the open visit. If no visit is open, it uses the latest visit that is not a virtual report visit.
- **MOA patient page.** An MOA sees demographics, visits and the care team. An MOA does not see the chart or the chat.
- **Audit.** Every action on one patient writes an audit record. A denied action also writes a record.

---

## 3. The hospital-visit journey

This is the main flow of the prototype. Each user group uses the same app.
Each step gives the user, the page, the action and the expected result.

Pages:
- `/patients`: Front desk, My patients and Find a patient.
- `/patients/:id`: the patient page. The chart is on the left. The Care Assistant is on the right. The tabs are Chart, Visit, Care team and Audit.
- `/directory`: departments, locations, staff and medications.

Chat mode: if no API key is set, the app uses the **fake LLM**. All steps then work offline.

### Step 0. The 3MT slide (Patient A)

- **User:** Dr. Amara Okafor (Doctor).
- **Page:** `/patients/:id` for Elena Marsh.
- **Action:** Ask the Care Assistant: "Is she allergic to penicillin?"
- **Expected result:** "No. A physician ruled it out with an allergy test on Oct 2, 2026." The card shows the current assertion. Below it, the card shows two superseded assertions with a line through them: "Other clinic, 2024: penicillin allergy (copied)" and "Front desk, 2019: penicillin allergy".

### Step 1. Arrival (front desk)

- **User:** Sofia Alvarez (MOA).
- **Page:** `/patients` (Front desk), then `/patients/:id` (Visit and Care team tabs).
- **Action:**
  1. Find Patient B by name and date of birth.
  2. Change the phone number. (**UPDATE**)
  3. Check in an emergency visit. Assign the location "ER Waiting".
  4. Set the care team: Priya Nair and Dr. Amara Okafor.
  5. Add Jun Park by mistake. Then remove Jun Park.
  6. Write an intake note: "Shortness of breath since this morning."
- **Expected result:**
  - The visit is open in "ER Waiting".
  - The care team has Priya Nair and Dr. Amara Okafor only.
  - Each care-team change is a new care-team entry that supersedes the earlier one. The chain shows: {Nair, Okafor} ← {Nair, Okafor, Park} ← {Nair, Okafor}. Each step names Sofia Alvarez as the author.
  - The intake note is an observation (chief complaint) in the open visit.

### Step 2. Waiting room (Patient B)

- **User:** Patient B.
- **Page:** `/patients/:id` (My record).
- **Action:**
  1. Ask: "What medications am I taking?"
  2. On the metformin item, select **Report**. Write: "I stopped taking metformin."
- **Expected result:**
  1. The answer lists metformin.
  2. The report is a new assertion about the metformin item. Its message has no staff issuer. Its origin is "Patient" and its channel is "App".
  3. The report supersedes the metformin prescription. The chain is: prescription ← patient report.

### Step 3. Triage (nurse)

- **User:** Priya Nair (Nurse).
- **Page:** `/patients` (My patients), then `/patients/:id`.
- **Action:**
  1. Open Patient B. Read the earlier visits.
  2. Record vital signs: heart rate, blood pressure, oxygen saturation.
  3. Record an assessment: "Possible asthma attack." (Recommendation, provisional)
  4. Recommend a salbutamol inhaler. (Recommendation)
  5. Move the patient to "ER Bed 2".
  6. Ask the Care Assistant: "Any allergies?"
- **Expected result:** The chart shows the new items with the nurse as author. The answer cites the allergy records with their authors.

### Step 4. Physician (doctor)

- **User:** Dr. Amara Okafor (Doctor).
- **Page:** `/patients/:id`.
- **Action:**
  1. Ask: "What did the nurse recommend?"
  2. Order a troponin test. Record the result.
  3. Revise the assessment to "Possible heart failure." This decision supersedes the nurse's asthma assessment.
  4. Tell the Care Assistant: "The patient's father died of a heart attack."
  5. Confirm the new family-history item.
  6. Prescribe furosemide. This decision supersedes the inhaler recommendation.
  7. Resolve metformin. This decision supersedes the patient's report.
- **Expected result:**
  1. The answer cites the nurse's recommendations.
  2. The lab order and the lab result show in the chart.
  3. The chain shows: asthma (superseded) ← heart failure.
  4. The agent records the family history as **unconfirmed**. The source is "Agent".
  5. The doctor's confirmation supersedes the agent's item.
  6. The chain shows: inhaler (superseded) ← furosemide.
  7. The chain shows: prescription ← patient report ← doctor decision.

### Step 5. Transfer (nurse and front desk)

- **User:** Priya Nair (Nurse), then Sofia Alvarez (MOA).
- **Action:**
  1. The nurse moves the patient to "Cardiology Room 401".
  2. The MOA adds Tom Becker to the care team. This is a new care-team entry that supersedes the earlier one.
- **Expected result:** The visit shows two locations with times. Tom Becker can open the chart.

### Step 6. Evening (Patient B)

- **User:** Patient B.
- **Action:** Ask: "What is my plan?"
- **Expected result:** The answer gives the heart-failure work-up and furosemide. It does **not** give asthma or the inhaler. The cards show the current items only.

This step shows the main idea of TRIAD. A long record does not make the assistant use an old fact.

### Step 7. Privacy check (nurse not on the care team)

- **User:** Jun Park (Nurse).
- **Page:** `/patients` (Find a patient).
- **Action:** Find Patient B. Open the chart.
- **Expected result:** A 403 panel: "You are not on this patient's care team. This attempt is in the audit log." Patient B can see the denied attempt in the Audit tab.

### Step 8. Directory (front desk)

- **User:** Sofia Alvarez (MOA).
- **Page:** `/directory`.
- **Action:**
  1. Change the phone number of a staff member. (**UPDATE**)
  2. Try to delete the Emergency department. (It has staff.)
  3. Delete the unused location "Old Storage Room". (**DELETE**)
- **Expected result:**
  1. The new phone number shows.
  2. A 409 message: the department has staff, so you cannot delete it.
  3. The location goes away from the list.

### Step 9. Discharge (doctor)

- **User:** Dr. Amara Okafor (Doctor).
- **Action:** End the visit.
- **Expected result:** The visit shows an end time. The chart keeps the full history, with the author of each item.

---

## 4. Flows by user type

### Patient

- See "My record": the visible items only.
- Report a change on an item (for example, "I stopped taking a medicine").
- Ask the Care Assistant about your own record. See past chats.
- See who opened your record (your audit log).

### MOA (front desk)

- Find or register a patient. Edit demographics.
- Check in a visit. Assign a location. End a visit.
- Add or remove care-team members.
- Write intake notes and phone notes.
- Manage the directory: departments, locations, staff and medications.

### Nurse

- See "My patients" (your care teams).
- Find any patient. If you are not on the care team, you get a 403.
- Record vital signs, assessments and recommendations.
- Move a patient to a new location.
- Ask the Care Assistant. Tell it facts (LLM or fake LLM mode).

### Doctor

- See "My patients".
- Review the chart with the Care Assistant. Answers show their sources.
- Make decisions. Order tests and record results. Prescribe.
- Supersede, confirm or refute items.
- Tell the Care Assistant facts.
- End visits. See the audit log of your patients.

---

## 5. Out of scope

- Login and authentication.
- A release workflow for patient data (the patient-visible rule replaces it).
- Scheduling.

---

## 6. How to check the flows

There are four ways to check the flows. The first way is the fastest.

1. **Read.** Each step in section 3 gives the expected result. Screenshots of each step are in `doc/screenshots/`.
2. **Click through.**
   1. Run `./src/scripts/quickstart.sh`.
   2. Open http://localhost:8000.
   3. Open the **Demo guide** panel in the top bar. It lists the steps of section 3.
   4. On each step, select **Act as ⟨user⟩**. The app sets the user and opens the correct page.
   5. To start again, run `./src/scripts/quickstart.sh --reset-db`.
3. **Automated test.**
   - Run `pytest src/backend/tests/integration/test_hospital_visit.py`. The test does each step through the API.
   - The Playwright test `hospital_visit.spec.ts` does the same steps in a browser. It also makes the screenshots.
4. **Report.** The figures in the Milestone 4 report show the main steps.
