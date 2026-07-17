"""
Módulo B — Motor de Trading (bucle principal).

Un `TradingEngine` por usuario, ejecutado como tarea asyncio en el propio
proceso de FastAPI. Cada ciclo (POLL_INTERVAL segundos):

1. Relee la configuración de riesgo desde la BD (editable en caliente).
2. Supervisa posiciones abiertas: aplica break-even / trailing stop y
   detecta cierres (SL, TP o manual) sincronizando broker ↔ BD.
3. Para cada activo habilitado: descarga velas, evalúa la estrategia
   SOLO cuando cierra una vela nueva, y abre órdenes con lote dinámico.
4. Publica eventos en el `event_bus` (WebSocket del dashboard, Telegram).

Los conectores de broker son síncronos; todas sus llamadas se ejecutan
con `asyncio.to_thread` para no bloquear el event-loop.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import select

from app.brokers.base import BrokerConnector, OpenPosition
from app.core.events import event_bus
from app.db.database import SessionLocal
from app.db.models import (
    Asset,
    BotConfig,
    Trade,
    TradeDirection,
    TradeStatus,
)
from app.engine import risk_manager as rm
from app.strategies import get_strategy
from app.strategies.base_strategy import SignalType

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5.0
HISTORY_BARS = 300  # velas descargadas por ciclo (holgura sobre min_bars)

_TIMEFRAME_MINUTES = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440,
}


class TradingEngine:
    """Motor de trading de un usuario, conectado a un broker concreto."""

    def __init__(self, user_id: int, connector: BrokerConnector) -> None:
        self.user_id = user_id
        self.connector = connector
        self._task: asyncio.Task | None = None
        self._running = False
        # Última vela evaluada por símbolo → cada vela genera 1 sola evaluación.
        self._last_candle: dict[str, pd.Timestamp] = {}

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------
    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        await self._log("INFO", f"Motor de trading iniciado (usuario {self.user_id})")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await asyncio.to_thread(self.connector.disconnect)
        await self._log("INFO", "Motor de trading detenido")

    async def _loop(self) -> None:
        """Bucle principal: un ciclo cada POLL_INTERVAL_SECONDS, a prueba de errores."""
        while self._running:
            try:
                await self.run_cycle()
            except Exception as exc:  # noqa: BLE001 — el motor nunca debe morir
                logger.exception("Error en ciclo del motor")
                await self._log("ERROR", f"Ciclo falló: {exc}")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    # ------------------------------------------------------------------
    # Ciclo de trabajo (público para poder testearlo paso a paso)
    # ------------------------------------------------------------------
    async def run_cycle(self) -> None:
        with SessionLocal() as db:
            config = db.scalar(
                select(BotConfig).where(BotConfig.user_id == self.user_id)
            )
            if config is None or not config.bot_enabled:
                return

            await self._manage_open_positions(db, config)
            await self._publish_account_snapshot()

            open_count = self._count_open_trades(db)
            assets = db.scalars(
                select(Asset).where(
                    Asset.user_id == self.user_id, Asset.enabled.is_(True)
                )
            ).all()

            for asset in assets:
                if open_count >= config.max_open_trades:
                    break
                if await self._evaluate_asset(db, config, asset):
                    open_count += 1

    # ------------------------------------------------------------------
    # 1) Supervisión de posiciones abiertas
    # ------------------------------------------------------------------
    async def _manage_open_positions(self, db, config: BotConfig) -> None:
        broker_positions: dict[str, OpenPosition] = {
            p.ticket: p
            for p in await asyncio.to_thread(self.connector.get_open_positions)
        }

        open_trades = db.scalars(
            select(Trade).where(
                Trade.user_id == self.user_id, Trade.status == TradeStatus.OPEN
            )
        ).all()

        for trade in open_trades:
            if trade.broker_ticket in broker_positions:
                await self._adjust_stops(db, config, trade,
                                         broker_positions[trade.broker_ticket])
            else:
                await self._register_close(db, trade)
        db.commit()

    async def _adjust_stops(
        self, db, config: BotConfig, trade: Trade, position: OpenPosition
    ) -> None:
        """Aplica break-even y trailing stop sobre una posición viva."""
        pip_size = self._pip_size_for(db, trade.symbol)
        tick = await asyncio.to_thread(self.connector.get_price, trade.symbol)
        # Precio de cierre relevante: bid para BUY, ask para SELL.
        current = tick.bid if trade.direction == TradeDirection.BUY else tick.ask

        new_sl: float | None = None
        reason = ""

        # Break-even: una sola vez por operación.
        if config.break_even_enabled and not trade.break_even_applied:
            new_sl = rm.compute_break_even_sl(
                trade.direction.value, trade.entry_price, current,
                pip_size, config.break_even_trigger_pips,
            )
            if new_sl is not None:
                reason = "break_even"

        # Trailing: solo si no acaba de aplicarse el break-even.
        if new_sl is None and config.trailing_stop_enabled:
            gained = rm.profit_pips(
                trade.direction.value, trade.entry_price, current, pip_size
            )
            if gained >= config.trailing_stop_pips:
                new_sl = rm.compute_trailing_sl(
                    trade.direction.value, current,
                    trade.stop_loss, pip_size, config.trailing_stop_pips,
                )
                if new_sl is not None:
                    reason = "trailing_stop"

        if new_sl is None:
            return

        result = await asyncio.to_thread(
            self.connector.modify_position, trade.broker_ticket, new_sl, None
        )
        if not result.success:
            await self._log("WARNING",
                            f"No se pudo mover SL de {trade.symbol}: {result.message}")
            return

        trade.stop_loss = new_sl
        if reason == "break_even":
            trade.break_even_applied = True
        db.flush()

        await self._log(
            "INFO",
            f"{'Break-even' if reason == 'break_even' else 'Trailing'} aplicado "
            f"en {trade.symbol}: SL → {new_sl}",
        )
        await event_bus.publish(
            "trade_updated",
            {
                "user_id": self.user_id,
                "trade_id": trade.id,
                "symbol": trade.symbol,
                "stop_loss": new_sl,
                "reason": reason,
                "break_even_applied": trade.break_even_applied,
            },
        )

    async def _register_close(self, db, trade: Trade) -> None:
        """La posición ya no existe en el broker: registra el cierre en BD."""
        pip_size = self._pip_size_for(db, trade.symbol)

        info = await asyncio.to_thread(
            self.connector.get_closed_trade_info, trade.broker_ticket
        )
        if info is not None and info.exit_price is not None:
            exit_price, profit = info.exit_price, info.profit
        else:
            # Estimación con el último precio si el broker no da histórico.
            tick = await asyncio.to_thread(self.connector.get_price, trade.symbol)
            exit_price = (
                tick.bid if trade.direction == TradeDirection.BUY else tick.ask
            )
            profit = None

        pips = rm.profit_pips(
            trade.direction.value, trade.entry_price, exit_price, pip_size
        )
        if profit is None:
            pip_value = rm.pip_value_per_lot(trade.symbol, pip_size, exit_price)
            profit = round(pips * pip_value * trade.lot_size, 2)

        trade.status = rm.classify_close(
            trade.direction.value, exit_price,
            trade.stop_loss, trade.take_profit, pip_size,
        )
        trade.exit_price = exit_price
        trade.profit = profit
        trade.profit_pips = round(pips, 1)
        trade.closed_at = datetime.now(timezone.utc)
        db.flush()

        await self._log(
            "INFO",
            f"Operación cerrada {trade.symbol} {trade.direction.value} "
            f"[{trade.status.value}] P/L: {profit:+.2f} ({pips:+.1f} pips)",
        )
        await event_bus.publish(
            "trade_closed",
            {
                "user_id": self.user_id,
                "trade_id": trade.id,
                "symbol": trade.symbol,
                "direction": trade.direction.value,
                "status": trade.status.value,
                "exit_price": exit_price,
                "profit": profit,
                "profit_pips": trade.profit_pips,
            },
        )

    # ------------------------------------------------------------------
    # 2) Evaluación de estrategia y apertura de órdenes
    # ------------------------------------------------------------------
    async def _evaluate_asset(self, db, config: BotConfig, asset: Asset) -> bool:
        """Evalúa un activo; devuelve True si abrió una operación."""
        strategy = get_strategy(config.strategy_name)
        tf_minutes = _TIMEFRAME_MINUTES[asset.timeframe]
        date_to = datetime.now(timezone.utc)
        date_from = date_to - timedelta(minutes=tf_minutes * HISTORY_BARS)

        try:
            df = await asyncio.to_thread(
                self.connector.get_historical_data,
                asset.symbol, asset.timeframe, date_from, date_to,
            )
        except Exception as exc:  # noqa: BLE001
            await self._log("WARNING", f"Sin velas de {asset.symbol}: {exc}")
            return False

        if len(df) < strategy.min_bars:
            return False

        # Evaluar solo cuando aparece una vela cerrada nueva.
        last_candle = df.index[-1]
        if self._last_candle.get(asset.symbol) == last_candle:
            return False
        self._last_candle[asset.symbol] = last_candle

        signal = strategy.calculate_signal(df, asset.symbol)
        await event_bus.publish(
            "signal",
            {"symbol": asset.symbol, "signal": signal.type.value,
             "reason": signal.reason, "metadata": signal.metadata},
        )
        if signal.type == SignalType.HOLD:
            return False

        # Máximo una posición abierta por símbolo.
        already_open = db.scalar(
            select(Trade).where(
                Trade.user_id == self.user_id,
                Trade.symbol == asset.symbol,
                Trade.status == TradeStatus.OPEN,
            )
        )
        if already_open:
            return False

        return await self._open_trade(db, config, asset, signal.type.value)

    async def _open_trade(
        self, db, config: BotConfig, asset: Asset, direction: str
    ) -> bool:
        """Calcula lote/SL/TP, envía la orden y persiste la operación."""
        tick = await asyncio.to_thread(self.connector.get_price, asset.symbol)
        entry_ref = tick.ask if direction == "BUY" else tick.bid

        account = await asyncio.to_thread(self.connector.get_account_info)
        pip_value = rm.pip_value_per_lot(
            asset.symbol, asset.pip_size, entry_ref, account.currency
        )
        lot = rm.calc_lot_size(
            account.balance, config.risk_per_trade_pct,
            config.stop_loss_pips, pip_value,
        )
        sl, tp = rm.calc_sl_tp(
            direction, entry_ref,
            config.stop_loss_pips, config.take_profit_pips, asset.pip_size,
        )

        result = await asyncio.to_thread(
            self.connector.open_order, asset.symbol, direction, lot, sl, tp
        )
        if not result.success:
            await self._log("ERROR",
                            f"Orden {direction} {asset.symbol} rechazada: {result.message}")
            return False

        trade = Trade(
            user_id=self.user_id,
            broker_ticket=result.ticket,
            symbol=asset.symbol,
            direction=TradeDirection(direction),
            lot_size=lot,
            entry_price=result.executed_price or entry_ref,
            stop_loss=sl,
            take_profit=tp,
            strategy_name=config.strategy_name,
        )
        db.add(trade)
        db.commit()
        db.refresh(trade)

        await self._log(
            "INFO",
            f"Operación abierta {direction} {asset.symbol} {lot} lotes "
            f"@ {trade.entry_price} | SL {sl} | TP {tp}",
        )
        await event_bus.publish(
            "trade_opened",
            {
                "user_id": self.user_id,
                "trade_id": trade.id,
                "symbol": asset.symbol,
                "direction": direction,
                "lot_size": lot,
                "entry_price": trade.entry_price,
                "stop_loss": sl,
                "take_profit": tp,
                "strategy": config.strategy_name,
            },
        )
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _count_open_trades(self, db) -> int:
        return len(
            db.scalars(
                select(Trade.id).where(
                    Trade.user_id == self.user_id,
                    Trade.status == TradeStatus.OPEN,
                )
            ).all()
        )

    def _pip_size_for(self, db, symbol: str) -> float:
        asset = db.scalar(
            select(Asset).where(
                Asset.user_id == self.user_id, Asset.symbol == symbol
            )
        )
        if asset is not None:
            return asset.pip_size
        return 0.01 if "JPY" in symbol else 0.0001

    async def _publish_account_snapshot(self) -> None:
        try:
            info = await asyncio.to_thread(self.connector.get_account_info)
        except Exception:  # noqa: BLE001 — snapshot es best-effort
            return
        await event_bus.publish(
            "account",
            {
                "balance": info.balance,
                "equity": info.equity,
                "margin_free": info.margin_free,
                "currency": info.currency,
            },
        )

    async def _log(self, level: str, message: str) -> None:
        """Log a consola/buffer + evento para la consola en vivo del dashboard."""
        logger.log(logging.getLevelName(level), message)
        await event_bus.publish("log", {"level": level, "message": message})


# ---------------------------------------------------------------------------
# Registro de motores activos (uno por usuario)
# ---------------------------------------------------------------------------
_ENGINES: dict[int, TradingEngine] = {}


def get_engine(user_id: int) -> TradingEngine | None:
    return _ENGINES.get(user_id)


async def start_engine(user_id: int, connector: BrokerConnector) -> TradingEngine:
    """Crea (o reutiliza) y arranca el motor del usuario."""
    existing = _ENGINES.get(user_id)
    if existing is not None and existing.is_running:
        return existing
    engine = TradingEngine(user_id, connector)
    _ENGINES[user_id] = engine
    await engine.start()
    return engine


async def stop_engine(user_id: int) -> bool:
    """Detiene y elimina el motor del usuario. False si no había motor."""
    engine = _ENGINES.pop(user_id, None)
    if engine is None:
        return False
    await engine.stop()
    return True
