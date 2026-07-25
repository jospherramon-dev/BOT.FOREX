"""Tests de la estrategia SMC (sweep de liquidez + scoring 0-17)."""

import numpy as np
import pandas as pd
import pytest

from app.engine import risk_manager as rm
from app.strategies import get_strategy
from app.strategies.base_strategy import SignalType
from app.strategies.smc_liquidity_sweep import (
    aggregate_htf,
    detect_pot_phase,
    detect_sweep,
    find_fvg,
    find_order_block,
    has_ifvg,
    structure_bias,
)


# ---------------------------------------------------------------------------
# Detectores puros
# ---------------------------------------------------------------------------
def test_structure_bias_direcciones():
    up = np.linspace(1.10, 1.12, 30)
    assert structure_bias(up + 0.0002, up) == "BULL"
    down = np.linspace(1.12, 1.10, 30)
    assert structure_bias(down + 0.0002, down) == "BEAR"
    flat = np.full(30, 1.11)
    assert structure_bias(flat + 0.0002, flat) == "NEUTRAL"


def test_detect_sweep_bajista_bsl():
    # Plano en 1.1000; la última vela rompe el máximo con mecha larga
    # y cierra de vuelta dentro → sweep BSL → distribución bajista (-1).
    n = 20
    o = np.full(n, 1.1000)
    c = np.full(n, 1.1001)
    h = np.full(n, 1.1003)
    low = np.full(n, 1.0998)
    h[-1] = 1.1030          # caza el máximo
    c[-1] = 1.1002          # cierra dentro (mecha superior enorme)
    o[-1] = 1.1001
    direction, extreme = detect_sweep(o, h, low, c, None, 12, 1.2, False)
    assert direction == -1
    assert extreme == pytest.approx(1.1030)


def test_detect_sweep_alcista_ssl():
    n = 20
    o = np.full(n, 1.1000)
    c = np.full(n, 1.0999)
    h = np.full(n, 1.1002)
    low = np.full(n, 1.0997)
    low[-1] = 1.0970        # caza el mínimo
    c[-1] = 1.0999          # cierra dentro (mecha inferior enorme)
    o[-1] = 1.1000
    direction, extreme = detect_sweep(o, h, low, c, None, 12, 1.2, False)
    assert direction == +1
    assert extreme == pytest.approx(1.0970)


def test_detect_sweep_sin_ruptura_no_dispara():
    n = 20
    o = np.full(n, 1.1000)
    c = np.full(n, 1.1001)
    h = np.full(n, 1.1003)
    low = np.full(n, 1.0998)
    direction, _ = detect_sweep(o, h, low, c, None, 12, 1.2, False)
    assert direction == 0


def test_detect_pot_distribucion():
    # 9 velas HTF en rango + penúltima rompe el máximo y cierra dentro
    # → fase DIST con dirección bajista (opuesta al sweep de BSL).
    h = np.full(12, 1.1010)
    low = np.full(12, 1.0990)
    c = np.full(12, 1.1000)
    h[-2] = 1.1035
    c[-2] = 1.1005
    phase, direction = detect_pot_phase(h, low, c, 30, 0.0001)
    assert phase == "DIST"
    assert direction == -1


def test_find_fvg_alcista():
    # Gap alcista: high de la vela j no toca el low de la vela j+2.
    h = np.array([1.1000, 1.1005, 1.1030, 1.1035, 1.1040])
    low = np.array([1.0995, 1.1000, 1.1020, 1.1028, 1.1033])
    zone = find_fvg(h, low, +1, 10)
    assert zone is not None
    assert zone[0] < zone[1]


def test_has_ifvg_invalidado():
    # FVG bajista (low[j] > high[j+2]) invalidado por cierre posterior al
    # alza → refuerza una entrada de COMPRA.
    h = np.array([1.1040, 1.1035, 1.1010, 1.1015, 1.1050, 1.1060])
    low = np.array([1.1030, 1.1025, 1.1000, 1.1005, 1.1042, 1.1052])
    c = np.array([1.1035, 1.1030, 1.1005, 1.1010, 1.1048, 1.1058])
    assert has_ifvg(h, low, c, +1, 10) is True


def test_aggregate_htf_agrupa_desde_el_final():
    o = np.arange(30, dtype=float)
    h = o + 0.5
    low = o - 0.5
    c = o + 0.1
    ho, hh, hl, hc = aggregate_htf(o, h, low, c, factor=3, max_bars=5)
    assert len(hc) == 5
    assert hc[-1] == pytest.approx(c[-1])       # último grupo termina al final
    assert hh[-1] == pytest.approx(h[-3:].max())
    assert hl[-1] == pytest.approx(low[-3:].min())


def test_structural_levels_validacion():
    meta = {"sl_price": 1.0990, "tp_price": 1.1030}
    assert rm.structural_levels(meta, "BUY", 1.1000) == (1.0990, 1.1030)
    assert rm.structural_levels(meta, "SELL", 1.1000) is None  # incoherente
    meta_sell = {"sl_price": 1.1030, "tp_price": 1.0960}
    assert rm.structural_levels(meta_sell, "SELL", 1.1000) == (1.1030, 1.0960)
    assert rm.structural_levels(None, "BUY", 1.1) is None
    assert rm.structural_levels({}, "BUY", 1.1) is None


# ---------------------------------------------------------------------------
# Estrategia integrada
# ---------------------------------------------------------------------------
def _df(o, h, low, c, start="2025-01-06 03:00") -> pd.DataFrame:
    n = len(c)
    return pd.DataFrame(
        {"open": o, "high": h, "low": low, "close": c,
         "volume": np.full(n, 100.0)},
        index=pd.date_range(start, periods=n, freq="5min"),
    )


def _uptrend_arrays(n=420):
    c = np.linspace(1.1000, 1.1050, n)
    o = c.copy()
    h = c + 0.0001
    low = c - 0.0001
    return o, h, low, c


def test_registrada_y_min_bars():
    strategy = get_strategy("smc_liquidity_sweep")
    assert strategy.name == "smc_liquidity_sweep"
    assert strategy.min_bars == 400


def test_compra_tras_sweep_de_minimos_en_tendencia_alcista():
    # Tendencia alcista (bias BULL) + última vela caza los mínimos del
    # swing con mecha inferior larga y cierra de vuelta → BUY con SL
    # estructural bajo el sweep y TP con R:R ≥ min_rr.
    o, h, low, c = _uptrend_arrays()
    swing_low = low[-14:-2].min()
    o[-1] = c[-2]
    c[-1] = c[-2] + 0.0001
    h[-1] = c[-1] + 0.0001
    low[-1] = swing_low - 0.0015     # mecha profunda que barre los stops
    df = _df(o, h, low, c)

    strategy = get_strategy("smc_liquidity_sweep", {"min_score": 5})
    signal = strategy.calculate_signal(df, "EURUSD")

    assert signal.type == SignalType.BUY
    meta = signal.metadata
    assert meta["score"] >= 5
    assert meta["sl_price"] < meta["close"] < meta["tp_price"]
    assert meta["sl_price"] < swing_low                # SL detrás del sweep
    assert meta["breakdown"]["sweep"] == 3
    assert meta["breakdown"]["bias"] == 2              # BULL alineado


def test_venta_tras_sweep_de_maximos_en_tendencia_bajista():
    o, h, low, c = _uptrend_arrays()
    # Espejo: tendencia bajista + sweep del máximo del swing.
    c = c[::-1].copy()
    o = c.copy()
    h = c + 0.0001
    low = c - 0.0001
    swing_high = h[-14:-2].max()
    o[-1] = c[-2]
    c[-1] = c[-2] - 0.0001
    low[-1] = c[-1] - 0.0001
    h[-1] = swing_high + 0.0015
    df = _df(o, h, low, c)

    strategy = get_strategy("smc_liquidity_sweep", {"min_score": 5})
    signal = strategy.calculate_signal(df, "EURUSD")

    assert signal.type == SignalType.SELL
    meta = signal.metadata
    assert meta["tp_price"] < meta["close"] < meta["sl_price"]


def test_sin_sweep_no_opera():
    # Subida limpia sin barrer ningún mínimo: HOLD en todas las velas.
    o, h, low, c = _uptrend_arrays()
    df = _df(o, h, low, c)
    strategy = get_strategy("smc_liquidity_sweep", {"min_score": 1})
    signal = strategy.calculate_signal(df, "EURUSD")
    assert signal.type == SignalType.HOLD
    assert "sweep" in signal.reason.lower()


def test_min_score_bloquea():
    # El mismo escenario de compra con umbral imposible → HOLD por score.
    o, h, low, c = _uptrend_arrays()
    swing_low = low[-14:-2].min()
    o[-1] = c[-2]
    c[-1] = c[-2] + 0.0001
    h[-1] = c[-1] + 0.0001
    low[-1] = swing_low - 0.0015
    df = _df(o, h, low, c)

    strategy = get_strategy("smc_liquidity_sweep", {"min_score": 17})
    signal = strategy.calculate_signal(df, "EURUSD")
    assert signal.type == SignalType.HOLD
    assert "score" in signal.reason.lower()


def test_gate_de_bias_bloquea_contra_tendencia():
    # Sweep alcista pero en TENDENCIA BAJISTA: con require_bias=1 (default)
    # el gate lo bloquea; con require_bias=0 la señal pasa.
    o, h, low, c = _uptrend_arrays()
    c = c[::-1].copy()               # bajista
    o = c.copy()
    h = c + 0.0001
    low = c - 0.0001
    swing_low = low[-14:-2].min()
    o[-1] = c[-2]
    c[-1] = c[-2] + 0.0001
    h[-1] = c[-1] + 0.0001
    low[-1] = swing_low - 0.0015     # sweep de mínimos (señal de compra)
    df = _df(o, h, low, c)

    con_gate = get_strategy("smc_liquidity_sweep", {"min_score": 1})
    assert con_gate.calculate_signal(df, "EURUSD").type == SignalType.HOLD

    sin_gate = get_strategy(
        "smc_liquidity_sweep", {"min_score": 1, "require_bias": 0}
    )
    assert sin_gate.calculate_signal(df, "EURUSD").type == SignalType.BUY


def test_order_block_detectado():
    # Vela bajista seguida de dos alcistas, sin cierres posteriores por
    # debajo → OB válido para dirección alcista.
    o = np.array([1.1000, 1.1004, 1.0998, 1.1002, 1.1010, 1.1018])
    c = np.array([1.1004, 1.0998, 1.1002, 1.1010, 1.1018, 1.1025])
    h = c + 0.0002
    low = np.minimum(o, c) - 0.0002
    zone = find_order_block(o, h, low, c, +1, 10)
    assert zone is not None
    assert zone[0] <= 1.0998 - 0.0002 + 1e-9
