"""
ESTRATEGIA SMC — Caza de liquidez (sweep) con scoring ponderado.
================================================================

Adaptación del manual "Bot SMC Autónomo" (Z.AI v1.0) al motor de BOT.FOREX.
En lugar de indicadores retardados (EMAs, RSI), lee ACCIÓN DE PRECIO
institucional: liquidez, sweeps, order blocks, fair value gaps y fases de
Power of Three, combinados en un SCORE 0-17. Solo opera si el score supera
el umbral configurado.

La señal núcleo (y única obligatoria) es el LIQUIDITY SWEEP:

    El precio rompe un máximo/mínimo reciente (cazando los stops ahí
    acumulados) con MECHA LARGA y CIERRA de vuelta dentro del rango.
    Esa ruptura falsa revela que la liquidez ya fue tomada; el movimiento
    esperado (la "distribución") va en dirección OPUESTA al sweep.
    Sweep de mínimos (SSL) → COMPRA. Sweep de máximos (BSL) → VENTA.

Las otras 10 señales SUMAN PUNTOS (pesos del manual, máximo 17):
kill zone (+0..3), bias HTF (+2), fase PoT=Distribución (+2), sweep (+3),
order block (+2), FVG (+1), IFVG (+1), liquidez objetivo (+2), pullback a
OB (+1), liquidez interna (+1), tendencia menor (+1).

CORRECCIONES sobre el código del manual (que "asumía" señales sin calcular):
  * "Liquidez objetivo" (+2) se CALCULA de verdad: debe existir un pool
    (swing alto/bajo) a distancia ≥ min_rr × SL. El PDF regalaba estos 2
    puntos en cada evaluación.
  * "Tendencia menor alineada" (+1) también se calcula (estructura del TF
    de ejecución), no se asume.
  * Filtro de volumen del sweep (documentado en el PDF pero nunca
    implementado en su código): disponible vía `sweep_vol_filter`.

MULTI-TIMEFRAME sin tocar el motor: la estrategia recibe las velas del TF
de ejecución (M5 recomendado) y AGREGA internamente hacia el HTF
(`htf_minutes`, 15 por defecto) para bias y fase PoT. El factor se infiere
del espaciado del índice temporal; si se le da M15 directamente, factor=1.

FRECUENCIA (petición del operador: entradas diarias, no 70 en 4 años):
los 4 "gates" del manual (kill zone + bias + PoT + sweep) son tan
estrictos que producen ~1 operación por semana. Aquí cada gate es
CONFIGURABLE: por defecto solo se exigen sweep + bias; PoT y kill zone
suman puntos pero no bloquean. Perillas de frecuencia, de mayor a menor
efecto: `min_score` (bajar = más trades), `sweep_wick_body_ratio` (bajar),
`require_*` (activar = menos trades), `min_rr` (bajar = más fills).

SL/TP ESTRUCTURAL: el SL va detrás del extremo del sweep (no en pips
fijos) y el TP en el siguiente pool de liquidez (o min_rr × SL como
mínimo, max_rr × SL como techo). Ambos viajan en `Signal.metadata`
("sl_price"/"tp_price") y el motor/backtester los honran tal cual.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.strategies.base_strategy import BaseStrategy, Signal, SignalType


# ---------------------------------------------------------------------------
# Detectores puros (testeables de forma aislada, arrays cronológicos)
# ---------------------------------------------------------------------------
def aggregate_htf(
    opens: np.ndarray, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
    factor: int, max_bars: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Agrega velas del TF de ejecución al HTF por grupos de `factor`,
    alineados para que el ÚLTIMO grupo termine en la última vela cerrada.
    (Aproximación: los grupos no se anclan al reloj, sino al presente.)
    """
    if factor <= 1:
        n = min(max_bars, len(closes))
        return opens[-n:], highs[-n:], lows[-n:], closes[-n:]
    groups = min(max_bars, len(closes) // factor)
    take = groups * factor
    o = opens[-take:].reshape(groups, factor)[:, 0]
    h = highs[-take:].reshape(groups, factor).max(axis=1)
    low = lows[-take:].reshape(groups, factor).min(axis=1)
    c = closes[-take:].reshape(groups, factor)[:, -1]
    return o, h, low, c


def structure_bias(highs: np.ndarray, lows: np.ndarray, margin: int = 2) -> str:
    """Bias por estructura: cuenta velas HH+HL (alcistas) vs LH+LL (bajistas)."""
    up = down = 0
    for i in range(1, len(highs)):
        if highs[i] > highs[i - 1] and lows[i] > lows[i - 1]:
            up += 1
        elif highs[i] < highs[i - 1] and lows[i] < lows[i - 1]:
            down += 1
    if up > down + margin:
        return "BULL"
    if down > up + margin:
        return "BEAR"
    return "NEUTRAL"


def detect_sweep(
    opens: np.ndarray, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
    volumes: np.ndarray | None, lookback: int, wick_body_ratio: float,
    vol_filter: bool, min_wick: float = 0.0,
) -> tuple[int, float]:
    """
    Sweep en las últimas 2 velas contra el swing de las `lookback` previas.

    Devuelve (dirección, extremo_del_sweep):
      +1 = sweep de mínimos (SSL) → distribución ALCISTA, extremo = low.
      -1 = sweep de máximos (BSL) → distribución BAJISTA, extremo = high.
       0 = sin sweep.
    """
    if len(closes) < lookback + 3:
        return 0, 0.0
    swing_high = float(highs[-(lookback + 2):-2].max())
    swing_low = float(lows[-(lookback + 2):-2].min())

    for i in (-1, -2):  # vela recién cerrada primero
        body = abs(float(closes[i]) - float(opens[i]))
        upper = float(highs[i]) - max(float(opens[i]), float(closes[i]))
        lower = min(float(opens[i]), float(closes[i])) - float(lows[i])
        if vol_filter and volumes is not None and len(volumes) >= 12:
            if float(volumes[i]) <= float(volumes[-12:-2].mean()):
                continue
        # BSL: rompe el máximo, mecha superior larga, cierra dentro.
        # `min_wick` evita que dojis (cuerpo ≈ 0) disparen falsos sweeps.
        if (float(highs[i]) > swing_high and float(closes[i]) < swing_high
                and upper > body * wick_body_ratio and upper >= min_wick):
            return -1, float(highs[i])
        # SSL: rompe el mínimo, mecha inferior larga, cierra dentro.
        if (float(lows[i]) < swing_low and float(closes[i]) > swing_low
                and lower > body * wick_body_ratio and lower >= min_wick):
            return +1, float(lows[i])
    return 0, 0.0


def detect_pot_phase(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
    range_pips: float, pip_size: float,
) -> tuple[str, int]:
    """
    Fase Power of Three sobre las últimas 12 velas HTF: rango en las velas
    viejas (0..8) + sweep del rango en las últimas 3 → DISTRIBUCIÓN con
    dirección opuesta al sweep. Rango estrecho sin ruptura → ACUMULACIÓN.
    """
    if len(closes) < 12:
        return "NEUTRAL", 0
    h, low, c = highs[-12:], lows[-12:], closes[-12:]
    range_high = float(h[:9].max())
    range_low = float(low[:9].min())
    for i in (-1, -2, -3):
        if float(h[i]) > range_high and float(c[i]) < range_high:
            return "DIST", -1   # sweep BSL → distribución bajista
        if float(low[i]) < range_low and float(c[i]) > range_low:
            return "DIST", +1   # sweep SSL → distribución alcista
    if (range_high - range_low) < range_pips * pip_size:
        return "ACC", 0
    return "NEUTRAL", 0


def find_order_block(
    opens: np.ndarray, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
    direction: int, lookback: int,
) -> tuple[float, float] | None:
    """
    Order block: última vela CONTRARIA seguida de 2 velas de impulso a
    favor. Devuelve la zona (low, high) del OB más reciente NO violado
    (sin cierres posteriores más allá de su extremo), o None.
    """
    n = len(closes)
    start = max(1, n - 2 - lookback)
    for j in range(n - 3, start - 1, -1):
        if direction > 0:
            is_ob = (closes[j] < opens[j]
                     and closes[j + 1] > opens[j + 1]
                     and closes[j + 2] > opens[j + 2])
            if is_ob and closes[j + 1:].min() > lows[j]:
                return float(lows[j]), float(highs[j])
        else:
            is_ob = (closes[j] > opens[j]
                     and closes[j + 1] < opens[j + 1]
                     and closes[j + 2] < opens[j + 2])
            if is_ob and closes[j + 1:].max() < highs[j]:
                return float(lows[j]), float(highs[j])
    return None


def find_fvg(
    highs: np.ndarray, lows: np.ndarray, direction: int, lookback: int,
) -> tuple[float, float] | None:
    """
    Fair Value Gap de 3 velas más reciente en la dirección dada.
    Alcista: high[j] < low[j+2] (hueco arriba). Bajista: low[j] > high[j+2].
    Devuelve la zona (low, high) del gap o None.
    """
    n = len(highs)
    start = max(0, n - 2 - lookback)
    for j in range(n - 3, start - 1, -1):
        if direction > 0 and highs[j] < lows[j + 2]:
            return float(highs[j]), float(lows[j + 2])
        if direction < 0 and lows[j] > highs[j + 2]:
            return float(highs[j + 2]), float(lows[j])
    return None


def has_ifvg(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
    direction: int, lookback: int,
) -> bool:
    """
    IFVG: un FVG CONTRARIO a la dirección del trade que fue invalidado por
    un cierre posterior a favor (el gap roto se vuelve soporte/resistencia
    invertida que refuerza la tesis).
    """
    n = len(highs)
    start = max(0, n - 4 - lookback)
    for j in range(n - 4, start - 1, -1):
        if direction > 0 and lows[j] > highs[j + 2]:          # FVG bajista…
            if closes[j + 3:].max() > lows[j]:                 # …invalidado al alza
                return True
        if direction < 0 and highs[j] < lows[j + 2]:           # FVG alcista…
            if closes[j + 3:].min() < highs[j]:                # …invalidado a la baja
                return True
    return False


# ---------------------------------------------------------------------------
# Estrategia
# ---------------------------------------------------------------------------
class SmcLiquiditySweepStrategy(BaseStrategy):
    """Sweep de liquidez + scoring SMC 0-17 con SL/TP estructural."""

    name = "smc_liquidity_sweep"
    description = (
        "Smart Money Concepts: entra en dirección opuesta a un sweep de "
        "liquidez (ruptura falsa con mecha larga), puntuando 11 señales "
        "(bias HTF, PoT, OB, FVG, IFVG, kill zone, liquidez objetivo…) "
        "hasta 17 puntos. SL detrás del sweep, TP en el siguiente pool. "
        "min_score y los require_* controlan la frecuencia de entradas."
    )

    @classmethod
    def default_params(cls) -> dict:
        return {
            # -- Multi-timeframe ------------------------------------------
            "htf_minutes": 15,        # HTF para bias/PoT (agregado interno)
            # -- Umbral y gates (frecuencia) -------------------------------
            "min_score": 8,           # de 17; bajar = más operaciones
            "require_bias": 1,        # exigir bias HTF alineado
            "require_pot": 0,         # exigir fase PoT=Distribución (estricto)
            "require_killzone": 0,    # exigir kill zone ITC activa
            "require_liq_target": 0,  # exigir pool de liquidez como TP
            # -- Sweep (señal núcleo, siempre obligatoria) -----------------
            "swing_lookback": 12,     # velas del swing barrido
            "sweep_wick_body_ratio": 1.2,  # mecha ≥ ratio × cuerpo (PDF: 1.5)
            "sweep_min_wick_pips": 3,  # mecha mínima real (filtra dojis)
            "sweep_vol_filter": 0,    # 1 = exigir volumen > media (PDF §7.2)
            # -- Detectores ------------------------------------------------
            "pot_range_pips": 30,     # rango máx. de la acumulación (HTF)
            "ob_lookback": 15,        # ventana de order blocks (TF ejecución)
            "fvg_max_dist_pips": 15,  # FVG "coincidente" si está a ≤ X pips
            "liq_lookback": 40,       # ventana de pools de liquidez
            # -- Kill zones (hora del broker → ET) -------------------------
            "broker_et_offset": 7,    # XM GMT+3 vs Nueva York (verano) = 7
            # -- SL/TP estructural -----------------------------------------
            "sl_buffer_pips": 2,      # colchón tras el extremo del sweep
            "min_rr": 1.5,            # R:R mínimo aceptado (PDF exige 2)
            "max_rr": 3.0,            # techo del TP aunque el pool esté lejos
        }

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params)
        # Cubre el peor caso de entrada M1 (factor 15 → ~26 velas HTF).
        self.min_bars = 400

    # -- señal ------------------------------------------------------------
    def calculate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        self.validate_data(df)
        p = self.params
        pip_size = 0.01 if "JPY" in symbol.upper() else 0.0001

        opens = df["open"].to_numpy(dtype=float)
        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)
        volumes = (
            df["volume"].to_numpy(dtype=float) if "volume" in df.columns else None
        )
        close = float(closes[-1])

        # 1) SWEEP — sin él no hay trade (define la dirección).
        direction, sweep_extreme = detect_sweep(
            opens, highs, lows, closes, volumes,
            int(p["swing_lookback"]), float(p["sweep_wick_body_ratio"]),
            bool(int(p["sweep_vol_filter"])),
            min_wick=float(p["sweep_min_wick_pips"]) * pip_size,
        )
        if direction == 0:
            return Signal(type=SignalType.HOLD, symbol=symbol,
                          reason="Sin sweep de liquidez", metadata={"score": 0})

        # 2) HTF (bias + PoT) sobre velas agregadas internamente.
        factor = self._htf_factor(df)
        ho, hh, hl, hc = aggregate_htf(
            opens, highs, lows, closes, factor, max_bars=30
        )
        bias = structure_bias(hh, hl)
        pot_phase, pot_dir = detect_pot_phase(
            hh, hl, hc, float(p["pot_range_pips"]), pip_size
        )

        bias_ok = (bias == "BULL" and direction > 0) or (
            bias == "BEAR" and direction < 0
        )
        pot_ok = pot_phase == "DIST" and pot_dir == direction
        kz_name, kz_weight = self._kill_zone(df.index[-1])

        # -- Gates configurables ------------------------------------------
        if int(p["require_bias"]) and not bias_ok:
            return self._hold(symbol, f"Bias HTF ({bias}) no alineado", bias, kz_name)
        if int(p["require_pot"]) and not pot_ok:
            return self._hold(symbol, f"Fase PoT ({pot_phase}) sin distribución "
                                      "a favor", bias, kz_name)
        if int(p["require_killzone"]) and kz_weight <= 0:
            return self._hold(symbol, "Fuera de kill zone ITC", bias, kz_name)

        # 3) Zonas de interés en el TF de ejecución.
        ob_zone = find_order_block(
            opens, highs, lows, closes, direction, int(p["ob_lookback"])
        )
        fvg_zone = find_fvg(highs, lows, direction, int(p["ob_lookback"]))
        fvg_near = fvg_zone is not None and (
            min(abs(close - fvg_zone[0]), abs(close - fvg_zone[1]))
            <= float(p["fvg_max_dist_pips"]) * pip_size
        )
        ifvg = has_ifvg(highs, lows, closes, direction, int(p["ob_lookback"]))
        pullback_ob = ob_zone is not None and ob_zone[0] <= close <= ob_zone[1]

        # 4) SL estructural: detrás del extremo del sweep.
        buffer = float(p["sl_buffer_pips"]) * pip_size
        sl_price = sweep_extreme - buffer if direction > 0 else sweep_extreme + buffer
        sl_dist = abs(close - sl_price)
        if sl_dist <= 0:
            return self._hold(symbol, "SL estructural inválido", bias, kz_name)

        # 5) Liquidez objetivo (+2 REAL, no asumido) y TP.
        liq = int(p["liq_lookback"])
        min_rr, max_rr = float(p["min_rr"]), float(p["max_rr"])
        if direction > 0:
            pool = float(highs[-liq:].max())
            pool_dist = pool - close
        else:
            pool = float(lows[-liq:].min())
            pool_dist = close - pool
        liq_target = pool_dist >= min_rr * sl_dist
        if int(p["require_liq_target"]) and not liq_target:
            return self._hold(symbol, "Sin pool de liquidez a distancia útil",
                              bias, kz_name)
        tp_dist = min(pool_dist, max_rr * sl_dist) if liq_target else min_rr * sl_dist
        if tp_dist < min_rr * sl_dist:
            return self._hold(symbol, "R:R por debajo del mínimo", bias, kz_name)
        tp_price = close + tp_dist if direction > 0 else close - tp_dist

        # 6) Liquidez interna (+1): entrar cerca del extremo favorable del
        # rango (descuento en compras, premium en ventas), no en el medio.
        rng_high = float(highs[-liq:].max())
        rng_low = float(lows[-liq:].min())
        rng = rng_high - rng_low
        pos = (close - rng_low) / rng if rng > 0 else 0.5
        internal_ok = pos <= 0.4 if direction > 0 else pos >= 0.6

        # 7) Tendencia menor (+1 REAL): estructura del TF de ejecución.
        minor = structure_bias(highs[-12:], lows[-12:], margin=1)
        minor_ok = (minor == "BULL" and direction > 0) or (
            minor == "BEAR" and direction < 0
        )

        # -- Score (pesos del manual, máximo 17) --------------------------
        breakdown = {
            "kill_zone": kz_weight,
            "bias": 2 if bias_ok else 0,
            "pot": 2 if pot_ok else 0,
            "sweep": 3,
            "order_block": 2 if ob_zone else 0,
            "fvg": 1 if fvg_near else 0,
            "ifvg": 1 if ifvg else 0,
            "liq_objetivo": 2 if liq_target else 0,
            "pullback_ob": 1 if pullback_ob else 0,
            "liq_interna": 1 if internal_ok else 0,
            "tendencia_menor": 1 if minor_ok else 0,
        }
        score = sum(breakdown.values())

        digits = 3 if pip_size == 0.01 else 5
        metadata = {
            "score": score,
            "score_max": 17,
            "breakdown": breakdown,
            "bias": bias,
            "pot_phase": pot_phase,
            "kill_zone": kz_name,
            "sweep_extreme": round(sweep_extreme, digits),
            "sl_price": round(sl_price, digits),
            "tp_price": round(tp_price, digits),
            "close": round(close, digits),
        }

        if score < int(p["min_score"]):
            return Signal(
                type=SignalType.HOLD, symbol=symbol,
                reason=f"Score {score}/17 < umbral {int(p['min_score'])}",
                metadata=metadata,
            )

        side = "SSL barrida (compra)" if direction > 0 else "BSL barrida (venta)"
        return Signal(
            type=SignalType.BUY if direction > 0 else SignalType.SELL,
            symbol=symbol,
            reason=f"SMC {side} | score {score}/17 | bias {bias} | KZ {kz_name}",
            metadata=metadata,
        )

    # -- helpers -----------------------------------------------------------
    def _htf_factor(self, df: pd.DataFrame) -> int:
        """Velas de ejecución por vela HTF, inferido del índice temporal."""
        try:
            deltas = df.index.to_series().diff().dropna()
            tf_minutes = max(1.0, deltas.median().total_seconds() / 60.0)
        except Exception:  # noqa: BLE001 — índice sin tiempos: asumir 1:1
            return 1
        return max(1, round(float(self.params["htf_minutes"]) / tf_minutes))

    def _kill_zone(self, ts) -> tuple[str, int]:
        """Kill zone ITC según hora ET (hora broker − broker_et_offset)."""
        hour = getattr(ts, "hour", None)
        if hour is None:
            return "NONE", 0
        et = (hour - int(self.params["broker_et_offset"])) % 24
        if 2 <= et < 5:
            return "LONDON", 3
        if 7 <= et < 10:
            return "NY_AM", 2
        if 12 <= et < 15:
            return "NY_PM", 1
        if 0 <= et < 7:
            return "ASIA", 0
        return "NONE", 0

    def _hold(self, symbol: str, reason: str, bias: str, kz: str) -> Signal:
        return Signal(type=SignalType.HOLD, symbol=symbol, reason=reason,
                      metadata={"score": 0, "bias": bias, "kill_zone": kz})
