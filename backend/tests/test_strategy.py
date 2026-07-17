"""Tests de la estrategia por defecto y del módulo de seguridad."""

import numpy as np
import pandas as pd
import pytest

from app.strategies import get_strategy
from app.strategies.base_strategy import SignalType
from app.strategies.ma_rsi_crossover import ema, rsi


def make_ohlcv(closes: list[float]) -> pd.DataFrame:
    """Construye un DataFrame OHLCV sintético a partir de precios de cierre."""
    closes_arr = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": closes_arr,
            "high": closes_arr * 1.0005,
            "low": closes_arr * 0.9995,
            "close": closes_arr,
            "volume": np.full(len(closes_arr), 1000),
        },
        index=pd.date_range("2025-01-01", periods=len(closes_arr), freq="15min"),
    )


def test_registry_devuelve_estrategia_por_defecto():
    strategy = get_strategy("ma_rsi_crossover")
    assert strategy.name == "ma_rsi_crossover"


def test_estrategia_desconocida_lanza_error():
    with pytest.raises(ValueError, match="no existe"):
        get_strategy("inexistente")


def test_indicadores_basicos():
    serie = pd.Series(np.linspace(1.0, 2.0, 100))
    assert ema(serie, 9).iloc[-1] == pytest.approx(2.0, abs=0.1)
    # En una serie estrictamente alcista el RSI debe estar saturado arriba.
    assert rsi(serie, 14).iloc[-1] > 90


def test_senal_compra_en_cruce_alcista():
    # 80 velas bajistas suaves y luego un giro alcista moderado: fuerza el
    # cruce EMA9>EMA21 con RSI en zona 50-70.
    closes = list(np.linspace(1.10, 1.09, 80)) + list(np.linspace(1.09, 1.0935, 12))
    strategy = get_strategy("ma_rsi_crossover")

    signals = [
        strategy.calculate_signal(make_ohlcv(closes[:i]), "EURUSD").type
        for i in range(70, len(closes) + 1)
    ]
    assert SignalType.BUY in signals


def test_hold_sin_cruce():
    closes = list(np.linspace(1.10, 1.20, 100))  # tendencia estable, sin cruce nuevo
    signal = get_strategy("ma_rsi_crossover").calculate_signal(
        make_ohlcv(closes), "EURUSD"
    )
    assert signal.type == SignalType.HOLD


def test_datos_insuficientes_lanza_error():
    with pytest.raises(ValueError, match="velas"):
        get_strategy("ma_rsi_crossover").calculate_signal(
            make_ohlcv([1.1] * 10), "EURUSD"
        )


def test_cifrado_fernet_roundtrip():
    from app.core.security import decrypt_secret, encrypt_secret

    secreto = "api-key-super-secreta-123"
    cifrado = encrypt_secret(secreto)
    assert cifrado != secreto
    assert decrypt_secret(cifrado) == secreto


def test_jwt_roundtrip():
    from app.core.security import create_access_token, decode_access_token

    token = create_access_token(subject="42")
    assert decode_access_token(token) == "42"
    assert decode_access_token("token-falso") is None
