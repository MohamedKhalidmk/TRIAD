// The top bar: the hospital name, the links of the role, the demo time, the Demo guide button
// and the acting-as bar (the user type and the user).

import { useQuery } from '@tanstack/react-query';
import { Link, useLocation } from 'react-router-dom';
import { api, queryKeys } from '../api/endpoints';
import type { Role } from '../api/types';
import { directoryPath, patientPath, patientsPath, ROUTES } from '../app/routes';
import { useActingUser } from '../app/session';
import { formatDateTime } from '../lib/dates';
import { ROLES, ROLE_LABELS } from '../lib/labels';
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

export function TopBar({ onOpenDemoGuide }: { onOpenDemoGuide: () => void }) {
  const { user, userKey, status, openPicker } = useActingUser();
  const navItems = useNavItems();
  const health = useQuery({
    queryKey: queryKeys.health,
    queryFn: ({ signal }) => api.health(signal),
    staleTime: 60_000,
    retry: false,
  });

  const roleValue: Role | '' = user?.role ?? '';

  return (
    <header className="topbar">
      <div className="topbar-inner">
        <Link to={ROUTES.home.path} className="brand" aria-label="TRIAD General Hospital, home page">
          <img src="/triad-icon.png" alt="" width="28" height="28" />
          <span className="brand-text">
            <span className="brand-name">TRIAD</span>
            <span className="brand-sub">General Hospital</span>
          </span>
        </Link>

        <nav className="topnav" aria-label="Main">
          {navItems.map((item) => (
            <Link key={item.label} to={item.to} className={item.active ? 'topnav-link topnav-active' : 'topnav-link'} aria-current={item.active ? 'page' : undefined}>
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="topbar-tools">
          {health.data ? (
            <span className="clock" title="The demo time of the server (TRIAD_NOW) and the chat mode">
              {formatDateTime(health.data.now)} · Chat: {health.data.mode}
            </span>
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
