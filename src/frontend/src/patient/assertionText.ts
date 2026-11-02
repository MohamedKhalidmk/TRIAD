// Pure helpers that make text from an assertion.

import type { AssertionView, Intent } from '../api/types';
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
