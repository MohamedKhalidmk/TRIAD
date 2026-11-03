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
| `npm run check:demo` | Checks the Demo guide steps (see below). |

## How the app acts as a user

- The top bar has the user type (Patient, Doctor, Nurse, MOA) and the user.
  The user list comes from `GET /api/users?role=&q=`. The demo users show first.
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
| 403 | A full panel with the message of the server. Example (journey Step 7): "You are not on this patient's care team. This attempt is in the audit log." |
| 409 | A banner with the message of the server. |
| 422 | The message, and each message of `fields` under its field. |
| No connection | A panel that tells you to start the backend (see the Quickstart in the root README). |

## Dates and times

The API sends times as ISO 8601 with an offset, for example `2026-10-30T09:01:00-04:00`.
The app shows the time as it is written in the string ("Oct 30, 2026 09:01"). The hospital is in Eastern time.
The app does not give a date-only string (`YYYY-MM-DD`) to `new Date()`, because the browser can show the day before.
The helpers are in `src/lib/dates.ts`.

## Demo guide

Select **Demo guide** in the top bar. The panel lists the steps of the hospital-visit journey (`USER_FLOWS.md`, section 3, Steps 0 to 9).
Each part of a step has an **Act as ⟨user⟩** button. The button sets the user and opens the correct page and tab.
For a patient page, the app gets the patient id from `GET /api/users/{key}` (`patientId`).

The steps are in `src/demo/steps.json`. `npm run check:demo` checks that:

- each user key is a demo user of `doc/api.md`, section 1.1, with the same name;
- each page is a route of `src/app/routes.json`, and each tab is a tab of that route;
- each patient page has a demo patient key;
- the file has Steps 0 to 9, in order, each with actions and an expected result.

## Folder structure

```
src/frontend/
  index.html               the HTML page
  vite.config.ts           the dev server (port 5173, /api proxy to TRIAD_API_URL) and the build (dist/)
  package.json             exact versions, scripts, engines (Node.js 20.19 or later)
  .env.example             the settings template (dev.sh copies it to .env; git ignores .env)
  scripts/check-demo.mjs   the check of the Demo guide steps
  public/triad.svg         the icon
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
    components/            the top bar, the user picker, dialogs, tabs, fields, badges, error views
    pages/                 Welcome, Home, Patients, Patient and Directory pages
    patient/               the tabs of the patient page, the record form and the chain view
    chat/                  the Care Assistant and its evidence card
    directory/             the four directory tabs
    demo/                  steps.json and the Demo guide panel
    lib/                   pure helpers: dates, labels, debounce
```

## Pages and API endpoints

| Page or tab | Who sees it | API endpoints |
|---|---|---|
| Top bar | all | `GET /api/health`, `GET /api/me`, `GET /api/users?role=&q=` |
| `/` (home) | all | (sends a patient to "My record", the MOA to the front desk, a nurse or doctor to "My patients") |
| `/patients`: Front desk | MOA | `GET /api/patients?scope=open-visits`, `POST /api/patients` |
| `/patients`: My patients | nurse, doctor | `GET /api/patients?scope=care-team` |
| `/patients`: Find a patient | staff | `GET /api/patients?q=&dob=` |
| `/patients/:id`: header | all who can open the patient | `GET /api/patients/{id}`, `PATCH /api/patients/{id}` (MOA) |
| Chart ("My record" for a patient) | patient, nurse, doctor | `GET /api/patients/{id}/chart?history=`, `GET /api/assertions/{id}/chain`, `GET /api/codes`, `GET /api/medications?q=`, `POST /api/messages` |
| Visit | patient, MOA, care team | `GET /api/patients/{id}/visits`, `POST /api/patients/{id}/visits` (MOA), `POST /api/visits/{id}/locations`, `POST /api/visits/{id}/end`, `GET /api/locations`, `POST /api/messages` (MOA intake note) |
| Care team | patient, MOA, care team | `GET /api/visits/{id}/care-team`, `PUT /api/visits/{id}/care-team` (MOA, a doctor on the team), `GET /api/staff?q=` |
| Audit | patient (self), a doctor on the care team | `GET /api/patients/{id}/audit` |
| Care Assistant (right pane) | patient, nurse, doctor (not the MOA) | `GET /api/patients/{id}/chat/sessions`, `POST /api/patients/{id}/chat/sessions`, `GET /api/chat/sessions/{id}`, `POST /api/chat/sessions/{id}/turns` |
| `/directory`: Departments | staff (MOA can change) | `GET`, `POST /api/departments`, `PATCH`, `DELETE /api/departments/{id}` |
| `/directory`: Locations | staff (MOA can change) | `GET`, `POST /api/locations`, `PATCH`, `DELETE /api/locations/{id}` |
| `/directory`: Staff | staff (MOA can change) | `GET /api/staff?role=&q=`, `POST /api/staff`, `PATCH`, `DELETE /api/staff/{id}` |
| `/directory`: Medications | staff (MOA can change) | `GET /api/medications?q=`, `POST /api/medications`, `PATCH`, `DELETE /api/medications/{id}` |
| Demo guide | all | `GET /api/users/{key}` (the patient id of a step) |

The tabs of the patient page follow the role and `Patient.permissions`:

- A nurse or a doctor always gets the Chart tab. The app always calls the chart endpoint.
  If the user is not on the care team, the server sends 403, and the tab shows the 403 panel (journey Step 7).
- The MOA gets the Visit and Care team tabs only. The app does not call the chart or the chat endpoints for the MOA.
- The Audit tab shows when `permissions.viewAudit` is true.

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
