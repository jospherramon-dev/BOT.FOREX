"""
Modelos ORM de BOT.FOREX (SQLAlchemy 2.0, sintaxis Mapped/mapped_column).

Tablas:
- users               : usuarios del dashboard (login JWT).
- broker_credentials  : credenciales de broker CIFRADAS (Fernet).
- assets              : pares de divisas que el bot monitorea (watchlist).
- bot_configs         : parámetros de riesgo/estrategia por usuario.
- trades              : historial de operaciones (vivas y cerradas).
- backtest_runs       : resultados de simulaciones (Módulo C).
- optimization_runs   : historial permanente de barridos de parámetros (Módulo C+).
- system_logs         : eventos persistidos para auditoría.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def utcnow() -> datetime:
    """Timestamp UTC consciente de zona horaria (default de columnas)."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Enumeraciones de dominio
# ---------------------------------------------------------------------------
class BrokerType(str, enum.Enum):
    MT5 = "MT5"
    OANDA = "OANDA"
    PEPPERSTONE = "PEPPERSTONE"  # Pepperstone expone cTrader/MT5; vía MT5 API


class TradeDirection(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class TradeStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED_TP = "CLOSED_TP"          # cerrada por Take Profit
    CLOSED_SL = "CLOSED_SL"          # cerrada por Stop Loss
    CLOSED_MANUAL = "CLOSED_MANUAL"  # cierre manual desde el dashboard
    CLOSED_TRAILING = "CLOSED_TRAILING"


# ---------------------------------------------------------------------------
# Usuarios y seguridad
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    credentials: Mapped[list["BrokerCredential"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    assets: Mapped[list["Asset"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    config: Mapped["BotConfig | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    trades: Mapped[list["Trade"]] = relationship(back_populates="user")


class BrokerCredential(Base):
    """
    Credenciales de conexión al broker.

    Los campos `encrypted_*` se almacenan cifrados con Fernet
    (app/core/security.py) y solo se descifran en memoria al conectar.
    """

    __tablename__ = "broker_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    broker_type: Mapped[BrokerType] = mapped_column(Enum(BrokerType))
    label: Mapped[str] = mapped_column(String(100), default="Mi cuenta")

    # MT5: login numérico + password + servidor. OANDA: api_key + account_id.
    encrypted_login: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_password: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    server: Mapped[str | None] = mapped_column(String(120), nullable=True)
    account_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # MT5: ruta al terminal.exe de este broker (opcional). Necesaria si hay
    # varios terminales MT5 instalados en la PC (uno por broker).
    terminal_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship(back_populates="credentials")


# ---------------------------------------------------------------------------
# Activos y configuración del bot
# ---------------------------------------------------------------------------
class Asset(Base):
    """Par de divisas monitoreado por el bot (watchlist del usuario)."""

    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("user_id", "symbol", name="uq_user_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(12))          # ej. "EURUSD"
    timeframe: Mapped[str] = mapped_column(String(8), default="M15")
    pip_size: Mapped[float] = mapped_column(Float, default=0.0001)  # JPY: 0.01
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship(back_populates="assets")


class BotConfig(Base):
    """
    Parámetros de riesgo y estrategia (Módulo B). Editables en caliente
    desde el dashboard; el motor los relee en cada ciclo.
    """

    __tablename__ = "bot_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)

    strategy_name: Mapped[str] = mapped_column(String(60), default="ma_rsi_crossover")
    # Sobreescrituras de parámetros de la estrategia (JSON), p. ej. umbrales
    # de RSI aplicados desde el optimizador. Vacío = defaults de la estrategia.
    strategy_params_json: Mapped[str] = mapped_column(Text, default="{}")
    risk_per_trade_pct: Mapped[float] = mapped_column(Float, default=1.0)   # % de cuenta
    stop_loss_pips: Mapped[float] = mapped_column(Float, default=30.0)
    take_profit_pips: Mapped[float] = mapped_column(Float, default=60.0)
    # SL/TP adaptativos por volatilidad (Método B del manual EMA+ADX). Con
    # atr_sl_enabled=True el SL = ATR(atr_period) × atr_sl_multiplier (nunca
    # por debajo de atr_sl_min_pips) y el TP = SL × atr_tp_ratio (R:R). Con
    # False se usan los pips fijos de arriba. 0/False = comportamiento clásico.
    atr_sl_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    atr_period: Mapped[int] = mapped_column(Integer, default=14)
    atr_sl_multiplier: Mapped[float] = mapped_column(Float, default=1.5)
    atr_tp_ratio: Mapped[float] = mapped_column(Float, default=2.0)
    atr_sl_min_pips: Mapped[float] = mapped_column(Float, default=5.0)
    break_even_trigger_pips: Mapped[float] = mapped_column(Float, default=20.0)
    break_even_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    trailing_stop_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    trailing_stop_pips: Mapped[float] = mapped_column(Float, default=15.0)
    max_open_trades: Mapped[int] = mapped_column(Integer, default=3)
    # Freno de drawdown en vivo: si la equity cae este % desde su máximo, el
    # motor deja de abrir operaciones nuevas durante drawdown_cooldown_hours.
    # 0 = desactivado.
    max_drawdown_pct: Mapped[float] = mapped_column(Float, default=0.0)
    drawdown_cooldown_hours: Mapped[float] = mapped_column(Float, default=48.0)
    bot_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    # Notificaciones Telegram (Módulo D) — token cifrado con Fernet.
    telegram_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    encrypted_telegram_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped["User"] = relationship(back_populates="config")

    @property
    def strategy_params(self) -> dict:
        """Parámetros de estrategia deserializados (para API y motor)."""
        import json

        try:
            return json.loads(self.strategy_params_json or "{}")
        except ValueError:
            return {}


# ---------------------------------------------------------------------------
# Operaciones e historial
# ---------------------------------------------------------------------------
class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    broker_ticket: Mapped[str | None] = mapped_column(String(64), nullable=True)

    symbol: Mapped[str] = mapped_column(String(12), index=True)
    direction: Mapped[TradeDirection] = mapped_column(Enum(TradeDirection))
    status: Mapped[TradeStatus] = mapped_column(
        Enum(TradeStatus), default=TradeStatus.OPEN, index=True
    )

    lot_size: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    profit: Mapped[float | None] = mapped_column(Float, nullable=True)  # divisa cuenta
    profit_pips: Mapped[float | None] = mapped_column(Float, nullable=True)
    break_even_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    strategy_name: Mapped[str | None] = mapped_column(String(60), nullable=True)

    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User"] = relationship(back_populates="trades")


class BacktestRun(Base):
    """Resultado agregado de una simulación (Módulo C)."""

    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    strategy_name: Mapped[str] = mapped_column(String(60))
    symbol: Mapped[str] = mapped_column(String(12))
    timeframe: Mapped[str] = mapped_column(String(8))
    date_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    date_to: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    initial_balance: Mapped[float] = mapped_column(Float)
    final_balance: Mapped[float] = mapped_column(Float)
    total_trades: Mapped[int] = mapped_column(Integer)
    win_rate: Mapped[float] = mapped_column(Float)          # 0-100
    profit_factor: Mapped[float] = mapped_column(Float)
    max_drawdown_pct: Mapped[float] = mapped_column(Float)
    sharpe_ratio: Mapped[float] = mapped_column(Float)

    # Serie de equity serializada en JSON (para pintar la curva en el front).
    equity_curve_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OptimizationRun(Base):
    """
    Historial PERMANENTE de un barrido de optimización (Módulo C+).

    A diferencia del job en memoria (`app/backtesting/optimizer.py`, que se
    pierde al reiniciar el servidor o al superar 5 corridas por usuario),
    este registro sobrevive indefinidamente — igual que `BacktestRun` para
    backtests individuales. Se crea una vez que el barrido termina.
    """

    __tablename__ = "optimization_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    strategy_name: Mapped[str] = mapped_column(String(60))
    symbol: Mapped[str] = mapped_column(String(12))
    timeframe: Mapped[str] = mapped_column(String(8))

    total_combinations: Mapped[int] = mapped_column(Integer)
    validation_split: Mapped[float] = mapped_column(Float, default=0.0)
    train_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    train_end: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Resumen de la mejor combinación (evita parsear el JSON completo solo
    # para listar el historial).
    best_stop_loss_pips: Mapped[float] = mapped_column(Float)
    best_take_profit_pips: Mapped[float] = mapped_column(Float)
    best_break_even_trigger_pips: Mapped[float] = mapped_column(Float)
    best_net_profit: Mapped[float] = mapped_column(Float)
    best_profit_factor: Mapped[float] = mapped_column(Float)
    best_validation_net_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_validation_profit_factor: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Barrido completo (todas las combinaciones con sus métricas y, si hubo
    # validación out-of-sample, también esas métricas por fila).
    results_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SystemLog(Base):
    """Eventos persistidos para auditoría (aperturas, cierres, errores)."""

    __tablename__ = "system_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    level: Mapped[str] = mapped_column(String(10), default="INFO")
    source: Mapped[str] = mapped_column(String(40), default="system")
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
