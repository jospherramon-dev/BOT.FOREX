"""
Test de integración del motor de trading (Módulo B) con un broker simulado.

Simula el ciclo de vida completo de una operación:
  ciclo 1: señal BUY → apertura con lote dinámico y SL/TP calculados.
  ciclo 2: precio +25 pips → break-even mueve el SL a la entrada.
  ciclo 3: la posición desaparece en el broker → cierre clasificado como TP.
"""

import asyncio
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from app.brokers.base import (
    AccountInfo,
    BrokerConnector,
    ClosedTradeInfo,
    OpenPosition,
    OrderResult,
    TickPrice,
)
from app.db.database import SessionLocal, init_db
from app.db.models import Asset, BotConfig, Trade, TradeStatus, User
from app.engine.trading_engine import TradingEngine
from app.strategies import STRATEGY_REGISTRY
from app.strategies.base_strategy import BaseStrategy, Signal, SignalType


# ---------------------------------------------------------------------------
# Dobles de prueba
# ---------------------------------------------------------------------------
class AlwaysBuyStrategy(BaseStrategy):
    """Estrategia de prueba: siempre emite BUY."""

    name = "test_always_buy"
    min_bars = 10

    def calculate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        return Signal(type=SignalType.BUY, symbol=symbol, reason="test")


STRATEGY_REGISTRY[AlwaysBuyStrategy.name] = AlwaysBuyStrategy


class FakeConnector(BrokerConnector):
    """Broker en memoria con precio controlable desde el test."""

    name = "FAKE"

    def __init__(self) -> None:
        self.price = 1.1000
        self.positions: list[OpenPosition] = []
        self.modify_calls: list[tuple] = []
        self.closed_info: ClosedTradeInfo | None = None
        self.connect_calls = 0
        self.fail_history = False  # simula pérdida de conexión (IPC caído)

    def connect(self) -> bool:
        self.connect_calls += 1
        return True

    def disconnect(self) -> None:
        pass

    def is_connected(self) -> bool:
        return True

    def get_account_info(self) -> AccountInfo:
        return AccountInfo(balance=10_000, equity=10_000,
                           margin_free=9_000, currency="USD", leverage=100)

    def get_price(self, symbol: str) -> TickPrice:
        return TickPrice(symbol=symbol, bid=self.price, ask=self.price,
                         time=datetime.now(timezone.utc))

    def get_historical_data(self, symbol, timeframe, date_from, date_to):
        if self.fail_history:
            raise ConnectionError("(-10004, 'No IPC connection')")
        closes = np.full(60, self.price)
        # Índice temporal FIJO: el motor deduplica por última vela, así que
        # los ciclos 2 y 3 no deben re-evaluar la estrategia.
        idx = pd.date_range("2025-01-01", periods=60, freq="15min")
        return pd.DataFrame(
            {"open": closes, "high": closes, "low": closes,
             "close": closes, "volume": np.full(60, 100)},
            index=idx,
        )

    def open_order(self, symbol, direction, lot_size, stop_loss=None,
                   take_profit=None, comment="") -> OrderResult:
        self.positions = [
            OpenPosition(ticket="T1", symbol=symbol, direction=direction,
                         lot_size=lot_size, entry_price=self.price,
                         stop_loss=stop_loss, take_profit=take_profit,
                         current_profit=0.0)
        ]
        return OrderResult(success=True, ticket="T1",
                           executed_price=self.price, message="ok")

    def modify_position(self, ticket, stop_loss=None, take_profit=None) -> OrderResult:
        self.modify_calls.append((ticket, stop_loss, take_profit))
        return OrderResult(success=True, ticket=ticket, message="ok")

    def close_position(self, ticket) -> OrderResult:
        self.positions = []
        return OrderResult(success=True, ticket=ticket,
                           executed_price=self.price, message="ok")

    def get_open_positions(self) -> list[OpenPosition]:
        return self.positions

    def get_closed_trade_info(self, ticket) -> ClosedTradeInfo | None:
        return self.closed_info


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def user_with_config():
    """Usuario de prueba con configuración de riesgo y EURUSD habilitado."""
    init_db()
    with SessionLocal() as db:
        user = User(username="engine_test", email="engine@test.com",
                    hashed_password="x")
        db.add(user)
        db.flush()
        db.add(BotConfig(
            user_id=user.id,
            strategy_name="test_always_buy",
            risk_per_trade_pct=1.0,
            stop_loss_pips=30,
            take_profit_pips=60,
            break_even_enabled=True,
            break_even_trigger_pips=20,
            bot_enabled=True,
        ))
        db.add(Asset(user_id=user.id, symbol="EURUSD",
                     timeframe="M15", pip_size=0.0001))
        db.commit()
        yield user.id
        # Limpieza para que el test sea repetible.
        db.query(Trade).filter_by(user_id=user.id).delete()
        db.query(Asset).filter_by(user_id=user.id).delete()
        db.query(BotConfig).filter_by(user_id=user.id).delete()
        db.query(User).filter_by(id=user.id).delete()
        db.commit()


def test_ciclo_completo_apertura_breakeven_cierre(user_with_config):
    user_id = user_with_config
    connector = FakeConnector()
    engine = TradingEngine(user_id, connector)

    # ── Ciclo 1: señal BUY → apertura ─────────────────────────────────
    asyncio.run(engine.run_cycle())

    with SessionLocal() as db:
        trade = db.query(Trade).filter_by(user_id=user_id).one()
        # Lote dinámico: $10.000 × 1% = $100 / (30 pips × $10) = 0.33
        assert trade.lot_size == 0.33
        assert trade.entry_price == pytest.approx(1.1000)
        assert trade.stop_loss == pytest.approx(1.0970)   # -30 pips
        assert trade.take_profit == pytest.approx(1.1060)  # +60 pips
        assert trade.status == TradeStatus.OPEN

    # ── Ciclo 2: +25 pips → break-even ────────────────────────────────
    connector.price = 1.1025
    asyncio.run(engine.run_cycle())

    assert connector.modify_calls, "El motor debió mover el SL"
    _, new_sl, _ = connector.modify_calls[0]
    assert new_sl == pytest.approx(1.1001)  # entrada + 1 pip de colchón

    with SessionLocal() as db:
        trade = db.query(Trade).filter_by(user_id=user_id).one()
        assert trade.break_even_applied is True
        assert trade.stop_loss == pytest.approx(1.1001)

    # ── Ciclo 3: la posición desaparece → cierre por TP ───────────────
    connector.positions = []
    connector.closed_info = ClosedTradeInfo(exit_price=1.1060, profit=198.0)
    asyncio.run(engine.run_cycle())

    with SessionLocal() as db:
        trade = db.query(Trade).filter_by(user_id=user_id).one()
        assert trade.status == TradeStatus.CLOSED_TP
        assert trade.exit_price == pytest.approx(1.1060)
        assert trade.profit == pytest.approx(198.0)
        assert trade.profit_pips == pytest.approx(60, abs=1.5)
        assert trade.closed_at is not None


def test_reconexion_automatica_tras_fallos_de_datos(user_with_config):
    """
    Si el broker deja de entregar velas (p. ej. MT5 pierde la conexión IPC
    al cerrarse el terminal), tras varios fallos consecutivos el motor debe
    intentar reconectar por sí solo — sin requerir un reinicio manual.
    """
    user_id = user_with_config
    connector = FakeConnector()
    connector.fail_history = True
    engine = TradingEngine(user_id, connector)

    # Tres ciclos con fallo de datos → debe dispararse una reconexión.
    for _ in range(3):
        asyncio.run(engine.run_cycle())
    assert connector.connect_calls >= 1

    # Al volver los datos, el contador se resetea y no reconecta de más.
    connector.fail_history = False
    reconnects = connector.connect_calls
    asyncio.run(engine.run_cycle())
    assert connector.connect_calls == reconnects
