# LoL Draft Assistant

LoL Draft Assistant is a League of Legends champion select companion built around one goal: give fast, role-aware pick and ban recommendations from live draft context instead of static tier lists.

The project combines a FastAPI backend, a React frontend, a Tauri desktop shell, Riot LCU integration, a remote bridge for cloud-hosted setups, and a data pipeline that scrapes Lolalytics into a local SQLite store.

## What it does

- Reads live champion select state from the local Riot League Client through the LCU lockfile and localhost API.
- Mirrors that state into a desktop UI or a browser UI.
- Recommends picks and bans using exact matchup, synergy, tier, role-fit, and confidence-aware scoring.
- Falls back gracefully when the client does not expose full role information by inferring visible roles from champion lane data.
- Maintains its own local dataset for champions, tier stats, matchups, and synergies.
- Supports both local single-machine usage and split cloud deployments with a remote bridge client.

## Architecture

### Core layers

1. `backend/`
   FastAPI application, SQLite persistence, recommendation engine, scraper orchestration, scheduler, bridge endpoints, and websocket broadcasting.

2. `frontend/`
   React + TypeScript interface for draft tracking, filters, recommendations, health/status cards, and manual overrides.

3. `frontend/src-tauri/`
   Tauri desktop shell written in Rust. It polls the local Riot client and emits `lcu-draft-update` events into the frontend.

4. `bridge/`
   Python bridge client for machines where the Riot client runs locally but the API is hosted remotely.

5. `ops/`
   Docker Compose and Caddy configuration for deployment, including the Hetzner split-service setup.

## Main runtime modes

### 1. Local all-in-one

The backend, frontend, scheduler, and local LCU connector all run on the same machine.

Use this when:

- you want to develop locally
- League Client runs on the same machine
- you want the simplest setup

### 2. Local desktop client + remote API

The Tauri app runs locally and talks to a hosted API for recommendations and static data.

Use this when:

- you want the desktop UI locally
- recommendation serving and data refresh live on a VPS
- League Client still runs on your own PC

### 3. Remote bridge mode

The API lives on a server, but a small local bridge process reads LCU state and relays draft updates to the server through authenticated bridge endpoints.

Use this when:

- the server cannot read the local Riot client directly
- you want centralized hosting with live local client state
- you need session-aware remote draft tracking

## Technology stack

### Backend

- Python 3.12
- FastAPI
- Pydantic v2
- `pydantic-settings`
- aiosqlite
- aiohttp
- httpx
- APScheduler
- BeautifulSoup 4
- Playwright
- Uvicorn

### Frontend

- React 18
- TypeScript
- Vite
- Tailwind CSS
- Vitest
- Testing Library

### Desktop shell

- Tauri 2
- Rust
- Tokio
- Reqwest
- Serde
- Winreg on Windows for Riot install discovery

### Data sources

- Riot Data Dragon for champion metadata and champion icons
- Lolalytics for tier, matchup, and synergy data

### Deployment

- Docker
- Docker Compose
- Caddy
- Hetzner VPS

## How draft data flows through the app

### Local desktop mode

1. The Tauri Rust process locates the Riot lockfile.
2. It authenticates against the local LCU API on `127.0.0.1`.
3. It polls:
   - `/lol-champ-select/v1/session`
   - `/lol-gameflow/v1/gameflow-phase`
4. The Rust side builds a normalized draft payload and emits `lcu-draft-update`.
5. The React app hydrates that payload with champion metadata and applies local overrides if needed.
6. The frontend sends a recommendation request to the backend.

### Backend analysis flow

1. The backend receives draft state and effective filters.
2. It resolves ally and enemy role context.
3. If the client did not provide lane assignments, the recommendation engine infers likely roles from champion lane distributions and scenario scoring.
4. It scores candidate champions using:
   - counter data
   - synergy data
   - tier performance
   - role fit
   - evidence confidence
   - coverage and ambiguity penalties
5. It returns ranked pick and ban suggestions with explanations and component-level scoring.

## Recommendation model

The scoring layer is not a plain tier-list lookup. It works from a structured draft context.

The model combines:

- direct lane-vs-lane matchup signals
- team synergy signals
- tier performance for the chosen region, rank, and role
- role suitability for the recommended champion
- confidence adjustments when the visible draft is incomplete or role assignments are ambiguous
- evidence shrinkage to avoid over-trusting thin samples

The output bundle includes:

- recommended picks
- recommended bans
- score breakdowns
- explanation text
- warnings about fallback or partial confidence
- patch and scope readiness metadata

## Scraping and data pipeline

This repo maintains its own SQLite-backed recommendation dataset.

### Champion sync

Champion metadata is synchronized from Riot Data Dragon. The backend stores:

- champion id
- key
- display name
- image URL
- patch
- known role list

### Lolalytics scraping strategy

The scraper is HTTP-first and browser-second.

#### Tier data

Tier pages are fetched with `httpx` and parsed with BeautifulSoup. The parser extracts champion rows directly from the tierlist document.

#### Build, matchup, and synergy data

The build scraper first tries to avoid browser automation:

- matchup/counter rows are parsed from the page payload
- synergy rows are fetched from Lolalytics' JSON endpoint under `https://a1.lolalytics.com/mega/`

This keeps refreshes much faster and lighter than a pure browser scraper.

#### Browser fallback

If the HTTP parser returns no usable payload, the provider falls back to headless Chromium through Playwright and scrapes the live page.

That fallback is limited and controlled:

- normal refreshes use HTTP parsing first
- browser parsing is only used when the direct parser fails
- parser fallback and parser failure events are recorded in the database

### Refresh orchestration

The backend does not blindly re-scrape every scope every cycle.

It tracks per-scope freshness using:

- region
- rank
- role
- patch
- tier/build signatures
- row counts
- last success time
- next due timestamps
- fallback health

The scheduler then refreshes only due scopes. Hot scopes can refresh more often than cold or aggregate scopes.

### Patch generation model

Each refresh cycle is grouped around an active patch generation. The backend keeps patch readiness metrics so the UI can tell whether the requested scope is fully ready, partial, stale, or still falling back.

## API surface

### Public status and recommendation endpoints

- `GET /api/health`
  Basic app health plus LCU/bridge connection state.

- `GET /api/status`
  Returns runtime state, effective filters, patch metadata, scope readiness, and storage snapshot data.

- `POST /api/recommend`
  Stateless recommendation endpoint for manually supplied picks, bans, region, rank, and role.

- `GET /api/data/champions`
  Champion catalog used by the frontend and Tauri desktop UI.

- `GET /api/tierlist`
  Lightweight tier list response for a selected region/rank/role.

- `GET /api/recommendations`
  Current recommendation bundle for a session.

### Session and draft endpoints

- `GET /api/settings`
- `PUT /api/settings`
- `PUT /api/draft/overrides`
- `POST /api/draft/preview`
- `GET /ws/draft`

These endpoints support live session state, websocket broadcasting, and manual role overrides during champion select.

### Bridge endpoints

The bridge layer is mounted under `/api/bridge`.

Main endpoints:

- `POST /api/bridge/register`
- `POST /api/bridge/heartbeat`
- `PUT /api/bridge/draft-state`
- `DELETE /api/bridge/session/{device_id}`

Bridge requests are authenticated with bearer tokens from `LDA_BRIDGE_TOKENS`.

### Admin and operations endpoints

The admin layer exposes:

- overview snapshots
- scope health
- refresh jobs
- parser health
- manual scope refresh
- hot-scope refresh
- patch generation rebuild
- failed-scope retry
- provider run visibility

These endpoints exist to operate the dataset, not just the player-facing recommendation flow.

## Frontend and desktop client

The UI supports two primary interaction styles.

### Browser UI

The browser build works as a manual draft board and API client. It is useful for:

- frontend development
- remote API usage without the native shell
- fallback/manual tracking

### Tauri desktop UI

The desktop build adds:

- direct LCU polling through Rust
- local event delivery into the React UI
- automatic draft hydration
- local role inference and per-slot override support

The Tauri side polls every two seconds and emits only when the draft payload fingerprint changes.

## Project structure

```text
backend/
  app/
    db/               SQLite access and schema
    domain/           typed models and shared domain objects
    providers/        external data providers
    routers/          FastAPI routes
    services/         scoring, inference, scraping, scheduling, LCU integration
    ws/               websocket state broadcasting
  tests/

bridge/
  bridge_client.py    remote bridge process for cloud deployments

frontend/
  src/                React app
  src-tauri/          Rust Tauri shell

ops/
  docker-compose.hetzner.yml
  docker-compose.tailscale.yml
  Caddyfile

scripts/
  run.py
  run_worker.py
  run_bridge.py
  full_refresh.py
  bootstrap.py
```

## Local development

### Prerequisites

- Python 3.12
- Node.js 22
- npm
- Playwright browser dependencies
- League of Legends client if you want live LCU testing

For desktop development on Windows:

- Rust toolchain
- Cargo
- Visual Studio C++ build tools

### Backend setup

```bash
cd backend
python -m pip install -e ".[dev]"
python -m playwright install chromium
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Frontend setup

```bash
cd frontend
npm install
npm run dev
```

### Run backend + frontend together

```bash
python scripts/run.py
```

### Run the refresh worker

```bash
python scripts/run_worker.py
```

### Run the bridge client

```bash
python scripts/run_bridge.py --server-base-url https://your-host --token your-token
```

### Run the Tauri desktop shell

```bash
cd frontend
npm run tauri dev
```

## Tests

### Backend

```bash
cd backend
pytest
```

### Frontend

```bash
cd frontend
npm test
```

### Production frontend build

```bash
cd frontend
npm run build
```

## Environment configuration

Copy `.env.example` to `.env` and adjust what you need.

Important flags:

- `LDA_ENABLE_LOCAL_LCU`
  Enables direct local League Client polling from the backend.

- `LDA_ENABLE_REFRESH_SCHEDULER`
  Enables rolling refresh and integrity jobs.

- `LDA_ENABLE_BRIDGE_HOUSEKEEPING`
  Enables stale bridge session cleanup.

- `LDA_BRIDGE_TOKENS`
  Comma-separated bridge auth tokens.

- `LDA_DATABASE_PATH`
  SQLite database location.

- `LDA_FRONTEND_DIST`
  Path to the built frontend that FastAPI serves in production.

- `LDA_SCHEDULED_REGIONS`
- `LDA_SCHEDULED_RANKS`
- `LDA_SCHEDULED_ROLES`
  Controls which exact scopes the scheduler maintains.

## Deployment

### Docker image

The project Dockerfile builds the frontend first, then installs the backend and Playwright into a Python runtime image.

### Hetzner split-service deployment

The Hetzner compose file runs:

- `api`
  FastAPI app serving the API and built frontend

- `worker`
  scheduler and refresh worker against the same SQLite volume

- `caddy`
  reverse proxy and public entrypoint

Bring it up with:

```bash
docker compose -f ops/docker-compose.hetzner.yml up -d --build
```

### Recommended production split

- disable local LCU on the server
- keep scheduler on the worker only
- keep bridge housekeeping on the API
- mount persistent `backend/data` and `backend/logs`

That is exactly how the Hetzner compose file is structured.

## Notes on current data model

- recommendations are patch-aware
- exact scope completeness is tracked explicitly
- aggregate rank buckets are supported in addition to exact ranks
- the app favors exact region/rank/role data when available
- parser fallback is recorded so operational issues are visible instead of silent

## Why this project is structured this way

League draft assistance gets unreliable quickly when it depends on a single live client session or a single scrape pass. This codebase is structured around three practical constraints:

1. live client state is noisy and sometimes incomplete
2. external data sources change their markup
3. recommendations need to stay usable even when a scope is partial or stale

That is why the project has:

- a normalized draft domain model
- explicit role inference
- HTTP-first scraping with browser fallback
- patch generation and scope readiness tracking
- websocket session broadcasting
- a bridge mode for hosted deployments

## License

No license file is included in this repository at the moment. Treat the project as all rights reserved unless a license is added.
