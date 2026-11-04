// The hospital-visit journey of USER_FLOWS.md section 3 (Use case 0 to Use case 9), in the real UI.
// Each use case uses the users and the pages of the Demo guide (src/demo/steps.json).
// src/backend/tests/integration/test_hospital_visit.py does the same journey through the API.
//
// The use cases share one database, so they run in the order of this file (serial mode).
// If one use case fails, Playwright skips the use cases after it.
// The tests also take the panel screenshots of the report (doc/screenshots/, see helpers.ts).

import { expect, test, type Locator, type Page } from '@playwright/test';
import { openAs, panel, PATIENT_B, patientIdOf, showChatFrom, USERS, windowShot } from './helpers';

test.describe.configure({ mode: 'serial' });

let patientA = 0;
let patientB = 0;

test.beforeAll(async ({ playwright, baseURL }) => {
  const request = await playwright.request.newContext({ baseURL });
  patientA = await patientIdOf(request, USERS.patientA);
  patientB = await patientIdOf(request, USERS.patientB);
  await request.dispose();
});

const WIDE = { width: 1440, height: 900 };
const OLD_WORDS = /asthma|inhaler|albuterol|salbutamol/i;
const PRESETS = {
  asthma: 'http://snomed.info/sct|195967001',
  heartFailure: 'http://snomed.info/sct|84114007',
  salbutamol: 'http://www.nlm.nih.gov/research/umls/rxnorm|745752',
  furosemide: 'http://www.nlm.nih.gov/research/umls/rxnorm|313988',
  troponin: 'http://loinc.org|89579-7',
};

// ----- Steps that the use cases share -----

function patientPage(id: number): string {
  return `/patients/${id}`;
}

async function selectTab(page: Page, name: string): Promise<void> {
  await page.getByRole('tab', { name, exact: true }).click();
  await expect(page.getByRole('tab', { name, exact: true })).toHaveAttribute('aria-selected', 'true');
}

/** Sends a question or a fact to the Care Assistant. Gives the new assistant turn. */
async function ask(page: Page, text: string): Promise<Locator> {
  const turns = page.locator('.assistant .assistant-turn');
  const before = await turns.count();
  const box = page.getByRole('textbox', { name: 'Message to the Care Assistant' });
  await box.fill(text);
  await box.press('Enter');
  await expect(turns).toHaveCount(before + 1, { timeout: 20_000 });
  await expect(page.locator('.assistant .bubble-typing')).toHaveCount(0);
  return turns.nth(before);
}

function messages(page: Page): Locator {
  return page.locator('.assistant .assistant-messages');
}

/** The question bubble of the user that is before an assistant turn. */
function questionOf(page: Page, text: string): Locator {
  return page.locator('.assistant .bubble-row-user').filter({ hasText: text }).last();
}

/**
 * Writes a search in "Find in the chart" and waits for the result. The chart asks the server 300 ms after the
 * last key. If the same search is in the cache of the app (15 s), the app sends no request: then wait 2 s only.
 */
async function findInChart(page: Page, text: string): Promise<void> {
  const answer = page
    .waitForResponse((response) => response.url().includes('/chart') && new URL(response.url()).searchParams.get('q') === text, {
      timeout: 2_000,
    })
    .catch(() => null);
  await page.getByLabel('Find in the chart').fill(text);
  await answer;
  await expect(page.locator('.chart .paged-busy')).toHaveCount(0);
}

function chartItem(page: Page, text: string | RegExp): Locator {
  return page.locator('.chart .chart-item').filter({ hasText: text }).first();
}

/** Opens the record form from the chart toolbar. */
async function openRecordForm(page: Page): Promise<Locator> {
  await page.getByRole('button', { name: 'Record', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Record' });
  await expect(dialog).toBeVisible();
  return dialog;
}

/** Selects Record in a record form and waits until the form closes. */
async function submitRecord(dialog: Locator, label = 'Record'): Promise<void> {
  await dialog.getByRole('button', { name: label, exact: true }).click();
  await expect(dialog).toBeHidden();
}

interface RowValues {
  category?: string;
  preset?: string;
  intent?: string;
  verification?: string;
  statement?: string;
  details?: Record<string, string>;
}

/** Fills one assertion row of the record form. */
async function fillRow(dialog: Locator, values: RowValues): Promise<void> {
  if (values.category) await dialog.getByLabel('Category', { exact: true }).selectOption(values.category);
  if (values.preset) {
    // The presets load from GET /api/codes. Wait for the option, then select it.
    const preset = dialog.getByLabel('Preset code', { exact: true });
    await expect(preset.locator(`option[value="${values.preset}"]`)).toHaveCount(1);
    await preset.selectOption(values.preset);
  }
  for (const [label, value] of Object.entries(values.details ?? {})) {
    const field = dialog.getByLabel(label, { exact: true });
    if ((await field.evaluate((element) => element.tagName)) === 'SELECT') await field.selectOption(value);
    else await field.fill(value);
  }
  if (values.intent) await dialog.getByLabel('Intent', { exact: true }).selectOption(values.intent);
  if (values.verification) await dialog.getByLabel('Verification', { exact: true }).selectOption(values.verification);
  if (values.statement !== undefined) await dialog.getByLabel('Statement', { exact: true }).fill(values.statement);
}

/** Opens the chain of a chart item. Gives the chain dialog. */
async function openChain(page: Page, item: Locator): Promise<Locator> {
  await item.getByRole('button', { name: /Show the chain|Supersedes \d+/ }).click();
  const dialog = page.getByRole('dialog', { name: 'Assertion chain' });
  await expect(dialog.locator('.chain-list > li').first()).toBeVisible();
  return dialog;
}

async function closeDialog(dialog: Locator): Promise<void> {
  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(dialog).toBeHidden();
}

/** Adds staff members to the draft care team with the staff finder. */
async function addMembers(page: Page, ...names: string[]): Promise<void> {
  const finder = page.getByLabel('Add a member: find staff by name');
  for (const name of names) {
    await finder.fill(name.split(' ').at(-1) as string);
    const result = page.locator('.finder-results li').filter({ hasText: name });
    await result.getByRole('button', { name: 'Add', exact: true }).click();
    await expect(page.getByRole('row').filter({ hasText: name })).toBeVisible();
  }
}

/** Saves the care team and waits for the new version in the chain. */
async function saveCareTeam(page: Page, versions: number): Promise<void> {
  await page.getByRole('button', { name: 'Save the care team' }).click();
  await expect(page.locator('.team-chain .team-version')).toHaveCount(versions);
}

/** Moves the patient from the current location to a new location (Visit tab). */
async function moveTo(page: Page, from: string, to: string): Promise<void> {
  const openVisit = page.getByRole('region', { name: 'Open visit' });
  await openVisit.getByLabel(`Move from ${from} to`).selectOption({ label: to });
  await openVisit.getByRole('button', { name: 'Move', exact: true }).click();
  await expect(openVisit.locator('.location-current .location-name')).toHaveText(to);
}

async function findPatientB(page: Page): Promise<void> {
  await page.getByLabel('Name (or part of the name)').fill(PATIENT_B.search);
  await page.getByLabel('Date of birth').fill(PATIENT_B.dob);
  await page.getByRole('button', { name: 'Find', exact: true }).click();
  const results = page.locator('.table tbody tr');
  await expect(results).toHaveCount(1);
  await expect(results).toContainText(PATIENT_B.name);
  await expect(page.locator('.pager-range')).toHaveText('1–1 of 1');
  await page.getByRole('link', { name: PATIENT_B.name }).click();
  await expect(page).toHaveURL(new RegExp(`/patients/${patientB}(\\?|$)`));
}

// ----- The use cases -----

test('Use case 0: the doctor asks about the penicillin allergy of Patient A (the 3MT slide)', async ({ page }) => {
  await openAs(page, USERS.okafor, patientPage(patientA), 'chart');
  await expect(page.getByRole('heading', { name: 'Elena Marsh' })).toBeVisible();

  const turn = await ask(page, 'Is she allergic to penicillin?');
  await expect(turn.locator('.bubble-assistant')).toHaveText('No. A physician ruled it out with an allergy test on Oct 2, 2026.');
  const cards = turn.locator('.evidence-card');
  await expect(cards).toHaveCount(1);
  const card = cards.first();
  await expect(card.locator('.evidence-main')).toContainText('Physician, Oct 2, 2026');
  await expect(card.locator('.badges')).toContainText('Refuted');
  // The two superseded assertions have a line through them, oldest first (as on the slide).
  const struck = card.locator('.evidence-supersedes li s');
  await expect(struck).toHaveCount(2);
  await expect(struck.nth(0)).toContainText(/^Front desk, 2019: .*penicillin/i);
  await expect(struck.nth(1)).toContainText(/^Other clinic, 2024: .*penicillin.*copied/i);

  await showChatFrom(page, 'Is she allergic to penicillin?');
  await panel(page, '01_doctor_slide_answer', [page.locator('.assistant .window-bar'), card], { bottomOf: messages(page) });

  // The README overview: the full window at 1440 × 900, one image pixel for each CSS pixel.
  await page.getByRole('textbox', { name: 'Message to the Care Assistant' }).blur();
  await page.evaluate(() => window.scrollTo(0, 0));
  await windowShot(page, '00_doctor_patient_page', { scale: 'css' });

  // A phone (390 px wide): the Care Assistant is the last tab. The chat stays open when the layout changes.
  await page.setViewportSize({ width: 390, height: 640 });
  await selectTab(page, 'Care Assistant');
  await expect(page.locator('.assistant .evidence-supersedes li s')).toHaveCount(2);
  await windowShot(page, '11_doctor_chat_narrow');
});

test('Use case 1: the front desk checks in Patient B and sets the care team', async ({ page }) => {
  // Step 1: find Patient B by name and date of birth.
  await openAs(page, USERS.sofia, '/patients', 'find');
  await findPatientB(page);

  // Step 2: change the phone number (UPDATE), then check in an emergency visit in "ER Waiting".
  await selectTab(page, 'Visit');
  await page.getByRole('button', { name: 'Edit details' }).click();
  const edit = page.getByRole('dialog', { name: 'Edit the patient details' });
  await edit.getByLabel('Phone number').fill('+1-508-555-0199');
  await edit.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(edit).toBeHidden();
  await expect(page.locator('.patient-header')).toContainText('+1-508-555-0199');

  const checkIn = page.getByRole('region', { name: 'Check in a visit' });
  await checkIn.getByLabel('Visit class').selectOption('EMER');
  await checkIn.getByLabel('Location').selectOption({ label: 'ER Waiting' });
  await checkIn.getByLabel('Reason (optional)').fill('Shortness of breath');
  await checkIn.getByRole('button', { name: 'Check in' }).click();
  const openVisit = page.getByRole('region', { name: 'Open visit' });
  await expect(openVisit).toContainText('Emergency');
  await expect(openVisit.locator('.location-current .location-name')).toHaveText('ER Waiting');
  await expect(page.locator('.patient-header')).toContainText('Open visit');

  // Step 3: set the care team. Add Jun Park by mistake, then remove him. Each save is a new version.
  await selectTab(page, 'Care team');
  await addMembers(page, 'Priya Nair', 'Amara Okafor');
  await saveCareTeam(page, 1);
  await addMembers(page, 'Jun Park');
  await saveCareTeam(page, 2);
  await page.getByRole('button', { name: 'Remove Jun Park' }).click();
  await saveCareTeam(page, 3);

  const team = page.getByRole('region', { name: 'Current care team' }).locator('tbody tr');
  await expect(team).toHaveCount(2);
  await expect(team.filter({ hasText: 'Priya Nair' })).toHaveCount(1);
  await expect(team.filter({ hasText: 'Amara Okafor' })).toHaveCount(1);

  // The chain, newest first: {Nair, Okafor} ← {Nair, Okafor, Park} ← {Nair, Okafor}. Sofia Alvarez wrote each version.
  const chain = page.getByRole('region', { name: 'Care-team chain' });
  const versions = chain.locator('.team-version');
  await expect(versions.nth(0)).toHaveClass(/team-version-current/);
  await expect(versions.nth(0).locator('.badge')).toHaveText('Current');
  await expect(versions.nth(0).locator('.team-version-members s')).toHaveCount(0);
  await expect(versions.nth(1).locator('.team-version-members s')).toHaveCount(1);
  await expect(versions.nth(2).locator('.team-version-members s')).toHaveCount(1);
  const members = versions.locator('.team-version-members');
  for (const index of [0, 1, 2]) {
    await expect(members.nth(index)).toContainText('Priya Nair');
    await expect(members.nth(index)).toContainText('Amara Okafor');
    await expect(versions.nth(index)).toContainText('By Sofia Alvarez');
  }
  await expect(members.nth(0)).not.toContainText('Jun Park');
  await expect(members.nth(1)).toContainText('Jun Park');
  await expect(members.nth(2)).not.toContainText('Jun Park');
  // The MOA page has one column. A window of 900 px keeps the panel small enough for the report.
  await page.setViewportSize({ width: 900, height: 900 });
  await panel(page, '02_moa_care_team_chain', chain);
  await page.setViewportSize(WIDE);

  // Step 4: write the intake note. Use case 3 checks it in the chart.
  await selectTab(page, 'Visit');
  await page.getByRole('button', { name: 'Write an intake note' }).click();
  const intake = page.getByRole('dialog', { name: 'Write an intake note' });
  await expect(intake.getByLabel('Display name')).toHaveValue('Chief complaint');
  await intake.getByLabel('Statement', { exact: true }).fill('Shortness of breath since this morning.');
  await submitRecord(intake);
});

test('Use case 2: Patient B asks about the medications and reports that metformin stopped', async ({ page }) => {
  await openAs(page, USERS.patientB, patientPage(patientB), 'chart');
  await expect(page.getByRole('tab', { name: 'My record' })).toHaveAttribute('aria-selected', 'true');

  const turn = await ask(page, 'What medications am I taking?');
  await expect(turn.locator('.bubble-assistant')).toContainText(/metformin/i);
  await expect(turn.locator('.evidence-card').filter({ hasText: /Metformin/ })).not.toHaveCount(0);
  await expect(turn.locator('.evidence-supersedes')).toHaveCount(0);

  await findInChart(page, 'metformin');
  const metformin = chartItem(page, /Metformin/);
  await metformin.getByRole('button', { name: 'Report', exact: true }).click();
  const report = page.getByRole('dialog', { name: 'Report a change' });
  await report.getByLabel('Your report').fill('I stopped taking metformin.');
  await submitRecord(report);

  // The report is the new current assertion of the metformin item. A patient sees the head of the chain only.
  await expect(metformin.locator('.chart-item-statement')).toHaveText('I stopped taking metformin.');
  await expect(metformin.locator('.chart-item-meta')).toContainText(`Patient · ${PATIENT_B.name}`);
  await expect(metformin.getByRole('button', { name: /chain/ })).toHaveCount(0);
});

test('Use case 3: the triage nurse records the vital signs and an asthma assessment', async ({ page }) => {
  // Step 1: open Patient B from My patients.
  await openAs(page, USERS.nair, '/patients', 'my-patients');
  await page.getByRole('link', { name: PATIENT_B.name }).click();
  await expect(page).toHaveURL(new RegExp(`/patients/${patientB}(\\?|$)`));

  // Step 2: read the earlier visits.
  await selectTab(page, 'Visit');
  await expect(page.locator('#visit-history-title')).toContainText('Earlier visits');
  await expect(page.locator('.visit-list > li').first()).toBeVisible();

  // The intake note of Use case 1 is a chief complaint in the chart.
  await selectTab(page, 'Chart');
  await findInChart(page, 'Shortness of breath since this morning');
  const note = chartItem(page, 'Shortness of breath since this morning.');
  await expect(note).toContainText('Chief complaint');
  await expect(note.locator('.chart-item-meta')).toContainText('Sofia Alvarez');

  // Record the vital signs: one message with three assertions.
  await page.getByRole('button', { name: 'Record vital signs' }).click();
  const vitals = page.getByRole('dialog', { name: 'Record vital signs' });
  const rows = vitals.locator('fieldset.record-row');
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0).getByLabel('Display name')).toHaveValue('Heart rate');
  for (const [index, value] of ['112', '150/95', '91'].entries()) {
    await rows.nth(index).getByLabel('Value', { exact: true }).fill(value);
  }
  await submitRecord(vitals, 'Record 3 assertions');

  // Record the assessment (a provisional recommendation), then the inhaler (a recommendation).
  let form = await openRecordForm(page);
  await fillRow(form, {
    category: 'Diagnosis',
    preset: PRESETS.asthma,
    intent: 'Recommendation',
    verification: 'Provisional',
    statement: 'Possible asthma attack.',
  });
  await submitRecord(form);

  form = await openRecordForm(page);
  await fillRow(form, {
    category: 'Prescription',
    preset: PRESETS.salbutamol,
    intent: 'Recommendation',
    verification: 'Provisional',
    statement: 'Recommend a salbutamol inhaler, 2 puffs as needed.',
  });
  await submitRecord(form);

  // The chart shows the new items. The nurse is the author.
  for (const [search, text, badges] of [
    ['Heart rate', '112 /min', /Report\s*Confirmed/],
    ['asthma', 'Possible asthma attack.', /Recommendation\s*Provisional/],
    ['salbutamol', 'Recommend a salbutamol inhaler', /Recommendation\s*Provisional/],
  ] as const) {
    await findInChart(page, search);
    const item = chartItem(page, text);
    await expect(item.locator('.chart-item-meta')).toContainText('Priya Nair');
    await expect(item.locator('.badges')).toContainText(badges);
  }

  // The search also finds the author (and the members of the care team): the items of triage.
  await findInChart(page, 'Priya Nair');
  const chips = page.locator('.chart .chips');
  for (const chip of ['Diagnoses (1)', 'Prescriptions (1)', 'Observations (3)']) {
    await expect(chips.getByRole('button', { name: chip, exact: true })).toBeVisible();
  }
  const prescriptions = page.locator('.chart-group').filter({ has: page.getByRole('heading', { name: /^Prescriptions/ }) });
  await panel(page, '03_nurse_triage_record', [page.locator('.chart .toolbar'), prescriptions]);

  // Move the patient to "ER Bed 2".
  await selectTab(page, 'Visit');
  await moveTo(page, 'ER Waiting', 'ER Bed 2');
  const places = page.getByRole('region', { name: 'Open visit' }).locator('.location-name');
  await expect(places).toHaveText(['ER Waiting', 'ER Bed 2']);

  // Patient B has no allergy on record. The answer says so, and it cites no item.
  const turn = await ask(page, 'Any allergies?');
  await expect(turn.locator('.bubble-assistant')).toContainText(/no allergy is recorded/i);
  await expect(turn.locator('.evidence-card')).toHaveCount(0);
  await expect(turn.locator('.bubble-time')).toContainText('No item cited');
});

test('Use case 4: the doctor revises the assessment, confirms a fact of the agent and prescribes', async ({ page }) => {
  await openAs(page, USERS.okafor, patientPage(patientB), 'chart');

  // The answer cites the two recommendations of the nurse.
  const recommended = await ask(page, 'What did the nurse recommend?');
  const cited = recommended.locator('.evidence-card');
  await expect(cited).toHaveCount(2);
  await expect(cited.filter({ hasText: 'Asthma attack' })).toHaveCount(1);
  await expect(cited.filter({ hasText: /Salbutamol inhaler/ })).toHaveCount(1);
  await expect(cited.filter({ hasText: 'Priya Nair' })).toHaveCount(2);

  // Order a troponin test and record the result.
  let form = await openRecordForm(page);
  await fillRow(form, { category: 'LabOrder', preset: PRESETS.troponin, intent: 'Decision', statement: 'Order a troponin test, stat.' });
  await submitRecord(form);
  form = await openRecordForm(page);
  await fillRow(form, {
    category: 'LabReport',
    preset: PRESETS.troponin,
    details: { 'Conclusion (optional)': 'Troponin I 0.09 ng/mL (high).' },
    intent: 'Report',
    verification: 'Confirmed',
    statement: 'Troponin I is above the reference range.',
  });
  await submitRecord(form);
  await findInChart(page, 'troponin');
  await expect(page.locator('.chart-group').filter({ hasText: 'Lab orders' })).toContainText('Order a troponin test, stat.');
  await expect(page.locator('.chart-group').filter({ hasText: 'Lab results' })).toContainText('Troponin I is above the reference range.');

  // Supersede the asthma assessment of the nurse with heart failure (a decision).
  await findInChart(page, 'asthma');
  await chartItem(page, 'Possible asthma attack.').getByRole('button', { name: 'Supersede' }).click();
  form = page.getByRole('dialog', { name: 'Supersede an item' });
  await expect(form.locator('.target-card')).toContainText('Asthma attack');
  await fillRow(form, { preset: PRESETS.heartFailure, intent: 'Decision', verification: 'Provisional', statement: 'Possible heart failure.' });
  await submitRecord(form);

  await findInChart(page, 'heart failure');
  let chain = await openChain(page, chartItem(page, 'Possible heart failure.'));
  let links = chain.locator('.chain-list > li');
  await expect(links).toHaveCount(2);
  await expect(links.nth(0)).toContainText('Heart failure');
  await expect(links.nth(0).locator('.badges')).toContainText('Current');
  await expect(links.nth(1).locator('.chain-item-struck')).toContainText('Asthma attack');
  await expect(links.nth(1)).toContainText('Priya Nair');
  await panel(page, '04_doctor_supersede_chain', chain.locator('.dialog-frame'), { pad: 0 });
  await closeDialog(chain);

  // Tell the Care Assistant a fact. The agent records it as unconfirmed.
  const fact = "The patient's father died of a heart attack.";
  const told = await ask(page, fact);
  await expect(told.locator('.bubble-time')).toContainText('Recorded from your message');
  const recorded = told.locator('.evidence-card');
  await expect(recorded).toHaveCount(1);
  await expect(recorded.locator('.badges')).toContainText('Recorded, unconfirmed');
  await expect(recorded.locator('.badges')).toContainText('Agent');
  await expect(recorded.locator('.badges')).toContainText('Unconfirmed');
  await showChatFrom(page, fact);
  await panel(page, '05_doctor_tell_unconfirmed', [questionOf(page, fact), recorded], { bottomOf: messages(page) });

  // Confirm the family history. The confirmation supersedes the item of the agent.
  await findInChart(page, 'father');
  const family = chartItem(page, /father/i);
  await expect(family.locator('.badges')).toContainText('Agent');
  await family.getByRole('button', { name: 'Confirm', exact: true }).click();
  form = page.getByRole('dialog', { name: 'Confirm an item' });
  await fillRow(form, { intent: 'Decision', verification: 'Confirmed' });
  await submitRecord(form);
  await expect(family.locator('.badges')).toContainText('Confirmed');
  await expect(family.locator('.badges')).not.toContainText('Agent');
  chain = await openChain(page, family);
  links = chain.locator('.chain-list > li');
  await expect(links).toHaveCount(2);
  await expect(links.nth(0).locator('.badges')).toContainText('Confirmed');
  await expect(links.nth(1).locator('.chain-item-struck .badges')).toContainText('Agent');
  await closeDialog(chain);

  // Prescribe furosemide. The decision supersedes the inhaler recommendation.
  await findInChart(page, 'salbutamol');
  await chartItem(page, 'Recommend a salbutamol inhaler').getByRole('button', { name: 'Supersede' }).click();
  form = page.getByRole('dialog', { name: 'Supersede an item' });
  await fillRow(form, { preset: PRESETS.furosemide, intent: 'Decision', verification: 'Confirmed', statement: 'Start furosemide 40 mg once a day.' });
  await submitRecord(form);
  await findInChart(page, 'furosemide');
  chain = await openChain(page, chartItem(page, 'Start furosemide 40 mg once a day.'));
  links = chain.locator('.chain-list > li');
  await expect(links).toHaveCount(2);
  await expect(links.nth(0)).toContainText('Furosemide');
  await expect(links.nth(1).locator('.chain-item-struck')).toContainText(/Salbutamol inhaler/);
  await closeDialog(chain);

  // Stop metformin. The decision supersedes the report of the patient.
  await findInChart(page, 'metformin');
  await chartItem(page, 'I stopped taking metformin.').getByRole('button', { name: 'Supersede' }).click();
  form = page.getByRole('dialog', { name: 'Supersede an item' });
  await fillRow(form, { details: { Status: 'stopped' }, intent: 'Decision', verification: 'Confirmed', statement: 'Metformin is stopped.' });
  await submitRecord(form);
  chain = await openChain(page, chartItem(page, 'Metformin is stopped.'));
  links = chain.locator('.chain-list > li');
  // prescription ← patient report ← doctor decision (newest first in the dialog)
  await expect(links.nth(0)).toContainText('Metformin is stopped.');
  await expect(links.nth(0).locator('.chain-item-head strong')).toHaveText('Physician');
  await expect(links.nth(1)).toContainText('I stopped taking metformin.');
  await expect(links.nth(1).locator('.chain-item-head strong')).toHaveText('Patient');
  await expect(links.nth(2).locator('.chain-item-head strong')).toHaveText('Physician');
  await expect(links.nth(2).locator('.chain-item-struck')).toContainText('Metformin');
  await closeDialog(chain);
});

test('Use case 5: the nurse moves the patient to cardiology, and the front desk adds Tom Becker', async ({ page }) => {
  await openAs(page, USERS.nair, patientPage(patientB), 'visit');
  await moveTo(page, 'ER Bed 2', 'Cardiology Room 401');
  const openVisit = page.getByRole('region', { name: 'Open visit' });
  await expect(openVisit.locator('.location-name')).toHaveText(['ER Waiting', 'ER Bed 2', 'Cardiology Room 401']);
  await expect(openVisit.locator('.visit-head')).toContainText('Cardiology');
  // Each location has its times. Only the last location has no end time.
  await expect(openVisit.locator('.location-list li:not(.location-current) .location-time')).toHaveCount(2);
  await expect(openVisit.locator('.location-list li.location-current')).toHaveCount(1);

  await openAs(page, USERS.sofia, patientPage(patientB), 'care-team');
  await addMembers(page, 'Tom Becker');
  await saveCareTeam(page, 4);
  await expect(page.getByRole('region', { name: 'Current care team' }).locator('tbody tr')).toHaveCount(3);

  // Tom Becker can open the chart now.
  await openAs(page, USERS.becker, patientPage(patientB), 'chart');
  await expect(page.locator('.forbidden-panel')).toHaveCount(0);
  await expect(page.locator('.chart .chart-item').first()).toBeVisible();
});

test('Use case 6: in the evening, Patient B asks for the plan and gets heart failure, not asthma', async ({ page }) => {
  await openAs(page, USERS.patientB, patientPage(patientB), 'chart');
  const turn = await ask(page, 'What is my plan?');
  const answer = turn.locator('.bubble-assistant');
  await expect(answer).toContainText(/heart failure/i);
  await expect(answer).toContainText(/furosemide/i);
  await expect(turn).not.toContainText(OLD_WORDS);
  const cards = turn.locator('.evidence-card');
  await expect(cards.filter({ hasText: 'Heart failure' })).not.toHaveCount(0);
  await expect(cards.filter({ hasText: /Furosemide/ })).not.toHaveCount(0);
  // The cards show the current items only. A patient sees no superseded rows.
  await expect(turn.locator('.evidence-supersedes')).toHaveCount(0);

  await showChatFrom(page, 'What is my plan?');
  await panel(page, '06_patient_evening_plan', [page.locator('.assistant .window-bar'), questionOf(page, 'What is my plan?'), cards.first()], {
    bottomOf: messages(page),
    pad: 4,
  });
});

test('Use case 7: a nurse who is not on the care team gets the 403 panel, and the patient sees the denial', async ({ page }) => {
  await openAs(page, USERS.park, '/patients', 'find');
  await findPatientB(page);
  const denied = page.locator('.forbidden-panel');
  await expect(denied.getByRole('heading', { name: 'Access denied' })).toBeVisible();
  await expect(denied.locator('.forbidden-message')).toHaveText(
    "You are not on this patient's care team. This attempt is in the audit log.",
  );
  await expect(page.getByRole('button', { name: 'Record', exact: true })).toHaveCount(0);
  await page.setViewportSize({ width: 900, height: 900 });
  await panel(page, '07_nurse_403_denied', [page.locator('.patient-header'), denied]);
  await page.setViewportSize(WIDE);

  await openAs(page, USERS.patientB, patientPage(patientB), 'audit');
  await expect(page.getByRole('heading', { name: 'Who opened my record' })).toBeVisible();
  const row = page.locator('.table-audit tbody tr.row-denied').first();
  await expect(row).toContainText('Denied');
  await expect(row).toContainText('Jun Park');
  await expect(row).toContainText('Nurse:E1004');
  await expect(row).toContainText('/api/patients/{patient}/chart');
  await expect(page.locator('.toolbar-title p')).toContainText(/\d+ denied/);
  const next = page.locator('.table-audit tbody tr.row-denied + tr').first();
  await panel(page, '08_patient_audit_denied', [page.locator('.toolbar').first(), row, next]);
});

test('Use case 8: the front desk changes the directory: an UPDATE, a 409 and a DELETE', async ({ page }) => {
  await openAs(page, USERS.sofia, '/directory', 'staff');

  // UPDATE: change the phone number of a staff member.
  await page.getByLabel('Find staff by name').fill('Jun Park');
  const park = page.locator('tbody tr').filter({ hasText: 'Jun Park' });
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await park.getByRole('button', { name: 'Edit Jun Park' }).click();
  const edit = page.getByRole('dialog', { name: 'Edit Jun Park' });
  await edit.getByLabel('Phone number').fill('+1-508-555-2999');
  await edit.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(edit).toBeHidden();
  await expect(park).toContainText('+1-508-555-2999');

  // 409: the server stops the delete of a department that has staff.
  await selectTab(page, 'Departments');
  await page.getByRole('button', { name: 'Delete Emergency' }).click();
  const confirm = page.getByRole('dialog', { name: 'Delete a department' });
  await confirm.getByRole('button', { name: 'Delete', exact: true }).click();
  await expect(confirm.locator('.banner-conflict')).toHaveText('Conflict. The department has staff. You cannot delete it.');
  await panel(page, '09_moa_directory_409', confirm.locator('.dialog-frame'), { pad: 0 });
  await confirm.getByRole('button', { name: 'Cancel' }).click();
  await expect(confirm).toBeHidden();
  await expect(page.locator('tbody tr').filter({ hasText: 'Emergency' }).first()).toBeVisible();

  // DELETE: the unused location "Old Storage Room" goes away from the list.
  await selectTab(page, 'Locations');
  const store = page.locator('tbody tr').filter({ hasText: 'Old Storage Room' });
  await expect(store).toContainText('Not used');
  await store.getByRole('button', { name: 'Delete Old Storage Room' }).click();
  const remove = page.getByRole('dialog', { name: 'Delete a location' });
  await remove.getByRole('button', { name: 'Delete', exact: true }).click();
  await expect(remove).toBeHidden();
  await expect(store).toHaveCount(0);
});

test('Use case 9: the doctor ends the visit, and the chart keeps the full history', async ({ page }) => {
  await openAs(page, USERS.okafor, patientPage(patientB), 'visit');
  const openVisit = page.getByRole('region', { name: 'Open visit' });
  await openVisit.getByRole('button', { name: 'End the visit' }).click();
  const confirm = page.getByRole('dialog', { name: 'End the visit' });
  await confirm.getByRole('button', { name: 'End the visit' }).click();
  await expect(confirm).toBeHidden();
  await expect(openVisit).toHaveCount(0);
  await expect(page.locator('.patient-header')).toContainText('No open visit');

  // The visit of the journey is the newest visit. It has an end time and its three locations.
  const visit = page.locator('.visit-list > li').first();
  await expect(visit.locator('.visit-head')).toContainText('Emergency');
  await expect(visit.locator('.visit-time .badge')).toContainText('Ended');
  await expect(visit.locator('.location-name')).toHaveText(['ER Waiting', 'ER Bed 2', 'Cardiology Room 401']);
  await expect(visit.locator('.location-current')).toHaveCount(0);
  await panel(page, '10_doctor_visit_ended', visit);

  // The history keeps the superseded items, with their authors.
  await selectTab(page, 'Chart');
  await page.getByLabel('Show history').check();
  await findInChart(page, 'asthma');
  const asthma = chartItem(page, 'Possible asthma attack.');
  await expect(asthma).toHaveClass(/chart-item-old/);
  await expect(asthma.locator('.badges')).toContainText('Superseded');
  await expect(asthma.locator('.chart-item-meta')).toContainText('Priya Nair');
  await findInChart(page, 'heart failure');
  await expect(chartItem(page, 'Possible heart failure.').locator('.chart-item-meta')).toContainText('Amara Okafor');
});
