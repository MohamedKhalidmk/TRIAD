// "Delete patient" in the patient header (manual 5.4: a form to delete a person). Only the MOA sees the button.
// The tests do not use the patients of the hospital-visit journey (Patient A and Patient B), so the audit logs of
// the journey stay the same. The file runs after hospital_visit.spec.ts (the tests run in the order of the files).

import { expect, test, type Page } from '@playwright/test';
import { openAs, patientIdOf, USERS } from './helpers';

/** Opens a patient as the front desk: Find a patient, then the row of the name. */
async function openPatient(page: Page, search: string, name: string): Promise<void> {
  await openAs(page, USERS.sofia, '/patients');
  await page.getByRole('tab', { name: 'Find a patient', exact: true }).click();
  const field = page.getByLabel('Name (or part of the name)');
  await field.fill(search);
  await field.press('Enter');
  await page.locator('tbody tr').filter({ hasText: name }).getByRole('link', { name }).click();
  await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible();
}

test('DELETE: the front desk deletes a patient with no visit, after a confirmation', async ({ page }) => {
  await openAs(page, USERS.sofia, '/patients');
  await page.getByRole('button', { name: 'Register a patient' }).click();
  const register = page.getByRole('dialog', { name: 'Register a patient' });
  await register.getByLabel('Full name').fill('E2E Delete Patient');
  await register.getByLabel('Date of birth').fill('1991-04-15');
  await register.getByRole('button', { name: 'Register', exact: true }).click();
  await expect(page).toHaveURL(/\/patients\/\d+/);
  const id = Number(/\/patients\/(\d+)/.exec(page.url())![1]);
  await expect(page.getByRole('heading', { name: 'E2E Delete Patient', level: 1 })).toBeVisible();

  // Cancel keeps the patient.
  await page.getByRole('button', { name: 'Delete patient' }).click();
  const dialog = page.getByRole('dialog', { name: 'Delete a patient' });
  await expect(dialog).toContainText('E2E Delete Patient');
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole('heading', { name: 'E2E Delete Patient', level: 1 })).toBeVisible();

  // Delete removes the patient and goes back to the patient lists.
  await page.getByRole('button', { name: 'Delete patient' }).click();
  await dialog.getByRole('button', { name: 'Delete', exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page).toHaveURL(/\/patients$/);
  const response = await page.request.get(`/api/patients/${id}`, { headers: { 'X-Triad-User': USERS.sofia } });
  expect(response.status()).toBe(404);
});

test('409: the front desk cannot delete a patient who has visits', async ({ page }) => {
  await openPatient(page, 'Brekke496', 'Abram53 Brekke496');
  await page.getByRole('button', { name: 'Delete patient' }).click();
  const dialog = page.getByRole('dialog', { name: 'Delete a patient' });
  await dialog.getByRole('button', { name: 'Delete', exact: true }).click();
  await expect(dialog.locator('.banner-conflict')).toHaveText('Conflict. The patient has visits. You cannot delete the patient.');
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole('heading', { name: 'Abram53 Brekke496', level: 1 })).toBeVisible();
});

test('Only the MOA sees "Delete patient"', async ({ page, request }) => {
  const patientA = await patientIdOf(request, USERS.patientA);
  await openAs(page, USERS.okafor, `/patients/${patientA}`);
  await expect(page.getByRole('heading', { name: 'Elena Marsh', level: 1 })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Edit details' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Delete patient' })).toHaveCount(0);
});
