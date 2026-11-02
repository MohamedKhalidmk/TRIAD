// The user picker: select a user type, then a user (USER_FLOWS.md section 1).
// The demo users show first. Patients show their date of birth. Staff show their department.

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, queryKeys } from '../api/endpoints';
import type { Role, UserView } from '../api/types';
import { useActingUser } from '../app/session';
import { ROLES, ROLE_LABELS } from '../lib/labels';
import { useDebounced } from '../lib/useDebounced';
import { Badge } from './Badges';
import { Dialog } from './Dialog';
import { ErrorBanner, Loading } from './ErrorView';

export function initials(name: string): string {
  const words = name.replace(/^Dr\.?\s+/i, '').split(/\s+/).filter(Boolean);
  const letters = words.length > 1 ? [words[0], words[words.length - 1]] : words;
  return letters.map((word) => word.charAt(0).toUpperCase()).join('');
}

export function UserPickerPanel({ initialRole, onPicked }: { initialRole?: Role; onPicked?: () => void }) {
  const { userKey, switchUser } = useActingUser();
  const [role, setRole] = useState<Role>(initialRole ?? 'Doctor');
  const [filter, setFilter] = useState('');
  const q = useDebounced(filter.trim(), 250);

  const users = useQuery({
    queryKey: queryKeys.users(role, q),
    queryFn: ({ signal }) => api.users({ role, q, limit: 50 }, signal),
    staleTime: 60_000,
  });

  const pick = (user: UserView) => {
    onPicked?.();
    switchUser(user.key);
  };

  return (
    <div className="picker">
      <fieldset className="segmented">
        <legend>User type</legend>
        {ROLES.map((item) => (
          <label key={item} className={item === role ? 'segment segment-selected' : 'segment'}>
            <input
              type="radio"
              name="picker-role"
              value={item}
              checked={item === role}
              onChange={() => {
                setRole(item);
                setFilter('');
              }}
            />
            {ROLE_LABELS[item]}
          </label>
        ))}
      </fieldset>
      <div className="field">
        <label htmlFor="picker-filter">Find a user</label>
        <input
          id="picker-filter"
          type="search"
          placeholder={role === 'Patient' ? 'Part of the name, for example Marsh' : 'Part of the name, for example Okafor'}
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          autoComplete="off"
        />
      </div>
      <ErrorBanner error={users.error} />
      {users.isPending ? (
        <Loading label="Wait. The app gets the users." />
      ) : users.data && users.data.length === 0 ? (
        <p className="empty-state">No user has this name.</p>
      ) : (
        <ul className="picker-list" aria-label={`${ROLE_LABELS[role]} users`}>
          {users.data?.map((user) => (
            <li key={user.key}>
              <button
                type="button"
                className={user.key === userKey ? 'picker-item picker-item-current' : 'picker-item'}
                onClick={() => pick(user)}
              >
                <span className={`avatar avatar-${user.role.toLowerCase()}`} aria-hidden="true">
                  {initials(user.name)}
                </span>
                <span className="picker-item-text">
                  <span className="picker-item-name">{user.name}</span>
                  <span className="picker-item-detail">{user.detail}</span>
                </span>
                {user.pinned && <Badge tone="pin">Demo user</Badge>}
                {user.key === userKey && <Badge tone="ok">Current</Badge>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function UserPickerDialog() {
  const { picker, closePicker, user } = useActingUser();
  return (
    <Dialog open={picker.open} title="Select a user" onClose={closePicker} size="medium">
      {picker.reason && (
        <div className="banner banner-info" role="status">
          {picker.reason} Select a user to continue.
        </div>
      )}
      <UserPickerPanel initialRole={picker.role ?? user?.role} onPicked={closePicker} />
    </Dialog>
  );
}
