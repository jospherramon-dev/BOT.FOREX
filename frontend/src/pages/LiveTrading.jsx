/**
 * Sección Live Trading:
 * - Tarjetas de cuenta (balance, equity, margen, P/L flotante).
 * - Gráfico en vivo de equity/balance (alimentado por el WebSocket).
 * - Tabla de operaciones abiertas con cierre manual.
 * - Consola de eventos del sistema en tiempo real.
 */

import { DollarSign, Gauge, Scale, Wallet, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { api } from '../api/client';
import ChartTooltip from '../components/ChartTooltip';
import DirectionBadge from '../components/DirectionBadge';
import Panel from '../components/Panel';
import StatCard from '../components/StatCard';
import { useLive } from '../store/live';

const LEVEL_COLORS = {
  ERROR: 'text-term-bad',
  WARNING: 'text-term-warn',
  TRADE: 'text-term-accent',
  SIGNAL: 'text-purple-400',
  INFO: 'text-term-dim',
};

const fmt = (n, digits = 2) =>
  n == null ? '—' : Number(n).toLocaleString('es', { minimumFractionDigits: digits, maximumFractionDigits: digits });

export default function LiveTrading() {
  const { account, equitySeries, logs, tradeVersion } = useLive();
  const [openTrades, setOpenTrades] = useState([]);
  const [closing, setClosing] = useState(null);
  const consoleRef = useRef(null);

  // Recarga las operaciones abiertas al montar y con cada evento de trade.
  useEffect(() => {
    api.get('/bot/trades/open').then(setOpenTrades).catch(() => {});
  }, [tradeVersion]);

  // Autoscroll de la consola al llegar eventos nuevos.
  useEffect(() => {
    consoleRef.current?.scrollTo({ top: consoleRef.current.scrollHeight });
  }, [logs]);

  const closeTrade = async (trade) => {
    if (!window.confirm(`¿Cerrar ${trade.direction} ${trade.symbol} a mercado?`)) return;
    setClosing(trade.id);
    try {
      await api.post(`/bot/trades/${trade.id}/close`);
    } catch (err) {
      alert(err.message);
    } finally {
      setClosing(null);
    }
  };

  const floating = account ? account.equity - account.balance : null;

  return (
    <div className="space-y-5">
      {/* ── Tarjetas de cuenta ───────────────────────────────────── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Balance" value={fmt(account?.balance)} icon={Wallet} sub={account?.currency} />
        <StatCard label="Equity" value={fmt(account?.equity)} icon={Scale} sub={account?.currency} />
        <StatCard label="Margen libre" value={fmt(account?.margin_free)} icon={Gauge} sub={account?.currency} />
        <StatCard
          label="P/L flotante"
          value={floating == null ? '—' : `${floating >= 0 ? '+' : ''}${fmt(floating)}`}
          icon={DollarSign}
          tone={floating == null ? 'default' : floating >= 0 ? 'good' : 'bad'}
          sub={`${openTrades.length} operación(es) abiertas`}
        />
      </div>

      {/* ── Curva de equity en vivo ──────────────────────────────── */}
      <Panel title="Equity de la cuenta (en vivo)">
        {equitySeries.length < 2 ? (
          <p className="text-sm text-term-muted py-10 text-center">
            Esperando datos del motor… inicie el bot para ver la curva en tiempo real.
          </p>
        ) : (
          <div className="h-64">
            <ResponsiveContainer>
              <AreaChart data={equitySeries} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
                <defs>
                  <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#3987e5" stopOpacity={0.25} />
                    <stop offset="100%" stopColor="#3987e5" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#1e2b45" strokeDasharray="0" vertical={false} />
                <XAxis dataKey="time" stroke="#64748b" fontSize={11} tickLine={false} minTickGap={40} />
                <YAxis
                  stroke="#64748b"
                  fontSize={11}
                  tickLine={false}
                  domain={['auto', 'auto']}
                  tickFormatter={(v) => fmt(v, 0)}
                  width={70}
                />
                <Tooltip content={<ChartTooltip formatter={(v) => fmt(v)} />} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Area
                  type="monotone"
                  dataKey="equity"
                  name="Equity"
                  stroke="#3987e5"
                  strokeWidth={2}
                  fill="url(#equityFill)"
                  dot={false}
                />
                <Area
                  type="monotone"
                  dataKey="balance"
                  name="Balance"
                  stroke="#199e70"
                  strokeWidth={2}
                  strokeDasharray="5 4"
                  fill="none"
                  dot={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </Panel>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        {/* ── Operaciones abiertas ─────────────────────────────────── */}
        <Panel title={`Operaciones abiertas (${openTrades.length})`} className="min-w-0">
          <div className="overflow-x-auto -m-4">
            <table className="w-full">
              <thead className="border-b border-term-border">
                <tr>
                  <th className="th">Par</th>
                  <th className="th">Dir</th>
                  <th className="th">Lote</th>
                  <th className="th">Entrada</th>
                  <th className="th">SL</th>
                  <th className="th">TP</th>
                  <th className="th">BE</th>
                  <th className="th" />
                </tr>
              </thead>
              <tbody>
                {openTrades.length === 0 && (
                  <tr>
                    <td colSpan={8} className="td text-center text-term-muted py-8">
                      Sin posiciones abiertas
                    </td>
                  </tr>
                )}
                {openTrades.map((t) => (
                  <tr key={t.id} className="border-b border-term-border/50 hover:bg-term-panel2">
                    <td className="td font-semibold">{t.symbol}</td>
                    <td className="td"><DirectionBadge direction={t.direction} /></td>
                    <td className="td">{t.lot_size}</td>
                    <td className="td">{t.entry_price}</td>
                    <td className="td text-term-bad">{t.stop_loss ?? '—'}</td>
                    <td className="td text-term-good">{t.take_profit ?? '—'}</td>
                    <td className="td">{t.break_even_applied ? '🛡️' : '—'}</td>
                    <td className="td text-right">
                      <button
                        onClick={() => closeTrade(t)}
                        disabled={closing === t.id}
                        title="Cerrar a mercado"
                        className="btn-ghost !px-2 !py-1 text-xs hover:!border-term-bad hover:!text-term-bad"
                      >
                        <X className="w-3.5 h-3.5" /> Cerrar
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        {/* ── Consola de eventos ───────────────────────────────────── */}
        <Panel title="Consola del sistema" className="min-w-0">
          <div
            ref={consoleRef}
            className="-m-4 h-72 overflow-y-auto bg-term-panel2 font-mono text-xs leading-5 p-3"
          >
            {logs.length === 0 && (
              <p className="text-term-muted">— sin eventos todavía —</p>
            )}
            {logs.map((log, i) => (
              <p key={i} className="whitespace-pre-wrap break-words">
                <span className="text-term-muted">
                  {log.ts ? new Date(log.ts).toLocaleTimeString('es', { hour12: false }) : '--:--'}
                </span>{' '}
                <span className={`font-semibold ${LEVEL_COLORS[log.level] ?? 'text-term-dim'}`}>
                  [{log.level}]
                </span>{' '}
                <span className="text-term-text">{log.message}</span>
              </p>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}
