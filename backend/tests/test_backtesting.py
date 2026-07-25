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


class AlwaysBuyBtStrategy(BaseStrategy):
    """Compra en cada vela evaluada (para tests que necesitan muchos trades)."""

    name = "test_always_buy"
    min_bars = 5

    def calculate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        return Signal(type=SignalType.BUY, symbol=symbol, reason="test")


STRATEGY_REGISTRY[AlwaysBuyBtStrategy.name] = AlwaysBuyBtStrategy


class StructuralBuyStrategy(BaseStrategy):
    """Compra una vez con SL/TP ABSOLUTOS en la metadata (estilo SMC)."""

    name = "test_structural_buy"
    min_bars = 5

    def __init__(self, params=None):
        super().__init__(params)
        self._fired = False

    def calculate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        if not self._fired:
            self._fired = True
            return Signal(
                type=SignalType.BUY, symbol=symbol, reason="test",
                metadata={"sl_price": 1.0985, "tp_price": 1.1040},
            )
        return Signal(type=SignalType.HOLD, symbol=symbol)


STRATEGY_REGISTRY[StructuralBuyStrategy.name] = StructuralBuyStrategy


class BuyThenExitStrategy(BaseStrategy):
    """Compra una vez y, unas velas después, pide salir por check_exit."""

    name = "test_buy_then_exit"
    min_bars = 5

    def __init__(self, params=None):
        super().__init__(params)
        self._fired = False
        self._bars_open = 0

    def calculate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        if not self._fired:
            self._fired = True
            return Signal(type=SignalType.BUY, symbol=symbol, reason="test")
        return Signal(type=SignalType.HOLD, symbol=symbol)

    def check_exit(self, df: pd.DataFrame, symbol: str, direction: str) -> bool:
        # Cierra a la tercera vela evaluada tras abrir.
        self._bars_open += 1
        return self._bars_open >= 3


STRATEGY_REGISTRY[BuyThenExitStrategy.name] = BuyThenExitStrategy


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


def test_freno_drawdown_reduce_perdida():
    """
    Con una estrategia que siempre compra en un mercado que cae sin parar,
    el freno de drawdown debe cortar las entradas tras cruzar el umbral y
    dejar una pérdida MENOR que sin freno.
    """
    # Mercado bajista pronunciado: cada BUY pierde rápido (≈3 pips/vela), así
    # el drawdown se acumula pronto y el freno actúa a mitad del recorrido.
    closes = [1.1000] * 6 + list(np.linspace(1.0990, 1.0000, 300))
    df = _df_from_closes(closes)

    sin_freno = Backtester(df, _base_params(strategy_name="test_always_buy")).run()
    con_freno = Backtester(
        df,
        _base_params(
            strategy_name="test_always_buy",
            max_drawdown_pct=10,
            drawdown_cooldown_bars=50,
        ),
    ).run()

    # El freno deja una pérdida final menos negativa (protege capital).
    assert con_freno.final_balance > sin_freno.final_balance
    # Y abre menos operaciones (pausó durante los tramos malos).
    assert len(con_freno.trades) < len(sin_freno.trades)


def test_freno_drawdown_reanuda_tras_enfriamiento():
    """
    El freno NO debe bloquear el bot para siempre: tras el enfriamiento debe
    reanudar. Con una caída seguida de una recuperación, el bot pausado debe
    volver a operar en el tramo alcista (no quedarse plano hasta el final).
    """
    # Caída (activa el freno) → recuperación larga y sostenida.
    closes = (
        [1.1000] * 6
        + list(np.linspace(1.0990, 1.0850, 60))   # baja: dispara el freno
        + list(np.linspace(1.0851, 1.1400, 250))  # sube largo: debe reanudar
    )
    df = _df_from_closes(closes)
    result = Backtester(
        df,
        _base_params(
            strategy_name="test_always_buy",
            max_drawdown_pct=10,
            drawdown_cooldown_bars=30,
        ),
    ).run()

    # Debe haber operaciones con entrada DESPUÉS del tramo de recuperación
    # inicial — prueba de que reanudó y no quedó bloqueado.
    entry_times = [t.entry_time for t in result.trades]
    resume_point = df.index[100].to_pydatetime()
    assert any(t > resume_point for t in entry_times), (
        "El freno bloqueó el bot permanentemente: no reanudó tras el enfriamiento"
    )


def test_sl_por_atr_dimensiona_el_stop():
    """
    Con SL por ATR activado, el stop de la operación debe reflejar
    ATR × multiplicador, NO los pips fijos. Mercado que sube ~2 pips/vela
    (rango 4 pips/vela) → ATR ≈ 4 pips → SL ≈ 4 × 1.5 = 6 pips.
    """
    closes = [1.1000] * 6 + list(np.linspace(1.10002, 1.10600, 300))
    df = _df_from_closes(closes)
    params = _base_params(
        strategy_name="test_always_buy",
        stop_loss_pips=30,          # fijo alto: se debe IGNORAR
        take_profit_pips=60,
        atr_sl_enabled=True,
        atr_period=14,
        atr_sl_multiplier=1.5,
        atr_tp_ratio=2.0,
        atr_sl_min_pips=1.0,        # bajo para no enmascarar el cálculo
    )
    result = Backtester(df, params).run()
    assert result.trades, "Debe abrir al menos una operación"
    t = result.trades[0]
    sl_pips = abs(t.entry_price - t.stop_loss) / 0.0001
    tp_pips = abs(t.take_profit - t.entry_price) / 0.0001
    assert sl_pips < 30            # mucho menor que el SL fijo → viene del ATR
    assert 3 < sl_pips < 12        # ~6 pips (ATR ~4 × 1.5)
    assert tp_pips == pytest.approx(sl_pips * 2.0, rel=0.02)  # R:R 1:2


def test_sl_tp_estructural_de_la_estrategia_se_honra():
    """
    Si la señal trae sl_price/tp_price absolutos (ej. SMC: SL tras el
    sweep), el backtester debe usarlos TAL CUAL en vez de los pips fijos,
    y dimensionar el lote con esa distancia real.
    """
    closes = [1.1000] * 6 + list(np.linspace(1.1005, 1.1055, 20))
    df = _df_from_closes(closes)
    result = Backtester(
        df, _base_params(strategy_name="test_structural_buy",
                         stop_loss_pips=30, take_profit_pips=60),
    ).run()

    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.stop_loss == pytest.approx(1.0985)     # el de la estrategia
    assert t.take_profit == pytest.approx(1.1040)   # no el fijo de 60 pips
    assert t.status == "CLOSED_TP"
    assert t.exit_price == pytest.approx(1.1040)


def test_salida_tecnica_de_estrategia_cierra_posicion():
    """
    Una estrategia que pide salir por check_exit debe cerrar la posición
    ANTES de que toque SL o TP, con estado manual (salida discrecional).
    """
    # Precio que sube suave: sin la salida técnica no tocaría SL ni TP pronto.
    closes = [1.1000] * 6 + list(np.linspace(1.10005, 1.10080, 20))
    df = _df_from_closes(closes)
    result = Backtester(
        df, _base_params(strategy_name="test_buy_then_exit",
                         stop_loss_pips=50, take_profit_pips=100),
    ).run()

    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.status == "CLOSED_MANUAL"        # cerrada por la estrategia
    assert t.exit_price is not None
    # Salió a mitad de camino, sin tocar SL (1.0950) ni TP (1.1100).
    assert 1.1000 < t.exit_price < 1.1010


def test_freno_drawdown_desactivado_por_defecto():
    """Con max_drawdown_pct=0 el resultado es idéntico a no tener freno."""
    closes = [1.1000] * 6 + list(np.linspace(1.1005, 1.1100, 30))
    df = _df_from_closes(closes)
    a = Backtester(df, _base_params()).run()
    b = Backtester(df, _base_params(max_drawdown_pct=0)).run()
    assert a.final_balance == b.final_balance


def test_backtest_equity_curve_consistente():
    closes = [1.1000] * 6 + list(np.linspace(1.1005, 1.1070, 10))
    result = Backtester(_df_from_closes(closes), _base_params()).run()

    assert result.equity_curve, "La curva de equity no puede estar vacía"
    # El último punto de equity coincide con el balance final.
    assert result.equity_curve[-1]["equity"] == pytest.approx(result.final_balance)
    # La equity nunca es negativa en este escenario.
    assert all(pt["equity"] > 0 for pt in result.equity_curve)