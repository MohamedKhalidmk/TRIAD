// The Chart tab (staff) and "My record" (patient): the current items, grouped by category.
// GET /api/patients/{id}/chart. "Show history" (staff) adds the superseded assertions (history=true).
// The server finds the text (q), filters the category and sends one page. The chips show the counts of the server.
// Each chart read writes an audit record, so the search waits 300 ms after the last key.

import { useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, queryKeys, type ChartParams } from '../api/endpoints';
import type { AssertionView, Category, Patient, UserView } from '../api/types';
import { Badge, IntentBadge, SourceBadge, VerificationBadge } from '../components/Badges';
import { EmptyState, ErrorPanel, Loading } from '../components/ErrorView';
import { formatCount, Pager } from '../components/Pager';
import { formatDateTime } from '../lib/dates';
import { CATEGORY_GROUP_LABELS, CATEGORY_ORDER } from '../lib/labels';
import { useDebounced } from '../lib/useDebounced';
import { keepPageOf, usePage } from '../lib/usePage';
import { detailSummary, pickIntent, supersededCount } from './assertionText';
import { ChainDialog } from './ChainView';
import { detailsFromItem, isEntryCategory, LOINC_SYSTEM, type RecordSeed } from './recordModel';

interface ChartTabProps {
  patient: Patient;
  user: UserView;
  onRecord: (seed: RecordSeed) => void;
}

/** One page of the chart. The previous page of the same patient stays on the screen while the next page loads. */
export function useChart(patientId: number, params: ChartParams, enabled = true) {
  return useQuery({
    queryKey: queryKeys.chart(patientId, params),
    queryFn: ({ signal }) => api.chart(patientId, params, signal),
    placeholderData: keepPageOf(queryKeys.patientCharts(patientId)),
    enabled,
  });
}

export function ChartTab({ patient, user, onRecord }: ChartTabProps) {
  const isPatient = user.role === 'Patient';
  const [history, setHistory] = useState(false);
  const [filter, setFilter] = useState('');
  const [category, setCategory] = useState<Category | 'all'>('all');
  const [chainOf, setChainOf] = useState<number | null>(null);
  const q = useDebounced(filter.trim(), 300);
  const withHistory = history && !isPatient;
  const page = usePage([patient.id, withHistory, q, category]);
  const listRef = useRef<HTMLDivElement>(null);
  const chart = useChart(patient.id, {
    history: withHistory || undefined,
    q: q || undefined,
    category: category === 'all' ? undefined : category,
    ...page.params,
  });
  const intents = patient.permissions.recordIntents;
  // No record buttons when the chart is not open to the user (for example the 403 panel of Use case 7).
  const canRecord = !isPatient && intents.length > 0 && patient.permissions.viewChart && !chart.isError;

  const items = useMemo(() => chart.data?.items ?? [], [chart.data]);
  const byId = useMemo(() => new Map(items.map((item) => [item.id, item])), [items]);
  // The counts of the server: the items of each category with the search, on all pages. "All" is their sum.
  const counts = chart.data?.counts ?? {};
  const countOf = (cat: Category) => counts[cat] ?? 0;
  const allCount = CATEGORY_ORDER.reduce((sum, cat) => sum + countOf(cat), 0);
  const filtered = q !== '' || category !== 'all';
  // The groups of this page. The server sends the items in the category order, so a group can go on to the next page.
  const groups = CATEGORY_ORDER.map((cat) => ({ category: cat, items: items.filter((item) => item.category === cat) })).filter(
    (group) => group.items.length > 0,
  );

  const staffIntent = pickIntent(intents, ['Decision', 'Recommendation', 'Report']);

  const actions: ItemActions = {
    openChain: (item) => setChainOf(item.id),
    supersede: (item) =>
      onRecord({
        title: 'Supersede an item',
        rows: [
          {
            kind: 'new',
            action: 'supersede',
            target: item,
            category: isEntryCategory(item.category) ? item.category : 'Diagnosis',
            // Start from the values of the item. Select a preset to change the code (for example asthma to heart failure).
            code: item.code,
            codeSystem: item.codeSystem,
            display: item.display,
            details: detailsFromItem(item),
            intent: staffIntent,
          },
        ],
      }),
    confirm: (item) =>
      onRecord({
        title: 'Confirm an item',
        rows: [
          {
            kind: 'existing',
            action: 'confirm',
            target: item,
            intent: staffIntent,
            verification: 'Confirmed',
            statement: `Confirmed: ${item.statement}`,
          },
        ],
      }),
    refute: (item) =>
      onRecord({
        title: 'Refute an item',
        rows: [
          {
            kind: 'existing',
            action: 'refute',
            target: item,
            intent: staffIntent,
            verification: 'Refuted',
            statement: `Refuted: ${item.statement}`,
          },
        ],
      }),
    report: (item) =>
      onRecord({
        title: 'Report a change',
        text: `Report about ${item.display}.`,
        rows: [{ kind: 'existing', action: 'report', target: item, intent: 'Report', verification: 'Unconfirmed', statement: '' }],
      }),
  };

  const recordVitals = () =>
    onRecord({
      title: 'Record vital signs',
      rows: [
        { code: '8867-4', display: 'Heart rate', unit: '/min' },
        { code: '85354-9', display: 'Blood pressure', unit: 'mm[Hg]' },
        { code: '2708-6', display: 'Oxygen saturation', unit: '%' },
      ].map((vital) => ({
        kind: 'new' as const,
        action: 'vitals' as const,
        category: 'Observation' as const,
        presetCode: vital.code,
        code: vital.code,
        codeSystem: LOINC_SYSTEM,
        display: vital.display,
        details: { unit: vital.unit },
        intent: pickIntent(intents, ['Report']),
        verification: 'Confirmed' as const,
        statement: '',
      })),
    });

  return (
    <div className="chart">
      <div className="toolbar">
        <div className="toolbar-title">
          <h2>{isPatient ? 'My record' : 'Chart'}</h2>
          <p className="muted">
            {isPatient
              ? 'The current items that you can see. To tell your care team about a change, select Report on an item.'
              : history
                ? 'All assertions, newest first. The superseded assertions have a line through them.'
                : 'The current items, newest first. Each item has one current assertion.'}
          </p>
        </div>
        <div className="toolbar-actions">
          {!isPatient && !chart.isError && (
            <label className="switch">
              <input type="checkbox" checked={history} onChange={(event) => setHistory(event.target.checked)} />
              Show history
            </label>
          )}
          {canRecord && (
            <>
              <button type="button" className="button" onClick={recordVitals}>
                Record vital signs
              </button>
              <button
                type="button"
                className="button button-primary"
                onClick={() => onRecord({ title: 'Record', rows: [{ kind: 'new', intent: staffIntent }] })}
              >
                Record
              </button>
            </>
          )}
        </div>
      </div>

      {chart.isPending ? (
        <Loading label="Wait. The app gets the chart." />
      ) : chart.isError ? (
        <ErrorPanel error={chart.error} onRetry={() => chart.refetch()} />
      ) : (
        <>
          {(filtered || filter !== '' || allCount > 0) && (
            <div className="filter-bar">
              <div className="field field-inline">
                <label htmlFor="chart-filter">Find in the chart</label>
                <input
                  id="chart-filter"
                  type="search"
                  value={filter}
                  onChange={(event) => setFilter(event.target.value)}
                  placeholder="For example metformin"
                  autoComplete="off"
                />
              </div>
              <div className="chips" role="group" aria-label="Category">
                <button type="button" className={category === 'all' ? 'chip chip-selected' : 'chip'} aria-pressed={category === 'all'} onClick={() => setCategory('all')}>
                  All ({formatCount(allCount)})
                </button>
                {CATEGORY_ORDER.filter((cat) => countOf(cat) > 0 || cat === category).map((cat) => (
                  <button
                    key={cat}
                    type="button"
                    className={category === cat ? 'chip chip-selected' : 'chip'}
                    aria-pressed={category === cat}
                    onClick={() => setCategory(cat)}
                  >
                    {CATEGORY_GROUP_LABELS[cat]} ({formatCount(countOf(cat))})
                  </button>
                ))}
              </div>
            </div>
          )}
          {groups.length === 0 ? (
            <EmptyState>{!filtered ? (isPatient ? 'Your record has no visible items now.' : 'The chart has no items.') : 'No item matches the filter.'}</EmptyState>
          ) : (
            <div ref={listRef} className={chart.isPlaceholderData ? 'stack paged-busy' : 'stack'}>
              {groups.map((group) => (
                <ChartGroup
                  key={group.category}
                  category={group.category}
                  items={group.items}
                  total={countOf(group.category)}
                  byId={byId}
                  history={withHistory}
                  isPatient={isPatient}
                  canAct={canRecord}
                  actions={actions}
                />
              ))}
            </div>
          )}
          <Pager page={chart.data} state={page} label="the chart" busy={chart.isPlaceholderData} scrollTo={listRef} />
        </>
      )}
      <ChainDialog assertionId={chainOf} onClose={() => setChainOf(null)} />
    </div>
  );
}

interface ItemActions {
  openChain: (item: AssertionView) => void;
  supersede: (item: AssertionView) => void;
  confirm: (item: AssertionView) => void;
  refute: (item: AssertionView) => void;
  report: (item: AssertionView) => void;
}

interface ChartGroupProps {
  category: Category;
  /** The items of the group on this page. */
  items: AssertionView[];
  /** The items of the category on all pages. */
  total: number;
  byId: Map<number, AssertionView>;
  history: boolean;
  isPatient: boolean;
  canAct: boolean;
  actions: ItemActions;
}

function ChartGroup({ category, items, total, byId, history, isPatient, canAct, actions }: ChartGroupProps) {
  const headingId = `chart-group-${category}`;
  return (
    <section className="chart-group" aria-labelledby={headingId}>
      <h3 id={headingId}>
        {CATEGORY_GROUP_LABELS[category]} <span className="count">{formatCount(Math.max(total, items.length))}</span>
      </h3>
      <ul className="chart-items">
        {items.map((item) => (
          <ChartItem key={item.id} item={item} byId={byId} history={history} isPatient={isPatient} canAct={canAct} actions={actions} />
        ))}
      </ul>
    </section>
  );
}

interface ChartItemProps {
  item: AssertionView;
  byId: Map<number, AssertionView>;
  history: boolean;
  isPatient: boolean;
  canAct: boolean;
  actions: ItemActions;
}

function ChartItem({ item, byId, history, isPatient, canAct, actions }: ChartItemProps) {
  const summary = detailSummary(item);
  const superseded = !item.isCurrent;
  const count = history ? supersededCount(item, byId) : null;
  const editable = item.isCurrent && isEntryCategory(item.category);
  return (
    <li className={superseded ? 'chart-item chart-item-old' : 'chart-item'}>
      <div className="chart-item-main">
        <div className="chart-item-title">
          {superseded ? <s>{item.display}</s> : <strong>{item.display}</strong>}
          {summary && <span className="chart-item-summary"> {summary}</span>}
        </div>
        <div className="chart-item-statement">{superseded ? <s>{item.statement}</s> : item.statement}</div>
        <div className="chart-item-meta">
          <strong>{item.author.label}</strong>
          <span> · {item.author.name}</span>
          <span> · {formatDateTime(item.assertedAt)}</span>
        </div>
        <div className="badges">
          <IntentBadge intent={item.intent} />
          <VerificationBadge verification={item.verification} />
          <SourceBadge source={item.source} />
          {superseded && <Badge tone="muted">Superseded</Badge>}
          {!isPatient && item.isCurrent && item.patientVisible && (
            <Badge tone="visible" title="The patient can see this item (USER_FLOWS.md section 2.1)">
              Patient can see
            </Badge>
          )}
          {!isPatient && item.supersedesId !== null && (
            <button type="button" className="link-button" onClick={() => actions.openChain(item)}>
              {count !== null && count > 0 ? `Supersedes ${count}` : 'Show the chain'}
            </button>
          )}
        </div>
      </div>
      {editable && (canAct || isPatient) && (
        <div className="chart-item-actions">
          {isPatient ? (
            <button type="button" className="button button-small" onClick={() => actions.report(item)}>
              Report
            </button>
          ) : (
            <>
              <button type="button" className="button button-small" onClick={() => actions.supersede(item)}>
                Supersede
              </button>
              <button type="button" className="button button-small" onClick={() => actions.confirm(item)}>
                Confirm
              </button>
              <button type="button" className="button button-small" onClick={() => actions.refute(item)}>
                Refute
              </button>
            </>
          )}
        </div>
      )}
    </li>
  );
}
