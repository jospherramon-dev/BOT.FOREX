"""
Módulo A — Selector dinámico de activos (watchlist de pares Forex).

GET    /assets            : lista los pares del usuario.
POST   /assets            : añade un par (ej. EURUSD M15).
PATCH  /assets/{id}/toggle: activa/desactiva el monitoreo de un par.
DELETE /assets/{id}       : elimina un par de la watchlist.
"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.db.models import Asset
from app.schemas.broker import AssetIn, AssetOut

router = APIRouter(prefix="/assets", tags=["Activos"])

# Pares sugeridos en el dropdown del dashboard (el usuario puede añadir otros).
SUGGESTED_PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD",
    "USDCAD", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY",
]


def _get_owned_asset(db: DBSession, user_id: int, asset_id: int) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None or asset.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Activo no encontrado"
        )
    return asset


@router.get("/suggested", response_model=list[str])
def suggested_pairs() -> list[str]:
    """Pares populares para poblar el selector del dashboard."""
    return SUGGESTED_PAIRS


@router.get("", response_model=list[AssetOut])
def list_assets(db: DBSession, current_user: CurrentUser) -> list[Asset]:
    return list(
        db.scalars(select(Asset).where(Asset.user_id == current_user.id))
    )


@router.post("", response_model=AssetOut, status_code=status.HTTP_201_CREATED)
def add_asset(payload: AssetIn, db: DBSession, current_user: CurrentUser) -> Asset:
    """Añade un par a la watchlist. Los pares JPY usan pip_size 0.01."""
    duplicate = db.scalar(
        select(Asset).where(
            Asset.user_id == current_user.id, Asset.symbol == payload.symbol
        )
    )
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{payload.symbol} ya está en la watchlist",
        )

    # Corrección automática del tamaño de pip para pares con JPY.
    pip_size = 0.01 if "JPY" in payload.symbol else payload.pip_size

    asset = Asset(
        user_id=current_user.id,
        symbol=payload.symbol,
        timeframe=payload.timeframe,
        pip_size=pip_size,
        enabled=payload.enabled,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


@router.patch("/{asset_id}/toggle", response_model=AssetOut)
def toggle_asset(asset_id: int, db: DBSession, current_user: CurrentUser) -> Asset:
    """Activa/desactiva el monitoreo del par sin borrarlo."""
    asset = _get_owned_asset(db, current_user.id, asset_id)
    asset.enabled = not asset.enabled
    db.commit()
    db.refresh(asset)
    return asset


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(asset_id: int, db: DBSession, current_user: CurrentUser) -> None:
    asset = _get_owned_asset(db, current_user.id, asset_id)
    db.delete(asset)
    db.commit()
