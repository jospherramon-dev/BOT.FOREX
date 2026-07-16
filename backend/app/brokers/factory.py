"""
Fábrica de conectores de broker.

Recibe un registro `BrokerCredential` de la base de datos, descifra los
secretos EN MEMORIA (nunca se escriben descifrados) y devuelve el conector
concreto ya configurado. Es el único punto del sistema que conoce todas
las implementaciones.
"""

from __future__ import annotations

from app.brokers.base import BrokerConnector
from app.brokers.mt5_connector import MT5Connector
from app.brokers.oanda_connector import OandaConnector
from app.core.security import decrypt_secret
from app.db.models import BrokerCredential, BrokerType


def create_connector(credential: BrokerCredential) -> BrokerConnector:
    """
    Construye el conector adecuado para la credencial dada.

    Raises:
        ValueError: si la credencial está incompleta o el broker no
        está soportado.
    """
    if credential.broker_type in (BrokerType.MT5, BrokerType.PEPPERSTONE):
        if not (credential.encrypted_login and credential.encrypted_password
                and credential.server):
            raise ValueError("Credencial MT5 incompleta: requiere login, password y server.")
        return MT5Connector(
            login=int(decrypt_secret(credential.encrypted_login)),
            password=decrypt_secret(credential.encrypted_password),
            server=credential.server,
        )

    if credential.broker_type == BrokerType.OANDA:
        if not (credential.encrypted_api_key and credential.account_id):
            raise ValueError("Credencial OANDA incompleta: requiere api_key y account_id.")
        return OandaConnector(
            api_key=decrypt_secret(credential.encrypted_api_key),
            account_id=credential.account_id,
            is_demo=credential.is_demo,
        )

    raise ValueError(f"Broker no soportado: {credential.broker_type}")
