// The types of the API contract. This is a copy of doc/api.md, section 2.
// Do not change a type here. Change doc/api.md first, then copy the change.

export type Role = 'Patient' | 'Doctor' | 'Nurse' | 'MOA';
export type StaffRole = 'Doctor' | 'Nurse' | 'MOA';
export type Category = 'Diagnosis' | 'Procedure' | 'Allergy' | 'Observation' | 'LabOrder' | 'LabReport' | 'Prescription' | 'CareTeam';
export type Intent = 'Report' | 'Recommendation' | 'Decision';
export type Source = 'Human' | 'Agent';
export type Verification = 'Unconfirmed' | 'Provisional' | 'Differential' | 'Confirmed' | 'Refuted' | 'EnteredInError';
export type Channel = 'InPerson' | 'Phone' | 'Video' | 'Email' | 'Fax' | 'Transfer' | 'Chat' | 'App';
export type Origin = 'Patient' | 'Staff' | 'OtherClinic' | 'PharmaNet' | 'Lab' | 'Agent';
export type VisitClass = 'AMB' | 'EMER' | 'IMP' | 'HH' | 'VR';
export type ChatMode = 'rules' | 'fake' | 'llm';

export interface ApiError { code: 'no_user' | 'forbidden' | 'not_found' | 'conflict' | 'validation'; message: string; fields?: Record<string, string>; }
export interface Identifier { system: string; value: string; }
export interface Address { street: string | null; city: string | null; region: string | null; postalCode: string | null; country: string | null; }

// Users
export interface UserView {
  key: string; role: Role; name: string;
  detail: string;            // patient: "born 1971-05-14"; staff: the department names, for example "Emergency"
  pinned: boolean;           // true for a demo user (section 1.1)
  patientId: number | null; staffId: number | null;
}

// Patients
export interface Permissions {      // what the current user can do for this patient. The UI uses it to show buttons. The backend checks again.
  viewChart: boolean; chat: boolean; tell: boolean; editDemographics: boolean;
  checkIn: boolean; endVisit: boolean; moveLocation: boolean; manageCareTeam: boolean; viewAudit: boolean;
  recordIntents: Intent[];   // the intents that the user can record
}
export interface PatientSummary { id: number; name: string; dateOfBirth: string; sex: 'female' | 'male' | 'other' | 'unknown'; phoneNumber: string | null; openVisitId: number | null; }
export interface Patient extends PatientSummary { address: Address; identifiers: Identifier[]; permissions: Permissions; }

// Visits
export interface VisitLocation { locationId: number; name: string; department: string | null; startDate: string; endDate: string | null; }
export interface Visit {
  id: number; patientId: number; identifier: Identifier; class: VisitClass; type: string | null; reason: string | null;
  startDate: string; endDate: string | null; isOpen: boolean;
  department: string | null;  // the department of the latest location
  locations: VisitLocation[]; // oldest first
}

// Assertions
export interface Author {
  name: string;              // the staff name, or the patient name for a patient report
  role: Role;
  staffId: number | null;
  label: string;             // the short label of the 3MT slide: "Physician", "Nurse", "Front desk", "Other clinic", "Patient", "Agent"
}
export interface AssertionView {
  id: number; entryId: number; messageId: number; seq: number; visitId: number;
  category: Category; code: string; codeSystem: string; display: string;
  details: Record<string, string | number | null>; // the subtype columns in camelCase, for example { value, unit } or { medication, dosage, status }
  statement: string; intent: Intent; source: Source; verification: Verification; assertedAt: string;
  author: Author; channel: Channel; origin: Origin;
  supersedesId: number | null; supersededById: number | null; isCurrent: boolean;
  patientVisible: boolean;   // the patient-visible rule of USER_FLOWS.md section 2.1
}
export interface Chart { patientId: number; items: AssertionView[]; }   // newest first
export interface Chain { headId: number; items: AssertionView[]; }      // newest first; items[0] is the current one. A patient gets the head only.

// Care team
export interface CareTeamMember {
  system: string; value: string; role: string | null;
  staffId: number | null; name: string; staffRole: StaffRole | null; department: string | null;
}
export interface CareTeamVersion {
  entryId: number; assertionId: number; visitId: number; name: string | null; status: string;
  members: CareTeamMember[]; author: Author; assertedAt: string; isCurrent: boolean;
}
export interface CareTeam { visitId: number; current: CareTeamVersion | null; chain: CareTeamVersion[]; } // chain: newest first, the current version included

// Records (new messages and assertions)
export interface NewMessage {
  patientId: number;
  visitId?: number | null;   // the visit for new entries. Default: the open visit. See section 3.4.
  channel?: Channel;         // default: 'InPerson' for staff, 'App' for a patient
  text: string;              // the message text (the note)
  assertions: NewAssertion[];// one or more
}
export interface NewAssertion {
  entryId?: number;          // an assertion about an entry that exists (confirm, refute, a report on an item)
  newEntry?: NewEntry;       // or a new entry. Give exactly one of entryId and newEntry.
  supersedesId?: number | null; // must be the current assertion of its chain, else 409
  intent: Intent; verification: Verification; statement: string;
}
export interface NewEntry {
  category: Exclude<Category, 'CareTeam'>;
  code: string; codeSystem: string; display: string; text?: string | null;
  details: Record<string, string | number | null>; // see section 3.4
}
export interface RecordResult { messageId: number; assertions: AssertionView[]; }
export interface CodePreset { category: Category; code: string; codeSystem: string; display: string; details: Record<string, string | number | null>; }

// Chat
export interface Card { rank: number; assertion: AssertionView; supersedes: AssertionView[]; } // supersedes: oldest first; empty for a patient
export interface ChatTurn {
  id: number; seq: number; speaker: 'User' | 'Assistant'; text: string; createdAt: string;
  kind: 'ask' | 'tell' | null;  // null for a user turn
  cards: Card[];                // one card for each citation, by rank
  recordedIds: number[];        // a tell turn: the ids of the new unconfirmed assertions (they are also cards)
}
export interface ChatSessionSummary { id: number; identifier: string; startedAt: string; mode: ChatMode; turnCount: number; firstQuestion: string | null; }
export interface ChatSession { id: number; identifier: string; patientId: number; startedAt: string; mode: ChatMode; model: string | null; turns: ChatTurn[]; }
export interface TurnResult { userTurn: ChatTurn; assistantTurn: ChatTurn; }

// Audit
export interface AuditEvent {
  id: number; identifier: string; at: string;
  action: 'read' | 'create' | 'update' | 'delete' | 'ask' | 'tell'; outcome: 'Allowed' | 'Denied';
  actorRole: Role; actorKey: string; actorName: string | null; path: string; chatTurnId: number | null;
}

// Directory
export interface Department { id: number; identifier: Identifier; name: string; type: string | null; phoneNumber: string | null; email: string | null; address: Address; staffCount: number; }
export interface Location { id: number; identifier: Identifier; name: string; department: string | null; physicalType: string | null; phoneNumber: string | null; address: Address; inUse: boolean; }
export interface StaffDepartment { departmentId: number; name: string; roleCode: string; specialty: string | null; }
export interface Staff {
  id: number; key: string; identifier: Identifier; name: string; role: StaffRole;
  sex: string | null; email: string | null; phoneNumber: string | null; active: boolean;
  departments: StaffDepartment[]; languages: string[];
  licenseNumber: string | null; qualification: string | null;          // Doctor
  designation: 'RN' | 'LPN' | 'RPN' | 'NP' | null;                    // Nurse
  certificationNumber: string | null; desk: string | null; phoneExtension: string | null; // MOA
}
export interface Medication { id: number; code: string; codeSystem: string; name: string; form: string | null; manufacturer: string | null; }
