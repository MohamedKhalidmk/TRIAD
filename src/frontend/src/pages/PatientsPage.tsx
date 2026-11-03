// /patients: Front desk (MOA), My patients (nurse and doctor) and Find a patient.
// Each list is paged (GET /api/patients?limit=&offset=), with a pager under the table.

import { useState, type FormEvent } from 'react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { fieldError } from '../api/client';
import { api, queryKeys, type NewPatientBody, type PatientScope } from '../api/endpoints';
import type { PatientSummary } from '../api/types';
import { homePath, patientPath, type PatientsTab } from '../app/routes';
import { useCurrentUser } from '../app/session';
import { ADDRESS_FIELD_NAMES, AddressFields, readAddress } from '../components/AddressFields';
import { Badge } from '../components/Badges';
import { Dialog } from '../components/Dialog';
import { EmptyState, ErrorBanner, ErrorPanel, FieldList, Loading } from '../components/ErrorView';
import { formText, SelectField, TextField } from '../components/Field';
import { Pager } from '../components/Pager';
import { TabList, TabPanel, useTabParam, type TabItem } from '../components/Tabs';
import { formatDate } from '../lib/dates';
import { SEX_OPTIONS, sexLabel } from '../lib/labels';
import { usePage } from '../lib/usePage';

export function PatientsPage() {
  const user = useCurrentUser();
  if (user.role === 'Patient') return <Navigate to={homePath(user)} replace />;
  const tabs: TabItem<PatientsTab>[] =
    user.role === 'MOA'
      ? [
          { id: 'front-desk', label: 'Front desk' },
          { id: 'find', label: 'Find a patient' },
        ]
      : [
          { id: 'my-patients', label: 'My patients' },
          { id: 'find', label: 'Find a patient' },
        ];
  return <PatientsTabs tabs={tabs} isMoa={user.role === 'MOA'} />;
}

function PatientsTabs({ tabs, isMoa }: { tabs: TabItem<PatientsTab>[]; isMoa: boolean }) {
  const [tab, setTab] = useTabParam(tabs);
  return (
    <div className="page">
      <div className="page-header">
        <h1>Patients</h1>
      </div>
      <TabList tabs={tabs} selected={tab} onSelect={setTab} label="Patient lists" idPrefix="patients" />
      <TabPanel idPrefix="patients" selected={tab}>
        {tab === 'front-desk' && <FrontDesk canRegister={isMoa} />}
        {tab === 'my-patients' && <MyPatients />}
        {tab === 'find' && <FindPatient />}
      </TabPanel>
    </div>
  );
}

function usePatientList(scope: PatientScope, q = '', dob = '', enabled = true) {
  const page = usePage([scope, q, dob]);
  const query = useQuery({
    queryKey: queryKeys.patients(scope, q, dob, page.params),
    queryFn: ({ signal }) => api.patients({ scope, q: q || undefined, dob: dob || undefined, ...page.params }, signal),
    enabled,
    placeholderData: keepPreviousData,
  });
  return { query, page };
}

function FrontDesk({ canRegister }: { canRegister: boolean }) {
  const list = usePatientList('open-visits');
  const [registerOpen, setRegisterOpen] = useState(false);
  return (
    <section className="card" aria-labelledby="front-desk-title">
      <div className="card-header">
        <div>
          <h2 id="front-desk-title">Patients with an open visit</h2>
          <p className="muted">To check in a patient, find the patient first, or register a new patient.</p>
        </div>
        <div className="row">
          <Link className="button" to="?tab=find">
            Find a patient
          </Link>
          {canRegister && (
            <button type="button" className="button button-primary" onClick={() => setRegisterOpen(true)}>
              Register a patient
            </button>
          )}
        </div>
      </div>
      <PatientListBody list={list} empty="No patient has an open visit now." />
      <RegisterPatientDialog open={registerOpen} onClose={() => setRegisterOpen(false)} />
    </section>
  );
}

function MyPatients() {
  const list = usePatientList('care-team');
  return (
    <section className="card" aria-labelledby="my-patients-title">
      <div className="card-header">
        <div>
          <h2 id="my-patients-title">My patients</h2>
          <p className="muted">The patients whose current care team includes you.</p>
        </div>
      </div>
      <PatientListBody list={list} empty="You are not on a current care team." />
    </section>
  );
}

function FindPatient() {
  const [params, setParams] = useSearchParams();
  const q = params.get('q') ?? '';
  const dob = params.get('dob') ?? '';
  const searched = q !== '' || dob !== '';
  const list = usePatientList('all', q, dob, searched);

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const next = new URLSearchParams(params);
    next.set('tab', 'find');
    const name = formText(data, 'q');
    const date = formText(data, 'dob');
    if (name) next.set('q', name);
    else next.delete('q');
    if (date) next.set('dob', date);
    else next.delete('dob');
    setParams(next, { replace: true });
  };

  return (
    <section className="card" aria-labelledby="find-title">
      <div className="card-header">
        <div>
          <h2 id="find-title">Find a patient</h2>
          <p className="muted">Find a patient by name, date of birth, or both.</p>
        </div>
      </div>
      <form className="search-form" onSubmit={onSubmit} key={`${q}|${dob}`}>
        <TextField label="Name (or part of the name)" name="q" type="search" defaultValue={q} autoComplete="off" />
        <TextField label="Date of birth" name="dob" type="date" defaultValue={dob} />
        <button type="submit" className="button button-primary">
          Find
        </button>
      </form>
      {searched ? (
        <PatientListBody list={list} empty="No patient matches the search." />
      ) : (
        <EmptyState>Write a name or a date of birth, then select Find.</EmptyState>
      )}
    </section>
  );
}

function PatientListBody({ list, empty }: { list: ReturnType<typeof usePatientList>; empty: string }) {
  const { query, page } = list;
  if (query.isPending) return <Loading />;
  if (query.isError) return <ErrorPanel error={query.error} onRetry={() => query.refetch()} />;
  return (
    <>
      {query.data.items.length === 0 ? <EmptyState>{empty}</EmptyState> : <PatientTable patients={query.data.items} busy={query.isPlaceholderData} />}
      <Pager page={query.data} state={page} label="the patient list" busy={query.isPlaceholderData} />
    </>
  );
}

export function PatientTable({ patients, busy = false }: { patients: PatientSummary[]; busy?: boolean }) {
  return (
    <div className={busy ? 'table-wrap paged-busy' : 'table-wrap'}>
      <table className="table">
        <thead>
          <tr>
            <th scope="col">Name</th>
            <th scope="col">Date of birth</th>
            <th scope="col">Sex</th>
            <th scope="col">Phone</th>
            <th scope="col">Visit</th>
          </tr>
        </thead>
        <tbody>
          {patients.map((patient) => (
            <tr key={patient.id}>
              <td>
                <Link to={patientPath(patient.id)} className="strong-link">
                  {patient.name}
                </Link>
              </td>
              <td>{formatDate(patient.dateOfBirth)}</td>
              <td>{sexLabel(patient.sex)}</td>
              <td>{patient.phoneNumber ?? '—'}</td>
              <td>{patient.openVisitId !== null ? <Badge tone="ok">Open visit</Badge> : <span className="muted">None open</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RegisterPatientDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const create = useMutation({
    mutationFn: (body: NewPatientBody) => api.createPatient(body),
    onSuccess: (patient) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.patientLists });
      queryClient.setQueryData(queryKeys.patient(patient.id), patient);
      onClose();
      navigate(patientPath(patient.id, 'visit'));
    },
  });

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    create.mutate({
      name: formText(data, 'name') ?? '',
      dateOfBirth: formText(data, 'dateOfBirth') ?? '',
      sex: (formText(data, 'sex') ?? 'unknown') as NewPatientBody['sex'],
      phoneNumber: formText(data, 'phoneNumber'),
      address: readAddress(data),
    });
  };

  const close = () => {
    create.reset();
    onClose();
  };

  return (
    <Dialog open={open} title="Register a patient" onClose={close} size="medium" subtitle="The name and the date of birth are the key of the patient. You cannot change them later.">
      <form className="stack" onSubmit={onSubmit} noValidate>
        <ErrorBanner error={create.error} />
        <FieldList error={create.error} shown={['name', 'dateOfBirth', 'sex', 'phoneNumber', ...ADDRESS_FIELD_NAMES]} />
        <div className="grid-2">
          <TextField label="Full name" name="name" required autoComplete="off" error={fieldError(create.error, 'name')} className="span-2" />
          <TextField label="Date of birth" name="dateOfBirth" type="date" required error={fieldError(create.error, 'dateOfBirth')} />
          <SelectField label="Sex" name="sex" defaultValue="unknown" error={fieldError(create.error, 'sex')}>
            {SEX_OPTIONS.map((sex) => (
              <option key={sex} value={sex}>
                {sexLabel(sex)}
              </option>
            ))}
          </SelectField>
          <TextField label="Phone number" name="phoneNumber" type="tel" autoComplete="off" error={fieldError(create.error, 'phoneNumber')} />
        </div>
        <AddressFields error={create.error} />
        <div className="form-actions">
          <button type="button" className="button" onClick={close}>
            Cancel
          </button>
          <button type="submit" className="button button-primary" disabled={create.isPending}>
            {create.isPending ? 'Wait…' : 'Register'}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
