// Parts that the four directory tabs share.

import { useState, type ReactNode } from 'react';
import { useMutation, useQueryClient, type QueryKey } from '@tanstack/react-query';
import type { Identifier } from '../api/types';
import { ConfirmDialog } from '../components/Dialog';
import { ErrorBanner } from '../components/ErrorView';
import { TextField } from '../components/Field';

export const IDENTIFIER_SYSTEMS = {
  organization: 'https://triad.example/fhir/sid/organization',
  location: 'https://triad.example/fhir/sid/location',
  employee: 'https://triad.example/fhir/sid/employee',
} as const;

/** The optional identifier of a new row. If it is empty, the server makes one. */
export function IdentifierField({ system, error }: { system: string; error?: string }) {
  return (
    <TextField
      label="Identifier (optional)"
      name="identifierValue"
      autoComplete="off"
      hint={`System: ${system}. If you leave it empty, the server makes a new identifier.`}
      error={error}
    />
  );
}

export function readIdentifier(data: FormData, system: string): Identifier | undefined {
  const value = data.get('identifierValue');
  if (typeof value !== 'string' || value.trim() === '') return undefined;
  return { system, value: value.trim() };
}

/** A delete button with a confirm dialog. A 409 shows as a banner in the dialog. */
export function useDelete<T>(remove: (item: T) => Promise<void>, invalidate: QueryKey[]) {
  const queryClient = useQueryClient();
  const [target, setTarget] = useState<T | null>(null);
  const mutation = useMutation({
    mutationFn: (item: T) => remove(item),
    onSuccess: () => {
      for (const key of invalidate) queryClient.invalidateQueries({ queryKey: key });
      setTarget(null);
    },
  });
  const close = () => {
    mutation.reset();
    setTarget(null);
  };
  return { target, ask: (item: T) => setTarget(item), close, mutation };
}

export function DeleteDialog<T>({
  state,
  title,
  describe,
}: {
  state: ReturnType<typeof useDelete<T>>;
  title: string;
  describe: (item: T) => ReactNode;
}) {
  return (
    <ConfirmDialog
      open={state.target !== null}
      title={title}
      message={state.target !== null ? describe(state.target) : null}
      confirmLabel="Delete"
      danger
      busy={state.mutation.isPending}
      error={<ErrorBanner error={state.mutation.error} />}
      onConfirm={() => {
        if (state.target !== null) state.mutation.mutate(state.target);
      }}
      onClose={state.close}
    />
  );
}

export function RowActions({ onEdit, onDelete, name }: { onEdit: () => void; onDelete: () => void; name: string }) {
  return (
    <div className="row row-end">
      <button type="button" className="button button-small" onClick={onEdit} aria-label={`Edit ${name}`}>
        Edit
      </button>
      <button type="button" className="button button-small button-danger-outline" onClick={onDelete} aria-label={`Delete ${name}`}>
        Delete
      </button>
    </div>
  );
}

export function DirectoryToolbar({ children, onCreate, createLabel }: { children: ReactNode; onCreate?: () => void; createLabel: string }) {
  return (
    <div className="filter-bar filter-bar-row">
      <div className="row row-wrap">{children}</div>
      {onCreate && (
        <button type="button" className="button button-primary" onClick={onCreate}>
          {createLabel}
        </button>
      )}
    </div>
  );
}
