"""Tests de la estrategia de ruptura del rango de apertura (ORB)."""

import numpy as np
import pandas as pd

from app.strategies import get_strategy
from app.strategies.base_strategy import SignalType

# La sesión abre a las 15:00. `core_rows` empieza en esa vela; se le
# anteponen 40 velas de relleno (05:00 → 14:45) para superar min_bars sin
# crear una segunda ancla de las 15:00.
LEAD = 40
RANGE_START = "2025-01-06 15:00"


def _flat(precio):
    return (precio, precio + 0.0002, precio - 0.0002, precio)


def build(core_rows):
    lead = [_flat(1.1005) for _ in range(LEAD)]
    rows = np.asarray(lead + core_rows, dtype=float)
    start = pd.Timestamp(RANGE_START) - LEAD * pd.Timedelta(minutes=15)
    return pd.DataFrame(
        {"open": rows[:, 0], "high": rows[:, 1], "low": rows[:, 2],
         "close": rows[:, 3], "volume": np.full(len(rows), 100.0)},
        index=pd.date_range(start, periods=len(rows), freq="15min"),
    )


# Rango de apertura estándar: 4 velas entre 1.1000 y 1.1010.
RANGO = [
    (1.1005, 1.1010, 1.1000, 1.1004),
    (1.1004, 1.1009, 1.1001, 1.1006),
    (1.1006, 1.1010, 1.1002, 1.1005),
    (1.1005, 1.1008, 1.1000, 1.1007),
]


def test_registrada_y_min_bars():
    s = get_strategy("opening_range_breakout")
    assert s.name == "opening_range_breakout"
    assert s.min_bars == 40


def test_compra_en_ruptura_alcista():
    df = build(RANGO + [(1.1008, 1.1030, 1.1007, 1.1025)])  # rompe > 1.1010
    s = get_strategy("opening_range_breakout",
                     {"session_hour": 15, "range_bars": 4, "entry_window_bars": 8})
    sig = s.calculate_signal(df, "EURUSD")
    assert sig.type == SignalType.BUY
    m = sig.metadata
    assert m["range_high"] == 1.1010 and m["range_low"] == 1.1000
    assert m["sl_price"] < m["close"] < m["tp_price"]
    # SL a 1× el rango (10 pips); TP a 1.5× (15 pips) desde el cierre 1.1025.
    assert m["sl_price"] == round(1.1025 - 0.0010, 5)
    assert m["tp_price"] == round(1.1025 + 0.0015, 5)


def test_fade_invierte_la_direccion():
    df = build(RANGO + [(1.1008, 1.1030, 1.1007, 1.1025)])
    s = get_strategy("opening_range_breakout",
                     {"session_hour": 15, "range_bars": 4, "invert": 1})
    sig = s.calculate_signal(df, "EURUSD")
    assert sig.type == SignalType.SELL
    assert sig.metadata["tp_price"] < sig.metadata["close"] < sig.metadata["sl_price"]


def test_venta_en_ruptura_bajista():
    df = build(RANGO + [(1.1002, 1.1003, 1.0980, 1.0985)])  # rompe < 1.1000
    s = get_strategy("opening_range_breakout", {"session_hour": 15, "range_bars": 4})
    assert s.calculate_signal(df, "EURUSD").type == SignalType.SELL


def test_sin_ruptura_es_hold():
    df = build(RANGO + [(1.1005, 1.1008, 1.1003, 1.1006)])  # se queda dentro
    s = get_strategy("opening_range_breakout", {"session_hour": 15, "range_bars": 4})
    assert s.calculate_signal(df, "EURUSD").type == SignalType.HOLD


def test_fuera_de_ventana_no_opera():
    # Ruptura 10 velas después del rango, más allá de entry_window_bars=8.
    tarde = [_flat(1.1005) for _ in range(10)] + [(1.1008, 1.1030, 1.1007, 1.1025)]
    df = build(RANGO + tarde)
    s = get_strategy("opening_range_breakout",
                     {"session_hour": 15, "range_bars": 4, "entry_window_bars": 8})
    assert s.calculate_signal(df, "EURUSD").type == SignalType.HOLD


def test_otra_sesion_no_dispara():
    # session_hour=9, pero la apertura del dato es 15:00 -> sin ancla -> HOLD.
    df = build(RANGO + [(1.1008, 1.1030, 1.1007, 1.1025)])
    s = get_strategy("opening_range_breakout", {"session_hour": 9, "range_bars": 4})
    assert s.calculate_signal(df, "EURUSD").type == SignalType.HOLD
