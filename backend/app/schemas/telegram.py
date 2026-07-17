"""Schemas Pydantic del Módulo D: notificaciones Telegram."""

from pydantic import BaseModel, Field


class TelegramConfigIn(BaseModel):
    """
    Configuración desde el dashboard. `bot_token` es opcional: si llega
    None se conserva el token ya guardado (permite cambiar chat_id o el
    flag sin re-introducir el token).
    """

    enabled: bool = True
    bot_token: str | None = Field(
        default=None,
        min_length=20,
        description="Token de @BotFather (se cifra antes de guardarse)",
    )
    chat_id: str = Field(min_length=1, max_length=64)


class TelegramConfigOut(BaseModel):
    """Estado público: NUNCA devuelve el token, solo si está configurado."""

    enabled: bool
    token_set: bool
    chat_id: str | None


class TelegramTestResult(BaseModel):
    success: bool
    message: str
    bot_username: str | None = None
