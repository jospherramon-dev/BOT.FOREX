"""
Módulo A — Rutas de credenciales de broker.

POST   /broker/credentials          : guarda credenciales (cifradas Fernet).
GET    /broker/credentials          : lista credenciales (sin secretos).
DELETE /broker/credentials/{id}     : elimina una credencial.
POST   /broker/credentials/{id}/test : botón "Probar Conexión" del dashboard.
"""

import logging

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, DBSession
from app.brokers.factory import create_connector
from app.core.security import encrypt_secret
from app.db.models import BrokerCredential, BrokerType
from app.schemas.broker import (
    BrokerCredentialIn,
    BrokerCredentialOut,
    ConnectionTestResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/broker", tags=["Broker"])


def _get_owned_credential(
    db: DBSession, user_id: int, credential_id: int
) -> BrokerCredential:
    """Carga la credencial verificando que pertenece al usuario (404 si no)."""
    cred = db.get(BrokerCredential, credential_id)
    if cred is None or cred.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Credencial no encontrada"
        )
    return cred


@router.post(
    "/credentials",
    response_model=BrokerCredentialOut,
    status_code=status.HTTP_201_CREATED,
)
def save_credentials(
    payload: BrokerCredentialIn, db: DBSession, current_user: CurrentUser
) -> BrokerCredential:
    """
    Guarda credenciales de broker. Los secretos se cifran con Fernet antes
    de persistirse; jamás se devuelven en ninguna respuesta.
    """
    # Validar por tipo de broker que llegaron los campos necesarios.
    if payload.broker_type in (BrokerType.MT5, BrokerType.PEPPERSTONE):
        if not (payload.login and payload.password and payload.server):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="MT5/Pepperstone requiere: login, password y server",
            )
    elif payload.broker_type == BrokerType.OANDA:
        if not (payload.api_key and payload.account_id):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="OANDA requiere: api_key y account_id",
            )

    cred = BrokerCredential(
        user_id=current_user.id,
        broker_type=payload.broker_type,
        label=payload.label,
        encrypted_login=encrypt_secret(payload.login) if payload.login else None,
        encrypted_password=(
            encrypt_secret(payload.password) if payload.password else None
        ),
        encrypted_api_key=(
            encrypt_secret(payload.api_key) if payload.api_key else None
        ),
        server=payload.server,
        account_id=payload.account_id,
        is_demo=payload.is_demo,
    )
    db.add(cred)
    db.commit()
    db.refresh(cred)
    logger.info(
        "Credencial %s guardada (id=%s) para usuario %s",
        payload.broker_type.value, cred.id, current_user.username,
    )
    return cred


@router.get("/credentials", response_model=list[BrokerCredentialOut])
def list_credentials(db: DBSession, current_user: CurrentUser) -> list[BrokerCredential]:
    """Credenciales del usuario — vista pública, sin campos cifrados."""
    return list(
        db.scalars(
            select(BrokerCredential).where(
                BrokerCredential.user_id == current_user.id
            )
        )
    )


@router.delete("/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_credential(
    credential_id: int, db: DBSession, current_user: CurrentUser
) -> None:
    cred = _get_owned_credential(db, current_user.id, credential_id)
    db.delete(cred)
    db.commit()


@router.post("/credentials/{credential_id}/test", response_model=ConnectionTestResult)
async def test_connection(
    credential_id: int, db: DBSession, current_user: CurrentUser
) -> ConnectionTestResult:
    """
    Botón "Probar Conexión": construye el conector, abre sesión con el
    broker y devuelve balance/divisa si tuvo éxito.

    Los conectores son síncronos (MT5 lo exige), así que se ejecutan en el
    threadpool de Starlette para no bloquear el event-loop.
    """
    cred = _get_owned_credential(db, current_user.id, credential_id)

    try:
        connector = create_connector(cred)
    except ValueError as exc:
        return ConnectionTestResult(success=False, message=str(exc))

    def _probe() -> ConnectionTestResult:
        try:
            if not connector.connect():
                return ConnectionTestResult(
                    success=False,
                    message="No se pudo conectar: verifique credenciales y servidor.",
                )
            info = connector.get_account_info()
            return ConnectionTestResult(
                success=True,
                message=f"Conexión exitosa con {connector.name}",
                account_balance=info.balance,
                account_currency=info.currency,
            )
        except Exception as exc:  # noqa: BLE001 — se reporta al usuario
            logger.exception("Test de conexión falló")
            return ConnectionTestResult(success=False, message=str(exc))
        finally:
            connector.disconnect()

    return await run_in_threadpool(_probe)
