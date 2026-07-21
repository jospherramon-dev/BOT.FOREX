"""
ESTRATEGIA DE SCALPING — Cruce EMA 9/21 con filtro de FUERZA ADX.
=================================================================

Adaptación del manual operativo "Scalping Forex · EMA + ADX" (Z.AI v1.0)
al motor de BOT.FOREX. La idea central —y lo que la distingue de nuestras
otras estrategias— es el ADX como **filtro de fuerza de tendencia**:

    Un cruce de EMAs dice HACIA DÓNDE va el precio, pero no CON CUÁNTA
    fuerza. En rango, las EMAs se cruzan decenas de veces en falso y cada
    cruce es una pérdida. El ADX mide la fuerza (no la dirección): al exigir
    ADX > umbral, se ignoran los cruces que ocurren en mercado lateral —
    exactamente el régimen que hundió nuestras estrategias anteriores.

Lógica de ENTRADA (5 condiciones simultáneas, en el cierre de la vela)
----------------------------------------------------------------------
    COMPRA:
      1. CRUCE ALCISTA: EMA rápida cruza por ENCIMA de la EMA lenta.
      2. TENDENCIA MAYOR: el cierre está por ENCIMA de la EMA de filtro.
      3. FUERZA: ADX(period) > umbral (mercado con tendencia real).
      4. DIRECCIÓN: +DI > -DI (la fuerza es alcista).
      5. CONFIRMACIÓN: la vela de cruce CIERRA por encima de la EMA lenta
         (cuerpo, no una simple mecha).

    VENTA: espejo exacto (cruce bajista, cierre < EMA filtro, ADX > umbral,
    -DI > +DI, cierre < EMA lenta).

    HOLD en cualquier otro caso.

El cruce se evalúa SOLO en la transición penúltima → última vela: cada
cruce genera como máximo una entrada (no se re-dispara con la tendencia).

Mejoras sobre el manual original
--------------------------------
El PDF sugiere ("preferiblemente") pero NO exige que el ADX esté subiendo,
ni pone una separación mínima entre +DI y -DI. Aquí ambas cosas son
PARÁMETROS OPCIONALES para poder medir en backtest si aportan edge:

  * `require_adx_rising` — exige ADX(actual) > ADX(anterior): descarta
    entradas donde la fuerza ya se está agotando.
  * `di_min_gap`        — separación mínima entre +DI y -DI (el checklist
    del manual recomienda > 3 puntos): evita señales en la "zona limbo"
    donde la dirección aún no está definida.

Filtro de sesión (el manual insiste en operar solo Londres / solape NY)
-----------------------------------------------------------------------
`session_start_hour` / `session_end_hour` restringen las entradas a una
franja horaria [inicio, fin). Están DESACTIVADOS por defecto (0..24) para
no romper backtests en silencio. IMPORTANTE: la hora se lee del índice
temporal de las velas, que viene en la ZONA HORARIA DEL BROKER (MT5 suele
usar GMT+2/GMT+3). El solape Londres-NY (08:00–12:00 hora de Nueva York)
equivale, en un servidor GMT+3, a ~15:00–19:00 hora del broker. Ajústelo a
su servidor observando a qué hora local se mueve más el EUR/USD.

Nota sobre la salida por ADX del manual
---------------------------------------
El manual añade una salida forzosa "si el ADX cae por debajo de 20 con
posición abierta". Eso es una señal de SALIDA, y nuestro motor/backtester
gestionan las salidas con SL/TP/break-even/trailing (no con la estrategia).
El trailing por EMA rápida del manual se aproxima activando el trailing
stop del gestor de riesgo. La entrada —que es donde el ADX aporta el
edge— sí queda implementada al 100%.
"""

from __future__ import annotations

import pandas as pd

from app.strategies.base_strategy import BaseStrategy, Signal, SignalType
from app.strategies.ma_rsi_crossover import ema


# ---------------------------------------------------------------------------
# Indicador ADX (Average Directional Index) de Welles Wilder.
# Devuelve (ADX, +DI, -DI). Usa el suavizado de Wilder (RMA = EWM con
# alpha=1/period), igual criterio que el RSI del proyecto y que el iADX de
# MetaTrader 5, para que backtest y vivo coincidan con el terminal.
# ---------------------------------------------------------------------------
def adx(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Calcula ADX, +DI y -DI (fuerza y dirección de la tendencia)."""
    prev_close = close.shift(1)

    # True Range: mayor de las tres medidas de rango de la vela.
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    # Movimiento direccional: solo cuenta el lado que se expande más.
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    alpha = 1.0 / period
    atr = tr.ewm(alpha=alpha, adjust=False).mean()
    atr_safe = atr.replace(0.0, 1e-10)

    plus_di = 100.0 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_safe
    minus_di = 100.0 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_safe

    di_sum = (plus_di + minus_di).replace(0.0, 1e-10)
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum
    adx_line = dx.ewm(alpha=alpha, adjust=False).mean()

    return adx_line, plus_di, minus_di


# ---------------------------------------------------------------------------
# Estrategia
# ---------------------------------------------------------------------------
class ScalpingEmaAdxStrategy(BaseStrategy):
    """Cruce EMA rápida/lenta filtrado por EMA mayor, fuerza ADX y dirección DI."""

    name = "scalping_ema_adx"
    description = (
        "Scalping M5/M1: cruce EMA 9/21 aceptado SOLO si ADX supera el umbral "
        "(tendencia con fuerza real), el precio respeta la EMA 50 y +DI/-DI "
        "confirman la dirección. El ADX filtra los cruces falsos del rango."
    )

    @classmethod
    def default_params(cls) -> dict:
        return {
            "ema_fast": 9,          # EMA rápida (señal de cruce)
            "ema_slow": 21,         # EMA lenta (señal de cruce)
            "ema_filter": 50,       # EMA de tendencia mayor (filtro de lado)
            "adx_period": 14,       # período del ADX / DI (estándar Wilder)
            "adx_threshold": 22.0,  # fuerza mínima para aceptar el cruce
            # --- Mejoras opcionales sobre el manual (0/False = como el PDF) ---
            "require_adx_rising": 0,  # 1 = exigir ADX subiendo respecto a la vela previa
            "di_min_gap": 0.0,        # separación mínima +DI/-DI (manual sugiere >3)
            # --- Filtro de sesión (hora del BROKER; 0..24 = desactivado) ------
            "session_start_hour": 0,
            "session_end_hour": 24,
        }

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params)
        # La EMA de filtro y el suavizado de Wilder del ADX necesitan historia
        # para converger antes de emitir señales fiables.
        self.min_bars = max(
            int(self.params["ema_filter"]) * 3,
            int(self.params["adx_period"]) * 5,
            100,
        )

    def calculate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        self.validate_data(df)
        p = self.params
        close = df["close"]

        ema_fast = ema(close, int(p["ema_fast"]))
        ema_slow = ema(close, int(p["ema_slow"]))
        ema_filter = ema(close, int(p["ema_filter"]))
        adx_line, plus_di, minus_di = adx(
            df["high"], df["low"], close, int(p["adx_period"])
        )

        curr_close = float(close.iloc[-1])
        curr_fast, prev_fast = float(ema_fast.iloc[-1]), float(ema_fast.iloc[-2])
        curr_slow, prev_slow = float(ema_slow.iloc[-1]), float(ema_slow.iloc[-2])
        curr_filter = float(ema_filter.iloc[-1])
        curr_adx, prev_adx = float(adx_line.iloc[-1]), float(adx_line.iloc[-2])
        curr_pdi = float(plus_di.iloc[-1])
        curr_mdi = float(minus_di.iloc[-1])

        # Cruce EMA rápida/lenta: existe solo si la relación cambió de vela.
        crossed_up = curr_fast > curr_slow and prev_fast <= prev_slow
        crossed_down = curr_fast < curr_slow and prev_fast >= prev_slow

        # Filtros comunes de fuerza/dirección.
        adx_strong = curr_adx > float(p["adx_threshold"])
        adx_rising = (not int(p["require_adx_rising"])) or curr_adx > prev_adx
        di_gap = abs(curr_pdi - curr_mdi)
        di_ok = di_gap >= float(p["di_min_gap"])
        in_session = self._within_session(df.index[-1])

        metadata = {
            "close": round(curr_close, 5),
            "ema_fast": round(curr_fast, 5),
            "ema_slow": round(curr_slow, 5),
            "ema_filter": round(curr_filter, 5),
            "adx": round(curr_adx, 2),
            "plus_di": round(curr_pdi, 2),
            "minus_di": round(curr_mdi, 2),
        }

        base_ok = adx_strong and adx_rising and di_ok and in_session

        # ── COMPRA ───────────────────────────────────────────────────────
        if (
            base_ok
            and crossed_up
            and curr_close > curr_filter    # tendencia mayor alcista
            and curr_pdi > curr_mdi         # dirección alcista dominante
            and curr_close > curr_slow      # confirmación de cuerpo de vela
        ):
            return Signal(
                type=SignalType.BUY,
                symbol=symbol,
                reason=(
                    f"Cruce alcista EMA{int(p['ema_fast'])}/{int(p['ema_slow'])} "
                    f"| ADX {curr_adx:.1f}>{float(p['adx_threshold']):.0f} "
                    f"| +DI {curr_pdi:.1f}>-DI {curr_mdi:.1f} | sobre EMA{int(p['ema_filter'])}"
                ),
                metadata=metadata,
            )

        # ── VENTA ────────────────────────────────────────────────────────
        if (
            base_ok
            and crossed_down
            and curr_close < curr_filter    # tendencia mayor bajista
            and curr_mdi > curr_pdi         # dirección bajista dominante
            and curr_close < curr_slow      # confirmación de cuerpo de vela
        ):
            return Signal(
                type=SignalType.SELL,
                symbol=symbol,
                reason=(
                    f"Cruce bajista EMA{int(p['ema_fast'])}/{int(p['ema_slow'])} "
                    f"| ADX {curr_adx:.1f}>{float(p['adx_threshold']):.0f} "
                    f"| -DI {curr_mdi:.1f}>+DI {curr_pdi:.1f} | bajo EMA{int(p['ema_filter'])}"
                ),
                metadata=metadata,
            )

        return Signal(
            type=SignalType.HOLD,
            symbol=symbol,
            reason="Sin cruce válido con fuerza ADX suficiente",
            metadata=metadata,
        )

    # -- Filtro de sesión --------------------------------------------------
    def _within_session(self, ts) -> bool:
        """¿La hora de la vela cae en la franja operativa [inicio, fin)?"""
        start = int(self.params["session_start_hour"])
        end = int(self.params["session_end_hour"])
        if start == 0 and end == 24:
            return True  # filtro desactivado
        hour = getattr(ts, "hour", None)
        if hour is None:
            return True  # sin timestamp utilizable: no bloquear
        if start <= end:
            return start <= hour < end
        # Franja que cruza la medianoche (ej. 22..3).
        return hour >= start or hour < end
