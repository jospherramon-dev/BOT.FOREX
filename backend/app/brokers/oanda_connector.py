"""
Conector OANDA (API REST v20) — multiplataforma, ideal para desarrollo.

Usa httpx en modo síncrono (la interfaz BrokerConnector es síncrona y el
motor la ejecuta en threadpool). Funciona con cuentas practice (demo) y
live cambiando el host base.

Documentación oficial: https://developer.oanda.com/rest-live-v20/introduction/
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx
import pandas as pd

from app.brokers.base import (
    AccountInfo,
    BrokerConnector,
    OpenPosition,
    OrderResult,
    TickPrice,
)

logger = logging.getLogger(__name__)

_PRACTICE_HOST = "https://api-fxpractice.oanda.com"
_LIVE_HOST = "https://api-fxtrade.oanda.com"

# Timeframe interno → granularidad OANDA
_GRANULARITY = {
    "M1": "M1", "M5": "M5", "M15": "M15", "M30": "M30",
    "H1": "H1", "H4": "H4", "D1": "D",
}


def _to_oanda_symbol(symbol: str) -> str:
    """'EURUSD' → 'EUR_USD' (formato de instrumento OANDA)."""
    return f"{symbol[:3]}_{symbol[3:]}" if "_" not in symbol else symbol


class OandaConnector(BrokerConnector):
    """Adaptador de la API REST v20 de OANDA a nuestra interfaz."""

    name = "OANDA"

    def __init__(self, api_key: str, account_id: str, is_demo: bool = True) -> None:
        self._api_key = api_key
        self._account_id = account_id
        self._base = _PRACTICE_HOST if is_demo else _LIVE_HOST
        self._client: httpx.Client | None = None

    # --- Helpers internos -------------------------------------------------
    def _http(self) -> httpx.Client:
        if self._client is None:
            raise ConnectionError("OANDA no conectado: llame a connect() primero.")
        return self._client

    def _account_url(self, path: str = "") -> str:
        return f"/v3/accounts/{self._account_id}{path}"

    # --- Ciclo de vida --------------------------------------------------
    def connect(self) -> bool:
        self._client = httpx.Client(
            base_url=self._base,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=15.0,
        )
        try:
            resp = self._client.get(self._account_url("/summary"))
            resp.raise_for_status()
            logger.info("Conectado a OANDA | cuenta=%s (%s)", self._account_id,
                        "demo" if self._base == _PRACTICE_HOST else "LIVE")
            return True
        except httpx.HTTPError as exc:
            logger.error("Conexión OANDA falló: %s", exc)
            self._client.close()
            self._client = None
            return False

    def disconnect(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def is_connected(self) -> bool:
        return self._client is not None

    # --- Cuenta y mercado -------------------------------------------------
    def get_account_info(self) -> AccountInfo:
        data = self._http().get(self._account_url("/summary")).json()["account"]
        margin_rate = float(data.get("marginRate") or 0.02)
        return AccountInfo(
            balance=float(data["balance"]),
            equity=float(data["NAV"]),
            margin_free=float(data["marginAvailable"]),
            currency=data["currency"],
            leverage=int(round(1 / margin_rate)) if margin_rate else 50,
        )

    def get_price(self, symbol: str) -> TickPrice:
        resp = self._http().get(
            self._account_url("/pricing"),
            params={"instruments": _to_oanda_symbol(symbol)},
        )
        resp.raise_for_status()
        price = resp.json()["prices"][0]
        return TickPrice(
            symbol=symbol,
            bid=float(price["bids"][0]["price"]),
            ask=float(price["asks"][0]["price"]),
            time=datetime.fromisoformat(price["time"].replace("Z", "+00:00")),
        )

    def get_historical_data(
        self, symbol: str, timeframe: str, date_from: datetime, date_to: datetime
    ) -> pd.DataFrame:
        granularity = _GRANULARITY.get(timeframe)
        if granularity is None:
            raise ValueError(f"Timeframe no soportado: {timeframe}")

        resp = self._http().get(
            f"/v3/instruments/{_to_oanda_symbol(symbol)}/candles",
            params={
                "granularity": granularity,
                "from": date_from.isoformat() + "Z",
                "to": date_to.isoformat() + "Z",
                "price": "M",  # velas por precio medio (mid)
            },
        )
        resp.raise_for_status()
        candles = resp.json()["candles"]

        rows = [
            {
                "time": pd.Timestamp(c["time"]),
                "open": float(c["mid"]["o"]),
                "high": float(c["mid"]["h"]),
                "low": float(c["mid"]["l"]),
                "close": float(c["mid"]["c"]),
                "volume": int(c["volume"]),
            }
            for c in candles
            if c["complete"]
        ]
        if not rows:
            raise ValueError(f"Sin datos históricos para {symbol} {timeframe}")
        return pd.DataFrame(rows).set_index("time")

    # --- Órdenes ---------------------------------------------------------
    def open_order(
        self,
        symbol: str,
        direction: str,
        lot_size: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        comment: str = "BOT.FOREX",
    ) -> OrderResult:
        # OANDA opera en unidades: 1 lote estándar = 100.000 unidades.
        units = int(lot_size * 100_000)
        if direction.upper() == "SELL":
            units = -units

        order: dict = {
            "type": "MARKET",
            "instrument": _to_oanda_symbol(symbol),
            "units": str(units),
            "timeInForce": "FOK",
            "positionFill": "DEFAULT",
            "clientExtensions": {"comment": comment},
        }
        if stop_loss is not None:
            order["stopLossOnFill"] = {"price": f"{stop_loss:.5f}"}
        if take_profit is not None:
            order["takeProfitOnFill"] = {"price": f"{take_profit:.5f}"}

        resp = self._http().post(self._account_url("/orders"), json={"order": order})
        data = resp.json()

        fill = data.get("orderFillTransaction")
        if resp.status_code >= 400 or fill is None:
            reason = data.get("errorMessage") or str(
                data.get("orderCancelTransaction", {}).get("reason", "desconocido")
            )
            logger.error("Orden OANDA rechazada %s %s: %s", direction, symbol, reason)
            return OrderResult(success=False, message=reason)

        # El ticket es el id del trade abierto por el fill.
        ticket = fill.get("tradeOpened", {}).get("tradeID") or fill["id"]
        executed_price = float(fill["price"])
        logger.info(
            "Orden ejecutada %s %s %.2f lotes @ %.5f (trade %s)",
            direction, symbol, lot_size, executed_price, ticket,
        )
        return OrderResult(
            success=True,
            ticket=str(ticket),
            executed_price=executed_price,
            message="Orden ejecutada",
        )

    def modify_position(
        self,
        ticket: str,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> OrderResult:
        body: dict = {}
        if stop_loss is not None:
            body["stopLoss"] = {"price": f"{stop_loss:.5f}", "timeInForce": "GTC"}
        if take_profit is not None:
            body["takeProfit"] = {"price": f"{take_profit:.5f}", "timeInForce": "GTC"}

        resp = self._http().put(
            self._account_url(f"/trades/{ticket}/orders"), json=body
        )
        if resp.status_code >= 400:
            return OrderResult(
                success=False,
                message=resp.json().get("errorMessage", "modify falló"),
            )
        return OrderResult(success=True, ticket=ticket, message="SL/TP modificado")

    def close_position(self, ticket: str) -> OrderResult:
        resp = self._http().put(
            self._account_url(f"/trades/{ticket}/close"), json={"units": "ALL"}
        )
        data = resp.json()
        if resp.status_code >= 400:
            return OrderResult(
                success=False, message=data.get("errorMessage", "close falló")
            )
        fill = data.get("orderFillTransaction", {})
        return OrderResult(
            success=True,
            ticket=ticket,
            executed_price=float(fill["price"]) if fill.get("price") else None,
            message="Posición cerrada",
        )

    def get_open_positions(self) -> list[OpenPosition]:
        resp = self._http().get(self._account_url("/openTrades"))
        resp.raise_for_status()
        trades = resp.json()["trades"]
        return [
            OpenPosition(
                ticket=t["id"],
                symbol=t["instrument"].replace("_", ""),
                direction="BUY" if float(t["currentUnits"]) > 0 else "SELL",
                lot_size=abs(float(t["currentUnits"])) / 100_000,
                entry_price=float(t["price"]),
                stop_loss=(
                    float(t["stopLossOrder"]["price"])
                    if t.get("stopLossOrder") else None
                ),
                take_profit=(
                    float(t["takeProfitOrder"]["price"])
                    if t.get("takeProfitOrder") else None
                ),
                current_profit=float(t["unrealizedPL"]),
            )
            for t in trades
        ]
