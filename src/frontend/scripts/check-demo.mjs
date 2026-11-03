#!/usr/bin/env node
// Checks the use cases of the Demo guide (src/demo/steps.json):
// - each user key is a demo user of doc/api.md, section 1.1, with the same name;
// - each page is a route of src/app/routes.json, and each tab is a tab of that route;
// - a patient page has a patient key, and that key is a demo patient;
// - the use cases are 0 to 9 of USER_FLOWS.md section 3, in order. Each use case has a title, one or more steps
//   and an expected result. Each step has actions.
// Run it with: npm run check:demo

import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, '..');
const repo = resolve(frontend, '..', '..');
const paths = {
  steps: resolve(frontend, 'src/demo/steps.json'),
  routes: resolve(frontend, 'src/app/routes.json'),
  contract: resolve(repo, 'doc/api.md'),
};

function readJson(path) {
  return JSON.parse(readFileSync(path, 'utf8'));
}

/** Reads the demo-user table of doc/api.md, section 1.1: | `key` | name | role |. */
function readDemoUsers(markdown) {
  const start = markdown.indexOf('### 1.1');
  if (start < 0) throw new Error('doc/api.md has no section 1.1.');
  const end = markdown.indexOf('\n### ', start + 1);
  const section = markdown.slice(start, end < 0 ? undefined : end);
  const users = new Map();
  for (const line of section.split('\n')) {
    const match = /^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|/.exec(line);
    if (match) users.set(match[1], { name: match[2], role: match[3] });
  }
  if (users.size === 0) throw new Error('doc/api.md section 1.1 has no demo users.');
  return users;
}

const problems = [];
const problem = (where, text) => problems.push(`${where}: ${text}`);

const guide = readJson(paths.steps);
const routes = readJson(paths.routes);
const demoUsers = readDemoUsers(readFileSync(paths.contract, 'utf8'));
const routeByPath = new Map(Object.values(routes).map((route) => [route.path, route]));

// The users map of the guide must agree with the contract.
for (const [key, name] of Object.entries(guide.users ?? {})) {
  const known = demoUsers.get(key);
  if (!known) problem(`users.${key}`, 'is not a demo user of doc/api.md section 1.1');
  else if (known.name !== name) problem(`users.${key}`, `has the name "${name}", but doc/api.md has "${known.name}"`);
}

const useCases = guide.useCases ?? [];
if (useCases.length !== 10) {
  problem('useCases', `has ${useCases.length} use cases; USER_FLOWS.md section 3 has 10 (Use case 0 to Use case 9)`);
}

let stepCount = 0;
useCases.forEach((useCase, index) => {
  const where = `Use case ${useCase.id ?? index}`;
  if (useCase.id !== index) problem(where, `has the id ${useCase.id}; it must be ${index}`);
  if (!useCase.title) problem(where, 'has no title');
  if (!Array.isArray(useCase.expected) || useCase.expected.length === 0) problem(where, 'has no expected result');
  if (!Array.isArray(useCase.steps) || useCase.steps.length === 0) problem(where, 'has no step');
  (useCase.steps ?? []).forEach((step, stepIndex) => {
    stepCount += 1;
    const at = `${where}, Step ${stepIndex + 1}`;
    const user = demoUsers.get(step.user);
    if (!user) problem(at, `the user "${step.user}" is not a demo user of doc/api.md section 1.1`);
    if (!(step.user in (guide.users ?? {}))) problem(at, `the user "${step.user}" is not in the users map of steps.json`);
    if (user && !step.user.startsWith(`${user.role}:`)) problem(at, `the key "${step.user}" does not start with its role "${user.role}"`);

    const route = routeByPath.get(step.page);
    if (!route) {
      problem(at, `the page "${step.page}" is not a route of src/app/routes.json`);
    } else if (step.tab !== undefined && !route.tabs.includes(step.tab)) {
      problem(at, `the tab "${step.tab}" is not a tab of ${step.page} (${route.tabs.join(', ') || 'no tabs'})`);
    }
    if (step.page?.includes(':id')) {
      const patient = demoUsers.get(step.patient);
      if (!step.patient) problem(at, 'the page needs a patient key');
      else if (!patient || patient.role !== 'Patient') problem(at, `the patient "${step.patient}" is not a demo patient`);
    } else if (step.patient !== undefined) {
      problem(at, 'has a patient key, but the page has no :id');
    }
    if (step.search !== undefined && !(step.page === routes.patients.path && step.tab === 'find')) {
      problem(at, 'has a search, but the page is not /patients with the tab "find"');
    }
    if (!Array.isArray(step.actions) || step.actions.length === 0) problem(at, 'has no actions');
  });
});

if (problems.length > 0) {
  console.error(`Demo guide check failed (${problems.length} problems):`);
  for (const line of problems) console.error(`  - ${line}`);
  process.exit(1);
}
console.log(
  `Demo guide check passed: ${useCases.length} use cases, ${stepCount} steps, ` +
    `${new Set(useCases.flatMap((u) => u.steps.map((s) => s.user))).size} users. ` +
    `All users are demo users of doc/api.md section 1.1, and all pages are routes.`,
);
