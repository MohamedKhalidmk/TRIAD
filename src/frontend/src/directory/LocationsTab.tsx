// Directory: locations (GET, POST, PATCH, DELETE /api/locations).
// The department of a location is the department name.
// The server filters the department, finds the text (q: the name or the identifier value) and sends one page.

import { useState, type FormEvent } from 'react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { fieldError } from '../api/client';
import { api, queryKeys, type LocationBody } from '../api/endpoints';
import type { Department, Location } from '../api/types';
import { ADDRESS_FIELD_NAMES, AddressFields, readAddress } from '../components/AddressFields';
import { Badge } from '../components/Badges';
import { Dialog } from '../components/Dialog';
import { EmptyState, ErrorBanner, ErrorPanel, FieldList, Loading } from '../components/ErrorView';
import { formText, SelectField, TextField } from '../components/Field';
import { Pager } from '../components/Pager';
import { useDebounced } from '../lib/useDebounced';
import { usePage } from '../lib/usePage';
import {
  DeleteDialog,
  DirectoryToolbar,
  FILTER_DELAY,
  IDENTIFIER_SYSTEMS,
  IdentifierField,
  readIdentifier,
  RowActions,
  useDelete,
  useDepartmentOptions,
} from './common';

export function LocationsTab({ canWrite }: { canWrite: boolean }) {
  const [filter, setFilter] = useState('');
  const [department, setDepartment] = useState('');
  const q = useDebounced(filter.trim(), FILTER_DELAY);
  const page = usePage([department, q]);
  const locations = useQuery({
    queryKey: queryKeys.locationPage(department, q, page.params),
    queryFn: ({ signal }) => api.locations({ department, q, ...page.params }, signal),
    placeholderData: keepPreviousData,
  });
  const departments = useDepartmentOptions();
  const [editing, setEditing] = useState<Location | 'new' | null>(null);
  const remove = useDelete<Location>((item) => api.deleteLocation(item.id), [queryKeys.locations, queryKeys.departments]);

  const rows = locations.data?.items ?? [];

  return (
    <div className="stack">
      <DirectoryToolbar onCreate={canWrite ? () => setEditing('new') : undefined} createLabel="New location">
        <div className="field field-inline">
          <label htmlFor="location-filter">Find a location</label>
          <input id="location-filter" type="search" value={filter} onChange={(event) => setFilter(event.target.value)} autoComplete="off" />
        </div>
        <div className="field field-inline">
          <label htmlFor="location-department">Department</label>
          <select id="location-department" value={department} onChange={(event) => setDepartment(event.target.value)}>
            <option value="">All departments</option>
            {departments.map((item) => (
              <option key={item.id} value={item.name}>
                {item.name}
              </option>
            ))}
          </select>
        </div>
      </DirectoryToolbar>
      {locations.isPending ? (
        <Loading />
      ) : locations.isError ? (
        <ErrorPanel error={locations.error} onRetry={() => locations.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState>No location matches.</EmptyState>
      ) : (
        <div className={locations.isPlaceholderData ? 'table-wrap paged-busy' : 'table-wrap'}>
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Identifier</th>
                <th scope="col">Department</th>
                <th scope="col">Physical type</th>
                <th scope="col">Phone</th>
                <th scope="col">Use</th>
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
                  </td>
                  <td className="mono">{item.identifier.value}</td>
                  <td>{item.department ?? '—'}</td>
                  <td>{item.physicalType ?? '—'}</td>
                  <td className="nowrap">{item.phoneNumber ?? '—'}</td>
                  <td>{item.inUse ? <Badge tone="neutral">Used by a visit</Badge> : <Badge tone="muted">Not used</Badge>}</td>
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
      <Pager page={locations.data} state={page} label="the locations" busy={locations.isPlaceholderData} />
      {canWrite && <LocationDialog editing={editing} departments={departments} onClose={() => setEditing(null)} />}
      <DeleteDialog
        state={remove}
        title="Delete a location"
        describe={(item) => (
          <p>
            Do you want to delete the location <strong>{item.name}</strong>? You cannot delete a location that a visit used.
          </p>
        )}
      />
    </div>
  );
}

function LocationDialog({ editing, departments, onClose }: { editing: Location | 'new' | null; departments: Department[]; onClose: () => void }) {
  const queryClient = useQueryClient();
  const isNew = editing === 'new';
  const current = editing !== null && editing !== 'new' ? editing : null;
  const save = useMutation({
    mutationFn: (body: LocationBody) => (current ? api.updateLocation(current.id, body) : api.createLocation(body)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.locations });
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
    const body: LocationBody = {
      name: formText(data, 'name') ?? '',
      department: formText(data, 'department'),
      physicalType: formText(data, 'physicalType'),
      phoneNumber: formText(data, 'phoneNumber'),
      address: readAddress(data),
    };
    const identifier = isNew ? readIdentifier(data, IDENTIFIER_SYSTEMS.location) : undefined;
    if (identifier) body.identifier = identifier;
    save.mutate(body);
  };
  return (
    <Dialog open={editing !== null} title={isNew ? 'New location' : `Edit ${current?.name ?? ''}`} onClose={close}>
      <form className="stack" onSubmit={onSubmit} noValidate>
        <ErrorBanner error={save.error} />
        <FieldList error={save.error} shown={['name', 'department', 'physicalType', 'phoneNumber', 'identifier', 'identifier.value', ...ADDRESS_FIELD_NAMES]} />
        <div className="grid-2">
          <TextField label="Name" name="name" required defaultValue={current?.name ?? ''} error={fieldError(save.error, 'name')} className="span-2" />
          {isNew && <IdentifierField system={IDENTIFIER_SYSTEMS.location} error={fieldError(save.error, 'identifier', 'identifier.value')} />}
          <SelectField label="Department" name="department" defaultValue={current?.department ?? ''} error={fieldError(save.error, 'department')}>
            <option value="">No department</option>
            {departments.map((item) => (
              <option key={item.id} value={item.name}>
                {item.name}
              </option>
            ))}
          </SelectField>
          <TextField label="Physical type (optional)" name="physicalType" defaultValue={current?.physicalType ?? ''} error={fieldError(save.error, 'physicalType')} hint="For example: Room, Bed, Ward or Area." />
          <TextField label="Phone number (optional)" name="phoneNumber" type="tel" defaultValue={current?.phoneNumber ?? ''} error={fieldError(save.error, 'phoneNumber')} />
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
