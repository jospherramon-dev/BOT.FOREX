"""
Módulo C — Rutas de backtesting.

POST   /backtest/datasets            : sube un CSV de velas históricas.
GET    /backtest/datasets            : lista los datasets del usuario.
DELETE /backtest/datasets/{filename} : elimina un dataset.
POST   /backtest/run                 : ejecuta una simulación y la persiste.
GET    /backtest/runs                : historial de simulaciones.
GET    /backtest/runs/{run_id}       : detalle (incluye curva de equity).
"""

import asyncio
import json
import logging
import re

from fastapi import APIRouter, HTTPException, UploadFile, status
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, DBSession
from app.backtesting.backtester import Backtester, BacktestParams
from app.backtesting.data_loader import (
    MAX_UPLOAD_BYTES,
    dataset_info,
    load_csv,
    user_dataset_dir,
)
from app.backtesting import optimizer
from app.backtesting.metrics import compute_metrics, downsample_equity
from app.db.models import BacktestRun
from app.schemas.backtest import (
    BacktestRequest,
    BacktestResultOut,
    BacktestRunSummary,
    DatasetInfo,
    OptimizationRequest,
    OptimizationStarted,
)
from app.strategies import STRATEGY_REGISTRY

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backtest", tags=["Backtesting"])

_SAFE_FILENAME = re.compile(r"^[\w\-. ]+\.csv$", re.IGNORECASE)


def _safe_dataset_path(user_id: int, filename: str):
    """Valida el nombre y resuelve la ruta DENTRO del directorio del usuario."""
    if not _SAFE_FILENAME.match(filename) or ".." in filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nombre de archivo inválido (solo CSV, sin rutas)",
        )
    return user_dataset_dir(user_id) / filename


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------
@router.post("/datasets", response_model=DatasetInfo,
             status_code=status.HTTP_201_CREATED)
async def upload_dataset(
    file: UploadFile, current_user: CurrentUser
) -> dict:
    """Sube un CSV de velas; se valida y normaliza antes de aceptarlo."""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Solo se aceptan archivos .csv",
        )
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Máximo {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
        )

    path = _safe_dataset_path(current_user.id, file.filename)
    path.write_bytes(content)

    try:
        info = await run_in_threadpool(dataset_info, path)
    except ValueError as exc:
        path.unlink(missing_ok=True)  # no conservar archivos inválidos
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"CSV inválido: {exc}",
        ) from exc

    logger.info("Dataset subido: %s (%s velas)", file.filename, info["rows"])
    return info


@router.get("/datasets", response_model=list[DatasetInfo])
async def list_datasets(current_user: CurrentUser) -> list[dict]:
    infos = []
    for path in sorted(user_dataset_dir(current_user.id).glob("*.csv")):
        try:
            infos.append(await run_in_threadpool(dataset_info, path))
        except ValueError:
            continue  # archivo corrupto: se omite del listado
    return infos


@router.delete("/datasets/{filename}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(filename: str, current_user: CurrentUser) -> None:
    path = _safe_dataset_path(current_user.id, filename)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Dataset no encontrado")
    path.unlink()


# ---------------------------------------------------------------------------
# Ejecución
# ---------------------------------------------------------------------------
@router.post("/run", response_model=BacktestResultOut)
async def run_backtest(
    payload: BacktestRequest, db: DBSession, current_user: CurrentUser
) -> BacktestResultOut:
    """
    Ejecuta la simulación en el threadpool (CPU-bound) y persiste el
    resultado para el historial del dashboard.
    """
    if payload.strategy_name not in STRATEGY_REGISTRY:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Estrategia desconocida. Disponibles: {sorted(STRATEGY_REGISTRY)}",
        )

    path = _safe_dataset_path(current_user.id, payload.dataset)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Dataset no encontrado")

    def _simulate():
        df = load_csv(path)
        # Recorte por rango de fechas (si se indicó).
        if payload.date_from is not None:
            df = df[df.index >= payload.date_from.replace(tzinfo=None)]
        if payload.date_to is not None:
            df = df[df.index <= payload.date_to.replace(tzinfo=None)]

        params = BacktestParams(
            symbol=payload.symbol,
            timeframe=payload.timeframe,
            initial_balance=payload.initial_balance,
            spread_pips=payload.spread_pips,
            strategy_name=payload.strategy_name,
            strategy_params=payload.strategy_params,
            risk_per_trade_pct=payload.risk_per_trade_pct,
            stop_loss_pips=payload.stop_loss_pips,
            take_profit_pips=payload.take_profit_pips,
            break_even_enabled=payload.break_even_enabled,
            break_even_trigger_pips=payload.break_even_trigger_pips,
            trailing_stop_enabled=payload.trailing_stop_enabled,
            trailing_stop_pips=payload.trailing_stop_pips,
        )
        backtester = Backtester(df, params)
        if len(df) <= backtester.strategy.min_bars:
            raise ValueError(
                f"Datos insuficientes: la estrategia necesita más de "
                f"{backtester.strategy.min_bars} velas y hay {len(df)}."
            )
        return df, backtester.run()

    try:
        df, result = await run_in_threadpool(_simulate)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    equity_values = [pt["equity"] for pt in result.equity_curve]
    metrics = compute_metrics(
        [t.to_dict() for t in result.trades],
        equity_values or [payload.initial_balance],
        payload.initial_balance,
        payload.timeframe,
    )
    equity_curve = downsample_equity(result.equity_curve)

    run = BacktestRun(
        user_id=current_user.id,
        strategy_name=payload.strategy_name,
        symbol=payload.symbol,
        timeframe=payload.timeframe,
        date_from=df.index[0].to_pydatetime(),
        date_to=df.index[-1].to_pydatetime(),
        initial_balance=payload.initial_balance,
        final_balance=metrics["final_balance"],
        total_trades=metrics["total_trades"],
        win_rate=metrics["win_rate"],
        profit_factor=metrics["profit_factor"],
        max_drawdown_pct=metrics["max_drawdown_pct"],
        sharpe_ratio=metrics["sharpe_ratio"],
        equity_curve_json=json.dumps(equity_curve),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    logger.info(
        "Backtest #%s: %s en %s → %s trades, win rate %.1f%%, PF %.2f",
        run.id, payload.strategy_name, payload.symbol,
        metrics["total_trades"], metrics["win_rate"], metrics["profit_factor"],
    )
    return BacktestResultOut(
        run_id=run.id,
        metrics=metrics,
        equity_curve=equity_curve,
        trades=[t.to_dict() for t in result.trades],
    )


# ---------------------------------------------------------------------------
# Optimización de parámetros (grid search en segundo plano)
# ---------------------------------------------------------------------------
@router.post("/optimize", response_model=OptimizationStarted)
async def start_optimization(
    payload: OptimizationRequest, current_user: CurrentUser
) -> OptimizationStarted:
    """
    Lanza un barrido de parámetros. Devuelve un `job_id` para consultar el
    progreso con GET /backtest/optimize/{job_id}; la tabla del dashboard se
    va rellenando a medida que terminan combinaciones.
    """
    if payload.strategy_name not in STRATEGY_REGISTRY:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Estrategia desconocida. Disponibles: {sorted(STRATEGY_REGISTRY)}",
        )
    if optimizer.user_has_running_job(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya hay una optimización en curso; espere a que termine.",
        )

    path = _safe_dataset_path(current_user.id, payload.dataset)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Dataset no encontrado")

    base_risk = {
        "stop_loss_pips": payload.stop_loss_pips,
        "take_profit_pips": payload.take_profit_pips,
        "break_even_trigger_pips": payload.break_even_trigger_pips,
    }
    try:
        combos = optimizer.build_combos(
            payload.strategy_name,
            base_risk,
            payload.stop_loss_grid,
            payload.take_profit_grid,
            payload.break_even_grid,
            payload.strategy_param_grid,
        )
        df = await run_in_threadpool(load_csv, path)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    if payload.date_from is not None:
        df = df[df.index >= payload.date_from.replace(tzinfo=None)]
    if payload.date_to is not None:
        df = df[df.index <= payload.date_to.replace(tzinfo=None)]

    base_params = BacktestParams(
        symbol=payload.symbol,
        timeframe=payload.timeframe,
        initial_balance=payload.initial_balance,
        spread_pips=payload.spread_pips,
        strategy_name=payload.strategy_name,
        risk_per_trade_pct=payload.risk_per_trade_pct,
        stop_loss_pips=payload.stop_loss_pips,
        take_profit_pips=payload.take_profit_pips,
        break_even_enabled=payload.break_even_enabled,
        break_even_trigger_pips=payload.break_even_trigger_pips,
        trailing_stop_enabled=payload.trailing_stop_enabled,
        trailing_stop_pips=payload.trailing_stop_pips,
    )

    job = optimizer.create_job(
        current_user.id, payload.strategy_name, payload.symbol,
        payload.timeframe, len(combos),
    )
    # El barrido corre en el threadpool sin bloquear el event-loop; el
    # cliente sigue el progreso por polling del job.
    asyncio.get_running_loop().run_in_executor(
        None, optimizer.run_job, job, df, base_params, combos
    )
    logger.info(
        "Optimización %s lanzada: %s combinaciones de %s en %s",
        job.id, len(combos), payload.strategy_name, payload.dataset,
    )
    return OptimizationStarted(job_id=job.id, total_combinations=len(combos))


@router.get("/optimize/{job_id}")
def optimization_status(job_id: str, current_user: CurrentUser) -> dict:
    """Progreso y resultados (ordenados por P/L neto) de un barrido."""
    job = optimizer.get_job(job_id)
    if job is None or job.user_id != current_user.id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Optimización no encontrada"
        )
    return job.snapshot()


# ---------------------------------------------------------------------------
# Historial
# ---------------------------------------------------------------------------
@router.get("/runs", response_model=list[BacktestRunSummary])
def list_runs(
    db: DBSession, current_user: CurrentUser, limit: int = 20, offset: int = 0
) -> list[BacktestRun]:
    return list(
        db.scalars(
            select(BacktestRun)
            .where(BacktestRun.user_id == current_user.id)
            .order_by(BacktestRun.created_at.desc())
            .limit(min(limit, 100))
            .offset(offset)
        )
    )


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: DBSession, current_user: CurrentUser) -> dict:
    run = db.get(BacktestRun, run_id)
    if run is None or run.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Backtest no encontrado")
    summary = BacktestRunSummary.model_validate(run).model_dump()
    summary["equity_curve"] = json.loads(run.equity_curve_json)
    return summary
