"""
Registro de estrategias disponibles.

El motor de trading y el backtester instancian estrategias por nombre a
través de `get_strategy()`. Para añadir una nueva, importarla aquí y
sumarla al registro.
"""

from app.strategies.base_strategy import BaseStrategy, Signal, SignalType
from app.strategies.ma_rsi_crossover import MaRsiCrossoverStrategy
from app.strategies.scalping_bb_rsi import ScalpingBbRsiStrategy
from app.strategies.trend_ema_pullback import TrendEmaPullbackStrategy

STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    MaRsiCrossoverStrategy.name: MaRsiCrossoverStrategy,
    ScalpingBbRsiStrategy.name: ScalpingBbRsiStrategy,
    TrendEmaPullbackStrategy.name: TrendEmaPullbackStrategy,
}


def get_strategy(name: str, params: dict | None = None) -> BaseStrategy:
    """Instancia una estrategia registrada por su nombre."""
    cls = STRATEGY_REGISTRY.get(name)
    if cls is None:
        available = ", ".join(sorted(STRATEGY_REGISTRY))
        raise ValueError(f"Estrategia '{name}' no existe. Disponibles: {available}")
    return cls(params)


__all__ = [
    "BaseStrategy",
    "Signal",
    "SignalType",
    "STRATEGY_REGISTRY",
    "get_strategy",
]
