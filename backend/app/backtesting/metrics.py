"""
Módulo C — Métricas de rendimiento de un backtest.

Recibe la lista de trades simulados y la curva de equity y produce las
estadísticas que consume el dashboard: win rate, profit factor, drawdown
máximo, Sharpe ratio, rachas, promedios, etc.
"""

from __future__ import annotations

import math

# Minutos por timeframe para anualizar el Sharpe ratio.
_TIMEFRAME_MINUTES = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440,
}
_MINUTES_PER_YEAR = 365.25 * 24 * 60


def max_drawdown_pct(equity: list[float]) -> float:
    """Máxima caída pico-a-valle de la curva de equity, en porcentaje."""
    peak = float("-inf")
    max_dd = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            max_dd = max(max_dd, (peak - value) / peak * 100)
    return round(max_dd, 2)


def sharpe_ratio(equity: list[float], timeframe: str) -> float:
    """
    Sharpe anualizado sobre los retornos por vela de la curva de equity
    (tasa libre de riesgo = 0). Devuelve 0 si no hay variación.
    """
    if len(equity) < 3:
        return 0.0
    returns = [
        (equity[i] / equity[i - 1]) - 1
        for i in range(1, len(equity))
        if equity[i - 1] > 0
    ]
    if not returns:
        return 0.0

    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    std = math.sqrt(variance)
    if std == 0:
        return 0.0

    bars_per_year = _MINUTES_PER_YEAR / _TIMEFRAME_MINUTES.get(timeframe, 15)
    return round(mean / std * math.sqrt(bars_per_year), 2)


def _max_streak(profits: list[float], winning: bool) -> int:
    """Racha más larga de trades ganadores (o perdedores)."""
    best = current = 0
    for p in profits:
        if (p > 0) if winning else (p < 0):
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def compute_metrics(
    trades: list[dict],
    equity: list[float],
    initial_balance: float,
    timeframe: str,
) -> dict:
    """Estadísticas agregadas de la simulación (contrato del dashboard)."""
    profits = [t["profit"] for t in trades]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p < 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    final_balance = equity[-1] if equity else initial_balance
    net_profit = final_balance - initial_balance

    return {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
        "profit_factor": (
            round(gross_profit / gross_loss, 2) if gross_loss > 0
            else (999.0 if gross_profit > 0 else 0.0)
        ),
        "net_profit": round(net_profit, 2),
        "return_pct": round(net_profit / initial_balance * 100, 2),
        "max_drawdown_pct": max_drawdown_pct(equity),
        "sharpe_ratio": sharpe_ratio(equity, timeframe),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "best_trade": round(max(profits), 2) if profits else 0.0,
        "worst_trade": round(min(profits), 2) if profits else 0.0,
        "max_consecutive_wins": _max_streak(profits, winning=True),
        "max_consecutive_losses": _max_streak(profits, winning=False),
        "initial_balance": initial_balance,
        "final_balance": round(final_balance, 2),
    }


def downsample_equity(points: list[dict], max_points: int = 1000) -> list[dict]:
    """
    Reduce la curva de equity a ≤ max_points para el gráfico del dashboard
    (conservando siempre el primer y el último punto).
    """
    if len(points) <= max_points:
        return points
    step = len(points) / max_points
    sampled = [points[int(i * step)] for i in range(max_points)]
    if sampled[-1] is not points[-1]:
        sampled[-1] = points[-1]
    return sampled
