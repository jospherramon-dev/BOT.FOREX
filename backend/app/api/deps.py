"""Dependencias compartidas de la API: sesión de BD y usuario autenticado."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.database import get_db
from app.db.models import User

# tokenUrl apunta al endpoint de login para que Swagger UI ofrezca el botón
# "Authorize" funcional.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")

DBSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DBSession, token: Annotated[str, Depends(oauth2_scheme)]
) -> User:
    """Resuelve el usuario a partir del JWT; 401 si es inválido o expiró."""
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )

    user_id = decode_access_token(token)
    if user_id is None:
        raise credentials_error

    user = db.get(User, int(user_id))
    if user is None or not user.is_active:
        raise credentials_error
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
