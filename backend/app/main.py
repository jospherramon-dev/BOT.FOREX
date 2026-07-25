"""
BOT.FOREX — Punto de entrada de la API (FastAPI).

Arranque:
    uvicorn app.main:app --reload --port 8000

Swagger UI: http://localhost:8000/docs
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import assets, auth, backtest, bot, broker, telegram, ws
from app.core.config import settings
from app.core.logger import setup_logging
from app.db.database import init_db
from app.engine.trading_engine import resume_enabled_bots
from app.notifications.telegram_service import notifier

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicialización y apagado ordenado de la aplicación."""
    setup_logging()
    init_db()
    await notifier.start()  # Módulo D: escucha el event_bus
    # Tras un corte de luz/reinicio, relanza los bots que quedaron activos.
    try:
        resumed = await resume_enabled_bots()
        if resumed:
            logger.info("Bots reanudados automáticamente: %s", resumed)
    except Exception:  # noqa: BLE001 — el arranque de la API nunca se bloquea
        logger.exception("Error reanudando bots al arrancar")
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

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Convierte cualquier error no controlado en una respuesta que DICE la causa.

    Antes, un fallo inesperado (por ejemplo la base de datos bloqueada o con
    un esquema viejo) llegaba al dashboard como un escueto "Internal Server
    Error": imposible saber qué pasó sin abrir la consola del backend. Ahora
    la traza completa se escribe en el log Y el mensaje devuelto incluye el
    tipo de error y su descripción, que es lo que el usuario ve en pantalla.

    Es una app local de un solo usuario, así que mostrar el detalle ayuda a
    diagnosticar sin exponer nada a terceros. Aun así el texto se recorta,
    para no volcar sentencias SQL enormes en la interfaz.
    """
    logger.exception("Error no controlado en %s %s", request.method, request.url.path)
    detalle = " ".join(str(exc).split())[:300] or exc.__class__.__name__
    return JSONResponse(
        status_code=500,
        content={"detail": f"{exc.__class__.__name__}: {detalle}"},
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
