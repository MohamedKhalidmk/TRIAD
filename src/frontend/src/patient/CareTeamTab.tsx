// The Care team tab: the current team of the open visit, and its chain of versions.
// Each change is a new care-team entry that supersedes the earlier one (PUT /api/visits/{id}/care-team).
// The MOA and a doctor on the team can add and remove members. "Save" sends the full member list.

import { useMemo, useState } from 'react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, queryKeys, type CareTeamBody, type CareTeamMemberInput } from '../api/endpoints';
import type { CareTeamMember, CareTeamVersion, Patient, Staff } from '../api/types';
import { Badge } from '../components/Badges';
import { EmptyState, ErrorBanner, ErrorPanel, FieldList, Loading } from '../components/ErrorView';
import { formatDateTime } from '../lib/dates';
import { useDebounced } from '../lib/useDebounced';

/** The staff finder shows the first page of matches only (GET /api/staff?q=&limit=20). */
const STAFF_RESULTS = { limit: 20, offset: 0 };

interface DraftMember {
  system: string;
  value: string;
  role: string | null;
  name: string;
  staffRole: string | null;
  department: string | null;
}

function memberId(member: { system: string; value: string }): string {
  return `${member.system}|${member.value}`;
}

function fromMember(member: CareTeamMember): DraftMember {
  return {
    system: member.system,
    value: member.value,
    role: member.role,
    name: member.name,
    staffRole: member.staffRole,
    department: member.department,
  };
}

function fromStaff(staff: Staff): DraftMember {
  return {
    system: staff.identifier.system,
    value: staff.identifier.value,
    role: null,
    name: staff.name,
    staffRole: staff.role,
    department: staff.departments.map((item) => item.name).join(', ') || null,
  };
}

export function CareTeamTab({ patient }: { patient: Patient }) {
  const visitId = patient.openVisitId;
  if (visitId === null) {
    return (
      <EmptyState>
        The patient has no open visit. The Care team tab shows the current team of the open visit only. Check in a visit first.
      </EmptyState>
    );
  }
  return <CareTeamOfVisit patient={patient} visitId={visitId} />;
}

function CareTeamOfVisit({ patient, visitId }: { patient: Patient; visitId: number }) {
  const team = useQuery({
    queryKey: queryKeys.careTeam(visitId),
    queryFn: ({ signal }) => api.careTeam(visitId, signal),
  });

  if (team.isPending) return <Loading label="Wait. The app gets the care team." />;
  if (team.isError) return <ErrorPanel error={team.error} onRetry={() => team.refetch()} />;

  const current = team.data.current;
  return (
    <div className="stack">
      {patient.permissions.manageCareTeam ? (
        <CareTeamEditor
          key={current?.assertionId ?? 'none'}
          patientId={patient.id}
          visitId={visitId}
          current={current}
        />
      ) : (
        <section className="card" aria-labelledby="team-title">
          <div className="card-header">
            <h2 id="team-title">Current care team</h2>
          </div>
          {current ? <MemberTable members={current.members.map(fromMember)} /> : <EmptyState>The open visit has no care team.</EmptyState>}
        </section>
      )}
      <CareTeamChain chain={team.data.chain} />
    </div>
  );
}

function MemberTable({ members, onRemove, added }: { members: DraftMember[]; onRemove?: (member: DraftMember) => void; added?: Set<string> }) {
  if (members.length === 0) return <EmptyState>The team has no members.</EmptyState>;
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th scope="col">Name</th>
            <th scope="col">Staff role</th>
            <th scope="col">Department</th>
            <th scope="col">Team role</th>
            {onRemove && (
              <th scope="col">
                <span className="visually-hidden">Actions</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {members.map((member) => (
            <tr key={memberId(member)}>
              <td>
                <strong>{member.name}</strong> {added?.has(memberId(member)) && <Badge tone="warn">Not saved</Badge>}
              </td>
              <td>{member.staffRole ?? '—'}</td>
              <td>{member.department ?? '—'}</td>
              <td>{member.role ?? '—'}</td>
              {onRemove && (
                <td className="cell-actions">
                  <button type="button" className="button button-small" onClick={() => onRemove(member)} aria-label={`Remove ${member.name}`}>
                    Remove
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CareTeamEditor({ patientId, visitId, current }: { patientId: number; visitId: number; current: CareTeamVersion | null }) {
  const queryClient = useQueryClient();
  const saved = useMemo(() => (current?.members ?? []).map(fromMember), [current]);
  const [draft, setDraft] = useState<DraftMember[]>(saved);
  const savedIds = new Set(saved.map(memberId));
  const draftIds = new Set(draft.map(memberId));
  const added = new Set([...draftIds].filter((id) => !savedIds.has(id)));
  const removed = saved.filter((member) => !draftIds.has(memberId(member)));
  const changed = added.size > 0 || removed.length > 0;

  const save = useMutation({
    mutationFn: (body: CareTeamBody) => api.setCareTeam(visitId, body),
    onSuccess: (team) => {
      queryClient.setQueryData(queryKeys.careTeam(visitId), team);
      for (const key of [queryKeys.patient(patientId), queryKeys.patientLists, queryKeys.charts, queryKeys.audit(patientId)]) {
        queryClient.invalidateQueries({ queryKey: key });
      }
    },
  });

  const onSave = () => {
    const members: CareTeamMemberInput[] = draft.map((member) => ({ system: member.system, value: member.value, role: member.role }));
    save.mutate({ members, name: current?.name ?? null });
  };

  return (
    <section className="card" aria-labelledby="team-edit-title">
      <div className="card-header">
        <div>
          <h2 id="team-edit-title">Current care team</h2>
          <p className="muted">Add or remove members, then select Save. Each save makes a new care-team entry that supersedes the earlier one.</p>
        </div>
      </div>
      <ErrorBanner error={save.error} onDismiss={() => save.reset()} />
      <FieldList error={save.error} />
      <MemberTable members={draft} added={added} onRemove={(member) => setDraft(draft.filter((item) => memberId(item) !== memberId(member)))} />
      {removed.length > 0 && (
        <p className="muted">
          To remove: {removed.map((member) => member.name).join(', ')}
        </p>
      )}
      <StaffFinder exclude={draftIds} onAdd={(staff) => setDraft([...draft, fromStaff(staff)])} />
      <div className="form-actions">
        <button type="button" className="button" disabled={!changed || save.isPending} onClick={() => setDraft(saved)}>
          Cancel the changes
        </button>
        <button type="button" className="button button-primary" disabled={!changed || save.isPending || draft.length === 0} onClick={onSave}>
          {save.isPending ? 'Wait…' : 'Save the care team'}
        </button>
      </div>
    </section>
  );
}

function StaffFinder({ exclude, onAdd }: { exclude: Set<string>; onAdd: (staff: Staff) => void }) {
  const [query, setQuery] = useState('');
  const q = useDebounced(query.trim(), 250);
  const staff = useQuery({
    queryKey: queryKeys.staff('', q, STAFF_RESULTS),
    queryFn: ({ signal }) => api.staff({ q, ...STAFF_RESULTS }, signal),
    enabled: q.length >= 2,
    placeholderData: keepPreviousData,
  });
  const results = (staff.data?.items ?? []).filter((item) => item.active && !exclude.has(memberId(item.identifier)));
  const more = (staff.data?.total ?? 0) > STAFF_RESULTS.limit;
  return (
    <div className="staff-finder">
      <div className="field">
        <label htmlFor="staff-finder">Add a member: find staff by name</label>
        <input
          id="staff-finder"
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="For example Nair or Okafor"
          autoComplete="off"
        />
      </div>
      {q.length >= 2 &&
        (staff.isPending ? (
          <Loading label="Wait. The app finds the staff." />
        ) : staff.isError ? (
          <ErrorBanner error={staff.error} />
        ) : results.length === 0 ? (
          <p className="muted">No staff member matches, or all matches are on the team.</p>
        ) : (
          <ul className="finder-results">
            {results.map((item) => (
              <li key={item.id}>
                <span>
                  <strong>{item.name}</strong> <span className="muted">· {item.role} · {item.departments.map((d) => d.name).join(', ') || 'No department'}</span>
                </span>
                <button
                  type="button"
                  className="button button-small"
                  onClick={() => {
                    onAdd(item);
                    setQuery('');
                  }}
                >
                  Add
                </button>
              </li>
            ))}
            {more && (
              <li className="muted small">
                The first {STAFF_RESULTS.limit} of {staff.data?.total} matches. Write more letters to find fewer staff.
              </li>
            )}
          </ul>
        ))}
    </div>
  );
}

function CareTeamChain({ chain }: { chain: CareTeamVersion[] }) {
  if (chain.length === 0) return null;
  return (
    <section className="card" aria-labelledby="team-chain-title">
      <div className="card-header">
        <div>
          <h2 id="team-chain-title">Care-team chain</h2>
          <p className="muted">Newest first. Each version supersedes the version under it. The old versions have a line through them.</p>
        </div>
      </div>
      <ol className="team-chain">
        {chain.map((version, index) => {
          const names = version.members.map((member) => member.name).join(', ') || 'No members';
          return (
            <li key={version.assertionId} className={version.isCurrent ? 'team-version team-version-current' : 'team-version'}>
              <div className="team-version-head">
                <span className="team-version-number">Version {chain.length - index}</span>
                {version.isCurrent ? <Badge tone="ok">Current</Badge> : <Badge tone="muted">Superseded</Badge>}
                {version.status !== 'active' && <Badge tone="warn">{version.status}</Badge>}
              </div>
              <div className="team-version-members">{version.isCurrent ? names : <s>{names}</s>}</div>
              <div className="muted">
                By {version.author.name} ({version.author.label}), {formatDateTime(version.assertedAt)}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
