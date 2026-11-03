# TRIAD API contract (Milestone 4)

This file is the contract between the backend (`src/backend/api/`) and the frontend (`src/frontend/`).
Both sides must follow it. If a change is necessary, change this file first, then change the code.
The permission rules and the journey are in `USER_FLOWS.md`. This file does not repeat them.

## 1. General rules

- The base path is `/api`. Each request body and response body is JSON. Field names are camelCase.
- A time is ISO 8601 with an offset, for example `2026-10-30T09:01:00-04:00`. A date (date of birth) is `YYYY-MM-DD`.
- An `id` is the integer `Id` of the table row.
- The frontend sends the current user in the header `X-Triad-User: <user key>` (section 1.1).
  `GET /api/health`, `GET /api/users` and `GET /api/users/{key}` do not need the header. All other endpoints need it.
- `python src/backend/main.py serve` serves the API on port 8000. If `src/frontend/dist/` exists, it also serves the
  built frontend, and each path that does not start with `/api` gets `index.html` (deep links work).
- In development, Vite serves the frontend on port 5173 and sends `/api` to `http://127.0.0.1:8000`.

### 1.1 User keys

A user key is `<Role>:<identifier value>`.

- **Staff:** the value of the staff identifier. Examples: `Doctor:E1005` (Dr. Amara Okafor), `Doctor:9999999939` (a Synthea doctor; the value is the NPI).
- **Patient:** the value of the first patient identifier in this order of systems:
  `https://triad.example/fhir/sid/mrn`, then `https://github.com/synthetichealth/synthea`.
  A patient that the MOA registers gets a new MRN (`MRN-000002`, and so on).

The demo users show first in the picker, in this order:

| User key | Name | Role |
|---|---|---|
| `Patient:MRN-000001` | Elena Marsh (Patient A) | Patient |
| `Patient:0c1b260c-7f32-fdd5-15dd-1160caf24c2b` | Marlin805 Reggie481 Nienow652 (Patient B) | Patient |
| `MOA:E1001` | Sofia Alvarez | MOA |
| `Nurse:E1002` | Priya Nair | Nurse |
| `Nurse:E1003` | Tom Becker | Nurse |
| `Nurse:E1004` | Jun Park | Nurse |
| `Doctor:E1005` | Amara Okafor | Doctor |
| `Doctor:E1006` | Lucas Brennan | Doctor |

### 1.2 Errors

Each error has this body: `{ "code": "...", "message": "...", "fields": { ... } }`. `fields` is optional.

| Status | `code` | When |
|---|---|---|
| 401 | `no_user` | The header `X-Triad-User` is missing, or the key is not a known user. |
| 403 | `forbidden` | The permission rules do not allow the action. If the action is about one patient, the backend writes an audit record with Outcome = Denied before it sends the 403. |
| 404 | `not_found` | The row does not exist. |
| 409 | `conflict` | A unique key exists already; a row is in use and cannot be deleted; `supersedesId` is not the current assertion (the data changed); the patient has an open visit already. |
| 422 | `validation` | The input is not correct, or a CHECK or a trigger stops the statement. `fields` maps a field name to a message. |

The 403 for the chart of a patient whose care team does not include the user has this message:
"You are not on this patient's care team. This attempt is in the audit log."

### 1.3 Clock

- The environment variable `TRIAD_NOW` sets the demo time. The default is `2026-10-30T09:00:00-04:00` (from `hospital_profile.json`). `TRIAD_NOW=system` uses the computer clock.
- Each write gets the time max(`TRIAD_NOW`, the latest time in the database) + 1 minute. So the times always increase, also after a restart of the server.

### 1.4 Chat mode

- `TRIAD_LLM=fake` (the default): the rule-based lookups answer each question, and a fake extractor finds facts in a "tell" turn. No network is necessary.
- `TRIAD_LLM=llm`: LiteLLM words the answer and extracts facts. `TRIAD_LLM_MODEL` sets the model (default `anthropic/claude-opus-5-5`). The provider key comes from the usual environment variable (for example `ANTHROPIC_API_KEY`). If the call fails, the backend uses the fake mode for that turn.
- The rules always select the evidence. The assistant cites only the assertions that the rules returned in that turn.

## 2. Types (TypeScript notation)

The backend sends exactly these shapes. `T | null` means the field is always present and can be null.

```ts
type Role = 'Patient' | 'Doctor' | 'Nurse' | 'MOA';
type StaffRole = 'Doctor' | 'Nurse' | 'MOA';
type Category = 'Diagnosis' | 'Procedure' | 'Allergy' | 'Observation' | 'LabOrder' | 'LabReport' | 'Prescription' | 'CareTeam';
type Intent = 'Report' | 'Recommendation' | 'Decision';
type Source = 'Human' | 'Agent';
type Verification = 'Unconfirmed' | 'Provisional' | 'Differential' | 'Confirmed' | 'Refuted' | 'EnteredInError';
type Channel = 'InPerson' | 'Phone' | 'Video' | 'Email' | 'Fax' | 'Transfer' | 'Chat' | 'App';
type Origin = 'Patient' | 'Staff' | 'OtherClinic' | 'PharmaNet' | 'Lab' | 'Agent';
type VisitClass = 'AMB' | 'EMER' | 'IMP' | 'HH' | 'VR';
type ChatMode = 'rules' | 'fake' | 'llm';

interface ApiError { code: 'no_user' | 'forbidden' | 'not_found' | 'conflict' | 'validation'; message: string; fields?: Record<string, string>; }
interface Identifier { system: string; value: string; }
interface Address { street: string | null; city: string | null; region: string | null; postalCode: string | null; country: string | null; }

// Users
interface UserView {
  key: string; role: Role; name: string;
  detail: string;            // patient: "born 1971-05-14"; staff: the department names, for example "Emergency"
  pinned: boolean;           // true for a demo user (section 1.1)
  patientId: number | null; staffId: number | null;
}

// Patients
interface Permissions {      // what the current user can do for this patient. The UI uses it to show buttons. The backend checks again.
  viewChart: boolean; chat: boolean; tell: boolean; editDemographics: boolean;
  checkIn: boolean; endVisit: boolean; moveLocation: boolean; manageCareTeam: boolean; viewAudit: boolean;
  recordIntents: Intent[];   // the intents that the user can record
}
interface PatientSummary { id: number; name: string; dateOfBirth: string; sex: 'female' | 'male' | 'other' | 'unknown'; phoneNumber: string | null; openVisitId: number | null; }
interface Patient extends PatientSummary { address: Address; identifiers: Identifier[]; permissions: Permissions; }

// Visits
interface VisitLocation { locationId: number; name: string; department: string | null; startDate: string; endDate: string | null; }
interface Visit {
  id: number; patientId: number; identifier: Identifier; class: VisitClass; type: string | null; reason: string | null;
  startDate: string; endDate: string | null; isOpen: boolean;
  department: string | null;  // the department of the latest location
  locations: VisitLocation[]; // oldest first
}

// Assertions
interface Author {
  name: string;              // the staff name, or the patient name for a patient report
  role: Role;
  staffId: number | null;
  label: string;             // the short label of the 3MT slide: "Physician", "Nurse", "Front desk", "Other clinic", "Patient", "Agent"
}
interface AssertionView {
  id: number; entryId: number; messageId: number; seq: number; visitId: number;
  category: Category; code: string; codeSystem: string; display: string;
  details: Record<string, string | number | null>; // the subtype columns in camelCase, for example { value, unit } or { medication, dosage, status }
  statement: string; intent: Intent; source: Source; verification: Verification; assertedAt: string;
  author: Author; channel: Channel; origin: Origin;
  supersedesId: number | null; supersededById: number | null; isCurrent: boolean;
  patientVisible: boolean;   // the patient-visible rule of USER_FLOWS.md section 2.1
}
interface Chart { patientId: number; items: AssertionView[]; }   // newest first
interface Chain { headId: number; items: AssertionView[]; }      // newest first; items[0] is the current one. A patient gets the head only.

// Care team
interface CareTeamMember {
  system: string; value: string; role: string | null;
  staffId: number | null; name: string; staffRole: StaffRole | null; department: string | null;
}
interface CareTeamVersion {
  entryId: number; assertionId: number; visitId: number; name: string | null; status: string;
  members: CareTeamMember[]; author: Author; assertedAt: string; isCurrent: boolean;
}
interface CareTeam { visitId: number; current: CareTeamVersion | null; chain: CareTeamVersion[]; } // chain: newest first, the current version included

// Records (new messages and assertions)
interface NewMessage {
  patientId: number;
  visitId?: number | null;   // the visit for new entries. Default: the open visit. See section 3.4.
  channel?: Channel;         // default: 'InPerson' for staff, 'App' for a patient
  text: string;              // the message text (the note)
  assertions: NewAssertion[];// one or more
}
interface NewAssertion {
  entryId?: number;          // an assertion about an entry that exists (confirm, refute, a report on an item)
  newEntry?: NewEntry;       // or a new entry. Give exactly one of entryId and newEntry.
  supersedesId?: number | null; // must be the current assertion of its chain, else 409
  intent: Intent; verification: Verification; statement: string;
}
interface NewEntry {
  category: Exclude<Category, 'CareTeam'>;
  code: string; codeSystem: string; display: string; text?: string | null;
  details: Record<string, string | number | null>; // see section 3.4
}
interface RecordResult { messageId: number; assertions: AssertionView[]; }
interface CodePreset { category: Category; code: string; codeSystem: string; display: string; details: Record<string, string | number | null>; }

// Chat
interface Card { rank: number; assertion: AssertionView; supersedes: AssertionView[]; } // supersedes: oldest first; empty for a patient
interface ChatTurn {
  id: number; seq: number; speaker: 'User' | 'Assistant'; text: string; createdAt: string;
  kind: 'ask' | 'tell' | null;  // null for a user turn
  cards: Card[];                // one card for each citation, by rank
  recordedIds: number[];        // a tell turn: the ids of the new unconfirmed assertions (they are also cards)
}
interface ChatSessionSummary { id: number; identifier: string; startedAt: string; mode: ChatMode; turnCount: number; firstQuestion: string | null; }
interface ChatSession { id: number; identifier: string; patientId: number; startedAt: string; mode: ChatMode; model: string | null; turns: ChatTurn[]; }
interface TurnResult { userTurn: ChatTurn; assistantTurn: ChatTurn; }

// Audit
interface AuditEvent {
  id: number; identifier: string; at: string;
  action: 'read' | 'create' | 'update' | 'delete' | 'ask' | 'tell'; outcome: 'Allowed' | 'Denied';
  actorRole: Role; actorKey: string; actorName: string | null; path: string; chatTurnId: number | null;
}

// Directory
interface Department { id: number; identifier: Identifier; name: string; type: string | null; phoneNumber: string | null; email: string | null; address: Address; staffCount: number; }
interface Location { id: number; identifier: Identifier; name: string; department: string | null; physicalType: string | null; phoneNumber: string | null; address: Address; inUse: boolean; }
interface StaffDepartment { departmentId: number; name: string; roleCode: string; specialty: string | null; }
interface Staff {
  id: number; key: string; identifier: Identifier; name: string; role: StaffRole;
  sex: string | null; email: string | null; phoneNumber: string | null; active: boolean;
  departments: StaffDepartment[]; languages: string[];
  licenseNumber: string | null; qualification: string | null;          // Doctor
  designation: 'RN' | 'LPN' | 'RPN' | 'NP' | null;                    // Nurse
  certificationNumber: string | null; desk: string | null; phoneExtension: string | null; // MOA
}
interface Medication { id: number; code: string; codeSystem: string; name: string; form: string | null; manufacturer: string | null; }
```

## 3. Endpoints

"Care team" means: the user is a member of a current care-team entry of the patient (USER_FLOWS.md section 2.1).

### 3.1 System and users

| Method and path | Body | Response | Who |
|---|---|---|---|
| `GET /api/health` | — | `{ status: 'ok', schemaVersion: number, mode: ChatMode, now: string }` | all, no header |
| `GET /api/users?role=&q=&limit=50` | — | `UserView[]` (demo users first, then by name) | all, no header |
| `GET /api/users/{key}` | — | `UserView` | all, no header |
| `GET /api/me` | — | `UserView` | any user |
| `GET /api/codes?category=` | — | `CodePreset[]` (the codes of the record form and the journey) | staff |

### 3.2 Patients

| Method and path | Body | Response | Who |
|---|---|---|---|
| `GET /api/patients?q=&dob=&scope=all\|care-team\|open-visits&limit=50` | — | `PatientSummary[]` | staff; a patient gets self only |
| `POST /api/patients` | `{ name, dateOfBirth, sex, phoneNumber?, address? }` | 201 `Patient` | MOA. 409 if (name, dateOfBirth) exists. |
| `GET /api/patients/{id}` | — | `Patient` | staff; a patient: self only |
| `PATCH /api/patients/{id}` | `{ sex?, phoneNumber?, address? }` | `Patient` | MOA. A change to name or dateOfBirth gives 422. |
| `DELETE /api/patients/{id}` | — | 204 | MOA. 409 if the patient has visits. |

`scope=care-team` is "My patients". `scope=open-visits` is the front desk list (patients with an open visit).
`q` matches part of the name (case is not important). `dob` matches the date of birth exactly.

### 3.3 Visits and care team

| Method and path | Body | Response | Who |
|---|---|---|---|
| `GET /api/patients/{id}/visits` | — | `Visit[]` (newest first) | self, MOA, care team |
| `POST /api/patients/{id}/visits` | `{ class, reason?, type?, locationId }` | 201 `Visit` | MOA. 409 if a visit is open. |
| `POST /api/visits/{id}/locations` | `{ locationId }` | `Visit` | MOA, care team. Ends the current location (EndDate = now) and adds the new one. |
| `POST /api/visits/{id}/end` | — | `Visit` | MOA, a doctor on the care team. Sets EndDate on the visit and on its open location. |
| `GET /api/visits/{id}/care-team` | — | `CareTeam` | self, MOA, care team |
| `PUT /api/visits/{id}/care-team` | `{ members: { system, value, role? }[], name? }` | `CareTeam` | MOA; a doctor on the care team |

`PUT .../care-team` makes a new CareTeam entry (Status = active) in the visit, with one message (Channel = InPerson, issued by the user)
and one assertion (Intent = Report, Source = Human, Verification = Confirmed). The assertion supersedes the current care-team assertion
of this visit, if there is one. Each member must be a staff identifier (else 422).

### 3.4 Chart, chains and records

| Method and path | Body | Response | Who |
|---|---|---|---|
| `GET /api/patients/{id}/chart?visitId=&category=&history=false` | — | `Chart` | self (patient-visible items only), care team |
| `GET /api/assertions/{id}/chain` | — | `Chain` | self (head only), care team |
| `POST /api/messages` | `NewMessage` | 201 `RecordResult` | see USER_FLOWS.md section 2 |

- The chart gives the current items (one per entry that has a current assertion). `history=true` also gives the superseded assertions (staff only).
- **Visit of a new entry.** The default is the open visit. A staff user must have an open visit (else 422). For a patient report about a new fact with no open visit, the backend makes a VR visit that ends at once (EndDate = StartDate).
- **The entry and version rule.** A new claim about the same fact (confirm, refute, a report on the item) is a new assertion on the same entry (`entryId`).
  A claim with different content (a new code, a new status, a new member list) is a new entry (`newEntry`) whose assertion supersedes the old one.
  The backend never changes a ClinicalEntry row or a subtype row after the insert.
- **Head check.** If the entry of the new assertion has a current assertion, `supersedesId` must be that assertion (else 409).
- **Origin and source.** A patient's message has no staff issuer, Origin = Patient and Channel = App. A staff message has Origin = Staff. The API always writes Source = Human. Only the chat "tell" writes Source = Agent.
- **`details` of a new entry** (the backend fills a missing date from the clock):
  - Diagnosis: `clinicalStatus` (default `active`), `onsetDate`, `severity`
  - Procedure: `performedDate`, `outcome`
  - Allergy: `substance`, `type`, `allergyCategory`, `criticality`, `clinicalStatus`
  - Observation: `value`, `unit`
  - LabOrder: `testName`, `priority` (`routine`, `urgent`, `asap`, `stat`), `specimen`
  - LabReport: `issuedDate`, `conclusion`
  - Prescription: `medicationCode`, `medicationSystem`, `medicationName`, `dosage`, `frequency`, `status` (`active`, `draft`, `stopped`, `completed`).
    The backend finds the Medication by (code, system). If it does not exist, the backend adds it.
- In an `AssertionView`, `details` of a Prescription has `medication` (the name), `dosage`, `frequency` and `status`.
  `details` of a CareTeam has `name`, `status` and `members` (the member names, separated by commas).

### 3.5 Care Assistant (chat)

| Method and path | Body | Response | Who |
|---|---|---|---|
| `GET /api/patients/{id}/chat/sessions` | — | `ChatSessionSummary[]` (the sessions of this user about this patient, newest first) | self, care team |
| `POST /api/patients/{id}/chat/sessions` | — | 201 `ChatSession` | self, care team |
| `GET /api/chat/sessions/{id}` | — | `ChatSession` | the user of the session |
| `POST /api/chat/sessions/{id}/turns` | `{ clientTurnId: string, text: string }` | `TurnResult` | the user of the session; still self or care team |

- `clientTurnId` is a random id that the frontend makes. If the same `clientTurnId` comes again, the backend sends the turns that it saved, and does not add new turns.
- The backend sorts each turn into "ask" or "tell". A tell makes one message (Channel = Chat) with one or more assertions (Source = Agent, Verification = Unconfirmed). If it finds no fact, it makes no message and says so.
- An MOA cannot use the chat (403).

### 3.6 Audit

| Method and path | Body | Response | Who |
|---|---|---|---|
| `GET /api/patients/{id}/audit` | — | `AuditEvent[]` (newest first) | self, a doctor on the care team |

The backend writes one audit record for each of these: a chart read, a chain read, an audit read, each write about one patient,
each chat turn (`ask` or `tell`, with `chatTurnId`) and each 403 about one patient (Outcome = Denied).
It does not write a record for list endpoints or for `GET /api/patients/{id}`.
The `path` of a record is the route, with a name for each id, for example `/api/patients/{patient}/chart` (the form of the demo data).

### 3.7 Directory

Read: all staff. Create, change and delete: MOA only.

| Method and path | Body | Response |
|---|---|---|
| `GET /api/departments` | — | `Department[]` |
| `POST /api/departments`, `PATCH /api/departments/{id}` | the fields of `Department` without `id` and `staffCount`; `identifier` is optional | `Department` |
| `DELETE /api/departments/{id}` | — | 204. 409 if the department has staff or locations. |
| `GET /api/locations?department=` | — | `Location[]` |
| `POST /api/locations`, `PATCH /api/locations/{id}` | the fields of `Location` without `id` and `inUse` | `Location` |
| `DELETE /api/locations/{id}` | — | 204. 409 if a visit used the location. |
| `GET /api/staff?role=&department=&q=&limit=200` | — | `Staff[]` |
| `POST /api/staff` | the fields of `Staff` without `id`, `key` and `departments`, plus `departmentId`, `roleCode`, `specialty?` | 201 `Staff` |
| `PATCH /api/staff/{id}` | `{ email?, phoneNumber?, active?, languages?, licenseNumber?, qualification?, designation?, certificationNumber?, desk?, phoneExtension? }` | `Staff` |
| `DELETE /api/staff/{id}` | — | 204. 409 if the staff member issued a message or works in a department. |
| `GET /api/medications?q=&limit=200` | — | `Medication[]` |
| `POST /api/medications`, `PATCH /api/medications/{id}` | the fields of `Medication` without `id` | `Medication` |
| `DELETE /api/medications/{id}` | — | 204. 409 if a prescription uses it. |

The backend makes the identifier of a new row when the body has none
(system `https://triad.example/fhir/sid/<organization|location|employee>`, a new value).

## 4. Journey values

These values come from the data. The frontend Demo guide and the backend journey test use them.

| Item | Value |
|---|---|
| ER Waiting, ER Bed 2, Cardiology Room 401 | Location identifiers `ER-WAIT`, `ER-BED-2`, `CARD-401` |
| Old Storage Room (delete step) | Location identifier `STORE-OLD` |
| Emergency department (409 step) | Department identifier `TRIAD-GH-EMER` |
| Metformin (Patient B) | RxNorm `860975` |
| Salbutamol inhaler | RxNorm `745752` (albuterol 0.09 MG/ACTUAT inhaler) |
| Furosemide | RxNorm `313988` (Furosemide 40 MG Oral Tablet) |
| Heart rate, blood pressure, oxygen saturation | LOINC `8867-4`, `85354-9`, `2708-6` |
| Chief complaint (intake note) | LOINC `8661-1` |
| Troponin | LOINC `89579-7` |
| Asthma attack, heart failure | SNOMED CT `195967001`, `84114007` |
