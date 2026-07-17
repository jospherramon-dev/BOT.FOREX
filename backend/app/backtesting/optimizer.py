"""
Módulo C+ — Optimizador de parámetros (grid search sobre el backtester).

Ejecuta el MISMO simulador del backtesting una vez por cada combinación de
parámetros (SL, TP, break-even, parámetros de estrategia como umbrales de
RSI) y devuelve una tabla comparativa de métricas.

El trabajo corre en segundo plano (threadpool) y expone su progreso, de
modo que el dashboard lo muestra "corriendo en automático" y va rellenando
la tabla a medida que terminan combinaciones.

Advertencia metodológica (sobreajuste): el mejor resultado de un barrido
está, por definición, ajustado al pasado. Antes de operar en real, valide
la combinación ganadora sobre un periodo distinto al del barrido
(out-of-sample) y en cuenta demo.
"""

from __future__ import annotations

import itertools
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
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> dict:
        """Vista JSON-serializable, con resultados ordenados por P/L neto."""
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
def run_job(
    job: OptimizationJob,
    df: pd.DataFrame,
    base: BacktestParams,
    combos: list[dict],
) -> None:
    """Corre cada combinación y acumula sus métricas en el job."""
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
                break_even_enabled=base.break_even_enabled,
                break_even_trigger_pips=combo["break_even_trigger_pips"],
                trailing_stop_enabled=base.trailing_stop_enabled,
                trailing_stop_pips=base.trailing_stop_pips,
            )
            result = Backtester(df, params).run()
            metrics = compute_metrics(
                [t.to_dict() for t in result.trades],
                [p["equity"] for p in result.equity_curve]
                or [base.initial_balance],
                base.initial_balance,
                base.timeframe,
            )
            with job._lock:
                job.results.append({**combo, "metrics": metrics})
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


# ---------------------------------------------------------------------------
# Registro de trabajos
# ---------------------------------------------------------------------------
def create_job(
    user_id: int, strategy_name: str, symbol: str, timeframe: str, total: int
) -> OptimizationJob:
    """Registra un job nuevo, expulsando los más antiguos del usuario."""
    job = OptimizationJob(
        id=uuid.uuid4().hex[:12],
        user_id=user_id,
        strategy_name=strategy_name,
        symbol=symbol,
        timeframe=timeframe,
        total=total,
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
