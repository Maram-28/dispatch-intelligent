"""
Store persisté des profils membres (data/processed/member_profiles.json) et de leur
disponibilité (data/processed/availability.json).

Garanties (même pattern que src/notifications/store.py) :
  - Écriture atomique : fichier .tmp puis os.replace() — pas de JSON corrompu en cas de crash.
  - Protection concurrente : threading.Lock par fichier, tenu pendant toute la durée d'une
    transaction read-modify-write (voir profiles_transaction()/availability_transaction())
    — un load() et un save() séparés ne suffiraient pas à empêcher un incrément perdu entre
    deux requêtes HTTP concurrentes (FastAPI exécute les endpoints synchrones dans un
    threadpool, donc plusieurs threads OS réels même en Uvicorn "mono-worker").
  - Point d'entrée UNIQUE pour lire/écrire ces deux fichiers : aucun autre module ne doit
    faire open(PROFILES_FILE, "w")/open(AVAILABILITY_FILE, "w") directement.

Portée assumée : threading.Lock protège les threads concurrents à l'intérieur de CE
process (le cas visé par l'audit : requêtes HTTP simultanées). Ne protège pas contre une
exécution simultanée de la CLI set_availability.py dans un process séparé pendant que le
serveur tourne — nécessiterait un verrou inter-process, hors scope.
"""

import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List

PROFILES_FILE     = Path("data/processed/member_profiles.json")
AVAILABILITY_FILE = Path("data/processed/availability.json")

_PROFILES_LOCK     = threading.Lock()
_AVAILABILITY_LOCK = threading.Lock()


def _atomic_write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_profiles() -> List[Dict]:
    """Lecture seule, verrouillée. Lève FileNotFoundError si les profils n'ont pas
    encore été bootstrappés (même message que le comportement historique)."""
    with _PROFILES_LOCK:
        if not PROFILES_FILE.exists():
            raise FileNotFoundError("Profils non initialisés. Lancez run_bootstrap() d'abord.")
        with open(PROFILES_FILE, encoding="utf-8") as f:
            return json.load(f)


def save_profiles(profiles: List[Dict]) -> None:
    """Écriture seule (remplacement complet), verrouillée + atomique. Pour les cas qui
    n'ont pas besoin de relire l'existant avant d'écrire (ex: run_bootstrap)."""
    with _PROFILES_LOCK:
        _atomic_write(PROFILES_FILE, profiles)


@contextmanager
def profiles_transaction():
    """Charge member_profiles.json, verrou tenu pour TOUTE la durée du bloc `with`,
    sauvegarde atomique automatique à la sortie normale du bloc. Si une exception est
    levée à l'intérieur du bloc, la sauvegarde n'a pas lieu (rollback implicite) —
    aucune écriture partielle/incohérente n'est possible.

    Usage :
        with profiles_transaction() as profiles:
            ...mute `profiles` (liste de dicts) en place...

    Lève FileNotFoundError si les profils n'existent pas encore.
    """
    with _PROFILES_LOCK:
        if not PROFILES_FILE.exists():
            raise FileNotFoundError("Profils non initialisés. Lancez run_bootstrap() d'abord.")
        with open(PROFILES_FILE, encoding="utf-8") as f:
            profiles = json.load(f)
        yield profiles
        _atomic_write(PROFILES_FILE, profiles)


def load_availability() -> Dict:
    """Lecture seule, verrouillée. {"members": []} si le fichier n'existe pas encore
    (état de premier lancement normal, pas une erreur)."""
    with _AVAILABILITY_LOCK:
        if not AVAILABILITY_FILE.exists():
            return {"members": []}
        with open(AVAILABILITY_FILE, encoding="utf-8") as f:
            return json.load(f)


def save_availability(data: Dict) -> None:
    with _AVAILABILITY_LOCK:
        _atomic_write(AVAILABILITY_FILE, data)


@contextmanager
def availability_transaction():
    """Même pattern que profiles_transaction(), pour availability.json.

    Usage :
        with availability_transaction() as data:
            ...mute data["members"] en place...
    """
    with _AVAILABILITY_LOCK:
        if AVAILABILITY_FILE.exists():
            with open(AVAILABILITY_FILE, encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {"members": []}
        yield data
        _atomic_write(AVAILABILITY_FILE, data)
