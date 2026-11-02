// The Visit tab: the visits of the patient, newest first, with their locations and times.
// MOA: check in, move the location, end the visit, write an intake note.
// Care team: move the location. A doctor on the care team: end the visit.

import { useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { fieldError } from '../api/client';
import { api, queryKeys, type CheckInBody } from '../api/endpoints';
import type { Location, Patient, UserView, Visit, VisitClass } from '../api/types';
import { Badge } from '../components/Badges';
import { ConfirmDialog } from '../components/Dialog';
import { EmptyState, ErrorBanner, ErrorPanel, FieldList, Loading } from '../components/ErrorView';
import { formText, SelectField, TextField } from '../components/Field';
import { formatDateTime, formatRange } from '../lib/dates';
import { VISIT_CLASS_LABELS, VISIT_CLASSES } from '../lib/labels';
import { LOINC_SYSTEM, type RecordSeed } from './recordModel';

const VISITS_SHOWN = 6;

interface VisitTabProps {
  patient: Patient;
  user: UserView;
  onRecord: (seed: RecordSeed) => void;
}

function useInvalidateVisit(patientId: number) {
  const queryClient = useQueryClient();
  return () => {
    for (const key of [queryKeys.patient(patientId), queryKeys.visits(patientId), queryKeys.patientLists, queryKeys.careTeams, queryKeys.locations]) {
      queryClient.invalidateQueries({ queryKey: key });
    }
  };
}

export function VisitTab({ patient, user, onRecord }: VisitTabProps) {
  const permissions = patient.permissions;
  const visits = useQuery({
    queryKey: queryKeys.visits(patient.id),
    queryFn: ({ signal }) => api.visits(patient.id, signal),
  });
  const needsLocations = permissions.checkIn || permissions.moveLocation;
  const locations = useQuery({
    queryKey: queryKeys.locations,
    queryFn: ({ signal }) => api.locations({}, signal),
    enabled: needsLocations && user.role !== 'Patient',
    staleTime: 60_000,
  });
  const [all, setAll] = useState(false);

  if (visits.isPending) return <Loading label="Wait. The app gets the visits." />;
  if (visits.isError) return <ErrorPanel error={visits.error} onRetry={() => visits.refetch()} />;

  const openVisit = visits.data.find((visit) => visit.isOpen) ?? null;
  const others = visits.data.filter((visit) => visit !== openVisit);
  const shown = all ? others : others.slice(0, VISITS_SHOWN);
  const isMoa = user.role === 'MOA';

  return (
    <div className="visit-tab stack">
      {openVisit ? (
        <section className="card card-accent" aria-labelledby="open-visit-title">
          <div className="card-header">
            <h2 id="open-visit-title">Open visit</h2>
            <Badge tone="ok">Open</Badge>
          </div>
          <VisitDetails visit={openVisit} />
          <div className="visit-actions">
            {permissions.moveLocation && (
              <MoveLocationForm visit={openVisit} patientId={patient.id} locations={locations.data ?? []} loading={locations.isPending} />
            )}
            <div className="row">
              {isMoa && permissions.recordIntents.length > 0 && (
                <button
                  type="button"
                  className="button"
                  onClick={() =>
                    onRecord({
                      title: 'Write an intake note',
                      rows: [
                        {
                          kind: 'new',
                          action: 'intake',
                          category: 'Observation',
                          presetCode: '8661-1',
                          code: '8661-1',
                          codeSystem: LOINC_SYSTEM,
                          display: 'Chief complaint',
                          intent: 'Report',
                          verification: 'Unconfirmed',
                          statement: '',
                        },
                      ],
                    })
                  }
                >
                  Write an intake note
                </button>
              )}
              {permissions.endVisit && <EndVisitButton visit={openVisit} patientId={patient.id} />}
            </div>
          </div>
        </section>
      ) : (
        <p className="muted">The patient has no open visit.</p>
      )}

      {permissions.checkIn && (
        <CheckInForm patient={patient} openVisit={openVisit} locations={locations.data ?? []} loading={locations.isPending} />
      )}

      <section aria-labelledby="visit-history-title">
        <h2 id="visit-history-title" className="section-title">
          {openVisit ? 'Earlier visits' : 'Visits'} <span className="count">{others.length}</span>
        </h2>
        {others.length === 0 ? (
          <EmptyState>No earlier visit.</EmptyState>
        ) : (
          <ul className="visit-list">
            {shown.map((visit) => (
              <li key={visit.id} className="card card-flat">
                <VisitDetails visit={visit} />
              </li>
            ))}
          </ul>
        )}
        {others.length > VISITS_SHOWN && (
          <button type="button" className="link-button" onClick={() => setAll(!all)}>
            {all ? 'Show fewer' : `Show all ${others.length} visits`}
          </button>
        )}
      </section>
    </div>
  );
}

function VisitDetails({ visit }: { visit: Visit }) {
  return (
    <div className="visit">
      <div className="visit-head">
        <strong>{VISIT_CLASS_LABELS[visit.class]}</strong>
        {visit.department && <span className="muted"> · {visit.department}</span>}
        {visit.type && <span className="muted"> · {visit.type}</span>}
        <span className="visit-id muted"> · {visit.identifier.value}</span>
      </div>
      <div className="visit-time">
        {visit.endDate ? formatRange(visit.startDate, visit.endDate) : `Started ${formatDateTime(visit.startDate)}`}
        {visit.endDate && <Badge tone="muted">Ended {formatDateTime(visit.endDate)}</Badge>}
      </div>
      {visit.reason && <div className="visit-reason">Reason: {visit.reason}</div>}
      {visit.locations.length > 0 && (
        <ol className="location-list" aria-label="Locations, oldest first">
          {visit.locations.map((location, index) => (
            <li key={`${location.locationId}-${location.startDate}-${index}`} className={location.endDate ? '' : 'location-current'}>
              <span className="location-name">{location.name}</span>
              {location.department && <span className="muted"> ({location.department})</span>}
              <span className="location-time"> {formatRange(location.startDate, location.endDate)}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function LocationOptions({ locations, exclude }: { locations: Location[]; exclude?: number }) {
  const byDepartment = new Map<string, Location[]>();
  for (const location of locations) {
    if (location.id === exclude) continue;
    const name = location.department ?? 'No department';
    byDepartment.set(name, [...(byDepartment.get(name) ?? []), location]);
  }
  return (
    <>
      {[...byDepartment.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([department, items]) => (
          <optgroup key={department} label={department}>
            {items
              .sort((a, b) => a.name.localeCompare(b.name))
              .map((location) => (
                <option key={location.id} value={location.id}>
                  {location.name}
                </option>
              ))}
          </optgroup>
        ))}
    </>
  );
}

function CheckInForm({ patient, openVisit, locations, loading }: { patient: Patient; openVisit: Visit | null; locations: Location[]; loading: boolean }) {
  const invalidate = useInvalidateVisit(patient.id);
  const [visitClass, setVisitClass] = useState<VisitClass>('EMER');
  const [locationMissing, setLocationMissing] = useState(false);
  const checkIn = useMutation({
    mutationFn: (body: CheckInBody) => api.checkIn(patient.id, body),
    onSuccess: () => invalidate(),
  });
  const disabled = openVisit !== null;

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const locationId = Number(formText(data, 'locationId'));
    setLocationMissing(!locationId);
    if (!locationId) return;
    checkIn.mutate({
      class: visitClass,
      reason: formText(data, 'reason'),
      type: formText(data, 'type'),
      locationId,
    });
  };

  return (
    <section className="card" aria-labelledby="check-in-title">
      <div className="card-header">
        <h2 id="check-in-title">Check in a visit</h2>
      </div>
      {disabled && <p className="muted">You cannot check in a new visit. The patient has an open visit. End it first.</p>}
      <form className="stack" onSubmit={onSubmit} noValidate>
        <fieldset disabled={disabled || checkIn.isPending} className="fieldset-plain">
          <ErrorBanner error={checkIn.error} />
          <FieldList error={checkIn.error} shown={['class', 'reason', 'type', 'locationId']} />
          <div className="grid-2">
            <SelectField label="Visit class" name="class" value={visitClass} onChange={(event) => setVisitClass(event.target.value as VisitClass)} error={fieldError(checkIn.error, 'class')}>
              {VISIT_CLASSES.map((item) => (
                <option key={item} value={item}>
                  {VISIT_CLASS_LABELS[item]} ({item})
                </option>
              ))}
            </SelectField>
            <SelectField
              label="Location"
              name="locationId"
              required
              defaultValue=""
              error={locationMissing ? 'Select a location.' : fieldError(checkIn.error, 'locationId')}
              hint={loading ? 'Wait. The app gets the locations.' : undefined}
            >
              <option value="" disabled>
                Select a location
              </option>
              <LocationOptions locations={locations} />
            </SelectField>
            <TextField label="Reason (optional)" name="reason" placeholder="For example: Shortness of breath" error={fieldError(checkIn.error, 'reason')} />
            <TextField label="Visit type (optional)" name="type" placeholder="For example: Emergency room admission" error={fieldError(checkIn.error, 'type')} />
          </div>
          <div className="form-actions">
            <button type="submit" className="button button-primary">
              {checkIn.isPending ? 'Wait…' : 'Check in'}
            </button>
          </div>
        </fieldset>
      </form>
    </section>
  );
}

function MoveLocationForm({ visit, patientId, locations, loading }: { visit: Visit; patientId: number; locations: Location[]; loading: boolean }) {
  const invalidate = useInvalidateVisit(patientId);
  const current = visit.locations.find((location) => location.endDate === null) ?? visit.locations[visit.locations.length - 1];
  const move = useMutation({
    mutationFn: (locationId: number) => api.moveLocation(visit.id, locationId),
    onSuccess: () => invalidate(),
  });
  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const value = formText(new FormData(event.currentTarget), 'locationId');
    if (value) move.mutate(Number(value));
  };
  return (
    <form className="inline-form" onSubmit={onSubmit}>
      <SelectField
        label={current ? `Move from ${current.name} to` : 'Move to'}
        name="locationId"
        defaultValue=""
        required
        error={fieldError(move.error, 'locationId')}
        hint={loading ? 'Wait. The app gets the locations.' : undefined}
      >
        <option value="" disabled>
          Select a location
        </option>
        <LocationOptions locations={locations} exclude={current?.locationId} />
      </SelectField>
      <button type="submit" className="button" disabled={move.isPending}>
        {move.isPending ? 'Wait…' : 'Move'}
      </button>
      <ErrorBanner error={move.error} onDismiss={() => move.reset()} />
    </form>
  );
}

function EndVisitButton({ visit, patientId }: { visit: Visit; patientId: number }) {
  const invalidate = useInvalidateVisit(patientId);
  const [open, setOpen] = useState(false);
  const end = useMutation({
    mutationFn: () => api.endVisit(visit.id),
    onSuccess: () => {
      invalidate();
      setOpen(false);
    },
  });
  return (
    <>
      <button type="button" className="button button-danger-outline" onClick={() => setOpen(true)}>
        End the visit
      </button>
      <ConfirmDialog
        open={open}
        title="End the visit"
        message={
          <p>
            Do you want to end the {VISIT_CLASS_LABELS[visit.class].toLowerCase()} visit {visit.identifier.value}? The visit and its
            current location get an end time. The chart keeps all items.
          </p>
        }
        confirmLabel="End the visit"
        danger
        busy={end.isPending}
        error={<ErrorBanner error={end.error} />}
        onConfirm={() => end.mutate()}
        onClose={() => {
          end.reset();
          setOpen(false);
        }}
      />
    </>
  );
}
