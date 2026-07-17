"""
ESTRATEGIA DE SCALPING — Reversión a la media con Bollinger + RSI rápido.
=========================================================================

Diseñada para temporalidades cortas (M1, M5, M15), donde el precio tiende
a oscilar alrededor de su media y los estirones suelen corregirse.

Lógica ("re-entrada en banda")
------------------------------
No compra "cuchillos cayendo": espera a que el precio se estire FUERA de
la Banda de Bollinger, el RSI rápido confirme el agotamiento, y la vela
siguiente CIERRE DE VUELTA dentro de la banda (primer signo de rebote).

    COMPRA cuando:
      1. La vela anterior cerró POR DEBAJO de la banda inferior
         (estirón bajista excesivo), y
      2. El RSI rápido en esa vela estaba en sobreventa (≤ rsi_oversold), y
      3. La vela actual cierra DE VUELTA por encima de la banda inferior
         (re-entrada = el rebote empezó), y
      4. [opcional] El cierre está por encima de la EMA de tendencia
         (solo rebotes a favor de la tendencia mayor).

    VENTA: espejo exacto con la banda superior y sobrecompra.

    HOLD en cualquier otro caso.

Igual que todas las estrategias del bot, la señal se evalúa una sola vez
por vela cerrada (transición penúltima → última), así que cada estirón
genera como máximo una operación.

Recomendaciones de riesgo para backtest en TF cortas
----------------------------------------------------
- SL 10–15 pips / TP 12–20 pips (los recorridos son pequeños).
- Break-even con disparo de 6–10 pips.
- El SPREAD es crítico en scalping: simule siempre con el spread real de
  su broker (≥1 pip en majors); una estrategia rentable a 0.5 pips puede
  ser ruinosa a 2 pips.
"""

from __future__ import annotations

import pandas as pd

from app.strategies.base_strategy import BaseStrategy, Signal, SignalType
from app.strategies.ma_rsi_crossover import ema, rsi


def bollinger_bands(
    series: pd.Series, period: int = 20, num_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bandas de Bollinger: (banda inferior, media móvil, banda superior)."""
    middle = series.rolling(period).mean()
    std = series.rolling(period).std(ddof=0)
    return middle - num_std * std, middle, middle + num_std * std


class ScalpingBbRsiStrategy(BaseStrategy):
    """Reversión a la media: re-entrada en Banda de Bollinger + RSI rápido."""

    name = "scalping_bb_rsi"
    description = (
        "Scalping de reversión a la media para M1–M15: entra cuando el precio "
        "se estira fuera de la Banda de Bollinger con RSI rápido en zona "
        "extrema y la vela siguiente cierra de vuelta dentro de la banda."
    )

    @classmethod
    def default_params(cls) -> dict:
        return {
            "bb_period": 20,          # periodo de la Banda de Bollinger
            "bb_std": 2.0,            # desviaciones estándar de la banda
            "rsi_period": 7,          # RSI rápido (7 reacciona mejor en TF cortas)
            "rsi_oversold": 30,       # umbral de sobreventa (confirma compras)
            "rsi_overbought": 70,     # umbral de sobrecompra (confirma ventas)
            # EMA de tendencia: solo operar rebotes a favor de ella.
            # 0 = filtro desactivado (más señales, más ruido).
            "ema_trend_period": 0,
        }

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params)
        p = self.params
        self.min_bars = max(
            int(p["bb_period"]) * 3,
            int(p["ema_trend_period"]) * 2,
            60,
        )

    def calculate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        self.validate_data(df)
        p = self.params
        close = df["close"]

        lower, middle, upper = bollinger_bands(
            close, int(p["bb_period"]), float(p["bb_std"])
        )
        rsi_series = rsi(close, int(p["rsi_period"]))

        # Vela anterior (el estirón) y vela actual (la re-entrada).
        prev_close, curr_close = float(close.iloc[-2]), float(close.iloc[-1])
        prev_lower, curr_lower = float(lower.iloc[-2]), float(lower.iloc[-1])
        prev_upper, curr_upper = float(upper.iloc[-2]), float(upper.iloc[-1])
        prev_rsi, curr_rsi = float(rsi_series.iloc[-2]), float(rsi_series.iloc[-1])

        # Filtro de tendencia opcional.
        trend_period = int(p["ema_trend_period"])
        trend_ema = float(ema(close, trend_period).iloc[-1]) if trend_period > 0 else None
        buy_trend_ok = trend_ema is None or curr_close >= trend_ema
        sell_trend_ok = trend_ema is None or curr_close <= trend_ema

        metadata = {
            "close": round(curr_close, 5),
            "bb_lower": round(curr_lower, 5),
            "bb_middle": round(float(middle.iloc[-1]), 5),
            "bb_upper": round(curr_upper, 5),
            "rsi": round(curr_rsi, 2),
            "ema_trend": round(trend_ema, 5) if trend_ema is not None else None,
        }

        # ── COMPRA: estirón bajo la banda inferior + re-entrada ──────────
        stretched_down = prev_close < prev_lower and prev_rsi <= p["rsi_oversold"]
        reentered_up = curr_close > curr_lower
        if stretched_down and reentered_up and buy_trend_ok:
            return Signal(
                type=SignalType.BUY,
                symbol=symbol,
                reason=(
                    f"Re-entrada alcista en BB({p['bb_period']},{p['bb_std']}) "
                    f"tras sobreventa (RSI {prev_rsi:.1f} ≤ {p['rsi_oversold']})"
                ),
                metadata=metadata,
            )

        # ── VENTA: estirón sobre la banda superior + re-entrada ──────────
        stretched_up = prev_close > prev_upper and prev_rsi >= p["rsi_overbought"]
        reentered_down = curr_close < curr_upper
        if stretched_up and reentered_down and sell_trend_ok:
            return Signal(
                type=SignalType.SELL,
                symbol=symbol,
                reason=(
                    f"Re-entrada bajista en BB({p['bb_period']},{p['bb_std']}) "
                    f"tras sobrecompra (RSI {prev_rsi:.1f} ≥ {p['rsi_overbought']})"
                ),
                metadata=metadata,
            )

        return Signal(
            type=SignalType.HOLD, symbol=symbol,
            reason="Sin estirón + re-entrada", metadata=metadata,
        )
