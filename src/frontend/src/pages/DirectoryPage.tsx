// /directory: departments, locations, staff and medications.
// All staff can read the directory. Only the MOA can create, change and delete.

import type { DirectoryTab } from '../app/routes';
import { useCurrentUser } from '../app/session';
import { TabList, TabPanel, useTabParam, type TabItem } from '../components/Tabs';
import { DepartmentsTab } from '../directory/DepartmentsTab';
import { LocationsTab } from '../directory/LocationsTab';
import { MedicationsTab } from '../directory/MedicationsTab';
import { StaffTab } from '../directory/StaffTab';

const TABS: TabItem<DirectoryTab>[] = [
  { id: 'departments', label: 'Departments' },
  { id: 'locations', label: 'Locations' },
  { id: 'staff', label: 'Staff' },
  { id: 'medications', label: 'Medications' },
];

export function DirectoryPage() {
  const user = useCurrentUser();
  const [tab, setTab] = useTabParam(TABS);
  if (user.role === 'Patient') {
    return (
      <section className="panel-message" role="alert">
        <h2>The directory is for staff</h2>
        <p>A patient cannot open the directory. Open “My record” in the top bar.</p>
      </section>
    );
  }
  const canWrite = user.role === 'MOA';
  return (
    <div className="page">
      <div className="page-header">
        <h1>Directory</h1>
        <p className="muted">
          {canWrite
            ? 'You can create, change and delete the rows. The server stops a delete if other rows use the row.'
            : 'You can read the directory. Only the front desk (MOA) can change it.'}
        </p>
      </div>
      <TabList tabs={TABS} selected={tab} onSelect={setTab} label="Directory sections" idPrefix="directory" />
      <TabPanel idPrefix="directory" selected={tab}>
        {tab === 'departments' && <DepartmentsTab canWrite={canWrite} />}
        {tab === 'locations' && <LocationsTab canWrite={canWrite} />}
        {tab === 'staff' && <StaffTab canWrite={canWrite} />}
        {tab === 'medications' && <MedicationsTab canWrite={canWrite} />}
      </TabPanel>
    </div>
  );
}
