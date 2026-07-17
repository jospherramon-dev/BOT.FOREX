"""Schemas Pydantic compartidos de trading (Módulos B/C los ampliarán)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import TradeDirection, TradeStatus


class TradeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    broker_ticket: str | None
    symbol: str
    direction: TradeDirection
    status: TradeStatus
    lot_size: float
    entry_price: float
    stop_loss: float | None
    take_profit: float | None
    exit_price: float | None
    profit: float | None
    profit_pips: float | None
    break_even_applied: bool
    strategy_name: str | None
    opened_at: datetime
    closed_at: datetime | None


class BotConfigIn(BaseModel):
    """Parámetros de riesgo editables desde el dashboard (Módulo B)."""

    strategy_name: str = "ma_rsi_crossover"
    # Sobreescrituras de parámetros de la estrategia (p. ej. desde el
    # optimizador). Vacío = usar los defaults de la estrategia.
    strategy_params: dict = Field(default_factory=dict)
    risk_per_trade_pct: float = Field(default=1.0, gt=0, le=10)
    stop_loss_pips: float = Field(default=30.0, gt=0)
    take_profit_pips: float = Field(default=60.0, gt=0)
    break_even_enabled: bool = True
    break_even_trigger_pips: float = Field(default=20.0, gt=0)
    trailing_stop_enabled: bool = False
    trailing_stop_pips: float = Field(default=15.0, gt=0)
    max_open_trades: int = Field(default=3, ge=1, le=20)


class BotConfigOut(BotConfigIn):
    model_config = ConfigDict(from_attributes=True)

    bot_enabled: bool
    telegram_enabled: bool
    updated_at: datetime
