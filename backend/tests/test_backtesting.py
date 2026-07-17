"""Tests del Módulo C: cargador de datos, métricas y simulador."""

import numpy as np
import pandas as pd
import pytest

from app.backtesting.backtester import Backtester, BacktestParams
from app.backtesting.data_loader import load_csv
from app.backtesting.metrics import (
    compute_metrics,
    downsample_equity,
    max_drawdown_pct,
    sharpe_ratio,
)
from app.strategies import STRATEGY_REGISTRY
from app.strategies.base_strategy import BaseStrategy, Signal, SignalType


# ---------------------------------------------------------------------------
# data_loader
# ---------------------------------------------------------------------------
def test_load_csv_formato_estandar(tmp_path):
    path = tmp_path / "velas.csv"
    path.write_text(
        "time,open,high,low,close,volume\n"
        "2025-01-01 00:00,1.10,1.11,1.09,1.105,500\n"
        "2025-01-01 00:15,1.105,1.12,1.10,1.11,600\n"
    )
    df = load_csv(path)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert df["close"].iloc[-1] == pytest.approx(1.11)


def test_load_csv_formato_mt5(tmp_path):
    # Exporte MT5: tabulador, columnas <DATE>/<TIME> y <TICKVOL>.
    path = tmp_path / "mt5.csv"
    path.write_text(
        "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\n"
        "2025.01.01\t00:00:00\t1.10\t1.11\t1.09\t1.105\t500\n"
        "2025.01.01\t00:15:00\t1.105\t1.12\t1.10\t1.11\t600\n"
    )
    df = load_csv(path)
    assert len(df) == 2
    assert df.index[0] == pd.Timestamp("2025-01-01 00:00:00")


def test_load_csv_sin_ohlc_falla(tmp_path):
    path = tmp_path / "malo.csv"
    path.write_text("time,precio\n2025-01-01,1.1\n")
    with pytest.raises(ValueError, match="OHLC"):
        load_csv(path)


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------
def test_max_drawdown():
    # Pico 12000 → valle 9000 = 25% de caída.
    equity = [10_000, 11_000, 12_000, 10_500, 9_000, 11_500]
    assert max_drawdown_pct(equity) == pytest.approx(25.0)


def test_sharpe_cero_sin_variacion():
    assert sharpe_ratio([10_000] * 50, "M15") == 0.0


def test_compute_metrics_basico():
    trades = [{"profit": p} for p in [100, -50, 200, -50, 150]]
    equity = [10_000, 10_100, 10_050, 10_250, 10_200, 10_350]
    m = compute_metrics(trades, equity, 10_000, "M15")

    assert m["total_trades"] == 5
    assert m["wins"] == 3 and m["losses"] == 2
    assert m["win_rate"] == pytest.approx(60.0)
    assert m["profit_factor"] == pytest.approx(450 / 100)
    assert m["net_profit"] == pytest.approx(350)
    # Ganancias y pérdidas alternan: ninguna racha supera 1.
    assert m["max_consecutive_wins"] == 1
    assert m["max_consecutive_losses"] == 1
    assert m["best_trade"] == 200 and m["worst_trade"] == -50


def test_downsample_conserva_extremos():
    points = [{"i": i} for i in range(5000)]
    sampled = downsample_equity(points, max_points=100)
    assert len(sampled) == 100
    assert sampled[0] == points[0]
    assert sampled[-1] == points[-1]


# ---------------------------------------------------------------------------
# backtester (simulación determinista con estrategia de prueba)
# ---------------------------------------------------------------------------
class BuyOnceStrategy(BaseStrategy):
    """Compra en la primera vela evaluada y luego se mantiene en HOLD."""

    name = "test_buy_once"
    min_bars = 5

    def __init__(self, params=None):
        super().__init__(params)
        self._fired = False

    def calculate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        if not self._fired:
            self._fired = True
            return Signal(type=SignalType.BUY, symbol=symbol, reason="test")
        return Signal(type=SignalType.HOLD, symbol=symbol)


STRATEGY_REGISTRY[BuyOnceStrategy.name] = BuyOnceStrategy


def _df_from_closes(closes: list[float]) -> pd.DataFrame:
    """Velas sintéticas con rango high/low de ±2 pips alrededor del cierre."""
    arr = np.asarray(closes)
    return pd.DataFrame(
        {
            "open": arr,
            "high": arr + 0.0002,
            "low": arr - 0.0002,
            "close": arr,
            "volume": np.full(len(arr), 100),
        },
        index=pd.date_range("2025-01-01", periods=len(arr), freq="15min"),
    )


def _base_params(**overrides) -> BacktestParams:
    defaults = dict(
        symbol="EURUSD",
        timeframe="M15",
        initial_balance=10_000,
        spread_pips=0.0,           # sin spread para aserciones exactas
        strategy_name="test_buy_once",
        risk_per_trade_pct=1.0,
        stop_loss_pips=30,
        take_profit_pips=60,
        break_even_enabled=False,
    )
    defaults.update(overrides)
    return BacktestParams(**defaults)


def test_backtest_gana_por_take_profit():
    # Plano en 1.1000 (velas 0-5), señal en la vela 5 → entra a 1.1000.
    # Luego sube hasta superar el TP (1.1060).
    closes = [1.1000] * 6 + list(np.linspace(1.1005, 1.1070, 10))
    result = Backtester(_df_from_closes(closes), _base_params()).run()

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.status == "CLOSED_TP"
    assert trade.entry_price == pytest.approx(1.1000)
    assert trade.exit_price == pytest.approx(1.1060)
    assert trade.profit_pips == pytest.approx(60)
    # Lote 0.33 × 60 pips × $10/pip = $198 de beneficio.
    assert trade.profit == pytest.approx(198.0, abs=0.5)
    assert result.final_balance == pytest.approx(10_198.0, abs=0.5)


def test_backtest_pierde_por_stop_loss():
    closes = [1.1000] * 6 + list(np.linspace(1.0995, 1.0960, 10))
    result = Backtester(_df_from_closes(closes), _base_params()).run()

    trade = result.trades[0]
    assert trade.status == "CLOSED_SL"
    assert trade.exit_price == pytest.approx(1.0970)
    # Pérdida ≈ riesgo configurado (1% = $100), acotada por el lote truncado.
    assert trade.profit == pytest.approx(-99.0, abs=1.5)


def test_backtest_break_even_protege():
    # Sube +25 pips (dispara BE en 20) y luego cae por debajo de la entrada:
    # el SL movido a entrada+1pip convierte la pérdida en +1 pip.
    closes = [1.1000] * 6 + [1.1010, 1.1025, 1.1020, 1.1005, 1.0990, 1.0960]
    params = _base_params(break_even_enabled=True, break_even_trigger_pips=20)
    result = Backtester(_df_from_closes(closes), params).run()

    trade = result.trades[0]
    assert trade.break_even_applied is True
    assert trade.status == "CLOSED_SL"
    assert trade.exit_price == pytest.approx(1.1001)  # entrada + 1 pip
    assert trade.profit > 0  # protegido: cierra en positivo


def test_backtest_equity_curve_consistente():
    closes = [1.1000] * 6 + list(np.linspace(1.1005, 1.1070, 10))
    result = Backtester(_df_from_closes(closes), _base_params()).run()

    assert result.equity_curve, "La curva de equity no puede estar vacía"
    # El último punto de equity coincide con el balance final.
    assert result.equity_curve[-1]["equity"] == pytest.approx(result.final_balance)
    # La equity nunca es negativa en este escenario.
    assert all(pt["equity"] > 0 for pt in result.equity_curve)