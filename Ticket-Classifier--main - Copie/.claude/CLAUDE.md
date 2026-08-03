# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI-powered IT support ticket classification and dispatch system for LVMH Power BI. Classifies tickets into ITIL taxonomy using a three-agent CrewAI pipeline with few-shot learning, then assigns them to the best available team member using a Scorer Agent (CrewAI) based on skills, workload, and brand affinity.

**This repo is the backend only.** The frontend lives at `frontend`, a sibling directory next to this one (React 19 + Vite).

## Commands

```bash
# Setup
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
cp .env.example .env            # fill in EY Azure gateway credentials

# Run backend
python run_backend.py           # http://localhost:8000 | docs at /docs

# Integration tests (backend must be running)
python tests/test_api.py
python tests/test_api.py path/to/tickets.xlsx   # with real Excel data

# SLA engine / watchdog unit tests (no backend needed, fixed dates)
python tests/test_sla_engine.py
python tests/test_sla_watchdog.py
python tests/test_profiles_store.py             # concurrency test (20 threads)
python tests/test_auth_users_store.py           # concurrency test (20 threads) for users.json

# Manual SMTP test (requires real SMTP_USERNAME/SMTP_PASSWORD in .env)
python tests/test_email.py destinataire@exemple.com

# Accuracy benchmark (runs full CrewAI pipeline; slow — 10s between requests)
python evaluate_agents.py       # edit n_samples on line 88 to change count

# Rebuild training data from raw Excel
python src/preprocessing/prepare_data.py        # writes few_shot_examples.json + eval_dataset.json

# Manage team availability (CLI)
python -m src.agents.set_availability --liste
python -m src.agents.set_availability --membre cherazade_hamdi --dispo false --raison "Congé"
python -m src.agents.set_availability --membre all --dispo true

# One-shot data migration (dry-run by default; see scripts/migrate_priorite_calculee.py docstring)
python scripts/migrate_priorite_calculee.py
python scripts/migrate_priorite_calculee.py --apply

# One-shot migration: transition member_profiles.json to "performance metrics are live-only"
# (zeroes metriques/historique_resolutions/score_performance, preserves identity/skills/charge/
# availability) — see profiling_agent.py bootstrap note below
python scripts/reset_profile_stats.py
python scripts/reset_profile_stats.py --apply

# Hybrid ticket auto-start integration test (agent never clicks "Commencer")
python tests/test_hybrid_start.py
```

## LLM Configuration — EY Azure OpenAI Gateway

The system uses EY's Azure API Management gateway. Required `.env` variables:

```
OPENAI_API_KEY=<EY APIM subscription key>
OPENAI_ENDPOINT=https://eyq-incubator.europe.fabric.ey.com/eyq/eu/api
OPENAI_API_VERSION=2024-02-15-preview
OPENAI_MODEL_NAME=gpt-4o
```

The `_build_llm()` helper in `ticket_crew.py` and `scorer_agent.py` constructs:
- URL: `{OPENAI_ENDPOINT}/openai/deployments/{OPENAI_MODEL_NAME}/chat/completions`
- Auth: `api-key: {OPENAI_API_KEY}` header (Azure APIM format — NOT Bearer token)

**Critical:** never pass `api_version` to the LLM constructor — the EY gateway returns 400. The version is embedded in the URL only for actual Azure deployments.

## Other required `.env` variables

```
AUTH_MODE=legacy                 # "legacy" (default) | "keycloak" — see Module 5 below
JWT_SECRET=...                   # defaults to a hardcoded dev value in src/auth.py — change in production
JWT_EXPIRE_MINUTES=480

# AUTH_MODE=keycloak only — see infra/keycloak/README.md (sibling dir to this repo, at the workspace root)
KEYCLOAK_URL=http://localhost:8180
KEYCLOAK_REALM=lvmh-tickets
KEYCLOAK_FRONTEND_CLIENT_ID=ticket-dispatch-frontend
KEYCLOAK_BACKEND_CLIENT_ID=ticket-dispatch-backend
KEYCLOAK_BACKEND_CLIENT_SECRET=   # from Keycloak admin console after first realm import, not committed

SSE_TICKET_SECRET=...            # short-lived SSE ticket signing — see Module 5, unrelated to JWT_SECRET
FRONTEND_ORIGIN=http://localhost:5173   # single-origin CORS allowlist (allow_credentials=True forbids "*")

SMTP_HOST=smtp.gmail.com        # Gmail SMTP (STARTTLS, port 587); SMTP_PASSWORD must be a Gmail
SMTP_PORT=587                   # "app password", not the account password
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_SENDER_NAME=LVMH Ticket System
PLATFORM_URL=http://localhost:5173   # base URL used in notification email links

SN_INSTANCE=https://devXXXXX.service-now.com   # ServiceNow instance base URL, no trailing slash
SN_USER=...                      # ServiceNow technical account (Basic Auth)
SN_PASSWORD=...
```

`SN_*` vars were missing from `.env.example` until this update — check your local `.env` still has them
if you pull a fresh checkout. `AUTH_MODE`/`KEYCLOAK_*`/`SSE_TICKET_SECRET`/`FRONTEND_ORIGIN` are more
recent additions than that — same caveat applies.

`EmailNotifier` treats missing `SMTP_USERNAME`/`SMTP_PASSWORD` as "not configured" and silently skips
sending (logs a warning, returns `False`) rather than raising — so the backend runs fine without SMTP
configured, just without outbound email.

`.env.example` also lists `GROQ_API_KEY`, `ANTHROPIC_API_KEY`, and `LOG_LEVEL` — none are referenced
anywhere in `src/`; leftover scaffolding, safe to ignore/leave unset.

## Architecture

### Full Request Flow

```
POST /classify
  → src/api.py              — validates TicketInput, calls classification then scoring
  → ticket_crew.py          — classify_ticket() drives CrewAI Module 1
      → Agent 1 (Analyst)   — extracts intent, identifies service and brand
      → Agent 2 (Classifier)— assigns taxonomy + calls PriorityCalculatorTool
      → Agent 3 (Auditor)   — validates, outputs ClassificationResult with confidence
      → sla_engine.compute_priority() — unconditionally overwrites priorite_calculee after
        crew.kickoff(); the LLM's own priority text is NEVER trusted (see below)
  → scorer_agent.py         — assign_ticket() drives CrewAI Module 2
      → Python (direct)     — ScoreMembersDispatchTool scores all available members
      → LLM                 — generates French justification sentence only
  → profiling_agent.py      — run_update() increments assignee charge_actuelle
  → save_to_db()            — persists to classifications_db.json
  → NotificationDispatcher.notify_assignment() — in-app notif (sync) + SSE push
    (best-effort) + email (FastAPI BackgroundTasks, non-blocking)
  ← ClassificationResult (with assigned_to + justification)
```

**Never trust LLM-generated text for a value with a deterministic formula.** `priorite_calculee` was
historically written by the LLM (format `"1 - Critique"`) but read back with canonical keys
(`"1-Critique"`) by `sla_engine.SLA_HOURS` — the mismatch meant every ticket silently fell back to the
96h default budget, defeating the whole SLA watchdog while unit tests (built on already-canonical
fixtures) kept passing. Fixed by making `sla_engine.compute_priority(impact, urgence)` the single
source of truth, always called after `crew.kickoff()`. See `DESCRIPTION_PFE.md` section 7.2 for the full
story (`AUDIT_REPORT.md`, its original source, is not present in this repo copy);
`scripts/migrate_priorite_calculee.py` backfilled historical data.

### Key Files

- [src/api.py](src/api.py) — All FastAPI endpoints; `JOBS` dict (in-memory batch state, lost on restart); `load_db()` / `save_to_db()` / `update_in_db()` for the 100-entry sliding-window JSON (`_write_db_unlocked()` writes atomically via `.tmp` + `os.replace()` under `_DB_LOCK`, same pattern as the other stores; also called from `sla_watchdog.check_all_tickets()` every 5 min to persist dedup flags, not just from HTTP endpoints); CORS restricted to `FRONTEND_ORIGIN` (not wildcard); `POST /agent/notifications/sse-ticket` + `_mint_sse_ticket()`/`_consume_sse_ticket()` for SSE auth (Module 5)
- [src/auth.py](src/auth.py) — `AUTH_MODE=legacy` (JWT HS256 + `users.json` + bcrypt, still the default) or `AUTH_MODE=keycloak` (JWKS/RS256 validation only, never issues tokens) — see Module 5. `users_transaction()` context manager (same `threading.Lock` + atomic `.tmp`+`os.replace()` pattern as `profiles_store.py`) protects `users.json` for the whole read-modify-write cycle; used by `POST /auth/change-password` and `PATCH /users/{id}/role` (legacy mode) — see `tests/test_auth_users_store.py` (20-thread concurrency test, same pattern as `tests/test_profiles_store.py`)
- [src/keycloak_admin.py](src/keycloak_admin.py) — Keycloak Admin REST client (`requests`, `client_credentials` service account), used only in `AUTH_MODE=keycloak` — see Module 5
- [src/servicenow.py](src/servicenow.py) — ServiceNow REST client (`requests` + `HTTPBasicAuth`): `get_ticket_sys_id()`, `get_user_sys_id()` (email → sys_id, resolved dynamically per webhook call, no persisted mapping table), `update_ticket()` (PATCH). Used by the webhook handlers in `api.py` below.
- [src/agents/ticket_crew.py](src/agents/ticket_crew.py) — Module 1: Three CrewAI agents, LVMH taxonomy constants, `PriorityCalculatorTool` (deterministic 3×3 matrix), `get_few_shot_examples()`, `_build_llm()` helper for EY gateway, `AssignmentInfo` + `ClassificationResult` Pydantic models
- [src/agents/scorer_agent.py](src/agents/scorer_agent.py) — Module 2 Part 2: `ScoreMembersDispatchTool` (Python scoring, deterministic), `assign_ticket()` (hybrid: Python ranking + LLM justification only), `_build_llm()` helper
- [src/agents/profiling_agent.py](src/agents/profiling_agent.py) — Module 2 Part 1: Pure-Python member profiling; `run_bootstrap()` derives identity/skills from raw Excel but preserves each member's live performance metrics across re-runs (see Profiling & Dispatch below); `update_after_resolution()` updates metrics and auto-discovers skills; `get_profiles_for_scorer()` returns normalized workload for dispatch
- [src/agents/profiles_store.py](src/agents/profiles_store.py) — **Single entry point** for reading/writing `member_profiles.json` and `availability.json`: per-file `threading.Lock`, atomic writes (`.tmp` + `os.replace()`), and `profiles_transaction()`/`availability_transaction()` context managers that hold the lock for the whole read-modify-write cycle (prevents lost increments under concurrent HTTP requests — see `tests/test_profiles_store.py`). No other module should `open()` these files directly.
- [src/agents/set_availability.py](src/agents/set_availability.py) — CLI + importable `set_member_availability()`; syncs `availability.json` and `member_profiles.json` via `profiles_store`
- [src/notifications/dispatcher.py](src/notifications/dispatcher.py) — `NotificationDispatcher` façade: `notify_assignment()` and `notify_sla_alert()`. In-app notif is synchronous, SSE push is best-effort, email is async (`BackgroundTasks`) for assignments but synchronous for SLA alerts (called from the watchdog's dedicated APScheduler thread, not an HTTP request — see `sla_watchdog.py` docstring for why)
- [src/notifications/email_sender.py](src/notifications/email_sender.py) — `EmailNotifier`: SMTP Gmail (STARTTLS, port 587), `send_assignment()` + `send_sla_alert()`, never raises (logs and returns `False` on failure)
- [src/notifications/sse_manager.py](src/notifications/sse_manager.py) — In-memory SSE connection manager (`asyncio.Queue` per subscribed tab). `publish()` is called from sync/thread contexts and must cross into the asyncio event loop via `loop.call_soon_threadsafe()` — the only thread-safe way to push into a queue owned by the running loop
- [src/notifications/store.py](src/notifications/store.py) — Persisted in-app notifications (`data/output/notifications.json`), atomic writes, `threading.Lock`, idempotent by `(ticket_numero, user_id, type)`
- [src/sla/sla_engine.py](src/sla/sla_engine.py) — Pure, deterministic business-hours math (Mon–Fri 07:00–19:00, all `datetime`s are naive/local wall time, never UTC). `compute_priority()`, `add_business_hours()`, `business_seconds_between()`, `on_status_change()` (the ticket status state machine: `new → in_progress → on_hold → in_progress → done`)
- [src/sla/sla_watchdog.py](src/sla/sla_watchdog.py) — `check_all_tickets()` runs every 5 min via `APScheduler.BackgroundScheduler` (not `AsyncIOScheduler` — blocking SMTP would otherwise freeze the asyncio loop and every connected agent's SSE stream). Triggers 40%/10%/breach tier alerts, deduped per-ticket via `sla_alert_*_sent` flags, escalates 10%/breach to all `role="admin"` users
- [src/preprocessing/prepare_data.py](src/preprocessing/prepare_data.py) — One-time Excel → JSON prep; `compute_accuracy()` also used by benchmark
- [evaluate_agents.py](evaluate_agents.py) — Benchmark: samples from raw Excel, classifies, prints field-by-field accuracy
- [scripts/migrate_priorite_calculee.py](scripts/migrate_priorite_calculee.py) — One-shot, idempotent migration script for the priority-format bug above; dry-run by default, timestamped backup before `--apply`
- [scripts/reset_profile_stats.py](scripts/reset_profile_stats.py) — One-shot migration zeroing `metriques`/`historique_resolutions`/`score_performance` in `member_profiles.json` for the "performance metrics are live-only" bootstrap change (see Profiling & Dispatch below); dry-run by default, timestamped backup before `--apply`
- [scripts/migrate_users_to_keycloak.py](scripts/migrate_users_to_keycloak.py) — One-shot migration of `users.json` accounts into Keycloak via `keycloak_admin.create_user()`; dry-run by default, idempotent (skips existing usernames), never copies bcrypt hashes (temp password + forced `UPDATE_PASSWORD` instead)

### Module 1 — Classification Pipeline Details

Agents run **sequentially** via CrewAI's sequential process. Few-shot examples are keyword-matched at call time and injected into Agent 1's prompt. `PriorityCalculatorTool` enforces the ServiceNow 3×3 impact/urgence → priority matrix deterministically. Agent 3 uses `output_pydantic=ClassificationResult` to force structured JSON output.

### Module 2 — Scorer Agent Details

**Hybrid design** (critical to understand):
- **Python** calls `ScoreMembersDispatchTool._run()` directly — deterministic, avoids LLM tool-call hallucination
- **LLM** only generates the justification sentence — simple text task, no tool calls

**Scoring formula:**
```
score = match_competence × 0.35 + brand_affinity × 0.25
      + (1 - charge_norm) × 0.25 + performance_norm × 0.15

match_competence = (score_sous_cat + score_service) / 2
  score_sous_cat  = skills_found / skills_required  (gradual, from SOUS_CAT_TO_SKILLS map)
  score_service   = 1.0 if service skill present else 0.0

brand_affinity  = member_services_matching_brand / total_member_services
  (case-insensitive substring match of ticket.entreprise in member's specialisations.services)
```

**Hard filter:** `disponible=False` → excluded entirely before scoring, never assigned.

### Profiling & Dispatch

`profiling_agent.py` derives per-member **identity and skills** (`competences`,
`specialisations`) from `incident-10000.xlsx` during bootstrap. Skills are discovered from
`SOUS_CAT_TO_SKILLS` and `SERVICE_KEYWORD_TO_SKILL` maps. Auto-discovery fires when a member has
>85% success on ≥5 tickets in a category.

**Performance metrics are no longer derived from the Excel file.** `_build_profiles()`
(`profiling_agent.py`) never (re)computes `metriques` / `historique_resolutions` /
`score_performance` from `incident-10000.xlsx` — those fields are fed exclusively by real
`update_after_resolution()` calls as tickets get resolved in the app (real SLA time, not the
historical Excel). A member already present in `member_profiles.json` keeps its live metrics
untouched across re-bootstraps (only identity/skills refresh), so re-running bootstrap to onboard
a new member is now safe — it no longer wipes accumulated progress for everyone else. A brand-new
member starts at the same zeroed/neutral values a first-ever bootstrap used to produce.
`scripts/reset_profile_stats.py` is the one-shot migration for `member_profiles.json` files
populated under the old (Excel-derived) behavior — dry-run by default, timestamped backup before
`--apply`, same pattern as `migrate_priorite_calculee.py`.

`get_profiles_for_scorer()` adds `charge_normalisee` (0→1, relative to team max) dynamically at call time. After assignment, `run_update(delta=+1)` increments `charge_actuelle` in `member_profiles.json`.

**Hybrid ticket auto-start (safety net for agents who never click "Commencer"):**
`sla_watchdog.auto_start_assigned_tickets()` runs on the same periodic scheduler as
`check_all_tickets()` and starts the SLA clock (`sla_engine.on_status_change(ticket,
"in_progress", ...)`) on any assigned ticket still `status == "new"` more than
`AUTO_START_DELAY_MINUTES` (15) after `created_at`. The synthetic start time is anchored at
`created_at + 15min`, not the scan's wall-clock time, so the deadline doesn't drift with the
job's polling frequency. Races against a manual "Commencer" click
(`PATCH /agent/tickets/{numero}/status`, `action="start"`) are closed by
`update_in_db(numero, updates, expected_status="new")` (`api.py`): the write is a silent no-op if
the ticket's status no longer matches `expected_status` when re-read under the lock — whichever
path (manual click or auto-start) writes first wins, the loser doesn't clobber `started_at`.
Covered by `tests/test_hybrid_start.py`.

### Module 3 — Notifications (`src/notifications/`)

Pure Python, no LLM. `NotificationDispatcher.notify_assignment()` is called synchronously from `POST
/classify` and fires three channels: persisted in-app notif (`store.append_notification()`, idempotent),
best-effort SSE push (`sse_manager.publish()`), and a backgrounded email (`BackgroundTasks`, never
blocks the HTTP response). `notify_sla_alert()` follows the same three-channel pattern but is called
from `sla_watchdog.py`'s dedicated thread, so its email send is synchronous (no HTTP response or
asyncio loop to protect there).

SSE is deliberately used instead of WebSocket: the channel is strictly server→client, and native
`EventSource` reconnects automatically with zero client-side logic — see `App.jsx`'s `es.onerror`
handler, which only logs, it doesn't reconnect manually.

### Module 4 — SLA (`src/sla/`)

Pure Python, no LLM, no I/O in `sla_engine.py` (fully unit-testable with fixed dates — see
`tests/test_sla_engine.py`). Business-hours budget per priority:

```
1-Critique: 8h · 2-Majeure: 16h · 3-Mineure: 48h · 4-Standard: 96h   (all in business hours)
```

`on_status_change()` encodes the ticket status state machine and computes deadline updates, including
resuming from a manual pause (`on_hold → in_progress`): the deadline must shift by the **business**
duration of the pause via `add_business_hours()`, never by a raw wall-clock `timedelta` — two historical
bugs (pause spanning a weekend; pause pushing the deadline past 19:00 same day) both stemmed from a
naive wall-clock addition and are covered by dedicated regression scenarios (`test_sla_engine.py`,
"Scénario 3bis"/"3ter") that assert the result differs from the old buggy value, not just that it
matches the new one.

`sla_watchdog.check_all_tickets()` (APScheduler, every 5 min) scans `in_progress`/`on_hold` tickets and
fires 40%/10%/breach tier alerts via `NotificationDispatcher.notify_sla_alert()`, deduped per-ticket via
`sla_alert_40_sent`/`_10_sent`/`_breach_sent` flags on the ticket record (never reset once sent).
`POST /manager/sla-check-now` triggers an out-of-band scan from within the running process (required so
SSE pushes reach already-connected clients).

**Known inconsistency:** `GET /agent/notifications` (older endpoint) still recomputes SLA remaining time
in wall-clock, not via `sla_engine.business_seconds_remaining()` — the two calculations can disagree.
Not yet unified.

**A second, independent SLA-math implementation now exists in the frontend:**
`frontend/src/utils/sla.js` reimplements the business-hours calculation in JavaScript
(`isWorkingTime`, `businessSecsBetween`, `getSlaUrgency`, `getSlaComplianceStats`) — same
Mon–Fri 07:00–19:00 bounds, same pause-freeze semantics — so `SLAMonitorView`, `DashboardView`,
`AgentProfileView`, and `CountdownTimer.jsx` can render SLA countdowns client-side without a
round trip. Its own header comment states the intent is for it to mirror `sla_engine.py` exactly,
precisely so the Monitor and the countdown widget never show two different numbers for the same
ticket. Given this project's own history with parallel/divergent priority calculations (§7.2
above), a change to either implementation's business-hours logic should be mirrored in the other.

### Module 5 — Authentication (`src/auth.py`, `src/keycloak_admin.py`)

Two modes selected by `AUTH_MODE`, both pure Python, no LLM. `legacy` (env default) is the original JWT
HS256 + `users.json` + bcrypt flow, unchanged. `keycloak` validates an access token issued by an external
Keycloak server via JWKS/RS256 (`jwt.PyJWKClient`, cached signing keys — no network call while
`AUTH_MODE=legacy`); it never issues a JWT itself. Role and identity are read from the token's
`realm_access.roles` (admin/agent) and `preferred_username` — **never `sub`**, which is an opaque
Keycloak UUID unrelated to the business ids (`cherazade_hamdi`, etc.) used everywhere else
(`member_profiles.json`, `notifications/store.py`, `sse_manager.subscribe(user_id)`,
`assigned_to.membre_id`). This requires the Keycloak username to have been set equal to the business id
at migration time — a convention, not something the code enforces.

`src/keycloak_admin.py` is a dedicated REST client (`requests`, `client_credentials` service-account
grant — same "one dedicated module, no direct calls elsewhere" principle as `src/servicenow.py`) used
for listing users/roles, setting roles, and triggering Keycloak's password-reset email.
`scripts/migrate_users_to_keycloak.py` migrates `users.json` accounts across (temp password + forced
`UPDATE_PASSWORD`, never the bcrypt hash itself — the two credential stores are deliberately kept
separate).

**`users.json` writes are now transactional, same fix as `member_profiles.json`/`availability.json`:**
`auth.py`'s `users_transaction()` context manager holds `_USERS_LOCK` for the whole read-modify-write
cycle and saves atomically on exit — the same race a plain `load()`/`save()` pair would leave open
under FastAPI's threadpool-executed sync endpoints (see the `profiles_store.py` fix, `DESCRIPTION_PFE.md`
§7.3). `POST /auth/change-password` and `PATCH /users/{id}/role` (legacy mode only — keycloak mode
routes role changes through `keycloak_admin.set_user_role()` instead) both use it.
`tests/test_auth_users_store.py` verifies it the same way `test_profiles_store.py` verifies
`profiles_store.py`: 20 threads incrementing a counter field concurrently, asserting no lost update.

**SSE auth changed as part of this work:** the real auth token (legacy JWT or Keycloak access token) is
never put in a query string. `POST /agent/notifications/sse-ticket` mints a 60s single-use ticket for
the already-authenticated caller; `GET /agent/notifications/stream?ticket=...` consumes it
(`_consume_sse_ticket()`, popped immediately) instead of accepting a JWT/Keycloak token directly. Cost of
this choice: a single-use ticket breaks `EventSource`'s native auto-reconnect (replaying the same,
already-consumed ticket fails), so `frontend/src/App.jsx` implements manual reconnect — close, re-mint a
ticket via a fresh `POST`, reopen, with backoff up to ~15s.

**Frontend is Keycloak-only, no legacy login form:** `frontend/src/utils/api.js` hardcodes a `UserManager`
(`oidc-client-ts`) for the Keycloak Authorization Code + PKCE flow; `LoginPage.jsx` only shows a
redirect/retry screen, never a username/password form. So `AUTH_MODE=legacy` still works at the API level
(tests, scripts, `POST /login`) but has no usable path through the current React app anymore.

**Verified in real conditions** against a dedicated dev stack (`infra/keycloak/` — sibling directory to
this repo and to `frontend/` at the workspace root, not inside this repo; Docker Compose, Keycloak 26 +
Postgres, realm auto-imported, dev-only per its own README — no TLS, plaintext admin password in
`infra/.env`): account migration via `migrate_users_to_keycloak.py`, login as both `agent` and `admin`
roles, and RP-initiated logout. Not yet verified: long-session silent token renewal
(`automaticSilentRenew`), and the realm's SMTP config for password-reset emails. Full writeup:
`DESCRIPTION_PFE.md` section 8.4.

### Pydantic Models (ticket_crew.py)

```python
class TicketInput(BaseModel):
    numero: str
    breve_description: str
    description: Optional[str] = ""
    entreprise: Optional[str] = ""      # drives brand_affinity in scorer

class AssignmentInfo(BaseModel):
    membre_id: str
    nom: str
    score_assignation: float
    justification: str                  # only shown in TicketDetailsModal (not ClassificationModal)

class ClassificationResult(BaseModel):
    numero, categorie, sous_categorie, service: str
    impact, urgence, priorite_calculee: str
    confidence: float
    reasoning: str
    entreprise: Optional[str] = ""
    assigned_to: Optional[AssignmentInfo] = None
```

### Taxonomy (LVMH-specific)

Defined as constants at the top of [src/agents/ticket_crew.py](src/agents/ticket_crew.py):
- **Categories**: Incident, Demande, Assistance, Changement applicatif, Problème applicatif
- **Sub-categories**: Datas, Accès, Logiciel, Application, Production, Evolution, Sécurité, Matériel, Bug
- **Services**: 22 LVMH-specific services (e.g., PCD Retail Scorecard, O365-PowerBI, Guerlain - CRM, PCD - Dior Connect)
- **Priority**: 1-Critique → 4-Standard (from impact × urgence matrix)

## Data Storage

| File | Purpose |
|------|---------|
| `data/raw/incident-10000.xlsx` | Source dataset — do not modify |
| `data/processed/few_shot_examples.json` | 200 stratified examples loaded at agent startup |
| `data/processed/eval_dataset.json` | 500-ticket eval set with ground truth |
| `data/processed/member_profiles.json` | 6 team members with metrics, skills, charge, availability (via `profiles_store.py`) |
| `data/processed/availability.json` | Member availability state (synced with member_profiles.json, via `profiles_store.py`) |
| `data/processed/users.json` | Login accounts: id, email, role (`admin`/`agent`), bcrypt-hashed password |
| `data/output/classifications_db.json` | Sliding window of last 100 API classifications (lock-protected, atomic write) |
| `data/output/notifications.json` | Sliding window of last 1000 in-app notifications (atomic write, via `notifications/store.py`) |
| `data/output/temp_jobs/` | Temporary batch job files |

Batch job state (`JOBS` dict) is **in-memory only** — lost on restart.

## API Endpoint Groups

**Auth**: `POST /login`, `GET /me`, `POST /auth/change-password`, `GET /users`, `PATCH /users/{id}/role`

**Classification & Dispatch**: `POST /classify`, `GET /tickets`, `POST /classify/batch`, `POST /classify/upload`, `GET /jobs/{id}`, `GET /jobs/{id}/download`, `PATCH /jobs/{id}/correct`

**Profiling/Availability**: `POST /profiles/bootstrap`, `GET /profiles`, `GET /profiles/scorer`, `POST /profiles/{id}/availability`, `POST /profiles/{id}/resolve`, `POST /profiles/{id}/charge/increment`, `POST /profiles/{id}/charge/decrement`

**Agent space**: `GET /agent/tickets`, `PATCH /agent/tickets/{numero}/status` (drives `sla_engine.on_status_change`), `GET /agent/profile`

**Notifications**: `GET /agent/notifications` (legacy wall-clock SLA check, see Module 4 note above), `GET /agent/notifications/inbox`, `POST /agent/notifications/read-all`, `POST /agent/notifications/{id}/read`, `POST /agent/notifications/sse-ticket` (mints a 60s single-use ticket for the caller), `GET /agent/notifications/stream` (SSE, authenticated via `?ticket=...` — not the raw JWT/Keycloak token, see Module 5)

**Manager/SLA**: `GET /manager/sla-notifications`, `POST /manager/sla-check-now` (triggers `sla_watchdog.check_all_tickets()` immediately, in-process so SSE reaches connected clients)

**ServiceNow webhooks** (tag `ServiceNow`): `POST /webhook/new-ticket` (called by a ServiceNow Business Rule on incident insert; acks immediately, offloads the real work — classify → assign → save → notify → write back to ServiceNow — to a worker thread via `asyncio.to_thread()`, see below), `POST /webhook/priority-changed` (hidden from `/docs`, notifies admins on Critical-priority crossing only, never touches ServiceNow or the classifier). No automated test covers these two routes (unlike `tests/test_sla_watchdog_integration.py` for the SLA watchdog) — see `DESCRIPTION_PFE.md` section 14.7 for what was verified manually vs. not.

**Why `asyncio.to_thread()` in `/webhook/new-ticket`:** the webhook body (`classify_ticket` → `assign_ticket` → `save_to_db` → `update_ticket`) is a multi-second synchronous blocking call. An earlier version of this endpoint self-called `POST /internal/process-webhook` over an HTTP loopback, based on a claim that `crew.kickoff()` crashed with `"Agent execution was invoked synchronously from within a running event loop"` when triggered via `BackgroundTasks`, a bare `threading.Thread`, or `asyncio.create_task`. That claim was investigated on 2026-07-20 and could not be reproduced against the currently installed `crewai`/`litellm` versions (no `asyncio` reference in the sync LLM call path used here), and the project's own `DESCRIPTION_PFE.md` §14.7 already flagged it as never verified reproducibly (no test script, no logs). What *was* independently demonstrated is a real, version-independent problem: scheduling a multi-second blocking call via `asyncio.create_task()` (or an `async def` passed to `BackgroundTasks`) freezes the whole uvicorn event loop — including SSE streams — for the call's duration. `asyncio.to_thread()` avoids that by construction, so it replaced the loopback: `webhook_new_ticket` now schedules the work with `background_tasks.add_task(asyncio.to_thread, _webhook_worker, payload)` and returns immediately; `_webhook_worker` calls `asyncio.set_event_loop(asyncio.new_event_loop())` before `crew.kickoff()` as defensive insurance in case some code deeper in the stack calls `asyncio.get_event_loop()` from that thread.

**Outbound sync (second ServiceNow integration point, distinct from the two webhooks above):**
`api.py`'s `_sync_hold_status_to_servicenow()` is called from `PATCH /agent/tickets/{numero}/status`
whenever `action` is `pause`/`resume`/`done`, and PATCHes ServiceNow's `state` (plus `hold_reason` on
pause, `close_code`/`close_notes` on done) via `servicenow.update_ticket(..., display_value=True)`.
Best-effort like the rest of the integration — never fails the local request if ServiceNow is
unreachable. `state` and `hold_reason` (or `close_code`/`close_notes`) must be sent in the **same**
PATCH call: ServiceNow silently reverts the state transition if either arrives in a separate call
(discovered empirically, not documented by ServiceNow). An optional free-text `note` goes to the
internal `work_notes` field (never client-visible) and is distinct from `wait_comment`, which goes to
the client-visible `comments` field and is only required for the `contact_principal` wait motive.

## Frontend (`frontend`, sibling directory)

```bash
cd ../frontend
npm install
npm run dev      # http://localhost:5173
npm run build
npm run lint
```

Backend URL is hardcoded as `http://localhost:8000` in `App.jsx`.

**Auth:** `frontend/src/utils/api.js` hardcodes an `oidc-client-ts` `UserManager` for Keycloak
(Authorization Code + PKCE) — no username/password form exists in the UI (`LoginPage.jsx` only redirects
to Keycloak or offers a retry button). `apiFetch()` attaches the current access token, retries once via
`signinSilent()` on a 401, then falls back to `signinRedirect()`. See Module 5 above.

**Kanban logic** (`App.jsx` `mapStatus()`): driven primarily by `ticket.status` — `in_progress`/`on_hold` → `"In Progress"`, `done` → `"Done"`; for `status === "new"`, `assigned_to` present → `"Assigned"`, absent → `"New"`.

**Classification modal:** shows category, priority, confidence, assigned member + score. Justification is NOT shown here — only in `TicketDetailsModal` (opened by clicking a ticket card).

**Real-time notifications:** `App.jsx` calls `POST /agent/notifications/sse-ticket` then opens an
`EventSource` to `GET /agent/notifications/stream?ticket=...` (not the OIDC token — see Module 5). Since
tickets are single-use, native `EventSource` auto-reconnect can't be relied on: `onerror` closes the
connection and `App.jsx` manually re-mints a ticket and reopens, with backoff up to ~15s.
`hooks/useNotifications.js` fans each SSE `"assignment"` event out to three independent channels — sound, in-page toast (`components/ToastContainer.jsx`, auto-dismiss 5s), and browser `Notification` API (permission requested on login via a user gesture, to satisfy autoplay/permission policies).

**Active views:** DashboardView (Kanban + stats), AgentsView, SLAMonitorView (team-wide SLA compliance + alert feed + manual "Scanner maintenant" trigger), AgentDashboardView (agent's own tickets + `CountdownTimer`), AgentNotificationsView (agent's persisted notification inbox), AgentProfileView, SettingsView (accessibility panel, see below — no longer a stub).

**Shared date-range filter:** `components/DateRangeFilter.jsx` + `utils/dateRange.js` provide a
custom start/end date filter (ISO `YYYY-MM-DD` bounds, default range = 1st of the current month
through today) shared by DashboardView, AgentsView, SLAMonitorView, and AgentProfileView. This
replaced an older fixed-preset filter (`utils/period.js`, deleted) and the backend endpoint it
called, `GET /agent/profile/stats?period=` (also removed), in favor of filtering entirely
client-side across all four views for consistent behavior.

**Agent-side shell:** `views/AgentView.jsx` is the agent equivalent of `App.jsx`'s admin shell — its own sidebar (My Tickets / Notifications / My Profile / Settings tabs, unread-count badge polled every 60s from `/agent/notifications` + `/agent/notifications/inbox`) wrapping `AgentDashboardView`/`AgentNotificationsView`/`AgentProfileView`/`SettingsView`. Was not previously called out as a distinct component from the views it wraps.

**Stubs (UI only, no logic):** search/filter, Kanban drag-and-drop. (Settings was a stub as of the last review pass — it now has a real accessibility feature behind it, see below.)

**Accessibility panel (`SettingsView.jsx`, `context/AccessibilityContext.jsx`, `hooks/useAccessibility.js`, `hooks/useTextReader.js`) — added since the last review pass:**
- Global settings object (font size, spacing, cursor size, a color filter enum incl. a custom-HSL-hue picker for background/headings/content colors, link/header/element highlighting, enlarged buttons, a keyboard-nav toggle, a dyslexia-friendly font toggle, and a text-to-speech toggle) held in `AccessibilityContext` (React context, not Redux/Zustand — global state footprint here is small enough not to justify one), persisted to `localStorage` under `smartdispatch_accessibility`.
- Applied globally by setting `data-font-size`/`data-spacing`/`data-cursor-size`/`data-color-filter`/`data-highlight-*`/`data-enlarge-buttons`/`data-dyslexia-font` attributes plus `--custom-bg`/`--custom-bg-sidebar`/`--custom-headings`/`--custom-contents` CSS custom properties on `document.documentElement` — `index.css` (now 555 lines, up from a plain stylesheet) keys its accessibility rules off these attributes/properties, so no component needs conditional class logic for them.
- **Text reader** (`useTextReader.js`): click-to-read using the browser's native `SpeechSynthesis` API (no external TTS dependency) when the `textReader` setting is on. Skips interactive elements (`button, a, input, select, textarea, [role="button"], [contenteditable], svg`) so clicking a control still performs its normal action instead of reading it aloud; non-interactive text elements get a `.a11y-reading` class for the duration of the utterance.
- **`SkipLink.jsx`**: a skip-to-`#main-content` link, visible only on keyboard focus, shown only when the `keyboardNav` setting is enabled (rendered conditionally in both `App.jsx`'s admin shell and the login screen).

**Internationalization (EN/FR) — added since the last review pass:** migrated from a custom context to **`react-i18next`**/`i18next` (new `frontend/package.json` dependencies). `hooks/useLanguage.js` wraps `useTranslation()` behind the same `{ t, language, setLanguage, toggleLanguage }` shape every component already consumed, so the underlying-engine swap required no call-site changes. `i18n/translations.js` is a flat `{ 'nav.dashboard': { en, fr } }` dictionary (~150 keys) reshaped at init time into the two `react-i18next` resource bundles; keys are literal flat identifiers, not dot-path namespaces (`keySeparator`/`nsSeparator` disabled in `i18n/i18n.js` for that reason). Language choice persists to `localStorage` (`smartdispatch_language`, default `"en"`) and syncs `document.documentElement.lang`. `components/LanguageToggle.jsx` is a compact EN|FR control in both the admin sidebar (`App.jsx`) and the agent sidebar (`AgentView.jsx`). `utils/formatDate.js` centralizes locale-aware date/time/number formatting (`fr-FR` vs `en-US`) driven by the current language, replacing what used to be hardcoded `'fr-FR'` calls scattered across components.

Design token: `--primary-color: #f6c026` (LVMH gold).
