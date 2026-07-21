"""
Módulo C+ — Optimizador de parámetros (grid search sobre el backtester).

Ejecuta el MISMO simulador del backtesting una vez por cada combinación de
parámetros (SL, TP, break-even, parámetros de estrategia como umbrales de
RSI) y devuelve una tabla comparativa de métricas.

El trabajo corre en segundo plano (threadpool) y expone su progreso, de
modo que el dashboard lo muestra "corriendo en automático" y va rellenando
la tabla a medida que terminan combinaciones.

Validación out-of-sample (antídoto contra el sobreajuste)
---------------------------------------------------------
Si `validation_split > 0`, el dataset se divide CRONOLÓGICAMENTE: el primer
tramo se usa para el barrido (in-sample) y el tramo final, que el barrido
nunca "ve" al elegir parámetros, se simula aparte con cada combinación
(out-of-sample). La tabla muestra ambos resultados: una combinación
ganadora in-sample que se derrumba en validación está sobreajustada y debe
descartarse. Aun así, valide la ganadora en cuenta demo antes de operar.
"""

from __future__ import annotations

import itertools
import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

from app.backtesting.backtester import Backtester, BacktestParams
from app.backtesting.metrics import compute_metrics
from app.strategies import get_strategy

logger = logging.getLogger(__name__)

#: Tope de combinaciones por barrido: protege al servidor de grids explosivos.
MAX_COMBOS = 120
#: Trabajos retenidos en memoria por usuario (los más recientes).
MAX_JOBS_PER_USER = 5


@dataclass
class OptimizationJob:
    """Estado en memoria de un barrido de optimización."""

    id: str
    user_id: int
    strategy_name: str
    symbol: str
    timeframe: str
    total: int
    completed: int = 0
    status: str = "running"          # running | done | error
    error: str = ""
    results: list[dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Metadatos del split out-of-sample (0/None = validación desactivada).
    validation_split: float = 0.0
    train_rows: int = 0
    valid_rows: int = 0
    train_end: str | None = None     # timestamp donde termina el tramo in-sample
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> dict:
        """
        Vista JSON-serializable. Los resultados se ordenan por P/L neto del
        tramo de OPTIMIZACIÓN (la selección siempre es in-sample; la columna
        de validación existe para juzgarla, no para elegir con ella).
        """
        with self._lock:
            results = sorted(
                self.results,
                key=lambda r: r["metrics"]["net_profit"],
                reverse=True,
            )
            return {
                "job_id": self.id,
                "status": self.status,
                "error": self.error,
                "strategy_name": self.strategy_name,
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "total": self.total,
                "completed": self.completed,
                "created_at": self.created_at.isoformat(),
                "validation_split": self.validation_split,
                "train_rows": self.train_rows,
                "valid_rows": self.valid_rows,
                "train_end": self.train_end,
                "results": results,
            }


_JOBS: dict[str, OptimizationJob] = {}


# ---------------------------------------------------------------------------
# Construcción del grid
# ---------------------------------------------------------------------------
def build_combos(
    strategy_name: str,
    base_risk: dict,
    stop_loss_grid: list[float],
    take_profit_grid: list[float],
    break_even_grid: list[float],
    strategy_param_grid: dict[str, list],
) -> list[dict]:
    """
    Producto cartesiano de los ejes de barrido. Un eje vacío queda fijo en
    su valor base (riesgo) o en el default de la estrategia.

    Raises:
        ValueError: si el grid supera MAX_COMBOS o un parámetro no existe.
    """
    defaults = get_strategy(strategy_name).params
    for param in strategy_param_grid:
        if param not in defaults:
            raise ValueError(
                f"'{param}' no es un parámetro de {strategy_name}. "
                f"Disponibles: {sorted(defaults)}"
            )

    sl_axis = stop_loss_grid or [base_risk["stop_loss_pips"]]
    tp_axis = take_profit_grid or [base_risk["take_profit_pips"]]
    be_axis = break_even_grid or [base_risk["break_even_trigger_pips"]]
    param_names = sorted(strategy_param_grid)
    param_axes = [strategy_param_grid[name] or [defaults[name]] for name in param_names]

    total = len(sl_axis) * len(tp_axis) * len(be_axis)
    for axis in param_axes:
        total *= len(axis)
    if total > MAX_COMBOS:
        raise ValueError(
            f"El grid genera {total} combinaciones (máximo {MAX_COMBOS}). "
            "Reduzca los valores por eje."
        )

    combos = []
    for sl, tp, be, *param_values in itertools.product(
        sl_axis, tp_axis, be_axis, *param_axes
    ):
        combos.append(
            {
                "stop_loss_pips": float(sl),
                "take_profit_pips": float(tp),
                "break_even_trigger_pips": float(be),
                "strategy_params": dict(zip(param_names, param_values)),
            }
        )
    return combos


# ---------------------------------------------------------------------------
# Ejecución del barrido (síncrona; el route la manda al threadpool)
# ---------------------------------------------------------------------------
def _simulate(df: pd.DataFrame, params: BacktestParams) -> dict:
    """Un backtest → métricas agregadas (sin curva, para aligerar la tabla)."""
    result = Backtester(df, params).run()
    return compute_metrics(
        [t.to_dict() for t in result.trades],
        [p["equity"] for p in result.equity_curve] or [params.initial_balance],
        params.initial_balance,
        params.timeframe,
    )


def run_job(
    job: OptimizationJob,
    df_train: pd.DataFrame,
    base: BacktestParams,
    combos: list[dict],
    df_valid: pd.DataFrame | None = None,
) -> None:
    """
    Corre cada combinación sobre el tramo de optimización y, si hay split,
    también sobre el tramo de validación out-of-sample (que jamás participa
    en la elección de parámetros).
    """
    try:
        for combo in combos:
            params = BacktestParams(
                symbol=base.symbol,
                timeframe=base.timeframe,
                initial_balance=base.initial_balance,
                spread_pips=base.spread_pips,
                strategy_name=base.strategy_name,
                strategy_params=combo["strategy_params"],
                risk_per_trade_pct=base.risk_per_trade_pct,
                stop_loss_pips=combo["stop_loss_pips"],
                take_profit_pips=combo["take_profit_pips"],
                atr_sl_enabled=base.atr_sl_enabled,
                atr_period=base.atr_period,
                atr_sl_multiplier=base.atr_sl_multiplier,
                atr_tp_ratio=base.atr_tp_ratio,
                atr_sl_min_pips=base.atr_sl_min_pips,
                break_even_enabled=base.break_even_enabled,
                break_even_trigger_pips=combo["break_even_trigger_pips"],
                trailing_stop_enabled=base.trailing_stop_enabled,
                trailing_stop_pips=base.trailing_stop_pips,
                max_drawdown_pct=base.max_drawdown_pct,
                drawdown_cooldown_bars=base.drawdown_cooldown_bars,
            )
            metrics = _simulate(df_train, params)
            validation = _simulate(df_valid, params) if df_valid is not None else None
            with job._lock:
                job.results.append(
                    {**combo, "metrics": metrics, "validation": validation}
                )
                job.completed += 1

        job.status = "done"
        logger.info(
            "Optimización %s completada: %s combinaciones (%s)",
            job.id, job.total, job.strategy_name,
        )
    except Exception as exc:  # noqa: BLE001 — el estado de error viaja al front
        job.status = "error"
        job.error = str(exc)
        logger.exception("Optimización %s falló", job.id)
    finally:
        _persist_completed_job(job)


def _persist_completed_job(job: OptimizationJob) -> None:
    """
    Guarda el barrido en `optimization_runs` para que sobreviva al
    reinicio del servidor y a la expulsión de la caché en memoria (que
    solo retiene los 5 jobs más recientes por usuario). Un job fallido o
    sin resultados no genera historial — igual que un backtest que nunca
    corrió no aparece en "Simulaciones anteriores".
    """
    if job.status != "done" or not job.results:
        return

    # Import diferido: evita un ciclo de import entre optimizer y db.models.
    from app.db.database import SessionLocal
    from app.db.models import OptimizationRun

    snapshot = job.snapshot()
    best = snapshot["results"][0]  # ya viene ordenado por P/L de optimización
    best_validation = best.get("validation") or {}

    with SessionLocal() as db:
        db.add(
            OptimizationRun(
                user_id=job.user_id,
                strategy_name=job.strategy_name,
                symbol=job.symbol,
                timeframe=job.timeframe,
                total_combinations=job.total,
                validation_split=job.validation_split,
                train_rows=job.train_rows,
                valid_rows=job.valid_rows,
                train_end=job.train_end,
                best_stop_loss_pips=best["stop_loss_pips"],
                best_take_profit_pips=best["take_profit_pips"],
                best_break_even_trigger_pips=best["break_even_trigger_pips"],
                best_net_profit=best["metrics"]["net_profit"],
                best_profit_factor=best["metrics"]["profit_factor"],
                best_validation_net_profit=best_validation.get("net_profit"),
                best_validation_profit_factor=best_validation.get("profit_factor"),
                results_json=json.dumps(snapshot["results"]),
            )
        )
        db.commit()
    logger.info(
        "Optimización %s persistida en el historial (usuario %s)",
        job.id, job.user_id,
    )


# ---------------------------------------------------------------------------
# Registro de trabajos
# ---------------------------------------------------------------------------
def create_job(
    user_id: int,
    strategy_name: str,
    symbol: str,
    timeframe: str,
    total: int,
    validation_split: float = 0.0,
    train_rows: int = 0,
    valid_rows: int = 0,
    train_end: str | None = None,
) -> OptimizationJob:
    """Registra un job nuevo, expulsando los más antiguos del usuario."""
    job = OptimizationJob(
        id=uuid.uuid4().hex[:12],
        user_id=user_id,
        strategy_name=strategy_name,
        symbol=symbol,
        timeframe=timeframe,
        total=total,
        validation_split=validation_split,
        train_rows=train_rows,
        valid_rows=valid_rows,
        train_end=train_end,
    )
    user_jobs = sorted(
        (j for j in _JOBS.values() if j.user_id == user_id),
        key=lambda j: j.created_at,
    )
    for old in user_jobs[: max(0, len(user_jobs) - (MAX_JOBS_PER_USER - 1))]:
        _JOBS.pop(old.id, None)
    _JOBS[job.id] = job
    return job


def get_job(job_id: str) -> OptimizationJob | None:
    return _JOBS.get(job_id)


def user_has_running_job(user_id: int) -> bool:
    return any(j.user_id == user_id and j.status == "running" for j in _JOBS.values())
