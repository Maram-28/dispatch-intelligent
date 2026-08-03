"""
Script de test autonome pour src/sla/sla_engine.py — dates FIXES, pas de "now" réel.
Ne nécessite pas que l'API tourne. Lancer avec : python tests/test_sla_engine.py

Convention : toutes les dates sont naïves, interprétées comme heure locale murale
(voir docstring de sla_engine.py). Le lundi 2024-01-01 sert de point de repère fixe.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.ticket_crew import ClassificationResult
from src.sla import sla_engine


FAILURES = []


def check(label, expected, actual):
    ok = expected == actual
    status = "OK  " if ok else "FAIL"
    print(f"[{status}] {label}")
    print(f"        attendu : {expected}")
    print(f"        obtenu  : {actual}")
    if not ok:
        FAILURES.append(label)


def make_ticket(**overrides):
    base = dict(
        numero="T-TEST",
        categorie="Incident",
        sous_categorie="Application",
        service="O365-PowerBI",
        impact="2-Moyen",
        urgence="2-Moyen",
        priorite_calculee="1-Critique",
        confidence=0.9,
        reasoning="test",
        status="new",
        started_at=None,
        paused_at=None,
        total_paused_seconds=0,
        sla_deadline=None,
    )
    base.update(overrides)
    return ClassificationResult(**base)


print("=" * 70)
print("Scenario 1 : ticket critique (8h) demarre lundi 09h00")
print("=" * 70)
started = datetime(2024, 1, 1, 9, 0, 0)  # lundi
deadline = sla_engine.compute_sla_deadline("1-Critique", started)
check("deadline lundi 17h00 (8h ouvrees le meme jour)", datetime(2024, 1, 1, 17, 0, 0), deadline)

print()
print("=" * 70)
print("Scenario 2 : ticket demarre vendredi 17h00 (2h ouvrees avant 19h)")
print("=" * 70)
started = datetime(2024, 1, 5, 17, 0, 0)  # vendredi
deadline = sla_engine.compute_sla_deadline("1-Critique", started)
check("le reste du delai (6h) bascule au lundi matin -> lundi 13h00", datetime(2024, 1, 8, 13, 0, 0), deadline)

print()
print("=" * 70)
print("Scenario 3 : pause manuelle de 3h (en_attente) puis reprise")
print("=" * 70)
started = datetime(2024, 1, 1, 8, 0, 0)  # lundi 08h00, priorite 2-Majeure (16h)
initial_deadline = sla_engine.compute_sla_deadline("2-Majeure", started)
check("deadline initiale = mardi 12h00 (avant mise en pause)", datetime(2024, 1, 2, 12, 0, 0), initial_deadline)

paused_at = datetime(2024, 1, 1, 14, 0, 0)  # lundi 14h00 (en heures ouvrees)
resumed_at = datetime(2024, 1, 1, 17, 0, 0)  # lundi 17h00, soit 3h de pause reelle et ouvree
ticket = make_ticket(
    priorite_calculee="2-Majeure",
    status="on_hold",
    started_at=started.isoformat(),
    sla_deadline=initial_deadline.isoformat(),
    paused_at=paused_at.isoformat(),
    total_paused_seconds=0,
)
updates = sla_engine.on_status_change(ticket, "in_progress", resumed_at)
check("deadline reculee de 3h ouvrees -> mardi 15h00",
      datetime(2024, 1, 2, 15, 0, 0), datetime.fromisoformat(updates["sla_deadline"]))
check("total_paused_seconds cumule les 3h reelles de pause", 3 * 3600, updates["total_paused_seconds"])

print()
print("=" * 70)
print("Scenario 3bis (bonus) : pause qui chevauche un week-end")
print("=" * 70)
print("-> verifie que l'extension utilise les secondes OUVREES et non le delta mural")
paused_at2 = datetime(2024, 1, 5, 18, 0, 0)   # vendredi 18h00 (encore ouvre, 1h avant 19h)
resumed_at2 = datetime(2024, 1, 8, 8, 0, 0)   # lundi 08h00 (1h apres l'ouverture)
ticket2 = make_ticket(
    priorite_calculee="3-Mineure",
    status="on_hold",
    started_at=datetime(2024, 1, 5, 7, 0, 0).isoformat(),
    sla_deadline=datetime(2024, 1, 5, 19, 0, 0).isoformat(),  # valeur arbitraire pour le test
    paused_at=paused_at2.isoformat(),
    total_paused_seconds=0,
)
updates2 = sla_engine.on_status_change(ticket2, "in_progress", resumed_at2)
wall_seconds = (resumed_at2 - paused_at2).total_seconds()
business_seconds = sla_engine.business_seconds_between(paused_at2, resumed_at2)
print(f"        pause reelle (murale) : {wall_seconds/3600:.1f}h")
print(f"        pause ouvree (correcte) : {business_seconds/3600:.1f}h")
# L'extension doit se faire via add_business_hours (pas une addition murale brute),
# pour rester alignee sur une plage ouvree meme si l'ancienne deadline etait a la
# limite de 19h (ici : jusqu'a lundi 09h00, et non vendredi 21h00 hors plage).
expected_deadline = sla_engine.add_business_hours(datetime(2024, 1, 5, 19, 0, 0), business_seconds / 3600)
check("l'extension de deadline vaut la duree OUVREE (2h) correctement realignee (pas la duree murale de 62h)",
      expected_deadline, datetime.fromisoformat(updates2["sla_deadline"]))
check("la deadline corrigee reste dans une plage ouvree (lundi 09h00, pas vendredi 21h00 hors plage)",
      datetime(2024, 1, 8, 9, 0, 0), datetime.fromisoformat(updates2["sla_deadline"]))

print()
print("=" * 70)
print("Scenario 3ter : extension de pause qui deborde 19h le jour meme (sans week-end)")
print("=" * 70)
print("-> reproduit le bug signale : addition murale brute -> deadline hors plage (mardi 21h)")
old_deadline3 = datetime(2024, 1, 2, 17, 0, 0)  # mardi 17h00, deadline deja alignee
paused_at3 = datetime(2024, 1, 2, 13, 0, 0)     # mardi 13h00 (heures ouvrees)
resumed_at3 = datetime(2024, 1, 2, 17, 0, 0)    # mardi 17h00 -> 4h ouvrees de pause
ticket3 = make_ticket(
    priorite_calculee="2-Majeure",
    status="on_hold",
    started_at=datetime(2024, 1, 2, 7, 0, 0).isoformat(),
    sla_deadline=old_deadline3.isoformat(),
    paused_at=paused_at3.isoformat(),
    total_paused_seconds=0,
)
updates3 = sla_engine.on_status_change(ticket3, "in_progress", resumed_at3)
new_deadline3 = datetime.fromisoformat(updates3["sla_deadline"])
buggy_deadline3 = old_deadline3 + timedelta(hours=4)  # ancien calcul (addition murale) : mardi 21h00
check("nouvelle deadline correctement realignee -> mercredi 09h00 (2h mardi 17-19h + 2h mercredi 7-9h)",
      datetime(2024, 1, 3, 9, 0, 0), new_deadline3)
if new_deadline3 == buggy_deadline3:
    print(f"[FAIL] la deadline correspond encore au calcul mural bugge ({buggy_deadline3})")
    FAILURES.append("regression bug resume (deadline hors plage)")
else:
    print(f"[OK  ] la deadline ne correspond plus au calcul mural bugge ({buggy_deadline3}), comme attendu")

# now dans la "zone morte" (mardi 20h, apres 19h mais avant la nouvelle deadline du lendemain) :
# le temps restant doit rester correct et positif par rapport a la deadline corrigee, pas
# proche de zero/negatif comme avec l'ancienne deadline buguee (mardi 21h).
ticket3_resumed = make_ticket(
    priorite_calculee="2-Majeure",
    status="in_progress",
    started_at=datetime(2024, 1, 2, 7, 0, 0).isoformat(),
    sla_deadline=updates3["sla_deadline"],
    paused_at=None,
    total_paused_seconds=updates3["total_paused_seconds"],
)
now_dead_zone = datetime(2024, 1, 2, 20, 0, 0)  # mardi 20h00, zone morte hors plage ouvree
remaining3 = sla_engine.business_seconds_remaining(ticket3_resumed, now_dead_zone)
check("temps ouvre restant correct en zone morte (2h, pas proche de zero/negatif)",
      2 * 3600.0, remaining3)

print()
print("=" * 70)
print("Scenario 4 : sla_percent_remaining ~40% et ~10%")
print("=" * 70)
started = datetime(2024, 1, 1, 7, 0, 0)  # lundi 07h00, priorite 1-Critique (8h) -> deadline 15h00
deadline = sla_engine.compute_sla_deadline("1-Critique", started)
ticket = make_ticket(
    priorite_calculee="1-Critique",
    status="in_progress",
    started_at=started.isoformat(),
    sla_deadline=deadline.isoformat(),
)

now_40pct = datetime(2024, 1, 1, 11, 48, 0)  # 40% de 8h = 3h12 restantes avant 15h00
pct = sla_engine.sla_percent_remaining(ticket, now_40pct)
check("~40% restant a 11h48", 40.0, round(pct, 1))

now_10pct = datetime(2024, 1, 1, 14, 12, 0)  # 10% de 8h = 48min restantes avant 15h00
pct = sla_engine.sla_percent_remaining(ticket, now_10pct)
check("~10% restant a 14h12", 10.0, round(pct, 1))

print()
print("=" * 70)
print("Scenario 5 : ticket depasse -> business_seconds_remaining negatif, sla_breached")
print("=" * 70)
now_breached = datetime(2024, 1, 1, 16, 0, 0)  # 1h apres la deadline (15h00), toujours en heures ouvrees
remaining = sla_engine.business_seconds_remaining(ticket, now_breached)
check("business_seconds_remaining negatif (-3600s)", -3600.0, remaining)
check("is_breached == True", True, sla_engine.is_breached(ticket, now_breached))

done_updates = sla_engine.on_status_change(ticket, "done", now_breached)
check("sla_breached == True apres resolution", True, done_updates["sla_breached"])
check("resolution_time_business_seconds = 9h (8h budget + 1h de depassement)",
      9 * 3600.0, done_updates["resolution_time_business_seconds"])

print()
print("=" * 70)
print("Scenario 6 : compute_priority (matrice impact x urgence canonique)")
print("=" * 70)
check("1-Majeur / 1-Elevee (accentue, reel) -> 1-Critique",
      "1-Critique", sla_engine.compute_priority("1 - Majeur", "1 - Élevée"))
check("2-Modere / 2-Moyenne -> 2-Majeure",
      "2-Majeure", sla_engine.compute_priority("2 - Modéré", "2 - Moyenne"))
check("3-Mineur / 3-Faible -> 4-Standard",
      "4-Standard", sla_engine.compute_priority("3 - Mineur", "3 - Faible"))
check("paire hors taxonomie (N/A / ???) -> repli fail-strict 1-Critique",
      "1-Critique", sla_engine.compute_priority("N/A", "???"))
check("forme NON accentuee 'Elevee' (typo historique) -> repli fail-strict 1-Critique "
      "(ne doit PAS etre silencieusement acceptee comme equivalente a 'Élevée')",
      "1-Critique", sla_engine.compute_priority("1 - Majeur", "1 - Elevée"))

_IMPACTS  = ["1 - Majeur", "2 - Modéré", "3 - Mineur"]
_URGENCES = ["1 - Élevée", "2 - Moyenne", "3 - Faible"]
all_valid = True
for impact in _IMPACTS:
    for urgence in _URGENCES:
        priority = sla_engine.compute_priority(impact, urgence)
        if priority not in sla_engine.SLA_HOURS:
            all_valid = False
            print(f"        !! {impact!r}/{urgence!r} -> {priority!r} n'est PAS une cle de SLA_HOURS")
check("les 9 combinaisons valides retournent toutes une cle presente dans SLA_HOURS",
      True, all_valid)

print()
print("=" * 70)
if FAILURES:
    print(f"RESULTAT : {len(FAILURES)} echec(s) sur les scenarios : {FAILURES}")
    sys.exit(1)
else:
    print("RESULTAT : tous les scenarios sont valides.")
    sys.exit(0)
