"""
Gestionnaire de connexions SSE (Server-Sent Events) en mémoire.

Hypothèse : mono-worker Uvicorn (cohérent avec JOBS et le Lock du store).
Chaque user peut avoir N onglets ouverts → N queues distinctes.

publish() est appelé depuis un thread FastAPI sync (ex: /classify) et doit
pousser dans des asyncio.Queue qui vivent dans la boucle principale → on
utilise loop.call_soon_threadsafe(), l'unique API thread-safe pour ça.
"""

import asyncio
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

_loop: asyncio.AbstractEventLoop | None = None


def _set_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


class SSEManager:
    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue]] = defaultdict(list)

    def subscribe(self, user_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues[user_id].append(q)
        logger.info(
            "[SSE] Client souscrit — user_id=%s (connexions actives : %d)",
            user_id, len(self._queues[user_id]),
        )
        return q

    def unsubscribe(self, user_id: str, q: asyncio.Queue) -> None:
        queues = self._queues.get(user_id, [])
        try:
            queues.remove(q)
        except ValueError:
            pass
        if not queues:
            self._queues.pop(user_id, None)
        logger.info(
            "[SSE] Client désouscrit — user_id=%s (connexions restantes : %d)",
            user_id, len(self._queues.get(user_id, [])),
        )

    def publish(self, user_id: str, event: dict) -> None:
        queues = self._queues.get(user_id, [])
        if not queues:
            return
        if _loop is None:
            logger.warning("[SSE] publish() appelé avant initialisation de la boucle asyncio — événement ignoré")
            return
        for q in list(queues):
            _loop.call_soon_threadsafe(q.put_nowait, event)
        logger.info(
            "[SSE] Événement publié — user_id=%s, type=%s, connexions=%d",
            user_id, event.get("type", "?"), len(queues),
        )


sse_manager = SSEManager()
