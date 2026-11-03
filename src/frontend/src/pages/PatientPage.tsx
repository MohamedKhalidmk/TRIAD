// /patients/:id: the patient page.
// Left pane: the tabs Chart, Visit, Care team and Audit, as the role and Patient.permissions allow.
// Right pane: the Care Assistant (not for the MOA).
// The MOA sees the demographics, the Visit tab and the Care team tab only: no chart call and no chat.
// A nurse or a doctor always gets the Chart tab. If they are not on the care team, the chart call gives the 403 panel.

import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { ApiRequestError } from '../api/client';
import { api, queryKeys } from '../api/endpoints';
import type { AssertionView, Chart, Patient, UserView } from '../api/types';
import type { PatientTab } from '../app/routes';
import { useCurrentUser } from '../app/session';
import { CareAssistant } from '../chat/CareAssistant';
import { ErrorPanel, Loading } from '../components/ErrorView';
import { TabList, TabPanel, useTabParam, type TabItem } from '../components/Tabs';
import { AuditTab } from '../patient/AuditTab';
import { CareTeamTab } from '../patient/CareTeamTab';
import { ChartTab } from '../patient/ChartTab';
import { PatientHeader } from '../patient/PatientHeader';
import { RecordFormDialog } from '../patient/RecordForm';
import type { RecordSeed } from '../patient/recordModel';
import { VisitTab } from '../patient/VisitTab';

export function PatientPage() {
  const params = useParams();
  const patientId = Number(params.id);
  const valid = Number.isInteger(patientId) && patientId > 0;
  const user = useCurrentUser();
  const patient = useQuery({
    queryKey: queryKeys.patient(patientId),
    queryFn: ({ signal }) => api.patient(patientId, signal),
    enabled: valid,
  });

  if (!valid) return <ErrorPanel error={new ApiRequestError(404, 'not_found', 'The link has no correct patient id.')} />;
  if (patient.isPending) return <Loading label="Wait. The app gets the patient." />;
  if (patient.isError) return <ErrorPanel error={patient.error} onRetry={() => patient.refetch()} />;
  return <PatientView patient={patient.data} user={user} />;
}

export function patientTabs(user: UserView, patient: Patient): TabItem<PatientTab>[] {
  const permissions = patient.permissions;
  const tabs: TabItem<PatientTab>[] = [];
  const clinician = user.role === 'Nurse' || user.role === 'Doctor';
  if (user.role !== 'MOA') tabs.push({ id: 'chart', label: user.role === 'Patient' ? 'My record' : 'Chart' });
  // A nurse or a doctor who is not on the care team sees the Chart tab only (it shows the 403 panel).
  if (!clinician || permissions.viewChart) {
    tabs.push({ id: 'visit', label: 'Visit' });
    tabs.push({ id: 'care-team', label: 'Care team' });
  }
  if (permissions.viewAudit && user.role !== 'MOA') tabs.push({ id: 'audit', label: 'Audit' });
  return tabs;
}

function PatientView({ patient, user }: { patient: Patient; user: UserView }) {
  const queryClient = useQueryClient();
  const tabs = patientTabs(user, patient);
  const [tab, setTab] = useTabParam(tabs);
  const [recordSeed, setRecordSeed] = useState<RecordSeed | null>(null);
  const showChat = user.role !== 'MOA' && patient.permissions.chat;

  // The record form lists the current items of the chart that is in the cache. It does not read the chart again.
  const currentItems = (): AssertionView[] => {
    const chart =
      queryClient.getQueryData<Chart>(queryKeys.chart(patient.id, false)) ??
      queryClient.getQueryData<Chart>(queryKeys.chart(patient.id, true));
    return (chart?.items ?? []).filter((item) => item.isCurrent);
  };

  return (
    <div className="page patient-page">
      <PatientHeader patient={patient} user={user} />
      <div className={showChat ? 'patient-layout patient-layout-two' : 'patient-layout'}>
        <section className="pane pane-main" aria-label="Patient record">
          <TabList tabs={tabs} selected={tab} onSelect={setTab} label="Patient sections" idPrefix="patient" />
          <TabPanel idPrefix="patient" selected={tab}>
            {tab === 'chart' && <ChartTab patient={patient} user={user} onRecord={setRecordSeed} />}
            {tab === 'visit' && <VisitTab patient={patient} user={user} onRecord={setRecordSeed} />}
            {tab === 'care-team' && <CareTeamTab patient={patient} />}
            {tab === 'audit' && <AuditTab patient={patient} user={user} />}
          </TabPanel>
        </section>
        {showChat && (
          <aside className="pane pane-chat" aria-label="Care Assistant">
            <CareAssistant patient={patient} user={user} />
          </aside>
        )}
      </div>
      <RecordFormDialog
        patient={patient}
        user={user}
        seed={recordSeed}
        currentItems={recordSeed ? currentItems() : []}
        onClose={() => setRecordSeed(null)}
      />
    </div>
  );
}
