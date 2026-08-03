"""
CLI tool to manage L2 team member availability.

Usage:
  python -m src.agents.set_availability --liste
  python -m src.agents.set_availability --membre cherazade_hamdi --dispo false --raison "Congé"
  python -m src.agents.set_availability --membre all --dispo true

AVAILABILITY_MODE env var: "manual" (default) | "teams" (future Microsoft Graph)
"""

import argparse
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from src.agents import profiles_store

AVAILABILITY_MODE = os.getenv("AVAILABILITY_MODE", "manual")

TEAM_IDS = [
    "cherazade_hamdi",
    "leila_skouri",
    "mariem_el_ouekdi",
    "mohamed_rabeh_boukahla",
    "mohamed_salah_baccouche",
]

# ─────────────────────────────────────────────
#  I/O helpers
# ─────────────────────────────────────────────

def _sync_to_profiles(avail_data: dict) -> None:
    """Push disponible changes back into member_profiles.json.

    Ne synchronise QUE la disponibilité : availability.json n'a jamais été la source de
    vérité de charge_actuelle (seul run_update()/member_profiles.json l'est — voir
    AUDIT_REPORT.md). Un synchronisation de charge_actuelle ici écraserait silencieusement
    la vraie valeur avec le champ périmé/toujours à zéro d'availability.json.
    """
    try:
        with profiles_store.profiles_transaction() as profiles:
            avail_map = {a["id"]: a for a in avail_data.get("members", [])}
            for profile in profiles:
                av = avail_map.get(profile["id"])
                if av:
                    profile["disponible"] = av["disponible"]
    except FileNotFoundError:
        return  # profils pas encore initialisés — rien à synchroniser

# ─────────────────────────────────────────────
#  Commands
# ─────────────────────────────────────────────

def cmd_liste() -> None:
    data = profiles_store.load_availability()
    try:
        charge_map = {p["id"]: p["charge_actuelle"] for p in profiles_store.load_profiles()}
    except FileNotFoundError:
        charge_map = {}  # profils pas encore initialisés

    print(f"\n{'ID':<35} {'Disponible':<12} {'Charge':<8} Raison")
    print("-" * 75)
    for m in data["members"]:
        dot   = "🟢" if m["disponible"] else "🔴"
        raison = m.get("raison", "") or ""
        charge = charge_map.get(m["id"], 0)
        print(f"{m['id']:<35} {dot} {str(m['disponible']):<10} {charge:<8} {raison}")
    print()


def cmd_update(membre_id: str, dispo: bool, raison: str) -> None:
    if AVAILABILITY_MODE == "teams":
        print("AVAILABILITY_MODE=teams: updates via Microsoft Graph API (not yet implemented).")
        sys.exit(1)

    with profiles_store.availability_transaction() as data:
        members = data.setdefault("members", [])

        # Ensure all team IDs are present
        existing_ids = {m["id"] for m in members}
        for mid in TEAM_IDS:
            if mid not in existing_ids:
                members.append({"id": mid, "disponible": True, "raison": ""})

        if membre_id == "all":
            for m in members:
                m["disponible"] = dispo
                if raison:
                    m["raison"] = raison
            print(f"✓ All members set to disponible={dispo}")
        else:
            if membre_id not in TEAM_IDS:
                print(f"Unknown member ID '{membre_id}'. Valid IDs: {', '.join(TEAM_IDS)}")
                sys.exit(1)
            for m in members:
                if m["id"] == membre_id:
                    m["disponible"] = dispo
                    m["raison"] = raison
                    break
            else:
                members.append({"id": membre_id, "disponible": dispo, "raison": raison})
            status = "available" if dispo else "absent"
            print(f"✓ {membre_id} → {status}" + (f" ({raison})" if raison else ""))

    _sync_to_profiles(data)

# ─────────────────────────────────────────────
#  Public helpers (importable by other modules)
# ─────────────────────────────────────────────

def get_availability() -> dict:
    """Return availability dict {member_id: {disponible, raison}}. charge_actuelle
    n'existe pas dans availability.json — member_profiles.json en est l'unique source."""
    data = profiles_store.load_availability()
    return {m["id"]: m for m in data.get("members", [])}


def set_member_availability(membre_id: str, disponible: bool, raison: str = "") -> None:
    cmd_update(membre_id, disponible, raison)

# ─────────────────────────────────────────────
#  CLI entry point
# ─────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage L2 team availability (AVAILABILITY_MODE=manual|teams)"
    )
    parser.add_argument("--liste",   action="store_true", help="Show all members availability")
    parser.add_argument("--membre",  type=str, help="Member ID or 'all'")
    parser.add_argument("--dispo",   type=str, help="true / false")
    parser.add_argument("--raison",  type=str, default="", help="Reason for unavailability")
    args = parser.parse_args()

    if args.liste:
        cmd_liste()
        return

    if args.membre:
        if args.dispo is None:
            parser.error("--dispo is required when using --membre")
        dispo_bool = args.dispo.lower() in ("true", "1", "yes", "oui")
        cmd_update(args.membre, dispo_bool, args.raison)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
