// Directory: departments (GET, POST, PATCH, DELETE /api/departments).

import { useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { fieldError } from '../api/client';
import { api, queryKeys, type DepartmentBody } from '../api/endpoints';
import type { Department } from '../api/types';
import { ADDRESS_FIELD_NAMES, AddressFields, formatAddress, readAddress } from '../components/AddressFields';
import { Dialog } from '../components/Dialog';
import { EmptyState, ErrorBanner, ErrorPanel, FieldList, Loading } from '../components/ErrorView';
import { formText, TextField } from '../components/Field';
import { DeleteDialog, DirectoryToolbar, IDENTIFIER_SYSTEMS, IdentifierField, readIdentifier, RowActions, useDelete } from './common';

export function DepartmentsTab({ canWrite }: { canWrite: boolean }) {
  const departments = useQuery({ queryKey: queryKeys.departments, queryFn: ({ signal }) => api.departments(signal) });
  const [filter, setFilter] = useState('');
  const [editing, setEditing] = useState<Department | 'new' | null>(null);
  const remove = useDelete<Department>((item) => api.deleteDepartment(item.id), [queryKeys.departments]);

  const needle = filter.trim().toLowerCase();
  const rows = (departments.data ?? []).filter(
    (item) => !needle || item.name.toLowerCase().includes(needle) || item.identifier.value.toLowerCase().includes(needle),
  );

  return (
    <div className="stack">
      <DirectoryToolbar onCreate={canWrite ? () => setEditing('new') : undefined} createLabel="New department">
        <div className="field field-inline">
          <label htmlFor="department-filter">Find a department</label>
          <input id="department-filter" type="search" value={filter} onChange={(event) => setFilter(event.target.value)} autoComplete="off" />
        </div>
      </DirectoryToolbar>
      {departments.isPending ? (
        <Loading />
      ) : departments.isError ? (
        <ErrorPanel error={departments.error} onRetry={() => departments.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState>No department matches.</EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Identifier</th>
                <th scope="col">Type</th>
                <th scope="col">Phone</th>
                <th scope="col">Email</th>
                <th scope="col" className="num">
                  Staff
                </th>
                {canWrite && (
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((item) => (
                <tr key={item.id}>
                  <td>
                    <strong>{item.name}</strong>
                    {formatAddress(item.address) && <div className="muted small">{formatAddress(item.address)}</div>}
                  </td>
                  <td className="mono">{item.identifier.value}</td>
                  <td>{item.type ?? '—'}</td>
                  <td className="nowrap">{item.phoneNumber ?? '—'}</td>
                  <td>{item.email ?? '—'}</td>
                  <td className="num">{item.staffCount}</td>
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
      {canWrite && <DepartmentDialog editing={editing} onClose={() => setEditing(null)} />}
      <DeleteDialog
        state={remove}
        title="Delete a department"
        describe={(item) => (
          <p>
            Do you want to delete the department <strong>{item.name}</strong>? You cannot delete a department that has staff or
            locations.
          </p>
        )}
      />
    </div>
  );
}

function DepartmentDialog({ editing, onClose }: { editing: Department | 'new' | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const isNew = editing === 'new';
  const current = editing !== null && editing !== 'new' ? editing : null;
  const save = useMutation({
    mutationFn: (body: DepartmentBody) => (current ? api.updateDepartment(current.id, body) : api.createDepartment(body)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.departments });
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
    const body: DepartmentBody = {
      name: formText(data, 'name') ?? '',
      type: formText(data, 'type'),
      phoneNumber: formText(data, 'phoneNumber'),
      email: formText(data, 'email'),
      address: readAddress(data),
    };
    const identifier = isNew ? readIdentifier(data, IDENTIFIER_SYSTEMS.organization) : undefined;
    if (identifier) body.identifier = identifier;
    save.mutate(body);
  };
  return (
    <Dialog open={editing !== null} title={isNew ? 'New department' : `Edit ${current?.name ?? ''}`} onClose={close}>
      <form className="stack" onSubmit={onSubmit} noValidate>
        <ErrorBanner error={save.error} />
        <FieldList error={save.error} shown={['name', 'type', 'phoneNumber', 'email', 'identifier', 'identifier.value', ...ADDRESS_FIELD_NAMES]} />
        <div className="grid-2">
          <TextField label="Name" name="name" required defaultValue={current?.name ?? ''} error={fieldError(save.error, 'name')} className="span-2" />
          {isNew && <IdentifierField system={IDENTIFIER_SYSTEMS.organization} error={fieldError(save.error, 'identifier', 'identifier.value')} />}
          <TextField label="Type (optional)" name="type" defaultValue={current?.type ?? ''} error={fieldError(save.error, 'type')} />
          <TextField label="Phone number (optional)" name="phoneNumber" type="tel" defaultValue={current?.phoneNumber ?? ''} error={fieldError(save.error, 'phoneNumber')} />
          <TextField label="Email (optional)" name="email" type="email" defaultValue={current?.email ?? ''} error={fieldError(save.error, 'email')} />
        </div>
        <AddressFields value={current?.address} error={save.error} legend="Address (optional)" />
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
