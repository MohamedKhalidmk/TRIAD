// The data model of the record form: the rows, the detail fields of each category,
// and the conversion of the rows to the request body (NewMessage, doc/api.md section 3.4).

import type { AssertionView, Category, CodePreset, Intent, NewAssertion, NewEntry, Verification } from '../api/types';
import { isoDatePart } from '../lib/dates';

export type EntryCategory = NewEntry['category'];

export const ENTRY_CATEGORIES: EntryCategory[] = [
  'Diagnosis',
  'Observation',
  'Prescription',
  'Allergy',
  'LabOrder',
  'LabReport',
  'Procedure',
];

export function isEntryCategory(category: Category): category is EntryCategory {
  return category !== 'CareTeam';
}

export type RowAction = 'supersede' | 'confirm' | 'refute' | 'report' | 'intake' | 'vitals' | null;

/** How a screen starts the record form. */
export interface RowSeed {
  kind: 'new' | 'existing';
  action?: RowAction;
  /** The current item that the row is about (existing) or that the new entry supersedes (new). */
  target?: AssertionView | null;
  category?: EntryCategory;
  /** When the code presets load, the row takes the preset with this code. */
  presetCode?: string;
  code?: string;
  codeSystem?: string;
  display?: string;
  details?: Record<string, string>;
  intent?: Intent;
  verification?: Verification;
  statement?: string;
}

export interface RecordSeed {
  title: string;
  text?: string;
  rows: RowSeed[];
}

export interface RowDraft {
  key: string;
  kind: 'new' | 'existing';
  action: RowAction;
  target: AssertionView | null;
  category: EntryCategory;
  presetCode: string | null;
  code: string;
  codeSystem: string;
  display: string;
  details: Record<string, string>;
  intent: Intent;
  verification: Verification;
  statement: string;
}

// ----- Detail fields of each category (doc/api.md section 3.4) -----

export interface DetailField {
  name: string;
  label: string;
  type: 'text' | 'date' | 'select';
  options?: string[];
  /** Suggestions for a text field. */
  suggestions?: string[];
  required?: boolean;
  hint?: string;
}

export const DETAIL_FIELDS: Record<EntryCategory, DetailField[]> = {
  Diagnosis: [
    { name: 'clinicalStatus', label: 'Clinical status', type: 'select', options: ['active', 'recurrence', 'relapse', 'inactive', 'remission', 'resolved'] },
    { name: 'onsetDate', label: 'Onset date', type: 'date', hint: 'If you leave it empty, the server uses the current time.' },
    { name: 'severity', label: 'Severity', type: 'text', suggestions: ['mild', 'moderate', 'severe'] },
  ],
  Procedure: [
    { name: 'performedDate', label: 'Date done', type: 'date', hint: 'If you leave it empty, the server uses the current time.' },
    { name: 'outcome', label: 'Outcome', type: 'text' },
  ],
  Allergy: [
    { name: 'substance', label: 'Substance', type: 'text', required: true },
    { name: 'type', label: 'Type', type: 'text', suggestions: ['allergy', 'intolerance'] },
    { name: 'allergyCategory', label: 'Allergy category', type: 'text', suggestions: ['food', 'medication', 'environment', 'biologic'] },
    { name: 'criticality', label: 'Criticality', type: 'text', suggestions: ['low', 'high', 'unable-to-assess'] },
    { name: 'clinicalStatus', label: 'Clinical status', type: 'select', options: ['', 'active', 'inactive', 'resolved'] },
  ],
  Observation: [
    { name: 'value', label: 'Value', type: 'text', required: true, hint: 'For example 112, or 128/82. For a chief complaint, write the complaint.' },
    { name: 'unit', label: 'Unit', type: 'text', suggestions: ['/min', 'mm[Hg]', '%', 'ng/L'] },
  ],
  LabOrder: [
    { name: 'testName', label: 'Test name', type: 'text', required: true },
    { name: 'priority', label: 'Priority', type: 'select', options: ['routine', 'urgent', 'asap', 'stat'], required: true },
    { name: 'specimen', label: 'Specimen', type: 'text', suggestions: ['blood', 'serum', 'urine'] },
  ],
  LabReport: [
    { name: 'issuedDate', label: 'Date issued', type: 'date', hint: 'If you leave it empty, the server uses the current time.' },
    { name: 'conclusion', label: 'Conclusion', type: 'text' },
  ],
  Prescription: [
    { name: 'medicationName', label: 'Medication name', type: 'text', required: true },
    { name: 'medicationCode', label: 'Medication code', type: 'text', required: true },
    { name: 'medicationSystem', label: 'Medication code system', type: 'text', required: true },
    { name: 'dosage', label: 'Dosage', type: 'text' },
    { name: 'frequency', label: 'Frequency', type: 'text' },
    { name: 'status', label: 'Status', type: 'select', options: ['active', 'draft', 'stopped', 'completed'], required: true },
  ],
};

export const RXNORM_SYSTEM = 'http://www.nlm.nih.gov/research/umls/rxnorm';
export const LOINC_SYSTEM = 'http://loinc.org';
export const SNOMED_SYSTEM = 'http://snomed.info/sct';

export const DEFAULT_CODE_SYSTEM: Record<EntryCategory, string> = {
  Diagnosis: SNOMED_SYSTEM,
  Procedure: SNOMED_SYSTEM,
  Allergy: SNOMED_SYSTEM,
  Observation: LOINC_SYSTEM,
  LabOrder: LOINC_SYSTEM,
  LabReport: LOINC_SYSTEM,
  Prescription: RXNORM_SYSTEM,
};

/** The default details of a new row: the first option of each select field. */
export function defaultDetails(category: EntryCategory): Record<string, string> {
  const details: Record<string, string> = {};
  for (const field of DETAIL_FIELDS[category]) {
    if (field.type === 'select' && field.options) details[field.name] = field.options[0];
  }
  if (category === 'Prescription') details.medicationSystem = RXNORM_SYSTEM;
  return details;
}

/**
 * The details of a current item, as the strings of the form. The Supersede button uses them,
 * so that a change of one value (for example the status of a prescription) is one edit.
 * In an AssertionView, a prescription has "medication" (the name); the form needs medicationName.
 */
export function detailsFromItem(item: AssertionView): Record<string, string> {
  if (!isEntryCategory(item.category)) return {};
  const source = item.details ?? {};
  const details: Record<string, string> = {};
  for (const field of DETAIL_FIELDS[item.category]) {
    const value = source[field.name];
    if (value === null || value === undefined || value === '') continue;
    details[field.name] = field.type === 'date' ? isoDatePart(String(value)) || String(value) : String(value);
  }
  if (item.category === 'Prescription') {
    details.medicationName = String(source.medicationName ?? source.medication ?? item.display);
    details.medicationCode = String(source.medicationCode ?? item.code);
    details.medicationSystem = String(source.medicationSystem ?? item.codeSystem);
  }
  return details;
}

export function presetKey(preset: Pick<CodePreset, 'codeSystem' | 'code'>): string {
  return `${preset.codeSystem}|${preset.code}`;
}

/** Applies a code preset to a row: the code, the display and the details of the preset. */
export function applyPreset(row: RowDraft, preset: CodePreset): RowDraft {
  const details = { ...defaultDetails(row.category) };
  for (const [name, value] of Object.entries(preset.details ?? {})) {
    if (value !== null && value !== undefined) details[name] = String(value);
  }
  return {
    ...row,
    presetCode: null,
    code: preset.code,
    codeSystem: preset.codeSystem,
    display: preset.display,
    details,
  };
}

// ----- Validation and the request body -----

export type RowErrors = Record<string, string>;

/**
 * The statement of a row. A vital sign with no statement gets one from its value,
 * for example "Heart rate: 112 /min.".
 */
export function effectiveStatement(row: RowDraft): string {
  const statement = row.statement.trim();
  if (statement || row.action !== 'vitals') return statement;
  const value = (row.details.value ?? '').trim();
  if (!value) return '';
  const unit = (row.details.unit ?? '').trim();
  return `${row.display.trim() || 'Vital sign'}: ${value}${unit ? ` ${unit}` : ''}.`;
}

/** Checks a row before the request. The keys are the field paths of the request body. */
export function validateRow(row: RowDraft, index: number, allowed: Intent[]): RowErrors {
  const errors: RowErrors = {};
  const at = `assertions.${index}`;
  if (!effectiveStatement(row)) errors[`${at}.statement`] = 'Write the statement.';
  if (!allowed.includes(row.intent)) errors[`${at}.intent`] = 'You cannot record this intent.';
  if (row.kind === 'existing') {
    if (!row.target) errors[`${at}.entryId`] = 'Select the item.';
    return errors;
  }
  if (!row.code.trim()) errors[`${at}.newEntry.code`] = 'Write the code, or select a preset.';
  if (!row.codeSystem.trim()) errors[`${at}.newEntry.codeSystem`] = 'Write the code system.';
  if (!row.display.trim()) errors[`${at}.newEntry.display`] = 'Write the display name.';
  for (const field of DETAIL_FIELDS[row.category]) {
    if (field.required && !detailValue(row, field.name)) {
      errors[`${at}.newEntry.details.${field.name}`] = `Write the ${field.label.toLowerCase()}.`;
    }
  }
  return errors;
}

/** The value of a detail field. The value of an intake note (chief complaint) is the statement. */
function detailValue(row: RowDraft, name: string): string {
  const value = (row.details[name] ?? '').trim();
  if (!value && name === 'value' && row.category === 'Observation' && row.action === 'intake') return row.statement.trim();
  return value;
}

function cleanDetails(row: RowDraft): Record<string, string | number | null> {
  const details: Record<string, string | number | null> = {};
  for (const field of DETAIL_FIELDS[row.category]) {
    const value = detailValue(row, field.name);
    if (!value) continue;
    details[field.name] = field.name === 'value' && /^-?\d+(\.\d+)?$/.test(value) ? Number(value) : value;
  }
  return details;
}

export function toNewAssertion(row: RowDraft): NewAssertion {
  const base = { intent: row.intent, verification: row.verification, statement: effectiveStatement(row) };
  if (row.kind === 'existing' && row.target) {
    return { entryId: row.target.entryId, supersedesId: row.target.id, ...base };
  }
  return {
    newEntry: {
      category: row.category,
      code: row.code.trim(),
      codeSystem: row.codeSystem.trim(),
      display: row.display.trim(),
      details: cleanDetails(row),
    },
    supersedesId: row.target ? row.target.id : null,
    ...base,
  };
}

let rowCounter = 0;

export function newRowKey(): string {
  rowCounter += 1;
  return `row-${rowCounter}`;
}

export function toDraft(seed: RowSeed, allowed: Intent[], fallbackIntent: Intent): RowDraft {
  const targetCategory = seed.target && isEntryCategory(seed.target.category) ? seed.target.category : undefined;
  const category = seed.category ?? targetCategory ?? 'Observation';
  const intent = seed.intent && allowed.includes(seed.intent) ? seed.intent : fallbackIntent;
  return {
    key: newRowKey(),
    kind: seed.kind,
    action: seed.action ?? null,
    target: seed.target ?? null,
    category,
    presetCode: seed.presetCode ?? null,
    code: seed.code ?? '',
    codeSystem: seed.codeSystem ?? DEFAULT_CODE_SYSTEM[category],
    display: seed.display ?? '',
    details: { ...defaultDetails(category), ...(seed.details ?? {}) },
    intent,
    verification: seed.verification ?? (intent === 'Decision' ? 'Confirmed' : intent === 'Recommendation' ? 'Provisional' : 'Unconfirmed'),
    statement: seed.statement ?? '',
  };
}

export const ACTION_LABELS: Record<Exclude<RowAction, null>, string> = {
  supersede: 'Supersede',
  confirm: 'Confirm',
  refute: 'Refute',
  report: 'Report',
  intake: 'Intake note',
  vitals: 'Vital sign',
};
