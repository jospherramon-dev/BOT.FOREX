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

from app.core.events import event_bus
from app.core.logger import live_log_buffer
from app.core.security import decode_access_token

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Tiempo real"])


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
        # Snapshot inicial: últimos logs para poblar la consola al conectar.
        await websocket.send_json(
            {"type": "snapshot", "payload": {"logs": list(live_log_buffer)}}
        )
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe(queue)
        logger.info("Cliente WebSocket desconectado (usuario %s)", user_id)
