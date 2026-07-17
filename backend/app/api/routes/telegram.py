"""
Módulo D — Rutas de configuración de Telegram.

GET  /telegram/config : estado actual (sin exponer el token).
PUT  /telegram/config : guarda token (cifrado Fernet) + chat_id + flag.
POST /telegram/test   : botón "Probar Conexión" (getMe + mensaje de prueba).
"""

import logging

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.core.security import decrypt_secret, encrypt_secret
from app.db.models import BotConfig
from app.notifications import telegram_service
from app.schemas.telegram import (
    TelegramConfigIn,
    TelegramConfigOut,
    TelegramTestResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telegram", tags=["Telegram"])


def _get_config(db: DBSession, user_id: int) -> BotConfig:
    config = db.scalar(select(BotConfig).where(BotConfig.user_id == user_id))
    if config is None:
        config = BotConfig(user_id=user_id)
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


@router.get("/config", response_model=TelegramConfigOut)
def get_telegram_config(db: DBSession, current_user: CurrentUser) -> TelegramConfigOut:
    config = _get_config(db, current_user.id)
    return TelegramConfigOut(
        enabled=config.telegram_enabled,
        token_set=bool(config.encrypted_telegram_token),
        chat_id=config.telegram_chat_id,
    )


@router.put("/config", response_model=TelegramConfigOut)
def update_telegram_config(
    payload: TelegramConfigIn, db: DBSession, current_user: CurrentUser
) -> TelegramConfigOut:
    """Guarda la configuración; el token se cifra con Fernet antes de persistir."""
    config = _get_config(db, current_user.id)

    if payload.bot_token is not None:
        config.encrypted_telegram_token = encrypt_secret(payload.bot_token)
    elif not config.encrypted_telegram_token and payload.enabled:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No hay token guardado: debe indicar bot_token",
        )

    config.telegram_chat_id = payload.chat_id
    config.telegram_enabled = payload.enabled
    db.commit()

    logger.info("Configuración Telegram actualizada (usuario %s, enabled=%s)",
                current_user.username, payload.enabled)
    return TelegramConfigOut(
        enabled=config.telegram_enabled,
        token_set=bool(config.encrypted_telegram_token),
        chat_id=config.telegram_chat_id,
    )


@router.post("/test", response_model=TelegramTestResult)
async def test_telegram(db: DBSession, current_user: CurrentUser) -> TelegramTestResult:
    """Valida el token guardado y envía un mensaje de prueba al chat."""
    config = _get_config(db, current_user.id)
    if not config.encrypted_telegram_token or not config.telegram_chat_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Configure primero el token y el chat_id",
        )

    try:
        token = decrypt_secret(config.encrypted_telegram_token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token indescifrable: vuelva a guardarlo",
        ) from exc

    result = await telegram_service.test_connection(token, config.telegram_chat_id)
    return TelegramTestResult(**result)
