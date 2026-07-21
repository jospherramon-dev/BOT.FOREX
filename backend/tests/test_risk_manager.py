"""Tests del gestor de riesgo (Módulo B) — funciones puras."""

import numpy as np
import pytest

from app.db.models import TradeStatus
from app.engine import risk_manager as rm


# ---------------------------------------------------------------------------
# ATR y SL/TP adaptativos (Método B del manual EMA+ADX)
# ---------------------------------------------------------------------------
def test_atr_pips_rango_constante():
    # Velas con rango real constante de 10 pips (high-low) y sin gaps:
    # el ATR debe converger a ~10 pips.
    n = 60
    closes = np.full(n, 1.1000)
    highs = closes + 0.0005   # +5 pips
    lows = closes - 0.0005    # -5 pips  → rango 10 pips
    atr = rm.atr_pips(highs, lows, closes, 14, 0.0001)
    assert atr == pytest.approx(10.0, abs=0.5)


def test_atr_pips_pocas_velas_devuelve_cero():
    assert rm.atr_pips([1.1], [1.1], [1.1], 14, 0.0001) == 0.0


def test_resolve_sl_tp_fijo_cuando_atr_desactivado():
    sl, tp = rm.resolve_sl_tp_pips(30, 60, False, 8.0, 1.5, 2.0, 5.0)
    assert (sl, tp) == (30, 60)


def test_resolve_sl_tp_por_atr():
    # ATR 8 pips × 1.5 = 12 pips de SL; TP = 12 × 2.0 = 24 pips (R:R 1:2).
    sl, tp = rm.resolve_sl_tp_pips(30, 60, True, 8.0, 1.5, 2.0, 5.0)
    assert sl == pytest.approx(12.0)
    assert tp == pytest.approx(24.0)


def test_resolve_sl_tp_respeta_minimo():
    # ATR minúsculo (2 pips × 1.5 = 3) se eleva al mínimo de 5 pips.
    sl, tp = rm.resolve_sl_tp_pips(30, 60, True, 2.0, 1.5, 2.0, 5.0)
    assert sl == pytest.approx(5.0)
    assert tp == pytest.approx(10.0)


def test_resolve_sl_tp_cae_a_fijo_sin_atr():
    # ATR no disponible (0): usa el SL/TP fijo para no abrir con SL absurdo.
    sl, tp = rm.resolve_sl_tp_pips(30, 60, True, 0.0, 1.5, 2.0, 0.0)
    assert (sl, tp) == (30, 60)


# ---------------------------------------------------------------------------
# SL/TP y conversiones
# ---------------------------------------------------------------------------
def test_calc_sl_tp_buy():
    sl, tp = rm.calc_sl_tp("BUY", 1.1000, 30, 60, 0.0001)
    assert sl == pytest.approx(1.0970)
    assert tp == pytest.approx(1.1060)


def test_calc_sl_tp_sell_par_jpy():
    sl, tp = rm.calc_sl_tp("SELL", 150.00, 30, 60, 0.01)
    assert sl == pytest.approx(150.30)
    assert tp == pytest.approx(149.40)


def test_profit_pips_direccional():
    assert rm.profit_pips("BUY", 1.1000, 1.1025, 0.0001) == pytest.approx(25)
    assert rm.profit_pips("SELL", 1.1000, 1.1025, 0.0001) == pytest.approx(-25)


# ---------------------------------------------------------------------------
# Lote dinámico
# ---------------------------------------------------------------------------
def test_lote_dinamico_riesgo_1_pct():
    # $10.000, 1% de riesgo = $100. SL 30 pips a $10/pip → 0.33 lotes.
    lot = rm.calc_lot_size(10_000, 1.0, 30, 10.0)
    assert lot == 0.33
    # La pérdida potencial nunca supera el riesgo configurado.
    assert lot * 30 * 10.0 <= 100


def test_lote_respeta_minimo():
    assert rm.calc_lot_size(100, 0.5, 50, 10.0) == rm.MIN_LOT


def test_lote_parametros_invalidos():
    with pytest.raises(ValueError):
        rm.calc_lot_size(10_000, 1.0, 0, 10.0)


def test_pip_value_usd_quote():
    # EURUSD con cuenta USD: exactamente $10/pip por lote.
    assert rm.pip_value_per_lot("EURUSD", 0.0001, 1.10) == pytest.approx(10.0)


def test_pip_value_usd_base():
    # USDJPY con cuenta USD: 1000 JPY/pip → dividido por el precio.
    assert rm.pip_value_per_lot("USDJPY", 0.01, 150.0) == pytest.approx(1000 / 150)


# ---------------------------------------------------------------------------
# Cuentas Micro/Cent (contract_size ≠ 100.000)
# ---------------------------------------------------------------------------
def test_pip_value_cuenta_micro():
    # XM Micro: 1 lote = 1.000 unidades → EURUSD vale $0.10/pip por lote.
    value = rm.pip_value_per_lot("EURUSD", 0.0001, 1.10, contract_size=1_000)
    assert value == pytest.approx(0.10)


def test_lote_micro_con_cuenta_pequena():
    # $50 al 1% = $0.50 de riesgo. SL 30 pips a $0.10/pip (micro) →
    # raw 0.1667 lotes; con paso 0.1 (XM Micro) se trunca a 0.1.
    lot = rm.calc_lot_size(50, 1.0, 30, 0.10, volume_min=0.1, volume_step=0.1)
    assert lot == pytest.approx(0.1)
    # La pérdida potencial (0.1 × 30 × $0.10 = $0.30) respeta el riesgo.
    assert lot * 30 * 0.10 <= 0.50


def test_lote_micro_respeta_minimo_de_cuenta():
    # Cuenta minúscula: el mínimo de la cuenta manda aunque exceda el riesgo.
    lot = rm.calc_lot_size(5, 1.0, 30, 0.10, volume_min=0.1, volume_step=0.1)
    assert lot == pytest.approx(0.1)


def test_lote_trunca_al_paso_de_la_cuenta():
    # raw = 100 / (30 × 0.10) = 33.33; con paso 0.1 → 33.3 exacto.
    lot = rm.calc_lot_size(10_000, 1.0, 30, 0.10, volume_min=0.1, volume_step=0.1)
    assert lot == pytest.approx(33.3)


# ---------------------------------------------------------------------------
# Break-even y trailing
# ---------------------------------------------------------------------------
def test_break_even_no_aplica_antes_del_trigger():
    assert rm.compute_break_even_sl("BUY", 1.1000, 1.1010, 0.0001, 20) is None


def test_break_even_aplica_con_colchon():
    new_sl = rm.compute_break_even_sl("BUY", 1.1000, 1.1025, 0.0001, 20)
    assert new_sl == pytest.approx(1.1001)  # entrada + 1 pip de colchón


def test_break_even_sell():
    new_sl = rm.compute_break_even_sl("SELL", 1.1000, 1.0975, 0.0001, 20)
    assert new_sl == pytest.approx(1.0999)


def test_trailing_solo_mejora():
    # BUY con SL en 1.1000: precio 1.1030 y trailing 15 → SL 1.1015 (mejora).
    assert rm.compute_trailing_sl("BUY", 1.1030, 1.1000, 0.0001, 15) == pytest.approx(1.1015)
    # Si el candidato no mejora el SL vigente, no se mueve.
    assert rm.compute_trailing_sl("BUY", 1.1030, 1.1020, 0.0001, 15) is None


# ---------------------------------------------------------------------------
# Clasificación de cierres
# ---------------------------------------------------------------------------
def test_classify_close():
    # Salida pegada al TP (con slippage de 1 pip) → CLOSED_TP.
    assert rm.classify_close("BUY", 1.1059, 1.0970, 1.1060, 0.0001) == TradeStatus.CLOSED_TP
    # Salida pegada al SL → CLOSED_SL.
    assert rm.classify_close("BUY", 1.0971, 1.0970, 1.1060, 0.0001) == TradeStatus.CLOSED_SL
    # Salida lejos de ambos → manual.
    assert rm.classify_close("BUY", 1.1010, 1.0970, 1.1060, 0.0001) == TradeStatus.CLOSED_MANUAL
