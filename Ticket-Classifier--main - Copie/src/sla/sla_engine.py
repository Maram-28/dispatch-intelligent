"""Moteur de chrono SLA — calcul des délais en heures ouvrées.

Convention de fuseau horaire : toutes les dates manipulées ici sont des
`datetime` NAÏFS (sans tzinfo), interprétés comme de l'heure MURALE LOCALE
(celle du serveur qui exécute l'API). Les bornes ouvrées (7h-23h) sont donc
dans le même référentiel que `created_at`, `started_at`, `paused_at`, etc.
Un ticket créé à 8h locale est bien traité comme 8h ouvrée, sans décalage.

Il ne faut jamais mélanger avec des dates UTC (ex: `datetime.utcnow()`) —
utiliser systématiquement `datetime.now()` pour horodater un événement lié
au SLA (voir src/api.py).

Aucune écriture disque, aucun appel LLM : uniquement du calcul de dates pur
et déterministe.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  CONSTANTES
# ─────────────────────────────────────────────

# Délai SLA par priorité, en heures OUVRÉES.
SLA_HOURS = {
    "1-Critique": 8,
    "2-Majeure": 16,
    "3-Mineure": 48,
    "4-Standard": 96,
}

# Heures ouvrées : lundi (0) à vendredi (4), 07h00-23h00.
_WORK_START = 7   # 07:00
_WORK_END = 23    # 23:00

# Motifs de mise en attente valides.
WAIT_MOTIVES = ("contact_principal", "changement", "resolution_probleme")

# Mapping des statuts métier (spec) -> valeurs stockées (inchangées, existantes) :
#   nouveau      -> "new"
#   en_cours     -> "in_progress"
#   en_attente   -> "on_hold"
#   résolu       -> "done"


# ─────────────────────────────────────────────
#  PRIORITÉ (impact × urgence) — matrice canonique
# ─────────────────────────────────────────────

# Matrice ServiceNow impact × urgence -> priorité, dans le format canonique
# (clés valides de SLA_HOURS ci-dessus). Source de vérité UNIQUE pour ce calcul :
# aussi utilisée par PriorityCalculatorTool (src/agents/ticket_crew.py) pour que
# l'agent CrewAI et le moteur SLA ne divergent plus jamais sur le format.
# Libellés impact/urgence : doivent matcher EXACTEMENT ceux de TAXONOMY dans
# ticket_crew.py (accents compris — vérifié contre les vraies sorties LLM stockées
# dans classifications_db.json, pas seulement contre la constante elle-même).
_PRIORITY_MATRIX = {
    ("1 - Majeur", "1 - Élevée"):  "1-Critique",
    ("1 - Majeur", "2 - Moyenne"): "2-Majeure",
    ("1 - Majeur", "3 - Faible"):  "3-Mineure",
    ("2 - Modéré", "1 - Élevée"):  "2-Majeure",
    ("2 - Modéré", "2 - Moyenne"): "2-Majeure",
    ("2 - Modéré", "3 - Faible"):  "3-Mineure",
    ("3 - Mineur", "1 - Élevée"):  "3-Mineure",
    ("3 - Mineur", "2 - Moyenne"): "4-Standard",
    ("3 - Mineur", "3 - Faible"):  "4-Standard",
}


def compute_priority(impact: str, urgence: str) -> str:
    """Priorité canonique (clé valide de SLA_HOURS) depuis impact/urgence.

    Repli sur '1-Critique' (fail-strict) si la paire est hors taxonomie, plutôt
    que sur une valeur relâchée : un ticket mal classé doit sur-alerter et rester
    visible, jamais disparaître silencieusement dans un SLA de 96h par défaut.
    Sert aussi de validateur implicite de taxonomie (paire inconnue = absente du dict).
    """
    key = ((impact or "").strip(), (urgence or "").strip())
    priority = _PRIORITY_MATRIX.get(key)
    if priority is None:
        logger.error("[PRIORITY] impact/urgence hors taxonomie: %r/%r — repli 1-Critique", impact, urgence)
        return "1-Critique"
    return priority


# ─────────────────────────────────────────────
#  HELPERS HEURES OUVRÉES
# ─────────────────────────────────────────────

def is_business_time(dt: datetime) -> bool:
    """True si `dt` tombe dans une plage ouvrée (lun-ven, 07h-23h)."""
    if dt.weekday() >= 5:  # 5=samedi, 6=dimanche
        return False
    secs = dt.hour * 3600 + dt.minute * 60 + dt.second
    return _WORK_START * 3600 <= secs < _WORK_END * 3600


def add_business_hours(start: datetime, hours: float) -> datetime:
    """Retourne la date `hours` heures OUVRÉES après `start`.

    Heures ouvrées : lun-ven, 07h00-23h00. Les nuits et week-ends sont
    sautés sans consommer de délai.
    """
    remaining = hours * 3600  # secondes
    cur = start
    while remaining > 0:
        dow = cur.weekday()  # 0=lun … 6=dim
        if dow >= 5:  # week-end -> saut au lundi 07h00
            cur = (cur + timedelta(days=7 - dow)).replace(
                hour=_WORK_START, minute=0, second=0, microsecond=0
            )
            continue
        cur_secs = cur.hour * 3600 + cur.minute * 60 + cur.second
        ws = _WORK_START * 3600
        we = _WORK_END * 3600
        if cur_secs < ws:
            cur = cur.replace(hour=_WORK_START, minute=0, second=0, microsecond=0)
            continue
        if cur_secs >= we:
            cur = (cur + timedelta(days=1)).replace(
                hour=_WORK_START, minute=0, second=0, microsecond=0
            )
            continue
        avail = we - cur_secs
        if remaining <= avail:
            cur = cur + timedelta(seconds=remaining)
            remaining = 0
        else:
            remaining -= avail
            cur = (cur + timedelta(days=1)).replace(
                hour=_WORK_START, minute=0, second=0, microsecond=0
            )
    return cur


def _business_seconds_forward(a: datetime, b: datetime) -> float:
    """Secondes ouvrées entre `a` et `b`, en supposant a <= b."""
    total = 0.0
    cur = a
    while cur < b:
        dow = cur.weekday()
        if dow >= 5:  # week-end -> saut au lundi 07h00
            nxt = (cur + timedelta(days=7 - dow)).replace(
                hour=_WORK_START, minute=0, second=0, microsecond=0
            )
            cur = min(nxt, b)
            continue
        cur_secs = cur.hour * 3600 + cur.minute * 60 + cur.second
        ws = _WORK_START * 3600
        we = _WORK_END * 3600
        if cur_secs < ws:
            nxt = cur.replace(hour=_WORK_START, minute=0, second=0, microsecond=0)
            cur = min(nxt, b)
            continue
        if cur_secs >= we:
            nxt = (cur + timedelta(days=1)).replace(
                hour=_WORK_START, minute=0, second=0, microsecond=0
            )
            cur = min(nxt, b)
            continue
        # `cur` est dans une plage ouvrée : on compte jusqu'à min(b, fin de plage)
        window_end = cur.replace(hour=_WORK_END, minute=0, second=0, microsecond=0)
        end = min(b, window_end)
        total += (end - cur).total_seconds()
        if end == window_end and window_end < b:
            cur = (cur + timedelta(days=1)).replace(
                hour=_WORK_START, minute=0, second=0, microsecond=0
            )
        else:
            cur = end
    return total


def business_seconds_between(a: datetime, b: datetime) -> float:
    """Secondes ouvrées signées entre `a` et `b` (négatif si b < a)."""
    if a == b:
        return 0.0
    if a < b:
        return _business_seconds_forward(a, b)
    return -_business_seconds_forward(b, a)


# ─────────────────────────────────────────────
#  MOTEUR SLA
# ─────────────────────────────────────────────

def compute_sla_deadline(priority: str, started_at: datetime) -> datetime:
    """Deadline absolue (heure ouvrée) pour une priorité donnée."""
    hours = SLA_HOURS.get(priority, SLA_HOURS["4-Standard"])
    return add_business_hours(started_at, hours)


def business_seconds_remaining(ticket, now: datetime) -> Optional[float]:
    """Temps OUVRÉ restant avant la deadline (peut être négatif si dépassé).

    Si le ticket est en pause manuelle (`on_hold`), le chrono est gelé au
    moment de la pause (`paused_at`) : le temps qui s'écoule pendant la
    pause, ouvré ou non, ne compte pas.
    La pause automatique hors heures ouvrées n'a pas besoin d'être gérée
    ici séparément : elle est déjà intégrée dans `business_seconds_between`,
    qui ne compte que les secondes tombant dans une plage ouvrée.
    """
    if not ticket.sla_deadline or not ticket.started_at:
        return None
    deadline = datetime.fromisoformat(ticket.sla_deadline)
    if ticket.status == "on_hold" and ticket.paused_at:
        reference = datetime.fromisoformat(ticket.paused_at)
    else:
        reference = now
    return business_seconds_between(reference, deadline)


def sla_percent_remaining(ticket, now: datetime) -> Optional[float]:
    """Pourcentage de temps ouvré restant (base = délai total de la priorité)."""
    budget_hours = SLA_HOURS.get(ticket.priorite_calculee)
    if budget_hours is None:
        return None
    remaining = business_seconds_remaining(ticket, now)
    if remaining is None:
        return None
    return remaining / (budget_hours * 3600) * 100


def is_breached(ticket, now: datetime) -> bool:
    """True si le temps ouvré restant est négatif (SLA dépassé)."""
    remaining = business_seconds_remaining(ticket, now)
    return remaining is not None and remaining < 0


def on_status_change(
    ticket,
    new_status: str,
    now: datetime,
    wait_motive: Optional[str] = None,
    wait_comment: Optional[str] = None,
    hold_note: Optional[str] = None,
) -> dict:
    """Applique une transition de statut et retourne les champs à mettre à jour.

    Statuts stockés (inchangés) : "new" | "in_progress" | "on_hold" | "done".
    Lève ValueError sur une transition invalide ou un motif d'attente manquant.
    """
    current = ticket.status

    if new_status == "in_progress":
        if current == "new":
            # Démarrage initial du chrono.
            started = now
            return {
                "status": "in_progress",
                "started_at": started.isoformat(),
                "sla_deadline": compute_sla_deadline(ticket.priorite_calculee, started).isoformat(),
                "wait_motive": None,
                "wait_comment": None,
                "hold_note": None,
            }
        if current == "on_hold":
            # Reprise depuis une pause manuelle : on ne recule la deadline
            # que du temps OUVRÉ réellement consommé pendant la pause (et
            # non du delta mural, qui inclurait à tort les nuits/week-ends).
            if not ticket.paused_at:
                raise ValueError("Ticket en 'on_hold' sans 'paused_at'.")
            paused_at = datetime.fromisoformat(ticket.paused_at)
            business_paused = business_seconds_between(paused_at, now)
            wall_paused = (now - paused_at).total_seconds()
            # add_business_hours (et non une addition murale) pour que la nouvelle
            # deadline reste alignée sur une plage ouvrée, comme la deadline initiale.
            new_deadline = add_business_hours(datetime.fromisoformat(ticket.sla_deadline), business_paused / 3600)
            return {
                "status": "in_progress",
                "paused_at": None,
                "total_paused_seconds": ticket.total_paused_seconds + int(wall_paused),
                "sla_deadline": new_deadline.isoformat(),
                "wait_motive": None,
                "wait_comment": None,
                "hold_note": None,
            }
        raise ValueError(f"Transition invalide : '{current}' -> 'in_progress'.")

    if new_status == "on_hold":
        if current != "in_progress":
            raise ValueError(f"Transition invalide : '{current}' -> 'on_hold'.")
        if wait_motive not in WAIT_MOTIVES:
            raise ValueError(f"wait_motive invalide ou manquant : {wait_motive!r}.")
        if wait_motive == "contact_principal" and not wait_comment:
            raise ValueError("wait_comment est requis pour le motif 'contact_principal'.")
        return {
            "status": "on_hold",
            "paused_at": now.isoformat(),
            "wait_motive": wait_motive,
            "wait_comment": wait_comment,
            "hold_note": hold_note,
        }

    if new_status == "done":
        if current not in ("in_progress", "on_hold"):
            raise ValueError(f"Transition invalide : '{current}' -> 'done'.")
        remaining = business_seconds_remaining(ticket, now)
        budget_hours = SLA_HOURS.get(ticket.priorite_calculee)
        consumed = (budget_hours * 3600 - remaining) if (remaining is not None and budget_hours is not None) else None
        return {
            "status": "done",
            "resolved_at": now.isoformat(),
            "resolution_time_business_seconds": consumed,
            "sla_breached": bool(remaining is not None and remaining < 0),
        }

    raise ValueError(f"Statut cible inconnu : {new_status!r}.")
