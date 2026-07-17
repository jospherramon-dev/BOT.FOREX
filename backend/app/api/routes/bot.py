"""
Módulo B — Rutas de control del bot y operaciones.

GET  /bot/config             : configuración de riesgo actual.
PUT  /bot/config             : actualiza parámetros (en caliente).
POST /bot/start              : conecta al broker y arranca el motor.
POST /bot/stop               : detiene el motor y desconecta.
GET  /bot/status             : estado del motor + cuenta.
GET  /bot/trades/open        : operaciones abiertas (para el dashboard).
POST /bot/trades/{id}/close  : cierre manual de una operación.
GET  /bot/trades/history     : historial paginado de operaciones cerradas.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.brokers.factory import create_connector
from app.core.events import event_bus
from app.db.models import BotConfig, BrokerCredential, Trade, TradeStatus
from app.engine import risk_manager as rm
from app.engine.trading_engine import get_engine, start_engine, stop_engine
from app.schemas.trading import BotConfigIn, BotConfigOut, TradeOut
from app.strategies import STRATEGY_REGISTRY

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bot", tags=["Bot"])


def _get_config(db: DBSession, user_id: int) -> BotConfig:
    config = db.scalar(select(BotConfig).where(BotConfig.user_id == user_id))
    if config is None:  # usuarios creados antes de existir BotConfig
        config = BotConfig(user_id=user_id)
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


# ---------------------------------------------------------------------------
# Configuración de riesgo
# ---------------------------------------------------------------------------
@router.get("/config", response_model=BotConfigOut)
def get_config(db: DBSession, current_user: CurrentUser) -> BotConfig:
    return _get_config(db, current_user.id)


@router.put("/config", response_model=BotConfigOut)
def update_config(
    payload: BotConfigIn, db: DBSession, current_user: CurrentUser
) -> BotConfig:
    """
    Actualiza los parámetros de riesgo. El motor los relee en cada ciclo,
    así que aplican inmediatamente sin reiniciar el bot.
    """
    if payload.strategy_name not in STRATEGY_REGISTRY:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Estrategia desconocida. Disponibles: {sorted(STRATEGY_REGISTRY)}",
        )
    config = _get_config(db, current_user.id)
    data = payload.model_dump()
    # strategy_params se persiste serializado (columna strategy_params_json).
    config.strategy_params_json = json.dumps(data.pop("strategy_params"))
    for field, value in data.items():
        setattr(config, field, value)
    db.commit()
    db.refresh(config)
    return config


@router.get("/strategies", response_model=list[dict])
def list_strategies() -> list[dict]:
    """Estrategias disponibles con sus parámetros por defecto (para el selector)."""
    return [
        {
            "name": cls.name,
            "description": cls.description,
            "default_params": cls.default_params(),
        }
        for cls in STRATEGY_REGISTRY.values()
    ]


# ---------------------------------------------------------------------------
# Arranque / parada / estado
# ---------------------------------------------------------------------------
@router.post("/start")
async def start_bot(db: DBSession, current_user: CurrentUser) -> dict:
    """Conecta con la credencial activa del usuario y arranca el motor."""
    engine = get_engine(current_user.id)
    if engine is not None and engine.is_running:
        return {"running": True, "message": "El bot ya estaba en ejecución"}

    credential = db.scalar(
        select(BrokerCredential).where(
            BrokerCredential.user_id == current_user.id,
            BrokerCredential.is_active.is_(True),
        )
    )
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No hay credenciales de broker activas. Configúrelas primero.",
        )

    try:
        connector = create_connector(credential)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    connected = await asyncio.to_thread(connector.connect)
    if not connected:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se pudo conectar con el broker: verifique credenciales.",
        )

    config = _get_config(db, current_user.id)
    config.bot_enabled = True
    db.commit()

    await start_engine(current_user.id, connector)
    await event_bus.publish(
        "bot_status", {"user_id": current_user.id, "running": True}
    )
    return {"running": True, "message": "Bot iniciado"}


@router.post("/stop")
async def stop_bot(db: DBSession, current_user: CurrentUser) -> dict:
    """Detiene el motor. Las posiciones abiertas NO se cierran (usar close manual)."""
    config = _get_config(db, current_user.id)
    config.bot_enabled = False
    db.commit()

    stopped = await stop_engine(current_user.id)
    await event_bus.publish(
        "bot_status", {"user_id": current_user.id, "running": False}
    )
    return {
        "running": False,
        "message": "Bot detenido" if stopped else "El bot no estaba en ejecución",
    }


@router.get("/status")
async def bot_status(db: DBSession, current_user: CurrentUser) -> dict:
    """Estado del motor y snapshot de la cuenta (para la cabecera del dashboard)."""
    engine = get_engine(current_user.id)
    running = engine is not None and engine.is_running

    account = None
    if running:
        try:
            info = await asyncio.to_thread(engine.connector.get_account_info)
            account = {
                "balance": info.balance,
                "equity": info.equity,
                "margin_free": info.margin_free,
                "currency": info.currency,
                "leverage": info.leverage,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("No se pudo leer la cuenta: %s", exc)

    open_trades = len(
        db.scalars(
            select(Trade.id).where(
                Trade.user_id == current_user.id, Trade.status == TradeStatus.OPEN
            )
        ).all()
    )
    return {"running": running, "open_trades": open_trades, "account": account}


# ---------------------------------------------------------------------------
# Operaciones
# ---------------------------------------------------------------------------
@router.get("/trades/open", response_model=list[TradeOut])
def open_trades(db: DBSession, current_user: CurrentUser) -> list[Trade]:
    return list(
        db.scalars(
            select(Trade)
            .where(Trade.user_id == current_user.id,
                   Trade.status == TradeStatus.OPEN)
            .order_by(Trade.opened_at.desc())
        )
    )


@router.get("/trades/history", response_model=list[TradeOut])
def trade_history(
    db: DBSession,
    current_user: CurrentUser,
    limit: int = 50,
    offset: int = 0,
) -> list[Trade]:
    return list(
        db.scalars(
            select(Trade)
            .where(Trade.user_id == current_user.id,
                   Trade.status != TradeStatus.OPEN)
            .order_by(Trade.closed_at.desc())
            .limit(min(limit, 200))
            .offset(offset)
        )
    )


@router.post("/trades/{trade_id}/close", response_model=TradeOut)
async def close_trade_manually(
    trade_id: int, db: DBSession, current_user: CurrentUser
) -> Trade:
    """
    Cierre manual desde el dashboard. Requiere el motor en ejecución
    (es quien mantiene la sesión con el broker).
    """
    trade = db.get(Trade, trade_id)
    if trade is None or trade.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Operación no encontrada")
    if trade.status != TradeStatus.OPEN:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="La operación ya está cerrada")

    engine = get_engine(current_user.id)
    if engine is None or not engine.is_running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El bot debe estar en ejecución para cerrar posiciones.",
        )

    result = await asyncio.to_thread(
        engine.connector.close_position, trade.broker_ticket
    )
    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"El broker rechazó el cierre: {result.message}",
        )

    pip_size = 0.01 if "JPY" in trade.symbol else 0.0001
    exit_price = result.executed_price
    info = await asyncio.to_thread(
        engine.connector.get_closed_trade_info, trade.broker_ticket
    )

    profit = info.profit if info else None
    if exit_price is None and info:
        exit_price = info.exit_price

    pips = (
        rm.profit_pips(trade.direction.value, trade.entry_price, exit_price, pip_size)
        if exit_price is not None else 0.0
    )
    if profit is None and exit_price is not None:
        pip_value = rm.pip_value_per_lot(trade.symbol, pip_size, exit_price)
        profit = round(pips * pip_value * trade.lot_size, 2)

    trade.status = TradeStatus.CLOSED_MANUAL
    trade.exit_price = exit_price
    trade.profit = profit
    trade.profit_pips = round(pips, 1)
    trade.closed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(trade)

    await event_bus.publish(
        "trade_closed",
        {
            "user_id": current_user.id,
            "trade_id": trade.id,
            "symbol": trade.symbol,
            "direction": trade.direction.value,
            "status": trade.status.value,
            "exit_price": exit_price,
            "profit": profit,
            "profit_pips": trade.profit_pips,
        },
    )
    return trade
