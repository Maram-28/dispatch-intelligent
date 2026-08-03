"""
Script de migration one-shot — remet à zéro les métriques de performance dans
member_profiles.json.

Contexte : profiling_agent.run_bootstrap() ne dérive plus les métriques de performance
(total tickets, résolution moyenne/médiane, taux de respect SLA, répartitions, score) depuis
incident-10000.xlsx — désormais seules les résolutions réelles de tickets dans l'app
(update_after_resolution(), alimentée par le temps SLA réel) les font évoluer. Bootstrap
préserve maintenant ces métriques d'un run à l'autre (voir _build_profiles), donc un simple
re-bootstrap ne suffit plus à repartir de zéro : ce script fait la transition une seule fois,
pour le member_profiles.json déjà peuplé par l'ancien comportement (dérivé de l'Excel).

Champs remis à zéro par membre : total_tickets_historique, resolution_moy_heures,
resolution_median_heures, resolution_times_h, repartition_priorites,
taux_resolution_par_priorite, temps_moyen_par_categorie, taux_respect_sla_pct,
nb_reaffectations_total, historique_resolutions, et score_performance (recalculé via la
même formule que _build_profiles utilise pour un membre neuf).

Inchangés : id, nom, email, groupe, competences, specialisations, charge_actuelle,
disponible — ces champs ne sont pas concernés par ce changement.

Usage (depuis la racine du projet) :
  python scripts/reset_profile_stats.py                      # dry-run sur le fichier par défaut
  python scripts/reset_profile_stats.py --file copie.json    # dry-run sur une copie
  python scripts/reset_profile_stats.py --apply               # applique sur le fichier réel

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

from src.agents.profiling_agent import _zero_metriques, _compute_score

_ZERO_STATS = {"resolution_median_h": 0.0, "total_tickets": 0, "taux_respect_sla_pct": 0.0}


def reset(profiles: list) -> tuple:
    """Applique la remise à zéro en mémoire. Retourne (profiles, rapport)."""
    report = []
    reset_count = 0
    neutral_score = _compute_score(_ZERO_STATS, [_ZERO_STATS])

    for p in profiles:
        old_metriques = p.get("metriques", {})
        old_total   = old_metriques.get("total_tickets_historique", 0)
        old_score   = p.get("score_performance")

        p["metriques"]             = _zero_metriques()
        p["historique_resolutions"] = {"par_categorie": {}, "par_priorite": {}}
        p["score_performance"]     = neutral_score
        reset_count += 1

        report.append({
            "id": p.get("id", "?"),
            "nom": p.get("nom", "?"),
            "tickets": f"{old_total} -> 0",
            "score": f"{old_score} -> {neutral_score}",
        })

    return profiles, {"total": len(profiles), "reset": reset_count, "entries": report}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", default="data/processed/member_profiles.json", help="Chemin du fichier à migrer.")
    parser.add_argument("--apply", action="store_true", help="Écrit réellement les changements (sinon dry-run).")
    args = parser.parse_args()

    target = Path(args.file)
    if not target.exists():
        print(f"Fichier introuvable : {target}")
        sys.exit(1)

    with open(target, encoding="utf-8") as f:
        profiles = json.load(f)

    profiles, result = reset(profiles)

    print("=" * 78)
    print(f"{'[DRY-RUN] ' if not args.apply else '[APPLY] '}Remise à zéro des métriques de performance — {target}")
    print("=" * 78)
    print(f"Profils inspectés : {result['total']}")
    print(f"Profils remis à zéro : {result['reset']}")
    print()

    for entry in result["entries"]:
        print(f"  {entry['nom']:<35} tickets: {entry['tickets']:<12} score: {entry['score']}")

    if not args.apply:
        print("\nDry-run — rien n'a été écrit. Relancer avec --apply pour appliquer ces changements.")
        return

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = target.with_suffix(f".backup-{timestamp}.json")
    shutil.copy2(target, backup_path)
    print(f"\nSauvegarde de l'original : {backup_path}")

    with open(target, "w", encoding="utf-8") as f:
        json.dump(profiles, f, ensure_ascii=False, indent=2)
    print(f"Fichier mis à jour : {target}")


if __name__ == "__main__":
    main()
