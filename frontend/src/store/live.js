/**
 * Store de datos en tiempo real (zustand).
 *
 * Recibe los eventos del WebSocket y mantiene:
 * - logs      : consola de eventos (máx. 300 líneas).
 * - account   : último snapshot de cuenta {balance, equity, ...}.
 * - equitySeries : serie temporal de equity para el gráfico en vivo.
 * - botRunning / wsConnected : indicadores de estado.
 * - tradeVersion : contador que dispara el refetch de operaciones abiertas.
 */

import { create } from 'zustand';

const MAX_LOGS = 300;
const MAX_EQUITY_POINTS = 240;

export const useLive = create((set) => ({
  logs: [],
  account: null,
  equitySeries: [],
  botRunning: false,
  wsConnected: false,
  tradeVersion: 0,

  setWsConnected: (wsConnected) => set({ wsConnected }),
  setBotRunning: (botRunning) => set({ botRunning }),

  pushLog: (entry) =>
    set((s) => ({ logs: [...s.logs.slice(-(MAX_LOGS - 1)), entry] })),

  /** Enruta un evento del EventBus del backend al estado del dashboard. */
  handleEvent: (event) =>
    set((s) => {
      const { type, payload, ts } = event;
      const next = {};

      if (type === 'snapshot') {
        next.logs = (payload.logs ?? []).slice(-MAX_LOGS).map((l) => ({
          ts: l.timestamp,
          level: l.level,
          message: l.message,
        }));
      } else if (type === 'log') {
        next.logs = [
          ...s.logs.slice(-(MAX_LOGS - 1)),
          { ts, level: payload.level, message: payload.message },
        ];
      } else if (type === 'signal') {
        next.logs = [
          ...s.logs.slice(-(MAX_LOGS - 1)),
          {
            ts,
            level: 'SIGNAL',
            message: `${payload.symbol}: ${payload.signal} — ${payload.reason}`,
          },
        ];
      } else if (type === 'account') {
        next.account = payload;
        next.equitySeries = [
          ...s.equitySeries.slice(-(MAX_EQUITY_POINTS - 1)),
          {
            time: new Date(ts).toLocaleTimeString('es', { hour12: false }),
            equity: payload.equity,
            balance: payload.balance,
          },
        ];
      } else if (type === 'bot_status') {
        next.botRunning = payload.running;
      } else if (['trade_opened', 'trade_closed', 'trade_updated'].includes(type)) {
        // Notifica a las vistas que deben refrescar sus tablas.
        next.tradeVersion = s.tradeVersion + 1;
        const msg =
          type === 'trade_opened'
            ? `ABIERTA ${payload.direction} ${payload.symbol} @ ${payload.entry_price}`
            : type === 'trade_closed'
              ? `CERRADA ${payload.symbol} [${payload.status}] P/L ${payload.profit >= 0 ? '+' : ''}${payload.profit}`
              : `SL ajustado en ${payload.symbol} → ${payload.stop_loss} (${payload.reason})`;
        next.logs = [
          ...s.logs.slice(-(MAX_LOGS - 1)),
          { ts, level: 'TRADE', message: msg },
        ];
      }
      return next;
    }),
}));
