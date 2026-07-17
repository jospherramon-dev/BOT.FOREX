"""
Bus de eventos en memoria (pub/sub) para datos en tiempo real.

El motor de trading PUBLICA eventos (ticks, aperturas, cierres, break-even,
balance, logs) y los consumidores se SUSCRIBEN:

- El WebSocket `/ws/live` reenvía cada evento al dashboard (Módulo E).
- El servicio de Telegram (Módulo D) filtrará los eventos de trading.

Los eventos son dicts JSON-serializables:
    {"type": "trade_opened", "ts": "...", "payload": {...}}
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone


class EventBus:
    """Pub/sub asíncrono sencillo basado en colas por suscriptor."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        """Registra un consumidor y devuelve su cola de eventos."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    async def publish(self, event_type: str, payload: dict) -> None:
        """
        Difunde un evento a todos los suscriptores. Si la cola de un
        consumidor lento está llena, el evento se descarta para él
        (nunca se bloquea al motor de trading).
        """
        event = {
            "type": event_type,
            "ts": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass


#: Instancia global compartida por motor, WebSocket y notificaciones.
event_bus = EventBus()
