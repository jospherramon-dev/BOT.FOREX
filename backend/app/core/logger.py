"""
Logging estructurado + buffer de eventos en vivo.

Además del logging estándar a consola, mantiene un buffer circular en
memoria (`live_log_buffer`) que el WebSocket del Dashboard (Módulo E)
consumirá para mostrar la "consola de eventos" en tiempo real.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone

from app.core.config import settings

# Buffer circular: conserva los últimos N eventos para nuevos clientes del WS.
LIVE_LOG_MAX_EVENTS = 500
live_log_buffer: deque[dict] = deque(maxlen=LIVE_LOG_MAX_EVENTS)


class LiveBufferHandler(logging.Handler):
    """Handler que replica cada log como dict JSON-serializable en el buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        live_log_buffer.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "module": record.name,
                "message": record.getMessage(),
            }
        )


def setup_logging() -> None:
    """Configura el logging global de la aplicación. Llamar una vez en main."""
    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL.upper())

    console = logging.StreamHandler()
    console.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root.handlers.clear()
    root.addHandler(console)
    root.addHandler(LiveBufferHandler())
