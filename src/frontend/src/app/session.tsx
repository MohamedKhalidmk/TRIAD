// The acting user: the user that the app acts as. The app has no login (USER_FLOWS.md section 1).
//
// Where the user key comes from, in this order:
//   1. The link parameter ?as=<user key>. It sets the user for this browser tab only.
//   2. The user of this tab (sessionStorage). A reload keeps it.
//   3. The last user that you selected (localStorage). A new tab starts with it.
// So you can open more than one tab, each with a different user.

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useLocation, useNavigate } from 'react-router-dom';
import { abortOpenRequests, isApiError, onUnauthorized, setRequestUser } from '../api/client';
import { api, queryKeys } from '../api/endpoints';
import type { Role, UserView } from '../api/types';
import { ROUTES } from './routes';

const STORED_USER = 'triad.user';
const TAB_USER = 'triad.user.tab';

function readStorage(storage: Storage | undefined, name: string): string | null {
  try {
    return storage?.getItem(name) ?? null;
  } catch {
    return null;
  }
}

function writeStorage(storage: Storage | undefined, name: string, value: string | null): void {
  try {
    if (value === null) storage?.removeItem(name);
    else storage?.setItem(name, value);
  } catch {
    // Private mode can block the storage. The app still works for this page.
  }
}

function readInitialKey(): string | null {
  const fromLink = new URLSearchParams(window.location.search).get('as');
  if (fromLink) {
    writeStorage(window.sessionStorage, TAB_USER, fromLink);
    return fromLink;
  }
  return readStorage(window.sessionStorage, TAB_USER) ?? readStorage(window.localStorage, STORED_USER);
}

export type UserStatus = 'none' | 'loading' | 'ready' | 'unknown' | 'error';

export interface PickerRequest {
  open: boolean;
  role?: Role;
  reason?: string;
}

export interface SwitchOptions {
  /** The page to open after the change. The default is the home page of the new user. */
  to?: string;
  /** true: keep the change in this tab only (the ?as= link parameter). */
  tabOnly?: boolean;
}

interface ActingUserValue {
  userKey: string | null;
  user: UserView | null;
  status: UserStatus;
  error: unknown;
  /** Increases on each user change. The pages use it as a React key, so they start again. */
  epoch: number;
  switchUser: (key: string | null, options?: SwitchOptions) => void;
  picker: PickerRequest;
  openPicker: (request?: Omit<PickerRequest, 'open'>) => void;
  closePicker: () => void;
}

const ActingUserContext = createContext<ActingUserValue | null>(null);

export function ActingUserProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const [userKey, setUserKey] = useState<string | null>(() => {
    const key = readInitialKey();
    setRequestUser(key);
    return key;
  });
  const [epoch, setEpoch] = useState(0);
  const [picker, setPicker] = useState<PickerRequest>({ open: false });

  const me = useQuery({
    queryKey: queryKeys.me(userKey ?? ''),
    queryFn: ({ signal }) => api.me(signal),
    enabled: userKey !== null,
    retry: false,
    staleTime: Infinity,
  });

  const switchUser = useCallback(
    (key: string | null, options: SwitchOptions = {}) => {
      // Stop the requests of the old user, and forget all data of the old user.
      abortOpenRequests();
      queryClient.clear();
      setRequestUser(key);
      writeStorage(window.sessionStorage, TAB_USER, key);
      if (!options.tabOnly) writeStorage(window.localStorage, STORED_USER, key);
      setUserKey(key);
      setEpoch((value) => value + 1);
      setPicker({ open: false });
      navigate(options.to ?? ROUTES.home.path);
    },
    [navigate, queryClient],
  );

  // The ?as= link parameter can also come with a link inside the app.
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const fromLink = params.get('as');
    if (!fromLink) return;
    params.delete('as');
    const rest = params.toString();
    const to = `${location.pathname}${rest ? `?${rest}` : ''}`;
    if (fromLink !== userKey) switchUser(fromLink, { to, tabOnly: true });
    else navigate(to, { replace: true });
  }, [location.pathname, location.search, navigate, switchUser, userKey]);

  // A 401 response means that the server does not know the user. Ask for a user.
  useEffect(
    () =>
      onUnauthorized((message) => {
        setPicker({ open: true, reason: message });
      }),
    [],
  );

  const openPicker = useCallback((request: Omit<PickerRequest, 'open'> = {}) => {
    setPicker({ open: true, ...request });
  }, []);
  const closePicker = useCallback(() => setPicker({ open: false }), []);

  let status: UserStatus = 'ready';
  if (userKey === null) status = 'none';
  else if (me.isPending) status = 'loading';
  else if (me.isError) status = isApiError(me.error) && (me.error.status === 401 || me.error.status === 404) ? 'unknown' : 'error';

  const value = useMemo<ActingUserValue>(
    () => ({
      userKey,
      user: me.data ?? null,
      status,
      error: me.error,
      epoch,
      switchUser,
      picker,
      openPicker,
      closePicker,
    }),
    [userKey, me.data, status, me.error, epoch, switchUser, picker, openPicker, closePicker],
  );

  return <ActingUserContext.Provider value={value}>{children}</ActingUserContext.Provider>;
}

export function useActingUser(): ActingUserValue {
  const value = useContext(ActingUserContext);
  if (!value) throw new Error('useActingUser must be inside ActingUserProvider.');
  return value;
}

/** The current user. Use it only in pages that show when the user is ready. */
export function useCurrentUser(): UserView {
  const { user } = useActingUser();
  if (!user) throw new Error('useCurrentUser needs a ready user.');
  return user;
}
