"""Tests del optimizador de parámetros (grid search)."""

import json

import numpy as np
import pandas as pd
import pytest

from app.backtesting.backtester import BacktestParams
from app.backtesting.optimizer import (
    MAX_COMBOS,
    build_combos,
    create_job,
    get_job,
    run_job,
    user_has_running_job,
)

# Importar registra la estrategia de prueba BuyOnce en el registry.
from tests.test_backtesting import BuyOnceStrategy, _df_from_closes  # noqa: F401

BASE_RISK = {
    "stop_loss_pips": 30.0,
    "take_profit_pips": 60.0,
    "break_even_trigger_pips": 20.0,
}


# ---------------------------------------------------------------------------
# build_combos
# ---------------------------------------------------------------------------
def test_grid_producto_cartesiano():
    combos = build_combos(
        "scalping_bb_rsi", BASE_RISK,
        stop_loss_grid=[10, 12],
        take_profit_grid=[15, 18, 21],
        break_even_grid=[],
        strategy_param_grid={"rsi_oversold": [25, 30]},
    )
    assert len(combos) == 2 * 3 * 1 * 2  # SL × TP × BE(fijo) × rsi
    # El eje sin barrido queda fijo en el valor base.
    assert all(c["break_even_trigger_pips"] == 20.0 for c in combos)
    assert {c["strategy_params"]["rsi_oversold"] for c in combos} == {25, 30}


def test_grid_sin_ejes_devuelve_una_combinacion():
    combos = build_combos("ma_rsi_crossover", BASE_RISK, [], [], [], {})
    assert len(combos) == 1
    assert combos[0]["stop_loss_pips"] == 30.0


def test_grid_excede_el_tope():
    with pytest.raises(ValueError, match="combinaciones"):
        build_combos(
            "ma_rsi_crossover", BASE_RISK,
            stop_loss_grid=list(range(1, 12)),      # 11
            take_profit_grid=list(range(1, 12)),    # 11 → 121 > MAX_COMBOS
            break_even_grid=[], strategy_param_grid={},
        )
    assert MAX_COMBOS == 120


def test_grid_parametro_inexistente():
    with pytest.raises(ValueError, match="no es un parámetro"):
        build_combos(
            "scalping_bb_rsi", BASE_RISK, [], [], [],
            {"parametro_falso": [1, 2]},
        )


# ---------------------------------------------------------------------------
# run_job (barrido completo sobre datos deterministas)
# ---------------------------------------------------------------------------
def test_barrido_completo_ordena_por_beneficio():
    # Subida sostenida: con TP corto la operación gana; con SL corto y TP
    # inalcanzable... aquí todos ganan, pero con P/L distinto por TP.
    closes = [1.1000] * 6 + list(np.linspace(1.1005, 1.1100, 30))
    df = _df_from_closes(closes)

    base = BacktestParams(
        symbol="EURUSD", timeframe="M15", initial_balance=10_000,
        spread_pips=0.0, strategy_name="test_buy_once",
        stop_loss_pips=30, take_profit_pips=60,
        break_even_enabled=False,
    )
    combos = build_combos(
        "test_buy_once", BASE_RISK,
        stop_loss_grid=[30],
        take_profit_grid=[20, 40, 80],
        break_even_grid=[],
        strategy_param_grid={},
    )
    job = create_job(1, "test_buy_once", "EURUSD", "M15", len(combos))
    run_job(job, df, base, combos)

    assert job.status == "done"
    assert job.completed == 3
    snapshot = job.snapshot()
    assert len(snapshot["results"]) == 3
    # Ordenado por P/L neto descendente.
    profits = [r["metrics"]["net_profit"] for r in snapshot["results"]]
    assert profits == sorted(profits, reverse=True)
    # Cada fila conserva sus parámetros y métricas completas.
    best = snapshot["results"][0]
    assert {"stop_loss_pips", "take_profit_pips", "metrics"} <= set(best)
    assert "win_rate" in best["metrics"]


def test_barrido_sin_validacion_no_incluye_columna():
    closes = [1.1000] * 6 + list(np.linspace(1.1005, 1.1100, 30))
    df = _df_from_closes(closes)
    base = BacktestParams(
        symbol="EURUSD", timeframe="M15", initial_balance=10_000,
        spread_pips=0.0, strategy_name="test_buy_once",
        break_even_enabled=False,
    )
    combos = build_combos("test_buy_once", BASE_RISK, [30], [40], [], {})
    job = create_job(2, "test_buy_once", "EURUSD", "M15", len(combos))
    run_job(job, df, base, combos)  # sin df_valid

    row = job.snapshot()["results"][0]
    assert row["validation"] is None


def test_validacion_out_of_sample_simula_ambos_tramos():
    # Tramo de optimización: subida sostenida (el BUY gana por TP).
    # Tramo de validación: caída sostenida (el mismo BUY pierde por SL).
    # La validación debe delatar que el resultado no generaliza.
    train_closes = [1.1000] * 6 + list(np.linspace(1.1005, 1.1100, 30))
    valid_closes = [1.1000] * 6 + list(np.linspace(1.0995, 1.0900, 30))
    df_train = _df_from_closes(train_closes)
    df_valid = _df_from_closes(valid_closes)

    base = BacktestParams(
        symbol="EURUSD", timeframe="M15", initial_balance=10_000,
        spread_pips=0.0, strategy_name="test_buy_once",
        break_even_enabled=False,
    )
    combos = build_combos("test_buy_once", BASE_RISK, [30], [40, 80], [], {})
    job = create_job(
        3, "test_buy_once", "EURUSD", "M15", len(combos),
        validation_split=0.5, train_rows=len(df_train),
        valid_rows=len(df_valid), train_end=str(df_train.index[-1]),
    )
    run_job(job, df_train, base, combos, df_valid)

    snapshot = job.snapshot()
    assert snapshot["validation_split"] == 0.5
    assert snapshot["valid_rows"] == len(df_valid)

    for row in snapshot["results"]:
        assert row["validation"] is not None
        assert "net_profit" in row["validation"]
        # In-sample gana; out-of-sample pierde → sobreajuste visible.
        assert row["metrics"]["net_profit"] > 0
        assert row["validation"]["net_profit"] < 0


def test_barrido_completo_se_persiste_en_historial():
    """
    El historial de optimizaciones debe sobrevivir aunque el job en memoria
    se pierda (reinicio del servidor, o expulsión tras 5 corridas por
    usuario) — el mismo problema que ya resuelve BacktestRun para backtests
    individuales.
    """
    from app.db.database import SessionLocal, init_db
    from app.db.models import OptimizationRun

    init_db()
    closes = [1.1000] * 6 + list(np.linspace(1.1005, 1.1100, 30))
    df = _df_from_closes(closes)
    base = BacktestParams(
        symbol="EURUSD", timeframe="M15", initial_balance=10_000,
        spread_pips=0.0, strategy_name="test_buy_once",
        break_even_enabled=False,
    )
    combos = build_combos(
        "test_buy_once", BASE_RISK,
        stop_loss_grid=[30], take_profit_grid=[40, 80],
        break_even_grid=[], strategy_param_grid={},
    )
    job = create_job(4321, "test_buy_once", "EURUSD", "M15", len(combos))
    run_job(job, df, base, combos)

    with SessionLocal() as db:
        saved = (
            db.query(OptimizationRun)
            .filter_by(user_id=4321)
            .order_by(OptimizationRun.id.desc())
            .first()
        )
        assert saved is not None
        assert saved.total_combinations == 2
        assert saved.strategy_name == "test_buy_once"
        expected_best = job.snapshot()["results"][0]
        assert saved.best_net_profit == expected_best["metrics"]["net_profit"]
        assert saved.best_take_profit_pips == expected_best["take_profit_pips"]
        # El barrido completo (ambas filas) debe poder reconstruirse del JSON.
        stored_results = json.loads(saved.results_json)
        assert len(stored_results) == 2

        db.delete(saved)
        db.commit()


def test_job_fallido_no_genera_historial():
    """Un barrido con datos insuficientes no debe crear una fila espuria."""
    from app.db.database import SessionLocal
    from app.db.models import OptimizationRun

    df_insuficiente = _df_from_closes([1.1000] * 3)  # menos velas que min_bars
    base = BacktestParams(
        symbol="EURUSD", timeframe="M15", initial_balance=10_000,
        strategy_name="test_buy_once",
    )
    combos = build_combos("test_buy_once", BASE_RISK, [30], [60], [], {})
    job = create_job(4322, "test_buy_once", "EURUSD", "M15", len(combos))

    # Fuerza el error dentro de _simulate llamando run_job con datos que
    # provocan una excepción de estrategia (min_bars no cumplido en Backtester).
    from app.backtesting import optimizer as optimizer_module

    original_simulate = optimizer_module._simulate

    def _boom(*args, **kwargs):
        raise ValueError("datos insuficientes (forzado en test)")

    optimizer_module._simulate = _boom
    try:
        run_job(job, df_insuficiente, base, combos)
    finally:
        optimizer_module._simulate = original_simulate

    assert job.status == "error"
    with SessionLocal() as db:
        saved = db.query(OptimizationRun).filter_by(user_id=4322).first()
        assert saved is None


def test_registro_de_jobs_por_usuario():
    job = create_job(99, "ma_rsi_crossover", "EURUSD", "M15", total=1)
    assert get_job(job.id) is job
    assert user_has_running_job(99) is True
    job.status = "done"
    assert user_has_running_job(99) is False
