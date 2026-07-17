"""
Módulo C — Motor de Backtesting.

- data_loader.py : carga/normalización de CSVs y gestión de datasets.
- backtester.py  : simulador vela a vela que reutiliza estrategias y
                   risk manager del trading en vivo.
- metrics.py     : win rate, profit factor, drawdown, Sharpe, rachas...
"""

from app.backtesting.backtester import Backtester, BacktestParams, BacktestResult
from app.backtesting.data_loader import load_csv
from app.backtesting.metrics import compute_metrics

__all__ = [
    "Backtester",
    "BacktestParams",
    "BacktestResult",
    "load_csv",
    "compute_metrics",
]
