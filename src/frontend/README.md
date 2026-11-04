# TRIAD frontend

This folder has the web frontend of the TRIAD prototype (Milestone 4).
The frontend is one app for all user groups: patients, doctors, nurses and the front desk (MOA).
It shows the hospital-visit journey of [`USER_FLOWS.md`](../../USER_FLOWS.md) and the Care Assistant of the 3MT slide.

The app has no login. You select a user type and a user in the top bar.
All data is synthetic. Do not put real patient data in the app.

The frontend uses only the API in [`doc/api.md`](../../doc/api.md).
The types in `src/api/types.ts` are a copy of section 2 of that file.

## Stack

| Part | Item |
|---|---|
| Language | TypeScript 7 |
| UI | React 19, plain CSS (no UI kit), the native `<dialog>` element, `FormData` |
| Routes | react-router-dom 7 |
| Server data | @tanstack/react-query 5 |
| Build and dev server | Vite 8 |

The versions in `package.json` are exact. `package-lock.json` is in the repository.

## Prerequisites

- Node.js 20.19 or later. We recommend Node.js 22 or later.
- npm 10 or later.
- For the full app: the TRIAD backend (port 8000 by default). See the root [`README.md`](../../README.md).

## Install

Run these commands from the root of the repository:

```sh
cd src/frontend
npm ci
```

## Run

### Development (with hot reload)

The easy way is `./src/scripts/dev.sh` from the root folder. It starts the backend and the frontend together.
To start the frontend alone:

1. Start the backend on port 8000 (`python src/backend/main.py serve`).
2. Start the frontend:

   ```sh
   cd src/frontend
   npm run dev
   ```

3. Open http://127.0.0.1:5173.

Vite serves the frontend on port 5173. It sends each `/api` request to `TRIAD_API_URL` (default
`http://127.0.0.1:8000`). See [Settings (.env)](#settings-env).
If port 5173 is in use, Vite stops with an error (`strictPort`). It does not select a different port.

### Production build

```sh
cd src/frontend
npm run build
```

The build goes to `src/frontend/dist/`. Git ignores this folder.
`python src/backend/main.py serve` serves `dist/` on port 8000, together with the API.
Each path that does not start with `/api` gets `index.html`, so deep links work.

## Settings (.env)

The frontend reads its settings from `src/frontend/.env`. `dev.sh` makes this file from
[`.env.example`](.env.example) if it is missing. Git ignores `.env`. A variable of the shell wins over the file.

| Variable | Default | Who reads it |
|---|---|---|
| `TRIAD_API_URL` | `http://127.0.0.1:8000` | Only the Vite dev server (`vite.config.ts`). It is the address for the `/api` requests. It does not go into the bundle. `dev.sh` sets it from `PORT`. |
| `VITE_...` | — | The app (`import.meta.env.VITE_...`). The app uses no `VITE_` value yet. |

Rules:

- **Each `VITE_` value is public.** The build puts it into the JavaScript bundle, and each user of the app can read it.
  Never put an API key or another secret in `src/frontend/`. The secrets go in `src/backend/.env`.
  The browser calls the backend, and only the backend calls the LLM provider.
- **The values are fixed when Vite starts or builds.** After a change, start `npm run dev` again or make a new build.
  `main.py serve` serves the files of the last build. Vite also reads `.env.development` (for `npm run dev`) and
  `.env.production` (for `npm run build`), if they exist. Git ignores them too.
- **Declare each `VITE_` value** in [`src/vite-env.d.ts`](src/vite-env.d.ts). Then `tsc -b` stops on a name that is not declared.
- The app always calls the relative path `/api`, so it needs no backend address. In production, the backend serves
  the app and the API on one port. In development, the Vite proxy sends `/api` to `TRIAD_API_URL`.

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Starts the Vite dev server on port 5173. |
| `npm run build` | Checks the types (`tsc -b`), then builds `dist/`. |
| `npm run typecheck` | Checks the types only. |
| `npm run preview` | Serves `dist/` on port 4173 (with the same `/api` proxy). |
| `npm run check:demo` | Checks the use cases of the Demo guide (see below). Then `scripts/check-logo.mjs` checks that `public/triad-icon.png` is the repository logo. |
| `npm run e2e` | Runs the Playwright end-to-end tests on port 8123 (see [End-to-end tests](#end-to-end-tests-playwright)). |
| `npm run e2e:screens` | Runs the same tests and writes the screenshots to `doc/screenshots/`. |

## How the app acts as a user

- The top bar has the user type (Patient, Doctor, Nurse, MOA) and the user.
  The user list comes from `GET /api/users?role=&q=&limit=&offset=`, one page at a time. The demo users show first.
- The app sends the user key in the header `X-Triad-User` with each request (`src/api/client.ts`).
- The app keeps the last user in `localStorage`. Each browser tab also keeps its own user in `sessionStorage`.
- The link parameter `?as=<user key>` sets the user for this tab only.
  Example: `http://localhost:5173/patients?as=Nurse:E1004`.
  Use it to open different users in different tabs.
- When the user changes, the app stops the open requests, clears all cached data, closes the chat and opens the home page of the role.
- If the server does not know the user (401), the app asks you to select a user.

## Errors

| Status | What the app shows |
|---|---|
| 401 | The user picker, with the message of the server. |
| 403 | A full panel with the message of the server. Example (journey Use case 7): "You are not on this patient's care team. This attempt is in the audit log." |
| 409 | A banner with the message of the server. |
| 422 | The message, and each message of `fields` under its field. |
| No connection | A panel that tells you to start the backend (see the Quickstart in the root README). |

## Dates and times

The API sends times as ISO 8601 with an offset, for example `2026-10-30T09:01:00-04:00`.
The app shows the time as it is written in the string ("Oct 30, 2026 09:01"). The hospital is in Eastern time.
The app does not give a date-only string (`YYYY-MM-DD`) to `new Date()`, because the browser can show the day before.
The helpers are in `src/lib/dates.ts`.

The clock in the top bar follows the value `clock` of `GET /api/health`:

- `system` (`TRIAD_NOW=system`): the time of the server, for example "Nov 3, 2026 15:52". It starts at `now` of the
  health response and moves on each 30 s, in the offset of the server. It does not use the time zone data of the
  browser, so it always agrees with the times of the new records.
- `fixed`, or no value (an old backend): the demo time of the server, for example "Demo time: Oct 30, 2026 09:19".
- Below 1180 px, the clock shows the short form: "15:52" or "Demo 09:19".

## Demo guide

Select **Demo guide** in the top bar. The panel lists the use cases of the hospital-visit journey (`USER_FLOWS.md`, section 3, Use cases 0 to 9).
Each use case has one or more steps (Step 1, Step 2, and so on). Each step has one user, one page and an **Act as ⟨user⟩** button.
The button sets the user and opens the correct page and tab.
For a patient page, the app gets the patient id from `GET /api/users/{key}` (`patientId`).

The use cases are in `src/demo/steps.json` (the list `useCases`; each use case has the list `steps`). `npm run check:demo` checks that:

- each user key is a demo user of `doc/api.md`, section 1.1, with the same name;
- each page is a route of `src/app/routes.json`, and each tab is a tab of that route;
- each patient page has a demo patient key;
- the file has Use cases 0 to 9, in order. Each use case has one or more steps and an expected result. Each step has actions.

## End-to-end tests (Playwright)

The Playwright tests use the real app in Chromium: the built frontend, the backend and a SQLite database.

| File | What it tests |
|---|---|
| `e2e/hospital_visit.spec.ts` | The hospital-visit journey of `USER_FLOWS.md` section 3, Use case 0 to Use case 9, with the users and the pages of the Demo guide. It checks the expected result of each use case, and it takes the screenshots. The use cases share the database, so they run in order (serial mode). If one use case fails, Playwright skips the use cases after it. `src/backend/tests/integration/test_hospital_visit.py` does the same journey through the API. |
| `e2e/crud.spec.ts` | The directory of the front desk: UPDATE (a staff member), INSERT and DELETE (a new location), three deletes that the server stops with a 409, and the pager of the Staff tab (292 staff, 25 on a page). |
| `e2e/demo_guide.spec.ts` | The Demo guide lists the 10 use cases, and **Act as** sets the user and opens the page of the step. |

### Before the first run

1. Make the Python venv of the backend at the root of the repository (`.venv`). See the root [`README.md`](../../README.md).
   To use a different Python, set `TRIAD_PYTHON` (an absolute path, or a path from the root of the repository).
2. Install the packages and the headless Chromium of Playwright 1.59.1 (about 190 MB on the disk, one time only):

   ```sh
   cd src/frontend
   npm ci
   npx playwright install --only-shell chromium
   ```

   To see the browser (`npx playwright test --headed`), install the full Chromium: `npx playwright install chromium`.

### Run

```sh
cd src/frontend
npm run e2e
```

The run takes about 25 s on a laptop, together with the frontend build. The first run also builds the template database (about 3 s).

`playwright.config.ts` starts the web server `e2e/serve.mjs`. The server:

1. builds the frontend (`npm run build`), because `main.py serve` serves `dist/`;
2. builds the template database `<temp>/triad-e2e/template.db` (`main.py ensure-db`). It keeps the template for the next run,
   and it builds it again when a file of `src/backend` (the code, the SQL or the data) changes;
3. copies the template to `<temp>/triad-e2e/run.db`, so each run starts from the same data and does not depend on an earlier run;
4. starts `main.py serve` on port 8123 with `TRIAD_LLM=fake`, `TRIAD_NOW=2026-10-30T09:00:00-04:00` (the fixed demo time) and `TRIAD_SQL_LOG=off`.

When the tests end, Playwright stops the server, and the server deletes `run.db`.
The tests do not use the ports of `dev.sh` (8000 and 5173) or the database `src/backend/data/triad.db`.
If port 8123 is in use, the run stops with an error. The tests need no network and no API key.

| Variable | Default | What it does |
|---|---|---|
| `TRIAD_PYTHON` | `.venv/bin/python` | The Python of the backend. |
| `TRIAD_E2E_PORT` | `8123` | The port of the test server. |
| `TRIAD_E2E_NO_BUILD` | — | `1`: do not build the frontend. Use the `dist/` folder that is there. |
| `TRIAD_SCREENS` | — | `1`: write the screenshots to `doc/screenshots/` (`npm run e2e:screens` sets it). |

Output (git ignores these folders):

- `test-results/screenshots/`: the screenshots of a normal run.
- `test-results/output/`: a screenshot and a trace of each failed test (`npx playwright show-trace <trace.zip>`).
- `playwright-report/`: the HTML report (`npx playwright show-report`).

To run one file or one use case: `npx playwright test crud` or `npx playwright test -g "Use case 0"`.
The journey use cases need the use cases before them, so run the full journey file, not one use case of it.

On Windows, use WSL2 (`npm run e2e:screens` uses the shell syntax `TRIAD_SCREENS=1`).

### Screenshots

The journey test takes the screenshots in Chromium at `deviceScaleFactor` 2. Each panel is a part of the page of at most
900 × 640 CSS pixels, so it is easy to read when the report prints it small. The times are the times of the journey,
because the demo time is fixed. The same code gives the same PNG files on the same computer.
`npm run e2e:screens` writes them to `doc/screenshots/`:

| File | Use case | What it shows |
|---|---|---|
| `00_doctor_patient_page.png` | 0 | The full window (1440 × 900, scale 1): the chart of Elena Marsh and the Care Assistant (the README overview). |
| `01_doctor_slide_answer.png` | 0 | The 3MT slide answer: "No. A physician ruled it out with an allergy test on Oct 2, 2026.", with the two superseded assertions struck through. |
| `02_moa_care_team_chain.png` | 1 | The care-team chain: {Nair, Okafor} ← {Nair, Okafor, Park} ← {Nair, Okafor}, each version by Sofia Alvarez. |
| `03_nurse_triage_record.png` | 3 | The chart, found by the nurse name: the provisional asthma assessment and the inhaler recommendation of Priya Nair. |
| `04_doctor_supersede_chain.png` | 4 | The assertion chain: heart failure (the decision of the doctor) supersedes the asthma assessment of the nurse. |
| `05_doctor_tell_unconfirmed.png` | 4 | The "tell" turn: the agent records the family history as unconfirmed. |
| `06_patient_evening_plan.png` | 6 | The plan of Patient B: heart failure and furosemide, no asthma and no inhaler. |
| `07_nurse_403_denied.png` | 7 | The 403 panel of Jun Park, who is not on the care team. |
| `08_patient_audit_denied.png` | 7 | The audit log of Patient B with the denied attempt of Jun Park (the red row). |
| `09_moa_directory_409.png` | 8 | The 409 message: the Emergency department has staff, so the front desk cannot delete it. |
| `10_doctor_visit_ended.png` | 9 | The ended visit with its three locations and their times. |
| `11_doctor_chat_narrow.png` | 0 | The Care Assistant tab on a phone (390 px wide). |

## Folder structure

```
src/frontend/
  index.html               the HTML page
  vite.config.ts           the dev server (port 5173, /api proxy to TRIAD_API_URL) and the build (dist/)
  playwright.config.ts     the end-to-end tests: Chromium, one worker, the web server on port 8123
  tsconfig.e2e.json        the type check of playwright.config.ts and e2e/ (tsc -b)
  package.json             exact versions, scripts, engines (Node.js 20.19 or later)
  .env.example             the settings template (dev.sh copies it to .env; git ignores .env)
  scripts/check-demo.mjs   the check of the Demo guide use cases
  scripts/check-logo.mjs   the check that the app logo has the same bytes as assets/triad-icon.png
  e2e/                     the Playwright tests, their helpers and the web server of the tests (serve.mjs)
  public/triad-icon.png    the logo of the top bar and the browser tab (a copy of assets/triad-icon.png)
  src/
    main.tsx               the entry point
    vite-env.d.ts          the types of the VITE_ values (import.meta.env)
    styles.css             all styles
    api/
      types.ts             the contract types (a copy of doc/api.md, section 2)
      client.ts            the fetch wrapper: X-Triad-User, the error body, abort, the 422 field names
      endpoints.ts         one function for each endpoint, and the query keys
    app/
      App.tsx              the providers, the shell and the routes
      session.tsx          the acting user (localStorage, sessionStorage, ?as=)
      routes.json          the routes and their tabs (the app and check-demo.mjs read it)
      routes.ts            the path helpers and the home page of each role
    components/            the top bar, the user picker, dialogs, tabs, fields, badges, error views, the pager
    pages/                 Welcome, Home, Patients, Patient and Directory pages
    patient/               the tabs of the patient page, the record form and the chain view
    chat/                  the Care Assistant and its evidence card
    directory/             the four directory tabs
    demo/                  steps.json (the use cases) and the Demo guide panel
    lib/                   helpers: dates, labels, debounce, the page state (usePage), the media query hook (useMediaQuery)
```

## Pages and API endpoints

| Page or tab | Who sees it | API endpoints |
|---|---|---|
| Top bar | all | `GET /api/health`, `GET /api/me`, `GET /api/users?role=&q=&limit=&offset=` (the user picker) |
| `/` (home) | all | (sends a patient to "My record", the MOA to the front desk, a nurse or doctor to "My patients") |
| `/patients`: Front desk | MOA | `GET /api/patients?scope=open-visits&limit=&offset=`, `POST /api/patients` |
| `/patients`: My patients | nurse, doctor | `GET /api/patients?scope=care-team&limit=&offset=` |
| `/patients`: Find a patient | staff | `GET /api/patients?q=&dob=&limit=&offset=` |
| `/patients/:id`: header | all who can open the patient | `GET /api/patients/{id}`, `PATCH /api/patients/{id}` (MOA) |
| Chart ("My record" for a patient) | patient, nurse, doctor | `GET /api/patients/{id}/chart?history=&q=&category=&limit=&offset=`, `GET /api/assertions/{id}/chain?limit=&offset=`, `GET /api/codes`, `GET /api/medications?q=&limit=8`, `GET /api/patients/{id}/chart?q=&limit=10` (the item search of the record form), `POST /api/messages` |
| Visit | patient, MOA, care team | `GET /api/patients/{id}/visits?limit=&offset=`, `POST /api/patients/{id}/visits` (MOA), `POST /api/visits/{id}/locations`, `POST /api/visits/{id}/end`, `GET /api/locations?limit=200`, `POST /api/messages` (MOA intake note) |
| Care team | patient, MOA, care team | `GET /api/visits/{id}/care-team`, `PUT /api/visits/{id}/care-team` (MOA, a doctor on the team), `GET /api/staff?q=&limit=20` |
| Audit | patient (self), a doctor on the care team | `GET /api/patients/{id}/audit?limit=&offset=` |
| Care Assistant (right pane) | patient, nurse, doctor (not the MOA) | `GET /api/patients/{id}/chat/sessions?limit=&offset=`, `POST /api/patients/{id}/chat/sessions`, `GET /api/chat/sessions/{id}`, `POST /api/chat/sessions/{id}/turns` |
| `/directory`: Departments | staff (MOA can change) | `GET /api/departments?q=&limit=&offset=`, `POST /api/departments`, `PATCH`, `DELETE /api/departments/{id}` |
| `/directory`: Locations | staff (MOA can change) | `GET /api/locations?department=&q=&limit=&offset=`, `GET /api/departments?limit=200` (the department list), `POST /api/locations`, `PATCH`, `DELETE /api/locations/{id}` |
| `/directory`: Staff | staff (MOA can change) | `GET /api/staff?role=&q=&limit=&offset=`, `GET /api/departments?limit=200` (MOA: the new staff form), `POST /api/staff`, `PATCH`, `DELETE /api/staff/{id}` |
| `/directory`: Medications | staff (MOA can change) | `GET /api/medications?q=&limit=&offset=`, `POST /api/medications`, `PATCH`, `DELETE /api/medications/{id}` |
| Demo guide | all | `GET /api/users/{key}` (the patient id of a step) |

Pages: a list with `limit=&offset=` shows one page of 25 rows, and a pager under it ("1–25 of 1,148", Previous, Next).
A change of a filter goes back to the first page. The past chats have "Show older chats" in place of a pager.
The pager is `src/components/Pager.tsx`, and `src/lib/usePage.ts` keeps the offset.

The tabs of the patient page follow the role and `Patient.permissions`:

- A nurse or a doctor always gets the Chart tab. The app always calls the chart endpoint.
  If the user is not on the care team, the server sends 403, and the tab shows the 403 panel (journey Use case 7).
- The MOA gets the Visit and Care team tabs only. The app does not call the chart or the chat endpoints for the MOA.
- The Audit tab shows when `permissions.viewAudit` is true.

## Narrow screens

- **1100 px or less:** the patient page has one column. The Care Assistant is the last tab ("Care Assistant", `?tab=assistant`).
  The chat stays open when you select a different tab, so the open chat and the text in the box stay.
  The chat fills the screen under the top bar. When the screen becomes wide again, the chat goes back to the right pane,
  and the app selects the first tab.
- **1000 px or less:** the top bar has two rows. The links scroll sideways if they do not fit.
- **600 px or less:** the user button shows only the avatar and the name. The tab lists scroll sideways.
  The forms, the user picker and the Demo guide use the full screen.
- A wide table scrolls in its box. The page itself does not scroll sideways.

## The Care Assistant

The chat looks like the chat of the 3MT slide:

- The answer text, then one evidence card for each citation, by rank.
- The card shows the current assertion: the author label, the date and the statement, for example "**Physician**, Oct 2, 2026: not allergic (allergy test)".
- Under "Supersedes", the card lists the superseded assertions in the order of the API (oldest first, as on the 3MT slide), with a line through each one ("Front desk, 2019: penicillin allergy").
  A patient gets no superseded assertions from the API, so a patient sees no "Supersedes" list.
- A card of a new assertion from a "tell" turn has the badge "Recorded, unconfirmed".
- The window bar shows the chat mode of the session (`rules`, `fake` or `llm`).
- Each message gets a new `clientTurnId` (`crypto.randomUUID()`). "Try again" sends the same `clientTurnId`, so the server does not save the turn two times.

## AI use

Claude Code (an AI tool) wrote the first version of this frontend. The team checked it. See `doc/ai_review_log.md`.
