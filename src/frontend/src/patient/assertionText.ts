// Pure helpers that make text from an assertion.

import type { AssertionView, Intent, Role } from '../api/types';
import { formatYear } from '../lib/dates';

function text(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '';
  return String(value).trim();
}

/**
 * A short summary of the subtype values, for example "112 /min" or "40 mg · once a day · active".
 * A value that is the same as the display name does not show again.
 */
export function detailSummary(item: Pick<AssertionView, 'category' | 'details'> & { display?: string }): string {
  const d = item.details ?? {};
  const notDisplay = (value: string) => (value && value !== item.display ? value : '');
  switch (item.category) {
    case 'Observation':
      return notDisplay([text(d.value), text(d.unit)].filter(Boolean).join(' '));
    case 'Prescription':
      return [notDisplay(text(d.medication ?? d.medicationName)), text(d.dosage), text(d.frequency), text(d.status)]
        .filter(Boolean)
        .join(' · ');
    case 'Diagnosis':
      return [text(d.clinicalStatus), text(d.severity)].filter(Boolean).join(' · ');
    case 'Allergy':
      return [text(d.substance), text(d.criticality) && `criticality ${text(d.criticality)}`, text(d.clinicalStatus)]
        .filter(Boolean)
        .join(' · ');
    case 'LabOrder':
      return [text(d.testName), text(d.priority), text(d.specimen)].filter(Boolean).join(' · ');
    case 'LabReport':
      return text(d.conclusion);
    case 'Procedure':
      return text(d.outcome);
    case 'CareTeam':
      return [text(d.name), text(d.status)].filter(Boolean).join(' · ');
    default:
      return Object.values(d).map(text).filter(Boolean).join(' · ');
  }
}

/** The struck-through line of the 3MT slide: "Front desk, 2019: penicillin allergy". */
export function supersededLine(item: AssertionView): string {
  return `${item.author.label}, ${formatYear(item.assertedAt)}: ${item.statement}`;
}

/** Selects the first intent of the list that the user can record. */
export function pickIntent(allowed: Intent[], preferred: Intent[]): Intent {
  for (const intent of preferred) if (allowed.includes(intent)) return intent;
  return allowed[0] ?? 'Report';
}

/**
 * True if a staff user can supersede `item` (Supersede, Confirm or Refute) with an assertion of `intent`.
 * This is the rule of supersede_denial in src/backend/domain/access.py. The app uses it to show the buttons.
 * The backend checks the rule again on each write.
 */
export function canSupersede(role: Role, item: AssertionView, intent: Intent): boolean {
  // The supersede guard: only a doctor decision can supersede an item that the patient can see.
  if (item.patientVisible && !(role === 'Doctor' && intent === 'Decision')) return false;
  if (role === 'Doctor') return true;
  if (role === 'Nurse') return item.intent === 'Report' || item.intent === 'Recommendation';
  if (role === 'MOA') return item.category === 'CareTeam';
  return false;
}

/**
 * The number of earlier assertions that a current item supersedes, from the loaded items.
 * It gives null if the chain goes to an item that is not loaded (the chart has no history).
 */
export function supersededCount(item: AssertionView, byId: Map<number, AssertionView>): number | null {
  let count = 0;
  let next = item.supersedesId;
  const seen = new Set<number>([item.id]);
  while (next !== null) {
    const older = byId.get(next);
    if (!older || seen.has(older.id)) return null;
    seen.add(older.id);
    count += 1;
    next = older.supersedesId;
  }
  return count;
}
