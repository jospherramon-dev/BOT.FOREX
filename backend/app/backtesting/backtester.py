"""
Módulo C — Simulador de estrategias vela a vela.

Reutiliza EXACTAMENTE el mismo código que el trading en vivo:
- las estrategias (`app/strategies`) reciben el mismo DataFrame OHLCV, y
- el gestor de riesgo (`app/engine/risk_manager`) calcula lote, SL/TP,
  break-even y trailing con las mismas funciones puras.

Modelo de ejecución (una posición simultánea, como el motor en vivo por símbolo):

1. La señal se evalúa SOLO sobre velas cerradas; la entrada se ejecuta al
   cierre de la vela de señal, sumando el spread configurado en las compras
   (aproximación bid/ask).
2. En cada vela posterior se comprueba si el High/Low tocó SL o TP.
   Si una misma vela toca ambos, se asume el peor caso (SL primero).
3. Tras sobrevivir la vela, se aplican break-even y trailing usando el
   precio de cierre — igual que el motor en vivo usa el precio actual.
4. La equity (balance + flotante) se registra en cada vela para la curva
   del dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from app.db.models import TradeStatus
from app.engine import risk_manager as rm
from app.strategies import get_strategy
from app.strategies.base_strategy import SignalType


# ---------------------------------------------------------------------------
# Parámetros y resultados
# ---------------------------------------------------------------------------
@dataclass
class BacktestParams:
    """Configuración completa de una simulación."""

    symbol: str
    timeframe: str = "M15"
    initial_balance: float = 10_000.0
    spread_pips: float = 1.0

    strategy_name: str = "ma_rsi_crossover"
    strategy_params: dict = field(default_factory=dict)

    # Gestión de riesgo (mismos campos que BotConfig).
    risk_per_trade_pct: float = 1.0
    stop_loss_pips: float = 30.0
    take_profit_pips: float = 60.0
    break_even_enabled: bool = True
    break_even_trigger_pips: float = 20.0
    trailing_stop_enabled: bool = False
    trailing_stop_pips: float = 15.0

    # Freno de drawdown (circuit breaker). 0 = desactivado. Si la equity cae
    # este % desde su MÁXIMO HISTÓRICO REAL, el bot deja de abrir operaciones
    # nuevas para no seguir sangrando en un régimen adverso, y no reanuda
    # hasta recuperarse por debajo del umbral tras `drawdown_cooldown_bars`
    # velas. El pico de referencia nunca se reinicia hacia abajo.
    max_drawdown_pct: float = 0.0
    drawdown_cooldown_bars: int = 480  # M15: ≈5 días de mercado

    @property
    def pip_size(self) -> float:
        return 0.01 if "JPY" in self.symbol.upper() else 0.0001


@dataclass
class SimulatedTrade:
    """Operación simulada (espejo del modelo Trade en vivo)."""

    direction: str
    entry_time: datetime
    entry_price: float
    lot_size: float
    stop_loss: float
    take_profit: float
    break_even_applied: bool = False
    exit_time: datetime | None = None
    exit_price: float | None = None
    profit: float = 0.0
    profit_pips: float = 0.0
    status: str = "OPEN"

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "entry_time": self.entry_time.isoformat(),
            "entry_price": self.entry_price,
            "lot_size": self.lot_size,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "break_even_applied": self.break_even_applied,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "exit_price": self.exit_price,
            "profit": round(self.profit, 2),
            "profit_pips": round(self.profit_pips, 1),
            "status": self.status,
        }


@dataclass
class BacktestResult:
    trades: list[SimulatedTrade]
    equity_curve: list[dict]     # [{"time": iso, "equity": x, "balance": y}, ...]
    final_balance: float


# ---------------------------------------------------------------------------
# Simulador
# ---------------------------------------------------------------------------
class Backtester:
    """Ejecuta una estrategia sobre datos históricos con gestión de riesgo real."""

    def __init__(self, df: pd.DataFrame, params: BacktestParams) -> None:
        self.df = df
        self.p = params
        self.strategy = get_strategy(params.strategy_name, params.strategy_params)
        # Ventana móvil para la estrategia: suficiente para sus indicadores
        # sin recalcular sobre todo el histórico en cada vela (O(n·w), no O(n²)).
        self._window = self.strategy.min_bars + 60

    # -- API pública -------------------------------------------------------
    def run(self) -> BacktestResult:
        p = self.p
        balance = p.initial_balance
        open_trade: SimulatedTrade | None = None
        trades: list[SimulatedTrade] = []
        equity_curve: list[dict] = []

        # Estado del freno de drawdown.
        peak_balance = balance
        paused_until_bar = -1  # índice de vela hasta el que el freno pausa

        for i in range(self.strategy.min_bars, len(self.df)):
            candle = self.df.iloc[i]
            when = self.df.index[i].to_pydatetime()

            # 1) Gestionar la posición abierta contra la vela actual.
            if open_trade is not None:
                closed = self._check_exit(open_trade, candle, when)
                if closed:
                    balance += open_trade.profit
                    trades.append(open_trade)
                    open_trade = None
                else:
                    self._apply_stop_management(open_trade, float(candle["close"]))

            # -- Freno de drawdown: ¿debe pausar la apertura de operaciones? --
            trading_allowed = True
            if p.max_drawdown_pct > 0:
                # Al terminar un enfriamiento, se reinicia la referencia de
                # pico al balance actual: así el bot puede REANUDAR y
                # participar de una recuperación en vez de quedar bloqueado
                # para siempre (un freno que mata el bot no sirve en vivo).
                if 0 < paused_until_bar <= i:
                    peak_balance = balance
                    paused_until_bar = 0
                peak_balance = max(peak_balance, balance)
                drawdown = (
                    (peak_balance - balance) / peak_balance if peak_balance > 0 else 0.0
                )
                if i < paused_until_bar:
                    trading_allowed = False  # en enfriamiento
                elif drawdown * 100 >= p.max_drawdown_pct:
                    paused_until_bar = i + p.drawdown_cooldown_bars
                    trading_allowed = False

            # 2) Buscar señal si no hay posición y el trading está permitido.
            if open_trade is None and trading_allowed:
                window = self.df.iloc[max(0, i - self._window): i + 1]
                signal = self.strategy.calculate_signal(window, p.symbol)
                if signal.type in (SignalType.BUY, SignalType.SELL):
                    open_trade = self._open_trade(
                        signal.type.value, float(candle["close"]), when, balance
                    )

            # 3) Registrar equity (balance + P/L flotante al cierre de vela).
            floating = (
                self._floating_profit(open_trade, float(candle["close"]))
                if open_trade else 0.0
            )
            equity_curve.append(
                {
                    "time": when.isoformat(),
                    "equity": round(balance + floating, 2),
                    "balance": round(balance, 2),
                }
            )

        # Cerrar la posición residual al último precio disponible.
        if open_trade is not None:
            last_close = float(self.df["close"].iloc[-1])
            self._close_trade(
                open_trade, last_close, self.df.index[-1].to_pydatetime(),
                TradeStatus.CLOSED_MANUAL.value,
            )
            balance += open_trade.profit
            trades.append(open_trade)
            if equity_curve:
                equity_curve[-1]["equity"] = round(balance, 2)
                equity_curve[-1]["balance"] = round(balance, 2)

        return BacktestResult(
            trades=trades, equity_curve=equity_curve, final_balance=round(balance, 2)
        )

    # -- Apertura ----------------------------------------------------------
    def _open_trade(
        self, direction: str, close_price: float, when: datetime, balance: float
    ) -> SimulatedTrade:
        p = self.p
        spread = rm.pips_to_price_delta(p.spread_pips, p.pip_size)
        # BUY entra al ask (cierre + spread); SELL entra al bid (cierre).
        entry = close_price + spread if direction == "BUY" else close_price

        pip_value = rm.pip_value_per_lot(p.symbol, p.pip_size, entry)
        lot = rm.calc_lot_size(
            balance, p.risk_per_trade_pct, p.stop_loss_pips, pip_value
        )
        sl, tp = rm.calc_sl_tp(
            direction, entry, p.stop_loss_pips, p.take_profit_pips, p.pip_size
        )
        return SimulatedTrade(
            direction=direction, entry_time=when, entry_price=entry,
            lot_size=lot, stop_loss=sl, take_profit=tp,
        )

    # -- Salidas intra-vela --------------------------------------------------
    def _check_exit(
        self, trade: SimulatedTrade, candle: pd.Series, when: datetime
    ) -> bool:
        """
        Comprueba si la vela tocó SL o TP. Peor caso: si toca ambos en la
        misma vela, se asume que el SL saltó primero.
        """
        high, low = float(candle["high"]), float(candle["low"])

        if trade.direction == "BUY":
            sl_hit = low <= trade.stop_loss
            tp_hit = high >= trade.take_profit
        else:
            sl_hit = high >= trade.stop_loss
            tp_hit = low <= trade.take_profit

        if sl_hit:
            self._close_trade(trade, trade.stop_loss, when,
                              TradeStatus.CLOSED_SL.value)
            return True
        if tp_hit:
            self._close_trade(trade, trade.take_profit, when,
                              TradeStatus.CLOSED_TP.value)
            return True
        return False

    def _close_trade(
        self, trade: SimulatedTrade, exit_price: float, when: datetime, status: str
    ) -> None:
        p = self.p
        pips = rm.profit_pips(
            trade.direction, trade.entry_price, exit_price, p.pip_size
        )
        pip_value = rm.pip_value_per_lot(p.symbol, p.pip_size, exit_price)
        trade.exit_time = when
        trade.exit_price = exit_price
        trade.profit_pips = pips
        trade.profit = pips * pip_value * trade.lot_size
        trade.status = status

    # -- Break-even / trailing (mismas funciones que el motor en vivo) -------
    def _apply_stop_management(self, trade: SimulatedTrade, close: float) -> None:
        p = self.p

        if p.break_even_enabled and not trade.break_even_applied:
            new_sl = rm.compute_break_even_sl(
                trade.direction, trade.entry_price, close,
                p.pip_size, p.break_even_trigger_pips,
            )
            if new_sl is not None:
                trade.stop_loss = new_sl
                trade.break_even_applied = True
                return

        if p.trailing_stop_enabled:
            gained = rm.profit_pips(
                trade.direction, trade.entry_price, close, p.pip_size
            )
            if gained >= p.trailing_stop_pips:
                new_sl = rm.compute_trailing_sl(
                    trade.direction, close, trade.stop_loss,
                    p.pip_size, p.trailing_stop_pips,
                )
                if new_sl is not None:
                    trade.stop_loss = new_sl

    def _floating_profit(self, trade: SimulatedTrade, close: float) -> float:
        p = self.p
        pips = rm.profit_pips(trade.direction, trade.entry_price, close, p.pip_size)
        return pips * rm.pip_value_per_lot(p.symbol, p.pip_size, close) * trade.lot_size
