/**
 * Sección Analytics: estadísticas sobre el historial de operaciones.
 *
 * Los agregados (P/L por día/mes, por par, rachas, promedios) se calculan
 * en el cliente a partir de /bot/trades/history — el backend entrega los
 * trades crudos y esta vista es puramente derivada.
 */

import { Award, Percent, Sigma, TrendingDown, TrendingUp } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
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

const fmt = (n) =>
  n == null ? '—' : Number(n).toLocaleString('es', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const signed = (n) => `${n >= 0 ? '+' : ''}${fmt(n)}`;

/** Agrega P/L por clave temporal ('day' | 'month'). */
function groupProfit(trades, mode) {
  const buckets = new Map();
  for (const t of trades) {
    if (!t.closed_at) continue;
    const d = new Date(t.closed_at);
    const key =
      mode === 'day'
        ? d.toISOString().slice(0, 10)
        : `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    buckets.set(key, (buckets.get(key) ?? 0) + (t.profit ?? 0));
  }
  return [...buckets.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([period, profit]) => ({ period, profit: +profit.toFixed(2) }));
}

function computeStats(trades) {
  const profits = trades.map((t) => t.profit ?? 0);
  const wins = profits.filter((p) => p > 0);
  const losses = profits.filter((p) => p < 0);
  const grossWin = wins.reduce((a, b) => a + b, 0);
  const grossLoss = Math.abs(losses.reduce((a, b) => a + b, 0));

  let bestStreak = 0, worstStreak = 0, cur = 0;
  for (const p of profits) {
    cur = p > 0 ? Math.max(cur, 0) + 1 : p < 0 ? Math.min(cur, 0) - 1 : 0;
    bestStreak = Math.max(bestStreak, cur);
    worstStreak = Math.min(worstStreak, cur);
  }

  return {
    total: trades.length,
    netProfit: profits.reduce((a, b) => a + b, 0),
    winRate: trades.length ? (wins.length / trades.length) * 100 : 0,
    profitFactor: grossLoss > 0 ? grossWin / grossLoss : grossWin > 0 ? Infinity : 0,
    avgWin: wins.length ? grossWin / wins.length : 0,
    avgLoss: losses.length ? -grossLoss / losses.length : 0,
    bestStreak,
    worstStreak: Math.abs(worstStreak),
  };
}

export default function Analytics() {
  const [trades, setTrades] = useState([]);
  const [mode, setMode] = useState('day'); // 'day' | 'month'
  const tradeVersion = useLive((s) => s.tradeVersion);

  useEffect(() => {
    api.get('/bot/trades/history?limit=200').then(setTrades).catch(() => {});
  }, [tradeVersion]);

  const stats = useMemo(() => computeStats(trades), [trades]);
  const periodData = useMemo(() => groupProfit(trades, mode).slice(-31), [trades, mode]);
  const byPair = useMemo(() => {
    const buckets = new Map();
    for (const t of trades) {
      buckets.set(t.symbol, (buckets.get(t.symbol) ?? 0) + (t.profit ?? 0));
    }
    return [...buckets.entries()]
      .map(([symbol, profit]) => ({ symbol, profit: +profit.toFixed(2) }))
      .sort((a, b) => b.profit - a.profit);
  }, [trades]);

  return (
    <div className="space-y-5">
      {/* ── Métricas clave ───────────────────────────────────────── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 xl:grid-cols-6 gap-4">
        <StatCard label="Trades cerrados" value={stats.total} icon={Sigma} />
        <StatCard
          label="P/L neto"
          value={signed(stats.netProfit)}
          tone={stats.netProfit >= 0 ? 'good' : 'bad'}
          icon={Award}
        />
        <StatCard label="Win rate" value={`${stats.winRate.toFixed(1)}%`} icon={Percent} />
        <StatCard
          label="Profit factor"
          value={Number.isFinite(stats.profitFactor) ? stats.profitFactor.toFixed(2) : '∞'}
        />
        <StatCard
          label="Promedio ganador"
          value={signed(stats.avgWin)}
          tone="good"
          icon={TrendingUp}
          sub={`racha máx: ${stats.bestStreak}`}
        />
        <StatCard
          label="Promedio perdedor"
          value={signed(stats.avgLoss)}
          tone="bad"
          icon={TrendingDown}
          sub={`racha máx: ${stats.worstStreak}`}
        />
      </div>

      {/* ── P/L por periodo ──────────────────────────────────────── */}
      <Panel
        title={`Rendimiento por ${mode === 'day' ? 'día' : 'mes'}`}
        actions={
          <div className="flex gap-1">
            {['day', 'month'].map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`rounded px-2 py-1 text-xs font-medium transition-colors ${
                  mode === m ? 'bg-term-accent text-white' : 'text-term-dim hover:text-term-text'
                }`}
              >
                {m === 'day' ? 'Diario' : 'Mensual'}
              </button>
            ))}
          </div>
        }
      >
        {periodData.length === 0 ? (
          <p className="text-sm text-term-muted py-10 text-center">
            Sin operaciones cerradas todavía.
          </p>
        ) : (
          <div className="h-64">
            <ResponsiveContainer>
              <BarChart data={periodData} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
                <CartesianGrid stroke="#1e2b45" vertical={false} />
                <XAxis dataKey="period" stroke="#64748b" fontSize={11} tickLine={false} minTickGap={30} />
                <YAxis stroke="#64748b" fontSize={11} tickLine={false} width={70} tickFormatter={fmt} />
                <Tooltip content={<ChartTooltip formatter={signed} />} cursor={{ fill: '#1e2b4533' }} />
                <ReferenceLine y={0} stroke="#64748b" />
                {/* Polaridad ganancia/pérdida: el color acompaña al signo del valor. */}
                <Bar dataKey="profit" name="P/L" radius={[4, 4, 0, 0]} maxBarSize={28}>
                  {periodData.map((d) => (
                    <Cell key={d.period} fill={d.profit >= 0 ? '#0ca30c' : '#d03b3b'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </Panel>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        {/* ── Distribución por par ─────────────────────────────────── */}
        <Panel title="P/L por par de divisas">
          {byPair.length === 0 ? (
            <p className="text-sm text-term-muted py-10 text-center">Sin datos.</p>
          ) : (
            <div style={{ height: Math.max(160, byPair.length * 44) }}>
              <ResponsiveContainer>
                <BarChart data={byPair} layout="vertical" margin={{ top: 4, right: 40, left: 8, bottom: 0 }}>
                  <CartesianGrid stroke="#1e2b45" horizontal={false} />
                  <XAxis type="number" stroke="#64748b" fontSize={11} tickLine={false} tickFormatter={fmt} />
                  <YAxis type="category" dataKey="symbol" stroke="#94a3b8" fontSize={12} tickLine={false} width={70} />
                  <Tooltip content={<ChartTooltip formatter={signed} />} cursor={{ fill: '#1e2b4533' }} />
                  <ReferenceLine x={0} stroke="#64748b" />
                  <Bar dataKey="profit" name="P/L" radius={[0, 4, 4, 0]} maxBarSize={22}>
                    {byPair.map((d) => (
                      <Cell key={d.symbol} fill={d.profit >= 0 ? '#0ca30c' : '#d03b3b'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Panel>

        {/* ── Últimas operaciones ──────────────────────────────────── */}
        <Panel title="Historial reciente">
          <div className="overflow-x-auto -m-4 max-h-80 overflow-y-auto">
            <table className="w-full">
              <thead className="border-b border-term-border sticky top-0 bg-term-panel">
                <tr>
                  <th className="th">Cierre</th>
                  <th className="th">Par</th>
                  <th className="th">Dir</th>
                  <th className="th">Motivo</th>
                  <th className="th text-right">Pips</th>
                  <th className="th text-right">P/L</th>
                </tr>
              </thead>
              <tbody>
                {trades.length === 0 && (
                  <tr>
                    <td colSpan={6} className="td text-center text-term-muted py-8">
                      Sin operaciones cerradas
                    </td>
                  </tr>
                )}
                {trades.map((t) => (
                  <tr key={t.id} className="border-b border-term-border/50 hover:bg-term-panel2">
                    <td className="td text-term-dim text-xs">
                      {t.closed_at ? new Date(t.closed_at).toLocaleString('es') : '—'}
                    </td>
                    <td className="td font-semibold">{t.symbol}</td>
                    <td className="td"><DirectionBadge direction={t.direction} /></td>
                    <td className="td text-xs text-term-dim">{t.status.replace('CLOSED_', '')}</td>
                    <td className={`td text-right ${t.profit_pips >= 0 ? 'text-term-good' : 'text-term-bad'}`}>
                      {t.profit_pips != null ? signed(t.profit_pips) : '—'}
                    </td>
                    <td className={`td text-right font-medium ${t.profit >= 0 ? 'text-term-good' : 'text-term-bad'}`}>
                      {t.profit != null ? signed(t.profit) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </div>
  );
}
