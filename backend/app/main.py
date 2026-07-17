"""
BOT.FOREX — Punto de entrada de la API (FastAPI).

Arranque:
    uvicorn app.main:app --reload --port 8000

Swagger UI: http://localhost:8000/docs
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import assets, auth, backtest, bot, broker, telegram, ws
from app.core.config import settings
from app.core.logger import setup_logging
from app.db.database import init_db
from app.notifications.telegram_service import notifier

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicialización y apagado ordenado de la aplicación."""
    setup_logging()
    init_db()
    await notifier.start()  # Módulo D: escucha el event_bus
    logger.info("%s iniciado | entorno=%s", settings.APP_NAME, settings.ENVIRONMENT)
    yield
    await notifier.stop()
    logger.info("%s detenido", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "API del Bot de Trading de Forex Automatizado: autenticación, "
        "credenciales de broker cifradas, watchlist de pares, motor de "
        "trading, backtesting y notificaciones."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# CORS: permite que el dashboard React (Vite) consuma la API en desarrollo.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Rutas del Módulo A ------------------------------------------------
app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(broker.router, prefix=settings.API_V1_PREFIX)
app.include_router(assets.router, prefix=settings.API_V1_PREFIX)

# --- Rutas del Módulo B (motor de trading + tiempo real) ----------------
app.include_router(bot.router, prefix=settings.API_V1_PREFIX)
app.include_router(ws.router)  # /ws/live (sin prefijo de versión)

# --- Rutas del Módulo C (backtesting) ------------------------------------
app.include_router(backtest.router, prefix=settings.API_V1_PREFIX)

# --- Rutas del Módulo D (notificaciones Telegram) -------------------------
app.include_router(telegram.router, prefix=settings.API_V1_PREFIX)


@app.get("/health", tags=["Sistema"])
def health_check() -> dict:
    """Endpoint de salud para monitoreo y para el indicador del dashboard."""
    return {"status": "ok", "app": settings.APP_NAME, "version": app.version}
