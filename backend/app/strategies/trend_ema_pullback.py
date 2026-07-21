"""
ESTRATEGIA DE TENDENCIA — Triple EMA con entrada en retroceso (pullback).
=========================================================================

Enfoque OPUESTO a la reversión a la media: en lugar de comprar caídas,
opera A FAVOR del momentum — y solo cuando tres medias móviles confirman
que la tendencia es real. Pensada para M15 y M5 (la combinación 20/50/200
es la clásica del trend-following intradía; en M5 la EMA200 representa la
tendencia de ~16 horas, en M15 la de ~2 días).

Lógica
------
    COMPRA cuando se cumplen las tres a la vez:
      1. ALINEACIÓN ALCISTA: EMA rápida > EMA media > EMA lenta
         (las tres capas de la tendencia apuntan hacia arriba), y
      2. RETROCESO + REANUDACIÓN: la vela anterior cerró POR DEBAJO de la
         EMA rápida (un descanso dentro de la tendencia) y la vela actual
         cierra DE VUELTA por encima (la tendencia retoma) — así se entra
         en el "descuento" del retroceso, no persiguiendo el precio, y
      3. [opcional] RSI > 50: el momentum acompaña (rsi_period=0 lo apaga).

    VENTA: espejo exacto (alineación bajista, reanudación bajo la EMA
    rápida, RSI < 50).

    HOLD en cualquier otro caso — en mercados laterales las EMAs se
    entrelazan, la alineación desaparece y la estrategia se queda fuera
    (su defensa natural contra el rango, donde el trend-following pierde).

La señal se evalúa una sola vez por vela cerrada (transición penúltima →
última): cada retroceso genera como máximo una entrada.

Riesgo recomendado para backtest
--------------------------------
El trend-following gana dejando correr: TP amplio respecto al SL
(ej. SL 30 / TP 80-100) y, sobre todo, TRAILING STOP activado (15-25
pips) — es la salida natural de una estrategia de tendencia. Break-even
temprano (15-20) protege los retrocesos fallidos.
"""

from __future__ import annotations

import pandas as pd

from app.strategies.base_strategy import BaseStrategy, Signal, SignalType
from app.strategies.ma_rsi_crossover import ema, rsi


class TrendEmaPullbackStrategy(BaseStrategy):
    """Triple EMA alineada + entrada en la reanudación del retroceso."""

    name = "trend_ema_pullback"
    description = (
        "Seguimiento de tendencia para M5/M15: exige EMA 20>50>200 alineadas "
        "y entra cuando el precio retrocede a la EMA rápida y la reanuda, "
        "con confirmación opcional de RSI. En rango se queda fuera."
    )

    @classmethod
    def default_params(cls) -> dict:
        return {
            "ema_fast": 20,     # capa rápida: define el retroceso
            "ema_medium": 50,   # capa media: estructura de la tendencia
            "ema_slow": 200,    # capa lenta: la tendencia de fondo
            "rsi_period": 14,   # confirmación de momentum (0 = desactivada)
            # Separación mínima entre capas de EMA, en pips. En un mercado
            # plano las EMAs quedan casi pegadas y se "alinean" por ruido
            # microscópico; exigir una separación real evita operar el rango.
            "min_separation_pips": 3,
        }

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params)
        # La EMA lenta necesita historia para converger.
        self.min_bars = max(int(self.params["ema_slow"]) * 2, 60)

    def calculate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        self.validate_data(df)
        p = self.params
        close = df["close"]

        ema_fast = ema(close, int(p["ema_fast"]))
        ema_medium = ema(close, int(p["ema_medium"]))
        ema_slow = ema(close, int(p["ema_slow"]))

        prev_close, curr_close = float(close.iloc[-2]), float(close.iloc[-1])
        prev_fast = float(ema_fast.iloc[-2])
        curr_fast = float(ema_fast.iloc[-1])
        curr_medium = float(ema_medium.iloc[-1])
        curr_slow = float(ema_slow.iloc[-1])

        rsi_period = int(p["rsi_period"])
        curr_rsi = float(rsi(close, rsi_period).iloc[-1]) if rsi_period > 0 else None

        # Separación mínima entre EMAs (tendencia real, no ruido plano).
        pip_size = 0.01 if "JPY" in symbol.upper() else 0.0001
        min_sep = float(p["min_separation_pips"]) * pip_size

        metadata = {
            "close": round(curr_close, 5),
            "ema_fast": round(curr_fast, 5),
            "ema_medium": round(curr_medium, 5),
            "ema_slow": round(curr_slow, 5),
            "rsi": round(curr_rsi, 2) if curr_rsi is not None else None,
        }

        # ── COMPRA: tendencia alcista + reanudación del retroceso ────────
        aligned_up = (
            curr_fast - curr_medium >= min_sep
            and curr_medium - curr_slow >= min_sep
        )
        resumed_up = prev_close < prev_fast and curr_close > curr_fast
        rsi_up_ok = curr_rsi is None or curr_rsi > 50
        if aligned_up and resumed_up and rsi_up_ok:
            return Signal(
                type=SignalType.BUY,
                symbol=symbol,
                reason=(
                    f"Tendencia alcista (EMA {p['ema_fast']}>{p['ema_medium']}>"
                    f"{p['ema_slow']}) reanudada tras retroceso"
                ),
                metadata=metadata,
            )

        # ── VENTA: tendencia bajista + reanudación del retroceso ─────────
        aligned_down = (
            curr_medium - curr_fast >= min_sep
            and curr_slow - curr_medium >= min_sep
        )
        resumed_down = prev_close > prev_fast and curr_close < curr_fast
        rsi_down_ok = curr_rsi is None or curr_rsi < 50
        if aligned_down and resumed_down and rsi_down_ok:
            return Signal(
                type=SignalType.SELL,
                symbol=symbol,
                reason=(
                    f"Tendencia bajista (EMA {p['ema_fast']}<{p['ema_medium']}<"
                    f"{p['ema_slow']}) reanudada tras retroceso"
                ),
                metadata=metadata,
            )

        return Signal(
            type=SignalType.HOLD, symbol=symbol,
            reason="Sin alineación de tendencia + reanudación",
            metadata=metadata,
        )
