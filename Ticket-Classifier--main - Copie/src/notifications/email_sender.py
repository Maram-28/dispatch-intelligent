"""
Envoi d'emails de notification via SMTP Gmail (STARTTLS, port 587).

Variables .env requises :
  SMTP_HOST         — défaut : smtp.gmail.com
  SMTP_PORT         — défaut : 587
  SMTP_USERNAME     — adresse Gmail expéditeur
  SMTP_PASSWORD     — mot de passe d'application Gmail (pas le mot de passe du compte)
  SMTP_SENDER_NAME  — nom affiché dans l'en-tête From
  PLATFORM_URL      — URL de base du frontend (lien dans l'email)

Conception :
  - EmailNotifier est instancié à l'usage : relit les variables d'env à chaque création.
  - send_assignment() retourne True/False et logge les erreurs — ne lève jamais d'exception.
  - Encapsulé derrière une interface générique pour permettre une bascule vers
    Microsoft Graph ou tout autre backend SMTP (Phase 2).
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

_PRIORITY_COLORS = {
    "1-Critique": "#ef4444",
    "2-Majeure":  "#f97316",
    "3-Mineure":  "#3b82f6",
    "4-Standard": "#94a3b8",
}


class EmailNotifier:
    """Envoie des notifications par email via SMTP Gmail."""

    def __init__(self):
        self.host         = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        self.port         = int(os.environ.get("SMTP_PORT", "587"))
        self.username     = os.environ.get("SMTP_USERNAME", "")
        self.password     = os.environ.get("SMTP_PASSWORD", "")
        self.sender_name  = os.environ.get("SMTP_SENDER_NAME", "SmartDispatch")
        self.platform_url = os.environ.get("PLATFORM_URL", "http://localhost:5173")

    def _is_configured(self) -> bool:
        return bool(self.username and self.password)

    def send_assignment(
        self,
        recipient_email: str,
        recipient_name: str,
        ticket_numero: str,
        ticket_titre: str,
        ticket_priorite: str,
        ticket_sous_categorie: str,
        ticket_service: str,
        justification: str,
    ) -> bool:
        """
        Envoie un email d'assignation de ticket.
        Retourne True si envoi réussi, False sinon.
        Ne lève jamais d'exception — les erreurs sont loggées.
        """
        if not self._is_configured():
            logger.warning(
                "[EMAIL] SMTP non configuré (SMTP_USERNAME/SMTP_PASSWORD manquants) "
                "— email ignoré pour %s",
                recipient_email,
            )
            return False

        ticket_url = f"{self.platform_url}/?ticket={ticket_numero}"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[Ticket Assigné] {ticket_numero} — {ticket_titre}"
        msg["From"]    = f"{self.sender_name} <{self.username}>"
        msg["To"]      = recipient_email

        msg.attach(MIMEText(
            self._build_text(
                recipient_name, ticket_numero, ticket_titre, ticket_priorite,
                ticket_sous_categorie, ticket_service, justification, ticket_url,
            ),
            "plain", "utf-8",
        ))
        msg.attach(MIMEText(
            self._build_html(
                recipient_name, ticket_numero, ticket_titre, ticket_priorite,
                ticket_sous_categorie, ticket_service, justification, ticket_url,
            ),
            "html", "utf-8",
        ))

        try:
            with smtplib.SMTP(self.host, self.port, timeout=10) as server:
                server.ehlo()
                server.starttls()
                server.login(self.username, self.password)
                server.sendmail(self.username, recipient_email, msg.as_string())
            logger.info(
                "[EMAIL] Notification envoyée à %s pour ticket %s",
                recipient_email, ticket_numero,
            )
            return True
        except smtplib.SMTPAuthenticationError:
            logger.error(
                "[EMAIL] Échec d'authentification SMTP — vérifiez SMTP_USERNAME et SMTP_PASSWORD"
            )
        except smtplib.SMTPConnectError:
            logger.error("[EMAIL] Impossible de se connecter à %s:%s", self.host, self.port)
        except TimeoutError:
            logger.error(
                "[EMAIL] Timeout lors de la connexion SMTP pour %s (ticket %s)",
                recipient_email, ticket_numero,
            )
        except Exception as exc:
            logger.error(
                "[EMAIL] Erreur inattendue pour %s (ticket %s) : %s",
                recipient_email, ticket_numero, exc,
            )
        return False

    def send_sla_alert(
        self,
        recipient_email: str,
        recipient_name: str,
        ticket_numero: str,
        ticket_titre: str,
        ticket_priorite: str,
        tier: str,
        percent_remaining: float,
        remaining_hours: float,
        is_agent: bool,
        agent_nom: str,
    ) -> bool:
        """
        Envoie un email d'alerte SLA (tier = "40" | "10" | "breach").

        is_agent distingue le destinataire : True si c'est l'agent assigné au ticket
        (message "votre ticket"), False si c'est un manager en escalade (message
        précisant explicitement `agent_nom`, le nom de l'agent réellement assigné —
        un manager ne doit jamais lire "votre ticket" pour un ticket qui n'est pas
        le sien).

        Retourne True si envoi réussi, False sinon.
        Ne lève jamais d'exception — les erreurs sont loggées.
        """
        if not self._is_configured():
            logger.warning(
                "[EMAIL] SMTP non configuré (SMTP_USERNAME/SMTP_PASSWORD manquants) "
                "— email SLA ignoré pour %s",
                recipient_email,
            )
            return False

        ticket_url = f"{self.platform_url}/?ticket={ticket_numero}"
        subject_label, time_phrase = self._sla_wording(tier, percent_remaining, remaining_hours)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[{subject_label}] {ticket_numero} — {ticket_titre}"
        msg["From"]    = f"{self.sender_name} <{self.username}>"
        msg["To"]      = recipient_email

        msg.attach(MIMEText(
            self._build_sla_text(
                recipient_name, ticket_numero, ticket_titre, ticket_priorite,
                subject_label, time_phrase, ticket_url, is_agent, agent_nom,
            ),
            "plain", "utf-8",
        ))
        msg.attach(MIMEText(
            self._build_sla_html(
                recipient_name, ticket_numero, ticket_titre, ticket_priorite,
                subject_label, time_phrase, ticket_url, is_agent, agent_nom,
            ),
            "html", "utf-8",
        ))

        try:
            with smtplib.SMTP(self.host, self.port, timeout=10) as server:
                server.ehlo()
                server.starttls()
                server.login(self.username, self.password)
                server.sendmail(self.username, recipient_email, msg.as_string())
            logger.info(
                "[EMAIL] Alerte SLA '%s' envoyée à %s pour ticket %s",
                tier, recipient_email, ticket_numero,
            )
            return True
        except smtplib.SMTPAuthenticationError:
            logger.error(
                "[EMAIL] Échec d'authentification SMTP — vérifiez SMTP_USERNAME et SMTP_PASSWORD"
            )
        except smtplib.SMTPConnectError:
            logger.error("[EMAIL] Impossible de se connecter à %s:%s", self.host, self.port)
        except TimeoutError:
            logger.error(
                "[EMAIL] Timeout lors de la connexion SMTP pour %s (ticket %s)",
                recipient_email, ticket_numero,
            )
        except Exception as exc:
            logger.error(
                "[EMAIL] Erreur inattendue pour %s (ticket %s) : %s",
                recipient_email, ticket_numero, exc,
            )
        return False

    def send_priority_escalation(
        self,
        recipient_email: str,
        recipient_name: str,
        ticket_numero: str,
        ticket_titre: str,
        old_priority_label: str,
        new_priority_label: str,
        escalating: bool,
    ) -> bool:
        """
        Envoie un email quand la priorité ServiceNow d'un ticket franchit la
        frontière Critique (entrée ou sortie).

        escalating=True  : passage VERS Critique (alerte).
        escalating=False : sortie DE Critique (information, dé-escalade).

        Retourne True si envoi réussi, False sinon. Ne lève jamais d'exception.
        """
        if not self._is_configured():
            logger.warning(
                "[EMAIL] SMTP non configuré — email d'escalade priorité ignoré pour %s",
                recipient_email,
            )
            return False

        ticket_url = f"{self.platform_url}/?ticket={ticket_numero}"
        subject_label = "ESCALADE CRITIQUE" if escalating else "Dé-escalade de Critique"
        color = "#ef4444" if escalating else "#3b82f6"
        verb = "escaladé vers" if escalating else "descendu de"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[{subject_label}] {ticket_numero} — {ticket_titre}"
        msg["From"]    = f"{self.sender_name} <{self.username}>"
        msg["To"]      = recipient_email

        text = (
            f"Bonjour {recipient_name},\n\n"
            f"Le ticket {ticket_numero} ({ticket_titre}) a été {verb} Critique.\n\n"
            f"  Ancienne priorité ServiceNow : {old_priority_label}\n"
            f"  Nouvelle priorité ServiceNow : {new_priority_label}\n\n"
            f"Consulter le ticket : {ticket_url}\n\n"
            f"---\n"
            f"SmartDispatch — Système de gestion des tickets IT\n"
            f"Ceci est un message automatique, ne pas répondre.\n"
        )
        html = f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:Arial,sans-serif;background:#f8fafc;margin:0;padding:20px;">
  <div style="max-width:560px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
    <div style="background:#0f172a;padding:20px 28px;display:flex;align-items:center;gap:12px;">
      <span style="color:#f6c026;font-size:20px;font-weight:700;letter-spacing:1px;">SmartDispatch</span>
      <span style="color:#94a3b8;font-size:12px;margin-left:8px;">Power BI · Gestion des tickets IT</span>
    </div>
    <div style="padding:28px;">
      <h2 style="margin:0 0 6px;color:{color};font-size:17px;font-weight:700;">{subject_label}</h2>
      <p style="margin:0 0 20px;color:#64748b;font-size:14px;">
        Bonjour <strong>{recipient_name}</strong>, le ticket a été {verb} <strong>Critique</strong> côté ServiceNow.
      </p>
      <div style="background:#f8fafc;border-radius:8px;padding:16px 20px;margin-bottom:20px;">
        <table style="width:100%;border-collapse:collapse;font-size:14px;">
          <tr>
            <td style="color:#64748b;padding:5px 0;width:110px;vertical-align:top;">Numéro</td>
            <td style="color:#1e293b;font-weight:700;padding:5px 0;">{ticket_numero}</td>
          </tr>
          <tr>
            <td style="color:#64748b;padding:5px 0;vertical-align:top;">Titre</td>
            <td style="color:#1e293b;padding:5px 0;">{ticket_titre}</td>
          </tr>
          <tr>
            <td style="color:#64748b;padding:5px 0;vertical-align:top;">Priorité</td>
            <td style="padding:5px 0;">
              <span style="color:#94a3b8;">{old_priority_label}</span>
              →
              <span style="background:{color}1a;color:{color};font-weight:700;padding:2px 10px;border-radius:999px;">{new_priority_label}</span>
            </td>
          </tr>
        </table>
      </div>
      <a href="{ticket_url}" style="display:inline-block;background:#f6c026;color:#0f172a;font-weight:700;font-size:14px;padding:11px 24px;border-radius:8px;text-decoration:none;">
        Voir le ticket →
      </a>
    </div>
    <div style="padding:14px 28px;background:#f1f5f9;font-size:11px;color:#94a3b8;text-align:center;">
      SmartDispatch — Message automatique, ne pas répondre.
    </div>
  </div>
</body>
</html>"""
        msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))

        try:
            with smtplib.SMTP(self.host, self.port, timeout=10) as server:
                server.ehlo()
                server.starttls()
                server.login(self.username, self.password)
                server.sendmail(self.username, recipient_email, msg.as_string())
            logger.info(
                "[EMAIL] Escalade priorité envoyée à %s pour ticket %s",
                recipient_email, ticket_numero,
            )
            return True
        except smtplib.SMTPAuthenticationError:
            logger.error(
                "[EMAIL] Échec d'authentification SMTP — vérifiez SMTP_USERNAME et SMTP_PASSWORD"
            )
        except smtplib.SMTPConnectError:
            logger.error("[EMAIL] Impossible de se connecter à %s:%s", self.host, self.port)
        except TimeoutError:
            logger.error(
                "[EMAIL] Timeout lors de la connexion SMTP pour %s (ticket %s)",
                recipient_email, ticket_numero,
            )
        except Exception as exc:
            logger.error(
                "[EMAIL] Erreur inattendue pour %s (ticket %s) : %s",
                recipient_email, ticket_numero, exc,
            )
        return False

    @staticmethod
    def _sla_wording(tier: str, percent_remaining: float, remaining_hours: float) -> tuple:
        """Retourne (libellé du sujet, phrase décrivant le temps restant/dépassé).

        Un ticket peut être découvert déjà dépassé alors que le palier nominal
        évalué est "40" ou "10" (rattrapage : le job n'est pas passé à temps pour
        déclencher les paliers intermédiaires). Dans ce cas on décrit le
        dépassement en clair plutôt qu'un pourcentage négatif ("-13% restant"),
        qui serait confus pour le destinataire.
        """
        breached_now = remaining_hours < 0
        if tier == "breach" or breached_now:
            return (
                "SLA DÉPASSÉ",
                f"le SLA est déjà dépassé de {abs(remaining_hours):.1f}h au moment de la vérification",
            )
        if tier == "10":
            return "SLA CRITIQUE — 10% restant", f"il reste environ {remaining_hours:.1f}h ({percent_remaining:.0f}% du délai)"
        return "SLA — 40% consommé", f"il reste environ {remaining_hours:.1f}h ({percent_remaining:.0f}% du délai)"

    # ──────────────────────────────────────────
    #  Templates texte et HTML — alertes SLA
    # ──────────────────────────────────────────

    def _build_sla_text(
        self, nom: str, numero: str, titre: str, priorite: str,
        subject_label: str, time_phrase: str, url: str,
        is_agent: bool, agent_nom: str,
    ) -> str:
        if is_agent:
            intro = f"Alerte SLA sur VOTRE ticket : {subject_label}."
            assignee_line = ""
        else:
            intro = f"Alerte SLA sur un ticket assigné à {agent_nom} : {subject_label}."
            assignee_line = f"  Assigné à : {agent_nom}\n"
        return (
            f"Bonjour {nom},\n\n"
            f"{intro}\n\n"
            f"  Numéro    : {numero}\n"
            f"  Titre     : {titre}\n"
            f"  Priorité  : {priorite}\n"
            f"{assignee_line}"
            f"  Statut SLA: {time_phrase}\n\n"
            f"Consulter le ticket : {url}\n\n"
            f"---\n"
            f"SmartDispatch — Système de gestion des tickets IT\n"
            f"Ceci est un message automatique, ne pas répondre.\n"
        )

    def _build_sla_html(
        self, nom: str, numero: str, titre: str, priorite: str,
        subject_label: str, time_phrase: str, url: str,
        is_agent: bool, agent_nom: str,
    ) -> str:
        pcolor = _PRIORITY_COLORS.get(priorite, "#94a3b8")
        if is_agent:
            intro = f"Bonjour <strong>{nom}</strong>, {time_phrase} sur <strong>votre</strong> ticket."
            assignee_row = ""
        else:
            intro = f"Bonjour <strong>{nom}</strong>, {time_phrase} sur un ticket assigné à <strong>{agent_nom}</strong>."
            assignee_row = f"""
          <tr>
            <td style="color:#64748b;padding:5px 0;vertical-align:top;">Assigné à</td>
            <td style="color:#1e293b;font-weight:700;padding:5px 0;">{agent_nom}</td>
          </tr>"""
        return f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:Arial,sans-serif;background:#f8fafc;margin:0;padding:20px;">
  <div style="max-width:560px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">

    <div style="background:#0f172a;padding:20px 28px;display:flex;align-items:center;gap:12px;">
      <span style="color:#f6c026;font-size:20px;font-weight:700;letter-spacing:1px;">SmartDispatch</span>
      <span style="color:#94a3b8;font-size:12px;margin-left:8px;">Power BI · Gestion des tickets IT</span>
    </div>

    <div style="padding:28px;">
      <h2 style="margin:0 0 6px;color:#dc2626;font-size:17px;font-weight:700;">
        {subject_label}
      </h2>
      <p style="margin:0 0 20px;color:#64748b;font-size:14px;">
        {intro}
      </p>

      <div style="background:#f8fafc;border-radius:8px;padding:16px 20px;margin-bottom:20px;">
        <table style="width:100%;border-collapse:collapse;font-size:14px;">
          <tr>
            <td style="color:#64748b;padding:5px 0;width:110px;vertical-align:top;">Numéro</td>
            <td style="color:#1e293b;font-weight:700;padding:5px 0;">{numero}</td>
          </tr>
          <tr>
            <td style="color:#64748b;padding:5px 0;vertical-align:top;">Titre</td>
            <td style="color:#1e293b;padding:5px 0;">{titre}</td>
          </tr>
          <tr>
            <td style="color:#64748b;padding:5px 0;vertical-align:top;">Priorité</td>
            <td style="padding:5px 0;">
              <span style="background:{pcolor}1a;color:{pcolor};font-weight:700;font-size:12px;padding:2px 10px;border-radius:999px;">
                {priorite}
              </span>
            </td>
          </tr>{assignee_row}
          <tr>
            <td style="color:#64748b;padding:5px 0;vertical-align:top;">Statut SLA</td>
            <td style="color:#dc2626;font-weight:700;padding:5px 0;">{time_phrase}</td>
          </tr>
        </table>
      </div>

      <a href="{url}" style="display:inline-block;background:#f6c026;color:#0f172a;font-weight:700;font-size:14px;padding:11px 24px;border-radius:8px;text-decoration:none;">
        Voir le ticket →
      </a>
    </div>

    <div style="padding:14px 28px;background:#f1f5f9;font-size:11px;color:#94a3b8;text-align:center;">
      SmartDispatch — Message automatique, ne pas répondre.
    </div>
  </div>
</body>
</html>"""

    # ──────────────────────────────────────────
    #  Templates texte et HTML
    # ──────────────────────────────────────────

    def _build_text(
        self, nom: str, numero: str, titre: str, priorite: str,
        sous_cat: str, service: str, justif: str, url: str,
    ) -> str:
        return (
            f"Bonjour {nom},\n\n"
            f"Un nouveau ticket vous a été assigné.\n\n"
            f"  Numéro    : {numero}\n"
            f"  Titre     : {titre}\n"
            f"  Priorité  : {priorite}\n"
            f"  Catégorie : {sous_cat} — {service}\n\n"
            f"Justification d'assignation :\n{justif}\n\n"
            f"Consulter vos tickets : {url}\n\n"
            f"---\n"
            f"SmartDispatch — Système de gestion des tickets IT\n"
            f"Ceci est un message automatique, ne pas répondre.\n"
        )

    def _build_html(
        self, nom: str, numero: str, titre: str, priorite: str,
        sous_cat: str, service: str, justif: str, url: str,
    ) -> str:
        pcolor = _PRIORITY_COLORS.get(priorite, "#94a3b8")
        return f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:Arial,sans-serif;background:#f8fafc;margin:0;padding:20px;">
  <div style="max-width:560px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">

    <div style="background:#0f172a;padding:20px 28px;display:flex;align-items:center;gap:12px;">
      <span style="color:#f6c026;font-size:20px;font-weight:700;letter-spacing:1px;">SmartDispatch</span>
      <span style="color:#94a3b8;font-size:12px;margin-left:8px;">Power BI · Gestion des tickets IT</span>
    </div>

    <div style="padding:28px;">
      <h2 style="margin:0 0 6px;color:#1e293b;font-size:17px;font-weight:700;">
        Nouveau ticket assigné
      </h2>
      <p style="margin:0 0 20px;color:#64748b;font-size:14px;">
        Bonjour <strong>{nom}</strong>, un ticket vous a été assigné et est en attente de traitement.
      </p>

      <div style="background:#f8fafc;border-radius:8px;padding:16px 20px;margin-bottom:20px;">
        <table style="width:100%;border-collapse:collapse;font-size:14px;">
          <tr>
            <td style="color:#64748b;padding:5px 0;width:110px;vertical-align:top;">Numéro</td>
            <td style="color:#1e293b;font-weight:700;padding:5px 0;">{numero}</td>
          </tr>
          <tr>
            <td style="color:#64748b;padding:5px 0;vertical-align:top;">Titre</td>
            <td style="color:#1e293b;padding:5px 0;">{titre}</td>
          </tr>
          <tr>
            <td style="color:#64748b;padding:5px 0;vertical-align:top;">Priorité</td>
            <td style="padding:5px 0;">
              <span style="background:{pcolor}1a;color:{pcolor};font-weight:700;font-size:12px;padding:2px 10px;border-radius:999px;">
                {priorite}
              </span>
            </td>
          </tr>
          <tr>
            <td style="color:#64748b;padding:5px 0;vertical-align:top;">Catégorie</td>
            <td style="color:#1e293b;padding:5px 0;">{sous_cat} — {service}</td>
          </tr>
        </table>
      </div>

      <div style="border-left:3px solid #f6c026;padding:12px 16px;background:#fffbeb;border-radius:0 8px 8px 0;margin-bottom:24px;">
        <p style="margin:0 0 4px;font-size:11px;font-weight:700;color:#92400e;text-transform:uppercase;letter-spacing:0.5px;">
          Justification d'assignation
        </p>
        <p style="margin:0;font-size:13px;color:#78350f;line-height:1.5;">{justif}</p>
      </div>

      <a href="{url}" style="display:inline-block;background:#f6c026;color:#0f172a;font-weight:700;font-size:14px;padding:11px 24px;border-radius:8px;text-decoration:none;">
        Voir mes tickets →
      </a>
    </div>

    <div style="padding:14px 28px;background:#f1f5f9;font-size:11px;color:#94a3b8;text-align:center;">
      SmartDispatch — Message automatique, ne pas répondre.
    </div>
  </div>
</body>
</html>"""
