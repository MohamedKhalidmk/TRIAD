// The first page when no user is selected.

import { UserPickerPanel } from '../components/UserPicker';

export function WelcomePage({ onOpenDemoGuide }: { onOpenDemoGuide: () => void }) {
  return (
    <div className="welcome">
      <section className="welcome-intro">
        <h1>TRIAD General Hospital</h1>
        <p>
          This prototype shows a hospital visit with the TRIAD Care Assistant. Each fact in the record is an
          assertion with an author. A new assertion supersedes the old one, so the assistant uses the current fact.
        </p>
        <p>The app has no login. Select a user type and a user to start. All data is synthetic.</p>
        <button type="button" className="button" onClick={onOpenDemoGuide}>
          Open the Demo guide
        </button>
      </section>
      <section className="card welcome-picker" aria-labelledby="welcome-picker-title">
        <h2 id="welcome-picker-title">Select a user</h2>
        <UserPickerPanel initialRole="Doctor" />
      </section>
    </div>
  );
}
