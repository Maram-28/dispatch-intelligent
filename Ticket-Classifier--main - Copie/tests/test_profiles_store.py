"""
Script de test autonome pour src/agents/profiles_store.py — vérifie que la protection
concurrente (verrou tenu pendant toute la durée du read-modify-write) empêche bien les
incréments perdus sur member_profiles.json.
Lancer avec : python tests/test_profiles_store.py

Utilise un fichier temporaire isolé (jamais les vraies données) : redirige
profiles_store.PROFILES_FILE avant de lancer les threads, le restaure à la fin.
"""

import shutil
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents import profiles_store
from src.agents.profiling_agent import run_update

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
print("Scenario : N incrementations concurrentes de charge_actuelle")
print("=" * 70)

tmp_dir = Path(tempfile.mkdtemp(prefix="profiles_store_test_"))
original_profiles_file = profiles_store.PROFILES_FILE
profiles_store.PROFILES_FILE = tmp_dir / "member_profiles.json"

try:
    profiles_store.save_profiles([{"id": "test_member", "charge_actuelle": 0}])

    N = 20

    def worker():
        run_update({"assignee_id": "test_member", "delta": 1})

    threads = [threading.Thread(target=worker) for _ in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final_profiles = profiles_store.load_profiles()
    final_charge = next(p["charge_actuelle"] for p in final_profiles if p["id"] == "test_member")
    check(f"{N} incrementations concurrentes -> charge_actuelle == {N} (aucune perdue)", N, final_charge)

    # Sanity : le fichier reste un JSON valide et lisible (pas de corruption partielle).
    check("fichier reste un JSON valide avec 1 profil", 1, len(final_profiles))

finally:
    profiles_store.PROFILES_FILE = original_profiles_file
    shutil.rmtree(tmp_dir, ignore_errors=True)

print()
print("=" * 70)
if FAILURES:
    print(f"RESULTAT : {len(FAILURES)} echec(s) sur les scenarios : {FAILURES}")
    sys.exit(1)
else:
    print("RESULTAT : tous les scenarios sont valides.")
    sys.exit(0)
