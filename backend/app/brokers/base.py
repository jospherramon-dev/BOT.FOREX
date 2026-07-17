"""
Interfaz abstracta de conexión con brokers (patrón Adapter).

Cada broker (MT5, OANDA, Pepperstone...) implementa esta interfaz. El motor
de trading (Módulo B) y el backtester (Módulo C) SOLO conocen esta clase,
nunca las librerías concretas — cambiar de broker es cambiar una línea en
la factory.

Todos los métodos son síncronos; el motor los ejecuta en un threadpool
para no bloquear el event-loop de FastAPI.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

import pandas as pd


# ---------------------------------------------------------------------------
# Objetos de valor que la interfaz intercambia (agnósticos del broker)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AccountInfo:
    balance: float
    equity: float
    margin_free: float
    currency: str
    leverage: int


@dataclass(frozen=True)
class TickPrice:
    symbol: str
    bid: float
    ask: float
    time: datetime

    @property
    def spread(self) -> float:
        return self.ask - self.bid


@dataclass(frozen=True)
class OrderResult:
    """Resultado normalizado de enviar/modificar/cerrar una orden."""

    success: bool
    ticket: str | None = None       # id de la posición en el broker
    executed_price: float | None = None
    message: str = ""


@dataclass(frozen=True)
class ClosedTradeInfo:
    """Datos reales de una posición ya cerrada en el broker."""

    exit_price: float | None
    profit: float | None                # realizado, en divisa de la cuenta


@dataclass(frozen=True)
class OpenPosition:
    ticket: str
    symbol: str
    direction: str                  # "BUY" | "SELL"
    lot_size: float
    entry_price: float
    stop_loss: float | None
    take_profit: float | None
    current_profit: float           # flotante, en divisa de la cuenta


# ---------------------------------------------------------------------------
# Contrato
# ---------------------------------------------------------------------------
class BrokerConnector(ABC):
    """Contrato que todo conector de broker debe cumplir."""

    name: str = "abstract"

    # --- Ciclo de vida --------------------------------------------------
    @abstractmethod
    def connect(self) -> bool:
        """Abre la sesión con el broker. Devuelve True si conectó."""

    @abstractmethod
    def disconnect(self) -> None:
        """Cierra la sesión y libera recursos."""

    @abstractmethod
    def is_connected(self) -> bool:
        """Indica si la sesión sigue viva."""

    # --- Cuenta y mercado -------------------------------------------------
    @abstractmethod
    def get_account_info(self) -> AccountInfo:
        """Balance, equity, margen libre, divisa y apalancamiento."""

    @abstractmethod
    def get_price(self, symbol: str) -> TickPrice:
        """Último tick (bid/ask) del símbolo."""

    @abstractmethod
    def get_historical_data(
        self,
        symbol: str,
        timeframe: str,
        date_from: datetime,
        date_to: datetime,
    ) -> pd.DataFrame:
        """
        Velas OHLCV como DataFrame indexado por tiempo con columnas:
        ['open', 'high', 'low', 'close', 'volume'].
        Formato que consumen estrategias y backtester.
        """

    # --- Órdenes ---------------------------------------------------------
    @abstractmethod
    def open_order(
        self,
        symbol: str,
        direction: str,             # "BUY" | "SELL"
        lot_size: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        comment: str = "BOT.FOREX",
    ) -> OrderResult:
        """Envía una orden a mercado con SL/TP opcionales (precios absolutos)."""

    @abstractmethod
    def modify_position(
        self,
        ticket: str,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> OrderResult:
        """Modifica SL/TP de una posición abierta (break-even, trailing)."""

    @abstractmethod
    def close_position(self, ticket: str) -> OrderResult:
        """Cierra una posición a mercado."""

    @abstractmethod
    def get_open_positions(self) -> list[OpenPosition]:
        """Posiciones abiertas actualmente en el broker."""

    def get_closed_trade_info(self, ticket: str) -> ClosedTradeInfo | None:
        """
        Precio de salida y beneficio realizado de una posición cerrada.
        Opcional: los conectores que no lo soporten devuelven None y el
        motor estima los valores con el último precio conocido.
        """
        return None
