// How the app shows an error of the API.
// - 403: a full panel with the message of the server.
// - 409: a banner with the message of the server.
// - 422: a banner with the message. The form shows each field message under its field.
// - 401: a panel that asks you to select a user.

import type { ReactNode } from 'react';
import { isAbortError, isApiError, normalizeFieldName } from '../api/client';
import { useActingUser } from '../app/session';

export function errorMessage(error: unknown): string {
  if (isApiError(error)) return error.message;
  if (isAbortError(error)) return 'The request stopped.';
  if (error instanceof Error) return error.message;
  return 'An unknown error occurred.';
}

/** A full panel for an error that stops the page or the tab. */
export function ErrorPanel({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { openPicker } = useActingUser();
  if (isApiError(error) && error.status === 403) return <ForbiddenPanel message={error.message} />;
  if (isApiError(error) && error.status === 401) {
    return (
      <section className="panel-message" role="alert">
        <h2>Select a user</h2>
        <p>{error.message}</p>
        <button type="button" className="button button-primary" onClick={() => openPicker({ reason: error.message })}>
          Select a user
        </button>
      </section>
    );
  }
  const title = isApiError(error)
    ? error.status === 404
      ? 'Not found'
      : error.status === 0
        ? 'No connection to the server'
        : 'The request failed'
    : 'An error occurred';
  return (
    <section className="panel-message" role="alert">
      <h2>{title}</h2>
      <p>{errorMessage(error)}</p>
      {isApiError(error) && error.status === 422 && <FieldList error={error} />}
      {onRetry && (
        <button type="button" className="button" onClick={onRetry}>
          Try again
        </button>
      )}
    </section>
  );
}

/** The 403 panel (journey Use case 7). */
export function ForbiddenPanel({ message }: { message: string }) {
  return (
    <section className="forbidden-panel" role="alert">
      <div className="forbidden-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="28" height="28">
          <path
            d="M7 10V7a5 5 0 0 1 10 0v3"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
          />
          <rect x="4.5" y="10" width="15" height="11" rx="2" fill="currentColor" />
        </svg>
      </div>
      <div>
        <h2>Access denied</h2>
        <p className="forbidden-message">{message}</p>
      </div>
    </section>
  );
}

/** A banner for an error of an action: 409, 422 and the other errors. */
export function ErrorBanner({ error, onDismiss }: { error: unknown; onDismiss?: () => void }) {
  if (!error || isAbortError(error)) return null;
  const conflict = isApiError(error) && error.status === 409;
  const forbidden = isApiError(error) && error.status === 403;
  const title = conflict ? 'Conflict' : forbidden ? 'Access denied' : isApiError(error) && error.status === 422 ? 'Correct the input' : 'Error';
  return (
    <div className={conflict ? 'banner banner-conflict' : 'banner banner-error'} role="alert">
      <div>
        <strong>{title}.</strong> {errorMessage(error)}
      </div>
      {onDismiss && (
        <button type="button" className="icon-button" aria-label="Close the message" onClick={onDismiss}>
          ×
        </button>
      )}
    </div>
  );
}

/** Lists the field messages of a 422 error that the form does not show under a field. */
export function FieldList({ error, shown = [] }: { error: unknown; shown?: string[] }) {
  if (!isApiError(error)) return null;
  const known = new Set(shown.map(normalizeFieldName));
  const rest = Object.entries(error.fields).filter(([name]) => !known.has(normalizeFieldName(name)));
  if (rest.length === 0) return null;
  return (
    <ul className="field-list">
      {rest.map(([name, message]) => (
        <li key={name}>
          <code>{normalizeFieldName(name)}</code>: {message}
        </li>
      ))}
    </ul>
  );
}

export function FieldMessage({ message }: { message?: ReactNode }) {
  if (!message) return null;
  return <span className="field-error">{message}</span>;
}

export function Loading({ label = 'Wait…' }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden="true" />
      {label}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="empty-state">{children}</p>;
}
