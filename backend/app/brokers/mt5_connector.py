"""
Conector MetaTrader 5 (válido también para cuentas Pepperstone MT5).

Requiere el paquete oficial `MetaTrader5` y un terminal MT5 instalado
(SOLO Windows). El import está protegido: en Linux/macOS el módulo carga
sin romper y `connect()` devuelve un error explicativo — así el resto del
sistema (OANDA, backtesting, dashboard) funciona en cualquier SO.
"""

from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd

from app.brokers.base import (
    AccountInfo,
    BrokerConnector,
    ClosedTradeInfo,
    OpenPosition,
    OrderResult,
    SymbolSpecs,
    TickPrice,
)

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5

    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False

# Mapeo timeframe interno → constante MT5 (resuelto en tiempo de ejecución
# porque `mt5` puede no estar disponible en la plataforma).
_TIMEFRAME_ATTRS = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}


class MT5Connector(BrokerConnector):
    """Adaptador de la API oficial de MetaTrader 5 a nuestra interfaz."""

    name = "MT5"

    def __init__(self, login: int, password: str, server: str) -> None:
        self._login = login
        self._password = password
        self._server = server
        self._connected = False

    # --- Ciclo de vida --------------------------------------------------
    def connect(self) -> bool:
        if not MT5_AVAILABLE:
            logger.error(
                "El paquete MetaTrader5 no está instalado (solo Windows). "
                "Use OANDA o instale MT5 en un host Windows."
            )
            return False

        if not mt5.initialize(
            login=self._login, password=self._password, server=self._server
        ):
            logger.error("MT5 initialize() falló: %s", mt5.last_error())
            return False

        self._connected = True
        logger.info("Conectado a MT5 | login=%s server=%s", self._login, self._server)
        return True

    def disconnect(self) -> None:
        if MT5_AVAILABLE and self._connected:
            mt5.shutdown()
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    # --- Cuenta y mercado -------------------------------------------------
    def get_account_info(self) -> AccountInfo:
        info = mt5.account_info()
        if info is None:
            raise ConnectionError(f"MT5 account_info() falló: {mt5.last_error()}")
        return AccountInfo(
            balance=info.balance,
            equity=info.equity,
            margin_free=info.margin_free,
            currency=info.currency,
            leverage=info.leverage,
        )

    def get_price(self, symbol: str) -> TickPrice:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise ValueError(f"Símbolo desconocido en MT5: {symbol}")
        return TickPrice(
            symbol=symbol,
            bid=tick.bid,
            ask=tick.ask,
            time=datetime.fromtimestamp(tick.time),
        )

    def get_historical_data(
        self, symbol: str, timeframe: str, date_from: datetime, date_to: datetime
    ) -> pd.DataFrame:
        tf_attr = _TIMEFRAME_ATTRS.get(timeframe)
        if tf_attr is None:
            raise ValueError(f"Timeframe no soportado: {timeframe}")

        rates = mt5.copy_rates_range(
            symbol, getattr(mt5, tf_attr), date_from, date_to
        )
        if rates is None or len(rates) == 0:
            raise ValueError(
                f"Sin datos históricos para {symbol} {timeframe}: {mt5.last_error()}"
            )

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.set_index("time").rename(columns={"tick_volume": "volume"})
        return df[["open", "high", "low", "close", "volume"]]

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
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return OrderResult(success=False, message=f"Símbolo inválido: {symbol}")

        is_buy = direction.upper() == "BUY"
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot_size,
            "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
            "price": tick.ask if is_buy else tick.bid,
            "sl": stop_loss or 0.0,
            "tp": take_profit or 0.0,
            "deviation": 10,                      # slippage máximo en puntos
            "magic": 900_001,                     # identificador del bot
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            msg = getattr(result, "comment", str(mt5.last_error()))
            logger.error("Orden rechazada %s %s: %s", direction, symbol, msg)
            return OrderResult(success=False, message=msg)

        logger.info(
            "Orden ejecutada %s %s %.2f lotes @ %.5f (ticket %s)",
            direction, symbol, lot_size, result.price, result.order,
        )
        return OrderResult(
            success=True,
            ticket=str(result.order),
            executed_price=result.price,
            message="Orden ejecutada",
        )

    def modify_position(
        self,
        ticket: str,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> OrderResult:
        positions = mt5.positions_get(ticket=int(ticket))
        if not positions:
            return OrderResult(success=False, message=f"Posición {ticket} no existe")
        pos = positions[0]

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": int(ticket),
            "symbol": pos.symbol,
            "sl": stop_loss if stop_loss is not None else pos.sl,
            "tp": take_profit if take_profit is not None else pos.tp,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            return OrderResult(
                success=False, message=getattr(result, "comment", "modify falló")
            )
        return OrderResult(success=True, ticket=ticket, message="SL/TP modificado")

    def close_position(self, ticket: str) -> OrderResult:
        positions = mt5.positions_get(ticket=int(ticket))
        if not positions:
            return OrderResult(success=False, message=f"Posición {ticket} no existe")
        pos = positions[0]

        tick = mt5.symbol_info_tick(pos.symbol)
        is_buy = pos.type == mt5.POSITION_TYPE_BUY
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": int(ticket),
            "symbol": pos.symbol,
            "volume": pos.volume,
            # Para cerrar un BUY se vende, y viceversa.
            "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
            "price": tick.bid if is_buy else tick.ask,
            "deviation": 10,
            "magic": 900_001,
            "comment": "BOT.FOREX close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            return OrderResult(
                success=False, message=getattr(result, "comment", "close falló")
            )
        return OrderResult(
            success=True,
            ticket=ticket,
            executed_price=result.price,
            message="Posición cerrada",
        )

    def get_symbol_specs(self, symbol: str) -> SymbolSpecs:
        """
        Tamaño de contrato y lote mínimo/paso REALES de esta cuenta MT5.

        Crítico en cuentas Micro/Cent (ej. XM Micro: 1 lote = 1.000
        unidades, mínimo 0.1; Exness Cent similar): sin esto, el bot
        calcularía el tamaño de posición asumiendo el estándar de
        100.000 unidades y el riesgo real quedaría mal por un factor de
        10x-100x. Si el símbolo no se encuentra, cae al estándar de la
        clase base.
        """
        info = mt5.symbol_info(symbol)
        if info is None:
            logger.warning(
                "symbol_info(%s) no disponible; usando estándar 100.000 "
                "unidades / lote mínimo 0.01", symbol,
            )
            return super().get_symbol_specs(symbol)
        return SymbolSpecs(
            contract_size=float(info.trade_contract_size),
            volume_min=float(info.volume_min),
            volume_step=float(info.volume_step),
        )

    def get_closed_trade_info(self, ticket: str) -> ClosedTradeInfo | None:
        """Consulta el histórico de deals de la posición cerrada."""
        deals = mt5.history_deals_get(position=int(ticket))
        if not deals:
            return None
        # Los deals de salida (DEAL_ENTRY_OUT) cierran la posición.
        out_deals = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT]
        if not out_deals:
            return None
        profit = sum(d.profit + d.swap + d.commission for d in out_deals)
        return ClosedTradeInfo(exit_price=out_deals[-1].price, profit=profit)

    def get_open_positions(self) -> list[OpenPosition]:
        positions = mt5.positions_get() or []
        return [
            OpenPosition(
                ticket=str(p.ticket),
                symbol=p.symbol,
                direction="BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                lot_size=p.volume,
                entry_price=p.price_open,
                stop_loss=p.sl or None,
                take_profit=p.tp or None,
                current_profit=p.profit,
            )
            for p in positions
        ]
