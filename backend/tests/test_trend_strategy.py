"""Tests de la estrategia de tendencia (triple EMA + pullback)."""

import numpy as np
import pandas as pd

from app.strategies import get_strategy
from app.strategies.base_strategy import SignalType


def make_ohlcv(closes) -> pd.DataFrame:
    arr = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": arr, "high": arr * 1.0002, "low": arr * 0.9998,
            "close": arr, "volume": np.full(len(arr), 100),
        },
        index=pd.date_range("2025-01-01", periods=len(arr), freq="15min"),
    )


def scan_signals(closes, params=None):
    """Evalúa vela a vela (como el motor) y devuelve la lista de señales."""
    strategy = get_strategy("trend_ema_pullback", params)
    signals = []
    for i in range(strategy.min_bars, len(closes) + 1):
        s = strategy.calculate_signal(make_ohlcv(closes[:i]), "EURUSD")
        signals.append(s.type)
    return signals


def test_registrada_y_min_bars():
    strategy = get_strategy("trend_ema_pullback")
    assert strategy.name == "trend_ema_pullback"
    assert strategy.min_bars == 400  # EMA lenta 200 × 2


def test_compra_en_reanudacion_de_tendencia_alcista():
    # Subida larga (alinea las 3 EMAs) → retroceso corto bajo la EMA rápida
    # → reanudación alcista: debe aparecer al menos un BUY tras el retroceso.
    rng = np.random.default_rng(5)
    uptrend = list(1.0500 + np.linspace(0, 0.0600, 450) + rng.normal(0, 0.00005, 450))
    pullback = list(np.linspace(uptrend[-1], uptrend[-1] - 0.0025, 10))
    resume = list(np.linspace(pullback[-1] + 0.0005, pullback[-1] + 0.0060, 15))
    signals = scan_signals(uptrend + pullback + resume)
    assert SignalType.BUY in signals
    assert SignalType.SELL not in signals  # jamás vende en tendencia alcista


def test_venta_en_reanudacion_de_tendencia_bajista():
    rng = np.random.default_rng(5)
    downtrend = list(1.2000 - np.linspace(0, 0.0600, 450) + rng.normal(0, 0.00005, 450))
    pullback = list(np.linspace(downtrend[-1], downtrend[-1] + 0.0025, 10))
    resume = list(np.linspace(pullback[-1] - 0.0005, pullback[-1] - 0.0060, 15))
    signals = scan_signals(downtrend + pullback + resume)
    assert SignalType.SELL in signals
    assert SignalType.BUY not in signals


def test_en_rango_se_queda_fuera():
    # Mercado lateral: las EMAs se entrelazan, no hay alineación → sin señales.
    rng = np.random.default_rng(9)
    closes = list(1.1000 + rng.normal(0, 0.0004, 480))
    signals = scan_signals(closes)
    assert SignalType.BUY not in signals
    assert SignalType.SELL not in signals


def test_rsi_desactivable():
    # Con rsi_period=0 el filtro de momentum se apaga y la estrategia sigue
    # funcionando (mismo escenario alcista del test de compra).
    rng = np.random.default_rng(5)
    uptrend = list(1.0500 + np.linspace(0, 0.0600, 450) + rng.normal(0, 0.00005, 450))
    pullback = list(np.linspace(uptrend[-1], uptrend[-1] - 0.0025, 10))
    resume = list(np.linspace(pullback[-1] + 0.0005, pullback[-1] + 0.0060, 15))
    signals = scan_signals(uptrend + pullback + resume, {"rsi_period": 0})
    assert SignalType.BUY in signals
