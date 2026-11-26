#!/usr/bin/env node
// The web server of the Playwright tests (playwright.config.ts starts it).
//
// 1. Build the frontend (npm run build). "main.py serve" serves src/frontend/dist.
// 2. Build the template database in <temp>/triad-e2e/template.db (main.py ensure-db, about 3 s).
//    The template stays for the next run. The script builds it again when a backend file or a data file changes.
// 3. Copy the template to a new database for this run (<temp>/triad-e2e/run.db).
//    So each run starts from the same data, and a run does not depend on an earlier run.
// 4. Start "main.py serve" on port 8123 with the fake LLM and the fixed demo time.
//    With TRIAD_E2E_STORE=oxigraph the script also builds a template of the knowledge graph (ensure-kg, embedded
//    Oxigraph) from the template database, copies it for the run, and starts the server with --store oxigraph.
// On SIGTERM or SIGINT, the script stops the server and deletes the database of the run.
//
// Environment variables:
//   TRIAD_PYTHON        the Python of the backend (default: <repo>/.venv/bin/python)
//   TRIAD_E2E_PORT      the port (default: 8123; "npm run e2e:kg" uses 8124)
//   TRIAD_E2E_STORE     the data store of the backend: sqlite (default) or oxigraph (virtuoso is not supported here)
//   TRIAD_E2E_NO_BUILD  "1": do not build the frontend (use the dist folder that is there)

import { spawn, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { cpSync, copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const repo = resolve(frontend, '..', '..');
const backend = join(repo, 'src', 'backend');
const python = resolve(repo, process.env.TRIAD_PYTHON || join('.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python'));
const port = process.env.TRIAD_E2E_PORT || '8123';
const work = join(tmpdir(), 'triad-e2e');
const template = join(work, 'template.db');
const stampFile = join(work, 'template.stamp');
const runDb = join(work, 'run.db');
const store = (process.env.TRIAD_E2E_STORE || 'sqlite').toLowerCase();
// The knowledge graph of the template and of the run: Oxigraph files and the export files of ensure-kg.
const kgTemplate = join(work, 'kg-template');
const kgStampFile = join(work, 'kg-template.stamp');
const kgRun = join(work, 'kg-run');

// The fixed demo time of USER_FLOWS.md section 0.3. The times in the screenshots are the times of the journey.
const DEMO_NOW = '2026-10-30T09:00:00-04:00';

function say(text) {
  process.stderr.write(`[e2e server] ${text}\n`);
}

function fail(text) {
  say(text);
  process.exit(1);
}

/** Runs a command to its end. Shows its output only if it fails. */
function run(command, args, options = {}) {
  const result = spawnSync(command, args, { encoding: 'utf8', ...options });
  if (result.status !== 0) {
    process.stderr.write(result.stdout ?? '');
    process.stderr.write(result.stderr ?? '');
    fail(`"${command} ${args.join(' ')}" failed (${result.error?.message ?? `exit code ${result.status}`}).`);
  }
}

/** Lists the files that the database build reads: the backend code, the SQL and the data. */
function buildInputs(folder, out = []) {
  for (const entry of readdirSync(folder, { withFileTypes: true })) {
    const path = join(folder, entry.name);
    if (entry.isDirectory()) {
      // data/kg holds the export files of the knowledge graph. They do not change the SQLite template.
      const exported = relative(backend, path).split('\\').join('/') === 'data/kg';
      if (!exported && !['tests', '__pycache__', '.pytest_cache'].includes(entry.name)) buildInputs(path, out);
    } else if (/\.(py|sql|json|gz)$/.test(entry.name) && entry.name !== 'onboard_report.json') {
      out.push(path);
    }
  }
  return out;
}

/** A value that changes when a file of the database build changes. */
function inputStamp() {
  const hash = createHash('sha1');
  for (const path of buildInputs(backend).sort()) {
    const info = statSync(path);
    hash.update(`${relative(backend, path)} ${info.size} ${info.mtimeMs}\n`);
  }
  return hash.digest('hex');
}

function removeRunDb() {
  for (const suffix of ['', '-wal', '-shm']) rmSync(`${runDb}${suffix}`, { force: true });
  rmSync(kgRun, { recursive: true, force: true });
}

if (!['sqlite', 'oxigraph'].includes(store)) fail(`TRIAD_E2E_STORE must be sqlite or oxigraph, not "${store}".`);
if (!existsSync(python)) {
  fail(`Python ${python} does not exist. Create the venv (see the root README.md), or set TRIAD_PYTHON.`);
}
mkdirSync(work, { recursive: true });

if (process.env.TRIAD_E2E_NO_BUILD !== '1') {
  say('Building the frontend (npm run build) ...');
  run(process.platform === 'win32' ? 'npm.cmd' : 'npm', ['run', 'build'], { cwd: frontend, shell: process.platform === 'win32' });
}
if (!existsSync(join(frontend, 'dist', 'index.html'))) fail('src/frontend/dist/index.html does not exist. Run npm run build.');

const stamp = inputStamp();
const current = existsSync(template) && existsSync(stampFile) && readFileSync(stampFile, 'utf8') === stamp;
if (current) {
  say(`The template database ${template} is current.`);
} else {
  say(`Building the template database ${template} ...`);
  rmSync(stampFile, { force: true });
  run(python, [join(backend, 'main.py'), 'ensure-db', '--reset-db', '--db', template], { cwd: repo });
  writeFileSync(stampFile, stamp);
}
removeRunDb();
copyFileSync(template, runDb);

// The settings of the knowledge graph: the template and the run have their own folders (TRIAD_KG_DIR and
// TRIAD_KG_OXIGRAPH_PATH), so the e2e run does not touch src/backend/data/kg.
const kgEnv = (dir) => ({ TRIAD_STORE: 'oxigraph', TRIAD_KG_DIR: dir, TRIAD_KG_OXIGRAPH_PATH: join(dir, 'oxigraph') });
if (store === 'oxigraph') {
  const kgCurrent = current && existsSync(kgTemplate) && existsSync(kgStampFile) && readFileSync(kgStampFile, 'utf8') === stamp;
  if (kgCurrent) {
    say(`The knowledge graph template ${kgTemplate} is current.`);
  } else {
    say(`Building the knowledge graph template ${kgTemplate} (ensure-kg --store oxigraph) ...`);
    rmSync(kgStampFile, { force: true });
    rmSync(kgTemplate, { recursive: true, force: true });
    run(python, [join(backend, 'main.py'), 'ensure-kg', '--store', 'oxigraph', '--db', template], {
      cwd: repo,
      env: { ...process.env, ...kgEnv(kgTemplate) },
    });
    writeFileSync(kgStampFile, stamp);
  }
  cpSync(kgTemplate, kgRun, { recursive: true });
}

const env = {
  ...process.env,
  TRIAD_DB_PATH: runDb,
  TRIAD_LLM: 'fake',
  TRIAD_NOW: DEMO_NOW,
  TRIAD_SQL_LOG: 'off',
  TRIAD_SPARQL_LOG: 'off',
  TRIAD_STORE: store,
  ...(store === 'oxigraph' ? kgEnv(kgRun) : {}),
  PORT: port,
};
say(`Starting the server on http://127.0.0.1:${port} with the database ${runDb} (store: ${store}) ...`);
const server = spawn(python, [join(backend, 'main.py'), 'serve', '--db', runDb, '--store', store], { cwd: repo, env, stdio: ['ignore', 'inherit', 'inherit'] });

let stopping = false;
function stop(signal) {
  if (stopping) return;
  stopping = true;
  server.kill(signal);
}
process.on('SIGTERM', () => stop('SIGTERM'));
process.on('SIGINT', () => stop('SIGINT'));
server.on('exit', (code, signal) => {
  removeRunDb();
  process.exit(stopping ? 0 : (code ?? (signal ? 1 : 0)));
});
