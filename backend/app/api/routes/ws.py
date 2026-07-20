"""
Canal WebSocket de datos en tiempo real (`/ws/live`).

El dashboard abre UNA conexión y recibe todos los eventos del bus:
señales, aperturas/cierres, break-even, snapshot de cuenta y logs.

Autenticación: los navegadores no permiten headers personalizados en el
handshake WebSocket, así que el JWT viaja como query param:
    ws://localhost:8000/ws/live?token=<jwt>
"""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.events import event_bus
from app.core.logger import live_log_buffer
from app.core.security import decode_access_token
from app.db.database import SessionLocal
from app.db.models import SystemLog

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Tiempo real"])


def _persisted_logs(user_id: int, limit: int = 100) -> list[dict]:
    """Últimos logs guardados en BD (sobreviven reinicios y cortes de luz)."""
    with SessionLocal() as db:
        rows = db.scalars(
            select(SystemLog)
            .where((SystemLog.user_id == user_id) | (SystemLog.user_id.is_(None)))
            .order_by(SystemLog.created_at.desc())
            .limit(limit)
        ).all()
    return [
        {"timestamp": r.created_at.isoformat(), "level": r.level, "message": r.message}
        for r in reversed(rows)
    ]


@router.websocket("/ws/live")
async def live_stream(websocket: WebSocket, token: str = "") -> None:
    """Flujo de eventos en vivo hacia el dashboard."""
    user_id = decode_access_token(token)
    if user_id is None:
        # 4401: código de aplicación para "no autorizado" en WebSocket.
        await websocket.close(code=4401, reason="Token inválido o expirado")
        return

    await websocket.accept()
    queue = event_bus.subscribe()
    logger.info("Cliente WebSocket conectado (usuario %s)", user_id)

    try:
        # Snapshot inicial de la consola: el buffer en memoria si tiene
        # historia; si el servidor acaba de reiniciar (p. ej. tras un corte
        # de luz), se repuebla desde system_logs en la base de datos.
        logs = list(live_log_buffer)
        if len(logs) < 10:
            logs = _persisted_logs(int(user_id)) or logs
        await websocket.send_json({"type": "snapshot", "payload": {"logs": logs}})
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe(queue)
        logger.info("Cliente WebSocket desconectado (usuario %s)", user_id)
