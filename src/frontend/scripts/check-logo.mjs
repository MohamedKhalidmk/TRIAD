#!/usr/bin/env node
// Checks that the app logo (public/triad-icon.png) is the repository logo (assets/triad-icon.png).
// The two files must have the same bytes. If they are different, copy the repository logo again:
//   cp assets/triad-icon.png src/frontend/public/triad-icon.png
// Run it with: npm run check:demo (this script runs after scripts/check-demo.mjs)

import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, '..');
const repo = resolve(frontend, '..', '..');
const files = {
  repository: resolve(repo, 'assets/triad-icon.png'),
  app: resolve(frontend, 'public/triad-icon.png'),
};

function sha256(path) {
  return createHash('sha256').update(readFileSync(path)).digest('hex');
}

const name = (path) => relative(repo, path);
const missing = Object.values(files).filter((path) => !existsSync(path));
if (missing.length > 0) {
  console.error('Logo check failed:');
  for (const path of missing) console.error(`  - The file ${name(path)} is missing.`);
  process.exit(1);
}

const hashes = { repository: sha256(files.repository), app: sha256(files.app) };
if (hashes.repository !== hashes.app) {
  console.error('Logo check failed: the app logo is not the repository logo.');
  console.error(`  - ${name(files.repository)}: SHA-256 ${hashes.repository}`);
  console.error(`  - ${name(files.app)}: SHA-256 ${hashes.app}`);
  console.error(`  Copy the repository logo again: cp ${name(files.repository)} ${name(files.app)}`);
  process.exit(1);
}
console.log(`Logo check passed: ${name(files.app)} is the same as ${name(files.repository)} (SHA-256 ${hashes.app.slice(0, 12)}…).`);
