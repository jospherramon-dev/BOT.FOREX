"""
Configuración central de la aplicación.

Carga variables desde el entorno (o un archivo `.env`) usando
pydantic-settings, validando tipos y valores por defecto.
Todo el código accede a la configuración a través del singleton
`settings` — nunca leyendo `os.environ` directamente.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Parámetros globales de BOT.FOREX."""

    # --- Aplicación ---------------------------------------------------
    APP_NAME: str = "BOT.FOREX"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    # --- API ----------------------------------------------------------
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # --- Seguridad ------------------------------------------------------
    # Clave para firmar JWT (HS256). OBLIGATORIO cambiarla en producción.
    SECRET_KEY: str = "dev-secret-key-CHANGE-ME-in-production-0000"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 horas

    # Clave Fernet (44 chars base64) para cifrar credenciales del broker.
    # Si se deja vacía en desarrollo, security.py genera una efímera
    # (las credenciales guardadas no sobrevivirán al reinicio).
    ENCRYPTION_KEY: str = ""

    # --- Base de datos --------------------------------------------------
    DATABASE_URL: str = "sqlite:///./botforex.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Devuelve la configuración cacheada (se lee el .env una sola vez)."""
    return Settings()


settings = get_settings()
