// The header of the patient page: the demographics.
// The MOA can change the phone number, the sex and the address (PATCH /api/patients/{id}).
// The name and the date of birth are the key of the patient. Nobody can change them.

import { useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { fieldError } from '../api/client';
import { api, queryKeys, type PatientPatchBody } from '../api/endpoints';
import type { Patient, UserView } from '../api/types';
import { ADDRESS_FIELD_NAMES, AddressFields, formatAddress, readAddress } from '../components/AddressFields';
import { Badge } from '../components/Badges';
import { Dialog } from '../components/Dialog';
import { ErrorBanner, FieldList } from '../components/ErrorView';
import { formText, SelectField, TextField } from '../components/Field';
import { formatDate } from '../lib/dates';
import { SEX_OPTIONS, sexLabel } from '../lib/labels';

function identifierLabel(system: string): string {
  if (system.endsWith('/mrn')) return 'MRN';
  if (system.includes('synthea')) return 'Synthea ID';
  if (system.includes('ca-bc-patient-healthcare-id')) return 'PHN';
  if (system.includes('us-ssn') || system.endsWith('/ssn')) return 'SSN';
  return 'ID';
}

export function PatientHeader({ patient, user }: { patient: Patient; user: UserView }) {
  const [editing, setEditing] = useState(false);
  const isSelf = user.role === 'Patient';
  const mainIdentifier = patient.identifiers[0];
  return (
    <section className="patient-header" aria-labelledby="patient-name">
      <div className="patient-header-main">
        <div>
          <span className="eyebrow">{isSelf ? 'My record' : 'Patient'}</span>
          <h1 id="patient-name">{patient.name}</h1>
          <dl className="facts">
            <div>
              <dt>Date of birth</dt>
              <dd>{formatDate(patient.dateOfBirth)}</dd>
            </div>
            <div>
              <dt>Sex</dt>
              <dd>{sexLabel(patient.sex)}</dd>
            </div>
            <div>
              <dt>Phone</dt>
              <dd>{patient.phoneNumber ?? '—'}</dd>
            </div>
            {mainIdentifier && (
              <div>
                <dt>{identifierLabel(mainIdentifier.system)}</dt>
                <dd className="mono" title={mainIdentifier.system}>
                  {mainIdentifier.value}
                </dd>
              </div>
            )}
            <div className="facts-wide">
              <dt>Address</dt>
              <dd>{formatAddress(patient.address) || '—'}</dd>
            </div>
          </dl>
        </div>
        <div className="patient-header-side">
          {patient.openVisitId !== null ? <Badge tone="ok">Open visit</Badge> : <Badge tone="muted">No open visit</Badge>}
          {patient.permissions.editDemographics && (
            <button type="button" className="button" onClick={() => setEditing(true)}>
              Edit details
            </button>
          )}
        </div>
      </div>
      {patient.permissions.editDemographics && <EditDemographicsDialog patient={patient} open={editing} onClose={() => setEditing(false)} />}
    </section>
  );
}

function EditDemographicsDialog({ patient, open, onClose }: { patient: Patient; open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const update = useMutation({
    mutationFn: (body: PatientPatchBody) => api.updatePatient(patient.id, body),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.patient(patient.id), updated);
      queryClient.invalidateQueries({ queryKey: queryKeys.patientLists });
      onClose();
    },
  });

  const close = () => {
    update.reset();
    onClose();
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    update.mutate({
      sex: (formText(data, 'sex') ?? patient.sex) as Patient['sex'],
      phoneNumber: formText(data, 'phoneNumber'),
      address: readAddress(data),
    });
  };

  return (
    <Dialog open={open} title="Edit the patient details" onClose={close} subtitle="The name and the date of birth are the key of the patient. You cannot change them.">
      <form className="stack" onSubmit={onSubmit} noValidate>
        <ErrorBanner error={update.error} />
        <FieldList error={update.error} shown={['sex', 'phoneNumber', ...ADDRESS_FIELD_NAMES]} />
        <div className="grid-2">
          <TextField label="Name" value={patient.name} readOnly disabled />
          <TextField label="Date of birth" value={formatDate(patient.dateOfBirth)} readOnly disabled />
          <TextField label="Phone number" name="phoneNumber" type="tel" defaultValue={patient.phoneNumber ?? ''} error={fieldError(update.error, 'phoneNumber')} />
          <SelectField label="Sex" name="sex" defaultValue={patient.sex} error={fieldError(update.error, 'sex')}>
            {SEX_OPTIONS.map((sex) => (
              <option key={sex} value={sex}>
                {sexLabel(sex)}
              </option>
            ))}
          </SelectField>
        </div>
        <AddressFields value={patient.address} error={update.error} />
        <div className="form-actions">
          <button type="button" className="button" onClick={close}>
            Cancel
          </button>
          <button type="submit" className="button button-primary" disabled={update.isPending}>
            {update.isPending ? 'Wait…' : 'Save'}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
