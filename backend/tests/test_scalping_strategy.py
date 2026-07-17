"""Tests de la estrategia de scalping (Bollinger + RSI, reversión a la media)."""

import numpy as np
import pandas as pd
import pytest

from app.strategies import get_strategy
from app.strategies.base_strategy import SignalType
from app.strategies.scalping_bb_rsi import bollinger_bands


def make_ohlcv(closes) -> pd.DataFrame:
    arr = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": arr, "high": arr * 1.0002, "low": arr * 0.9998,
            "close": arr, "volume": np.full(len(arr), 100),
        },
        index=pd.date_range("2025-01-01", periods=len(arr), freq="5min"),
    )


def scan_signals(closes, params=None):
    """Evalúa la estrategia en cada vela (como haría el motor) y recoge señales."""
    strategy = get_strategy("scalping_bb_rsi", params)
    signals = []
    for i in range(strategy.min_bars, len(closes) + 1):
        s = strategy.calculate_signal(make_ohlcv(closes[:i]), "EURUSD")
        signals.append(s.type)
    return signals


def test_registrada_en_el_registry():
    strategy = get_strategy("scalping_bb_rsi")
    assert strategy.name == "scalping_bb_rsi"
    assert strategy.min_bars >= 60


def test_bandas_de_bollinger():
    serie = pd.Series(np.linspace(1.0, 1.1, 50))
    lower, middle, upper = bollinger_bands(serie, 20, 2.0)
    # La media está entre las bandas y las bandas son simétricas.
    assert lower.iloc[-1] < middle.iloc[-1] < upper.iloc[-1]
    assert (middle.iloc[-1] - lower.iloc[-1]) == pytest.approx(
        upper.iloc[-1] - middle.iloc[-1]
    )


def test_compra_tras_estiron_y_reentrada():
    # Mercado lateral estable → caída brusca bajo la banda (RSI en sobreventa)
    # → vela de rebote que cierra de vuelta dentro de la banda.
    rng = np.random.default_rng(3)
    flat = list(1.1000 + rng.normal(0, 0.00008, 80))
    crash = [1.0994, 1.0988, 1.0982, 1.0976]      # estirón bajista sostenido
    bounce = [1.0987, 1.0992]                      # re-entrada en banda
    signals = scan_signals(flat + crash + bounce)
    assert SignalType.BUY in signals


def test_venta_tras_estiron_alcista():
    rng = np.random.default_rng(3)
    flat = list(1.1000 + rng.normal(0, 0.00008, 80))
    spike = [1.1006, 1.1012, 1.1018, 1.1024]       # estirón alcista
    fade = [1.1013, 1.1008]                        # re-entrada en banda
    signals = scan_signals(flat + spike + fade)
    assert SignalType.SELL in signals


def test_hold_en_mercado_tranquilo():
    # Ruido minúsculo alrededor de la media: nunca hay estirón fuera de banda
    # con RSI extremo, así que no debe haber señales.
    rng = np.random.default_rng(11)
    closes = list(1.1000 + rng.normal(0, 0.00003, 140))
    signals = scan_signals(closes)
    assert SignalType.BUY not in signals
    assert SignalType.SELL not in signals


def test_filtro_de_tendencia_bloquea_compras_contra_tendencia():
    # Tendencia bajista clara + rebote: con filtro EMA activado, el cierre
    # queda por debajo de la EMA de tendencia y la compra se bloquea.
    downtrend = list(np.linspace(1.1100, 1.1000, 90))
    crash = [1.0994, 1.0988, 1.0982, 1.0976]
    bounce = [1.0987, 1.0992]
    closes = downtrend + crash + bounce

    with_filter = scan_signals(closes, {"ema_trend_period": 50})
    without_filter = scan_signals(closes)

    assert SignalType.BUY not in with_filter
    assert SignalType.BUY in without_filter
