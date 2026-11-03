// One typed function for each endpoint of doc/api.md, section 3.
// The query keys of TanStack Query are here too, so that each screen uses the same keys.

import { apiRequest } from './client';
import type {
  Address,
  AuditEvent,
  CareTeam,
  Chain,
  Chart,
  ChatMode,
  ChatSession,
  ChatSessionSummary,
  CodePreset,
  Department,
  Identifier,
  Location,
  Medication,
  NewMessage,
  Patient,
  PatientSummary,
  RecordResult,
  Role,
  Staff,
  StaffRole,
  TurnResult,
  UserView,
  Visit,
  VisitClass,
} from './types';

// ----- Request bodies (doc/api.md, section 3) -----

export interface Health { status: 'ok'; schemaVersion: number; mode: ChatMode; now: string; }

export type PatientScope = 'all' | 'care-team' | 'open-visits';

export interface NewPatientBody {
  name: string;
  dateOfBirth: string;
  sex: Patient['sex'];
  phoneNumber?: string | null;
  address?: Address;
}

export interface PatientPatchBody {
  sex?: Patient['sex'];
  phoneNumber?: string | null;
  address?: Address;
}

export interface CheckInBody { class: VisitClass; reason?: string | null; type?: string | null; locationId: number; }

export interface CareTeamMemberInput { system: string; value: string; role?: string | null; }
export interface CareTeamBody { members: CareTeamMemberInput[]; name?: string | null; }

export interface TurnBody { clientTurnId: string; text: string; }

export type DepartmentBody = Omit<Department, 'id' | 'staffCount' | 'identifier'> & { identifier?: Identifier };
export type LocationBody = Omit<Location, 'id' | 'inUse' | 'identifier'> & { identifier?: Identifier };
export type StaffCreateBody = Omit<Staff, 'id' | 'key' | 'departments' | 'identifier'> & {
  identifier?: Identifier;
  departmentId: number;
  roleCode: string;
  specialty?: string | null;
};
export type StaffPatchBody = Partial<
  Pick<
    Staff,
    | 'email'
    | 'phoneNumber'
    | 'active'
    | 'languages'
    | 'licenseNumber'
    | 'qualification'
    | 'designation'
    | 'certificationNumber'
    | 'desk'
    | 'phoneExtension'
  >
>;
export type MedicationBody = Omit<Medication, 'id'>;

// ----- Endpoints -----

const enc = encodeURIComponent;

export const api = {
  // 3.1 System and users
  health: (signal?: AbortSignal) => apiRequest<Health>('/health', { signal, withUser: false }),
  users: (params: { role?: Role | ''; q?: string; limit?: number }, signal?: AbortSignal) =>
    apiRequest<UserView[]>('/users', { query: params, signal, withUser: false }),
  user: (key: string, signal?: AbortSignal) => apiRequest<UserView>(`/users/${enc(key)}`, { signal, withUser: false }),
  me: (signal?: AbortSignal) => apiRequest<UserView>('/me', { signal }),
  codes: (category?: string, signal?: AbortSignal) => apiRequest<CodePreset[]>('/codes', { query: { category }, signal }),

  // 3.2 Patients
  patients: (params: { q?: string; dob?: string; scope?: PatientScope; limit?: number }, signal?: AbortSignal) =>
    apiRequest<PatientSummary[]>('/patients', { query: params, signal }),
  createPatient: (body: NewPatientBody) => apiRequest<Patient>('/patients', { method: 'POST', body }),
  patient: (id: number, signal?: AbortSignal) => apiRequest<Patient>(`/patients/${id}`, { signal }),
  updatePatient: (id: number, body: PatientPatchBody) => apiRequest<Patient>(`/patients/${id}`, { method: 'PATCH', body }),
  deletePatient: (id: number) => apiRequest<void>(`/patients/${id}`, { method: 'DELETE' }),

  // 3.3 Visits and care team
  visits: (patientId: number, signal?: AbortSignal) => apiRequest<Visit[]>(`/patients/${patientId}/visits`, { signal }),
  checkIn: (patientId: number, body: CheckInBody) =>
    apiRequest<Visit>(`/patients/${patientId}/visits`, { method: 'POST', body }),
  moveLocation: (visitId: number, locationId: number) =>
    apiRequest<Visit>(`/visits/${visitId}/locations`, { method: 'POST', body: { locationId } }),
  endVisit: (visitId: number) => apiRequest<Visit>(`/visits/${visitId}/end`, { method: 'POST' }),
  careTeam: (visitId: number, signal?: AbortSignal) => apiRequest<CareTeam>(`/visits/${visitId}/care-team`, { signal }),
  setCareTeam: (visitId: number, body: CareTeamBody) =>
    apiRequest<CareTeam>(`/visits/${visitId}/care-team`, { method: 'PUT', body }),

  // 3.4 Chart, chains and records
  chart: (
    patientId: number,
    params: { visitId?: number; category?: string; history?: boolean },
    signal?: AbortSignal,
  ) => apiRequest<Chart>(`/patients/${patientId}/chart`, { query: params, signal }),
  chain: (assertionId: number, signal?: AbortSignal) => apiRequest<Chain>(`/assertions/${assertionId}/chain`, { signal }),
  postMessage: (body: NewMessage) => apiRequest<RecordResult>('/messages', { method: 'POST', body }),

  // 3.5 Care Assistant
  chatSessions: (patientId: number, signal?: AbortSignal) =>
    apiRequest<ChatSessionSummary[]>(`/patients/${patientId}/chat/sessions`, { signal }),
  createChatSession: (patientId: number) =>
    apiRequest<ChatSession>(`/patients/${patientId}/chat/sessions`, { method: 'POST' }),
  chatSession: (sessionId: number, signal?: AbortSignal) =>
    apiRequest<ChatSession>(`/chat/sessions/${sessionId}`, { signal }),
  postTurn: (sessionId: number, body: TurnBody) =>
    apiRequest<TurnResult>(`/chat/sessions/${sessionId}/turns`, { method: 'POST', body }),

  // 3.6 Audit
  audit: (patientId: number, signal?: AbortSignal) => apiRequest<AuditEvent[]>(`/patients/${patientId}/audit`, { signal }),

  // 3.7 Directory
  departments: (signal?: AbortSignal) => apiRequest<Department[]>('/departments', { signal }),
  createDepartment: (body: DepartmentBody) => apiRequest<Department>('/departments', { method: 'POST', body }),
  updateDepartment: (id: number, body: Partial<DepartmentBody>) =>
    apiRequest<Department>(`/departments/${id}`, { method: 'PATCH', body }),
  deleteDepartment: (id: number) => apiRequest<void>(`/departments/${id}`, { method: 'DELETE' }),

  locations: (params: { department?: string } = {}, signal?: AbortSignal) =>
    apiRequest<Location[]>('/locations', { query: params, signal }),
  createLocation: (body: LocationBody) => apiRequest<Location>('/locations', { method: 'POST', body }),
  updateLocation: (id: number, body: Partial<LocationBody>) =>
    apiRequest<Location>(`/locations/${id}`, { method: 'PATCH', body }),
  deleteLocation: (id: number) => apiRequest<void>(`/locations/${id}`, { method: 'DELETE' }),

  staff: (
    params: { role?: StaffRole | ''; department?: string; q?: string; limit?: number },
    signal?: AbortSignal,
  ) => apiRequest<Staff[]>('/staff', { query: params, signal }),
  createStaff: (body: StaffCreateBody) => apiRequest<Staff>('/staff', { method: 'POST', body }),
  updateStaff: (id: number, body: StaffPatchBody) => apiRequest<Staff>(`/staff/${id}`, { method: 'PATCH', body }),
  deleteStaff: (id: number) => apiRequest<void>(`/staff/${id}`, { method: 'DELETE' }),

  medications: (params: { q?: string; limit?: number }, signal?: AbortSignal) =>
    apiRequest<Medication[]>('/medications', { query: params, signal }),
  createMedication: (body: MedicationBody) => apiRequest<Medication>('/medications', { method: 'POST', body }),
  updateMedication: (id: number, body: Partial<MedicationBody>) =>
    apiRequest<Medication>(`/medications/${id}`, { method: 'PATCH', body }),
  deleteMedication: (id: number) => apiRequest<void>(`/medications/${id}`, { method: 'DELETE' }),
};

// ----- Query keys -----

export const queryKeys = {
  health: ['health'] as const,
  users: (role: string, q: string) => ['users', role, q] as const,
  user: (key: string) => ['user', key] as const,
  me: (key: string) => ['me', key] as const,
  codes: ['codes'] as const,
  patientLists: ['patients'] as const,
  patients: (scope: PatientScope, q: string, dob: string) => ['patients', scope, q, dob] as const,
  patient: (id: number) => ['patient', id] as const,
  visits: (patientId: number) => ['visits', patientId] as const,
  careTeams: ['careTeam'] as const,
  careTeam: (visitId: number) => ['careTeam', visitId] as const,
  charts: ['chart'] as const,
  chart: (patientId: number, history: boolean) => ['chart', patientId, history] as const,
  chains: ['chain'] as const,
  chain: (assertionId: number) => ['chain', assertionId] as const,
  chatSessions: (patientId: number) => ['chatSessions', patientId] as const,
  chatSession: (sessionId: number) => ['chatSession', sessionId] as const,
  audit: (patientId: number) => ['audit', patientId] as const,
  departments: ['departments'] as const,
  locations: ['locations'] as const,
  staffLists: ['staff'] as const,
  staff: (role: string, q: string) => ['staff', role, q] as const,
  medicationLists: ['medications'] as const,
  medications: (q: string) => ['medications', q] as const,
};
