"""Tests de la estrategia de scalping EMA 9/21 + filtro ADX."""

import numpy as np
import pandas as pd

from app.strategies import get_strategy
from app.strategies.base_strategy import SignalType
from app.strategies.scalping_ema_adx import adx


def make_ohlcv(closes, start="2025-01-01 10:00") -> pd.DataFrame:
    arr = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": arr,
            "high": arr + 0.0003,
            "low": arr - 0.0003,
            "close": arr,
            "volume": np.full(len(arr), 100),
        },
        index=pd.date_range(start, periods=len(arr), freq="5min"),
    )


def scan_signals(closes, params=None, start="2025-01-01 10:00"):
    """Evalúa vela a vela (como el motor) y devuelve la lista de señales."""
    strategy = get_strategy("scalping_ema_adx", params)
    signals = []
    df = make_ohlcv(closes, start)
    for i in range(strategy.min_bars, len(closes) + 1):
        s = strategy.calculate_signal(df.iloc[:i], "EURUSD")
        signals.append(s.type)
    return signals


# ---------------------------------------------------------------------------
# Indicador ADX
# ---------------------------------------------------------------------------
def test_adx_alto_en_tendencia_y_bajo_en_rango():
    # Tendencia limpia → ADX alto; ruido plano → ADX bajo.
    trend = 1.1000 + np.linspace(0, 0.0200, 300)
    df_t = make_ohlcv(trend)
    adx_t, pdi_t, mdi_t = adx(df_t["high"], df_t["low"], df_t["close"], 14)
    assert float(adx_t.iloc[-1]) > 25          # tendencia = fuerza alta
    assert float(pdi_t.iloc[-1]) > float(mdi_t.iloc[-1])  # +DI domina al subir

    rng = np.random.default_rng(3)
    flat = 1.1000 + rng.normal(0, 0.0003, 300)
    df_r = make_ohlcv(flat)
    adx_r, _, _ = adx(df_r["high"], df_r["low"], df_r["close"], 14)
    assert float(adx_r.iloc[-1]) < 25          # rango = fuerza baja


# ---------------------------------------------------------------------------
# Estrategia
# ---------------------------------------------------------------------------
def test_registrada_y_min_bars():
    strategy = get_strategy("scalping_ema_adx")
    assert strategy.name == "scalping_ema_adx"
    assert strategy.min_bars == 150  # EMA filtro 50 × 3


def test_compra_en_cruce_alcista_con_adx_fuerte():
    # Escenario realista: tendencia alcista ESTABLECIDA (ADX ya alto, precio
    # sobre la EMA50) → retroceso corto que cruza la EMA9 bajo la EMA21 →
    # reanudación que vuelve a cruzar al alza. Es en esa reanudación, con la
    # fuerza aún presente, donde el cruce coincide con ADX>umbral y dispara.
    rng = np.random.default_rng(7)
    uptrend = list(1.1000 + np.linspace(0, 0.0150, 200) + rng.normal(0, 0.00003, 200))
    pullback = list(np.linspace(uptrend[-1], uptrend[-1] - 0.0022, 12))
    resume = list(np.linspace(pullback[-1] + 0.0004, pullback[-1] + 0.0090, 40))
    signals = scan_signals(uptrend + pullback + resume)
    assert SignalType.BUY in signals
    assert SignalType.SELL not in signals


def test_venta_en_cruce_bajista_con_adx_fuerte():
    rng = np.random.default_rng(7)
    downtrend = list(1.2000 - np.linspace(0, 0.0150, 200) + rng.normal(0, 0.00003, 200))
    pullback = list(np.linspace(downtrend[-1], downtrend[-1] + 0.0022, 12))
    resume = list(np.linspace(pullback[-1] - 0.0004, pullback[-1] - 0.0090, 40))
    signals = scan_signals(downtrend + pullback + resume)
    assert SignalType.SELL in signals
    assert SignalType.BUY not in signals


def test_rango_sin_fuerza_no_opera():
    # Mercado lateral: hay cruces de EMA, pero el ADX nunca supera el umbral,
    # así que el filtro los rechaza todos (el problema que resuelve la estrategia).
    rng = np.random.default_rng(11)
    closes = list(1.1000 + rng.normal(0, 0.0004, 320))
    signals = scan_signals(closes)
    assert SignalType.BUY not in signals
    assert SignalType.SELL not in signals


def test_umbral_adx_alto_bloquea_todas_las_senales():
    # Con un umbral imposible (99) ni la mejor tendencia produce entradas:
    # prueba de que el filtro ADX realmente gobierna la señal.
    rng = np.random.default_rng(7)
    base = list(1.1000 + rng.normal(0, 0.00003, 160))
    rally = list(np.linspace(1.1001, 1.1120, 120))
    signals = scan_signals(base + rally, {"adx_threshold": 99})
    assert SignalType.BUY not in signals
    assert SignalType.SELL not in signals


def test_filtro_de_sesion_bloquea_fuera_de_horario():
    # La misma tendencia que compra a las 10:00 no debe generar señal si la
    # ventana de sesión es 08–09 (todas las velas caen fuera).
    rng = np.random.default_rng(7)
    base = list(1.1000 + rng.normal(0, 0.00003, 160))
    rally = list(np.linspace(1.1001, 1.1120, 120))
    con_sesion = scan_signals(
        base + rally,
        {"session_start_hour": 8, "session_end_hour": 9},
        start="2025-01-01 10:00",
    )
    assert SignalType.BUY not in con_sesion
    assert SignalType.SELL not in con_sesion
