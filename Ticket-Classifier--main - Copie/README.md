# AI Ticket Dispatch System — LVMH Power BI

An intelligent, multi-agent system powered by **CrewAI** and **FastAPI** that automatically classifies IT support tickets into ITIL taxonomy, calculates SLA priority, and assigns tickets to the best available team member based on skills, workload, and brand affinity.

## Features

- **Three-agent CrewAI pipeline** — Analyst → Classifier → Quality Auditor run sequentially; confidence score and reasoning included in every result
- **Deterministic priority** — 3×3 impact/urgence matrix (`PriorityCalculatorTool`) bypasses LLM for priority assignment
- **Few-shot learning** — 200 stratified examples from historical data injected at classification time via keyword matching
- **Member profiling** — Pure-Python engine bootstrapped from 10K historical tickets; tracks resolution times, reopen rate, skill set, and composite performance score
- **Intelligent dispatch** — Scorer Agent (CrewAI) assigns each ticket using a multi-criteria formula: skill match, brand affinity, workload, and performance
- **Brand-aware routing** — Ticket `entreprise` field influences assignment; members with Guerlain/Dior/etc. history are preferred for those brands
- **Assignment justification** — LLM generates a French explanation for every assignment decision, visible in ticket detail view
- **Async batch processing** — Upload Excel files; poll job progress; download results
- **Kanban board** — Classified + assigned tickets appear in the "Assigned" column automatically

## Setup

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # fill in your LLM credentials
```

### Environment variables (`.env`)

#### EY Azure OpenAI Gateway (current configuration)

| Variable | Value |
|----------|-------|
| `OPENAI_API_KEY` | Your EY APIM subscription key |
| `OPENAI_ENDPOINT` | `https://eyq-incubator.europe.fabric.ey.com/eyq/eu/api` |
| `OPENAI_API_VERSION` | `2024-02-15-preview` |
| `OPENAI_MODEL_NAME` | `gpt-4o` |

#### Alternative providers

| Variable | Purpose |
|----------|---------|
| `GROQ_API_KEY` | Groq inference (llama-3.1-8b-instant) — free tier |
| `ANTHROPIC_API_KEY` | Claude models |

> The `_build_llm()` helper in `ticket_crew.py` and `scorer_agent.py` reads these variables automatically. To switch provider, update `OPENAI_ENDPOINT` and `OPENAI_MODEL_NAME`.

## Running

```powershell
# Backend — http://localhost:8000  |  Swagger UI at /docs
python run_backend.py

# Frontend (separate repo at C:\Users\DELL\Desktop\frontend)
cd C:\Users\DELL\Desktop\frontend
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
  → scorer_agent.py         assign_ticket()
      Python                ScoreMembersDispatchTool — score all available members
      LLM                   generate French justification phrase
  → api.py                  save to DB, increment assignee charge
  ← ClassificationResult (with assigned_to + justification)
```

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

`src/agents/profiling_agent.py` bootstraps profiles from `data/raw/incident-10000.xlsx`:
- Filters on `WW - POWERBI - L2` group, matches members by email
- Computes: resolution times, reopen rate, priority breakdown, top services/sub-categories
- Infers skills from sub-categories via `SOUS_CAT_TO_SKILLS` map
- **Auto-discovery rule:** >85% success on ≥5 tickets in a category → skill added automatically
- `get_profiles_for_scorer()` adds `charge_normalisee` dynamically at call time

### Taxonomy (LVMH-specific)

| Field | Values |
|-------|--------|
| Category | Incident, Demande, Assistance, Changement applicatif, Problème applicatif |
| Sub-category | Datas, Accès, Logiciel, Application, Production, Evolution, Sécurité, Matériel, Bug |
| Priority | 1-Critique, 2-Majeur, 3-Mineur, 4-Standard |
| Services | 22 LVMH services (PCD Retail Scorecard, O365-PowerBI, Guerlain CRM, Dior Connect, …) |

## API Reference

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
| POST | `/profiles/bootstrap` | Initialize profiles from raw Excel |
| GET | `/profiles` | All member profiles |
| GET | `/profiles/scorer` | Profiles with `charge_normalisee` for dispatch |
| POST | `/profiles/{id}/availability` | Set member disponible + raison |
| POST | `/profiles/{id}/resolve` | Post-resolution metric update + skill discovery |
| POST | `/profiles/{id}/charge/increment` | +1 active ticket |
| POST | `/profiles/{id}/charge/decrement` | −1 active ticket |

## Data Files

| File | Purpose |
|------|---------|
| `data/raw/incident-10000.xlsx` | Source dataset — do not modify |
| `data/processed/few_shot_examples.json` | 200 stratified examples for in-context learning |
| `data/processed/eval_dataset.json` | 500-ticket evaluation set with ground truth |
| `data/processed/member_profiles.json` | 6 team members with metrics, skills, charge, availability |
| `data/processed/availability.json` | Member availability state (synced with profiles) |
| `data/output/classifications_db.json` | Last 100 classifications (sliding window) |
| `data/output/temp_jobs/` | Temporary batch job files |

## Frontend (`C:\Users\DELL\Desktop\frontend`)

React 19 + Vite — backend URL hardcoded as `http://localhost:8000`.

**Active views:**
- **Dashboard** — Stats + Kanban (New / Assigned / In Progress). Tickets with `assigned_to` land in "Assigned" automatically.
- **Agents** — Team member profiles and availability
- **SLA Monitor** — Ticket SLA tracking

**Classification flow:**
1. Click "+ New Ticket" → fill description + company/brand
2. `POST /classify` → classification + assignment in one call (~15–30s with gpt-4o)
3. Modal shows: category, priority, confidence, assigned member (no justification)
4. Ticket appears in "Assigned" Kanban column
5. Click ticket → full details including assignment justification

**Stubs (UI only, no logic):** Notifications, Settings, search/filter, Kanban drag-and-drop.

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

# Integration tests (backend must be running)
python tests/test_api.py
python tests/test_api.py path/to/tickets.xlsx
```

---

*Developed for the EY Data Team — LVMH Power BI Support — Module 1 (Classification) + Module 2 (Profiling & Dispatch)*
