// The directory of the front desk (MOA): INSERT, UPDATE and DELETE in the UI, the 409 messages and the pager.
// These tests do not use the rows of the hospital-visit journey (hospital_visit.spec.ts), so the two files
// can run in any order on the same database. The directory has no audit records, so these tests do not change
// the times of the journey.

import { expect, test, type Locator, type Page } from '@playwright/test';
import { openAs, USERS } from './helpers';

function rowOf(page: Page, name: string): Locator {
  return page.locator('tbody tr').filter({ hasText: name });
}

async function openTab(page: Page, name: string): Promise<void> {
  await page.getByRole('tab', { name, exact: true }).click();
  await expect(page.getByRole('tab', { name, exact: true })).toHaveAttribute('aria-selected', 'true');
}

/** Selects Delete on a row, then Delete in the dialog. Gives the dialog. */
async function deleteRow(page: Page, name: string, dialogTitle: string): Promise<Locator> {
  await page.getByRole('button', { name: `Delete ${name}`, exact: true }).click();
  const dialog = page.getByRole('dialog', { name: dialogTitle });
  await dialog.getByRole('button', { name: 'Delete', exact: true }).click();
  return dialog;
}

/** The server stops the delete with a 409. The dialog shows the message, and the row stays. */
async function expectConflict(page: Page, dialog: Locator, message: string, name: string): Promise<void> {
  await expect(dialog.locator('.banner-conflict')).toHaveText(`Conflict. ${message}`);
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(rowOf(page, name).first()).toBeVisible();
}

test.beforeEach(async ({ page }) => {
  await openAs(page, USERS.sofia, '/directory', 'staff');
  await expect(page.getByRole('heading', { name: 'Directory' })).toBeVisible();
});

test('UPDATE: the front desk changes the phone number and the email of a staff member', async ({ page }) => {
  await page.getByLabel('Find staff by name').fill('Aisha Ortega');
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await page.getByRole('button', { name: 'Edit Aisha Ortega', exact: true }).click();
  const edit = page.getByRole('dialog', { name: 'Edit Aisha Ortega' });
  await expect(edit.getByLabel('Name')).toHaveValue('Aisha Ortega');
  await edit.getByLabel('Phone number').fill('+1-508-555-3010');
  await edit.getByLabel('Email').fill('a.ortega@triad-general.example');
  await edit.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(edit).toBeHidden();
  const row = rowOf(page, 'Aisha Ortega');
  await expect(row).toContainText('+1-508-555-3010');
  await expect(row).toContainText('a.ortega@triad-general.example');

  // The change is in the database: a new page load shows it.
  await page.reload();
  await page.getByLabel('Find staff by name').fill('Aisha Ortega');
  await expect(rowOf(page, 'Aisha Ortega')).toContainText('+1-508-555-3010');
});

test('INSERT and DELETE: the front desk adds a location, then deletes it because no visit uses it', async ({ page }) => {
  await openTab(page, 'Locations');
  await page.getByRole('button', { name: 'New location' }).click();
  const create = page.getByRole('dialog', { name: 'New location' });
  await create.getByLabel('Name', { exact: true }).fill('E2E Test Room');
  await create.getByLabel('Identifier (optional)').fill('E2E-ROOM');
  await create.getByLabel('Department').selectOption({ label: 'Urgent Care' });
  await create.getByLabel('Physical type (optional)').fill('Room');
  await create.getByRole('button', { name: 'Create', exact: true }).click();
  await expect(create).toBeHidden();
  const row = rowOf(page, 'E2E Test Room');
  await expect(row).toContainText('E2E-ROOM');
  await expect(row).toContainText('Urgent Care');
  await expect(row).toContainText('Not used');

  const dialog = await deleteRow(page, 'E2E Test Room', 'Delete a location');
  await expect(dialog).toBeHidden();
  await expect(row).toHaveCount(0);
  await page.reload();
  await expect(rowOf(page, 'ER Waiting')).toBeVisible();
  await expect(rowOf(page, 'E2E Test Room')).toHaveCount(0);
});

test('409: the server stops a delete when other rows use the row', async ({ page }) => {
  await test.step('a location that a visit used', async () => {
    await openTab(page, 'Locations');
    await expect(rowOf(page, 'Emergency Unit')).toContainText('Used by a visit');
    const dialog = await deleteRow(page, 'Emergency Unit', 'Delete a location');
    await expectConflict(page, dialog, 'A visit used the location. You cannot delete it.', 'Emergency Unit');
  });
  await test.step('a department that has staff', async () => {
    await openTab(page, 'Departments');
    const dialog = await deleteRow(page, 'Urgent Care', 'Delete a department');
    await expectConflict(page, dialog, 'The department has staff. You cannot delete it.', 'Urgent Care');
  });
  await test.step('a staff member who works in a department', async () => {
    await openTab(page, 'Staff');
    await page.getByLabel('Find staff by name').fill('Aisha Ortega');
    await expect(page.locator('tbody tr')).toHaveCount(1);
    const dialog = await deleteRow(page, 'Aisha Ortega', 'Delete a staff member');
    await expectConflict(page, dialog, 'The staff member works in a department. You cannot delete the staff member.', 'Aisha Ortega');
  });
});

test('Pager: the Staff tab shows 25 of the 292 staff on a page, and Next shows the next 25', async ({ page }) => {
  const pager = page.getByRole('navigation', { name: 'Pages of the staff list' });
  const rows = page.locator('tbody tr');
  await expect(pager.locator('.pager-range')).toHaveText('1–25 of 292');
  await expect(rows).toHaveCount(25);
  await expect(pager.getByRole('button', { name: 'Previous' })).toBeDisabled();
  const firstName = await rows.first().locator('strong').textContent();

  await pager.getByRole('button', { name: 'Next' }).click();
  await expect(pager.locator('.pager-range')).toHaveText('26–50 of 292');
  await expect(rows).toHaveCount(25);
  await expect(page.locator('.table-wrap.paged-busy')).toHaveCount(0);
  await expect(rows.first().locator('strong')).not.toHaveText(firstName ?? '');
  await expect(pager.getByRole('button', { name: 'Previous' })).toBeEnabled();

  await pager.getByRole('button', { name: 'Previous' }).click();
  await expect(pager.locator('.pager-range')).toHaveText('1–25 of 292');
  await expect(rows.first().locator('strong')).toHaveText(firstName ?? '');
});
