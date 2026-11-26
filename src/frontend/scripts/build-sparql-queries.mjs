#!/usr/bin/env node
// Builds src/demo/sparql_queries.json from the SELECT queries of the knowledge graph
// (src/backend/models/semantic/sparql/03_select_queries.sparql).
//
// The split rule is the rule of src/backend/infrastructure/rdf/sparql_script.py for the query IDs of this file:
// - A marker line starts a query: "# Q1. Title", "# Q9a. Title", "# QA. Title".
// - A query is the text from its marker line to the next marker line (or to the end of the file).
// - The PREFIX lines before the first marker go before each query, so each query runs alone.
// The script does not check that a query is one statement: ";" is also part of the SPARQL triple patterns.
//
// Run it with: npm run build:sparql
// "npm run check:demo" builds the data again and fails if the committed JSON file is different.

import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, '..');
const repo = resolve(frontend, '..', '..');

export const SOURCE = 'src/backend/models/semantic/sparql/03_select_queries.sparql';
export const SPARQL_FILE = resolve(repo, SOURCE);
export const JSON_FILE = resolve(frontend, 'src/demo/sparql_queries.json');

const MARKER = /^# (Q(?:\d+[a-z]?|[A-Z]))\. +(\S.*?)\s*$/;
const PREFIX_LINE = /^PREFIX\s/i;

/** Splits the text of the .sparql file into { source, queries: [{ id, title, text }] }. */
export function buildQueries(text) {
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  const first = lines.findIndex((line) => MARKER.test(line));
  if (first < 0) throw new Error(`${SOURCE} has no marker line.`);
  const prefixes = lines.slice(0, first).filter((line) => PREFIX_LINE.test(line));
  if (prefixes.length === 0) throw new Error(`${SOURCE} has no PREFIX line before the first query.`);
  const queries = [];
  let current = null;
  for (const line of lines.slice(first)) {
    const match = MARKER.exec(line);
    if (match) {
      current = { id: match[1], title: match[2], lines: [] };
      queries.push(current);
    }
    current.lines.push(line);
  }
  const seen = new Set();
  return {
    source: SOURCE,
    queries: queries.map((query) => {
      if (seen.has(query.id)) throw new Error(`${SOURCE} has the query ${query.id} two times.`);
      seen.add(query.id);
      const body = query.lines.join('\n').replace(/\s+$/, '');
      return { id: query.id, title: query.title, text: `${prefixes.join('\n')}\n\n${body}\n` };
    }),
  };
}

export function renderJson(data) {
  return `${JSON.stringify(data, null, 2)}\n`;
}

export function expectedJson() {
  return renderJson(buildQueries(readFileSync(SPARQL_FILE, 'utf8')));
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const json = expectedJson();
  writeFileSync(JSON_FILE, json);
  console.log(`Wrote ${JSON_FILE} (${JSON.parse(json).queries.length} queries).`);
}
