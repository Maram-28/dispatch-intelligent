"""
Script de test autonome pour src/auth.py — vérifie que users_transaction() (verrou
tenu pendant toute la durée du read-modify-write) empêche bien les mises à jour
perdues sur users.json, même pattern que tests/test_profiles_store.py.
Lancer avec : python tests/test_auth_users_store.py

Utilise un fichier temporaire isolé (jamais les vraies données) : redirige
auth.USERS_FILE avant de lancer les threads, le restaure à la fin.
"""

import shutil
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import auth

FAILURES = []


def check(label, expected, actual):
    ok = expected == actual
    status = "OK  " if ok else "FAIL"
    print(f"[{status}] {label}")
    print(f"        attendu : {expected}")
    print(f"        obtenu  : {actual}")
    if not ok:
        FAILURES.append(label)


print("=" * 70)
print("Scenario : N mises a jour concurrentes du meme utilisateur via users_transaction()")
print("=" * 70)

tmp_dir = Path(tempfile.mkdtemp(prefix="auth_users_store_test_"))
original_users_file = auth.USERS_FILE
auth.USERS_FILE = tmp_dir / "users.json"

try:
    auth._save_users([{"id": "test_user", "nom": "Test User", "email": "test@example.com",
                        "role": "agent", "hashed_password": None, "counter": 0}])

    N = 20

    def worker():
        with auth.users_transaction() as users:
            for u in users:
                if u["id"] == "test_user":
                    u["counter"] += 1
                    break

    threads = [threading.Thread(target=worker) for _ in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final_users = auth._load_users()
    final_counter = next(u["counter"] for u in final_users if u["id"] == "test_user")
    check(f"{N} mises a jour concurrentes -> counter == {N} (aucune perdue)", N, final_counter)

    # Sanity : le fichier reste un JSON valide et lisible (pas de corruption partielle).
    check("fichier reste un JSON valide avec 1 utilisateur", 1, len(final_users))

finally:
    auth.USERS_FILE = original_users_file
    shutil.rmtree(tmp_dir, ignore_errors=True)

print()
print("=" * 70)
if FAILURES:
    print(f"RESULTAT : {len(FAILURES)} echec(s) sur les scenarios : {FAILURES}")
    sys.exit(1)
else:
    print("RESULTAT : tous les scenarios sont valides.")
    sys.exit(0)
