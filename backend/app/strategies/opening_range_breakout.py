"""
ESTRATEGIA ESTADÍSTICA — Ruptura del Rango de Apertura (Opening Range Breakout).
==============================================================================

A diferencia de las estrategias de indicadores (que buscan un patrón
predictivo en el ruido), esta se ancla a un EVENTO REAL y recurrente: la
apertura de una sesión (Londres, Nueva York…). En esos horarios entra el
flujo institucional, la volatilidad se expande y el precio suele definir
dirección. La estrategia no adivina la dirección — mide el rango de los
primeros minutos y opera su RUPTURA, con riesgo definido por la estructura.

Idea "estadística": el HORARIO y el largo del rango, la temporalidad, el
umbral de ruptura y si conviene CONTINUAR o DESVANECER (fade) la ruptura son
todos PARÁMETROS. Se barren con el optimizador (validación out-of-sample) y
se deja que los DATOS elijan la combinación con borde real — no una regla
asumida. La misma lógica se prueba en M5/M15/M30/H1 y gana la que sobrevive
fuera de muestra.

Lógica (una entrada por sesión, en la primera ruptura dentro de la ventana)
---------------------------------------------------------------------------
 1. ANCLA: la vela cuya hora = `session_hour`:`session_minute` (hora del
    BROKER) marca el inicio del rango de apertura de hoy.
 2. RANGO: máximo y mínimo de las primeras `range_bars` velas desde el ancla.
 3. VENTANA DE ENTRADA: solo se puede entrar en las `entry_window_bars` velas
    siguientes al cierre del rango (si el precio no rompe a tiempo, ese día
    no se opera — se espera a la próxima sesión).
 4. RUPTURA: cuando una vela CIERRA más allá del rango (+ `breakout_buffer_pips`)
    por primera vez (transición): COMPRA si rompe arriba, VENTA si rompe abajo.
 5. `invert=1` DESVANECE la ruptura (fade): la ruptura alcista se opera como
    VENTA y viceversa — para medir estadísticamente si en tu dato conviene
    continuar o revertir (como el continuidad/reversión del IFC).

SL/TP ESTRUCTURAL (lo trae la propia señal en metadata, como la SMC)
--------------------------------------------------------------------
`risk = sl_range_mult × altura_del_rango`. SL a `risk` del precio (al lado
contrario de la operación); TP a `tp_rr × risk`. Simétrico en continuación y
en fade. El motor/backtester honran `sl_price`/`tp_price` tal cual.

NOTA sobre horario e instrumentos
---------------------------------
`session_hour` es HORA DEL SERVIDOR del bróker (XM suele ir en GMT+2/+3). El
solape Londres-NY (~08:00 ET) cae sobre ~15:00 en un servidor GMT+3. Como el
horario es un parámetro a barrer, no hay que acertarlo a mano: se prueban
varios y gana el que valida. `breakout_buffer_pips` asume convención forex
(0.0001; 0.01 en JPY) — en oro es despreciable frente al SL por rango, que
manda.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.strategies.base_strategy import BaseStrategy, Signal, SignalType


class OpeningRangeBreakoutStrategy(BaseStrategy):
    """Ruptura del rango de apertura de sesión, con SL/TP estructural."""

    name = "opening_range_breakout"
    description = (
        "Marca el rango de las primeras velas tras la apertura de una sesión "
        "(hora del broker) y opera su ruptura, con SL/TP por el tamaño del "
        "rango. Horario, largo del rango, umbral, R:R y continuar-vs-fade son "
        "parámetros para estudio estadístico con validación out-of-sample."
    )

    @classmethod
    def default_params(cls) -> dict:
        return {
            "session_hour": 15,        # hora del BROKER en que arranca el rango
            "session_minute": 0,       # debe caer en la rejilla de la temporalidad
            "range_bars": 4,           # nº de velas que forman el rango de apertura
            "entry_window_bars": 8,    # velas tras el rango en que puede dispararse
            "breakout_buffer_pips": 1, # margen más allá del rango para confirmar
            "sl_range_mult": 1.0,      # SL = mult × altura del rango
            "tp_rr": 1.5,              # TP = tp_rr × riesgo (R:R)
            "invert": 0,               # 1 = desvanecer la ruptura (fade) en vez de continuar
        }

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params)
        # La entrada solo ocurre dentro de la ventana tras la apertura, así
        # que el ancla de la sesión queda a pocas velas cuando hay entrada
        # posible. 40 velas (motor: ventana de 100) alcanzan de sobra el
        # ancla + rango + ventana en cualquier temporalidad intradía.
        self.min_bars = 40

    def calculate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        self.validate_data(df)
        p = self.params
        pip_size = 0.01 if "JPY" in symbol.upper() else 0.0001

        sh = int(p["session_hour"])
        sm = int(p["session_minute"])
        range_bars = max(1, int(p["range_bars"]))
        entry_window = max(1, int(p["entry_window_bars"]))
        buf = float(p["breakout_buffer_pips"]) * pip_size

        idx = df.index
        # Ancla: última vela del window cuya hora:minuto = apertura de sesión.
        try:
            hours = idx.hour.to_numpy()
            minutes = idx.minute.to_numpy()
        except AttributeError:
            return self._hold(symbol, "Índice sin tiempos (se requiere DatetimeIndex)")
        anchors = np.where((hours == sh) & (minutes == sm))[0]
        if len(anchors) == 0:
            return self._hold(symbol, "Sin apertura de sesión en la ventana")
        a = int(anchors[-1])                 # ancla más reciente
        cur = len(df) - 1
        range_end = a + range_bars - 1       # última vela del rango

        # ¿El rango aún se está formando o la vela actual es parte del rango?
        if range_end >= cur:
            return self._hold(symbol, "Rango de apertura aún formándose")
        # ¿Estamos dentro de la ventana de entrada tras el rango?
        if not (range_end < cur <= range_end + entry_window):
            return self._hold(symbol, "Fuera de la ventana de entrada de la sesión")

        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)

        range_high = float(highs[a: range_end + 1].max())
        range_low = float(lows[a: range_end + 1].min())
        range_size = range_high - range_low
        if range_size <= 0:
            return self._hold(symbol, "Rango de apertura degenerado")

        level_up = range_high + buf
        level_down = range_low - buf
        prev_close = float(closes[cur - 1])
        curr_close = float(closes[cur])

        # Ruptura en la TRANSICIÓN (la vela previa no había roto; esta sí).
        broke_up = prev_close <= level_up and curr_close > level_up
        broke_down = prev_close >= level_down and curr_close < level_down
        if not broke_up and not broke_down:
            return self._hold(symbol, "Sin ruptura del rango de apertura")

        raw_dir = "CALL" if broke_up else "PUT"   # dirección de la CONTINUACIÓN
        if int(p["invert"]):
            direction = "PUT" if raw_dir == "CALL" else "CALL"
        else:
            direction = raw_dir

        risk = float(p["sl_range_mult"]) * range_size
        tp_dist = float(p["tp_rr"]) * risk
        digits = 3 if pip_size == 0.01 else 5
        if direction == "CALL":
            sl_price = round(curr_close - risk, digits)
            tp_price = round(curr_close + tp_dist, digits)
            sig_type = SignalType.BUY
        else:
            sl_price = round(curr_close + risk, digits)
            tp_price = round(curr_close - tp_dist, digits)
            sig_type = SignalType.SELL

        modo = "fade" if int(p["invert"]) else "ruptura"
        reason = (
            f"ORB {modo} {'↑' if broke_up else '↓'} sesión {sh:02d}:{sm:02d} | "
            f"rango [{range_low:.5f}, {range_high:.5f}] ({range_size / pip_size:.0f} pips) "
            f"| {'BUY' if sig_type == SignalType.BUY else 'SELL'}"
        )
        metadata = {
            "session_hour": sh,
            "range_high": round(range_high, digits),
            "range_low": round(range_low, digits),
            "range_pips": round(range_size / pip_size, 1),
            "sl_price": sl_price,
            "tp_price": tp_price,
            "close": round(curr_close, digits),
        }
        return Signal(type=sig_type, symbol=symbol, reason=reason, metadata=metadata)

    def _hold(self, symbol: str, reason: str) -> Signal:
        return Signal(type=SignalType.HOLD, symbol=symbol, reason=reason)
