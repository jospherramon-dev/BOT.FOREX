"""
Módulo B — Gestión de Riesgo (funciones puras, 100% testeables).

Responsabilidades:
- Convertir pips ↔ precio y calcular SL/TP absolutos.
- Tamaño de lote dinámico según el % de riesgo de la cuenta.
- Decidir movimientos de SL: break-even y trailing stop.
- Clasificar el motivo de cierre de una posición (SL / TP / manual).

Ninguna función toca la base de datos ni el broker: reciben valores y
devuelven decisiones. El motor (trading_engine.py) las ejecuta, y el
backtester (Módulo C) reutilizará exactamente las mismas.
"""

from __future__ import annotations

import math

from app.db.models import TradeStatus

# Límites de lote estándar de la industria.
MIN_LOT = 0.01
MAX_LOT = 100.0
#: Tamaño de contrato ESTÁNDAR (1 lote = 100.000 unidades). Las cuentas
#: Micro/Cent usan otros valores (ej. XM Micro: 1.000) — el motor pasa el
#: contract_size real consultado al broker vía get_symbol_specs().
UNITS_PER_LOT = 100_000


# ---------------------------------------------------------------------------
# Conversiones pips ↔ precio
# ---------------------------------------------------------------------------
def pips_to_price_delta(pips: float, pip_size: float) -> float:
    """Convierte una distancia en pips a distancia en precio."""
    return pips * pip_size


def price_delta_to_pips(delta: float, pip_size: float) -> float:
    """Convierte una distancia en precio a pips."""
    return delta / pip_size


def profit_pips(direction: str, entry_price: float, current_price: float,
                pip_size: float) -> float:
    """Pips a favor (positivo) o en contra (negativo) de la posición."""
    delta = current_price - entry_price
    if direction.upper() == "SELL":
        delta = -delta
    return price_delta_to_pips(delta, pip_size)


def calc_sl_tp(
    direction: str,
    entry_price: float,
    stop_loss_pips: float,
    take_profit_pips: float,
    pip_size: float,
) -> tuple[float, float]:
    """
    Calcula los precios absolutos de SL y TP a partir de distancias en pips.

    Returns:
        (stop_loss, take_profit) redondeados a la precisión del pip/10
        (5 decimales en pares estándar, 3 en pares JPY).
    """
    sl_delta = pips_to_price_delta(stop_loss_pips, pip_size)
    tp_delta = pips_to_price_delta(take_profit_pips, pip_size)

    if direction.upper() == "BUY":
        sl, tp = entry_price - sl_delta, entry_price + tp_delta
    else:
        sl, tp = entry_price + sl_delta, entry_price - tp_delta

    digits = 3 if pip_size == 0.01 else 5
    return round(sl, digits), round(tp, digits)


# ---------------------------------------------------------------------------
# ATR (volatilidad) y SL/TP adaptativos
# ---------------------------------------------------------------------------
def atr_pips(highs, lows, closes, period: int, pip_size: float) -> float:
    """
    ATR de Wilder sobre las velas dadas, devuelto EN PIPS.

    Acepta secuencias posicionales (listas o `numpy.ndarray`; NO Series con
    índice temporal — pásalas con `.to_numpy()`). Semilla = media simple de
    los primeros `period` True Range; después, suavizado de Wilder. Devuelve
    0.0 si no hay velas suficientes (el llamador cae al SL fijo).
    """
    n = len(closes)
    if n < 2 or pip_size <= 0:
        return 0.0
    period = max(1, int(period))

    trs: list[float] = []
    for i in range(1, n):
        h, low, prev_close = float(highs[i]), float(lows[i]), float(closes[i - 1])
        trs.append(max(h - low, abs(h - prev_close), abs(low - prev_close)))

    if len(trs) <= period:
        atr = sum(trs) / len(trs)
    else:
        atr = sum(trs[:period]) / period
        for tr in trs[period:]:
            atr = (atr * (period - 1) + tr) / period
    return atr / pip_size


def structural_levels(
    metadata: dict | None, direction: str, entry_price: float
) -> tuple[float, float] | None:
    """
    Extrae SL/TP ABSOLUTOS provistos por la estrategia (claves "sl_price" y
    "tp_price" en la metadata de la señal — ej. SMC: SL tras el sweep, TP en
    el pool de liquidez). Devuelve (sl, tp) solo si son coherentes con la
    dirección y el precio de entrada; en cualquier otro caso None (el motor
    cae a SL/TP por pips o ATR).
    """
    if not metadata:
        return None
    try:
        sl = float(metadata.get("sl_price") or 0)
        tp = float(metadata.get("tp_price") or 0)
    except (TypeError, ValueError):
        return None
    if sl <= 0 or tp <= 0:
        return None
    if direction.upper() == "BUY" and sl < entry_price < tp:
        return sl, tp
    if direction.upper() == "SELL" and tp < entry_price < sl:
        return sl, tp
    return None


def resolve_sl_tp_pips(
    fixed_sl_pips: float,
    fixed_tp_pips: float,
    atr_enabled: bool,
    atr_value_pips: float,
    atr_multiplier: float,
    tp_ratio: float,
    atr_min_pips: float = 0.0,
) -> tuple[float, float]:
    """
    Decide la distancia de SL y TP en pips para una entrada.

    - Con `atr_enabled=False`: usa los pips FIJOS configurados (comportamiento
      clásico; Método C del manual).
    - Con `atr_enabled=True` (Método B del manual): SL = ATR × multiplicador,
      acotado por debajo a `atr_min_pips` (el manual: "nunca < 5 pips en M5"),
      y TP = SL × ratio R:R. Si el ATR aún no está disponible (0), cae al SL
      fijo para no abrir con un SL absurdo.
    """
    if not atr_enabled:
        return fixed_sl_pips, fixed_tp_pips

    sl = atr_value_pips * atr_multiplier
    if atr_min_pips > 0:
        sl = max(sl, atr_min_pips)
    if sl <= 0:
        return fixed_sl_pips, fixed_tp_pips  # ATR no disponible: SL fijo
    return sl, sl * tp_ratio


# ---------------------------------------------------------------------------
# Tamaño de lote dinámico
# ---------------------------------------------------------------------------
def pip_value_per_lot(symbol: str, pip_size: float, price: float,
                      account_currency: str = "USD",
                      contract_size: float = UNITS_PER_LOT) -> float:
    """
    Valor monetario de 1 pip por lote, en la divisa de la cuenta.

    `contract_size` es el tamaño REAL de 1 lote en esta cuenta (100.000 en
    estándar; 1.000 en XM Micro; etc.) — en una cuenta Micro el pip vale
    ~$0.10/lote en EURUSD, no $10.

    - Divisa cotizada == divisa de cuenta (EURUSD con cuenta USD):
      valor exacto = pip_size × contract_size.
    - Divisa base == divisa de cuenta (USDJPY con cuenta USD):
      se divide por el precio actual.
    - Cruces (EURGBP con cuenta USD): APROXIMACIÓN dividiendo por el precio;
      para precisión total habría que consultar el par de conversión.
    """
    quote_currency = symbol[3:6]
    base_currency = symbol[:3]

    if quote_currency == account_currency:
        return pip_size * contract_size
    if base_currency == account_currency:
        return pip_size * contract_size / price
    return pip_size * contract_size / price  # aproximación para cruces


def calc_lot_size(
    account_balance: float,
    risk_pct: float,
    stop_loss_pips: float,
    pip_value: float,
    volume_min: float = MIN_LOT,
    volume_step: float = MIN_LOT,
) -> float:
    """
    Lote tal que, si salta el SL, la pérdida ≈ `risk_pct` % del balance.

        riesgo_monetario = balance × riesgo% / 100
        lote = riesgo_monetario / (SL_pips × valor_pip_por_lote)

    El resultado se TRUNCA (no redondea) al `volume_step` de la cuenta
    para nunca exceder el riesgo configurado, y se acota al rango
    [volume_min, MAX_LOT]. `volume_min`/`volume_step` vienen de las
    especificaciones reales del símbolo (ej. XM Micro: mínimo 0.1,
    paso 0.1) — con los defaults se conserva el comportamiento estándar
    (mínimo 0.01, truncado a 2 decimales).
    """
    if stop_loss_pips <= 0 or pip_value <= 0:
        raise ValueError("SL en pips y valor del pip deben ser positivos")
    if volume_min <= 0 or volume_step <= 0:
        raise ValueError("volume_min y volume_step deben ser positivos")

    risk_amount = account_balance * risk_pct / 100.0
    raw_lot = risk_amount / (stop_loss_pips * pip_value)
    # Truncar al paso de la cuenta (+epsilon contra errores de coma flotante).
    lot = math.floor(raw_lot / volume_step + 1e-9) * volume_step
    lot = round(lot, 6)
    return max(volume_min, min(MAX_LOT, lot))


# ---------------------------------------------------------------------------
# Break-even y trailing stop
# ---------------------------------------------------------------------------
def compute_break_even_sl(
    direction: str,
    entry_price: float,
    current_price: float,
    pip_size: float,
    trigger_pips: float,
    buffer_pips: float = 1.0,
) -> float | None:
    """
    Si la posición lleva ≥ `trigger_pips` a favor, devuelve el nuevo SL en
    el precio de entrada (+ un pequeño colchón a favor para cubrir spread).
    Devuelve None si aún no procede.
    """
    if profit_pips(direction, entry_price, current_price, pip_size) < trigger_pips:
        return None

    buffer_delta = pips_to_price_delta(buffer_pips, pip_size)
    digits = 3 if pip_size == 0.01 else 5
    if direction.upper() == "BUY":
        return round(entry_price + buffer_delta, digits)
    return round(entry_price - buffer_delta, digits)


def compute_trailing_sl(
    direction: str,
    current_price: float,
    current_sl: float | None,
    pip_size: float,
    trailing_pips: float,
) -> float | None:
    """
    SL dinámico a `trailing_pips` del precio actual. Solo devuelve un valor
    si MEJORA el SL vigente (el trailing nunca retrocede); None si no aplica.
    """
    trail_delta = pips_to_price_delta(trailing_pips, pip_size)
    digits = 3 if pip_size == 0.01 else 5

    if direction.upper() == "BUY":
        candidate = round(current_price - trail_delta, digits)
        if current_sl is None or candidate > current_sl:
            return candidate
    else:
        candidate = round(current_price + trail_delta, digits)
        if current_sl is None or candidate < current_sl:
            return candidate
    return None


# ---------------------------------------------------------------------------
# Clasificación de cierres
# ---------------------------------------------------------------------------
def classify_close(
    direction: str,
    exit_price: float | None,
    stop_loss: float | None,
    take_profit: float | None,
    pip_size: float,
    tolerance_pips: float = 3.0,
) -> TradeStatus:
    """
    Deduce el motivo de cierre comparando el precio de salida con SL/TP
    (con tolerancia por slippage). Si no coincide con ninguno → manual.
    """
    if exit_price is None:
        return TradeStatus.CLOSED_MANUAL

    tolerance = pips_to_price_delta(tolerance_pips, pip_size)
    if stop_loss is not None and abs(exit_price - stop_loss) <= tolerance:
        return TradeStatus.CLOSED_SL
    if take_profit is not None and abs(exit_price - take_profit) <= tolerance:
        return TradeStatus.CLOSED_TP
    return TradeStatus.CLOSED_MANUAL
