// "/" sends each role to its home page.
// Patient: their own patient page ("My record"). MOA: the front desk. Nurse and doctor: "My patients".

import { Navigate } from 'react-router-dom';
import { homePath, ROUTES } from '../app/routes';
import { useCurrentUser } from '../app/session';
import { ErrorPanel } from '../components/ErrorView';
import { ApiRequestError } from '../api/client';

export function HomePage() {
  const user = useCurrentUser();
  const to = homePath(user);
  if (to === ROUTES.home.path) {
    return <ErrorPanel error={new ApiRequestError(404, 'not_found', 'This patient user has no patient record.')} />;
  }
  return <Navigate to={to} replace />;
}
