"""
Módulo D — Notificaciones Telegram.

- telegram_service.py : cliente de la Bot API, plantillas Markdown de
  alertas (apertura, break-even, trailing, cierre, estado del bot) y el
  `TelegramNotifier` global suscrito al event_bus.
"""

from app.notifications.telegram_service import notifier, send_message, test_connection

__all__ = ["notifier", "send_message", "test_connection"]
