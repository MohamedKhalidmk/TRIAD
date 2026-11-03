// Display labels for the values of the API contract.

import type { Category, Channel, Intent, Role, Verification, VisitClass } from '../api/types';

export const ROLES: Role[] = ['Patient', 'Doctor', 'Nurse', 'MOA'];

export const ROLE_LABELS: Record<Role, string> = {
  Patient: 'Patient',
  Doctor: 'Doctor',
  Nurse: 'Nurse',
  MOA: 'MOA (front desk)',
};

/** The order of the groups in the chart. */
export const CATEGORY_ORDER: Category[] = [
  'Allergy',
  'Diagnosis',
  'Prescription',
  'Observation',
  'LabOrder',
  'LabReport',
  'Procedure',
  'CareTeam',
];

export const CATEGORY_LABELS: Record<Category, string> = {
  Diagnosis: 'Diagnosis',
  Procedure: 'Procedure',
  Allergy: 'Allergy',
  Observation: 'Observation',
  LabOrder: 'Lab order',
  LabReport: 'Lab result',
  Prescription: 'Prescription',
  CareTeam: 'Care team',
};

export const CATEGORY_GROUP_LABELS: Record<Category, string> = {
  Diagnosis: 'Diagnoses',
  Procedure: 'Procedures',
  Allergy: 'Allergies',
  Observation: 'Observations',
  LabOrder: 'Lab orders',
  LabReport: 'Lab results',
  Prescription: 'Prescriptions',
  CareTeam: 'Care teams',
};

export const INTENTS: Intent[] = ['Report', 'Recommendation', 'Decision'];

export const VERIFICATIONS: Verification[] = [
  'Unconfirmed',
  'Provisional',
  'Differential',
  'Confirmed',
  'Refuted',
  'EnteredInError',
];

export const VERIFICATION_LABELS: Record<Verification, string> = {
  Unconfirmed: 'Unconfirmed',
  Provisional: 'Provisional',
  Differential: 'Differential',
  Confirmed: 'Confirmed',
  Refuted: 'Refuted',
  EnteredInError: 'Entered in error',
};

export const CHANNEL_LABELS: Record<Channel, string> = {
  InPerson: 'In person',
  Phone: 'Phone',
  Video: 'Video',
  Email: 'Email',
  Fax: 'Fax',
  Transfer: 'Transfer',
  Chat: 'Chat',
  App: 'App',
};

/** The channels that a staff user can select in the record form. */
export const STAFF_CHANNELS: Channel[] = ['InPerson', 'Phone', 'Video', 'Email', 'Fax', 'Transfer'];

export const VISIT_CLASSES: VisitClass[] = ['EMER', 'AMB', 'IMP', 'HH', 'VR'];

export const VISIT_CLASS_LABELS: Record<VisitClass, string> = {
  AMB: 'Ambulatory',
  EMER: 'Emergency',
  IMP: 'Inpatient',
  HH: 'Home health',
  VR: 'Virtual',
};

export const SEX_OPTIONS = ['female', 'male', 'other', 'unknown'] as const;

export function sexLabel(sex: string | null | undefined): string {
  if (!sex) return '';
  return sex.charAt(0).toUpperCase() + sex.slice(1);
}

/** The default verification for an intent in the record form. */
export function defaultVerification(intent: Intent): Verification {
  if (intent === 'Decision') return 'Confirmed';
  if (intent === 'Recommendation') return 'Provisional';
  return 'Unconfirmed';
}
