// The record form: one message with one or more assertions (POST /api/messages).
// Each row is a new entry, or an assertion about an item in the chart.
// The Supersede, Confirm, Refute and Report buttons of the chart open this form with a row,
// and the form shows a preview of the chain that the new assertion supersedes.
// To select an item of the chart, the form finds it on the server (GET /api/patients/{id}/chart?q=&limit=10).

import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { fieldError, isApiError } from '../api/client';
import { api, queryKeys } from '../api/endpoints';
import type { AssertionView, Channel, CodePreset, Intent, Medication, NewMessage, Patient, UserView } from '../api/types';
import { Dialog } from '../components/Dialog';
import { ErrorBanner, FieldList, FieldMessage } from '../components/ErrorView';
import { SelectField, TextAreaField, TextField } from '../components/Field';
import { formatCount } from '../components/Pager';
import { formatDate } from '../lib/dates';
import { CATEGORY_LABELS, CHANNEL_LABELS, STAFF_CHANNELS, VERIFICATION_LABELS, VERIFICATIONS } from '../lib/labels';
import { useDebounced } from '../lib/useDebounced';
import { keepPageOf } from '../lib/usePage';
import { detailSummary, pickIntent } from './assertionText';
import { ChainItem, ChainPages } from './ChainView';
import {
  ACTION_LABELS,
  applyPreset,
  DEFAULT_CODE_SYSTEM,
  defaultDetails,
  DETAIL_FIELDS,
  effectiveStatement,
  ENTRY_CATEGORIES,
  isEntryCategory,
  presetKey,
  RXNORM_SYSTEM,
  toDraft,
  toNewAssertion,
  validateRow,
  type EntryCategory,
  type RecordSeed,
  type RowDraft,
  type RowErrors,
} from './recordModel';

interface RecordFormProps {
  patient: Patient;
  user: UserView;
  seed: RecordSeed | null;
  onClose: () => void;
}

export function RecordFormDialog(props: RecordFormProps) {
  return (
    <Dialog
      open={props.seed !== null}
      title={props.seed?.title ?? 'Record'}
      subtitle={`${props.patient.name}, born ${formatDate(props.patient.dateOfBirth)}`}
      onClose={props.onClose}
      variant="drawer"
    >
      {props.seed && <RecordForm {...props} seed={props.seed} />}
    </Dialog>
  );
}

function RecordForm({ patient, user, seed, onClose }: RecordFormProps & { seed: RecordSeed }) {
  const queryClient = useQueryClient();
  const isPatient = user.role === 'Patient';
  const allowed = patient.permissions.recordIntents;
  const fallbackIntent = pickIntent(allowed, ['Decision', 'Recommendation', 'Report']);

  const [text, setText] = useState(seed.text ?? '');
  const [channel, setChannel] = useState<Channel>('InPerson');
  const [rows, setRows] = useState<RowDraft[]>(() => seed.rows.map((row) => toDraft(row, allowed, fallbackIntent)));
  const [localErrors, setLocalErrors] = useState<RowErrors>({});

  const codes = useQuery({
    queryKey: queryKeys.codes,
    queryFn: ({ signal }) => api.codes(undefined, signal),
    enabled: !isPatient,
    staleTime: Infinity,
  });

  // A row can ask for a preset by code (for example the intake note, LOINC 8661-1). Apply it when the presets load.
  useEffect(() => {
    if (!codes.data) return;
    setRows((current) =>
      current.map((row) => {
        if (!row.presetCode) return row;
        const preset = codes.data.find((item) => item.code === row.presetCode && item.category === row.category);
        if (!preset) return { ...row, presetCode: null };
        const applied = applyPreset(row, preset);
        // Keep a value that the user wrote before the presets loaded.
        const details: Record<string, string> = { ...applied.details };
        if (row.details.value?.trim()) details.value = row.details.value;
        return { ...applied, details };
      }),
    );
  }, [codes.data]);

  const formRef = useRef<HTMLFormElement>(null);

  // After a failed submit, move the focus to the first field with an error, or show the message at the top.
  const focusFirstProblem = () => {
    requestAnimationFrame(() => {
      const form = formRef.current;
      const invalid = form?.querySelector<HTMLElement>('[aria-invalid="true"]');
      if (invalid) invalid.focus();
      else form?.querySelector('.banner')?.scrollIntoView({ block: 'nearest' });
    });
  };

  const submit = useMutation({
    mutationFn: (body: NewMessage) => api.postMessage(body),
    onSuccess: () => {
      // The prefixes: all pages and searches of the chart, all chains, all pages of the visits and of the audit log.
      for (const key of [queryKeys.patientCharts(patient.id), queryKeys.chains, queryKeys.patient(patient.id), queryKeys.visits(patient.id), queryKeys.audit(patient.id)]) {
        queryClient.invalidateQueries({ queryKey: key });
      }
      onClose();
    },
    onError: () => focusFirstProblem(),
  });

  const updateRow = (key: string, change: Partial<RowDraft>) => {
    setRows((current) => current.map((row) => (row.key === key ? { ...row, ...change } : row)));
  };

  const addRow = () => {
    setRows((current) => [...current, toDraft({ kind: isPatient ? 'existing' : 'new' }, allowed, fallbackIntent)]);
  };

  const removeRow = (key: string) => setRows((current) => current.filter((row) => row.key !== key));

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const errors: RowErrors = {};
    rows.forEach((row, index) => Object.assign(errors, validateRow(row, index, allowed)));
    if (rows.length === 0) errors.assertions = 'Add at least one assertion.';
    setLocalErrors(errors);
    if (Object.keys(errors).length > 0) {
      focusFirstProblem();
      return;
    }
    const statements = rows.map(effectiveStatement).join(' ');
    const body: NewMessage = {
      patientId: patient.id,
      text: text.trim() || statements,
      assertions: rows.map(toNewAssertion),
    };
    if (!isPatient) body.channel = channel;
    submit.mutate(body);
  };

  const errorFor = (...names: string[]) => {
    for (const name of names) if (localErrors[name]) return localErrors[name];
    return fieldError(submit.error, ...names);
  };

  const shownFieldNames = useMemo(() => {
    const names = ['text', 'channel', 'patientId', 'visitId'];
    rows.forEach((row, index) => {
      const at = `assertions.${index}`;
      names.push(`${at}.statement`, `${at}.intent`, `${at}.verification`, `${at}.entryId`, `${at}.supersedesId`);
      names.push(`${at}.newEntry.category`, `${at}.newEntry.code`, `${at}.newEntry.codeSystem`, `${at}.newEntry.display`);
      for (const field of DETAIL_FIELDS[row.category]) names.push(`${at}.newEntry.details.${field.name}`);
    });
    return names;
  }, [rows]);

  const needsVisit = !isPatient && patient.openVisitId === null && rows.some((row) => row.kind === 'new');
  const conflict = isApiError(submit.error) && submit.error.status === 409;

  return (
    <form className="record-form" onSubmit={onSubmit} noValidate ref={formRef}>
      <ErrorBanner error={submit.error} />
      {conflict && (
        <p className="muted">The chart changed after you opened this form. Close the form, then open it again from the chart.</p>
      )}
      <FieldList error={submit.error} shown={shownFieldNames} />
      {needsVisit && (
        <div className="banner banner-warn" role="status">
          This patient has no open visit. A new entry needs an open visit. An assertion about an item in the chart does
          not need one.
        </div>
      )}

      <fieldset className="fieldset">
        <legend>Message</legend>
        <div className={isPatient ? 'stack' : 'grid-message'}>
          {!isPatient && (
            <SelectField label="Channel" value={channel} onChange={(event) => setChannel(event.target.value as Channel)} error={errorFor('channel')}>
              {STAFF_CHANNELS.map((item) => (
                <option key={item} value={item}>
                  {CHANNEL_LABELS[item]}
                </option>
              ))}
            </SelectField>
          )}
          <TextAreaField
            label={isPatient ? 'Message to your care team' : 'Note'}
            value={text}
            onChange={(event) => setText(event.target.value)}
            rows={2}
            hint="If you leave it empty, the app uses the statements."
            error={errorFor('text')}
          />
        </div>
      </fieldset>

      {rows.map((row, index) => (
        <RowEditor
          key={row.key}
          row={row}
          index={index}
          count={rows.length}
          isPatient={isPatient}
          allowed={allowed}
          presets={codes.data ?? []}
          presetsLoading={codes.isPending && !isPatient}
          patientId={patient.id}
          errorFor={errorFor}
          onChange={(change) => updateRow(row.key, change)}
          onRemove={() => removeRow(row.key)}
        />
      ))}
      <FieldMessage message={localErrors.assertions} />

      <div className="form-actions form-actions-sticky">
        {!isPatient && (
          <button type="button" className="button" onClick={addRow}>
            Add another assertion
          </button>
        )}
        <span className="spacer" />
        <button type="button" className="button" onClick={onClose}>
          Cancel
        </button>
        <button type="submit" className="button button-primary" disabled={submit.isPending}>
          {submit.isPending ? 'Wait…' : rows.length > 1 ? `Record ${rows.length} assertions` : 'Record'}
        </button>
      </div>
    </form>
  );
}

interface RowEditorProps {
  row: RowDraft;
  index: number;
  count: number;
  isPatient: boolean;
  allowed: Intent[];
  presets: CodePreset[];
  presetsLoading: boolean;
  patientId: number;
  errorFor: (...names: string[]) => string | undefined;
  onChange: (change: Partial<RowDraft>) => void;
  onRemove: () => void;
}

function itemLabel(item: AssertionView): string {
  const statement = item.statement.length > 60 ? `${item.statement.slice(0, 57)}…` : item.statement;
  return `${CATEGORY_LABELS[item.category]}: ${item.display} — ${statement} (${item.author.label}, ${formatDate(item.assertedAt)})`;
}

function RowEditor({ row, index, count, isPatient, allowed, presets, presetsLoading, patientId, errorFor, onChange, onRemove }: RowEditorProps) {
  const at = `assertions.${index}`;
  const categoryPresets = presets.filter((preset) => preset.category === row.category);
  const selectedPreset = categoryPresets.find((preset) => preset.code === row.code && preset.codeSystem === row.codeSystem);

  const selectTarget = (target: AssertionView | null) => {
    const change: Partial<RowDraft> = { target };
    if (target && row.kind === 'new' && isEntryCategory(target.category) && target.category !== row.category) {
      change.category = target.category;
      change.codeSystem = DEFAULT_CODE_SYSTEM[target.category];
      change.code = '';
      change.display = '';
      change.details = defaultDetails(target.category);
    }
    onChange(change);
  };

  const selectCategory = (category: EntryCategory) => {
    onChange({ category, code: '', display: '', codeSystem: DEFAULT_CODE_SYSTEM[category], details: defaultDetails(category), presetCode: null });
  };

  const selectPreset = (key: string) => {
    const preset = categoryPresets.find((item) => presetKey(item) === key);
    if (preset) onChange(applyPreset(row, preset));
    else onChange({ code: '', display: '' });
  };

  const setDetail = (name: string, value: string) => onChange({ details: { ...row.details, [name]: value } });

  return (
    <fieldset className="fieldset record-row">
      <legend>
        Assertion {index + 1}
        {row.action && <span className="badge badge-neutral">{ACTION_LABELS[row.action]}</span>}
      </legend>
      {count > 1 && (
        <button type="button" className="link-button record-row-remove" onClick={onRemove}>
          Remove
        </button>
      )}

      {!isPatient && (
        <div className="segmented segmented-small" role="radiogroup" aria-label={`Assertion ${index + 1}: what it is about`}>
          <label className={row.kind === 'new' ? 'segment segment-selected' : 'segment'}>
            <input type="radio" name={`${row.key}-kind`} checked={row.kind === 'new'} onChange={() => onChange({ kind: 'new' })} />
            A new entry
          </label>
          <label className={row.kind === 'existing' ? 'segment segment-selected' : 'segment'}>
            <input type="radio" name={`${row.key}-kind`} checked={row.kind === 'existing'} onChange={() => onChange({ kind: 'existing' })} />
            An item in the chart
          </label>
        </div>
      )}

      {isPatient && row.target ? (
        <div className="target-card">
          <span className="eyebrow">About this item</span>
          <ChainItem item={row.target} struck={false} />
        </div>
      ) : (
        <ItemFinder
          patientId={patientId}
          kind={row.kind}
          target={row.target}
          error={errorFor(`${at}.entryId`, `${at}.supersedesId`)}
          onSelect={selectTarget}
        />
      )}

      {row.kind === 'new' && (
        <div className="grid-2">
          <SelectField label="Category" value={row.category} onChange={(event) => selectCategory(event.target.value as EntryCategory)} error={errorFor(`${at}.newEntry.category`)}>
            {ENTRY_CATEGORIES.map((category) => (
              <option key={category} value={category}>
                {CATEGORY_LABELS[category]}
              </option>
            ))}
          </SelectField>
          <SelectField
            label="Preset code"
            value={selectedPreset ? presetKey(selectedPreset) : ''}
            onChange={(event) => selectPreset(event.target.value)}
            hint={presetsLoading ? 'Wait. The app gets the presets.' : categoryPresets.length === 0 ? 'No preset for this category.' : undefined}
          >
            <option value="">Other code (write it below)</option>
            {categoryPresets.map((preset) => (
              <option key={presetKey(preset)} value={presetKey(preset)}>
                {preset.display} ({preset.code})
              </option>
            ))}
          </SelectField>
          <TextField label="Display name" value={row.display} onChange={(event) => onChange({ display: event.target.value })} error={errorFor(`${at}.newEntry.display`)} className="span-2" />
          <TextField label="Code" value={row.code} onChange={(event) => onChange({ code: event.target.value })} error={errorFor(`${at}.newEntry.code`)} />
          <TextField label="Code system" value={row.codeSystem} onChange={(event) => onChange({ codeSystem: event.target.value })} error={errorFor(`${at}.newEntry.codeSystem`)} />
          {row.category === 'Prescription' && (
            <MedicationFinder
              onPick={(medication) =>
                onChange({
                  code: medication.code,
                  codeSystem: medication.codeSystem,
                  display: medication.name,
                  details: {
                    ...row.details,
                    medicationCode: medication.code,
                    medicationSystem: medication.codeSystem,
                    medicationName: medication.name,
                  },
                })
              }
            />
          )}
          {DETAIL_FIELDS[row.category].map((field) => {
            const id = `${row.key}-${field.name}`;
            const error = errorFor(`${at}.newEntry.details.${field.name}`, `${at}.details.${field.name}`);
            const label = `${field.label}${field.required ? '' : ' (optional)'}`;
            if (field.type === 'select') {
              return (
                <SelectField key={id} label={label} value={row.details[field.name] ?? ''} onChange={(event) => setDetail(field.name, event.target.value)} error={error} hint={field.hint}>
                  {field.options?.map((option) => (
                    <option key={option} value={option}>
                      {option === '' ? 'Not known' : option}
                    </option>
                  ))}
                </SelectField>
              );
            }
            return (
              <div key={id} className="field-with-list">
                <TextField
                  label={label}
                  type={field.type === 'date' ? 'date' : 'text'}
                  value={row.details[field.name] ?? ''}
                  onChange={(event) => setDetail(field.name, event.target.value)}
                  error={error}
                  hint={row.action === 'intake' && field.name === 'value' ? 'If you leave it empty, the app uses the statement.' : field.hint}
                  list={field.suggestions ? `${id}-list` : undefined}
                />
                {field.suggestions && (
                  <datalist id={`${id}-list`}>
                    {field.suggestions.map((option) => (
                      <option key={option} value={option} />
                    ))}
                  </datalist>
                )}
              </div>
            );
          })}
        </div>
      )}

      {isPatient ? (
        <p className="muted small">The app sends this report to your care team. It stays unconfirmed until a staff member checks it.</p>
      ) : (
        <div className="grid-2">
          <SelectField
            label="Intent"
            value={row.intent}
            onChange={(event) => onChange({ intent: event.target.value as Intent })}
            error={errorFor(`${at}.intent`)}
            disabled={allowed.length <= 1}
          >
            {allowed.map((intent) => (
              <option key={intent} value={intent}>
                {intent}
              </option>
            ))}
          </SelectField>
          <SelectField
            label="Verification"
            value={row.verification}
            onChange={(event) => onChange({ verification: event.target.value as RowDraft['verification'] })}
            error={errorFor(`${at}.verification`)}
          >
            {VERIFICATIONS.map((verification) => (
              <option key={verification} value={verification}>
                {VERIFICATION_LABELS[verification]}
              </option>
            ))}
          </SelectField>
        </div>
      )}
      <TextAreaField
        label={isPatient ? 'Your report' : row.action === 'vitals' ? 'Statement (optional)' : 'Statement'}
        value={row.statement}
        onChange={(event) => onChange({ statement: event.target.value })}
        rows={2}
        placeholder={isPatient ? 'For example: I stopped taking metformin.' : row.action === 'vitals' ? effectiveStatement({ ...row, statement: '' }) || 'For example: Heart rate: 112 /min.' : 'For example: Possible heart failure.'}
        hint={row.action === 'vitals' ? 'If you leave it empty, the app writes it from the value.' : undefined}
        error={errorFor(`${at}.statement`)}
      />

      {row.target && !isPatient && <ChainPreview row={row} />}
    </fieldset>
  );
}

/** Shows the chain that the new assertion will supersede. */
function ChainPreview({ row }: { row: RowDraft }) {
  const summary = row.kind === 'existing' && row.target ? row.target.display : row.display || 'the new entry';
  return (
    <div className="chain-preview" aria-label="Chain preview">
      <span className="eyebrow">Chain preview</span>
      <div className="chain-item chain-item-new">
        <div className="chain-item-head">
          <strong>New</strong> <span className="muted">· {row.intent} · {VERIFICATION_LABELS[row.verification]}</span>
        </div>
        <div className="chain-item-body">
          {summary}
          {row.kind === 'new' && detailSummary({ category: row.category, details: row.details }) ? ` (${detailSummary({ category: row.category, details: row.details })})` : ''} — {row.statement || <span className="muted">your statement</span>}
        </div>
      </div>
      <span className="chain-arrow" aria-hidden="true">
        ↓ supersedes
      </span>
      {row.target && <ChainPages assertionId={row.target.id} strikeAll inline />}
    </div>
  );
}

const ITEM_RESULTS = 10;

/**
 * Finds the current item of the chart that a row is about, or that a new entry supersedes
 * (GET /api/patients/{id}/chart?q=&limit=10). Each chart read writes an audit record,
 * so the search waits 300 ms after the last key and needs 3 or more letters.
 */
function ItemFinder({
  patientId,
  kind,
  target,
  error,
  onSelect,
}: {
  patientId: number;
  kind: RowDraft['kind'];
  target: AssertionView | null;
  error?: string;
  onSelect: (item: AssertionView | null) => void;
}) {
  const [query, setQuery] = useState('');
  const q = useDebounced(query.trim(), 300);
  const params = { q, limit: ITEM_RESULTS };
  const found = useQuery({
    queryKey: queryKeys.chart(patientId, params),
    queryFn: ({ signal }) => api.chart(patientId, params, signal),
    enabled: target === null && q.length >= 3,
    placeholderData: keepPageOf(queryKeys.patientCharts(patientId)),
  });

  if (target) {
    return (
      <div className="target-card">
        <span className="eyebrow">{kind === 'existing' ? 'About this item' : 'Supersedes this item'}</span>
        <div>{itemLabel(target)}</div>
        <FieldMessage message={error} />
        <div className="row">
          <button type="button" className="button button-small" onClick={() => onSelect(null)}>
            {kind === 'existing' ? 'Change the item' : 'Do not supersede it'}
          </button>
        </div>
      </div>
    );
  }

  const results = (found.data?.items ?? []).filter((item) => item.isCurrent && isEntryCategory(item.category));
  const more = (found.data?.total ?? 0) > ITEM_RESULTS;
  return (
    <div className="medication-finder">
      <TextField
        label={kind === 'existing' ? 'Find the item in the chart' : 'Supersedes (optional): find the item in the chart'}
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        error={error}
        hint={
          kind === 'existing'
            ? 'The new assertion is about this item. It supersedes the current assertion of the item. Write 3 or more letters.'
            : 'Select an item if the new entry replaces it (for example a revised diagnosis). Write 3 or more letters.'
        }
        autoComplete="off"
      />
      {q.length >= 3 &&
        (found.isError ? (
          <ErrorBanner error={found.error} />
        ) : found.data ? (
          <ul className="finder-results" aria-busy={found.isPlaceholderData || undefined}>
            {results.length === 0 && <li className="muted">No current item matches.</li>}
            {results.map((item) => (
              <li key={item.id}>
                <span>{itemLabel(item)}</span>
                <button
                  type="button"
                  className="button button-small"
                  onClick={() => {
                    onSelect(item);
                    setQuery('');
                  }}
                >
                  Select
                </button>
              </li>
            ))}
            {more && (
              <li className="muted small">
                The first {ITEM_RESULTS} of {formatCount(found.data.total)} items. Write more letters to find fewer items.
              </li>
            )}
          </ul>
        ) : null)}
    </div>
  );
}

/** Finds a medication in the directory and fills the medication fields (GET /api/medications?q=). */
function MedicationFinder({ onPick }: { onPick: (medication: Medication) => void }) {
  const [query, setQuery] = useState('');
  const q = useDebounced(query.trim(), 300);
  const page = { limit: 8, offset: 0 };
  const medications = useQuery({
    queryKey: queryKeys.medications(q, page),
    queryFn: ({ signal }) => api.medications({ q, ...page }, signal),
    enabled: q.length >= 3,
    placeholderData: keepPreviousData,
  });
  return (
    <div className="span-2 medication-finder">
      <TextField
        label="Find a medication (optional)"
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        hint={`Write 3 or more letters. The default code system is RxNorm (${RXNORM_SYSTEM}).`}
        autoComplete="off"
      />
      {q.length >= 3 && medications.data && (
        <ul className="finder-results">
          {medications.data.items.length === 0 && <li className="muted">No medication has this name.</li>}
          {medications.data.items.map((medication) => (
            <li key={medication.id}>
              <button
                type="button"
                className="link-button"
                onClick={() => {
                  onPick(medication);
                  setQuery('');
                }}
              >
                {medication.name} <span className="muted">({medication.code})</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
