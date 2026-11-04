// The app: the providers, the top bar, the routes, the user picker and the Demo guide.

import { useState } from 'react';
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Link, Route, Routes } from 'react-router-dom';
import { isAbortError, isApiError } from '../api/client';
import { ErrorPanel, Loading } from '../components/ErrorView';
import { TopBar } from '../components/TopBar';
import { UserPickerDialog } from '../components/UserPicker';
import { DemoGuide } from '../demo/DemoGuide';
import { DirectoryPage } from '../pages/DirectoryPage';
import { HomePage } from '../pages/HomePage';
import { PatientPage } from '../pages/PatientPage';
import { PatientsPage } from '../pages/PatientsPage';
import { WelcomePage } from '../pages/WelcomePage';
import { AUDITED_READS, refreshClock } from './clock';
import { ROUTES } from './routes';
import { ActingUserProvider, useActingUser } from './session';

function makeQueryClient(): QueryClient {
  const client: QueryClient = new QueryClient({
    // Each write moves the time of the server on (doc/api.md section 1.3). A chart, chain or audit read is also a
    // write (an audit record). So after these requests the app reads GET /api/health again, and the clock of the
    // top bar shows the new time. The chat turns call refreshClock() themselves.
    queryCache: new QueryCache({
      onSuccess: (_data, query) => {
        if (AUDITED_READS.includes(String(query.queryKey[0]))) refreshClock(client);
      },
    }),
    mutationCache: new MutationCache({
      onSuccess: () => refreshClock(client),
    }),
    defaultOptions: {
      queries: {
        // Each chart read writes an audit record. So the app does not read again when the window gets focus.
        refetchOnWindowFocus: false,
        staleTime: 15_000,
        // Do not repeat a request that the server refused (4xx) or that the app stopped. Repeat a network error one time.
        retry: (count, error) =>
          !isAbortError(error) && !(isApiError(error) && error.status >= 400 && error.status < 500) && count < 1,
      },
      mutations: { retry: false },
    },
  });
  return client;
}

export function App() {
  const [queryClient] = useState(makeQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ActingUserProvider>
          <Shell />
        </ActingUserProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

function Shell() {
  const { status, error, userKey, epoch, openPicker } = useActingUser();
  const [guideOpen, setGuideOpen] = useState(false);
  const openGuide = () => setGuideOpen(true);

  let content;
  if (status === 'none') content = <WelcomePage onOpenDemoGuide={openGuide} />;
  else if (status === 'loading') content = <Loading label="Wait. The app gets the user." />;
  else if (status === 'unknown')
    content = (
      <section className="panel-message" role="alert">
        <h2>Select a user</h2>
        <p>
          The server does not know the user <code>{userKey}</code>. The database can be new. Select a user to continue.
        </p>
        <button type="button" className="button button-primary" onClick={() => openPicker()}>
          Select a user
        </button>
      </section>
    );
  else if (status === 'error') content = <ErrorPanel error={error} onRetry={() => window.location.reload()} />;
  else
    content = (
      <Routes>
        <Route path={ROUTES.home.path} element={<HomePage />} />
        <Route path={ROUTES.patients.path} element={<PatientsPage />} />
        <Route path={ROUTES.patient.path} element={<PatientPage />} />
        <Route path={ROUTES.directory.path} element={<DirectoryPage />} />
        <Route
          path="*"
          element={
            <section className="panel-message">
              <h2>Page not found</h2>
              <p>The app has no page at this address.</p>
              <Link to={ROUTES.home.path} className="button">
                Go to the home page
              </Link>
            </section>
          }
        />
      </Routes>
    );

  return (
    <div className="app">
      <a href="#main" className="skip-link">
        Skip to the content
      </a>
      <TopBar onOpenDemoGuide={openGuide} />
      <main id="main" className="main" key={`${userKey ?? 'none'}:${epoch}`}>
        {content}
      </main>
      <UserPickerDialog />
      <DemoGuide open={guideOpen} onClose={() => setGuideOpen(false)} />
    </div>
  );
}
