"""
Módulo C — Carga y normalización de datos históricos.

Acepta CSVs en los formatos habituales (exportes de MT5, OANDA, Dukascopy,
TradingView...) y los normaliza al contrato interno: DataFrame indexado por
tiempo con columnas ['open', 'high', 'low', 'close', 'volume'] — el mismo
formato que devuelven los conectores de broker, por lo que estrategias y
backtester no distinguen el origen de los datos.

Formatos soportados automáticamente:
- Separador coma, punto y coma o tabulador (autodetección).
- Columna única de fecha (`time`, `date`, `datetime`, `timestamp`) o
  columnas separadas `<DATE>` + `<TIME>` (exporte de MT5).
- Nombres de columna con o sin ángulos (`<OPEN>` → `open`), en cualquier
  capitalización.
- Volumen opcional (`volume`, `tick_volume`, `vol`); si falta se rellena 0.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.core.config import settings  # noqa: F401  (reservado para límites configurables)

#: Tamaño máximo de archivo aceptado en la subida (20 MB).
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

_TIME_CANDIDATES = ["time", "datetime", "date", "timestamp"]
_VOLUME_CANDIDATES = ["volume", "tick_volume", "vol", "tickvol"]


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """`<CLOSE>` / 'Close ' / 'CLOSE' → 'close'."""
    df.columns = [str(c).strip().strip("<>").lower() for c in df.columns]
    return df


def load_csv(path: str | Path) -> pd.DataFrame:
    """
    Lee y normaliza un CSV de velas.

    Returns:
        DataFrame OHLCV indexado por tiempo, ordenado ascendente y sin
        duplicados.

    Raises:
        ValueError: si faltan columnas OHLC o no se reconoce la fecha.
    """
    path = Path(path)
    # sep=None + engine='python' autodetecta coma / punto y coma / tab.
    df = pd.read_csv(path, sep=None, engine="python")
    df = _normalize_columns(df)

    # --- Resolver la columna temporal ---------------------------------
    if "date" in df.columns and "time" in df.columns and "datetime" not in df.columns:
        # Formato MT5: <DATE> 2024.01.02 + <TIME> 00:15:00
        df["datetime"] = pd.to_datetime(
            df["date"].astype(str) + " " + df["time"].astype(str),
            format="mixed",
        )
        time_col = "datetime"
    else:
        time_col = next((c for c in _TIME_CANDIDATES if c in df.columns), None)
        if time_col is None:
            raise ValueError(
                f"No se encontró columna temporal. Columnas: {list(df.columns)}"
            )
        # Los exportes de MT5 usan puntos (2024.01.02); pandas los resuelve
        # con format='mixed'. Epochs numéricos se tratan como segundos.
        if pd.api.types.is_numeric_dtype(df[time_col]):
            df[time_col] = pd.to_datetime(df[time_col], unit="s")
        else:
            df[time_col] = pd.to_datetime(
                df[time_col].astype(str).str.replace(".", "-", regex=False),
                format="mixed",
            )

    # --- Validar OHLC ----------------------------------------------------
    missing = {"open", "high", "low", "close"} - set(df.columns)
    if missing:
        raise ValueError(f"Faltan columnas OHLC en el CSV: {sorted(missing)}")

    # --- Volumen opcional -------------------------------------------------
    vol_col = next((c for c in _VOLUME_CANDIDATES if c in df.columns), None)
    df["volume"] = df[vol_col] if vol_col else 0

    df = (
        df.set_index(time_col)[["open", "high", "low", "close", "volume"]]
        .astype(float)
        .sort_index()
    )
    df = df[~df.index.duplicated(keep="last")]

    if df.empty:
        raise ValueError("El CSV no contiene velas válidas")
    return df


# ---------------------------------------------------------------------------
# Gestión de datasets subidos por el usuario
# ---------------------------------------------------------------------------
def datasets_root() -> Path:
    """Directorio raíz de datos históricos (backend/data/historical)."""
    return Path(__file__).resolve().parents[2] / "data" / "historical"


def user_dataset_dir(user_id: int) -> Path:
    """Directorio de datasets de un usuario; se crea si no existe."""
    path = datasets_root() / f"user_{user_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def dataset_info(path: Path) -> dict:
    """Metadatos rápidos de un dataset para listarlo en el dashboard."""
    df = load_csv(path)
    return {
        "filename": path.name,
        "rows": len(df),
        "date_from": df.index[0].isoformat(),
        "date_to": df.index[-1].isoformat(),
        "size_bytes": path.stat().st_size,
    }
