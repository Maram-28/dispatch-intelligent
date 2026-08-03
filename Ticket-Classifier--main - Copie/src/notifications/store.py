"""
Store persisté des notifications in-app (data/output/notifications.json).

Garanties :
  - Écriture atomique : fichier .tmp puis os.replace() — pas de JSON corrompu en cas de crash.
  - Protection concurrente : threading.Lock (valide pour un process Uvicorn mono-worker,
    cohérent avec JOBS et classifications_db).
  - Fenêtre glissante : MAX_NOTIFICATIONS entrées au total (cohérent avec la DB tickets).
  - Idempotence : une seule notification par (ticket_numero, user_id, type).
"""

import json
import os
import uuid
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

_STORE_FILE = Path("data/output/notifications.json")
_LOCK = threading.Lock()
MAX_NOTIFICATIONS = 1000


def _load() -> List[Dict]:
    if not _STORE_FILE.exists():
        return []
    try:
        with open(_STORE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save(notifications: List[Dict]) -> None:
    _STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STORE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(notifications, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _STORE_FILE)


def append_notification(
    user_id: str,
    ticket_numero: str,
    notif_type: str,
    message: str,
) -> Optional[Dict]:
    """
    Ajoute une notification au store.
    Idempotent : retourne None si une notification identique (ticket_numero + user_id + type)
    existe déjà — empêche les doubles notifications sur un même ticket.
    """
    with _LOCK:
        notifications = _load()
        for n in notifications:
            if (
                n["user_id"] == user_id
                and n["ticket_numero"] == ticket_numero
                and n["type"] == notif_type
            ):
                return None  # déjà notifiée, on n'écrit pas
        notif: Dict = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "ticket_numero": ticket_numero,
            "type": notif_type,
            "message": message,
            "lu": False,
            "created_at": datetime.utcnow().isoformat(),
        }
        notifications.insert(0, notif)
        notifications = notifications[:MAX_NOTIFICATIONS]
        _save(notifications)
        return notif


def get_for_user(user_id: str) -> List[Dict]:
    """Retourne toutes les notifications d'un utilisateur, du plus récent au plus ancien."""
    with _LOCK:
        all_notifs = _load()
    return [n for n in all_notifs if n["user_id"] == user_id]


def get_all() -> List[Dict]:
    """Retourne toutes les notifications, tous utilisateurs confondus (usage manager/admin)."""
    with _LOCK:
        return _load()


def get_unread_count(user_id: str) -> int:
    """Nombre de notifications non lues pour un utilisateur."""
    return sum(1 for n in get_for_user(user_id) if not n["lu"])


def mark_read(notif_id: str, user_id: str) -> bool:
    """
    Marque une notification comme lue.
    Vérifie que la notification appartient à user_id (protection ownership).
    Retourne True si succès, False si non trouvée ou appartient à un autre utilisateur.
    """
    with _LOCK:
        notifications = _load()
        for n in notifications:
            if n["id"] == notif_id:
                if n["user_id"] != user_id:
                    return False  # appartient à un autre utilisateur
                if not n["lu"]:
                    n["lu"] = True
                    _save(notifications)
                return True
    return False  # non trouvée


def mark_all_read(user_id: str) -> int:
    """
    Marque toutes les notifications non lues d'un utilisateur comme lues.
    Retourne le nombre de notifications modifiées.
    """
    with _LOCK:
        notifications = _load()
        count = 0
        for n in notifications:
            if n["user_id"] == user_id and not n["lu"]:
                n["lu"] = True
                count += 1
        if count > 0:
            _save(notifications)
        return count
