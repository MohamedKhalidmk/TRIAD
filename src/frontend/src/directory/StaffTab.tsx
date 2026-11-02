// Directory: staff (GET, POST, PATCH, DELETE /api/staff).
// A change (PATCH) can set the contact data, the languages, the active flag and the fields of the role.
// The name, the role and the departments do not change here.

import { useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { fieldError } from '../api/client';
import { api, queryKeys, type StaffCreateBody, type StaffPatchBody } from '../api/endpoints';
import type { Department, Staff, StaffRole } from '../api/types';
import { Badge } from '../components/Badges';
import { Dialog } from '../components/Dialog';
import { EmptyState, ErrorBanner, ErrorPanel, FieldList, Loading } from '../components/ErrorView';
import { formText, SelectField, TextField } from '../components/Field';
import { SEX_OPTIONS, sexLabel } from '../lib/labels';
import { useDebounced } from '../lib/useDebounced';
import { DeleteDialog, DirectoryToolbar, IDENTIFIER_SYSTEMS, IdentifierField, readIdentifier, RowActions, useDelete } from './common';

const STAFF_ROLES: StaffRole[] = ['Doctor', 'Nurse', 'MOA'];
const DESIGNATIONS = ['RN', 'LPN', 'RPN', 'NP'] as const;

export function StaffTab({ canWrite }: { canWrite: boolean }) {
  const [filter, setFilter] = useState('');
  const [role, setRole] = useState<StaffRole | ''>('');
  const q = useDebounced(filter.trim(), 250);
  const staff = useQuery({
    queryKey: queryKeys.staff(role, q),
    queryFn: ({ signal }) => api.staff({ role, q, limit: 200 }, signal),
  });
  const departments = useQuery({
    queryKey: queryKeys.departments,
    queryFn: ({ signal }) => api.departments(signal),
    enabled: canWrite,
  });
  const [editing, setEditing] = useState<Staff | null>(null);
  const [creating, setCreating] = useState(false);
  const remove = useDelete<Staff>((item) => api.deleteStaff(item.id), [queryKeys.staffLists, queryKeys.departments]);

  return (
    <div className="stack">
      <DirectoryToolbar onCreate={canWrite ? () => setCreating(true) : undefined} createLabel="New staff member">
        <div className="field field-inline">
          <label htmlFor="staff-filter">Find staff by name</label>
          <input id="staff-filter" type="search" value={filter} onChange={(event) => setFilter(event.target.value)} autoComplete="off" />
        </div>
        <div className="field field-inline">
          <label htmlFor="staff-role">Role</label>
          <select id="staff-role" value={role} onChange={(event) => setRole(event.target.value as StaffRole | '')}>
            <option value="">All roles</option>
            {STAFF_ROLES.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </div>
      </DirectoryToolbar>
      {staff.isPending ? (
        <Loading />
      ) : staff.isError ? (
        <ErrorPanel error={staff.error} onRetry={() => staff.refetch()} />
      ) : staff.data.length === 0 ? (
        <EmptyState>No staff member matches.</EmptyState>
      ) : (
        <>
          <p className="muted small">
            {staff.data.length} staff members{staff.data.length >= 200 ? ' (the first 200; write a name to find others)' : ''}.
          </p>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Role</th>
                  <th scope="col">Departments</th>
                  <th scope="col">Phone</th>
                  <th scope="col">Email</th>
                  <th scope="col">Status</th>
                  {canWrite && (
                    <th scope="col">
                      <span className="visually-hidden">Actions</span>
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {staff.data.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <strong>{item.name}</strong>
                      <div className="muted small mono">{item.key}</div>
                    </td>
                    <td>
                      {item.role}
                      {item.designation && <span className="muted"> ({item.designation})</span>}
                    </td>
                    <td>{item.departments.map((d) => (d.specialty ? `${d.name} (${d.specialty})` : d.name)).join(', ') || '—'}</td>
                    <td className="nowrap">{item.phoneNumber ?? '—'}</td>
                    <td>{item.email ?? '—'}</td>
                    <td>{item.active ? <Badge tone="ok">Active</Badge> : <Badge tone="muted">Not active</Badge>}</td>
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
        </>
      )}
      {canWrite && <StaffEditDialog staff={editing} onClose={() => setEditing(null)} />}
      {canWrite && <StaffCreateDialog open={creating} departments={departments.data ?? []} onClose={() => setCreating(false)} />}
      <DeleteDialog
        state={remove}
        title="Delete a staff member"
        describe={(item) => (
          <p>
            Do you want to delete <strong>{item.name}</strong>? You cannot delete a staff member who issued a message or works in a
            department.
          </p>
        )}
      />
    </div>
  );
}

function languagesOf(data: FormData): string[] {
  return (formText(data, 'languages') ?? '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

/** The fields of one role: Doctor (licence, qualification), Nurse (designation, licence), MOA (certificate, desk, extension). */
function RoleFields({ role, staff, error }: { role: StaffRole; staff?: Staff | null; error: unknown }) {
  if (role === 'Doctor') {
    return (
      <>
        <TextField label="Licence number (optional)" name="licenseNumber" defaultValue={staff?.licenseNumber ?? ''} error={fieldError(error, 'licenseNumber')} />
        <TextField label="Qualification (optional)" name="qualification" defaultValue={staff?.qualification ?? ''} error={fieldError(error, 'qualification')} />
      </>
    );
  }
  if (role === 'Nurse') {
    return (
      <>
        <SelectField label="Designation" name="designation" defaultValue={staff?.designation ?? 'RN'} error={fieldError(error, 'designation')}>
          {DESIGNATIONS.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </SelectField>
        <TextField label="Licence number (optional)" name="licenseNumber" defaultValue={staff?.licenseNumber ?? ''} error={fieldError(error, 'licenseNumber')} />
      </>
    );
  }
  return (
    <>
      <TextField label="Desk" name="desk" required defaultValue={staff?.desk ?? ''} error={fieldError(error, 'desk')} />
      <TextField label="Phone extension (optional)" name="phoneExtension" defaultValue={staff?.phoneExtension ?? ''} error={fieldError(error, 'phoneExtension')} />
      <TextField label="Certificate number (optional)" name="certificationNumber" defaultValue={staff?.certificationNumber ?? ''} error={fieldError(error, 'certificationNumber')} />
    </>
  );
}

function roleBody(role: StaffRole, data: FormData): StaffPatchBody {
  if (role === 'Doctor') return { licenseNumber: formText(data, 'licenseNumber'), qualification: formText(data, 'qualification') };
  if (role === 'Nurse') {
    return { designation: (formText(data, 'designation') ?? 'RN') as Staff['designation'], licenseNumber: formText(data, 'licenseNumber') };
  }
  return {
    desk: formText(data, 'desk'),
    phoneExtension: formText(data, 'phoneExtension'),
    certificationNumber: formText(data, 'certificationNumber'),
  };
}

const PATCH_FIELDS = ['email', 'phoneNumber', 'active', 'languages', 'licenseNumber', 'qualification', 'designation', 'certificationNumber', 'desk', 'phoneExtension'];

function StaffEditDialog({ staff, onClose }: { staff: Staff | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: (body: StaffPatchBody) => api.updateStaff((staff as Staff).id, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.staffLists });
      close();
    },
  });
  const close = () => {
    save.reset();
    onClose();
  };
  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!staff) return;
    const data = new FormData(event.currentTarget);
    save.mutate({
      email: formText(data, 'email'),
      phoneNumber: formText(data, 'phoneNumber'),
      active: data.get('active') === 'on',
      languages: languagesOf(data),
      ...roleBody(staff.role, data),
    });
  };
  return (
    <Dialog open={staff !== null} title={`Edit ${staff?.name ?? ''}`} onClose={close} subtitle={staff ? `${staff.role} · ${staff.key}` : undefined}>
      {staff && (
        <form className="stack" onSubmit={onSubmit} noValidate>
          <ErrorBanner error={save.error} />
          <FieldList error={save.error} shown={PATCH_FIELDS} />
          <div className="grid-2">
            <TextField label="Name" value={staff.name} readOnly disabled />
            <TextField label="Departments" value={staff.departments.map((d) => d.name).join(', ') || 'None'} readOnly disabled />
            <TextField label="Phone number" name="phoneNumber" type="tel" defaultValue={staff.phoneNumber ?? ''} error={fieldError(save.error, 'phoneNumber')} />
            <TextField label="Email" name="email" type="email" defaultValue={staff.email ?? ''} error={fieldError(save.error, 'email')} />
            <TextField
              label="Languages"
              name="languages"
              defaultValue={staff.languages.join(', ')}
              hint="Language codes, with a comma between them. For example: en, fr"
              error={fieldError(save.error, 'languages')}
            />
            <div className="field field-check">
              <label>
                <input type="checkbox" name="active" defaultChecked={staff.active} /> Active
              </label>
            </div>
            <RoleFields role={staff.role} staff={staff} error={save.error} />
          </div>
          <div className="form-actions">
            <button type="button" className="button" onClick={close}>
              Cancel
            </button>
            <button type="submit" className="button button-primary" disabled={save.isPending}>
              {save.isPending ? 'Wait…' : 'Save'}
            </button>
          </div>
        </form>
      )}
    </Dialog>
  );
}

function StaffCreateDialog({ open, departments, onClose }: { open: boolean; departments: Department[]; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [role, setRole] = useState<StaffRole>('Nurse');
  const save = useMutation({
    mutationFn: (body: StaffCreateBody) => api.createStaff(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.staffLists });
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
    const roleFields = roleBody(role, data);
    const body: StaffCreateBody = {
      name: formText(data, 'name') ?? '',
      role,
      sex: formText(data, 'sex'),
      email: formText(data, 'email'),
      phoneNumber: formText(data, 'phoneNumber'),
      active: data.get('active') === 'on',
      languages: languagesOf(data),
      licenseNumber: roleFields.licenseNumber ?? null,
      qualification: roleFields.qualification ?? null,
      designation: roleFields.designation ?? null,
      certificationNumber: roleFields.certificationNumber ?? null,
      desk: roleFields.desk ?? null,
      phoneExtension: roleFields.phoneExtension ?? null,
      departmentId: Number(formText(data, 'departmentId')),
      roleCode: formText(data, 'roleCode') ?? role.toLowerCase(),
      specialty: formText(data, 'specialty'),
    };
    const identifier = readIdentifier(data, IDENTIFIER_SYSTEMS.employee);
    if (identifier) body.identifier = identifier;
    save.mutate(body);
  };
  return (
    <Dialog open={open} title="New staff member" onClose={close}>
      <form className="stack" onSubmit={onSubmit} noValidate>
        <ErrorBanner error={save.error} />
        <FieldList
          error={save.error}
          shown={['name', 'role', 'sex', 'departmentId', 'roleCode', 'specialty', 'identifier', 'identifier.value', ...PATCH_FIELDS]}
        />
        <div className="grid-2">
          <TextField label="Name" name="name" required error={fieldError(save.error, 'name')} className="span-2" />
          <SelectField label="Role" name="role" value={role} onChange={(event) => setRole(event.target.value as StaffRole)} error={fieldError(save.error, 'role')}>
            {STAFF_ROLES.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </SelectField>
          <IdentifierField system={IDENTIFIER_SYSTEMS.employee} error={fieldError(save.error, 'identifier', 'identifier.value')} />
          <SelectField label="Department" name="departmentId" required defaultValue={departments[0]?.id ?? ''} error={fieldError(save.error, 'departmentId')}>
            {departments.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </SelectField>
          <TextField
            key={role}
            label="Role code"
            name="roleCode"
            defaultValue={role.toLowerCase()}
            hint="The role in the department (WorksIn.RoleCode)."
            error={fieldError(save.error, 'roleCode')}
          />
          <TextField label="Specialty (optional)" name="specialty" error={fieldError(save.error, 'specialty')} />
          <SelectField label="Sex" name="sex" defaultValue="unknown" error={fieldError(save.error, 'sex')}>
            {SEX_OPTIONS.map((sex) => (
              <option key={sex} value={sex}>
                {sexLabel(sex)}
              </option>
            ))}
          </SelectField>
          <TextField label="Phone number (optional)" name="phoneNumber" type="tel" error={fieldError(save.error, 'phoneNumber')} />
          <TextField label="Email (optional)" name="email" type="email" error={fieldError(save.error, 'email')} />
          <TextField label="Languages" name="languages" defaultValue="en" hint="Language codes, with a comma between them." error={fieldError(save.error, 'languages')} />
          <div className="field field-check">
            <label>
              <input type="checkbox" name="active" defaultChecked /> Active
            </label>
          </div>
          <RoleFields key={`fields-${role}`} role={role} error={save.error} />
        </div>
        <div className="form-actions">
          <button type="button" className="button" onClick={close}>
            Cancel
          </button>
          <button type="submit" className="button button-primary" disabled={save.isPending}>
            {save.isPending ? 'Wait…' : 'Create'}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
