"""Job périodique d'alertes SLA — paliers 40% / 10% / dépassement, dédup par ticket,
escalade manager (Lot 2).

Choix d'ordonnanceur : BackgroundScheduler (APScheduler), PAS AsyncIOScheduler.
Raison réelle (et non un détail accessoire) : `NotificationDispatcher.notify_sla_alert`
envoie l'email en SMTP de façon synchrone/bloquante. Si le job tournait sur
AsyncIOScheduler, il s'exécuterait sur la même boucle événementielle asyncio que
`GET /agent/notifications/stream` (le flux SSE de tous les agents connectés, voir
api.py) : un envoi SMTP bloquant gèlerait cette boucle, donc gèlerait TOUS les flux
SSE en cours pendant l'envoi. BackgroundScheduler exécute le job dans un thread
dédié, complètement séparé de la boucle asyncio — aucun risque de geler le SSE.
`sse_manager.publish()` reste utilisable depuis ce thread : elle est conçue
(`loop.call_soon_threadsafe`) pour être appelée en dehors de la boucle asyncio,
exactement comme le fait déjà `NotificationDispatcher.notify_assignment` lorsqu'il
est appelé depuis un endpoint FastAPI synchrone (exécuté dans le threadpool).

Ce module n'importe PAS src.api au niveau module (pour rester testable en isolation
et éviter un import circulaire, puisque api.py démarre ce scheduler depuis son
lifespan) : le chargement/l'écriture des tickets utilisent un import différé,
identique au pattern déjà en place dans update_my_ticket_status pour profiling_agent.

Aucun LLM, aucun agent CrewAI : calcul et orchestration purs, déterministes.
Logs préfixés [SLA] pour se distinguer de [EMAIL]/[NOTIF]/[SSE].
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from src.auth import AUTH_MODE, _load_users
from src import keycloak_admin
from src.notifications.dispatcher import NotificationDispatcher
from src.sla import sla_engine

logger = logging.getLogger(__name__)

# Statuts scannés par le watchdog — cohérent avec le mapping du Lot 1
# (nouveau="new" et résolu="done" sont hors scope : pas de chrono actif).
ACTIVE_STATUSES = ("in_progress", "on_hold")

# Délai avant démarrage automatique du chrono SLA après assignation si l'agent n'a
# PAS cliqué sur "Commencer" entre-temps — filet de sécurité hybride : le clic
# manuel (PATCH /agent/tickets/{numero}/status, action="start") reste le chemin
# nominal, ce job ne fait que couvrir le cas où l'agent ne clique jamais (voir
# auto_start_assigned_tickets ci-dessous, et le garde-fou anti-course dans
# update_in_db/update_my_ticket_status côté api.py).
AUTO_START_DELAY_MINUTES = 15

# Ordre de déclenchement : un ticket découvert directement en breach sans être
# passé par 40/10 (job qui n'a pas tourné à temps) déclenche les paliers manquants
# au même passage, dans cet ordre — jamais de palier "sauté".
TIERS_IN_ORDER = ("40", "10", "breach")

_FLAG_FIELD = {
    "40": "sla_alert_40_sent",
    "10": "sla_alert_10_sent",
    "breach": "sla_alert_breach_sent",
}


def _get_managers() -> list:
    """Tous les users avec le rôle 'admin' (critère confirmé avec l'existant :
    src/auth.py définit User.role comme "admin" | "agent", et require_admin vérifie
    exactement `current_user.role != "admin"`). Source : users.json en AUTH_MODE=legacy,
    l'Admin REST API Keycloak en AUTH_MODE=keycloak."""
    try:
        if AUTH_MODE == "keycloak":
            return keycloak_admin.get_admin_usernames()
        return [u["id"] for u in _load_users() if u.get("role") == "admin"]
    except Exception as exc:
        logger.error("[SLA] Impossible de résoudre les managers admin : %s", exc)
        return []


def resolve_recipients(tier: str, agent_id: str) -> list:
    """Agent seul pour le palier 40 ; agent + managers pour 10 et breach (escalade).

    Un manager peut lui-même être assigné à un ticket (le pool d'assignation n'est
    pas restreint par rôle, voir member_profiles.json) : dans ce cas `agent_id` fait
    déjà partie du résultat de `_get_managers()`, d'où le dédoublonnage (ordre
    préservé, agent en premier) plutôt qu'une simple concaténation — sans effet
    fonctionnel côté notif_store (idempotent par (ticket, user, type)), mais évite
    un envoi/parcours redondant pour le même destinataire.
    """
    recipients = [agent_id]
    if tier in ("10", "breach"):
        recipients.extend(m for m in _get_managers() if m != agent_id)
    return recipients


def evaluate_ticket_alerts(ticket, now: datetime):
    """Détermine quels paliers déclencher pour CE ticket — fonction PURE, sans I/O ni
    effet de bord (pas d'écriture, pas de notification, pas d'email).

    Retourne (paliers_déclenchés_dans_l'ordre: list[str], flags_à_persister: dict).
    Un palier ne se déclenche que si son flag de dédup est encore False sur le ticket ;
    les flags ne sont jamais réinitialisés par cette fonction (dédup définitive par ticket).
    """
    if ticket.status not in ACTIVE_STATUSES:
        return [], {}

    percent = sla_engine.sla_percent_remaining(ticket, now)
    if percent is None:
        return [], {}  # SLA pas démarré (started_at/sla_deadline absents) : rien à évaluer

    breached = sla_engine.is_breached(ticket, now)
    already_sent = {tier: getattr(ticket, _FLAG_FIELD[tier]) for tier in TIERS_IN_ORDER}
    should_be_sent = {
        "40": breached or percent <= 40,
        "10": breached or percent <= 10,
        "breach": breached,
    }

    triggered = []
    updates = {}
    for tier in TIERS_IN_ORDER:
        if should_be_sent[tier] and not already_sent[tier]:
            triggered.append(tier)
            updates[_FLAG_FIELD[tier]] = True

    return triggered, updates


def evaluate_resolved_ticket_alerts(ticket):
    """Variante de `evaluate_ticket_alerts` pour un ticket déjà résolu ("done") en
    dépassement SLA (`ticket.sla_breached` True) — fonction PURE, même contrat
    (aucune I/O, aucun effet de bord).

    `check_all_tickets` n'évalue jamais un ticket "done" (hors `ACTIVE_STATUSES`,
    volontairement : pas de chrono actif) — si un ticket est résolu avant d'avoir
    été scanné pendant qu'il était actif (process redémarré, ou résolu entre deux
    cycles de 5 minutes), aucun palier n'est jamais évalué pour lui.

    Seul le palier "breach" est rattrapé ici (jamais "40"/"10") : ces deux paliers
    sont des AVERTISSEMENTS progressifs pendant qu'un chrono tourne encore — un
    ticket déjà résolu n'a plus de chrono actif, donc les rattraper après coup ne
    ferait qu'envoyer 2 notifications supplémentaires avec exactement le même
    texte que "breach" ("le SLA est déjà dépassé de Xh", cf. notify_sla_alert :
    la formulation "déjà dépassé" s'applique dès que `breached_now` est vrai, quel
    que soit le palier). Contrairement à `evaluate_ticket_alerts` (tickets actifs,
    où rattraper 40/10/breach en une passe a du sens car ils décrivent une
    progression réelle non encore notifiée), le seul fait pertinent à notifier ici
    est le dépassement lui-même. Utilisée par `reconcile_resolved_tickets`.
    """
    if ticket.status != "done" or not ticket.sla_breached or ticket.sla_alert_breach_sent:
        return [], {}

    return ["breach"], {_FLAG_FIELD["breach"]: True}


def reconcile_resolved_tickets(now: Optional[datetime] = None) -> list:
    """Rattrapage exécuté une fois au démarrage (voir lifespan de api.py, après
    `start_scheduler()`) : un ticket résolu ("done") sans jamais avoir été scanné
    par `check_all_tickets` pendant qu'il était actif ne déclenchera plus jamais
    aucune alerte (statut hors `ACTIVE_STATUSES`) — cette passe couvre ce cas une
    fois pour toutes les tickets encore présents dans la fenêtre glissante de
    `classifications_db.json`.

    Même contrat que `check_all_tickets` : ne lève jamais d'exception, un ticket
    cassé est loggé et sauté.
    """
    now = now or datetime.now()  # non utilisé pour le calcul (ticket déjà résolu), gardé pour la cohérence de signature
    results = []

    try:
        from src.api import load_db, update_in_db
    except Exception as exc:
        logger.error(
            "[SLA] Impossible d'importer les accès à classifications_db.json (rattrapage) : %s", exc
        )
        return results

    try:
        tickets = load_db()
    except Exception as exc:
        logger.error("[SLA] Erreur de chargement de classifications_db.json (rattrapage) : %s", exc)
        return results

    for ticket in tickets:
        numero = getattr(ticket, "numero", "?")
        try:
            if ticket.status != "done" or not ticket.sla_breached or not ticket.assigned_to:
                continue

            triggered, updates = evaluate_resolved_ticket_alerts(ticket)
            if not triggered:
                continue

            agent_id = ticket.assigned_to.membre_id
            for tier in triggered:
                recipients = resolve_recipients(tier, agent_id)
                try:
                    NotificationDispatcher.notify_sla_alert(ticket, tier, recipients)
                except Exception as exc:
                    logger.error(
                        "[SLA] Notification de rattrapage échouée pour le ticket %s, palier %s : %s",
                        numero, tier, exc,
                    )

            update_in_db(numero, updates)
            results.append({"numero": numero, "triggered": triggered})
            logger.info("[SLA] Ticket résolu %s : paliers de rattrapage déclenchés %s", numero, triggered)
        except Exception as exc:
            logger.error("[SLA] Ticket résolu %s ignoré suite à une erreur (rattrapage) : %s", numero, exc)
            continue

    return results


def auto_start_assigned_tickets(now: Optional[datetime] = None) -> list:
    """Démarre automatiquement le chrono SLA des tickets assignés restés "new"
    depuis plus de `AUTO_START_DELAY_MINUTES` (job périodique, voir start_scheduler) —
    filet de sécurité hybride : si l'agent a déjà cliqué "Commencer" avant ce délai
    (PATCH /agent/tickets/{numero}/status, action="start"), le ticket n'est plus
    "new" et cette fonction l'ignore ; sinon elle joue le même rôle que ce clic.

    Le point de départ du chrono (`started_at`/`sla_deadline`) est ancré sur
    `created_at + AUTO_START_DELAY_MINUTES`, PAS sur l'heure réelle de ce scan —
    sinon la deadline dériverait avec la fréquence du job plutôt que de refléter
    les 15 minutes annoncées. `sla_engine.on_status_change` accepte déjà ce
    point de départ synthétique via son paramètre `now` (même fonction que le
    clic manuel "Commencer").

    `update_in_db(..., expected_status="new")` ferme la fenêtre de course avec un
    clic manuel survenu entre notre lecture (`load_db()` ci-dessous) et notre
    écriture : si l'agent a démarré le ticket entre-temps, l'écriture est un
    no-op silencieux (voir docstring de update_in_db côté api.py) plutôt qu'un
    écrasement du started_at posé par le clic.

    Ne lève jamais d'exception : un ticket cassé est loggé et sauté, même contrat
    que check_all_tickets.
    """
    now = now or datetime.now()  # heure locale — cohérent avec sla_engine
    results = []

    try:
        from src.api import load_db, update_in_db
    except Exception as exc:
        logger.error("[SLA] Impossible d'importer les accès à classifications_db.json (auto-start) : %s", exc)
        return results

    try:
        tickets = load_db()
    except Exception as exc:
        logger.error("[SLA] Erreur de chargement de classifications_db.json (auto-start) : %s", exc)
        return results

    threshold = timedelta(minutes=AUTO_START_DELAY_MINUTES)
    for ticket in tickets:
        numero = getattr(ticket, "numero", "?")
        try:
            if ticket.status != "new" or not ticket.assigned_to or not ticket.created_at:
                continue

            created = datetime.fromisoformat(ticket.created_at)
            if now - created < threshold:
                continue

            started = created + threshold
            updates = sla_engine.on_status_change(ticket, "in_progress", started)
            updated = update_in_db(numero, updates, expected_status="new")
            if updated is None:
                # Course perdue contre un clic manuel "Commencer" survenu entre notre
                # lecture et cette écriture : le ticket est déjà démarré, rien à faire.
                continue
            results.append({"numero": numero, "started_at": updates["started_at"]})
            logger.info("[SLA] Ticket %s : démarrage automatique du chrono (assigné depuis %s min)", numero, AUTO_START_DELAY_MINUTES)
        except Exception as exc:
            logger.error("[SLA] Ticket %s ignoré suite à une erreur (auto-start) : %s", numero, exc)
            continue

    return results


def check_all_tickets(now: Optional[datetime] = None) -> list:
    """Point d'entrée du job périodique (appelé par APScheduler toutes les 5 minutes,
    ou directement par les tests). Charge les tickets actifs, déclenche les alertes
    manquantes, persiste les flags de dédup.

    Ne lève JAMAIS d'exception : un ticket cassé est loggé et sauté, le scan continue.
    Une erreur globale (ex: fichier illisible) est loggée et le job attend le prochain
    cycle plutôt que de tuer le scheduler.
    """
    now = now or datetime.now()  # heure locale — cohérent avec sla_engine
    results = []

    try:
        # Import différé : évite le cycle api.py <-> sla_watchdog.py (api.py démarre
        # ce module depuis son lifespan) et garde ce module testable sans FastAPI.
        from src.api import load_db, update_in_db
    except Exception as exc:
        logger.error("[SLA] Impossible d'importer les accès à classifications_db.json : %s", exc)
        return results

    try:
        tickets = load_db()
    except Exception as exc:
        logger.error("[SLA] Erreur de chargement de classifications_db.json : %s", exc)
        return results

    for ticket in tickets:
        numero = getattr(ticket, "numero", "?")
        try:
            if ticket.status not in ACTIVE_STATUSES or not ticket.assigned_to:
                continue

            triggered, updates = evaluate_ticket_alerts(ticket, now)
            if not triggered:
                continue

            agent_id = ticket.assigned_to.membre_id
            for tier in triggered:
                recipients = resolve_recipients(tier, agent_id)
                try:
                    NotificationDispatcher.notify_sla_alert(ticket, tier, recipients)
                except Exception as exc:
                    logger.error(
                        "[SLA] Notification échouée pour le ticket %s, palier %s : %s",
                        numero, tier, exc,
                    )

            update_in_db(numero, updates)
            results.append({"numero": numero, "triggered": triggered})
            logger.info("[SLA] Ticket %s : paliers déclenchés %s", numero, triggered)
        except Exception as exc:
            logger.error("[SLA] Ticket %s ignoré suite à une erreur : %s", numero, exc)
            continue

    return results


def start_scheduler():
    """Démarre le job périodique (appelé depuis le lifespan de api.py).
    Retourne le scheduler démarré, à arrêter via `scheduler.shutdown()` à l'arrêt de l'API.
    """
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        check_all_tickets,
        "interval",
        minutes=5,
        id="sla_watchdog",
        replace_existing=True,
        max_instances=1,  # un cycle de scan lent ne doit jamais chevaucher le suivant
        coalesce=True,    # si plusieurs déclenchements ont été manqués, n'en rattrape qu'un seul
    )
    # Intervalle plus court que le watchdog SLA (5 min) : sinon un ticket assigné
    # juste après un cycle attendrait jusqu'à 20 min (15 + 5) avant démarrage
    # automatique au lieu des 15 min annoncées côté plateforme.
    scheduler.add_job(
        auto_start_assigned_tickets,
        "interval",
        minutes=1,
        id="auto_start_tickets",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info(
        "[SLA] Watchdog démarré (intervalle : 5 minutes) — démarrage auto à %s min (intervalle : 1 minute)",
        AUTO_START_DELAY_MINUTES,
    )
    return scheduler
