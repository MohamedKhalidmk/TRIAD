// The Demo guide panel: the use cases of the hospital-visit journey (USER_FLOWS.md section 3).
// Each use case has one or more steps. Each step has one user and one page.
// "Act as <user>" on a step sets the user and opens the page of the step.
// A patient page needs the patient id: the guide gets it from GET /api/users/{key} (patientId).

import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, queryKeys } from '../api/endpoints';
import { ROUTES } from '../app/routes';
import { useActingUser } from '../app/session';
import { Dialog } from '../components/Dialog';
import { errorMessage } from '../components/ErrorView';
import { sparqlPageUrl } from './sparql_link.mjs';
import sparql from './sparql_queries.json';
import guide from './steps.json';

interface DemoStep {
  user: string;
  page: string;
  patient?: string;
  tab?: string;
  search?: { q?: string; dob?: string };
  actions: string[];
}

interface DemoUseCase {
  id: number;
  title: string;
  steps: DemoStep[];
  queries?: string[];
  expected: string[];
}

interface SparqlQuery {
  id: string;
  title: string;
  text: string;
}

const QUERIES = new Map((sparql.queries as SparqlQuery[]).map((query) => [query.id, query]));
const USERS = guide.users as Record<string, string>;
const USE_CASES = guide.useCases as DemoUseCase[];
// The id of a step is "<use case id>.<step index>", for example "1.0" for Step 1 of Use case 1.
// The storage keeps the id of the last step that you acted as.
const LAST_STEP = 'triad.demo.step';

function stepId(useCase: DemoUseCase, index: number): string {
  return `${useCase.id}.${index}`;
}

const STEP_IDS = new Set(USE_CASES.flatMap((useCase) => useCase.steps.map((_, index) => stepId(useCase, index))));

/** The last step from the storage. A value that is not a step of this guide gives null. */
function readLastStep(): string | null {
  try {
    const value = window.sessionStorage.getItem(LAST_STEP);
    return value !== null && STEP_IDS.has(value) ? value : null;
  } catch {
    return null;
  }
}

function roleWord(key: string): string {
  const role = key.slice(0, key.indexOf(':'));
  return role === 'MOA' ? 'MOA' : role;
}

function pageLabel(step: DemoStep): string {
  const tab = step.tab ? ` (${step.tab.replace('-', ' ')})` : '';
  if (step.page === ROUTES.patient.path && step.patient) return `${USERS[step.patient] ?? step.patient}: patient page${tab}`;
  return `${step.page}${tab}`;
}

async function pathOf(step: DemoStep): Promise<string> {
  const params = new URLSearchParams();
  if (step.tab) params.set('tab', step.tab);
  if (step.search?.q) params.set('q', step.search.q);
  if (step.search?.dob) params.set('dob', step.search.dob);
  let path = step.page;
  if (path.includes(':id')) {
    if (!step.patient) throw new Error('The step has no patient.');
    const patient = await api.user(step.patient);
    if (patient.patientId === null) throw new Error(`The user ${step.patient} has no patient record.`);
    path = path.replace(':id', String(patient.patientId));
  }
  const search = params.toString();
  return search ? `${path}?${search}` : path;
}

/**
 * The SPARQL queries of a use case (the file 03_select_queries.sparql). "Show the SPARQL" shows the text for each store.
 * "Run in Virtuoso" shows only for the store Virtuoso: it opens the SPARQL page with the query in the editor.
 */
function UseCaseQueries({ ids, sparqlUrl }: { ids: string[]; sparqlUrl: string | null }) {
  const [shown, setShown] = useState<string | null>(null);
  return (
    <div className="demo-queries">
      <span className="eyebrow">SPARQL of this use case</span>
      <ul>
        {ids.map((id) => {
          const query = QUERIES.get(id);
          if (!query) return null;
          return (
            <li key={id} className="demo-query">
              <div className="demo-query-links">
                <span>
                  <strong>{id}.</strong> {query.title}
                </span>
                {sparqlUrl && (
                  <a href={sparqlPageUrl(sparqlUrl, query.text)} target="_blank" rel="noreferrer">
                    Run in Virtuoso
                  </a>
                )}
                <button
                  type="button"
                  className="button button-small"
                  aria-expanded={shown === id}
                  onClick={() => setShown(shown === id ? null : id)}
                >
                  {shown === id ? 'Hide the SPARQL' : 'Show the SPARQL'}
                </button>
              </div>
              {shown === id && <pre>{query.text}</pre>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function DemoGuide({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { switchUser, userKey } = useActingUser();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<{ step: string; message: string } | null>(null);
  const [lastStep, setLastStep] = useState<string | null>(readLastStep);
  const listRef = useRef<HTMLOListElement>(null);
  const health = useQuery({ queryKey: queryKeys.health, queryFn: ({ signal }) => api.health(signal), staleTime: 60_000, retry: false });
  const sparqlUrl = health.data?.store === 'virtuoso' ? (health.data.sparqlUrl ?? null) : null;

  useEffect(() => {
    if (!open || !lastStep) return;
    const element = listRef.current?.querySelector(`[data-step="${lastStep}"]`);
    element?.scrollIntoView({ block: 'center' });
  }, [open, lastStep]);

  const actAs = async (step: DemoStep, id: string) => {
    setBusy(id);
    setError(null);
    try {
      const to = await pathOf(step);
      try {
        window.sessionStorage.setItem(LAST_STEP, id);
      } catch {
        // The guide still works without the storage.
      }
      setLastStep(id);
      onClose();
      switchUser(step.user, { to });
    } catch (caught) {
      setError({ step: id, message: errorMessage(caught) });
    } finally {
      setBusy(null);
    }
  };

  return (
    <Dialog
      open={open}
      title="Demo guide"
      onClose={onClose}
      variant="drawer"
      subtitle="The use cases of the hospital-visit journey (USER_FLOWS.md, section 3). On each step of a use case, select “Act as”. The app sets the user and opens the page."
    >
      <p className="muted small">
        Chat mode: if no API key is set, the app uses the fake LLM, and all use cases work offline. To start again, run{' '}
        <code>./src/scripts/quickstart.sh --reset-db</code>. To see the tables of the database (read-only), run{' '}
        <code>./src/scripts/dbview.sh</code> and open http://127.0.0.1:8001.
      </p>
      <ol className="demo-steps" ref={listRef}>
        {USE_CASES.map((useCase) => (
          <li key={useCase.id} className="demo-step">
            <h3>
              <span className="demo-step-number">Use case {useCase.id}</span> {useCase.title}
            </h3>
            {useCase.steps.map((step, index) => {
              const id = stepId(useCase, index);
              const current = step.user === userKey;
              return (
                <div key={id} className={lastStep === id ? 'demo-act demo-act-last' : 'demo-act'} data-step={id}>
                  <div className="demo-act-head">
                    <div>
                      <div className="demo-user">
                        <span className="demo-act-step">Step {index + 1}</span> {USERS[step.user] ?? step.user} <span className="muted">({roleWord(step.user)})</span>
                      </div>
                      <div className="muted small">Page: {pageLabel(step)}</div>
                    </div>
                    <button
                      type="button"
                      className={current ? 'button button-small' : 'button button-small button-primary'}
                      onClick={() => void actAs(step, id)}
                      disabled={busy !== null}
                    >
                      {busy === id ? 'Wait…' : `Act as ${(USERS[step.user] ?? step.user).replace(/ \(Patient [AB]\)$/, '')}`}
                    </button>
                  </div>
                  <ol className="demo-actions">
                    {step.actions.map((action) => (
                      <li key={action}>{action}</li>
                    ))}
                  </ol>
                  {error?.step === id && (
                    <div className="banner banner-error" role="alert">
                      {error.message}
                    </div>
                  )}
                </div>
              );
            })}
            {useCase.queries && useCase.queries.length > 0 && <UseCaseQueries ids={useCase.queries} sparqlUrl={sparqlUrl} />}
            <div className="demo-expected">
              <span className="eyebrow">Expected result</span>
              <ul>
                {useCase.expected.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          </li>
        ))}
      </ol>
    </Dialog>
  );
}
