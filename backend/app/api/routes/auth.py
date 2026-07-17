"""
Módulo A — Rutas de autenticación (registro, login JWT, perfil).

POST /auth/register : crea un usuario (bcrypt para la contraseña).
POST /auth/login    : OAuth2 password flow → devuelve JWT.
GET  /auth/me       : datos del usuario autenticado.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import or_, select

from app.api.deps import CurrentUser, DBSession
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import BotConfig, User
from app.schemas.auth import Token, UserOut, UserRegister

router = APIRouter(prefix="/auth", tags=["Autenticación"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, db: DBSession) -> User:
    """Registra un usuario nuevo y crea su configuración de bot por defecto."""
    exists = db.scalar(
        select(User).where(
            or_(User.username == payload.username, User.email == payload.email)
        )
    )
    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El usuario o email ya está registrado",
        )

    user = User(
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    db.flush()  # asigna user.id antes de crear la config asociada
    db.add(BotConfig(user_id=user.id))
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(
    db: DBSession, form: Annotated[OAuth2PasswordRequestForm, Depends()]
) -> Token:
    """Valida credenciales y emite un JWT de sesión."""
    user = db.scalar(select(User).where(User.username == form.username))
    # Mensaje idéntico exista o no el usuario: no filtrar qué falló.
    if user is None or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Cuenta desactivada"
        )
    return Token(access_token=create_access_token(subject=str(user.id)))


@router.get("/me", response_model=UserOut)
def me(current_user: CurrentUser) -> User:
    """Perfil del usuario autenticado (verifica que el token sigue vivo)."""
    return current_user
