// The one fetch wrapper of the app.
// - It adds the header X-Triad-User with the current user key.
// - It reads the error body of the contract ({ code, message, fields? }) and throws an ApiRequestError.
// - It stops all open requests when the user changes (abortOpenRequests).

import type { ApiError } from './types';

export type ErrorCode = ApiError['code'] | 'network' | 'server';

/** An error from the API. status is 0 when the app cannot connect to the server. */
export class ApiRequestError extends Error {
  readonly status: number;
  readonly code: ErrorCode;
  readonly fields: Record<string, string>;

  constructor(status: number, code: ErrorCode, message: string, fields?: Record<string, string>) {
    super(message);
    this.name = 'ApiRequestError';
    this.status = status;
    this.code = code;
    this.fields = fields ?? {};
  }
}

export function isApiError(error: unknown): error is ApiRequestError {
  return error instanceof ApiRequestError;
}

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

// ----- The current user -----

let currentUserKey: string | null = null;
let sessionController = new AbortController();
const unauthorizedListeners = new Set<(message: string) => void>();

/** Sets the user key that the next requests send in X-Triad-User. */
export function setRequestUser(key: string | null): void {
  currentUserKey = key;
}

/** Stops all requests that are open now. Use it when the user changes. */
export function abortOpenRequests(): void {
  sessionController.abort();
  sessionController = new AbortController();
}

/** Calls the listener for each 401 response. Returns a function that removes the listener. */
export function onUnauthorized(listener: (message: string) => void): () => void {
  unauthorizedListeners.add(listener);
  return () => {
    unauthorizedListeners.delete(listener);
  };
}

// ----- Requests -----

export type QueryValue = string | number | boolean | null | undefined;

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  query?: Record<string, QueryValue>;
  body?: unknown;
  signal?: AbortSignal;
  /** false for the endpoints that do not need the user header (health and users). */
  withUser?: boolean;
}

const API_BASE = '/api';

export function buildPath(path: string, query?: Record<string, QueryValue>): string {
  const params = new URLSearchParams();
  for (const [name, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null || value === '') continue;
    params.set(name, String(value));
  }
  const search = params.toString();
  return `${API_BASE}${path}${search ? `?${search}` : ''}`;
}

function combineSignals(signals: (AbortSignal | undefined)[]): AbortSignal {
  const present = signals.filter((signal): signal is AbortSignal => signal !== undefined);
  if (typeof AbortSignal.any === 'function') return AbortSignal.any(present);
  const controller = new AbortController();
  for (const signal of present) {
    if (signal.aborted) {
      controller.abort(signal.reason);
      break;
    }
    signal.addEventListener('abort', () => controller.abort(signal.reason), { once: true });
  }
  return controller.signal;
}

const CODE_FOR_STATUS: Record<number, ErrorCode> = {
  401: 'no_user',
  403: 'forbidden',
  404: 'not_found',
  409: 'conflict',
  422: 'validation',
};

function toApiRequestError(status: number, statusText: string, body: unknown): ApiRequestError {
  const data = (typeof body === 'object' && body !== null ? body : {}) as Record<string, unknown>;
  const code = (typeof data.code === 'string' ? data.code : CODE_FOR_STATUS[status] ?? 'server') as ErrorCode;
  let message = typeof data.message === 'string' ? data.message : '';
  if (!message && typeof data.detail === 'string') message = data.detail;
  if (!message) message = status >= 500 ? `The server has a problem (${status} ${statusText}).` : `The request failed (${status} ${statusText}).`;
  const fields: Record<string, string> = {};
  if (typeof data.fields === 'object' && data.fields !== null) {
    for (const [name, value] of Object.entries(data.fields as Record<string, unknown>)) {
      fields[name] = String(value);
    }
  }
  return new ApiRequestError(status, code, message, fields);
}

/** Sends one request to the API and gives the parsed JSON body. A 204 response gives undefined. */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  const userKey = currentUserKey;
  if (options.withUser !== false && userKey) headers['X-Triad-User'] = userKey;
  let body: string | undefined;
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(options.body);
  }

  let response: Response;
  try {
    response = await fetch(buildPath(path, options.query), {
      method: options.method ?? 'GET',
      headers,
      body,
      signal: combineSignals([sessionController.signal, options.signal]),
    });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new ApiRequestError(
      0,
      'network',
      'The app cannot connect to the backend. Make sure that the backend runs (see the Quickstart in README.md).',
    );
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }

  if (!response.ok) {
    const error = toApiRequestError(response.status, response.statusText, data);
    if (response.status === 401 && userKey === currentUserKey) {
      for (const listener of unauthorizedListeners) listener(error.message);
    }
    throw error;
  }
  if (data === null && text) {
    throw new ApiRequestError(response.status, 'server', 'The server sent a response that is not JSON.');
  }
  return data as T;
}

// ----- Field errors (422) -----

/**
 * Normalizes a field name of a 422 response, so that the form can find it.
 * "body.assertions[0].newEntry.code" and "assertions.0.newEntry.code" both give "assertions.0.newEntry.code".
 */
export function normalizeFieldName(name: string): string {
  return name
    .replace(/\[(\d+)\]/g, '.$1')
    .replace(/^body\./, '')
    .replace(/^\./, '');
}

/** Gives the message for the first field name that has an error, or undefined. */
export function fieldError(error: unknown, ...names: string[]): string | undefined {
  if (!isApiError(error)) return undefined;
  const normalized = new Map<string, string>();
  for (const [name, message] of Object.entries(error.fields)) normalized.set(normalizeFieldName(name), message);
  for (const name of names) {
    const message = normalized.get(name);
    if (message !== undefined) return message;
  }
  return undefined;
}

/** Makes a random id for a chat turn. It uses crypto.randomUUID when the browser has it. */
export function newClientTurnId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
