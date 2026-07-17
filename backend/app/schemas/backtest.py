"""Schemas Pydantic del Módulo C: backtesting."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DatasetInfo(BaseModel):
    """Metadatos de un CSV subido, para el listado del dashboard."""

    filename: str
    rows: int
    date_from: datetime
    date_to: datetime
    size_bytes: int


class BacktestRequest(BaseModel):
    """Petición de simulación desde la sección Backtest del dashboard."""

    dataset: str = Field(description="Nombre del CSV subido previamente")
    symbol: str = Field(min_length=6, max_length=12, pattern=r"^[A-Z]{6,12}$")
    timeframe: str = Field(default="M15", pattern=r"^(M1|M5|M15|M30|H1|H4|D1)$")
    date_from: datetime | None = None       # None = desde el inicio del dataset
    date_to: datetime | None = None         # None = hasta el final

    initial_balance: float = Field(default=10_000, gt=0)
    spread_pips: float = Field(default=1.0, ge=0)

    strategy_name: str = "ma_rsi_crossover"
    strategy_params: dict = Field(default_factory=dict)

    risk_per_trade_pct: float = Field(default=1.0, gt=0, le=10)
    stop_loss_pips: float = Field(default=30.0, gt=0)
    take_profit_pips: float = Field(default=60.0, gt=0)
    break_even_enabled: bool = True
    break_even_trigger_pips: float = Field(default=20.0, gt=0)
    trailing_stop_enabled: bool = False
    trailing_stop_pips: float = Field(default=15.0, gt=0)


class OptimizationRequest(BaseModel):
    """
    Barrido de parámetros sobre un dataset. Cada `*_grid` es la lista de
    valores a probar en ese eje; una lista vacía deja el eje fijo en su
    valor base. `strategy_param_grid` barre parámetros de la estrategia
    (p. ej. {"rsi_oversold": [20, 25, 30]}).
    """

    dataset: str
    symbol: str = Field(min_length=6, max_length=12, pattern=r"^[A-Z]{6,12}$")
    timeframe: str = Field(default="M15", pattern=r"^(M1|M5|M15|M30|H1|H4|D1)$")
    date_from: datetime | None = None
    date_to: datetime | None = None

    initial_balance: float = Field(default=10_000, gt=0)
    spread_pips: float = Field(default=1.0, ge=0)
    strategy_name: str = "ma_rsi_crossover"

    # Valores base (se usan en los ejes sin barrido).
    risk_per_trade_pct: float = Field(default=1.0, gt=0, le=10)
    stop_loss_pips: float = Field(default=30.0, gt=0)
    take_profit_pips: float = Field(default=60.0, gt=0)
    break_even_enabled: bool = True
    break_even_trigger_pips: float = Field(default=20.0, gt=0)
    trailing_stop_enabled: bool = False
    trailing_stop_pips: float = Field(default=15.0, gt=0)

    # Ejes de barrido.
    stop_loss_grid: list[float] = Field(default_factory=list)
    take_profit_grid: list[float] = Field(default_factory=list)
    break_even_grid: list[float] = Field(default_factory=list)
    strategy_param_grid: dict[str, list] = Field(default_factory=dict)


class OptimizationStarted(BaseModel):
    job_id: str
    total_combinations: int


class BacktestRunSummary(BaseModel):
    """Fila del historial de backtests."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    strategy_name: str
    symbol: str
    timeframe: str
    date_from: datetime
    date_to: datetime
    initial_balance: float
    final_balance: float
    total_trades: int
    win_rate: float
    profit_factor: float
    max_drawdown_pct: float
    sharpe_ratio: float
    created_at: datetime


class BacktestResultOut(BaseModel):
    """Resultado completo de una simulación (respuesta de /backtest/run)."""

    run_id: int
    metrics: dict
    equity_curve: list[dict]
    trades: list[dict]
