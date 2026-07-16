"""Schemas Pydantic del Módulo A: credenciales de broker y watchlist."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import BrokerType


class BrokerCredentialIn(BaseModel):
    """
    Payload para registrar credenciales. Los secretos llegan en texto plano
    por HTTPS y se cifran (Fernet) ANTES de tocar la base de datos.

    - MT5/Pepperstone: login + password + server.
    - OANDA: api_key + account_id.
    """

    broker_type: BrokerType
    label: str = Field(default="Mi cuenta", max_length=100)
    login: str | None = None
    password: str | None = None
    api_key: str | None = None
    server: str | None = None
    account_id: str | None = None
    is_demo: bool = True


class BrokerCredentialOut(BaseModel):
    """Vista pública de una credencial: NUNCA expone los secretos."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    broker_type: BrokerType
    label: str
    server: str | None
    account_id: str | None
    is_demo: bool
    is_active: bool
    created_at: datetime


class ConnectionTestResult(BaseModel):
    """Resultado del botón 'Probar Conexión' del dashboard."""

    success: bool
    message: str
    account_balance: float | None = None
    account_currency: str | None = None


class AssetIn(BaseModel):
    symbol: str = Field(
        min_length=6, max_length=12, pattern=r"^[A-Z]{6,12}$",
        description="Par en mayúsculas sin separador, ej. EURUSD",
    )
    timeframe: str = Field(default="M15", pattern=r"^(M1|M5|M15|M30|H1|H4|D1)$")
    pip_size: float = Field(default=0.0001, gt=0)
    enabled: bool = True


class AssetOut(AssetIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
