"""
Test d'integration REEL du watchdog SLA (Lot 2, verification finale).

A la difference de tests/test_sla_watchdog.py (logique pure, sans I/O), ce script
verifie le chemin complet : insertion d'un vrai ticket, declenchement reel de
check_all_tickets(), envoi reel d'email, creation reelle de notif in-app, et push
SSE reel si un client est deja connecte.

ATTENTION - ce script :
  1) insere TEMPORAIREMENT un ticket de test dans classifications_db.json,
  2) modifie TEMPORAIREMENT l'email de l'agent de test dans users.json si --to est
     fourni (necessaire : le declenchement tourne dans le process du SERVEUR, pas
     dans celui de ce script, un monkeypatch local ne l'atteindrait pas),
  3) envoie un VRAI email (SMTP reellement contacte),
  4) declenche un VRAI push SSE si un agent/manager est deja connecte a
     /agent/notifications/stream au meme moment.
Les DEUX fichiers (classifications_db.json et users.json) sont restaures a l'identique
a la fin, meme en cas d'erreur (try/finally, snapshot/restore integral du contenu).

Prerequis :
  - Le backend doit deja tourner (python run_backend.py). Le declenchement se fait
    via POST /manager/sla-check-now pour que le push SSE atteigne un client deja
    connecte : un script Python separe ne pourrait pas toucher le sse_manager
    (singleton en memoire, propre au process serveur).
  - Identifiants d'un compte admin (role=="admin" dans users.json).

Usage :
  python tests/test_sla_watchdog_integration.py \\
      --admin-id mohamed_rabeh_boukahla --admin-password TicketApp2025! \\
      [--to ton_email@exemple.com] [--confirm]
"""

import argparse
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.ticket_crew import ClassificationResult, AssignmentInfo
from src.api import DB_FILE, save_to_db
from src.auth import _load_users, _save_users, USERS_FILE
from src.notifications import store as notif_store


def pick_agent_id() -> str:
    """Premier compte role=='agent' trouve dans users.json."""
    for u in _load_users():
        if u.get("role") == "agent":
            return u["id"]
    raise RuntimeError("Aucun compte role=='agent' trouve dans users.json")


def snapshot_file(path: Path):
    return path.read_text(encoding="utf-8") if path.exists() else None


def restore_file(path: Path, snapshot) -> None:
    if snapshot is None:
        if path.exists():
            path.unlink()
    else:
        path.write_text(snapshot, encoding="utf-8")


def override_agent_email(agent_id: str, email: str) -> None:
    """Redirige temporairement l'email de agent_id (persiste sur disque, relu par le
    serveur a chaque envoi — un simple monkeypatch en memoire ne suffirait pas car
    l'envoi reel s'execute dans le process serveur, pas dans celui de ce script)."""
    users = _load_users()
    for u in users:
        if u["id"] == agent_id:
            u["email"] = email
            break
    _save_users(users)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--admin-id", required=True, help="id d'un compte role=='admin' dans users.json")
    parser.add_argument("--admin-password", required=True)
    parser.add_argument("--to", default=None, help="email de test a utiliser a la place de celui de users.json")
    parser.add_argument("--confirm", action="store_true", help="ignore la confirmation interactive")
    args = parser.parse_args()

    print("=" * 70)
    print("ATTENTION : ce test va")
    print("  1) envoyer un VRAI email (SMTP reellement contacte),")
    print("  2) declencher un VRAI push SSE si un agent/manager est deja")
    print("     connecte a /agent/notifications/stream au meme moment.")
    if args.to:
        print(f"  3) modifier TEMPORAIREMENT l'email d'un agent reel dans users.json")
        print(f"     (redirige vers {args.to}, restaure integralement a la fin).")
    print("classifications_db.json (et users.json si --to) sont restaures a")
    print("l'identique a la fin, meme en cas d'erreur.")
    print("=" * 70)
    if not args.confirm:
        reply = input("Continuer ? [y/N] : ").strip().lower()
        if reply != "y":
            print("Annule.")
            sys.exit(0)

    db_snapshot = snapshot_file(DB_FILE)
    users_snapshot = snapshot_file(USERS_FILE)
    numero = f"TEST-SLA-INTEGRATION-{uuid.uuid4().hex[:8]}"
    exit_code = 0

    try:
        agent_id = pick_agent_id()
        if args.to:
            override_agent_email(agent_id, args.to)
            print(f"[TEST] Email de '{agent_id}' redirige vers {args.to} pour la duree du test.")

        now = datetime.now()
        ticket = ClassificationResult(
            numero=numero,
            categorie="Incident",
            sous_categorie="Application",
            service="O365-PowerBI",
            impact="2-Moyen",
            urgence="2-Moyen",
            priorite_calculee="1-Critique",
            confidence=0.9,
            reasoning="Ticket de test - integration watchdog SLA",
            titre="[TEST] Watchdog SLA - verification integration",
            status="in_progress",
            started_at=(now - timedelta(hours=9)).isoformat(),
            sla_deadline=(now - timedelta(hours=1)).isoformat(),  # deja depassee d'1h
            assigned_to=AssignmentInfo(
                membre_id=agent_id, nom=agent_id,
                score_assignation=0.9, justification="Assignation de test",
            ),
            sla_alert_40_sent=False,
            sla_alert_10_sent=False,
            sla_alert_breach_sent=False,
        )
        save_to_db(ticket)
        print(f"[TEST] Ticket {numero} insere (assigne a '{agent_id}', deadline depassee d'1h).")

        print("[TEST] Authentification admin...")
        login_resp = requests.post(
            f"{args.base_url}/login",
            json={"username": args.admin_id, "password": args.admin_password},
        )
        login_resp.raise_for_status()
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        print("[TEST] Declenchement de POST /manager/sla-check-now...")
        check_resp = requests.post(f"{args.base_url}/manager/sla-check-now", headers=headers)
        check_resp.raise_for_status()
        result = check_resp.json()
        print(f"[TEST] Reponse brute : {result}")

        matched = [r for r in result.get("triggered", []) if r["numero"] == numero]
        if not matched:
            print(f"[FAIL] Le ticket {numero} n'apparait pas dans les tickets ayant declenche une alerte.")
            exit_code = 1
        else:
            triggered_tiers = matched[0]["triggered"]
            print(f"[OK] Ticket {numero} -> paliers declenches : {triggered_tiers}")
            if set(triggered_tiers) != {"40", "10", "breach"}:
                print(f"[FAIL] Paliers attendus {{'40','10','breach'}}, obtenus {set(triggered_tiers)}")
                exit_code = 1

        notifs = [n for n in notif_store.get_for_user(agent_id) if n["ticket_numero"] == numero]
        print(f"[TEST] Notifications in-app trouvees pour '{agent_id}' / {numero} : {len(notifs)}")
        for n in notifs:
            print(f"        - {n['type']} : {n['message']}")
        if len(notifs) != 3:
            print(f"[FAIL] 3 notifications attendues (sla_40/sla_10/sla_breach), {len(notifs)} trouvees.")
            exit_code = 1

        dest = args.to or f"(email de '{agent_id}' dans users.json)"
        print()
        print("Verifications MANUELLES a faire maintenant :")
        print(f"  - Boite mail de {dest} : email(s) recus (3 attendus, un par palier) ?")
        print("  - Console du serveur (python run_backend.py) : lignes [EMAIL] et [SSE] ?")
        print("  - Si un navigateur est connecte (agent ou manager) : toast/son recu ?")
        print()
        if exit_code == 0:
            print("RESULTAT : verification automatique OK (paliers + notifs in-app). Confirme le reste manuellement.")
        else:
            print("RESULTAT : ECHEC d'une verification automatique (voir [FAIL] ci-dessus).")

    except Exception as exc:
        print(f"[ERREUR] Le test a echoue : {exc}")
        exit_code = 1

    finally:
        restore_file(DB_FILE, db_snapshot)
        restore_file(USERS_FILE, users_snapshot)
        print(f"[CLEANUP] classifications_db.json et users.json restaures a leur etat d'origine (ticket {numero} retire).")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
