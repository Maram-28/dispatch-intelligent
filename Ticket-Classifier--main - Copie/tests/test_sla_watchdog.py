"""
Script de test autonome pour src/sla/sla_watchdog.py — dates FIXES, tickets fictifs
en memoire, PAS d'APScheduler, PAS d'attente de 5 minutes.
Lancer avec : python tests/test_sla_watchdog.py

Choix delibere : ce script teste evaluate_ticket_alerts() et resolve_recipients()
directement (les fonctions PURES de decision), plutot que check_all_tickets() de
bout en bout. check_all_tickets() fait de l'I/O reel (lit/ecrit
data/output/classifications_db.json via src.api, ecrit data/output/notifications.json,
tente un envoi SMTP reel) — l'appeler depuis un test polluerait les donnees de prod
et enverrait de vrais emails. Tout ce que ce lot doit valider (quels paliers se
declenchent, l'escalade manager, la dedup) est entierement determine par ces deux
fonctions pures, qui sont la "logique metier" du job.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.ticket_crew import ClassificationResult, AssignmentInfo
from src.sla import sla_watchdog, sla_engine


FAILURES = []


def check(label, expected, actual):
    ok = expected == actual
    status = "OK  " if ok else "FAIL"
    print(f"[{status}] {label}")
    print(f"        attendu : {expected}")
    print(f"        obtenu  : {actual}")
    if not ok:
        FAILURES.append(label)


def make_ticket(sla_deadline, **overrides):
    base = dict(
        numero="T-TEST",
        categorie="Incident",
        sous_categorie="Application",
        service="O365-PowerBI",
        impact="2-Moyen",
        urgence="2-Moyen",
        priorite_calculee="1-Critique",  # budget 8h = 28800s
        confidence=0.9,
        reasoning="test",
        status="in_progress",
        started_at=datetime(2024, 1, 1, 7, 0, 0).isoformat(),
        sla_deadline=sla_deadline.isoformat(),
        assigned_to=AssignmentInfo(
            membre_id="agent_test", nom="Agent Test",
            score_assignation=0.9, justification="test",
        ),
        sla_alert_40_sent=False,
        sla_alert_10_sent=False,
        sla_alert_breach_sent=False,
    )
    base.update(overrides)
    return ClassificationResult(**base)


# Un seul instant de scan pour tous les tickets (comme un vrai passage du job) :
NOW = datetime(2024, 1, 1, 15, 0, 0)  # lundi 15h00

# sla_deadline choisie pour obtenir exactement le pourcentage restant vise a NOW,
# budget = 8h = 28800s (priorite 1-Critique) :
ticket_45 = make_ticket(datetime(2024, 1, 1, 18, 36, 0), numero="T-45PCT")   # remaining=45%
ticket_35 = make_ticket(datetime(2024, 1, 1, 17, 48, 0), numero="T-35PCT")   # remaining=35%
ticket_08 = make_ticket(datetime(2024, 1, 1, 15, 38, 24), numero="T-08PCT")  # remaining=8%
ticket_breach = make_ticket(datetime(2024, 1, 1, 14, 36, 0), numero="T-BREACH")  # remaining=-5%

TICKETS = {
    "45%": ticket_45,
    "35%": ticket_35,
    "8%": ticket_08,
    "breach (-5%)": ticket_breach,
}

print("=" * 70)
print("Passage 1 : premier scan (tous les flags a False)")
print("=" * 70)

managers = sla_watchdog._get_managers()
print(f"        managers resolus (role=='admin') : {managers}")

pass1_updates = {}
for label, ticket in TICKETS.items():
    percent = sla_engine.sla_percent_remaining(ticket, NOW)
    triggered, updates = sla_watchdog.evaluate_ticket_alerts(ticket, NOW)
    print(f"\n--- Ticket {label} (percent reel = {percent:.1f}%) ---")
    pass1_updates[label] = (triggered, updates)

check("45% -> aucun palier declenche", [], pass1_updates["45%"][0])
check("35% -> SEULEMENT le palier 40", ["40"], pass1_updates["35%"][0])
check("8% -> paliers 40 ET 10 (rattrapage)", ["40", "10"], pass1_updates["8%"][0])
check("breach -> les 3 paliers (40, 10, breach)", ["40", "10", "breach"], pass1_updates["breach (-5%)"][0])

print()
print("--- Escalade manager (resolve_recipients) ---")
recipients_40 = sla_watchdog.resolve_recipients("40", "agent_test")
recipients_10 = sla_watchdog.resolve_recipients("10", "agent_test")
recipients_breach = sla_watchdog.resolve_recipients("breach", "agent_test")
check("palier 40 -> agent SEUL (pas d'escalade)", ["agent_test"], recipients_40)
check("palier 10 -> agent + managers (escalade)", ["agent_test"] + managers, recipients_10)
check("palier breach -> agent + managers (escalade)", ["agent_test"] + managers, recipients_breach)

print()
print("=" * 70)
print("Application des mises a jour de flags (simulation de la persistance)")
print("=" * 70)
for label, ticket in TICKETS.items():
    _, updates = pass1_updates[label]
    for field, value in updates.items():
        setattr(ticket, field, value)
    print(f"        {label} -> {updates or '(aucune mise a jour)'}")

print()
print("=" * 70)
print("Passage 2 : re-scan des MEMES tickets (flags maintenant a True)")
print("=" * 70)

pass2_triggered = {}
for label, ticket in TICKETS.items():
    triggered, updates = sla_watchdog.evaluate_ticket_alerts(ticket, NOW)
    pass2_triggered[label] = triggered
    print(f"        {label} -> paliers redeclenches : {triggered}")

check("45% -> toujours aucun palier (rien n'a change)", [], pass2_triggered["45%"])
check("35% -> AUCUNE alerte redeclenchee (dedup)", [], pass2_triggered["35%"])
check("8% -> AUCUNE alerte redeclenchee (dedup)", [], pass2_triggered["8%"])
check("breach -> AUCUNE alerte redeclenchee (dedup)", [], pass2_triggered["breach (-5%)"])

print()
print("=" * 70)
if FAILURES:
    print(f"RESULTAT : {len(FAILURES)} echec(s) sur les scenarios : {FAILURES}")
    sys.exit(1)
else:
    print("RESULTAT : tous les scenarios sont valides.")
    sys.exit(0)
