"""Tests del Módulo D: plantillas Markdown y notificador de Telegram."""

import asyncio

import pytest

from app.core.security import encrypt_secret
from app.db.database import SessionLocal, init_db
from app.db.models import BotConfig, User
from app.notifications.telegram_service import (
    TelegramNotifier,
    format_event,
    format_trade_closed,
    format_trade_opened,
)


# ---------------------------------------------------------------------------
# Plantillas
# ---------------------------------------------------------------------------
def test_plantilla_apertura():
    text = format_trade_opened(
        {
            "symbol": "EURUSD", "direction": "BUY", "lot_size": 0.33,
            "entry_price": 1.1000, "stop_loss": 1.0970,
            "take_profit": 1.1060, "strategy": "ma_rsi_crossover",
        }
    )
    assert "🟢" in text and "OPERACIÓN ABIERTA" in text
    assert "`EURUSD`" in text and "`1.097`" in text
    assert "ma_rsi_crossover" in text


def test_plantilla_cierre_con_perdida():
    text = format_trade_closed(
        {
            "symbol": "GBPUSD", "direction": "SELL", "status": "CLOSED_SL",
            "exit_price": 1.2530, "profit": -99.5, "profit_pips": -30.0,
        }
    )
    assert "❌" in text and "Stop Loss" in text
    assert "-99.50" in text and "-30.0 pips" in text


def test_format_event_filtra_correctamente():
    # trade_updated solo notifica break-even y trailing.
    be = {"type": "trade_updated",
          "payload": {"symbol": "EURUSD", "stop_loss": 1.1001,
                      "reason": "break_even"}}
    assert "BREAK-EVEN" in format_event(be)

    otro = {"type": "trade_updated",
            "payload": {"symbol": "EURUSD", "stop_loss": 1.1, "reason": "otro"}}
    assert format_event(otro) is None

    # Eventos sin formateador (ticks, logs) se ignoran.
    assert format_event({"type": "account", "payload": {}}) is None
    assert format_event({"type": "log", "payload": {}}) is None


# ---------------------------------------------------------------------------
# Notificador (flujo completo con emisor simulado)
# ---------------------------------------------------------------------------
@pytest.fixture()
def telegram_user():
    """Usuario con Telegram habilitado y token cifrado en BD."""
    init_db()
    with SessionLocal() as db:
        user = User(username="tg_test", email="tg@test.com", hashed_password="x")
        db.add(user)
        db.flush()
        db.add(BotConfig(
            user_id=user.id,
            telegram_enabled=True,
            encrypted_telegram_token=encrypt_secret("123456:ABC-fake-token"),
            telegram_chat_id="987654321",
        ))
        db.commit()
        yield user.id
        db.query(BotConfig).filter_by(user_id=user.id).delete()
        db.query(User).filter_by(id=user.id).delete()
        db.commit()


def _make_notifier_with_spy():
    notifier = TelegramNotifier()
    sent: list[tuple[str, str, str]] = []

    async def fake_sender(token: str, chat_id: str, text: str):
        sent.append((token, chat_id, text))
        return True, "ok"

    notifier._sender = fake_sender
    return notifier, sent


def test_notificador_envia_alerta_de_apertura(telegram_user):
    notifier, sent = _make_notifier_with_spy()
    event = {
        "type": "trade_opened",
        "payload": {
            "user_id": telegram_user, "symbol": "EURUSD", "direction": "BUY",
            "lot_size": 0.33, "entry_price": 1.1, "stop_loss": 1.097,
            "take_profit": 1.106, "strategy": "ma_rsi_crossover",
        },
    }
    asyncio.run(notifier.handle_event(event))

    assert len(sent) == 1
    token, chat_id, text = sent[0]
    assert token == "123456:ABC-fake-token"  # descifrado desde la BD
    assert chat_id == "987654321"
    assert "OPERACIÓN ABIERTA" in text


def test_notificador_ignora_eventos_sin_usuario(telegram_user):
    notifier, sent = _make_notifier_with_spy()
    asyncio.run(notifier.handle_event(
        {"type": "trade_opened", "payload": {"symbol": "EURUSD"}}
    ))
    assert sent == []


def test_notificador_respeta_flag_deshabilitado(telegram_user):
    with SessionLocal() as db:
        config = db.query(BotConfig).filter_by(user_id=telegram_user).one()
        config.telegram_enabled = False
        db.commit()

    notifier, sent = _make_notifier_with_spy()
    asyncio.run(notifier.handle_event(
        {
            "type": "trade_closed",
            "payload": {"user_id": telegram_user, "symbol": "EURUSD",
                        "direction": "BUY", "status": "CLOSED_TP",
                        "exit_price": 1.106, "profit": 198.0,
                        "profit_pips": 60.0},
        }
    ))
    assert sent == []
