// Shared parts of the end-to-end tests: the demo users, the page links and the screenshots.

import { mkdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, type APIRequestContext, type Locator, type Page } from '@playwright/test';

/** The demo users of USER_FLOWS.md section 0.4 (the user keys of src/demo/steps.json). */
export const USERS = {
  patientA: 'Patient:MRN-000001',
  patientB: 'Patient:0c1b260c-7f32-fdd5-15dd-1160caf24c2b',
  sofia: 'MOA:E1001',
  nair: 'Nurse:E1002',
  becker: 'Nurse:E1003',
  park: 'Nurse:E1004',
  okafor: 'Doctor:E1005',
} as const;

export const PATIENT_B = { name: 'Marlin805 Reggie481 Nienow652', search: 'Nienow652', dob: '1966-02-18' };

/** The patient id of a patient user key (GET /api/users/{key}). The Demo guide gets it the same way. */
export async function patientIdOf(request: APIRequestContext, key: string): Promise<number> {
  const response = await request.get(`/api/users/${encodeURIComponent(key)}`);
  expect(response.ok(), `GET /api/users/${key}`).toBeTruthy();
  const user = (await response.json()) as { patientId: number | null };
  expect(user.patientId, `the patient id of ${key}`).not.toBeNull();
  return user.patientId as number;
}

/** Opens a page as a user. The link parameter ?as= sets the user for this tab (USER_FLOWS.md section 1). */
export async function openAs(page: Page, user: string, path: string, tab?: string): Promise<void> {
  const url = new URL(path, 'http://app');
  url.searchParams.set('as', user);
  if (tab) url.searchParams.set('tab', tab);
  await page.goto(`${url.pathname}${url.search}`);
  // The app removes ?as= from the link when the user is ready.
  await expect(page).not.toHaveURL(/[?&]as=/);
  await expect(page.locator('.acting-as-name')).not.toHaveText(/Wait|Select a user/);
}

// ----- Screenshots -----

const here = dirname(fileURLToPath(import.meta.url));
/** "npm run e2e:screens" (TRIAD_SCREENS=1) writes to doc/screenshots/. A normal run writes to test-results/. */
export const SCREEN_DIR = process.env.TRIAD_SCREENS === '1'
  ? resolve(here, '..', '..', '..', 'doc', 'screenshots')
  : resolve(here, '..', 'test-results', 'screenshots');

/** The largest panel in CSS pixels. At deviceScaleFactor 2 the PNG is two times larger. */
export const MAX_PANEL = { width: 900, height: 640 };

interface ShotOptions {
  /** Space around the parts, in CSS pixels. */
  pad?: number;
  /** Cut the panel at the bottom of this part (for example a list that scrolls). */
  bottomOf?: Locator;
}

interface Box {
  top: number;
  left: number;
  right: number;
  bottom: number;
}

async function unionBox(parts: Locator[]): Promise<Box> {
  const boxes = [];
  for (const part of parts) {
    const box = await part.boundingBox();
    expect(box, 'the box of a part of the panel').not.toBeNull();
    boxes.push(box!);
  }
  return {
    top: Math.min(...boxes.map((b) => b.y)),
    left: Math.min(...boxes.map((b) => b.x)),
    right: Math.max(...boxes.map((b) => b.x + b.width)),
    bottom: Math.max(...boxes.map((b) => b.y + b.height)),
  };
}

/**
 * Takes a screenshot of the box around one or more parts of the page. The name is "NN_role_action".
 * The box must not be larger than MAX_PANEL, so that the panel is easy to read when the report prints it small.
 * If the parts are not fully on the screen (under the top bar), the page scrolls the first part to the center.
 */
export async function panel(page: Page, name: string, parts: Locator | Locator[], options: ShotOptions = {}): Promise<string> {
  const list = Array.isArray(parts) ? parts : [parts];
  const pad = options.pad ?? 8;
  for (const part of list) await expect(part).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  const viewport = page.viewportSize()!;
  const topBar = (await page.locator('.topbar').boundingBox())?.height ?? 0;
  const inDialog = (await list[0].evaluate((element) => element.closest('dialog') !== null));
  let box = await unionBox(list);
  if (!inDialog && (box.top < topBar || box.bottom > viewport.height)) {
    await list[0].evaluate((element) => element.scrollIntoView({ block: 'center', inline: 'nearest' }));
    box = await unionBox(list);
  }
  const left = Math.max(0, box.left - pad);
  const top = Math.max(inDialog ? 0 : topBar, box.top - pad);
  const right = Math.min(viewport.width, box.right + pad);
  let bottom = Math.min(viewport.height, box.bottom + pad);
  if (options.bottomOf) {
    const limit = await options.bottomOf.boundingBox();
    if (limit) bottom = Math.min(bottom, limit.y + limit.height);
  }
  const clip = { x: Math.floor(left), y: Math.floor(top), width: Math.ceil(right - left), height: Math.ceil(bottom - top) };
  expect(clip.width, `the width of ${name}`).toBeLessThanOrEqual(MAX_PANEL.width);
  expect(clip.height, `the height of ${name}`).toBeLessThanOrEqual(MAX_PANEL.height);
  const path = join(SCREEN_DIR, `${name}.png`);
  mkdirSync(SCREEN_DIR, { recursive: true });
  await page.screenshot({ path, clip, animations: 'disabled', caret: 'hide' });
  return path;
}

/**
 * Shows the Care Assistant for a screenshot: the page scrolls until the chat pane is fully on the screen,
 * and the message list scrolls until the question is at its top.
 */
export async function showChatFrom(page: Page, question: string): Promise<void> {
  await page.locator('aside.pane-chat').evaluate((pane) => pane.scrollIntoView({ block: 'start' }));
  await page.locator('.assistant-messages').evaluate((list, text) => {
    const bubbles = [...list.querySelectorAll('.bubble-row-user')].filter((row) => row.textContent?.includes(text));
    const target = bubbles.at(-1);
    if (target) list.scrollTop += target.getBoundingClientRect().top - list.getBoundingClientRect().top - 8;
  }, question);
}

/** A screenshot of the full window. scale "css" gives one image pixel for each CSS pixel (the README overview). */
export async function windowShot(page: Page, name: string, options: { scale?: 'css' | 'device' } = {}): Promise<string> {
  const path = join(SCREEN_DIR, `${name}.png`);
  mkdirSync(SCREEN_DIR, { recursive: true });
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path, animations: 'disabled', caret: 'hide', scale: options.scale ?? 'device' });
  return path;
}
