// Directory: medications (GET, POST, PATCH, DELETE /api/medications).

import { useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { fieldError } from '../api/client';
import { api, queryKeys, type MedicationBody } from '../api/endpoints';
import type { Medication } from '../api/types';
import { Dialog } from '../components/Dialog';
import { EmptyState, ErrorBanner, ErrorPanel, FieldList, Loading } from '../components/ErrorView';
import { formText, TextField } from '../components/Field';
import { useDebounced } from '../lib/useDebounced';
import { RXNORM_SYSTEM } from '../patient/recordModel';
import { DeleteDialog, DirectoryToolbar, RowActions, useDelete } from './common';

export function MedicationsTab({ canWrite }: { canWrite: boolean }) {
  const [filter, setFilter] = useState('');
  const q = useDebounced(filter.trim(), 250);
  const medications = useQuery({
    queryKey: queryKeys.medications(q),
    queryFn: ({ signal }) => api.medications({ q, limit: 200 }, signal),
  });
  const [editing, setEditing] = useState<Medication | 'new' | null>(null);
  const remove = useDelete<Medication>((item) => api.deleteMedication(item.id), [queryKeys.medicationLists]);

  return (
    <div className="stack">
      <DirectoryToolbar onCreate={canWrite ? () => setEditing('new') : undefined} createLabel="New medication">
        <div className="field field-inline">
          <label htmlFor="medication-filter">Find a medication</label>
          <input id="medication-filter" type="search" value={filter} onChange={(event) => setFilter(event.target.value)} autoComplete="off" />
        </div>
      </DirectoryToolbar>
      {medications.isPending ? (
        <Loading />
      ) : medications.isError ? (
        <ErrorPanel error={medications.error} onRetry={() => medications.refetch()} />
      ) : medications.data.length === 0 ? (
        <EmptyState>No medication matches.</EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Code</th>
                <th scope="col">Form</th>
                <th scope="col">Manufacturer</th>
                {canWrite && (
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {medications.data.map((item) => (
                <tr key={item.id}>
                  <td>
                    <strong>{item.name}</strong>
                  </td>
                  <td className="mono" title={item.codeSystem}>
                    {item.code}
                  </td>
                  <td>{item.form ?? '—'}</td>
                  <td>{item.manufacturer ?? '—'}</td>
                  {canWrite && (
                    <td className="cell-actions">
                      <RowActions name={item.name} onEdit={() => setEditing(item)} onDelete={() => remove.ask(item)} />
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {canWrite && <MedicationDialog editing={editing} onClose={() => setEditing(null)} />}
      <DeleteDialog
        state={remove}
        title="Delete a medication"
        describe={(item) => (
          <p>
            Do you want to delete the medication <strong>{item.name}</strong>? You cannot delete a medication that a prescription
            uses.
          </p>
        )}
      />
    </div>
  );
}

function MedicationDialog({ editing, onClose }: { editing: Medication | 'new' | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const isNew = editing === 'new';
  const current = editing !== null && editing !== 'new' ? editing : null;
  const save = useMutation({
    mutationFn: (body: MedicationBody) => (current ? api.updateMedication(current.id, body) : api.createMedication(body)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.medicationLists });
      close();
    },
  });
  const close = () => {
    save.reset();
    onClose();
  };
  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    save.mutate({
      code: formText(data, 'code') ?? '',
      codeSystem: formText(data, 'codeSystem') ?? '',
      name: formText(data, 'name') ?? '',
      form: formText(data, 'form'),
      manufacturer: formText(data, 'manufacturer'),
    });
  };
  return (
    <Dialog open={editing !== null} title={isNew ? 'New medication' : `Edit ${current?.name ?? ''}`} onClose={close}>
      <form className="stack" onSubmit={onSubmit} noValidate>
        <ErrorBanner error={save.error} />
        <FieldList error={save.error} shown={['code', 'codeSystem', 'name', 'form', 'manufacturer']} />
        <div className="grid-2">
          <TextField label="Name" name="name" required defaultValue={current?.name ?? ''} error={fieldError(save.error, 'name')} className="span-2" />
          <TextField label="Code" name="code" required defaultValue={current?.code ?? ''} error={fieldError(save.error, 'code')} />
          <TextField label="Code system" name="codeSystem" required defaultValue={current?.codeSystem ?? RXNORM_SYSTEM} error={fieldError(save.error, 'codeSystem')} />
          <TextField label="Form (optional)" name="form" defaultValue={current?.form ?? ''} error={fieldError(save.error, 'form')} />
          <TextField label="Manufacturer (optional)" name="manufacturer" defaultValue={current?.manufacturer ?? ''} error={fieldError(save.error, 'manufacturer')} />
        </div>
        <div className="form-actions">
          <button type="button" className="button" onClick={close}>
            Cancel
          </button>
          <button type="submit" className="button button-primary" disabled={save.isPending}>
            {save.isPending ? 'Wait…' : isNew ? 'Create' : 'Save'}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
