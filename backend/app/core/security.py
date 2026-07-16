"""
Seguridad: hashing de contraseñas, JWT y cifrado de credenciales.

Tres responsabilidades, tres mecanismos independientes:

1. **Contraseñas de usuario** → hash irreversible con bcrypt (passlib).
2. **Sesiones**               → JWT firmado HS256 con expiración.
3. **Credenciales de broker / Telegram** → cifrado simétrico reversible
   Fernet (necesitamos recuperar el secreto para conectar con el broker),
   con una clave DISTINTA a la del JWT.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Hashing de contraseñas (bcrypt)
# ---------------------------------------------------------------------------
# bcrypt solo procesa los primeros 72 bytes; truncamos explícitamente para
# que contraseñas más largas no lancen ValueError en versiones >= 4.1.
_BCRYPT_MAX_BYTES = 72


def hash_password(plain_password: str) -> str:
    """Genera el hash bcrypt de una contraseña en texto plano."""
    password_bytes = plain_password.encode()[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Compara una contraseña en texto plano contra su hash almacenado."""
    password_bytes = plain_password.encode()[:_BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(password_bytes, hashed_password.encode())
    except ValueError:  # hash almacenado con formato inválido
        return False


# ---------------------------------------------------------------------------
# 2. JSON Web Tokens (sesión)
# ---------------------------------------------------------------------------
def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    """
    Crea un JWT firmado.

    Args:
        subject: identificador del usuario (se guarda en el claim `sub`).
        expires_minutes: TTL personalizado; por defecto el de settings.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": subject, "exp": expire, "iat": datetime.now(timezone.utc)}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """
    Valida un JWT y devuelve el `sub` (id de usuario).
    Devuelve None si el token es inválido o expiró.
    """
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


# ---------------------------------------------------------------------------
# 3. Cifrado reversible de credenciales (Fernet)
# ---------------------------------------------------------------------------
def _build_fernet() -> Fernet:
    """
    Construye la instancia Fernet a partir de ENCRYPTION_KEY.

    En desarrollo, si no hay clave configurada, se genera una efímera y se
    avisa por log: las credenciales cifradas se perderán al reiniciar.
    """
    key = settings.ENCRYPTION_KEY.strip()
    if not key or key.startswith("CAMBIAME"):
        logger.warning(
            "ENCRYPTION_KEY no configurada: usando clave efímera de desarrollo. "
            "Las credenciales guardadas NO sobrevivirán a un reinicio."
        )
        return Fernet(Fernet.generate_key())
    return Fernet(key.encode())


_fernet = _build_fernet()


def encrypt_secret(plain_text: str) -> str:
    """Cifra un secreto (API key, contraseña de broker, token Telegram)."""
    return _fernet.encrypt(plain_text.encode()).decode()


def decrypt_secret(cipher_text: str) -> str:
    """
    Descifra un secreto previamente cifrado con `encrypt_secret`.

    Raises:
        ValueError: si el texto no puede descifrarse (clave incorrecta
        o datos corruptos).
    """
    try:
        return _fernet.decrypt(cipher_text.encode()).decode()
    except InvalidToken as exc:
        raise ValueError(
            "No se pudo descifrar la credencial: ENCRYPTION_KEY incorrecta "
            "o dato corrupto."
        ) from exc
