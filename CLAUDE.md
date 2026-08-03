# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Layout

This workspace holds two independent projects, developed and run separately (no shared root
tooling — the root `package-lock.json` is a stub, not a real package):

- **`Ticket-Classifier--main - Copie/`** — Python/FastAPI backend (CrewAI multi-agent ticket
  classification, dispatch, SLA monitoring, notifications, ServiceNow integration). This directory
  has its own detailed `.claude/CLAUDE.md` — **read it before working on backend code**; it covers
  the full request flow, module-by-module file map, scoring formulas, and known issues in depth.
  This root file only summarizes what's needed to orient across both projects.
- **`frontend/`** — React 19 + Vite dashboard, sibling to the backend, consumes it over HTTP at a
  hardcoded `http://localhost:8000` base URL.

Treat them as two separate working directories for tooling purposes (separate installs, separate
lint/test runs) — `cd` into the relevant one before running backend or frontend commands.

## Quick Start

```powershell
# Backend (from "Ticket-Classifier--main - Copie/")
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env          # fill in EY Azure gateway + SMTP + ServiceNow + JWT secrets
python run_backend.py           # http://localhost:8000, Swagger at /docs

# Frontend (from "frontend/")
npm install
npm run dev                     # http://localhost:5173
npm run build
npm run lint
```

Backend test commands, the `.env` variable reference, and per-module CLI tools (availability
management, data migration, benchmarking) are documented in
[`Ticket-Classifier--main - Copie/.claude/CLAUDE.md`](Ticket-Classifier--main%20-%20Copie/.claude/CLAUDE.md) — don't duplicate lookups here, go there.

## Architecture, In One Pass

**Core design principle:** LLMs are used only for judgment/free-text generation (interpreting a
natural-language ticket description, writing a French justification sentence). Anything with a
deterministic formula — priority from the impact/urgence matrix, the dispatch score, SLA
deadlines — is computed in pure Python and the LLM's own output for that value is never trusted,
even when the LLM could technically produce it. This was hardened after a real incident (see
below), not designed in from the start.

**Request flow for `POST /classify`:**
```
api.py → ticket_crew.py (CrewAI: Analyst → Classifier → Auditor agents, taxonomy + confidence)
       → sla_engine.compute_priority() overwrites priorite_calculee unconditionally (LLM's value discarded)
       → scorer_agent.py assign_ticket() — Python scoring (ScoreMembersDispatchTool) + LLM justification text only
       → profiling_agent.py increments assignee charge_actuelle
       → save_to_db() (classifications_db.json, atomic write)
       → NotificationDispatcher.notify_assignment() — in-app (sync) + SSE (best-effort) + email (background)
```

**Why the "never trust LLM values" rule exists:** the LLM historically wrote priority labels like
`"1 - Critique"` (with spaces) while `sla_engine.SLA_HOURS` looked them up with canonical keys like
`"1-Critique"`. The mismatch fell through to a default 96h SLA budget on every real ticket — the
entire SLA alerting system was silently broken while unit tests (built on already-canonical
fixtures) stayed green. Fixed by making `sla_engine.compute_priority(impact, urgence)` the single
source of truth, always called after `crew.kickoff()`. Full writeup in
`Ticket-Classifier--main - Copie/DESCRIPTION_PFE.md` §7.2.

**Other structural decisions worth knowing before changing things:**
- JSON files, not a database, for persistence (`profiles_store.py`, `notifications/store.py`, and
  `classifications_db.json` writes all use `threading.Lock` + atomic `.tmp`+`os.replace()` writes to
  compensate) — a deliberate choice given current data volume, paired with a mono-worker Uvicorn
  deployment (in-memory locks would break under multiple workers).
- SSE (not WebSocket) for the one channel that needs real-time push (ticket assignment
  notifications); everything else (Kanban, profiles, SLA monitor) is HTTP polling — the
  unidirectional, low-complexity choice for a server→client-only need.
- SLA watchdog runs on APScheduler's `BackgroundScheduler` (separate thread), not
  `AsyncIOScheduler`, because its email sends are synchronous/blocking SMTP calls that would
  otherwise freeze the whole asyncio event loop (and every connected agent's SSE stream) if run on
  the main loop. The same scheduler also runs `auto_start_assigned_tickets()`, a hybrid safety net
  that auto-starts the SLA clock on any assigned ticket still `"new"` 15 minutes after creation, in
  case the agent never clicks "Commencer" — races against the manual click are closed by an
  `expected_status` guard on `update_in_db()` (whichever path writes first wins, the loser is a
  silent no-op).
- Auth is dual-mode (`AUTH_MODE=legacy` JWT+bcrypt, or `AUTH_MODE=keycloak` JWKS/RS256
  validation-only) at the API level, but the current React app is **Keycloak-only**: there is no
  username/password form anywhere in the UI, only a redirect/retry screen. `legacy` still works for
  tests/scripts/`POST /login`, just not through the deployed frontend.
- ServiceNow integration is bidirectional: two inbound webhooks (`POST /webhook/new-ticket`,
  `POST /webhook/priority-changed`) plus a separate outbound sync
  (`_sync_hold_status_to_servicenow()`) that PATCHes ServiceNow's `state`/`hold_reason`/
  `close_code`/`close_notes` whenever an agent pauses/resumes/completes a ticket locally. Both
  directions are best-effort — a ServiceNow failure never blocks the local request.
- Team-member performance metrics (`member_profiles.json`) are no longer derived from the
  historical Excel file — only identity/skills are. Performance metrics are live-only, fed
  exclusively by real ticket resolutions in the app, and preserved across profile-bootstrap re-runs.

**Frontend/backend contact points:**
- Kanban status mapping lives in `frontend/src/App.jsx`'s `mapStatus()` — driven by
  `ticket.status`, with `assigned_to` presence distinguishing "New" vs "Assigned" only when
  `status === "new"`.
- Real-time notifications: `frontend/src/hooks/useNotifications.js` consumes
  `GET /agent/notifications/stream` (SSE). Since `EventSource` can't set custom headers, the real
  auth token (legacy JWT or Keycloak access token) is never put in the query string — `App.jsx` first
  calls `POST /agent/notifications/sse-ticket` to mint a 60s single-use ticket, then opens the stream
  with `?ticket=...`. That single-use ticket breaks `EventSource`'s native auto-reconnect, so `App.jsx`
  reconnects manually (re-mint + reopen, backoff up to ~15s) on `onerror`. Each event fans out to
  sound + toast + browser `Notification` API.
- Accessibility and i18n are both frontend-only, no backend involvement: an `AccessibilityContext`
  (font size, spacing, cursor size, color filters, highlighting, keyboard-nav, dyslexia font,
  click-to-read via the browser's native `SpeechSynthesis` API) persisted to `localStorage`, and
  `react-i18next`-based EN/FR translation (`i18n/translations.js`, ~150 flat keys) persisted
  separately. Both live behind `SettingsView`/`LanguageToggle`, applied via `data-*` attributes on
  `document.documentElement`.
- `components/DateRangeFilter.jsx` + `utils/dateRange.js` provide one shared, 100%-client-side
  date-range filter used by four views (Dashboard, Agents, SLA Monitor, Agent Profile), replacing an
  older per-view preset filter and the backend endpoint it used to call.
- `frontend/src/utils/sla.js` is a second, independent implementation of the backend's business-hours
  SLA math, kept in sync by convention (not by any shared code) so `SLAMonitorView`/`CountdownTimer`
  never disagree with the server — worth double-checking if you change either side's business-hours
  logic, given this project's prior history with divergent parallel SLA calculations.
- Design token: `--primary-color: #f6c026` (LVMH gold).

For anything deeper — full endpoint list, Pydantic models, taxonomy constants, per-file
responsibilities, data storage schema, or the ServiceNow webhook integration — see
[`Ticket-Classifier--main - Copie/.claude/CLAUDE.md`](Ticket-Classifier--main%20-%20Copie/.claude/CLAUDE.md).
