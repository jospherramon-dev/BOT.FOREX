"""
Contrato base de estrategias de trading (arquitectura plugin).

Una estrategia es una clase PURA: recibe un DataFrame OHLCV y devuelve una
señal. NO sabe nada de brokers, lotes, SL/TP ni riesgo — eso es trabajo del
motor (Módulo B) y del backtester (Módulo C), que consumen la misma señal.
Gracias a esta separación, cualquier estrategia funciona idéntica en vivo
y en backtest sin cambiar una línea.

Para crear una estrategia nueva:

1. Crear un archivo en `app/strategies/` (ej. `mi_estrategia.py`).
2. Heredar de `BaseStrategy` e implementar `calculate_signal()`.
3. Registrarla en `STRATEGY_REGISTRY` (app/strategies/__init__.py).
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd


class SignalType(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"   # no operar / mantener


@dataclass(frozen=True)
class Signal:
    """
    Señal emitida por una estrategia para la última vela cerrada.

    `metadata` transporta valores de indicadores para logs, notificaciones
    Telegram y depuración visual en el dashboard.
    """

    type: SignalType
    symbol: str
    reason: str = ""
    metadata: dict = field(default_factory=dict)


class BaseStrategy(ABC):
    """Clase base de la que heredan todas las estrategias."""

    #: Identificador único usado en BotConfig.strategy_name y el registro.
    name: str = "base"
    #: Descripción mostrada en el selector de estrategias del dashboard.
    description: str = ""
    #: Nº mínimo de velas que necesita para calcular sus indicadores.
    min_bars: int = 50

    def __init__(self, params: dict | None = None) -> None:
        """
        Args:
            params: sobreescrituras de parámetros; se fusionan con
                `default_params()` para permitir configuración parcial.
        """
        self.params = {**self.default_params(), **(params or {})}

    @classmethod
    def default_params(cls) -> dict:
        """Parámetros por defecto de la estrategia (editables en el dashboard)."""
        return {}

    @abstractmethod
    def calculate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        """
        Evalúa la estrategia sobre las velas dadas.

        Args:
            df: DataFrame OHLCV indexado por tiempo, con columnas
                ['open', 'high', 'low', 'close', 'volume']. La ÚLTIMA fila
                es la vela cerrada más reciente.
            symbol: par evaluado (ej. "EURUSD").

        Returns:
            Signal con BUY / SELL / HOLD para la última vela.
        """

    def validate_data(self, df: pd.DataFrame) -> None:
        """Comprueba que hay velas suficientes y columnas correctas."""
        required = {"open", "high", "low", "close"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Faltan columnas OHLC en los datos: {missing}")
        if len(df) < self.min_bars:
            raise ValueError(
                f"'{self.name}' necesita ≥{self.min_bars} velas; recibió {len(df)}."
            )
