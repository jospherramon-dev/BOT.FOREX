"""
Módulo B — Motor de Trading y Gestión de Riesgo.

- risk_manager.py   : funciones puras de riesgo (lote dinámico, SL/TP,
                      break-even, trailing stop, clasificación de cierres).
- trading_engine.py : bucle principal por usuario (velas → estrategia →
                      órdenes → supervisión de posiciones) y registro de
                      motores activos.
"""

from app.engine.trading_engine import (
    TradingEngine,
    get_engine,
    start_engine,
    stop_engine,
)

__all__ = ["TradingEngine", "get_engine", "start_engine", "stop_engine"]
