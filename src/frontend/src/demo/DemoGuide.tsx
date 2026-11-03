// The Demo guide panel: the steps of the hospital-visit journey (USER_FLOWS.md section 3).
// "Act as <user>" sets the user and opens the page of the step.
// A patient page needs the patient id: the guide gets it from GET /api/users/{key} (patientId).

import { useEffect, useRef, useState } from 'react';
import { api } from '../api/endpoints';
import { ROUTES } from '../app/routes';
import { useActingUser } from '../app/session';
import { Dialog } from '../components/Dialog';
import { errorMessage } from '../components/ErrorView';
import guide from './steps.json';

interface DemoAct {
  user: string;
  page: string;
  patient?: string;
  tab?: string;
  search?: { q?: string; dob?: string };
  actions: string[];
}

interface DemoStep {
  id: number;
  title: string;
  acts: DemoAct[];
  expected: string[];
}

const USERS = guide.users as Record<string, string>;
const STEPS = guide.steps as DemoStep[];
const LAST_STEP = 'triad.demo.step';

function readLastStep(): string | null {
  try {
    return window.sessionStorage.getItem(LAST_STEP);
  } catch {
    return null;
  }
}

function roleWord(key: string): string {
  const role = key.slice(0, key.indexOf(':'));
  return role === 'MOA' ? 'MOA' : role;
}

function pageLabel(act: DemoAct): string {
  const tab = act.tab ? ` (${act.tab.replace('-', ' ')})` : '';
  if (act.page === ROUTES.patient.path && act.patient) return `${USERS[act.patient] ?? act.patient}: patient page${tab}`;
  return `${act.page}${tab}`;
}

async function pathOf(act: DemoAct): Promise<string> {
  const params = new URLSearchParams();
  if (act.tab) params.set('tab', act.tab);
  if (act.search?.q) params.set('q', act.search.q);
  if (act.search?.dob) params.set('dob', act.search.dob);
  let path = act.page;
  if (path.includes(':id')) {
    if (!act.patient) throw new Error('The step has no patient.');
    const patient = await api.user(act.patient);
    if (patient.patientId === null) throw new Error(`The user ${act.patient} has no patient record.`);
    path = path.replace(':id', String(patient.patientId));
  }
  const search = params.toString();
  return search ? `${path}?${search}` : path;
}

export function DemoGuide({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { switchUser, userKey } = useActingUser();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<{ act: string; message: string } | null>(null);
  const [lastAct, setLastAct] = useState<string | null>(readLastStep);
  const listRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    if (!open || !lastAct) return;
    const element = listRef.current?.querySelector(`[data-act="${lastAct}"]`);
    element?.scrollIntoView({ block: 'center' });
  }, [open, lastAct]);

  const actAs = async (act: DemoAct, actId: string) => {
    setBusy(actId);
    setError(null);
    try {
      const to = await pathOf(act);
      try {
        window.sessionStorage.setItem(LAST_STEP, actId);
      } catch {
        // The guide still works without the storage.
      }
      setLastAct(actId);
      onClose();
      switchUser(act.user, { to });
    } catch (caught) {
      setError({ act: actId, message: errorMessage(caught) });
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
      subtitle="The hospital-visit journey of USER_FLOWS.md, section 3. On each part of a step, select “Act as”. The app sets the user and opens the page."
    >
      <p className="muted small">
        Chat mode: if no API key is set, the app uses the fake LLM, and all steps work offline. To start again, run{' '}
        <code>./src/scripts/quickstart.sh --reset-db</code>.
      </p>
      <ol className="demo-steps" ref={listRef}>
        {STEPS.map((step) => (
          <li key={step.id} className="demo-step">
            <h3>
              <span className="demo-step-number">Step {step.id}</span> {step.title}
            </h3>
            {step.acts.map((act, index) => {
              const actId = `${step.id}.${index}`;
              const current = act.user === userKey;
              return (
                <div key={actId} className={lastAct === actId ? 'demo-act demo-act-last' : 'demo-act'} data-act={actId}>
                  <div className="demo-act-head">
                    <div>
                      <div className="demo-user">
                        {USERS[act.user] ?? act.user} <span className="muted">({roleWord(act.user)})</span>
                      </div>
                      <div className="muted small">Page: {pageLabel(act)}</div>
                    </div>
                    <button
                      type="button"
                      className={current ? 'button button-small' : 'button button-small button-primary'}
                      onClick={() => void actAs(act, actId)}
                      disabled={busy !== null}
                    >
                      {busy === actId ? 'Wait…' : `Act as ${(USERS[act.user] ?? act.user).replace(/ \(Patient [AB]\)$/, '')}`}
                    </button>
                  </div>
                  <ol className="demo-actions">
                    {act.actions.map((action) => (
                      <li key={action}>{action}</li>
                    ))}
                  </ol>
                  {error?.act === actId && (
                    <div className="banner banner-error" role="alert">
                      {error.message}
                    </div>
                  )}
                </div>
              );
            })}
            <div className="demo-expected">
              <span className="eyebrow">Expected result</span>
              <ul>
                {step.expected.map((item) => (
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
