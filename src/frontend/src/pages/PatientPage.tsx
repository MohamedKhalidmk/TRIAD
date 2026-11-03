// /patients/:id: the patient page.
// Left pane: the tabs Chart, Visit, Care team and Audit, as the role and Patient.permissions allow.
// Right pane: the Care Assistant (not for the MOA).
// On a narrow screen (1100 px or less) the page has one column, and the Care Assistant is the last tab.
// The chat stays mounted: when its tab is not selected, it is hidden. So the open chat and the text in the box stay.
// The MOA sees the demographics, the Visit tab and the Care team tab only: no chart call and no chat.
// A nurse or a doctor always gets the Chart tab. If they are not on the care team, the chart call gives the 403 panel.

import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useParams, useSearchParams } from 'react-router-dom';
import { ApiRequestError } from '../api/client';
import { api, queryKeys } from '../api/endpoints';
import type { Patient, UserView } from '../api/types';
import type { PatientTab } from '../app/routes';
import { useCurrentUser } from '../app/session';
import { CareAssistant } from '../chat/CareAssistant';
import { ErrorPanel, Loading } from '../components/ErrorView';
import { TabList, TabPanel, useTabParam, type TabItem } from '../components/Tabs';
import { useMediaQuery } from '../lib/useMediaQuery';
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

/** The width of the one-column layout. It is the same as "@media (max-width: 1100px)" in styles.css. */
const NARROW_LAYOUT = '(max-width: 1100px)';
const CHAT_PANEL_ID = 'patient-panel-assistant';

/** The tabs of the patient page. "withAssistant" adds the Care Assistant tab (narrow screens only). */
export function patientTabs(user: UserView, patient: Patient, withAssistant = false): TabItem<PatientTab>[] {
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
  if (withAssistant) tabs.push({ id: 'assistant', label: 'Care Assistant', panelId: CHAT_PANEL_ID });
  return tabs;
}

function PatientView({ patient, user }: { patient: Patient; user: UserView }) {
  const showChat = user.role !== 'MOA' && patient.permissions.chat;
  const narrow = useMediaQuery(NARROW_LAYOUT);
  const chatTab = showChat && narrow;
  const tabs = patientTabs(user, patient, chatTab);
  const [tab, setTab] = useTabParam(tabs);
  const chatSelected = chatTab && tab === 'assistant';
  const [recordSeed, setRecordSeed] = useState<RecordSeed | null>(null);
  const chatRef = useRef<HTMLElement>(null);
  const requestedTab = useSearchParams()[0].get('tab');

  // A wide screen has no Care Assistant tab: the chat is in the right pane. So select the first tab (the chart).
  // setTab is not in the list of the effect: it is a new function on each render.
  const firstTab = tabs[0]?.id;
  useEffect(() => {
    if (!chatTab && requestedTab === 'assistant' && firstTab) setTab(firstTab);
  }, [chatTab, requestedTab, firstTab]);

  // When the chat tab opens, move the chat to the top of the screen and show the newest message.
  useEffect(() => {
    const pane = chatRef.current;
    if (!chatSelected || !pane) return;
    const messages = pane.querySelector('.assistant-messages');
    if (messages) messages.scrollTop = messages.scrollHeight;
    pane.scrollIntoView({ block: 'start' });
  }, [chatSelected]);

  return (
    <div className="page patient-page">
      <PatientHeader patient={patient} user={user} />
      <div className={showChat ? 'patient-layout patient-layout-two' : 'patient-layout'}>
        <section className={chatSelected ? 'pane pane-main pane-main-tabs-only' : 'pane pane-main'} aria-label="Patient record">
          <TabList tabs={tabs} selected={tab} onSelect={setTab} label="Patient sections" idPrefix="patient" />
          <TabPanel idPrefix="patient" selected={tab} hidden={chatSelected}>
            {tab === 'chart' && <ChartTab patient={patient} user={user} onRecord={setRecordSeed} />}
            {tab === 'visit' && <VisitTab patient={patient} user={user} onRecord={setRecordSeed} />}
            {tab === 'care-team' && <CareTeamTab patient={patient} />}
            {tab === 'audit' && <AuditTab patient={patient} user={user} />}
          </TabPanel>
        </section>
        {showChat && (
          <aside
            ref={chatRef}
            className="pane pane-chat"
            aria-label="Care Assistant"
            id={CHAT_PANEL_ID}
            role={chatTab ? 'tabpanel' : undefined}
            aria-labelledby={chatTab ? 'patient-tab-assistant' : undefined}
            hidden={chatTab && !chatSelected}
          >
            <CareAssistant patient={patient} user={user} />
          </aside>
        )}
      </div>
      <RecordFormDialog
        patient={patient}
        user={user}
        seed={recordSeed}
        onClose={() => setRecordSeed(null)}
      />
    </div>
  );
}
