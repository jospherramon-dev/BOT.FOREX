"""
ESTRATEGIA POR DEFECTO — Cruce de Medias Móviles con filtro RSI.
================================================================

Sirve como PLANTILLA para futuras estrategias: copie este archivo, cambie
`name`, `description`, `default_params()` y la lógica de
`calculate_signal()`, y regístrela en STRATEGY_REGISTRY.

Lógica
------
Tendencia + momento, evitando comprar sobre-extendido:

    COMPRA  cuando:
      1. La EMA rápida cruza HACIA ARRIBA la EMA lenta en la última vela
         (cambio de tendencia alcista), y
      2. RSI > 50 (momento alcista confirmado), y
      3. RSI < rsi_overbought (no perseguir un mercado sobrecomprado).

    VENTA   cuando:
      1. La EMA rápida cruza HACIA ABAJO la EMA lenta, y
      2. RSI < 50 (momento bajista confirmado), y
      3. RSI > rsi_oversold (no vender un mercado ya sobrevendido).

    HOLD    en cualquier otro caso.

El cruce se evalúa SOLO en la transición entre la penúltima y la última
vela cerrada — así cada cruce genera exactamente una señal y no se
re-dispara mientras la tendencia continúa.
"""

from __future__ import annotations

import pandas as pd

from app.strategies.base_strategy import BaseStrategy, Signal, SignalType


# ---------------------------------------------------------------------------
# Indicadores (implementados con pandas puro: sin dependencias extra y
# 100% reproducibles en backtesting)
# ---------------------------------------------------------------------------
def ema(series: pd.Series, period: int) -> pd.Series:
    """Media Móvil Exponencial."""
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """RSI de Wilder (suavizado exponencial alpha=1/period)."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0.0, 1e-10)  # evita división por cero
    return 100 - (100 / (1 + rs))


# ---------------------------------------------------------------------------
# Estrategia
# ---------------------------------------------------------------------------
class MaRsiCrossoverStrategy(BaseStrategy):
    """Cruce EMA(rápida/lenta) confirmado por RSI."""

    name = "ma_rsi_crossover"
    description = (
        "Cruce de EMA rápida/lenta con confirmación de momento por RSI. "
        "Compra en cruce alcista con RSI>50; vende en cruce bajista con RSI<50."
    )

    @classmethod
    def default_params(cls) -> dict:
        return {
            "ema_fast": 9,          # periodo EMA rápida
            "ema_slow": 21,         # periodo EMA lenta
            "rsi_period": 14,       # periodo del RSI
            "rsi_overbought": 70,   # techo: no comprar por encima
            "rsi_oversold": 30,     # suelo: no vender por debajo
        }

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params)
        # Necesitamos historia suficiente para que la EMA lenta converja.
        self.min_bars = max(self.params["ema_slow"] * 3, 60)

    def calculate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        self.validate_data(df)
        p = self.params
        close = df["close"]

        ema_fast = ema(close, p["ema_fast"])
        ema_slow = ema(close, p["ema_slow"])
        rsi_now = float(rsi(close, p["rsi_period"]).iloc[-1])

        # Posición relativa de las EMAs en la última y penúltima vela:
        # el cruce existe solo si la relación cambió entre ambas.
        fast_above_now = ema_fast.iloc[-1] > ema_slow.iloc[-1]
        fast_above_prev = ema_fast.iloc[-2] > ema_slow.iloc[-2]
        crossed_up = fast_above_now and not fast_above_prev
        crossed_down = (not fast_above_now) and fast_above_prev

        metadata = {
            "ema_fast": round(float(ema_fast.iloc[-1]), 5),
            "ema_slow": round(float(ema_slow.iloc[-1]), 5),
            "rsi": round(rsi_now, 2),
            "close": round(float(close.iloc[-1]), 5),
        }

        if crossed_up and 50 < rsi_now < p["rsi_overbought"]:
            return Signal(
                type=SignalType.BUY,
                symbol=symbol,
                reason=(
                    f"Cruce alcista EMA{p['ema_fast']}/EMA{p['ema_slow']} "
                    f"con RSI {rsi_now:.1f} (>50, no sobrecomprado)"
                ),
                metadata=metadata,
            )

        if crossed_down and p["rsi_oversold"] < rsi_now < 50:
            return Signal(
                type=SignalType.SELL,
                symbol=symbol,
                reason=(
                    f"Cruce bajista EMA{p['ema_fast']}/EMA{p['ema_slow']} "
                    f"con RSI {rsi_now:.1f} (<50, no sobrevendido)"
                ),
                metadata=metadata,
            )

        return Signal(type=SignalType.HOLD, symbol=symbol,
                      reason="Sin cruce confirmado", metadata=metadata)
