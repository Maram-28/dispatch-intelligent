import asyncio
import logging
import os
import secrets
import time
import uuid
import json
import threading
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException, Depends, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ValidationError
from pathlib import Path

logger = logging.getLogger(__name__)


def _leading_digit(label: str, default: str = "3") -> str:
    """'2 - Modéré' -> '2'. Nos échelles impact/urgence (1/2/3) correspondent déjà
    à l'échelle numérique native ServiceNow — pas de table de correspondance requise."""
    label = (label or "").strip()
    return label[0] if label and label[0].isdigit() else default


# Palier ServiceNow "Critique" natif (échelle priority 1=Critical … 4/5=Low).
SN_CRITICAL_PRIORITY = "1"

from contextlib import asynccontextmanager
from src.agents.ticket_crew import TicketInput, ClassificationResult, classify_ticket, classify_batch
from src.auth import (
    AUTH_MODE,
    User, TokenResponse,
    get_current_user, require_admin,
    authenticate_user, create_access_token,
    init_users_from_profiles,
    _load_users, _save_users, users_transaction,
    hash_password, verify_password,
)
from src import keycloak_admin
from src.notifications.sse_manager import sse_manager, _set_loop
from src.sla import sla_engine
from src.sla.sla_watchdog import start_scheduler, reconcile_resolved_tickets, resolve_recipients
from src.agents import profiles_store


@asynccontextmanager
async def lifespan(_):
    _set_loop(asyncio.get_running_loop())
    init_users_from_profiles()
    scheduler = start_scheduler()
    # Rattrapage unique au démarrage : couvre les tickets résolus ("done") sans
    # jamais avoir été scannés par check_all_tickets pendant qu'ils étaient actifs
    # (process redémarré, ou résolu entre deux cycles de 5 min) — voir sla_watchdog.py.
    try:
        reconcile_resolved_tickets()
    except Exception as exc:
        logger.error("[SLA] Échec du rattrapage des tickets résolus au démarrage : %s", exc)
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="SmartDispatch API", description="AI-powered ticket classification backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # allow_origins=["*"] + allow_credentials=True est invalide côté navigateur
    # (le fetch spec rejette une réponse credentialed avec une origine wildcard) —
    # ni l'ancien schéma (Authorization: Bearer) ni le nouveau flow OIDC n'en ont
    # besoin de toute façon, donc restreint à l'origine réelle du frontend.
    allow_origins=[os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


JOBS: Dict[str, Dict] = {}

TEMP_DIR = Path("data/output/temp_jobs")
DB_FILE = Path("data/output/classifications_db.json")
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# Protège classifications_db.json contre les écritures concurrentes (même pattern que
# notifications.json) : le job périodique sla_watchdog écrit désormais dans ce fichier
# toutes les 5 minutes, en plus des endpoints HTTP existants.
_DB_LOCK = threading.Lock()


def _read_db_unlocked() -> List[ClassificationResult]:
    if not DB_FILE.exists():
        return []
    try:
        with open(DB_FILE, "r") as f:
            data = json.load(f)
            return [ClassificationResult(**item) for item in data]
    except (json.JSONDecodeError, OSError, ValidationError) as e:
        logger.error("[DB] Erreur de lecture de %s : %s: %s", DB_FILE, type(e).__name__, e)
        return []


def _write_db_unlocked(db: List[ClassificationResult]) -> None:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DB_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump([res.model_dump() for res in db], f, indent=2)
    os.replace(tmp, DB_FILE)


def load_db() -> List[ClassificationResult]:
    with _DB_LOCK:
        return _read_db_unlocked()


def save_to_db(result: ClassificationResult):
    with _DB_LOCK:
        db = _read_db_unlocked()
        db.insert(0, result)
        db = db[:100]
        _write_db_unlocked(db)


class JobStatus(BaseModel):
    job_id: str
    status: str
    total: int
    processed: int
    results: List[ClassificationResult] = []


# ─────────────────────────────────────────────
#  AUTH ENDPOINTS
# ─────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@app.post("/login", response_model=TokenResponse, tags=["Auth"])
def login(credentials: LoginRequest):
    """Authentification legacy — retourne un JWT Bearer token maison.
    Retiré en AUTH_MODE=keycloak : le frontend s'authentifie directement contre
    Keycloak (Authorization Code + PKCE), ce backend ne fait plus jamais de login."""
    if AUTH_MODE != "legacy":
        raise HTTPException(status_code=404, detail="Not Found")
    user = authenticate_user(credentials.username, credentials.password)
    if not user:
        raise HTTPException(status_code=401, detail="Identifiant ou mot de passe incorrect")
    token = create_access_token({"sub": user.id, "role": user.role})
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        role=user.role,
        nom=user.nom,
        membre_id=user.id,
    )


@app.get("/me", tags=["Auth"])
def get_me(current_user: User = Depends(get_current_user)):
    """Retourne le profil de l'utilisateur connecté."""
    return {"id": current_user.id, "nom": current_user.nom, "email": current_user.email, "role": current_user.role}


@app.post("/auth/change-password", tags=["Auth"])
def change_password(body: ChangePasswordRequest, current_user: User = Depends(get_current_user)):
    """Changer son propre mot de passe (legacy uniquement — en mode keycloak, le
    changement de mot de passe se fait via la Account Console de Keycloak)."""
    if AUTH_MODE != "legacy":
        raise HTTPException(status_code=404, detail="Not Found")
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Mot de passe actuel incorrect")
    with users_transaction() as users:
        for u in users:
            if u["id"] == current_user.id:
                u["hashed_password"] = hash_password(body.new_password)
                break
    return {"status": "ok", "message": "Mot de passe mis à jour"}


@app.get("/users", tags=["Auth"])
def list_users(_: User = Depends(require_admin)):
    """Liste tous les comptes utilisateurs (admin uniquement)."""
    if AUTH_MODE == "keycloak":
        return keycloak_admin.list_users_with_roles()
    return [
        {"id": u["id"], "nom": u["nom"], "email": u["email"], "role": u["role"]}
        for u in _load_users()
    ]


@app.patch("/users/{user_id}/role", tags=["Auth"])
def update_user_role(user_id: str, body: Dict, _: User = Depends(require_admin)):
    """Modifier le rôle d'un utilisateur (admin uniquement)."""
    new_role = body.get("role")
    if new_role not in ("admin", "agent"):
        raise HTTPException(status_code=400, detail="Rôle invalide. Valeurs acceptées: admin, agent")

    if AUTH_MODE == "keycloak":
        if not keycloak_admin.set_user_role(user_id, new_role):
            raise HTTPException(status_code=404, detail=f"Utilisateur '{user_id}' non trouvé")
        return {"id": user_id, "role": new_role}

    with users_transaction() as users:
        for u in users:
            if u["id"] == user_id:
                u["role"] = new_role
                return {"id": u["id"], "nom": u["nom"], "role": u["role"]}
    raise HTTPException(status_code=404, detail=f"Utilisateur '{user_id}' non trouvé")


# ─────────────────────────────────────────────
#  SSE ticket (AUTH_MODE=keycloak) — voir docstring de sse_stream() plus bas pour
#  le pourquoi de ce mécanisme distinct de la validation Keycloak.
# ─────────────────────────────────────────────

_SSE_TICKET_SECRET = os.environ.get("SSE_TICKET_SECRET", "dev-only-change-me-sse-ticket-secret")
_SSE_TICKET_TTL_SECONDS = 60
_sse_tickets_lock = threading.Lock()
_sse_tickets: Dict[str, Dict] = {}  # jti -> {"user_id": ..., "expires_at": ...}


def _mint_sse_ticket(user_id: str) -> str:
    jti = secrets.token_urlsafe(24)
    with _sse_tickets_lock:
        # purge occasionnelle des tickets expirés non consommés (petite table, pas
        # besoin d'un job dédié)
        now = time.time()
        for k in [k for k, v in _sse_tickets.items() if v["expires_at"] < now]:
            del _sse_tickets[k]
        _sse_tickets[jti] = {"user_id": user_id, "expires_at": now + _SSE_TICKET_TTL_SECONDS}
    return jti


def _consume_sse_ticket(jti: str) -> Optional[str]:
    """Retourne le user_id associé si le ticket est valide et non expiré, en le
    supprimant immédiatement (usage unique) — sinon None."""
    with _sse_tickets_lock:
        entry = _sse_tickets.pop(jti, None)
    if not entry or entry["expires_at"] < time.time():
        return None
    return entry["user_id"]


@app.post("/agent/notifications/sse-ticket", tags=["Notifications"])
def create_sse_ticket(current_user: User = Depends(get_current_user)):
    """Émet un ticket court (60s, usage unique) pour ouvrir UNE connexion SSE.

    Le vrai token d'auth (JWT legacy ou access token Keycloak) ne doit jamais
    apparaître dans une query string (logs serveur, historique navigateur,
    en-tête Referer) — ce ticket, sans rapport avec les clés de signature
    Keycloak, borne l'exposition à 60s et un seul usage plutôt qu'à la durée de
    vie complète du token réel."""
    return {"ticket": _mint_sse_ticket(current_user.id)}


# ─────────────────────────────────────────────
#  PUBLIC
# ─────────────────────────────────────────────

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "SmartDispatch API is running"}


# ─────────────────────────────────────────────
#  CLASSIFICATION & DISPATCH
# ─────────────────────────────────────────────

@app.post("/classify", response_model=ClassificationResult)
def classify_single(ticket: TicketInput, background_tasks: BackgroundTasks, _: User = Depends(get_current_user)):
    """Classify a single ticket then assign it to the best available team member."""
    try:
        result = classify_ticket(ticket)
        result.entreprise = ticket.entreprise
        result.breve_description = ticket.breve_description
        result.description = ticket.description
        result.created_at = datetime.now().isoformat()  # heure locale — cohérent avec sla_engine (7h-19h murales)
        result.source = "manual"
        result.titre = generate_title(
            ticket.breve_description,
            result.categorie,
            result.sous_categorie,
            result.service,
        )

        try:
            from src.agents.scorer_agent import assign_ticket
            from src.agents.ticket_crew import AssignmentInfo
            from src.agents.profiling_agent import run_update
            assignment = assign_ticket(
                ticket.entreprise or "",
                result.sous_categorie,
                result.service,
                ticket.numero,
            )
            if assignment and assignment.membre_id != "no_assignee":
                result.assigned_to = AssignmentInfo(
                    membre_id=assignment.membre_id,
                    nom=assignment.nom,
                    score_assignation=assignment.score_assignation,
                    justification=assignment.justification,
                )
                run_update({"assignee_id": assignment.membre_id, "delta": 1})
                # Notif in-app (sync) + email (background) — ne bloque jamais la réponse
                try:
                    from src.notifications.dispatcher import NotificationDispatcher
                    NotificationDispatcher.notify_assignment(result, assignment, background_tasks)
                except Exception as notif_err:
                    print(f"[NOTIF] Warning: {notif_err}")
        except Exception as scorer_err:
            print(f"[SCORER] Warning: {scorer_err}")

        save_to_db(result)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tickets", response_model=List[ClassificationResult])
def get_all_tickets(_: User = Depends(get_current_user)):
    """Retrieve all classified tickets from the 'database'."""
    return load_db()


@app.post("/classify/batch")
def classify_batch_endpoint(tickets: List[TicketInput], background_tasks: BackgroundTasks, _: User = Depends(get_current_user)):
    """Classify multiple tickets in the background."""
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"status": "processing", "total": len(tickets), "processed": 0, "results": []}
    background_tasks.add_task(run_batch_job, job_id, tickets)
    return {"job_id": job_id, "message": "Batch processing started"}


@app.post("/classify/upload")
async def classify_upload_endpoint(background_tasks: BackgroundTasks, file: UploadFile = File(...), _: User = Depends(get_current_user)):
    """Classify tickets from an uploaded Excel file."""
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Only Excel files are supported")

    contents = await file.read()
    df = pd.read_excel(contents)

    col_map = {
        "Numéro": "numero",
        "Brève description": "breve_description",
        "Description": "description",
        "Entreprise": "entreprise"
    }
    df = df.rename(columns=col_map)

    tickets = []
    for _, row in df.iterrows():
        tickets.append(TicketInput(
            numero=str(row.get("numero", "INC_UNK")),
            breve_description=str(row.get("breve_description", "")),
            description=str(row.get("description", "")),
            entreprise=str(row.get("entreprise", ""))
        ))

    job_id = f"upload_{uuid.uuid4().hex[:8]}"
    JOBS[job_id] = {"status": "processing", "total": len(tickets), "processed": 0, "results": []}
    background_tasks.add_task(run_batch_job, job_id, tickets)
    return {"job_id": job_id, "message": "File upload successful, processing started"}


@app.get("/jobs/{job_id}")
def get_job_status(job_id: str, _: User = Depends(get_current_user)):
    """Retrieve job progress and results."""
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    return JOBS[job_id]


@app.get("/jobs/{job_id}/download")
def download_job_results(job_id: str, _: User = Depends(get_current_user)):
    """Download job results as an Excel file."""
    if job_id not in JOBS or JOBS[job_id]["status"] != "done":
        raise HTTPException(status_code=400, detail="Job not finished or not found")

    results = JOBS[job_id]["results"]
    df = pd.DataFrame([res.model_dump() for res in results])

    output_path = TEMP_DIR / f"results_{job_id}.xlsx"
    df.to_excel(output_path, index=False, sheet_name="Classifications")
    return FileResponse(path=output_path, filename=f"ticket_results_{job_id}.xlsx")


@app.patch("/jobs/{job_id}/correct")
def correct_job_result(job_id: str, correction: Dict, _: User = Depends(require_admin)):
    """Manually correct a result (admin only)."""
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": "success", "message": f"Ticket {correction.get('numero')} corrected in job {job_id}"}


# ─────────────────────────────────────────────
#  SERVICENOW WEBHOOK
# ─────────────────────────────────────────────
# Reçoit un ticket créé côté ServiceNow (Business Rule "after insert" sur la table
# incident), répond 200 immédiatement, puis fait tourner le pipeline complet
# (classification + dispatch + notifications) en arrière-plan avant d'écrire le
# résultat dans ServiceNow (state, work_notes, assigned_to). Pas d'auth JWT ici :
# l'appelant est ServiceNow lui-même via le tunnel ngrok, pas un utilisateur connecté.

class WebhookTicket(BaseModel):
    sys_id: str = ""
    number: str
    short_description: str = ""
    description: str = ""
    priority: str = "4"
    company: str = ""
    offre_de_service: str = ""


def _process_webhook_background(payload: WebhookTicket) -> None:
    """
    Traitement IA après réception du webhook ServiceNow — exécuté dans un thread
    dédié via asyncio.to_thread() (voir webhook_new_ticket), avec sa propre
    boucle asyncio créée explicitement pour ce thread avant l'appel à
    crew.kickoff(). Cette fonction elle-même reste du code Python synchrone
    classique ; c'est l'appelant qui gère l'isolation asyncio.
    """
    from src.servicenow import update_ticket, get_user_sys_id
    from src.agents.scorer_agent import assign_ticket
    from src.agents.ticket_crew import AssignmentInfo
    from src.agents.profiling_agent import run_update
    from src.agents import profiles_store
    from src.notifications.dispatcher import NotificationDispatcher

    description = payload.description
    if payload.offre_de_service:
        description = f"[Offre de service : {payload.offre_de_service}]\n{description}"

    ticket = TicketInput(
        numero=payload.number,
        breve_description=payload.short_description,
        description=description,
        entreprise=payload.company,
    )

    try:
        result = classify_ticket(ticket)
        result.entreprise = ticket.entreprise
        result.breve_description = ticket.breve_description
        result.description = ticket.description
        result.created_at = datetime.now().isoformat()
        result.source = "servicenow"
        result.titre = generate_title(
            ticket.breve_description, result.categorie, result.sous_categorie, result.service,
        )

        try:
            assignment = assign_ticket(
                ticket.entreprise or "", result.sous_categorie, result.service, ticket.numero,
            )
            if assignment and assignment.membre_id != "no_assignee":
                result.assigned_to = AssignmentInfo(
                    membre_id=assignment.membre_id,
                    nom=assignment.nom,
                    score_assignation=assignment.score_assignation,
                    justification=assignment.justification,
                )
                run_update({"assignee_id": assignment.membre_id, "delta": 1})
                # Pas de BackgroundTasks de requête ici (on est déjà en tâche de fond,
                # synchrone, sans boucle asyncio) : on capture la tâche email dans une
                # BackgroundTasks jetable et on l'exécute nous-mêmes directement
                # (_send_assignment_email est une fonction sync — même pattern que
                # notify_sla_alert, appelé depuis le thread dédié du watchdog SLA).
                nested_bg = BackgroundTasks()
                NotificationDispatcher.notify_assignment(result, assignment, nested_bg)
                for task in nested_bg.tasks:
                    task.func(*task.args, **task.kwargs)
        except Exception as scorer_err:
            logger.warning("[WEBHOOK] Scorer indisponible pour %s : %s", ticket.numero, scorer_err)

        save_to_db(result)

        work_notes = (
            f"Classification IA : {result.categorie} / {result.sous_categorie} / {result.service}\n"
            f"Priorité calculée : {result.priorite_calculee} (confiance {result.confidence:.0%})\n"
            f"{result.reasoning}"
        )
        comments = (
            f"Votre ticket {payload.number} a été classifié et assigné automatiquement.\n"
            f"Catégorie : {result.categorie} — Priorité : {result.priorite_calculee}.\n"
            + (
                f"Pris en charge par : {result.assigned_to.nom}."
                if result.assigned_to else "Aucun agent disponible pour le moment."
            )
        )
        sn_payload = {
            "state": "2",  # In Progress
            # ServiceNow recalcule priority lui-même à partir de impact/urgency (un
            # write direct sur priority est silencieusement écrasé par sa propre
            # logique native — vérifié empiriquement). On écrit donc impact/urgency,
            # pas priority : nos échelles 1/2/3 (Majeur/Modéré/Mineur, Élevée/
            # Moyenne/Faible) correspondent déjà à l'échelle numérique native de
            # ServiceNow. Sa matrice interne peut légèrement différer de la nôtre
            # (sla_engine._PRIORITY_MATRIX) sur certaines combinaisons — attendu.
            "impact": _leading_digit(result.impact),
            "urgency": _leading_digit(result.urgence),
            "work_notes": work_notes,   # interne IT
            "comments": comments,       # visible par le demandeur
        }

        if result.assigned_to:
            # Email pro LVMH (member_profiles.json), pas l'email de connexion à la
            # plateforme (users.json) — c'est celui-là que ServiceNow connaît.
            profile = next(
                (p for p in profiles_store.load_profiles() if p["id"] == result.assigned_to.membre_id),
                None,
            )
            email = (profile or {}).get("email")
            if not email:
                logger.warning(
                    "[WEBHOOK] Email introuvable pour %s dans member_profiles.json — "
                    "assigned_to non renseigné, classification conservée.",
                    result.assigned_to.membre_id,
                )
            else:
                sn_sys_id = get_user_sys_id(email)
                if sn_sys_id:
                    sn_payload["assigned_to"] = sn_sys_id
                else:
                    logger.warning(
                        "[WEBHOOK] Agent %s introuvable dans ServiceNow (email %s) — "
                        "assigned_to non renseigné, classification conservée.",
                        result.assigned_to.membre_id, email,
                    )

        ok = update_ticket(payload.number, sn_payload)
        logger.info("[WEBHOOK] %s traité — SN update: %s", payload.number, "OK" if ok else "ÉCHEC")

    except Exception as e:
        logger.error("[WEBHOOK] Erreur de traitement pour %s : %s", payload.number, e)
        try:
            update_ticket(payload.number, {"work_notes": f"Erreur classification IA : {e}"})
        except Exception:
            pass


def _webhook_worker(payload: WebhookTicket) -> None:
    """
    Cible de asyncio.to_thread() (voir webhook_new_ticket) : tourne dans un
    thread de pool dédié, distinct du thread principal qui fait tourner la
    boucle asyncio d'uvicorn. On y attache explicitement une boucle asyncio
    fraîche avant crew.kickoff(), au cas où du code appelé plus bas dans la
    pile (litellm, telemetry, etc.) irait chercher asyncio.get_event_loop()
    dans ce thread — sans set_event_loop(), un thread tout neuf n'en a pas et
    lèverait RuntimeError à cet endroit précis.
    """
    asyncio.set_event_loop(asyncio.new_event_loop())
    _process_webhook_background(payload)


@app.post("/webhook/new-ticket", tags=["ServiceNow"])
async def webhook_new_ticket(payload: WebhookTicket, background_tasks: BackgroundTasks):
    """
    Reçoit un nouveau ticket ServiceNow, répond 200 immédiatement, traite en arrière-plan
    sans bloquer la boucle asyncio principale (celle-ci sert aussi les flux SSE — voir
    sse_manager.py — qui ne doivent jamais geler pendant un traitement webhook).

    Le traitement (classify_ticket -> assign_ticket -> save -> notify -> update_ticket)
    est un appel Python synchrone bloquant de plusieurs secondes. On le décharge donc
    sur asyncio.to_thread(), qui l'exécute dans le thread pool par défaut sans jamais
    bloquer la boucle événementielle courante — contrairement à BackgroundTasks avec une
    fonction async, ou à asyncio.create_task() sur une coroutine qui appellerait
    _process_webhook_background() directement : dans les deux cas, un appel bloquant de
    plusieurs secondes exécuté sans passer par un thread séparé gèle toute la boucle le
    temps du traitement (mesuré : ~10 ticks d'un heartbeat concurrent sur 3s au lieu de
    ~30 attendus). asyncio.to_thread() évite ce gel par construction.
    """
    background_tasks.add_task(asyncio.to_thread, _webhook_worker, payload)
    return {"status": "reçu", "ticket": payload.number}


class PriorityChangeWebhook(BaseModel):
    number: str
    short_description: str = ""
    old_priority: str = ""
    new_priority: str = ""


def _dispatch_priority_escalation(payload: "PriorityChangeWebhook") -> None:
    from src.sla.sla_watchdog import _get_managers
    from src.notifications.dispatcher import NotificationDispatcher

    old_p, new_p = payload.old_priority.strip(), payload.new_priority.strip()
    was_critical = old_p == SN_CRITICAL_PRIORITY
    is_critical = new_p == SN_CRITICAL_PRIORITY

    if was_critical == is_critical or not new_p:
        return

    managers = _get_managers()
    if not managers:
        logger.warning("[WEBHOOK] Aucun manager (role=admin) à notifier pour %s", payload.number)
        return

    NotificationDispatcher.notify_priority_escalation(
        ticket_numero=payload.number,
        titre=payload.short_description or payload.number,
        old_priority_label=old_p,
        new_priority_label=new_p,
        escalating=is_critical,
        recipients=managers,
    )
    logger.info(
        "[WEBHOOK] %s : franchissement Critique (%s -> %s), managers notifiés",
        payload.number, old_p, new_p,
    )


@app.post("/webhook/priority-changed", tags=["ServiceNow"], include_in_schema=False)
def webhook_priority_changed(payload: PriorityChangeWebhook, background_tasks: BackgroundTasks):
    """
    Business Rule ServiceNow dédiée (Update, condition "Priority changes") — voir
    doc d'intégration. Détecte un franchissement de la frontière Critique dans un
    sens ou dans l'autre et notifie les managers (in-app + SSE + email).

    Répond immédiatement, envoi des emails en tâche de fond (BackgroundTasks) :
    cette Business Rule s'exécute de façon SYNCHRONE dans la même transaction
    ServiceNow que le PATCH de /webhook/new-ticket qui a déclenché le changement
    de priorité (r.execute(), pas executeAsync()) — si on attend ici la fin de
    l'envoi SMTP (plusieurs secondes par destinataire), ServiceNow ne rend la main
    à /webhook/new-ticket qu'après, ce qui peut faire dépasser son propre timeout
    HTTP côté client (observé : "Read timed out (timeout=15)" sur update_ticket()
    alors que l'écriture ServiceNow avait pourtant réussi). Sans risque CrewAI ici
    contrairement à /webhook/new-ticket : cet endpoint n'appelle jamais
    classify_ticket(), donc BackgroundTasks est sûr à utiliser directement.

    Volontairement séparé de /webhook/new-ticket : n'appelle jamais classify_ticket()
    ni update_ticket() côté ServiceNow, donc aucun risque de boucle infinie même si
    la Business Rule ServiceNow se redéclenche sur d'autres champs modifiés en
    parallèle. Purement notificatif, aucune écriture retour vers ServiceNow.
    """
    background_tasks.add_task(_dispatch_priority_escalation, payload)
    return {"status": "reçu", "ticket": payload.number}


# ─────────────────────────────────────────────
#  HELPER
# ─────────────────────────────────────────────

def run_batch_job(job_id: str, tickets: List[TicketInput]):
    results = []
    for ticket in tickets:
        try:
            result = classify_ticket(ticket)
            result.created_at = datetime.now().isoformat()  # heure locale — cohérent avec sla_engine (7h-19h murales)
            result.source = "manual"
            result.breve_description = ticket.breve_description
            result.description = ticket.description
            result.titre = generate_title(
                ticket.breve_description,
                result.categorie,
                result.sous_categorie,
                result.service,
            )
            save_to_db(result)
            results.append(result)
        except Exception as e:
            results.append(ClassificationResult(
                numero=ticket.numero,
                categorie="Error",
                sous_categorie="Processing",
                service="N/A",
                impact="N/A",
                urgence="N/A",
                priorite_calculee="N/A",
                confidence=0.0,
                reasoning=f"Internal Error: {str(e)}"
            ))
        JOBS[job_id]["processed"] += 1
        JOBS[job_id]["results"] = results
    JOBS[job_id]["status"] = "done"


# ─────────────────────────────────────────────
#  MODULE 2 — PROFILING ROUTES
# ─────────────────────────────────────────────

class AvailabilityUpdate(BaseModel):
    disponible: bool
    raison: str = ""


@app.post("/profiles/bootstrap")
def bootstrap_profiles(_: User = Depends(require_admin)):
    """Calcule les profils depuis incident-10000.xlsx (admin uniquement)."""
    from src.agents.profiling_agent import run_bootstrap
    try:
        profiles = run_bootstrap()
        return {"status": "ok", "membres": len(profiles), "profiles": profiles}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/profiles")
def get_profiles(_: User = Depends(get_current_user)):
    """Return all member profiles."""
    try:
        return profiles_store.load_profiles()
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/profiles/scorer")
def get_profiles_for_scorer(_: User = Depends(get_current_user)):
    """Retourne les profils enrichis avec charge_normalisee pour le Scorer Agent."""
    from src.agents.profiling_agent import get_profiles_for_scorer
    try:
        return get_profiles_for_scorer()
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/profiles/{membre_id}/availability")
def update_member_availability(membre_id: str, update: AvailabilityUpdate, _: User = Depends(require_admin)):
    """Update disponible flag and raison for one member (admin uniquement)."""
    try:
        with profiles_store.profiles_transaction() as profiles:
            found = False
            for p in profiles:
                if p["id"] == membre_id:
                    p["disponible"] = update.disponible
                    found = True
                    break
            if not found:
                raise HTTPException(status_code=404, detail=f"Member '{membre_id}' not found.")
            result = next(p for p in profiles if p["id"] == membre_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    with profiles_store.availability_transaction() as avail:
        members = avail.setdefault("members", [])
        for m in members:
            if m["id"] == membre_id:
                m["disponible"] = update.disponible
                m["raison"]     = update.raison
                break
        else:
            members.append({"id": membre_id, "disponible": update.disponible, "raison": update.raison})

    return result


class TicketResolved(BaseModel):
    categorie:         str
    sous_categorie:    str = ""
    service:           str = ""
    priorite:          str
    resolution_time_h: float
    reopened:          bool = False


@app.post("/profiles/{membre_id}/resolve")
def resolve_ticket(membre_id: str, ticket: TicketResolved, _: User = Depends(get_current_user)):
    """Met à jour le profil d'un membre après résolution d'un ticket."""
    from src.agents.profiling_agent import update_after_resolution, run_update
    try:
        run_update({"assignee_id": membre_id, "delta": -1})
        updated = update_after_resolution(membre_id, ticket.dict(), reopened=ticket.reopened)
        return updated
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/profiles/{membre_id}/charge/increment")
def increment_charge(membre_id: str, _: User = Depends(get_current_user)):
    """Increment charge_actuelle by 1 for a member."""
    from src.agents.profiling_agent import run_update
    try:
        return run_update({"assignee_id": membre_id, "delta": 1})
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/profiles/{membre_id}/charge/decrement")
def decrement_charge(membre_id: str, _: User = Depends(get_current_user)):
    """Decrement charge_actuelle by 1 for a member (floor 0)."""
    from src.agents.profiling_agent import run_update
    try:
        return run_update({"assignee_id": membre_id, "delta": -1})
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ─────────────────────────────────────────────
#  AGENT WORKSPACE
# ─────────────────────────────────────────────

def generate_title(breve_description: str, categorie: str, sous_categorie: str, service: str) -> str:
    """Call the LLM directly to produce a ≤8-word ticket title in French."""
    try:
        import openai
        deployment = os.environ.get("OPENAI_MODEL_NAME", "gpt-4o")
        api_key    = os.environ.get("OPENAI_API_KEY", "")
        base_url   = os.environ.get("OPENAI_ENDPOINT", "").rstrip("/")
        client = openai.OpenAI(
            api_key=api_key,
            base_url=f"{base_url}/openai/deployments/{deployment}",
            default_headers={"api-key": api_key},
        )
        resp = client.chat.completions.create(
            model=deployment,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Tu génères des titres courts et clairs pour des tickets IT LVMH Power BI. "
                        "Maximum 8 mots en français. Commence directement par le titre — "
                        "pas de guillemets, pas de ponctuation finale, pas d'explication."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Description : {breve_description}\n"
                        f"Catégorie : {categorie} > {sous_categorie}\n"
                        f"Service : {service}\n\n"
                        "Titre (max 8 mots) :"
                    ),
                },
            ],
            max_completion_tokens=25,
            temperature=0.3,
        )
        raw = resp.choices[0].message.content.strip().strip('"').strip("'")
        return raw if raw else breve_description[:70]
    except Exception as exc:
        print(f"[TITLE] Warning: {exc}")
        return breve_description[:70]


# Constantes et calculs SLA centralisés dans src/sla/sla_engine.py.
SLA_HOURS = sla_engine.SLA_HOURS


def update_in_db(numero: str, updates: dict, expected_status: Optional[str] = None) -> Optional[ClassificationResult]:
    """Patch a single ticket in the DB by numero.

    expected_status: si fourni, l'écriture est sautée (retourne None) si le statut
    ACTUEL du ticket (relu ici, sous le verrou) ne correspond plus à cette valeur.
    Ferme la fenêtre de course entre le clic manuel "Commencer" et le démarrage
    automatique du scheduler (sla_watchdog.auto_start_assigned_tickets) : les deux
    chemins lisent le ticket via load_db() HORS verrou, calculent leur propre
    `updates` via sla_engine.on_status_change(), puis appellent cette fonction —
    sans cette garde, celui qui écrit en second écraserait started_at/sla_deadline
    du premier avec des valeurs obsolètes au lieu de constater que le ticket est
    déjà démarré.
    """
    with _DB_LOCK:
        db = _read_db_unlocked()
        for i, ticket in enumerate(db):
            if ticket.numero == numero:
                if expected_status is not None and ticket.status != expected_status:
                    return None
                ticket_dict = ticket.model_dump()
                ticket_dict.update(updates)
                db[i] = ClassificationResult(**ticket_dict)
                _write_db_unlocked(db)
                return db[i]
    return None


class StatusUpdate(BaseModel):
    action: str  # "start" | "pause" | "resume" | "done"
    wait_motive: Optional[str] = None   # requis si action == "pause" (voir sla_engine.WAIT_MOTIVES)
    wait_comment: Optional[str] = None  # requis seulement si wait_motive == "contact_principal"
    # Note libre, TOUJOURS facultative, indépendante de wait_comment ci-dessus (qui reste
    # requis pour "contact_principal" — règle métier inchangée). Distincte à dessein :
    # wait_comment part dans le champ ServiceNow `comments` (visible client), cette note-ci
    # part dans `work_notes` (interne only, voir _sync_hold_status_to_servicenow) ET est
    # persistée sur le ticket (`hold_note`, voir sla_engine.on_status_change) pour être
    # réaffichée dans TicketDetailsModal sans reparser le journal ServiceNow.
    note: Optional[str] = None


_ACTION_TO_STATUS = {
    "start": "in_progress",
    "pause": "on_hold",
    "resume": "in_progress",
    "done": "done",
}

# Libellés natifs ServiceNow (Status dropdown, confirmés sur l'instance) — envoyés en
# display-value plutôt qu'en code technique brut (voir update_ticket) pour ne pas avoir
# à deviner/maintenir des codes numériques spécifiques à l'instance.
_SN_STATE_IN_PROGRESS_LABEL = "In Progress"
_SN_STATE_ON_HOLD_LABEL = "On Hold"
_SN_STATE_RESOLVED_LABEL = "Resolved"
# Liste de choix close_code personnalisée sur cette instance (confirmé sur l'instance) :
# Duplicate / Known error / No resolution provided / Resolved by caller / Resolved by
# change / Resolved by problem / Resolved by request / Solution provided / Workaround
# provided / User error. "Solution provided" est le plus générique pour une résolution
# faite depuis la plateforme (pas de motif plus spécifique disponible côté agent).
_SN_CLOSE_CODE_LABEL = "Solution provided"

# wait_motive (plateforme) -> libellé exact (traduit) du choix ServiceNow `hold_reason`
# sur la table incident. Seuls ces 3 motifs sont pilotés par la plateforme, les autres
# choix ServiceNow (Autres, En attente du fournisseur/TMA, Suspension, En attente
# d'acceptation utilisateur) ne sont jamais utilisés côté plateforme.
_WAIT_MOTIVE_TO_SN_HOLD_REASON = {
    "contact_principal":   "En attente du contact principal",
    "changement":          "En attente du changement",
    "resolution_probleme": "En attente de la résolution du problème",
}


def _sync_hold_status_to_servicenow(
    numero: str, action: str, wait_motive: Optional[str], wait_comment: Optional[str],
    note: Optional[str] = None,
):
    """Best-effort : répercute pause/reprise/résolution vers ServiceNow (state + hold_reason).

    state et hold_reason sont envoyés dans le MÊME appel PATCH, en display-value
    (sysparm_input_display_value=true, voir update_ticket) : ServiceNow refuse la
    transition vers "On Hold" sans hold_reason renseigné en même temps — testé en
    premier avec deux champs séparés, le state repartait silencieusement à sa valeur
    précédente pendant que le commentaire, lui, était bien enregistré. N'échoue jamais
    la requête locale si ServiceNow est indisponible — même logique que le reste de
    l'intégration (update_ticket() est toujours best-effort).

    `note` (facultative, tous motifs confondus) part dans `work_notes` — le champ
    ServiceNow INTERNE (onglet "Notes"), jamais visible du client, à ne pas confondre
    avec `wait_comment` ci-dessus qui part dans `comments` (visible client, requis
    uniquement pour le motif "contact_principal" — règle métier distincte, inchangée).
    """
    try:
        from src.servicenow import update_ticket
        if action == "pause":
            sn_payload = {"state": _SN_STATE_ON_HOLD_LABEL}
            label = _WAIT_MOTIVE_TO_SN_HOLD_REASON.get(wait_motive)
            if label:
                sn_payload["hold_reason"] = label
            # Seul le motif "contact_principal" ouvre le champ notes côté ServiceNow.
            # Champ texte libre : non affecté par display_value.
            if wait_motive == "contact_principal" and wait_comment:
                sn_payload["comments"] = wait_comment
            if note and note.strip():
                sn_payload["work_notes"] = note.strip()
            update_ticket(numero, sn_payload, display_value=True)
        elif action == "resume":
            update_ticket(numero, {"state": _SN_STATE_IN_PROGRESS_LABEL, "hold_reason": ""}, display_value=True)
        elif action == "done":
            # Comme pour hold_reason (voir plus haut) : ServiceNow refuse la transition
            # vers "Resolved" sans close_code (et généralement close_notes) renseignés
            # dans le MÊME appel — sinon le state repart silencieusement à sa valeur
            # précédente malgré un 200 OK. Pas de champ de commentaire de résolution
            # côté plateforme aujourd'hui, donc valeurs par défaut ci-dessous.
            update_ticket(numero, {
                "state": _SN_STATE_RESOLVED_LABEL,
                "close_code": _SN_CLOSE_CODE_LABEL,
                "close_notes": "Ticket résolu via la plateforme SmartDispatch.",
            }, display_value=True)
    except Exception as e:
        logger.warning("[ServiceNow] Échec synchro statut pour %s (%s) : %s", numero, action, e)


@app.get("/agent/tickets")
def get_my_tickets(current_user: User = Depends(get_current_user)):
    """Retourne les tickets assignés à l'agent connecté."""
    db = load_db()
    mine = [t for t in db if t.assigned_to and t.assigned_to.membre_id == current_user.id]
    # Sort: in_progress first, then on_hold, then new, then done
    order = {"in_progress": 0, "on_hold": 1, "new": 2, "done": 3}
    mine.sort(key=lambda t: order.get(t.status, 9))
    return mine


@app.patch("/agent/tickets/{numero}/status")
def update_my_ticket_status(numero: str, body: StatusUpdate, current_user: User = Depends(get_current_user)):
    """Met à jour le statut d'un ticket assigné à l'agent connecté."""
    db = load_db()
    ticket = next((t for t in db if t.numero == numero), None)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket non trouvé")
    if not ticket.assigned_to or ticket.assigned_to.membre_id != current_user.id:
        raise HTTPException(status_code=403, detail="Ce ticket ne vous est pas assigné")

    new_status = _ACTION_TO_STATUS.get(body.action)
    if not new_status:
        raise HTTPException(status_code=400, detail=f"Action inconnue: '{body.action}'")

    # "start" est en concurrence avec sla_watchdog.auto_start_assigned_tickets (démarrage
    # automatique 15 min après assignation si l'agent n'a pas cliqué "Commencer") : le
    # bouton peut rester affiché sur une fiche restée ouverte alors que le ticket a déjà
    # été démarré (par le scheduler, ou par un clic précédent) avant même que cette requête
    # ne lise le ticket ci-dessus — sla_engine.on_status_change ne connaît pas de transition
    # "in_progress" -> "in_progress" et lèverait ValueError sur ce cas, qui n'est pourtant
    # pas une erreur. Traité en no-op idempotent : on renvoie l'état déjà démarré tel quel
    # plutôt que de faire échouer le clic de l'agent.
    if body.action == "start" and ticket.status != "new":
        return ticket

    now = datetime.now()  # heure locale — cohérent avec sla_engine (7h-19h murales)
    try:
        updates = sla_engine.on_status_change(
            ticket, new_status, now,
            wait_motive=body.wait_motive, wait_comment=body.wait_comment, hold_note=body.note,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if body.action in ("pause", "resume", "done"):
        _sync_hold_status_to_servicenow(numero, body.action, body.wait_motive, body.wait_comment, body.note)

    if body.action == "done":
        try:
            from src.agents.profiling_agent import update_after_resolution, run_update
            run_update({"assignee_id": current_user.id, "delta": -1})
            started = datetime.fromisoformat(ticket.started_at) if ticket.started_at else now
            elapsed_h = (now - started).total_seconds() / 3600 - ticket.total_paused_seconds / 3600
            update_after_resolution(current_user.id, {
                "categorie": ticket.categorie,
                "sous_categorie": ticket.sous_categorie,
                "service": ticket.service,
                "priorite": f"P{ticket.priorite_calculee[0]}",
                "resolution_time_h": round(elapsed_h, 2),
                "reopened": False,
            }, reopened=False, sla_respected=not updates["sla_breached"])
        except Exception as e:
            print(f"[PROFILING] Warning: {e}")

    # "start" est en concurrence avec sla_watchdog.auto_start_assigned_tickets (démarrage
    # automatique 15 min après assignation si l'agent n'a pas cliqué "Commencer") : les
    # deux chemins lisent le ticket hors verrou puis calculent leurs propres `updates`
    # à partir du même statut "new". expected_status ferme cette fenêtre — voir
    # update_in_db pour le mécanisme complet.
    expected_status = ticket.status if body.action == "start" else None
    updated = update_in_db(numero, updates, expected_status=expected_status)
    if not updated:
        if body.action == "start":
            # Le scheduler a démarré ce ticket entre notre lecture et notre écriture :
            # déjà "in_progress" avec un started_at/sla_deadline valides posés par
            # l'autre chemin. Pas une erreur — on renvoie l'état actuel plutôt que de
            # faire échouer le clic de l'agent (idempotence, voir sla_watchdog.py).
            current = next((t for t in load_db() if t.numero == numero), None)
            if current and current.status != "new":
                return current
        raise HTTPException(status_code=500, detail="Échec de la mise à jour")

    # Backstop : si ce ticket breach au moment même de sa résolution, il ne sera
    # plus jamais revu par check_all_tickets (qui n'évalue que ACTIVE_STATUSES) —
    # sans cet appel, un ticket résolu entre deux cycles de 5 min du watchdog ne
    # déclencherait jamais la notification de dépassement (voir sla_watchdog.py,
    # reconcile_resolved_tickets, pour le rattrapage au démarrage du cas symétrique).
    # Même flag de dédup que le watchdog (sla_alert_breach_sent) : idempotent si le
    # watchdog a déjà notifié ce ticket juste avant sa résolution.
    if body.action == "done" and updated.sla_breached and not updated.sla_alert_breach_sent:
        try:
            from src.notifications.dispatcher import NotificationDispatcher
            recipients = resolve_recipients("breach", updated.assigned_to.membre_id)
            NotificationDispatcher.notify_sla_alert(updated, "breach", recipients)
            update_in_db(numero, {"sla_alert_breach_sent": True})
        except Exception as exc:
            logger.error(
                "[SLA] Notification de dépassement à la résolution échouée pour %s : %s", numero, exc,
            )

    return updated


@app.get("/agent/notifications")
def get_my_notifications(current_user: User = Depends(get_current_user)):
    """Retourne les alertes SLA pour les tickets assignés à l'agent connecté."""
    db = load_db()
    now = datetime.now()  # heure locale — cohérent avec sla_engine (7h-19h murales)
    notifications = []

    for ticket in db:
        if not ticket.assigned_to or ticket.assigned_to.membre_id != current_user.id:
            continue
        if ticket.status in ("done", "new") or not ticket.sla_deadline:
            continue
        deadline = datetime.fromisoformat(ticket.sla_deadline)
        if ticket.status == "in_progress" and now > deadline:
            overdue_min = int((now - deadline).total_seconds() / 60)
            notifications.append({
                "ticket_numero": ticket.numero,
                "priorite": ticket.priorite_calculee,
                "sous_categorie": ticket.sous_categorie,
                "service": ticket.service,
                "deadline": ticket.sla_deadline,
                "overdue_minutes": overdue_min,
                "message": f"SLA dépassé de {overdue_min} min",
            })

    # Also include tickets approaching deadline (< 20% time remaining)
    for ticket in db:
        if not ticket.assigned_to or ticket.assigned_to.membre_id != current_user.id:
            continue
        if ticket.status != "in_progress" or not ticket.sla_deadline or not ticket.started_at:
            continue
        deadline = datetime.fromisoformat(ticket.sla_deadline)
        if now >= deadline:
            continue  # already in breached list
        total_secs = SLA_HOURS.get(ticket.priorite_calculee, 120) * 3600
        remaining_secs = (deadline - now).total_seconds()
        if remaining_secs / total_secs < 0.20:
            notifications.append({
                "ticket_numero": ticket.numero,
                "priorite": ticket.priorite_calculee,
                "sous_categorie": ticket.sous_categorie,
                "service": ticket.service,
                "deadline": ticket.sla_deadline,
                "overdue_minutes": 0,
                "message": f"SLA expire dans {int(remaining_secs / 60)} min",
            })

    return {"notifications": notifications, "count": len(notifications)}


# ─────────────────────────────────────────────
#  INBOX NOTIFICATIONS (assignations persistées)
# ─────────────────────────────────────────────

@app.get("/agent/notifications/inbox")
def get_inbox(current_user: User = Depends(get_current_user)):
    """
    Retourne les notifications in-app persistées de l'agent/manager connecté.
    Seules les notifications appartenant au token JWT sont renvoyées.

    Filtre additionnel pour les alertes SLA ("sla_40"/"sla_10"/"sla_breach") :
    uniquement celles dont le ticket est assigné au destinataire lui-même. Un
    manager reçoit aussi ces alertes comme destinataire d'ESCALADE pour des
    tickets qui ne lui sont pas assignés (sla_watchdog.resolve_recipients,
    paliers "10"/"breach" → tous les role="admin") — ces copies-là restent
    persistées et visibles dans le flux team-wide GET /manager/sla-notifications
    (SLA Monitor), mais n'ont pas leur place dans l'inbox PERSONNELLE : un
    manager n'y verrait rien qui ressemble à "un de mes tickets", seulement des
    alertes sur des tickets d'agents, à tort mêlées à ses propres assignations.
    "assignment" et "priority_escalation" ne sont pas filtrées : elles ne sont
    pas rattachées à la notion d'assigné du ticket.
    """
    from src.notifications import store as notif_store
    notifs = notif_store.get_for_user(current_user.id)

    sla_numeros = {n["ticket_numero"] for n in notifs if n["type"].startswith("sla_")}
    if sla_numeros:
        assignee_by_numero = {
            t.numero: (t.assigned_to.membre_id if t.assigned_to else None)
            for t in load_db() if t.numero in sla_numeros
        }
        notifs = [
            n for n in notifs
            if not n["type"].startswith("sla_")
            or assignee_by_numero.get(n["ticket_numero"]) == current_user.id
        ]

    unread  = sum(1 for n in notifs if not n["lu"])
    return {"notifications": notifs, "count": len(notifs), "unread_count": unread}


@app.post("/agent/notifications/read-all")
def mark_all_notifications_read(current_user: User = Depends(get_current_user)):
    """Marque toutes les notifications de l'agent connecté comme lues."""
    from src.notifications import store as notif_store
    count = notif_store.mark_all_read(current_user.id)
    return {"marked": count}


@app.get("/manager/sla-notifications")
def get_manager_sla_notifications(current_user: User = Depends(require_admin)):
    """
    Retourne les alertes SLA (paliers 40/10/breach) adressées AU manager connecté
    uniquement (notif_store.get_for_user), restreint aux types "sla_*". Réservé
    aux comptes admin (managers) — 403 sinon.

    Contrairement à GET /agent/notifications/inbox (inbox personnelle), PAS de
    filtrage supplémentaire par assigné du ticket ici : c'est précisément le flux
    destiné à voir les alertes d'ESCALADE reçues pour des tickets qui ne sont pas
    les siens (ex. le ticket d'un agent qui a dépassé son SLA) — voir
    sla_watchdog.resolve_recipients, paliers "10"/"breach" → tous les role="admin".
    L'inbox personnelle, elle, ne montre les alertes SLA que pour les tickets
    assignés au destinataire lui-même, pour ne pas les mêler à tort à ses propres
    tickets ; ce flux team-wide est l'endroit prévu pour les alertes des autres.

    Historiquement cet endpoint renvoyait TOUTES les alertes SLA de tous les
    agents et managers sans filtrage par destinataire (flux d'audit agrégé) — un
    manager y voyait donc aussi les alertes adressées à d'autres managers ou à
    l'agent assigné (message "votre ticket" écrit à la première personne, déroutant
    pour un tiers). Recentré sur le destinataire connecté.
    """
    from src.notifications import store as notif_store
    notifs = [n for n in notif_store.get_for_user(current_user.id) if n["type"].startswith("sla_")]
    unread = sum(1 for n in notifs if not n["lu"])
    return {"notifications": notifs, "count": len(notifs), "unread_count": unread}


@app.post("/manager/sla-check-now")
def trigger_sla_check_now(_: User = Depends(require_admin)):
    """
    Déclenche immédiatement un cycle du watchdog SLA (au lieu d'attendre le prochain
    passage périodique de 5 minutes). Réservé aux comptes admin — 403 sinon.

    Exécute check_all_tickets() DANS ce process serveur : c'est nécessaire pour que
    les pushs SSE atteignent réellement les clients déjà connectés à /agent/notifications/stream
    (sse_manager et sa boucle asyncio sont propres à ce process — un déclenchement
    depuis un script externe séparé ne pourrait pas les atteindre). Sert aussi de
    déclencheur manuel ops pour forcer un scan SLA immédiat.
    """
    from src.sla.sla_watchdog import check_all_tickets
    results = check_all_tickets(now=datetime.now())
    return {"checked": True, "triggered": results}


@app.post("/agent/notifications/{notif_id}/read")
def mark_notification_read(notif_id: str, current_user: User = Depends(get_current_user)):
    """
    Marque une notification spécifique comme lue.
    Retourne 404 si introuvable dans les notifs de l'utilisateur connecté
    (ownership implicitement vérifiée : on ne cherche que dans ses propres notifs).
    """
    from src.notifications import store as notif_store
    user_notifs = notif_store.get_for_user(current_user.id)
    if not any(n["id"] == notif_id for n in user_notifs):
        raise HTTPException(status_code=404, detail="Notification non trouvée")
    notif_store.mark_read(notif_id, current_user.id)
    return {"id": notif_id, "lu": True}


@app.get("/agent/notifications/stream")
async def sse_stream(request: Request, ticket: str = Query(...)):
    """
    Canal SSE temps réel pour les notifications de l'agent connecté.

    Authentification par ticket court (60s, usage unique — voir
    POST /agent/notifications/sse-ticket), PAS par le token d'auth réel : EventSource
    ne peut pas envoyer d'en-tête Authorization, donc tout ce qui transite ici
    transite en query string (logs serveur, historique navigateur, Referer). Ce
    mécanisme est volontairement indépendant de la validation Keycloak/legacy —
    ne pas le "corriger" pour accepter un token JWT/Keycloak directement.
    """
    user_id = _consume_sse_ticket(ticket)
    if not user_id:
        raise HTTPException(status_code=401, detail="Ticket SSE invalide, expiré ou déjà utilisé")

    q = sse_manager.subscribe(user_id)

    async def event_stream():
        try:
            yield 'event: connected\ndata: {"status": "ok"}\n\n'
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        break
                    yield ": ping\n\n"
        finally:
            sse_manager.unsubscribe(user_id, q)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/agent/profile")
def get_my_profile(current_user: User = Depends(get_current_user)):
    """Retourne le profil membre de l'agent connecté."""
    try:
        profiles = profiles_store.load_profiles()
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    profile = next((p for p in profiles if p["id"] == current_user.id), None)
    if not profile:
        raise HTTPException(status_code=404, detail="Profil non trouvé")
    return profile


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
