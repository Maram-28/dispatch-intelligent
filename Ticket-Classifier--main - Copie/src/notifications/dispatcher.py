"""
Façade NotificationDispatcher.

Orchestre la notification in-app (synchrone, dans la requête) et l'email
(asynchrone, via BackgroundTasks de FastAPI — ne bloque pas la réponse).

Conçue pour être réutilisée pour les alertes SLA (Phase 2) : ajouter une méthode
notify_sla_breach() suivant le même pattern.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import BackgroundTasks

from src.notifications import store as notif_store
from src.notifications.email_sender import EmailNotifier
from src.sla import sla_engine

logger = logging.getLogger(__name__)

_USERS_FILE = Path("data/processed/users.json")


def _lookup_user(membre_id: str) -> tuple:
    """
    Retourne (email, nom) depuis users.json à partir d'un membre_id.
    Lève ValueError si l'utilisateur est introuvable ou si l'email est vide.
    """
    if not _USERS_FILE.exists():
        raise ValueError("users.json introuvable — impossible de résoudre l'email")
    with open(_USERS_FILE, encoding="utf-8") as f:
        users = json.load(f)
    for u in users:
        if u["id"] == membre_id:
            email = (u.get("email") or "").strip()
            if not email:
                raise ValueError(f"Email vide pour le membre '{membre_id}' dans users.json")
            return email, u.get("nom", membre_id)
    raise ValueError(f"Membre '{membre_id}' absent de users.json")


class NotificationDispatcher:
    """
    Point d'entrée unique pour émettre des notifications.
    Chaque méthode publique est fire-and-forget du point de vue du flux appelant :
    elle ne lève jamais d'exception.
    """

    @staticmethod
    def notify_assignment(ticket, assignment, background_tasks: BackgroundTasks) -> None:
        """
        Notification d'assignation de ticket.

        1. Enregistre la notif in-app dans le store JSON (synchrone, <5 ms).
        2. Planifie l'email en tâche de fond via BackgroundTasks (non bloquant).

        Si la notif existe déjà pour ce ticket+membre, rien n'est fait (idempotent).
        Les erreurs sont loggées sans jamais remonter au flux appelant.
        """
        try:
            membre_id = assignment.membre_id
            titre = getattr(ticket, "titre", None) or getattr(ticket, "breve_description", ticket.numero)
            message = f"Nouveau ticket assigné : {ticket.numero} — {titre}"

            # Notif in-app — synchrone
            created = notif_store.append_notification(
                user_id=membre_id,
                ticket_numero=ticket.numero,
                notif_type="assignment",
                message=message,
            )
            if created is None:
                logger.info(
                    "[NOTIF] Notification d'assignation déjà existante pour %s / ticket %s",
                    membre_id, ticket.numero,
                )
                return

            logger.info("[NOTIF] Notif in-app créée pour %s (ticket %s)", membre_id, ticket.numero)

            # Pousse en temps réel vers le canal SSE — best-effort, n'impacte jamais l'email
            try:
                from src.notifications.sse_manager import sse_manager
                sse_manager.publish(membre_id, {
                    "type": created["type"],
                    "id": created["id"],
                    "ticket_numero": created["ticket_numero"],
                    "message": created["message"],
                    "created_at": created["created_at"],
                })
            except Exception as sse_exc:
                logger.warning("[SSE] publish best-effort raté : %s", sse_exc)

            # Email — tâche de fond (ne bloque pas la réponse HTTP)
            background_tasks.add_task(
                NotificationDispatcher._send_assignment_email,
                membre_id=membre_id,
                ticket=ticket,
                assignment=assignment,
            )
        except Exception as exc:
            logger.error("[NOTIF] Erreur inattendue dans notify_assignment : %s", exc)

    @staticmethod
    def _send_assignment_email(membre_id: str, ticket, assignment) -> None:
        """Tâche de fond — résout l'email et envoie la notification."""
        try:
            email, nom = _lookup_user(membre_id)
        except ValueError as exc:
            logger.warning("[EMAIL] %s — email non envoyé pour ticket %s", exc, ticket.numero)
            return

        titre = getattr(ticket, "titre", None) or getattr(ticket, "breve_description", ticket.numero)
        ok = EmailNotifier().send_assignment(
            recipient_email=email,
            recipient_name=nom,
            ticket_numero=ticket.numero,
            ticket_titre=titre,
            ticket_priorite=ticket.priorite_calculee,
            ticket_sous_categorie=ticket.sous_categorie,
            ticket_service=ticket.service,
            justification=assignment.justification,
        )
        if ok:
            logger.info(
                "[EMAIL] Email d'assignation -> %s (ticket %s) : succès",
                email, ticket.numero,
            )
        else:
            logger.warning(
                "[EMAIL] Email d'assignation -> %s (ticket %s) : échec (voir logs email_sender)",
                email, ticket.numero,
            )

    @staticmethod
    def notify_priority_escalation(
        ticket_numero: str,
        titre: str,
        old_priority_label: str,
        new_priority_label: str,
        escalating: bool,
        recipients: list,
    ) -> None:
        """
        Notifie les managers quand la priorité ServiceNow d'un ticket franchit la
        frontière Critique, dans un sens ou dans l'autre (escalating=True : vers
        Critique ; False : hors de Critique).

        Email SYNCHRONE (pas de BackgroundTasks) : appelé depuis l'endpoint webhook
        léger /webhook/priority-changed, hors du cycle requête/réponse d'un
        utilisateur — même raisonnement que notify_sla_alert (voir sla_watchdog.py).
        Ne lève jamais d'exception vers l'appelant.
        """
        try:
            verb = "escaladé vers Critique" if escalating else "descendu de Critique"
            message = (
                f"Ticket {ticket_numero} ({titre}) : priorité {verb} "
                f"(ServiceNow {old_priority_label} → {new_priority_label})."
            )
            notif_type = "priority_escalation" if escalating else "priority_deescalation"

            for user_id in recipients:
                try:
                    created = notif_store.append_notification(
                        user_id=user_id,
                        ticket_numero=ticket_numero,
                        notif_type=notif_type,
                        message=message,
                    )
                    if created is None:
                        logger.info(
                            "[NOTIF] Alerte priorité déjà existante pour %s / ticket %s",
                            user_id, ticket_numero,
                        )
                        continue

                    try:
                        from src.notifications.sse_manager import sse_manager
                        sse_manager.publish(user_id, {
                            "type": created["type"],
                            "id": created["id"],
                            "ticket_numero": created["ticket_numero"],
                            "message": created["message"],
                            "created_at": created["created_at"],
                        })
                    except Exception as sse_exc:
                        logger.warning("[SSE] publish best-effort raté (priorité) : %s", sse_exc)

                    try:
                        email, nom = _lookup_user(user_id)
                    except ValueError as exc:
                        logger.warning(
                            "[EMAIL] %s — email priorité non envoyé pour ticket %s", exc, ticket_numero
                        )
                        continue

                    ok = EmailNotifier().send_priority_escalation(
                        recipient_email=email,
                        recipient_name=nom,
                        ticket_numero=ticket_numero,
                        ticket_titre=titre,
                        old_priority_label=old_priority_label,
                        new_priority_label=new_priority_label,
                        escalating=escalating,
                    )
                    if ok:
                        logger.info(
                            "[EMAIL] Escalade priorité -> %s (ticket %s) : succès", email, ticket_numero,
                        )
                    else:
                        logger.warning(
                            "[EMAIL] Escalade priorité -> %s (ticket %s) : échec", email, ticket_numero,
                        )
                except Exception as exc:
                    logger.error(
                        "[NOTIF] Erreur inattendue pour le destinataire %s (ticket %s) : %s",
                        user_id, ticket_numero, exc,
                    )
        except Exception as exc:
            logger.error(
                "[NOTIF] Erreur inattendue dans notify_priority_escalation (ticket %s) : %s",
                ticket_numero, exc,
            )

    @staticmethod
    def notify_sla_alert(ticket, tier: str, recipients: list) -> None:
        """
        Alerte de palier SLA (tier = "40" | "10" | "breach").

        Envoyée à chaque destinataire de `recipients` (résolu en amont par
        sla_watchdog.resolve_recipients : agent seul pour "40", agent + managers
        pour "10"/"breach"). Pour chaque destinataire : notif in-app (idempotente,
        type "sla_40"/"sla_10"/"sla_breach"), push SSE best-effort, email.

        Différence assumée avec notify_assignment : l'email est envoyé de façon
        SYNCHRONE (pas de BackgroundTasks). Ce dispatcher est appelé depuis le job
        périodique sla_watchdog, qui tourne dans le thread dédié d'APScheduler
        (BackgroundScheduler), pas dans une requête HTTP — il n'y a donc pas de
        réponse HTTP à protéger d'un éventuel délai SMTP, et surtout pas de boucle
        asyncio à bloquer (voir sla_watchdog.py pour la justification complète du
        choix BackgroundScheduler plutôt qu'AsyncIOScheduler).

        Ne lève jamais d'exception vers l'appelant (même contrat que notify_assignment).
        """
        try:
            now = datetime.now()  # heure locale — cohérent avec sla_engine
            titre = getattr(ticket, "titre", None) or getattr(ticket, "breve_description", ticket.numero)
            percent = sla_engine.sla_percent_remaining(ticket, now)
            remaining_secs = sla_engine.business_seconds_remaining(ticket, now)
            remaining_h = (remaining_secs / 3600) if remaining_secs is not None else 0.0
            # Un ticket peut être découvert déjà dépassé alors que le palier nominal
            # évalué est "40"/"10" (rattrapage) : on décrit alors le dépassement en
            # clair plutôt qu'un pourcentage négatif ("-13% restant"), confus pour
            # le destinataire.
            breached_now = remaining_h < 0
            notif_type = f"sla_{tier}"

            if tier == "breach" or breached_now:
                status_phrase = f"le SLA est déjà dépassé de {abs(remaining_h):.1f}h au moment de la vérification"
            else:
                status_phrase = f"il reste environ {remaining_h:.1f}h ({percent:.0f}% du délai SLA)"

            # Le manager en escalade n'est PAS l'assigné : il doit voir explicitement
            # qui est l'agent concerné, pas un message "vous est assigné" erroné.
            agent_id = ticket.assigned_to.membre_id if getattr(ticket, "assigned_to", None) else None
            agent_nom = agent_id
            if agent_id:
                try:
                    _, agent_nom = _lookup_user(agent_id)
                except ValueError:
                    pass  # agent introuvable dans users.json : on garde le membre_id comme nom d'affichage

            for user_id in recipients:
                try:
                    is_agent = (user_id == agent_id)
                    if is_agent:
                        message = f"SLA sur votre ticket {ticket.numero} ({titre}) : {status_phrase}."
                    else:
                        message = (
                            f"SLA sur le ticket {ticket.numero} ({titre}), "
                            f"assigné à {agent_nom} : {status_phrase}."
                        )

                    created = notif_store.append_notification(
                        user_id=user_id,
                        ticket_numero=ticket.numero,
                        notif_type=notif_type,
                        message=message,
                    )
                    if created is None:
                        logger.info(
                            "[SLA] Alerte '%s' déjà existante pour %s / ticket %s",
                            tier, user_id, ticket.numero,
                        )
                        continue

                    logger.info(
                        "[SLA] Notif in-app '%s' créée pour %s (ticket %s)",
                        notif_type, user_id, ticket.numero,
                    )

                    try:
                        from src.notifications.sse_manager import sse_manager
                        sse_manager.publish(user_id, {
                            "type": created["type"],
                            "id": created["id"],
                            "ticket_numero": created["ticket_numero"],
                            "message": created["message"],
                            "created_at": created["created_at"],
                        })
                    except Exception as sse_exc:
                        logger.warning("[SSE] publish best-effort raté (SLA) : %s", sse_exc)

                    try:
                        email, nom = _lookup_user(user_id)
                    except ValueError as exc:
                        logger.warning(
                            "[EMAIL] %s — email SLA non envoyé pour ticket %s", exc, ticket.numero
                        )
                        continue

                    ok = EmailNotifier().send_sla_alert(
                        recipient_email=email,
                        recipient_name=nom,
                        ticket_numero=ticket.numero,
                        ticket_titre=titre,
                        ticket_priorite=ticket.priorite_calculee,
                        tier=tier,
                        percent_remaining=percent,
                        remaining_hours=remaining_h,
                        is_agent=is_agent,
                        agent_nom=agent_nom,
                    )
                    if ok:
                        logger.info(
                            "[EMAIL] Email SLA '%s' -> %s (ticket %s) : succès",
                            tier, email, ticket.numero,
                        )
                    else:
                        logger.warning(
                            "[EMAIL] Email SLA '%s' -> %s (ticket %s) : échec (voir logs email_sender)",
                            tier, email, ticket.numero,
                        )
                except Exception as exc:
                    logger.error(
                        "[SLA] Erreur inattendue pour le destinataire %s (ticket %s, palier %s) : %s",
                        user_id, ticket.numero, tier, exc,
                    )
        except Exception as exc:
            logger.error(
                "[SLA] Erreur inattendue dans notify_sla_alert (ticket %s, palier %s) : %s",
                getattr(ticket, "numero", "?"), tier, exc,
            )
