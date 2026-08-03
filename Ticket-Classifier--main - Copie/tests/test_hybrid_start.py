"""
Test d'integration REEL du demarrage hybride "Commencer" manuel + auto-start 15 min
(voir sla_watchdog.auto_start_assigned_tickets et update_my_ticket_status/api.py).

A la difference de tests/test_sla_watchdog.py (logique pure, sans I/O), ce script :
  1) insere TEMPORAIREMENT des tickets de test (prefixes TEST-HYBRID-) dans
     classifications_db.json, restaures a l'identique en sortie (try/finally,
     snapshot/restore integral, meme pattern que test_sla_watchdog_integration.py),
  2) pose TEMPORAIREMENT un mot de passe de test sur un compte agent Keycloak existant
     (reset-password via l'API Admin, restaure via requiredActions=UPDATE_PASSWORD a
     la fin, meme en cas d'erreur) pour appeler PATCH /agent/tickets/{numero}/status
     comme le ferait vraiment cet agent,
  3) authentifie ce compte via le flow reel Authorization Code + PKCE (pas de grant
     "password" : le client public ticket-dispatch-frontend ne l'autorise pas — voir
     infra/keycloak/README.md, section "Verification manuelle du flow", reproduite
     ici en HTTP pur plutot qu'au clavier).

Ne fait AUCUNE hypothese de timing reel (pas de sleep, pas d'attente de 15 minutes) :
les tickets sont toujours crees avec un created_at FRAIS (evite toute interference
avec le vrai job auto_start_assigned_tickets du serveur en cours d'execution, qui
tourne toutes les minutes sur de vraies dates), et le passage "15 minutes plus tard"
est simule en appelant directement auto_start_assigned_tickets(now=<synthetique>).

Prerequis :
  - Le backend doit deja tourner (python run_backend.py), AUTH_MODE=keycloak.
  - Keycloak doit deja tourner (infra/keycloak, docker compose), realm lvmh-tickets
    importe, avec au moins un compte role=="agent".
  - Identifiants admin Keycloak (KEYCLOAK_ADMIN/KEYCLOAK_ADMIN_PASSWORD, voir infra/.env
    — stack de developpement local uniquement, pas de TLS, voir infra/keycloak/README.md).

Usage :
  python tests/test_hybrid_start.py --agent-id cherazade_hamdi \\
      --kc-admin admin --kc-admin-password DevAdminPass123! --confirm
"""

import argparse
import base64
import hashlib
import os
import re
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.ticket_crew import ClassificationResult, AssignmentInfo
from src.api import DB_FILE, save_to_db, load_db
from src.sla import sla_watchdog

KEYCLOAK_URL = "http://localhost:8180"
REALM = "lvmh-tickets"
CLIENT_ID = "ticket-dispatch-frontend"
TEMP_PASSWORD = "TestHybridStart123!"

FAILURES = []


def check(label, expected, actual):
    ok = expected == actual
    print(f"[{'OK  ' if ok else 'FAIL'}] {label}")
    print(f"        attendu : {expected}")
    print(f"        obtenu  : {actual}")
    if not ok:
        FAILURES.append(label)


def snapshot_file(path: Path):
    return path.read_text(encoding="utf-8") if path.exists() else None


def restore_file(path: Path, snapshot) -> None:
    if snapshot is None:
        if path.exists():
            path.unlink()
    else:
        path.write_text(snapshot, encoding="utf-8")


def make_ticket(numero: str, agent_id: str, created_at: datetime) -> ClassificationResult:
    return ClassificationResult(
        numero=numero, categorie="Incident", sous_categorie="Application",
        service="O365-PowerBI", impact="2-Moyen", urgence="2-Moyen",
        priorite_calculee="2-Majeure", confidence=0.9,
        reasoning="Ticket de test - demarrage hybride", titre="[TEST] Hybrid start",
        status="new", created_at=created_at.isoformat(),
        assigned_to=AssignmentInfo(membre_id=agent_id, nom=agent_id, score_assignation=0.9, justification="test"),
    )


# ─── Keycloak plumbing ──────────────────────────────────────────────────────

def kc_admin_token(admin_user: str, admin_password: str) -> str:
    resp = requests.post(
        f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token",
        data={"grant_type": "password", "client_id": "admin-cli",
              "username": admin_user, "password": admin_password},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def kc_find_user_id(admin_token: str, username: str) -> str:
    resp = requests.get(
        f"{KEYCLOAK_URL}/admin/realms/{REALM}/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        params={"username": username, "exact": "true"},
    )
    resp.raise_for_status()
    users = resp.json()
    if not users:
        raise RuntimeError(f"Utilisateur Keycloak '{username}' introuvable dans le realm {REALM}")
    return users[0]["id"]


def kc_set_temp_password(admin_token: str, user_id: str, password: str) -> None:
    resp = requests.put(
        f"{KEYCLOAK_URL}/admin/realms/{REALM}/users/{user_id}/reset-password",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"type": "password", "value": password, "temporary": False},
    )
    resp.raise_for_status()


def kc_require_password_reset(admin_token: str, user_id: str) -> None:
    """Invalide le mot de passe de test pose ci-dessus en forcant un changement au
    prochain login — ne le laisse pas utilisable comme identifiant permanent."""
    resp = requests.put(
        f"{KEYCLOAK_URL}/admin/realms/{REALM}/users/{user_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"requiredActions": ["UPDATE_PASSWORD"]},
    )
    resp.raise_for_status()


def pkce_pair():
    verifier = base64.urlsafe_b64encode(os.urandom(40)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def kc_agent_token_via_pkce(username: str, password: str, redirect_uri: str) -> str:
    """Reproduit infra/keycloak/README.md ("Verification manuelle du flow Authorization
    Code + PKCE") en HTTP pur : le client public ticket-dispatch-frontend n'autorise pas
    le grant "password" (Direct Access Grants desactive, PKCE uniquement — verifie en
    amont de ce script), donc on simule le formulaire de login que le navigateur
    soumettrait normalement.

    Keycloak pose AUTH_SESSION_ID/KC_RESTART avec l'attribut Secure, meme sur ce realm
    de dev en http:// (pas de TLS, voir infra/keycloak/README.md) — http.cookiejar
    (utilise par requests.Session) refuse de renvoyer un cookie Secure sur une connexion
    non-https, ce qui ferait echouer le POST du formulaire ("Cookie introuvable").
    On propage donc ces deux cookies nous-memes via l'en-tete Cookie, en contournant le
    jar automatique.
    """
    verifier, challenge = pkce_pair()
    state = uuid.uuid4().hex

    session = requests.Session()
    auth_resp = session.get(
        f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/auth",
        params={
            "client_id": CLIENT_ID, "response_type": "code", "scope": "openid",
            "redirect_uri": redirect_uri, "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256",
        },
    )
    auth_resp.raise_for_status()
    match = re.search(r'action="([^"]+)"', auth_resp.text)
    if not match:
        raise RuntimeError("Formulaire de login Keycloak introuvable dans la reponse (theme modifie ?)")
    login_action = match.group(1).replace("&amp;", "&")

    cookie_header = "; ".join(f"{c.name}={c.value}" for c in session.cookies)

    login_resp = session.post(
        login_action, data={"username": username, "password": password},
        headers={"Cookie": cookie_header},
    )
    login_resp.raise_for_status()
    redirected_url = login_resp.url
    query = parse_qs(urlparse(redirected_url).query)
    if "code" not in query:
        raise RuntimeError(
            f"Pas de 'code' dans l'URL de redirection ({redirected_url}) — identifiants "
            "invalides ou mot de passe de test pas encore propage ?"
        )
    code = query["code"][0]

    token_resp = requests.post(
        f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token",
        data={
            "grant_type": "authorization_code", "client_id": CLIENT_ID,
            "redirect_uri": redirect_uri, "code": code, "code_verifier": verifier,
        },
    )
    token_resp.raise_for_status()
    return token_resp.json()["access_token"]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--redirect-uri", default="http://localhost:5173/")
    parser.add_argument("--agent-id", required=True, help="id d'un compte role=='agent' (business id = username Keycloak)")
    parser.add_argument("--kc-admin", required=True)
    parser.add_argument("--kc-admin-password", required=True)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()

    print("=" * 70)
    print("Ce test va poser TEMPORAIREMENT un mot de passe de test sur le compte")
    print(f"Keycloak '{args.agent_id}' (restaure via requiredActions=UPDATE_PASSWORD a la")
    print("fin), et inserer/retirer des tickets de test dans classifications_db.json.")
    print("=" * 70)
    if not args.confirm:
        if input("Continuer ? [y/N] : ").strip().lower() != "y":
            print("Annule.")
            sys.exit(0)

    db_snapshot = snapshot_file(DB_FILE)
    suffix = uuid.uuid4().hex[:8]
    numeros = {k: f"TEST-HYBRID-{k}-{suffix}" for k in ("manual", "auto", "race_auto_first", "race_manual_first")}

    admin_token = kc_admin_token(args.kc_admin, args.kc_admin_password)
    user_id = kc_find_user_id(admin_token, args.agent_id)
    kc_set_temp_password(admin_token, user_id, TEMP_PASSWORD)
    print(f"[TEST] Mot de passe temporaire pose sur '{args.agent_id}'.")

    try:
        agent_token = kc_agent_token_via_pkce(args.agent_id, TEMP_PASSWORD, args.redirect_uri)
        headers = {"Authorization": f"Bearer {agent_token}"}
        print("[TEST] Authentification agent OK (Authorization Code + PKCE).")

        # ─── Scenario 1 : clic manuel avant les 15 minutes ──────────────────
        now1 = datetime.now()
        save_to_db(make_ticket(numeros["manual"], args.agent_id, now1))
        resp = requests.patch(f"{args.base_url}/agent/tickets/{numeros['manual']}/status",
                               json={"action": "start"}, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        check("Scenario 1 (clic manuel) -> statut in_progress", "in_progress", data["status"])
        check("Scenario 1 -> started_at pose", True, data["started_at"] is not None)
        check("Scenario 1 -> sla_deadline pose", True, data["sla_deadline"] is not None)

        # Le watchdog auto-start, simule APRES le clic manuel, ne doit rien faire.
        auto_results = sla_watchdog.auto_start_assigned_tickets(now=now1 + timedelta(minutes=16))
        touched = [r["numero"] for r in auto_results]
        check("Scenario 1 -> auto-start n'a PAS retouche le ticket deja demarre manuellement",
              False, numeros["manual"] in touched)
        after = next(t for t in load_db() if t.numero == numeros["manual"])
        check("Scenario 1 -> started_at inchange apres le passage du watchdog",
              data["started_at"], after.started_at)

        # ─── Scenario 2 : absence d'action, auto-start apres 15 min ─────────
        now2 = datetime.now()
        save_to_db(make_ticket(numeros["auto"], args.agent_id, now2))
        auto_results = sla_watchdog.auto_start_assigned_tickets(now=now2 + timedelta(minutes=16))
        touched = [r["numero"] for r in auto_results]
        check("Scenario 2 (pas d'action, >15min) -> ticket demarre automatiquement",
              True, numeros["auto"] in touched)
        after = next(t for t in load_db() if t.numero == numeros["auto"])
        check("Scenario 2 -> statut in_progress", "in_progress", after.status)
        check("Scenario 2 -> started_at ancre sur created_at+15min (pas sur l'heure du scan)",
              (now2 + timedelta(minutes=15)).isoformat(), after.started_at)

        # Un clic "Commencer" tardif (bouton reste affiche car la fiche etait deja
        # ouverte) doit etre un no-op idempotent, pas une erreur ni un second demarrage.
        resp = requests.patch(f"{args.base_url}/agent/tickets/{numeros['auto']}/status",
                               json={"action": "start"}, headers=headers)
        check("Scenario 2 -> clic tardif apres auto-start renvoie 200 (idempotent)",
              200, resp.status_code)
        data2 = resp.json()
        check("Scenario 2 -> clic tardif ne change PAS started_at (pas de double demarrage)",
              after.started_at, data2["started_at"])

        # ─── Scenario 3a : course, le watchdog ecrit en premier ─────────────
        now3a = datetime.now()
        save_to_db(make_ticket(numeros["race_auto_first"], args.agent_id, now3a))
        sla_watchdog.auto_start_assigned_tickets(now=now3a + timedelta(minutes=16))
        won_by_auto = next(t for t in load_db() if t.numero == numeros["race_auto_first"])
        resp = requests.patch(f"{args.base_url}/agent/tickets/{numeros['race_auto_first']}/status",
                               json={"action": "start"}, headers=headers)
        check("Scenario 3a (watchdog gagne la course) -> le clic manuel qui arrive apres renvoie 200",
              200, resp.status_code)
        data3a = resp.json()
        check("Scenario 3a -> started_at reste celui du watchdog (pas ecrase par le clic)",
              won_by_auto.started_at, data3a["started_at"])

        # ─── Scenario 3b : course, le clic manuel ecrit en premier ──────────
        now3b = datetime.now()
        save_to_db(make_ticket(numeros["race_manual_first"], args.agent_id, now3b))
        resp = requests.patch(f"{args.base_url}/agent/tickets/{numeros['race_manual_first']}/status",
                               json={"action": "start"}, headers=headers)
        resp.raise_for_status()
        data3b = resp.json()
        auto_results = sla_watchdog.auto_start_assigned_tickets(now=now3b + timedelta(minutes=16))
        touched = [r["numero"] for r in auto_results]
        check("Scenario 3b (clic manuel gagne la course) -> le watchdog qui tourne apres ne retouche pas le ticket",
              False, numeros["race_manual_first"] in touched)
        after3b = next(t for t in load_db() if t.numero == numeros["race_manual_first"])
        check("Scenario 3b -> started_at reste celui du clic manuel (pas ecrase par le watchdog)",
              data3b["started_at"], after3b.started_at)

    finally:
        restore_file(DB_FILE, db_snapshot)
        kc_require_password_reset(admin_token, user_id)
        print(f"[CLEANUP] classifications_db.json restaure, mot de passe de test invalide pour '{args.agent_id}'.")

    print()
    print("=" * 70)
    if FAILURES:
        print(f"RESULTAT : {len(FAILURES)} echec(s) sur les scenarios : {FAILURES}")
        sys.exit(1)
    else:
        print("RESULTAT : tous les scenarios sont valides.")
        sys.exit(0)


if __name__ == "__main__":
    main()
