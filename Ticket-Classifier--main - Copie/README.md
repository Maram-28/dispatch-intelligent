# AI Ticket Dispatch System — LVMH Power BI

An intelligent, multi-agent system powered by **CrewAI** and **FastAPI** that automatically classifies IT support tickets into ITIL taxonomy, calculates SLA priority, assigns tickets to the best available team member, and keeps everyone in sync via real-time notifications, SLA monitoring, and a bidirectional ServiceNow integration.

## Features

- **Three-agent CrewAI pipeline** — Analyst → Classifier → Quality Auditor run sequentially; confidence score and reasoning included in every result
- **Deterministic priority** — 3×3 impact/urgence matrix (`sla_engine.compute_priority()`) is the single source of truth for `priorite_calculee`; the LLM's own priority output is always overwritten, never trusted
- **Few-shot learning** — 200 stratified examples from historical data injected at classification time via keyword matching
- **Member profiling** — identity/skills bootstrapped from 10K historical tickets; performance metrics (resolution time, SLA compliance, etc.) are live-only, fed exclusively by real ticket resolutions and preserved across bootstrap re-runs
- **Intelligent dispatch** — Scorer Agent (CrewAI) assigns each ticket using a multi-criteria formula: skill match, brand affinity, workload, and performance
- **Brand-aware routing** — Ticket `entreprise` field influences assignment; members with Guerlain/Dior/etc. history are preferred for those brands
- **Assignment justification** — LLM generates a French explanation for every assignment decision, visible in ticket detail view
- **SLA monitoring** — business-hours (Mon–Fri 07:00–19:00) countdown per priority, tiered alerts (40%/10%/breach) with manager escalation, and a hybrid safety net that auto-starts the clock if an agent never clicks "Commencer"
- **Real-time notifications** — in-app + SSE push + email on every assignment and SLA alert
- **Dual-mode authentication** — legacy JWT+bcrypt, or Keycloak (JWKS/RS256); the deployed frontend is Keycloak-only
- **ServiceNow integration** — inbound webhooks turn new/updated ServiceNow incidents into classified, assigned tickets; local pause/resume/resolve actions sync back to ServiceNow
- **Async batch processing** — Upload Excel files; poll job progress; download results
- **Kanban board** — Classified + assigned tickets appear in the "Assigned" column automatically

## Setup

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # fill in LLM + auth + SMTP + ServiceNow credentials
```

### Environment variables (`.env`)

#### EY Azure OpenAI Gateway (current configuration)

| Variable | Value |
|----------|-------|
| `OPENAI_API_KEY` | Your EY APIM subscription key |
| `OPENAI_ENDPOINT` | `https://eyq-incubator.europe.fabric.ey.com/eyq/eu/api` |
| `OPENAI_API_VERSION` | `2024-02-15-preview` |
| `OPENAI_MODEL_NAME` | `gpt-4o` |

> The `_build_llm()` helper in `ticket_crew.py` and `scorer_agent.py` reads these variables automatically. To switch provider, update `OPENAI_ENDPOINT` and `OPENAI_MODEL_NAME`. Never pass `api_version` to the LLM constructor — the EY gateway returns 400 (the version lives in the URL only).

#### Auth, notifications, ServiceNow

| Variable | Purpose |
|----------|---------|
| `AUTH_MODE` | `legacy` (default, JWT+bcrypt) or `keycloak` (JWKS/RS256 validation only) |
| `JWT_SECRET`, `JWT_EXPIRE_MINUTES` | Legacy JWT signing (dev default in `src/auth.py` — change in production) |
| `KEYCLOAK_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_FRONTEND_CLIENT_ID`, `KEYCLOAK_BACKEND_CLIENT_ID`, `KEYCLOAK_BACKEND_CLIENT_SECRET` | `AUTH_MODE=keycloak` only — see `infra/keycloak/README.md` |
| `SSE_TICKET_SECRET` | Signs short-lived SSE auth tickets — unrelated to `JWT_SECRET` |
| `FRONTEND_ORIGIN` | Single-origin CORS allowlist |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_SENDER_NAME` | Gmail SMTP (STARTTLS, port 587); `SMTP_PASSWORD` must be a Gmail app password. Missing SMTP creds → email sending is silently skipped, everything else still works |
| `PLATFORM_URL` | Base URL used in notification email links |
| `SN_INSTANCE`, `SN_USER`, `SN_PASSWORD` | ServiceNow instance + technical account (Basic Auth) |

Full variable reference (including a couple of unused/leftover ones) lives in
[`.claude/CLAUDE.md`](.claude/CLAUDE.md).

## Running

```powershell
# Backend — http://localhost:8000  |  Swagger UI at /docs
python run_backend.py

# Frontend (sibling directory, same workspace)
cd ..\frontend
npm install
npm run dev        # http://localhost:5173
```

## Architecture

### Full request flow

```
POST /classify
  → src/api.py              validate TicketInput (numero, breve_description, description, entreprise)
  → ticket_crew.py          classify_ticket()
      Agent 1 — Analyst     extract intent, service, LVMH brand
      Agent 2 — Classifier  assign taxonomy, call PriorityCalculatorTool (deterministic)
      Agent 3 — Auditor     validate JSON, output ClassificationResult with confidence
  → sla_engine.compute_priority()  unconditionally overwrites priorite_calculee — LLM's value discarded
  → scorer_agent.py         assign_ticket()
      Python                ScoreMembersDispatchTool — score all available members
      LLM                   generate French justification phrase
  → profiling_agent.py      increments assignee charge_actuelle
  → save_to_db()            persist to classifications_db.json (atomic write)
  → NotificationDispatcher.notify_assignment()  in-app (sync) + SSE (best-effort) + email (background)
  ← ClassificationResult (with assigned_to + justification)
```

**Why the SLA-overwrite step exists:** the LLM historically wrote priority labels like `"1 - Critique"`
(with spaces) while the SLA lookup used canonical keys like `"1-Critique"` — every real ticket
silently fell back to the 96h default budget, defeating the whole SLA watchdog while unit tests (built
on already-canonical fixtures) stayed green. Full writeup in `DESCRIPTION_PFE.md` §7.2.

### Scorer Agent — dispatch formula

```
score = match_competence × 0.35
      + brand_affinity    × 0.25
      + (1 − charge_norm) × 0.25
      + performance_norm  × 0.15

match_competence = (score_sous_cat + score_service) / 2
  score_sous_cat  = skills_found / skills_required  (gradual, 0→1)
  score_service   = 1.0 if service skill present, else 0.0

brand_affinity  = member_services_matching_brand / total_member_services
charge_norm     = charge_actuelle / max_charge_team  (0=free, 1=most loaded)
performance_norm = score_performance / max_score_team
```

**Hard filter:** members with `disponible=false` are excluded before scoring — they are never assigned.

**Hybrid approach:** Python computes the ranking deterministically; the LLM only generates the justification sentence. This avoids LLM hallucination on tool calls.

### Member profiling

`src/agents/profiling_agent.py`:
- **Identity and skills** are bootstrapped from `data/raw/incident-10000.xlsx` (filtered on the
  `WW - POWERBI - L2` group, matched by email). Skills are inferred from sub-categories via the
  `SOUS_CAT_TO_SKILLS` map; auto-discovery adds a skill when a member has >85% success on ≥5 tickets
  in a category.
- **Performance metrics** (resolution times, SLA compliance, priority breakdown, score) are **not**
  derived from the Excel file — they're fed exclusively by real ticket resolutions
  (`update_after_resolution()`) and preserved across bootstrap re-runs, so re-running bootstrap to
  onboard a new member no longer wipes everyone else's accumulated progress.
- `get_profiles_for_scorer()` adds `charge_normalisee` dynamically at call time.

### SLA monitoring

`src/sla/sla_engine.py` computes business-hours (Mon–Fri 07:00–19:00) deadlines per priority:
`1-Critique` 8h · `2-Majeure` 16h · `3-Mineure` 48h · `4-Standard` 96h. `sla_watchdog.py` scans every 5
minutes, fires tiered alerts (40% consumed / 10% remaining / breached, deduped per ticket) with manager
escalation on the top two tiers, and auto-starts the clock (`auto_start_assigned_tickets()`) on any
assigned ticket still `"new"` 15 minutes after creation, in case the agent never clicked "Commencer".

### Taxonomy (LVMH-specific)

| Field | Values |
|-------|--------|
| Category | Incident, Demande, Assistance, Changement applicatif, Problème applicatif |
| Sub-category | Datas, Accès, Logiciel, Application, Production, Evolution, Sécurité, Matériel, Bug |
| Priority | 1-Critique, 2-Majeur, 3-Mineur, 4-Standard |
| Services | 22 LVMH services (PCD Retail Scorecard, O365-PowerBI, Guerlain CRM, Dior Connect, …) |

## API Reference

### Auth

| Method | Path | Description |
|--------|------|-------------|
| POST | `/login` | Legacy JWT login (`AUTH_MODE=legacy`) |
| GET | `/me` | Current user |
| POST | `/auth/change-password` | Legacy mode only |
| GET | `/users` | List accounts |
| PATCH | `/users/{id}/role` | Change a user's role |

### Classification & Dispatch

| Method | Path | Description |
|--------|------|-------------|
| POST | `/classify` | Classify + assign a single ticket (sync) |
| GET | `/tickets` | All classified tickets (last 100) |
| POST | `/classify/batch` | Classify multiple tickets (async, returns `job_id`) |
| POST | `/classify/upload` | Upload Excel file for async processing |
| GET | `/jobs/{id}` | Poll batch job progress |
| GET | `/jobs/{id}/download` | Download results as Excel |
| PATCH | `/jobs/{id}/correct` | Manual correction |

### Profiling & Availability

| Method | Path | Description |
|--------|------|-------------|
| POST | `/profiles/bootstrap` | Initialize/refresh identity+skills from raw Excel (performance metrics preserved) |
| GET | `/profiles` | All member profiles |
| GET | `/profiles/scorer` | Profiles with `charge_normalisee` for dispatch |
| POST | `/profiles/{id}/availability` | Set member disponible + raison |
| POST | `/profiles/{id}/resolve` | Post-resolution metric update + skill discovery |
| POST | `/profiles/{id}/charge/increment` | +1 active ticket |
| POST | `/profiles/{id}/charge/decrement` | −1 active ticket |

### Agent space

| Method | Path | Description |
|--------|------|-------------|
| GET | `/agent/tickets` | Tickets assigned to the current agent |
| PATCH | `/agent/tickets/{numero}/status` | Start / pause / resume / complete — drives the SLA state machine |
| GET | `/agent/profile` | Current agent's own profile |

### Notifications

| Method | Path | Description |
|--------|------|-------------|
| GET | `/agent/notifications` | Legacy SLA check (wall-clock, not business-hours — known inconsistency) |
| GET | `/agent/notifications/inbox` | Persisted in-app notification inbox |
| POST | `/agent/notifications/read-all` | Mark all as read |
| POST | `/agent/notifications/{id}/read` | Mark one as read |
| POST | `/agent/notifications/sse-ticket` | Mint a 60s single-use ticket for the SSE stream below |
| GET | `/agent/notifications/stream` | SSE push, authenticated via `?ticket=...` (not the raw JWT/Keycloak token) |

### Manager / SLA

| Method | Path | Description |
|--------|------|-------------|
| GET | `/manager/sla-notifications` | Team-wide SLA alert feed |
| POST | `/manager/sla-check-now` | Trigger an out-of-band SLA scan immediately |

### ServiceNow (inbound webhooks, tag `ServiceNow`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/webhook/new-ticket` | Business Rule on incident insert — acks immediately, classifies/assigns/writes back off the request thread |
| POST | `/webhook/priority-changed` | Hidden from `/docs` — notifies admins on Critical-priority crossing only |

Local pause/resume/complete actions (`PATCH /agent/tickets/{numero}/status`) also sync back to
ServiceNow's `state`/`hold_reason`/`close_code`/`close_notes` — a separate, outbound path from the
two webhooks above. All ServiceNow calls are best-effort and never block the local request.

## Data Files

| File | Purpose |
|------|---------|
| `data/raw/incident-10000.xlsx` | Source dataset — do not modify |
| `data/processed/few_shot_examples.json` | 200 stratified examples for in-context learning |
| `data/processed/eval_dataset.json` | 500-ticket evaluation set with ground truth |
| `data/processed/member_profiles.json` | 6 team members with metrics, skills, charge, availability |
| `data/processed/availability.json` | Member availability state (synced with profiles) |
| `data/processed/users.json` | Login accounts (legacy mode): id, email, role, bcrypt hash |
| `data/output/classifications_db.json` | Last 100 classifications (sliding window, atomic write) |
| `data/output/notifications.json` | Last 1000 in-app notifications (sliding window, atomic write) |
| `data/output/temp_jobs/` | Temporary batch job files |

## Frontend (`../frontend`, sibling directory)

React 19 + Vite — backend URL hardcoded as `http://localhost:8000`. Authentication is Keycloak-only in
this app (Authorization Code + PKCE via `oidc-client-ts`) — there's no username/password form in the UI.

**Active views:**
- **Dashboard** — Stats + Kanban (New / Assigned / In Progress / Done)
- **Agents** — Team member profiles and availability
- **SLA Monitor** — team-wide SLA compliance, alert feed, manual scan trigger
- **Agent space** (My Tickets / Notifications / My Profile / Settings) — an agent's own tickets with countdown timers, persisted notification inbox, and an accessibility panel (font size, color filters, keyboard nav, click-to-read via the browser's `SpeechSynthesis` API)

Also includes EN/FR internationalization (`react-i18next`) and a shared client-side date-range filter
used across four views.

**Classification flow:**
1. Click "+ New Ticket" → fill description + company/brand
2. `POST /classify` → classification + assignment in one call (~15–30s with gpt-4o)
3. Modal shows: category, priority, confidence, assigned member (no justification)
4. Ticket appears in "Assigned" Kanban column
5. Click ticket → full details including assignment justification

**Stubs (UI only, no logic):** search/filter, Kanban drag-and-drop.

## Additional Scripts

```powershell
# Rebuild training data from raw Excel
python src/preprocessing/prepare_data.py

# Accuracy benchmark (full CrewAI pipeline; ~10s between requests)
python evaluate_agents.py          # edit n_samples on line 88

# Manage team availability
python -m src.agents.set_availability --liste
python -m src.agents.set_availability --membre cherazade_hamdi --dispo false --raison "Congé"
python -m src.agents.set_availability --membre all --dispo true

# One-shot data migrations (dry-run by default; add --apply to write)
python scripts/migrate_priorite_calculee.py           # backfills the priority-format bug fix
python scripts/reset_profile_stats.py                 # transitions member_profiles.json to live-only metrics
python scripts/migrate_users_to_keycloak.py            # migrates users.json accounts into Keycloak

# Integration tests (backend must be running)
python tests/test_api.py
python tests/test_api.py path/to/tickets.xlsx

# Unit/integration tests needing no running backend (fixed dates / snapshot files)
python tests/test_sla_engine.py
python tests/test_sla_watchdog.py
python tests/test_hybrid_start.py
python tests/test_profiles_store.py
python tests/test_auth_users_store.py
```

Full command reference, module-by-module file map, and known issues:
[`.claude/CLAUDE.md`](.claude/CLAUDE.md) and [`DESCRIPTION_PFE.md`](DESCRIPTION_PFE.md).

---

*Developed for the EY Data Team — LVMH Power BI Support*
