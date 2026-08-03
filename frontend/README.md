# SmartDispatch — Frontend

React 19 + Vite dashboard for the LVMH ticket classification/dispatch system. Consumes the
[backend API](../Ticket-Classifier--main%20-%20Copie/) over HTTP at a hardcoded
`http://localhost:8000` base URL (`src/utils/api.js`).

For the full project overview (architecture, screenshots, both projects together), see the
[root README](../README.md).

## Setup

```powershell
npm install
npm run dev        # http://localhost:5173
npm run build
npm run lint
```

## Authentication

Keycloak-only: `src/utils/api.js` hardcodes an `oidc-client-ts` `UserManager` for the
Authorization Code + PKCE flow. There is no username/password form anywhere in the UI —
`LoginPage.jsx` only shows a redirect-to-Keycloak / retry screen. `apiFetch()` attaches the
current access token to every request, retries once via `signinSilent()` on a 401, and falls back
to a full `signinRedirect()` if that fails.

## Active views

| View | Role | Notes |
|---|---|---|
| `DashboardView` | Admin | Kanban (New / Assigned / In Progress / Done) + stats |
| `AgentsView` | Admin | Team member profiles, skills, workload, availability |
| `SLAMonitorView` | Admin | Team-wide SLA compliance, alert feed, manual "Scanner maintenant" trigger |
| `AgentView` | Agent | Sidebar shell (My Tickets / Notifications / My Profile / Settings) wrapping the views below |
| `views/agent/AgentDashboardView` | Agent | Own assigned tickets, status lifecycle, `CountdownTimer` |
| `views/agent/AgentNotificationsView` | Agent | Persisted in-app notification inbox |
| `views/agent/AgentProfileView` | Agent | Own profile + performance |
| `SettingsView` | Both | Accessibility panel (see below) |

**Stubs (UI only, no logic):** search/filter, Kanban drag-and-drop.

## Real-time notifications

`hooks/useNotifications.js` opens an `EventSource` to `GET /agent/notifications/stream`. Since
`EventSource` can't set custom headers, the real auth token never goes in the query string:
`App.jsx` first calls `POST /agent/notifications/sse-ticket` to mint a 60s single-use ticket, then
opens the stream with `?ticket=...`. That single-use ticket breaks native auto-reconnect, so
`App.jsx` reconnects manually (re-mint + reopen, backoff up to ~15s) on `onerror`. Each event fans
out to sound, an in-page toast (`components/ToastContainer.jsx`), and the browser `Notification`
API.

## Accessibility & internationalization

- **Accessibility** (`context/AccessibilityContext.jsx`, `hooks/useAccessibility.js`,
  `hooks/useTextReader.js`, `components/SkipLink.jsx`): font size, spacing, cursor size, color
  filters (incl. custom HSL background/heading/content colors), link/element highlighting,
  enlarged buttons, keyboard-nav mode, a dyslexia-friendly font, and click-to-read text-to-speech
  via the browser's native `SpeechSynthesis` API. Settings persist to `localStorage`
  (`smartdispatch_accessibility`) and apply globally via `data-*` attributes/CSS custom properties
  on `document.documentElement`.
- **i18n** (`i18n/i18n.js`, `i18n/translations.js`, `hooks/useLanguage.js`,
  `components/LanguageToggle.jsx`): EN/FR via `react-i18next`, a flat ~150-key dictionary,
  persisted to `localStorage` (`smartdispatch_language`), syncing `document.documentElement.lang`.

## Shared utilities

- `components/DateRangeFilter.jsx` + `utils/dateRange.js` — one client-side date-range filter
  (custom start/end, default = 1st of the month to today) shared by Dashboard, Agents, SLA
  Monitor, and Agent Profile.
- `utils/sla.js` — a JS reimplementation of the backend's business-hours SLA math (same Mon–Fri
  07:00–19:00 bounds, same pause-freeze semantics), used by `SLAMonitorView`, `DashboardView`,
  `AgentProfileView`, and `CountdownTimer` so the countdown never disagrees with the server.
  Intentionally mirrors `sla_engine.py` — if you change the business-hours logic on one side,
  mirror it on the other.
- `utils/formatDate.js` — locale-aware date/time/number formatting (`fr-FR` vs `en-US`) driven by
  the current language.

## Tech stack

React 19 · Vite · `react-i18next` · `oidc-client-ts` · Framer Motion · `lucide-react`

## Design token

`--primary-color: #f6c026` (LVMH gold).
