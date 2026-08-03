# SmartDispatch — AI Ticket Classification & Dispatch System

**LVMH Power BI Support · EY Data Team**

An intelligent, multi-agent system that automatically classifies IT support tickets into ITIL
taxonomy, calculates SLA priority, dispatches each ticket to the best available team member, and
keeps everyone in sync through real-time notifications, SLA monitoring, and a bidirectional
ServiceNow integration — all behind a React dashboard.

<p align="center">
  <img src="Ticket-Classifier--main%20-%20Copie/assets/ui_dashboard.jpg" alt="Dashboard" width="80%">
</p>

---

## Table of Contents

- [What it does](#what-it-does)
- [Screenshots](#screenshots)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Repository layout](#repository-layout)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Testing](#testing)
- [Documentation](#documentation)
- [Credits](#credits)

## What it does

1. **Classifies** every incoming ticket into the LVMH ITIL taxonomy (category, sub-category,
   service, impact, urgence) using a three-agent CrewAI pipeline (Analyst → Classifier →
   Auditor), with confidence score and reasoning attached to every result.
2. **Calculates SLA priority deterministically** — a 3×3 impact/urgence matrix, computed in pure
   Python, always overrides whatever the LLM produced. Nothing with a formula is ever trusted from
   free-text LLM output; only judgment calls (interpreting the ticket, writing the assignment
   justification) go through the model.
3. **Dispatches** the ticket to the best available team member via a Scorer Agent that combines a
   deterministic Python score (skills, workload, brand affinity, historical performance) with an
   LLM-written French justification sentence.
4. **Monitors SLA** on business hours (Mon–Fri, 07:00–19:00), alerting at 40% consumed / 10%
   remaining / breached, escalating to managers, and auto-starting the clock if an agent forgets
   to click "Commencer".
5. **Notifies in real time** — in-app notifications, a live SSE push to the dashboard, and email —
   on every assignment and SLA alert.
6. **Integrates with ServiceNow** bidirectionally: incidents created or updated in ServiceNow flow
   into the classification pipeline via webhooks, and local status changes (pause/resume/resolve)
   sync back out.
7. **Serves a role-aware dashboard** (React 19 + Vite) — admin Kanban/SLA/agent views and an agent
   workspace, authenticated via JWT or Keycloak, with built-in accessibility and EN/FR
   internationalization.

## Screenshots

| Ticket classification | Agent profiles | SLA monitoring |
|:---:|:---:|:---:|
| ![Input](Ticket-Classifier--main%20-%20Copie/assets/api_input.png) | ![Agents](Ticket-Classifier--main%20-%20Copie/assets/ui_agents.jpg) | ![SLA](Ticket-Classifier--main%20-%20Copie/assets/ui_sla.jpg) |

## Architecture

```
                        ┌─────────────────────────────────────────────┐
ServiceNow  ──webhook──►│                                               │
                        │              FastAPI backend                 │
React dashboard ──HTTP─►│                                               │
                        │  ┌─────────────┐   ┌──────────────────────┐  │
                        │  │  CrewAI      │   │  sla_engine.py       │  │
                        │  │  3-agent     │──►│  deterministic       │  │
                        │  │  classifier  │   │  priority + SLA math │  │
                        │  └─────────────┘   └──────────┬───────────┘  │
                        │                                │              │
                        │  ┌─────────────┐   ┌───────────▼───────────┐  │
                        │  │  Scorer      │◄──│  member_profiles.json │  │
                        │  │  Agent       │   │  (skills, charge,     │  │
                        │  │  (dispatch)  │   │   live performance)   │  │
                        │  └──────┬───────┘   └────────────────────────┘  │
                        │         │                                       │
                        │         ▼                                       │
                        │  NotificationDispatcher — in-app · SSE · email  │
                        └─────────────────────────────────────────────┘
```

**Design principle:** LLMs are used only for judgment and free-text generation (interpreting a
ticket description, writing a justification sentence). Anything with a deterministic formula —
priority, dispatch score, SLA deadlines — is computed in pure Python; the LLM's own output for
those values is discarded, even when it could technically produce them. This was hardened after a
real incident where an LLM-formatted priority label silently broke SLA tracking on every ticket —
see [`DESCRIPTION_PFE.md` §7.2](Ticket-Classifier--main%20-%20Copie/DESCRIPTION_PFE.md).

Data is persisted as JSON files (not a database) — a deliberate choice at the project's current
volume — with `threading.Lock` + atomic `.tmp`+`os.replace()` writes to keep concurrent requests
safe under a mono-worker deployment.

## Tech stack

| Layer | Technology |
|---|---|
| Classification / dispatch agents | CrewAI, LangChain OpenAI / LiteLLM, GPT-4o (via EY's Azure APIM gateway) |
| Backend API | FastAPI, Uvicorn, Pydantic 2 |
| Scheduling | APScheduler (SLA watchdog, hybrid ticket auto-start) |
| Auth | PyJWT + bcrypt (legacy mode) or Keycloak / JWKS-RS256 (`python-jose`, `oidc-client-ts`) |
| Notifications | SSE (`asyncio.Queue`), SMTP (Gmail, STARTTLS) |
| External integration | ServiceNow REST API (inbound webhooks + outbound sync) |
| Frontend | React 19, Vite, `react-i18next`, `oidc-client-ts`, Framer Motion |
| Data | JSON files (`data/processed/`, `data/output/`) — no database |
| Source data | `incident-10000.xlsx` — 10,000 historical LVMH IT tickets |

## Repository layout

This workspace holds two independently run projects (no shared root tooling):

```
Dispatch-Intelligent-Final/
├── Ticket-Classifier--main - Copie/   # Python/FastAPI backend
│   ├── src/
│   │   ├── agents/        # ticket_crew.py, scorer_agent.py, profiling_agent.py, profiles_store.py
│   │   ├── sla/           # sla_engine.py, sla_watchdog.py
│   │   ├── notifications/ # dispatcher.py, email_sender.py, sse_manager.py, store.py
│   │   ├── api.py         # all FastAPI routes
│   │   ├── auth.py        # legacy JWT + Keycloak validation
│   │   └── servicenow.py  # ServiceNow REST client
│   ├── data/               # raw source Excel + processed/output JSON stores
│   ├── scripts/            # one-shot migrations
│   ├── tests/               # unit + integration tests
│   ├── README.md           # backend-specific setup & API reference
│   └── DESCRIPTION_PFE.md  # full technical write-up (French, PFE report)
├── frontend/                # React 19 + Vite dashboard
│   └── src/
│       ├── views/           # Dashboard, Agents, SLA Monitor, Agent workspace, Settings
│       ├── hooks/, context/ # notifications, accessibility, i18n
│       └── utils/           # date-range filter, client-side SLA math
└── CLAUDE.md                # cross-project orientation notes
```

Treat the two projects as separate working directories for tooling purposes — `cd` into the
relevant one before running backend or frontend commands.

## Getting started

### Backend

```powershell
cd "Ticket-Classifier--main - Copie"
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # fill in LLM + auth + SMTP + ServiceNow credentials
python run_backend.py       # http://localhost:8000, Swagger at /docs
```

### Frontend

```powershell
cd frontend
npm install
npm run dev                 # http://localhost:5173
```

Full setup, environment variables, and troubleshooting live in the backend's own
[`README.md`](Ticket-Classifier--main%20-%20Copie/README.md).

## Configuration

At minimum you'll need an OpenAI-compatible LLM endpoint (this project targets EY's Azure APIM
gateway running GPT-4o). Optional but recommended for the full feature set: SMTP credentials for
email notifications, and ServiceNow instance credentials for the bidirectional integration. Auth
defaults to a self-contained JWT mode (`AUTH_MODE=legacy`) that needs no external service; a
Keycloak mode is also supported (`AUTH_MODE=keycloak`), which is what the deployed frontend
actually uses — see the backend docs for the full variable reference.

## Testing

```powershell
cd "Ticket-Classifier--main - Copie"

# Integration tests (backend must be running)
python tests/test_api.py

# Unit/integration tests needing no running backend
python tests/test_sla_engine.py
python tests/test_sla_watchdog.py
python tests/test_hybrid_start.py
python tests/test_profiles_store.py
python tests/test_auth_users_store.py
```

```powershell
cd frontend
npm run lint
```

## Documentation

| Document | Covers |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Cross-project orientation, request flow, key structural decisions |
| [`Ticket-Classifier--main - Copie/README.md`](Ticket-Classifier--main%20-%20Copie/README.md) | Backend setup, full API reference, formulas, data files |
| [`Ticket-Classifier--main - Copie/.claude/CLAUDE.md`](Ticket-Classifier--main%20-%20Copie/.claude/CLAUDE.md) | Deep engineering reference: module-by-module file map, known issues |
| [`Ticket-Classifier--main - Copie/DESCRIPTION_PFE.md`](Ticket-Classifier--main%20-%20Copie/DESCRIPTION_PFE.md) | Full technical write-up in French (PFE report) — design rationale, audits, limitations |

## Credits

Developed for the EY Data Team — LVMH Power BI Support.
