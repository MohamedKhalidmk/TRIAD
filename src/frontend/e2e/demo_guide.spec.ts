// The Demo guide panel (src/demo/steps.json): it lists the use cases, and "Act as" sets the user and opens the page.
// These tests open only pages that write no audit record (a patient search and the directory),
// so they do not change the data or the times of the journey (hospital_visit.spec.ts).

import { readFileSync } from 'node:fs';
import { expect, test, type Locator, type Page } from '@playwright/test';
import { PATIENT_B } from './helpers';

interface UseCase {
  id: number;
  title: string;
  steps: unknown[];
  expected: string[];
}

const guide = JSON.parse(readFileSync(new URL('../src/demo/steps.json', import.meta.url), 'utf8')) as { useCases: UseCase[] };

async function openGuide(page: Page): Promise<Locator> {
  await page.getByRole('button', { name: 'Demo guide', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Demo guide' });
  await expect(dialog).toBeVisible();
  return dialog;
}

function useCase(dialog: Locator, id: number): Locator {
  return dialog.locator('.demo-step').filter({ has: dialog.page().getByText(`Use case ${id}`, { exact: true }) });
}

test('The Demo guide lists the 10 use cases of the journey, with their steps and expected results', async ({ page }) => {
  await page.goto('/');
  const dialog = await openGuide(page);
  const cases = dialog.locator('.demo-step');
  await expect(cases).toHaveCount(guide.useCases.length);
  expect(guide.useCases.map((item) => item.id)).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
  for (const item of guide.useCases) {
    const card = useCase(dialog, item.id);
    await expect(card.locator('h3')).toContainText(item.title);
    await expect(card.locator('.demo-act')).toHaveCount(item.steps.length);
    await expect(card.locator('.demo-expected li')).toHaveCount(item.expected.length);
  }
});

test('Act as: Use case 7, Step 1 opens the patient search of Jun Park with the search filled in', async ({ page }) => {
  await page.goto('/');
  const dialog = await openGuide(page);
  await useCase(dialog, 7).locator('.demo-act').first().getByRole('button', { name: 'Act as Jun Park' }).click();
  await expect(dialog).toBeHidden();
  await expect(page).toHaveURL(/\/patients\?/);
  const url = new URL(page.url());
  expect(url.searchParams.get('tab')).toBe('find');
  expect(url.searchParams.get('q')).toBe(PATIENT_B.search);
  expect(url.searchParams.get('dob')).toBe(PATIENT_B.dob);
  await expect(page.locator('.acting-as-name')).toHaveText('Jun Park');
  await expect(page.getByRole('link', { name: PATIENT_B.name })).toBeVisible();
});

test('Act as: Use case 8 opens the Staff tab of the directory as Sofia Alvarez', async ({ page }) => {
  await page.goto('/');
  const dialog = await openGuide(page);
  await useCase(dialog, 8).getByRole('button', { name: 'Act as Sofia Alvarez' }).click();
  await expect(dialog).toBeHidden();
  await expect(page).toHaveURL(/\/directory\?tab=staff$/);
  await expect(page.locator('.acting-as-name')).toHaveText('Sofia Alvarez');
  await expect(page.getByRole('tab', { name: 'Staff', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('button', { name: 'New staff member' })).toBeVisible();
});

test('The top bar names the data store, and "Show the SPARQL" shows the query of Use case 0', async ({ page }) => {
  const label = { sqlite: 'SQLite', oxigraph: 'Knowledge graph (Oxigraph)', virtuoso: 'Knowledge graph (Virtuoso)' }[
    process.env.TRIAD_E2E_STORE ?? 'sqlite'
  ];
  await page.goto('/');
  await expect(page.locator('.store-badge')).toHaveText(label ?? 'SQLite');
  const dialog = await openGuide(page);
  const queries = useCase(dialog, 0).locator('.demo-queries');
  await expect(queries.locator('.demo-query')).toHaveCount(2);
  // "Run in Virtuoso" shows only for the store Virtuoso.
  await expect(queries.getByRole('link', { name: 'Run in Virtuoso' })).toHaveCount(process.env.TRIAD_E2E_STORE === 'virtuoso' ? 2 : 0);
  await queries.getByRole('button', { name: 'Show the SPARQL' }).first().click();
  await expect(queries.locator('pre')).toContainText('PREFIX triad:');
  await expect(queries.locator('pre')).toContainText('# Q2.');
});
