"""
Módulo D — Servicio de notificaciones por Telegram.

Tres piezas:

1. Cliente mínimo de la Bot API de Telegram (httpx asíncrono):
   `send_message()` y `test_connection()`.
2. Plantillas de alertas en Markdown para apertura, break-even y cierre
   de operaciones.
3. `TelegramNotifier`: tarea global suscrita al `event_bus` que filtra los
   eventos de trading, resuelve la configuración del usuario (token
   cifrado con Fernet + chat_id) y envía la alerta formateada.

El notificador arranca con la aplicación (lifespan de FastAPI); si el
usuario no tiene Telegram habilitado, los eventos simplemente se ignoran.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from sqlalchemy import select

from app.core.events import event_bus
from app.core.security import decrypt_secret
from app.db.database import SessionLocal
from app.db.models import BotConfig

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org"

# Etiquetas legibles para el motivo de cierre.
_CLOSE_REASONS = {
    "CLOSED_TP": "✅ Take Profit",
    "CLOSED_SL": "🛑 Stop Loss",
    "CLOSED_TRAILING": "🎯 Trailing Stop",
    "CLOSED_MANUAL": "✋ Cierre manual",
}


# ---------------------------------------------------------------------------
# 1. Cliente de la Bot API
# ---------------------------------------------------------------------------
async def _api_call(token: str, method: str, payload: dict) -> dict:
    """POST a la Bot API. Devuelve el JSON de respuesta (ok/description)."""
    url = f"{_API_BASE}/bot{token}/{method}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload)
        return resp.json()


async def send_message(token: str, chat_id: str, text: str) -> tuple[bool, str]:
    """
    Envía un mensaje Markdown. Devuelve (éxito, detalle).
    Nunca lanza: los fallos de notificación no deben afectar al trading.
    """
    try:
        data = await _api_call(
            token, "sendMessage",
            {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
        )
        if data.get("ok"):
            return True, "Mensaje enviado"
        return False, str(data.get("description", "Error desconocido de Telegram"))
    except httpx.HTTPError as exc:
        return False, f"Error de red: {exc}"


async def test_connection(token: str, chat_id: str) -> dict:
    """
    Botón "Probar Conexión" del dashboard: valida el token con getMe y
    envía un mensaje de prueba al chat indicado.
    """
    try:
        me = await _api_call(token, "getMe", {})
    except httpx.HTTPError as exc:
        return {"success": False, "message": f"Error de red: {exc}"}

    if not me.get("ok"):
        return {"success": False,
                "message": "Token inválido: Telegram rechazó getMe"}

    bot_username = me["result"].get("username", "desconocido")
    ok, detail = await send_message(
        token, chat_id,
        "🤖 *BOT.FOREX conectado*\n"
        "Este chat recibirá las alertas de trading.\n"
        "_Mensaje de prueba enviado desde el dashboard._",
    )
    if not ok:
        return {
            "success": False,
            "message": f"Token válido (@{bot_username}) pero falló el envío: {detail}",
        }
    return {
        "success": True,
        "message": f"Conexión exitosa con @{bot_username}; mensaje de prueba enviado",
        "bot_username": bot_username,
    }


# ---------------------------------------------------------------------------
# 2. Plantillas de alertas (Markdown)
# ---------------------------------------------------------------------------
def format_trade_opened(p: dict) -> str:
    emoji = "🟢" if p["direction"] == "BUY" else "🔴"
    return (
        f"{emoji} *OPERACIÓN ABIERTA*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"*Par:* `{p['symbol']}`\n"
        f"*Dirección:* {p['direction']}\n"
        f"*Lote:* `{p['lot_size']}`\n"
        f"*Entrada:* `{p['entry_price']}`\n"
        f"*Stop Loss:* `{p['stop_loss']}`\n"
        f"*Take Profit:* `{p['take_profit']}`\n"
        f"*Estrategia:* _{p.get('strategy', 'manual')}_"
    )


def format_break_even(p: dict) -> str:
    return (
        f"🛡️ *BREAK-EVEN APLICADO*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"*Par:* `{p['symbol']}`\n"
        f"*Nuevo SL:* `{p['stop_loss']}`\n"
        f"_La operación queda protegida en la entrada._"
    )


def format_trailing(p: dict) -> str:
    return (
        f"🎯 *TRAILING STOP*\n"
        f"*Par:* `{p['symbol']}` → SL movido a `{p['stop_loss']}`"
    )


def format_trade_closed(p: dict) -> str:
    profit = p.get("profit") or 0.0
    pips = p.get("profit_pips") or 0.0
    result_emoji = "✅" if profit >= 0 else "❌"
    reason = _CLOSE_REASONS.get(p["status"], p["status"])
    return (
        f"{result_emoji} *OPERACIÓN CERRADA*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"*Par:* `{p['symbol']}`\n"
        f"*Dirección:* {p['direction']}\n"
        f"*Motivo:* {reason}\n"
        f"*Salida:* `{p.get('exit_price', '-')}`\n"
        f"*Resultado:* `{profit:+.2f}` ({pips:+.1f} pips)"
    )


def format_bot_status(p: dict) -> str:
    return ("🤖 *Bot INICIADO* — monitoreando el mercado"
            if p.get("running") else "🤖 *Bot DETENIDO*")


#: Evento → función de formato. `trade_updated` solo notifica break-even
#: y trailing (los demás cambios de SL serían ruido).
_FORMATTERS = {
    "trade_opened": format_trade_opened,
    "trade_closed": format_trade_closed,
    "bot_status": format_bot_status,
}


def format_event(event: dict) -> str | None:
    """Convierte un evento del bus en texto Markdown, o None si no aplica."""
    payload = event.get("payload", {})
    if event["type"] == "trade_updated":
        if payload.get("reason") == "break_even":
            return format_break_even(payload)
        if payload.get("reason") == "trailing_stop":
            return format_trailing(payload)
        return None
    formatter = _FORMATTERS.get(event["type"])
    return formatter(payload) if formatter else None


# ---------------------------------------------------------------------------
# 3. Notificador suscrito al EventBus
# ---------------------------------------------------------------------------
class TelegramNotifier:
    """
    Consume eventos del bus y envía alertas al Telegram de cada usuario.
    Se identifica al destinatario por el `user_id` incluido en el payload.
    """

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        # Inyectable en tests para no llamar a la API real.
        self._sender = send_message

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())
            logger.info("Notificador de Telegram iniciado")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        queue = event_bus.subscribe()
        try:
            while True:
                event = await queue.get()
                try:
                    await self.handle_event(event)
                except Exception:  # noqa: BLE001 — nunca tumbar el consumidor
                    logger.exception("Error procesando notificación Telegram")
        finally:
            event_bus.unsubscribe(queue)

    async def handle_event(self, event: dict) -> None:
        """Procesa un evento: filtra, resuelve config del usuario y envía."""
        user_id = event.get("payload", {}).get("user_id")
        if user_id is None:
            return

        text = format_event(event)
        if text is None:
            return

        with SessionLocal() as db:
            config = db.scalar(
                select(BotConfig).where(BotConfig.user_id == user_id)
            )
        if (
            config is None
            or not config.telegram_enabled
            or not config.encrypted_telegram_token
            or not config.telegram_chat_id
        ):
            return

        try:
            token = decrypt_secret(config.encrypted_telegram_token)
        except ValueError as exc:
            logger.error("Token de Telegram indescifrable (usuario %s): %s",
                         user_id, exc)
            return

        ok, detail = await self._sender(token, config.telegram_chat_id, text)
        if not ok:
            logger.warning("Notificación Telegram falló (usuario %s): %s",
                           user_id, detail)


#: Instancia global gestionada por el lifespan de la aplicación.
notifier = TelegramNotifier()
