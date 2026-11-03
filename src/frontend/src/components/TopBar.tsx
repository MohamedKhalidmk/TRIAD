// The top bar: the hospital name, the links of the role, the clock, the Demo guide button
// and the acting-as bar (the user type and the user).
// The clock: if GET /api/health gives clock "system", it shows the local time of the browser.
// If it gives "fixed" or no clock (an old backend), it shows the demo time of the server.
// The top bar writes its height to the CSS variable --topbar-height. The chat pane uses it (styles.css).

import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useLocation } from 'react-router-dom';
import { api, queryKeys, type Health } from '../api/endpoints';
import type { Role } from '../api/types';
import { directoryPath, patientPath, patientsPath, ROUTES } from '../app/routes';
import { useActingUser } from '../app/session';
import { formatDateTime, formatTime } from '../lib/dates';
import { ROLES, ROLE_LABELS } from '../lib/labels';
import { useScrollFade } from './Tabs';
import { initials } from './UserPicker';

interface NavItem {
  label: string;
  to: string;
  active: boolean;
}

function useNavItems(): NavItem[] {
  const { user } = useActingUser();
  const location = useLocation();
  const tab = new URLSearchParams(location.search).get('tab');
  if (!user) return [];
  const onPatients = location.pathname === ROUTES.patients.path;
  if (user.role === 'Patient') {
    if (user.patientId === null) return [];
    const to = patientPath(user.patientId);
    return [{ label: 'My record', to, active: location.pathname === to }];
  }
  const first =
    user.role === 'MOA'
      ? { label: 'Front desk', to: patientsPath('front-desk'), active: onPatients && tab !== 'find' }
      : { label: 'My patients', to: patientsPath('my-patients'), active: onPatients && tab !== 'find' };
  return [
    first,
    { label: 'Find a patient', to: patientsPath('find'), active: onPatients && tab === 'find' },
    { label: 'Directory', to: directoryPath(), active: location.pathname === ROUTES.directory.path },
  ];
}

const CLOCK_INTERVAL_MS = 30_000;

function pad2(value: number): string {
  return value < 10 ? `0${value}` : String(value);
}

/** The local time of the browser as "YYYY-MM-DDTHH:MM". It changes each 30 s while "enabled" is true. */
function useLocalTime(enabled: boolean): string {
  // new Date() is correct here: it is the clock of this computer, not a date-only string of the API.
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    if (!enabled) return;
    setNow(new Date());
    const timer = window.setInterval(() => setNow(new Date()), CLOCK_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [enabled]);
  return `${now.getFullYear()}-${pad2(now.getMonth() + 1)}-${pad2(now.getDate())}T${pad2(now.getHours())}:${pad2(now.getMinutes())}`;
}

/** The long form shows above 1180 px (in two lines up to 1300 px), the short form below (styles.css). */
function Clock({ health }: { health: Health }) {
  const system = health.clock === 'system';
  const localTime = useLocalTime(system);
  if (system) {
    return (
      <span className="clock" title="The local time of this computer">
        <span className="clock-long">
          <span>{formatDateTime(localTime)}</span>
          <span className="clock-mode">Chat: {health.mode}</span>
        </span>
        <span className="clock-short">{formatTime(localTime)}</span>
      </span>
    );
  }
  return (
    <span className="clock" title="The demo time of the server (TRIAD_NOW) and the chat mode">
      <span className="clock-long">
        <span>Demo time: {formatDateTime(health.now)}</span>
        <span className="clock-mode">Chat: {health.mode}</span>
      </span>
      <span className="clock-short">Demo {formatTime(health.now)}</span>
    </span>
  );
}

/** Keeps the CSS variable --topbar-height equal to the height of the top bar. The height changes with the width. */
function useTopBarHeight() {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const header = ref.current;
    if (!header) return;
    const root = document.documentElement;
    const update = () => root.style.setProperty('--topbar-height', `${Math.ceil(header.getBoundingClientRect().height)}px`);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(header);
    return () => {
      observer.disconnect();
      root.style.removeProperty('--topbar-height');
    };
  }, []);
  return ref;
}

export function TopBar({ onOpenDemoGuide }: { onOpenDemoGuide: () => void }) {
  const { user, userKey, status, openPicker } = useActingUser();
  const navItems = useNavItems();
  const headerRef = useTopBarHeight();
  const navRef = useRef<HTMLElement>(null);
  const navFade = useScrollFade(navRef, navItems.length);
  const health = useQuery({
    queryKey: queryKeys.health,
    queryFn: ({ signal }) => api.health(signal),
    staleTime: 60_000,
    retry: false,
  });

  const roleValue: Role | '' = user?.role ?? '';

  return (
    <header className="topbar" ref={headerRef}>
      <div className="topbar-inner">
        <Link to={ROUTES.home.path} className="brand" aria-label="TRIAD General Hospital, home page">
          <img src="/triad-icon.png" alt="" width="28" height="28" />
          <span className="brand-text">
            <span className="brand-name">TRIAD</span>
            <span className="brand-sub">General Hospital</span>
          </span>
        </Link>

        <nav className={`topnav${navFade}`} aria-label="Main" ref={navRef}>
          {navItems.map((item) => (
            <Link key={item.label} to={item.to} className={item.active ? 'topnav-link topnav-active' : 'topnav-link'} aria-current={item.active ? 'page' : undefined}>
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="topbar-tools">
          {health.data ? (
            <Clock health={health.data} />
          ) : health.isError ? (
            <span className="clock clock-offline" title="GET /api/health failed">
              Server offline
            </span>
          ) : null}
          <button type="button" className="button button-demo" onClick={onOpenDemoGuide}>
            Demo guide
          </button>
        </div>

        <div className="acting-as" aria-label="Current user">
          <label className="acting-as-type">
            <span className="acting-as-label">User type</span>
            <select
              value={roleValue}
              onChange={(event) => openPicker({ role: event.target.value as Role })}
              aria-label="User type"
            >
              {roleValue === '' && <option value="">Select</option>}
              {ROLES.map((role) => (
                <option key={role} value={role}>
                  {ROLE_LABELS[role]}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="acting-as-user"
            onClick={() => openPicker({ role: user?.role })}
            title={userKey ? `User key: ${userKey}` : undefined}
          >
            {user ? (
              <>
                <span className={`avatar avatar-${user.role.toLowerCase()}`} aria-hidden="true">
                  {initials(user.name)}
                </span>
                <span className="acting-as-text">
                  <span className="acting-as-name">{user.name}</span>
                  <span className="acting-as-detail">
                    {ROLE_LABELS[user.role]}
                    {user.detail ? ` · ${user.detail}` : ''}
                  </span>
                </span>
              </>
            ) : (
              <span className="acting-as-text">
                <span className="acting-as-name">{status === 'loading' ? 'Wait…' : 'Select a user'}</span>
                <span className="acting-as-detail">No login. This is a prototype.</span>
              </span>
            )}
            <span className="chevron" aria-hidden="true">
              ▾
            </span>
          </button>
        </div>
      </div>
    </header>
  );
}
