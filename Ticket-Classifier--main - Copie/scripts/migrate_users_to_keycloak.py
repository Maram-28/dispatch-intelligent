"""
Script de migration one-shot — crée dans Keycloak un compte pour chaque entrée de
data/processed/users.json (voir infra/keycloak/README.md pour le contexte complet
de la bascule AUTH_MODE=legacy -> keycloak).

Pourquoi aucun mot de passe n'est jamais recopié : les hash bcrypt de users.json ne
peuvent pas être importés tels quels dans le hashing provider par défaut de
Keycloak (pbkdf2-sha256) — les réutiliser reviendrait à deviner/rejouer le mot de
passe en clair, ce qui n'est de toute façon jamais accessible depuis un hash. Ce
script crée donc chaque compte avec un mot de passe temporaire aléatoire,
immédiatement jeté (jamais affiché ni loggé), marqué `temporary=True` +
`requiredActions=["UPDATE_PASSWORD"]`, puis déclenche l'email Keycloak natif
"définir votre mot de passe" (requiert le SMTP du realm configuré — voir le
README ci-dessus). Aucune communication de mot de passe hors bande n'est donc
nécessaire.

Usage (depuis la racine de "Ticket-Classifier--main - Copie") :
  python scripts/migrate_users_to_keycloak.py                # dry-run
  python scripts/migrate_users_to_keycloak.py --apply         # crée réellement les comptes

Idempotent : un utilisateur déjà présent dans le realm (même username) est signalé
"déjà existant" et sauté, sans erreur — le script peut être relancé sans risque.
"""

import argparse
import json
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src import keycloak_admin as ka

USERS_FILE = Path("data/processed/users.json")


def _generate_temp_password() -> str:
    return secrets.token_urlsafe(24)


def migrate(users: list, apply: bool) -> list:
    report = []
    for u in users:
        username, email, nom, role = u["id"], u.get("email", ""), u.get("nom", u["id"]), u.get("role", "agent")

        if not apply:
            report.append({"id": username, "role": role, "action": "[DRY-RUN] créerait le compte + enverrait l'email de reset"})
            continue

        created = ka.create_user(username, email, nom, role, _generate_temp_password())
        if not created:
            report.append({"id": username, "role": role, "action": "déjà existant — sauté"})
            continue

        emailed = ka.send_password_reset_email(username)
        action = "créé, email de reset envoyé" if emailed else "créé, ÉCHEC envoi email (vérifier le SMTP du realm)"
        report.append({"id": username, "role": role, "action": action})

    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", default=str(USERS_FILE), help="Chemin de users.json à migrer.")
    parser.add_argument("--apply", action="store_true", help="Crée réellement les comptes (sinon dry-run).")
    args = parser.parse_args()

    target = Path(args.file)
    if not target.exists():
        print(f"Fichier introuvable : {target}")
        sys.exit(1)

    with open(target, encoding="utf-8") as f:
        users = json.load(f)

    report = migrate(users, args.apply)

    print("=" * 78)
    print(f"{'[DRY-RUN] ' if not args.apply else '[APPLY] '}Migration users.json -> Keycloak ({ka.KEYCLOAK_URL}, realm {ka.KEYCLOAK_REALM})")
    print("=" * 78)
    print(f"Comptes inspectés : {len(users)}")
    print()
    for entry in report:
        print(f"  {entry['id']:<20} [{entry['role']:<6}] {entry['action']}")

    if not args.apply:
        print("\nDry-run — rien n'a été créé. Relancer avec --apply pour créer les comptes.")


if __name__ == "__main__":
    main()
