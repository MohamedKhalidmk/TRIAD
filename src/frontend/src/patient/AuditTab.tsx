// The Audit tab: who opened or changed the record of this patient (GET /api/patients/{id}/audit).
// A denied attempt has a red row.

import { useQuery } from '@tanstack/react-query';
import { api, queryKeys } from '../api/endpoints';
import type { Patient, UserView } from '../api/types';
import { Badge } from '../components/Badges';
import { EmptyState, ErrorPanel, Loading } from '../components/ErrorView';
import { formatDateTime } from '../lib/dates';

export function AuditTab({ patient, user }: { patient: Patient; user: UserView }) {
  const audit = useQuery({
    queryKey: queryKeys.audit(patient.id),
    queryFn: ({ signal }) => api.audit(patient.id, signal),
  });
  if (audit.isPending) return <Loading label="Wait. The app gets the audit log." />;
  if (audit.isError) return <ErrorPanel error={audit.error} onRetry={() => audit.refetch()} />;
  const denied = audit.data.filter((event) => event.outcome === 'Denied').length;
  return (
    <div className="stack">
      <div className="toolbar">
        <div className="toolbar-title">
          <h2>{user.role === 'Patient' ? 'Who opened my record' : 'Audit log'}</h2>
          <p className="muted">
            Newest first. {audit.data.length} records{denied > 0 ? `, ${denied} denied` : ''}.
          </p>
        </div>
        <button type="button" className="button" onClick={() => audit.refetch()} disabled={audit.isFetching}>
          {audit.isFetching ? 'Wait…' : 'Reload'}
        </button>
      </div>
      {audit.data.length === 0 ? (
        <EmptyState>The audit log has no records for this patient.</EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="table table-audit">
            <thead>
              <tr>
                <th scope="col">Time</th>
                <th scope="col">Outcome</th>
                <th scope="col">Action</th>
                <th scope="col">User</th>
                <th scope="col">Path</th>
              </tr>
            </thead>
            <tbody>
              {audit.data.map((event) => (
                <tr key={event.id} className={event.outcome === 'Denied' ? 'row-denied' : undefined}>
                  <td className="nowrap">{formatDateTime(event.at)}</td>
                  <td>{event.outcome === 'Denied' ? <Badge tone="danger">Denied</Badge> : <Badge tone="ok">Allowed</Badge>}</td>
                  <td>
                    {event.action}
                    {event.chatTurnId !== null && <span className="muted"> (chat turn {event.chatTurnId})</span>}
                  </td>
                  <td>
                    <strong>{event.actorName ?? event.actorKey}</strong>
                    <div className="muted small">
                      {event.actorRole} · {event.actorKey}
                    </div>
                  </td>
                  <td>
                    <code className="path">{event.path}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
