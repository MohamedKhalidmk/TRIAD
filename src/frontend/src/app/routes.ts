// The routes of the app. routes.json is the one source: the app and scripts/check-demo.mjs read it.

import routeTable from './routes.json';
import type { Role, UserView } from '../api/types';

export const ROUTES = routeTable;

export type PatientsTab = 'front-desk' | 'my-patients' | 'find';
export type PatientTab = 'chart' | 'visit' | 'care-team' | 'audit';
export type DirectoryTab = 'departments' | 'locations' | 'staff' | 'medications';

export function patientPath(id: number, tab?: PatientTab): string {
  const path = ROUTES.patient.path.replace(':id', String(id));
  return tab ? `${path}?tab=${tab}` : path;
}

export function patientsPath(tab?: PatientsTab): string {
  return tab ? `${ROUTES.patients.path}?tab=${tab}` : ROUTES.patients.path;
}

export function directoryPath(tab?: DirectoryTab): string {
  return tab ? `${ROUTES.directory.path}?tab=${tab}` : ROUTES.directory.path;
}

/** The home page of a user: a patient gets "My record", staff get the patient lists. */
export function homePath(user: Pick<UserView, 'role' | 'patientId'>): string {
  if (user.role === 'Patient') return user.patientId !== null ? patientPath(user.patientId) : ROUTES.home.path;
  if (user.role === 'MOA') return patientsPath('front-desk');
  return patientsPath('my-patients');
}

/** The role of a user key "<Role>:<identifier value>", or null. */
export function roleOfKey(key: string | null | undefined): Role | null {
  if (!key) return null;
  const role = key.slice(0, key.indexOf(':'));
  return role === 'Patient' || role === 'Doctor' || role === 'Nurse' || role === 'MOA' ? role : null;
}
