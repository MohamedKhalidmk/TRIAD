// The user picker: select a user type, then a user (USER_FLOWS.md section 1).
// The demo users show first. Patients show their date of birth. Staff show their department.
// The server finds the text (q) and sends one page of users (GET /api/users?role=&q=&limit=&offset=).

import { useEffect, useRef, useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { api, queryKeys } from '../api/endpoints';
import type { Role, UserView } from '../api/types';
import { useActingUser } from '../app/session';
import { ROLES, ROLE_LABELS } from '../lib/labels';
import { useDebounced } from '../lib/useDebounced';
import { usePage } from '../lib/usePage';
import { Badge } from './Badges';
import { Dialog } from './Dialog';
import { ErrorBanner, Loading } from './ErrorView';
import { Pager } from './Pager';

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
  const page = usePage([role, q]);
  const listRef = useRef<HTMLUListElement>(null);

  const users = useQuery({
    queryKey: queryKeys.users(role, q, page.params),
    queryFn: ({ signal }) => api.users({ role, q, ...page.params }, signal),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });

  // The list scrolls in its box. On a new page, show the top of the list.
  const shownOffset = users.data?.offset;
  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = 0;
  }, [shownOffset]);

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
      ) : users.data && users.data.items.length === 0 ? (
        <p className="empty-state">No user has this name.</p>
      ) : (
        <ul
          ref={listRef}
          className={users.isPlaceholderData ? 'picker-list paged-busy' : 'picker-list'}
          aria-label={`${ROLE_LABELS[role]} users`}
        >
          {users.data?.items.map((user) => (
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
      <Pager page={users.data} state={page} label="the user list" busy={users.isPlaceholderData} />
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
