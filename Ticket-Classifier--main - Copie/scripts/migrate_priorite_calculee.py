"""
Script de migration one-shot — corrige `priorite_calculee` dans classifications_db.json.

Contexte : avant le fix de src/agents/ticket_crew.py + src/sla/sla_engine.py, le LLM
écrivait `priorite_calculee` dans un format ("1 - Critique", "2 - Majeur", parfois le
placeholder du prompt "valeur textuelle") qui ne correspondait JAMAIS aux clés attendues
par sla_engine.SLA_HOURS ("1-Critique", "2-Majeure", ...). Conséquence : tous les tickets
déjà persistés ont une priorité mal formatée et, pour ceux avec un chrono actif, une
sla_deadline calculée sur le budget par défaut (96h) au lieu du vrai budget de leur
priorité.

Ce script recalcule `priorite_calculee` de façon déterministe depuis `impact`/`urgence`
(sla_engine.compute_priority, la même fonction que le pipeline de classification utilise
désormais) pour chaque ticket déjà en base, et — pour les tickets à chrono actif
(in_progress/on_hold) dont la priorité change — recalcule `sla_deadline` en conséquence.

Portée volontairement limitée (voir AUDIT_REPORT.md finding #1 et le plan associé) :
  - Tickets "done" : seul le libellé `priorite_calculee` est corrigé (cohérence
    d'affichage). Le verdict SLA historique (resolution_time_business_seconds,
    sla_breached) n'est PAS retouché : recalculer changerait rétroactivement si un
    ticket a été jugé "dans les temps", ce qui serait plus trompeur qu'utile.
  - Tickets "in_progress"/"on_hold" : la nouvelle deadline est recalculée depuis
    started_at avec le nouveau budget — approximation qui ignore l'historique fin des
    pauses déjà écoulées (non reconstituible précisément : total_paused_seconds est un
    cumul en temps mural, pas la somme des portions ouvrées de chaque pause). Les flags
    de dédup d'alerte SLA (sla_alert_40_sent/10_sent/breach_sent) sont réinitialisés à
    False par sûreté (l'audit a confirmé qu'aucune alerte n'a jamais pu être envoyée
    jusqu'ici avec l'ancien bug, donc ce reset est une mesure de sûreté, pas un
    changement de comportement réel).
  - Tickets "new" : correction du libellé uniquement, pas de sla_deadline à toucher.

Usage (depuis la racine du projet) :
  python scripts/migrate_priorite_calculee.py                       # dry-run sur le fichier par défaut
  python scripts/migrate_priorite_calculee.py --file copie.json      # dry-run sur une copie
  python scripts/migrate_priorite_calculee.py --file copie.json --apply   # applique réellement
  python scripts/migrate_priorite_calculee.py --apply                # applique sur le fichier réel

Sans --apply : dry-run, affiche uniquement ce qui changerait, n'écrit rien.
Avec --apply : sauvegarde d'abord l'original en <file>.backup-<timestamp>.json, puis écrit.
"""

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.sla import sla_engine

ACTIVE_STATUSES = ("in_progress", "on_hold")


def migrate(tickets: list) -> tuple:
    """Applique les corrections en mémoire. Retourne (tickets_modifies, rapport)."""
    report = []
    corrected = 0

    for t in tickets:
        numero = t.get("numero", "?")
        old_priority = t.get("priorite_calculee")
        new_priority = sla_engine.compute_priority(t.get("impact"), t.get("urgence"))

        if new_priority == old_priority:
            continue

        status = t.get("status", "new")
        old_deadline = t.get("sla_deadline")
        new_deadline = old_deadline
        deadline_note = "inchangée"

        if status in ACTIVE_STATUSES and t.get("started_at"):
            started = datetime.fromisoformat(t["started_at"])
            new_deadline = sla_engine.compute_sla_deadline(new_priority, started).isoformat()
            t["sla_deadline"] = new_deadline
            t["sla_alert_40_sent"] = False
            t["sla_alert_10_sent"] = False
            t["sla_alert_breach_sent"] = False
            deadline_note = f"{old_deadline} -> {new_deadline}"
        elif status == "done":
            deadline_note = "inchangée (ticket clos — verdict SLA historique non retouché)"
        elif status in ACTIVE_STATUSES and not t.get("started_at"):
            deadline_note = "inchangée (started_at absent — cas inattendu, à vérifier manuellement)"

        t["priorite_calculee"] = new_priority
        corrected += 1
        report.append({
            "numero": numero,
            "status": status,
            "priority": f"{old_priority!r} -> {new_priority!r}",
            "deadline": deadline_note,
        })

    return tickets, {"total": len(tickets), "corrected": corrected, "unchanged": len(tickets) - corrected, "entries": report}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", default="data/output/classifications_db.json", help="Chemin du fichier à migrer.")
    parser.add_argument("--apply", action="store_true", help="Écrit réellement les changements (sinon dry-run).")
    args = parser.parse_args()

    target = Path(args.file)
    if not target.exists():
        print(f"Fichier introuvable : {target}")
        sys.exit(1)

    with open(target, encoding="utf-8") as f:
        tickets = json.load(f)

    tickets, result = migrate(tickets)

    print("=" * 78)
    print(f"{'[DRY-RUN] ' if not args.apply else '[APPLY] '}Migration priorite_calculee — {target}")
    print("=" * 78)
    print(f"Tickets inspectés : {result['total']}")
    print(f"Tickets corrigés  : {result['corrected']}")
    print(f"Tickets inchangés : {result['unchanged']}")
    print()

    for entry in result["entries"]:
        print(f"  {entry['numero']:<14} [{entry['status']:<11}] priorite: {entry['priority']}")
        print(f"                          deadline: {entry['deadline']}")

    if result["corrected"] == 0:
        print("\nAucune correction nécessaire.")
        return

    if not args.apply:
        print("\nDry-run — rien n'a été écrit. Relancer avec --apply pour appliquer ces changements.")
        return

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = target.with_suffix(f".backup-{timestamp}.json")
    shutil.copy2(target, backup_path)
    print(f"\nSauvegarde de l'original : {backup_path}")

    with open(target, "w", encoding="utf-8") as f:
        json.dump(tickets, f, ensure_ascii=False, indent=2)
    print(f"Fichier mis à jour : {target}")


if __name__ == "__main__":
    main()
