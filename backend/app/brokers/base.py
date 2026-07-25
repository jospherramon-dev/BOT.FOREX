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
class SymbolSpecs:
    """
    Especificaciones REALES de trading para un símbolo en ESTA cuenta.

    Existen porque el tamaño de 1 "lote" no es universal: en una cuenta
    estándar 1 lote = 100.000 unidades, pero en cuentas Micro/Cent (muy
    comunes para arrancar con poco capital, ej. XM Micro, Exness Cent)
    puede ser 1.000 unidades o menos. Si el motor asumiera siempre el
    estándar, el tamaño de lote calculado por `risk_manager.calc_lot_size`
    quedaría mal por un factor de 10x-100x en esas cuentas.
    """

    contract_size: float   # unidades de la divisa base por 1.0 lote
    volume_min: float      # lote mínimo operable
    volume_step: float     # incremento mínimo entre lotes válidos


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
    #: Detalle del último fallo de connect() (código/mensaje real del
    #: broker). Los conectores lo rellenan; por defecto vacío. Permite que
    #: el botón "Probar Conexión" muestre la causa exacta en vez de un
    #: mensaje genérico.
    last_error: str = ""

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

    def get_symbol_specs(self, symbol: str) -> SymbolSpecs:
        """
        Tamaño de contrato y lote mínimo/paso REALES de esta cuenta para
        el símbolo dado. Los conectores que no puedan consultarlo (u
        operen sobre un modelo sin lotes, como OANDA) devuelven el
        estándar de la industria: 100.000 unidades, lote mínimo 0.01.
        """
        return SymbolSpecs(contract_size=100_000.0, volume_min=0.01, volume_step=0.01)
