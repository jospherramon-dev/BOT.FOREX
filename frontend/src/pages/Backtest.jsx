/**
 * Sección Backtest:
 * - Gestión de datasets CSV (subir / listar / borrar).
 * - Formulario de simulación (estrategia + riesgo + fechas).
 * - Resultados: métricas, curva de equity y tabla de operaciones.
 * - Historial de simulaciones anteriores.
 */

import { CheckCircle2, Eye, FileUp, Loader2, Play, SlidersHorizontal, Trash2 } from 'lucide-react';
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

const fmt = (n) =>
  n == null ? '—' : Number(n).toLocaleString('es', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const signed = (n) => `${n >= 0 ? '+' : ''}${fmt(n)}`;

/** "10, 12,15" → [10, 12, 15] (ignora entradas no numéricas). */
const parseList = (text) =>
  String(text ?? '')
    .split(',')
    .map((s) => parseFloat(s.trim()))
    .filter((n) => Number.isFinite(n));

/**
 * Panel de optimización: define listas de valores para SL/TP/break-even y
 * parámetros de la estrategia (p. ej. umbrales de RSI), lanza el barrido en
 * el backend y va rellenando la tabla comparativa con el progreso en vivo.
 * Cada fila puede aplicarse al bot con un clic.
 */
function OptimizationPanel({ form, strategies }) {
  const [grids, setGrids] = useState({ sl: '', tp: '', be: '' });
  const [validSplit, setValidSplit] = useState('30');
  const [paramGrids, setParamGrids] = useState({});
  const [job, setJob] = useState(null);
  const [error, setError] = useState('');
  const [applied, setApplied] = useState(null);
  const [runsHistory, setRunsHistory] = useState([]);
  const pollRef = useRef(null);

  const strategy = strategies.find((s) => s.name === form.strategy_name);
  const numericParams = Object.entries(strategy?.default_params ?? {}).filter(
    ([, v]) => typeof v === 'number',
  );

  // El historial es PERMANENTE (queda en la base de datos): sobrevive a
  // cerrar el navegador, reiniciar el backend, o lanzar más optimizaciones.
  const refreshRunsHistory = () =>
    api.get('/backtest/optimize-runs').then(setRunsHistory).catch(() => {});
  useEffect(() => { refreshRunsHistory(); }, []);

  // Detiene el polling al desmontar la página.
  useEffect(() => () => clearInterval(pollRef.current), []);

  const poll = (jobId) => {
    clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const snapshot = await api.get(`/backtest/optimize/${jobId}`);
        setJob(snapshot);
        if (snapshot.status !== 'running') {
          clearInterval(pollRef.current);
          refreshRunsHistory(); // el barrido recién terminado ya quedó guardado
        }
      } catch {
        clearInterval(pollRef.current);
      }
    }, 2000);
  };

  const start = async () => {
    setError('');
    setApplied(null);
    setJob(null);
    try {
      const strategy_param_grid = {};
      for (const [name, text] of Object.entries(paramGrids)) {
        const values = parseList(text);
        if (values.length > 0) strategy_param_grid[name] = values;
      }
      const payload = {
        dataset: form.dataset,
        symbol: form.symbol,
        timeframe: form.timeframe,
        initial_balance: +form.initial_balance,
        spread_pips: +form.spread_pips,
        strategy_name: form.strategy_name,
        risk_per_trade_pct: +form.risk_per_trade_pct,
        stop_loss_pips: +form.stop_loss_pips,
        take_profit_pips: +form.take_profit_pips,
        atr_sl_enabled: form.atr_sl_enabled,
        atr_period: +form.atr_period,
        atr_sl_multiplier: +form.atr_sl_multiplier,
        atr_tp_ratio: +form.atr_tp_ratio,
        atr_sl_min_pips: +form.atr_sl_min_pips,
        break_even_enabled: form.break_even_enabled,
        break_even_trigger_pips: +form.break_even_trigger_pips,
        trailing_stop_enabled: form.trailing_stop_enabled,
        trailing_stop_pips: +form.trailing_stop_pips,
        max_drawdown_pct: +form.max_drawdown_pct,
        drawdown_cooldown_bars: +form.drawdown_cooldown_bars,
        stop_loss_grid: parseList(grids.sl),
        take_profit_grid: parseList(grids.tp),
        break_even_grid: parseList(grids.be),
        strategy_param_grid,
        validation_split: Math.min(Math.max((parseFloat(validSplit) || 0) / 100, 0), 0.5),
      };
      const { job_id, total_combinations } = await api.post('/backtest/optimize', payload);
      setJob({ job_id, status: 'running', completed: 0, total: total_combinations, results: [] });
      poll(job_id);
    } catch (err) {
      setError(err.message);
    }
  };

  /** Recarga una optimización pasada desde el historial permanente. */
  const loadHistoricalRun = async (id) => {
    setError('');
    clearInterval(pollRef.current);
    try {
      setJob(await api.get(`/backtest/optimize-runs/${id}`));
    } catch (err) {
      setError(err.message);
    }
  };

  /** Escribe la fila elegida en la configuración del bot (aplica en caliente). */
  const applyToBot = async (row) => {
    try {
      const current = await api.get('/bot/config');
      await api.put('/bot/config', {
        ...current,
        strategy_name: form.strategy_name,
        strategy_params: { ...current.strategy_params, ...row.strategy_params },
        stop_loss_pips: row.stop_loss_pips,
        take_profit_pips: row.take_profit_pips,
        break_even_trigger_pips: row.break_even_trigger_pips,
      });
      setApplied(row);
    } catch (err) {
      setError(err.message);
    }
  };

  const sweptParams = job?.results?.length
    ? Object.keys(job.results[0].strategy_params ?? {})
    : [];
  const running = job?.status === 'running';
  const progressPct = job?.total ? Math.round((job.completed / job.total) * 100) : 0;
  const hasValidation = job?.results?.some((r) => r.validation != null);

  return (
    <Panel
      title="Optimización de parámetros (grid search)"
      actions={
        running && (
          <span className="text-xs text-term-dim tabular">
            {job.completed}/{job.total} combinaciones
          </span>
        )
      }
    >
      <p className="text-xs text-term-muted mb-3">
        Liste los valores a probar separados por comas (vacío = usar el valor del formulario
        superior). Usa el dataset, spread y estrategia seleccionados arriba. El % de
        validación reserva el tramo FINAL del histórico como out-of-sample: cada combinación
        se simula también ahí, fuera del barrido — si gana en optimización pero pierde en
        validación, está sobreajustada.
      </p>

      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        <div>
          <label className="label">SL (pips)</label>
          <input className="input" placeholder="10, 12, 15" value={grids.sl}
                 onChange={(e) => setGrids({ ...grids, sl: e.target.value })} />
        </div>
        <div>
          <label className="label">TP (pips)</label>
          <input className="input" placeholder="15, 18, 24" value={grids.tp}
                 onChange={(e) => setGrids({ ...grids, tp: e.target.value })} />
        </div>
        <div>
          <label className="label">BE trigger (pips)</label>
          <input className="input" placeholder="6, 8, 10" value={grids.be}
                 onChange={(e) => setGrids({ ...grids, be: e.target.value })} />
        </div>
        <div>
          <label className="label">Validación % (OOS)</label>
          <input className="input" type="number" min="0" max="50" placeholder="30 (0 = off)"
                 value={validSplit} onChange={(e) => setValidSplit(e.target.value)} />
        </div>
        {numericParams.map(([name, def]) => (
          <div key={name}>
            <label className="label">{name}</label>
            <input
              className="input"
              placeholder={`${def} (fijo)`}
              value={paramGrids[name] ?? ''}
              onChange={(e) => setParamGrids({ ...paramGrids, [name]: e.target.value })}
            />
          </div>
        ))}
      </div>

      <div className="mt-4 flex items-center gap-3 flex-wrap">
        <button onClick={start} disabled={running || !form.dataset} className="btn-primary">
          {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <SlidersHorizontal className="w-4 h-4" />}
          {running ? 'Optimizando…' : 'Iniciar optimización'}
        </button>
        {!form.dataset && <span className="text-xs text-term-muted">Seleccione un dataset</span>}
        {error && <span className="text-sm text-term-bad">{error}</span>}
        {applied && (
          <span className="flex items-center gap-1.5 text-sm text-term-good">
            <CheckCircle2 className="w-4 h-4" />
            Aplicado al bot: SL {applied.stop_loss_pips} / TP {applied.take_profit_pips} — el
            motor lo usa en el próximo ciclo y gestionará el SL automáticamente.
          </span>
        )}
      </div>

      {/* Detalle del split cronológico in-sample / out-of-sample */}
      {job?.valid_rows > 0 && (
        <p className="mt-3 text-xs text-term-dim tabular">
          Optimización: {job.train_rows?.toLocaleString('es')} velas (hasta{' '}
          {job.train_end?.slice(0, 16).replace('T', ' ')}) · Validación OOS:{' '}
          {job.valid_rows?.toLocaleString('es')} velas posteriores, nunca vistas por el barrido.
        </p>
      )}

      {/* Barra de progreso del barrido */}
      {job && (
        <div className="mt-4 h-1.5 rounded-full bg-term-panel2 overflow-hidden">
          <div
            className={`h-full transition-all ${job.status === 'error' ? 'bg-term-bad' : 'bg-term-accent'}`}
            style={{ width: `${progressPct}%` }}
          />
        </div>
      )}
      {job?.status === 'error' && (
        <p className="mt-2 text-sm text-term-bad">Barrido fallido: {job.error}</p>
      )}

      {/* Tabla comparativa (ordenada por P/L neto) */}
      {job?.results?.length > 0 && (
        <div className="mt-4 overflow-x-auto max-h-96 overflow-y-auto border border-term-border rounded-md">
          <table className="w-full">
            <thead className="border-b border-term-border sticky top-0 bg-term-panel">
              <tr>
                <th className="th">#</th>
                <th className="th text-right">SL</th>
                <th className="th text-right">TP</th>
                <th className="th text-right">BE</th>
                {sweptParams.map((p) => (
                  <th key={p} className="th text-right">{p}</th>
                ))}
                <th className="th text-right">Trades</th>
                <th className="th text-right">Win rate</th>
                <th className="th text-right">PF</th>
                <th className="th text-right">P/L optim.</th>
                {hasValidation && <th className="th text-right">P/L valid.</th>}
                {hasValidation && <th className="th text-right">PF valid.</th>}
                <th className="th text-right">DD%</th>
                <th className="th text-right">Sharpe</th>
                <th className="th" />
              </tr>
            </thead>
            <tbody>
              {job.results.map((r, i) => (
                <tr
                  key={i}
                  className={`border-b border-term-border/50 hover:bg-term-panel2 ${
                    i === 0 ? 'bg-term-good/5' : ''
                  }`}
                >
                  <td className="td text-term-muted">{i + 1}{i === 0 && ' 🏆'}</td>
                  <td className="td text-right">{r.stop_loss_pips}</td>
                  <td className="td text-right">{r.take_profit_pips}</td>
                  <td className="td text-right">{r.break_even_trigger_pips}</td>
                  {sweptParams.map((p) => (
                    <td key={p} className="td text-right">{r.strategy_params?.[p]}</td>
                  ))}
                  <td className="td text-right">{r.metrics.total_trades}</td>
                  <td className="td text-right">{r.metrics.win_rate}%</td>
                  <td className="td text-right">{r.metrics.profit_factor}</td>
                  <td className={`td text-right font-medium ${r.metrics.net_profit >= 0 ? 'text-term-good' : 'text-term-bad'}`}>
                    {signed(r.metrics.net_profit)}
                  </td>
                  {hasValidation && (
                    <td
                      className={`td text-right font-medium ${
                        (r.validation?.net_profit ?? 0) >= 0 ? 'text-term-good' : 'text-term-bad'
                      }`}
                      title="P/L en el tramo de validación (nunca visto por el barrido)"
                    >
                      {r.validation ? signed(r.validation.net_profit) : '—'}
                      {r.metrics.net_profit > 0 && (r.validation?.net_profit ?? 0) < 0 && ' ⚠'}
                    </td>
                  )}
                  {hasValidation && (
                    <td className="td text-right">
                      {r.validation ? r.validation.profit_factor : '—'}
                    </td>
                  )}
                  <td className="td text-right">{r.metrics.max_drawdown_pct}%</td>
                  <td className="td text-right">{r.metrics.sharpe_ratio}</td>
                  <td className="td text-right">
                    <button
                      onClick={() => applyToBot(r)}
                      className="btn-ghost !px-2 !py-1 text-xs"
                      title="Escribir estos parámetros en la configuración del bot"
                    >
                      Aplicar al bot
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Historial PERMANENTE: cada barrido queda guardado en la base de
          datos apenas termina, sin importar que cierres el navegador,
          reinicies el servidor, o corras más optimizaciones después. */}
      {runsHistory.length > 0 && (
        <div className="mt-6">
          <p className="text-xs font-semibold uppercase tracking-wider text-term-dim mb-2">
            Historial de optimizaciones (guardado permanentemente)
          </p>
          <div className="overflow-x-auto border border-term-border rounded-md">
            <table className="w-full">
              <thead className="border-b border-term-border">
                <tr>
                  <th className="th">Fecha</th>
                  <th className="th">Estrategia</th>
                  <th className="th">Par</th>
                  <th className="th text-right">Combos</th>
                  <th className="th text-right">Mejor SL/TP/BE</th>
                  <th className="th text-right">P/L optim.</th>
                  <th className="th text-right">P/L valid.</th>
                  <th className="th text-right">PF valid.</th>
                  <th className="th" />
                </tr>
              </thead>
              <tbody>
                {runsHistory.map((r) => (
                  <tr key={r.id} className="border-b border-term-border/50 hover:bg-term-panel2">
                    <td className="td text-xs text-term-dim">
                      {new Date(r.created_at).toLocaleString('es')}
                    </td>
                    <td className="td">{r.strategy_name}</td>
                    <td className="td font-semibold">{r.symbol}</td>
                    <td className="td text-right">{r.total_combinations}</td>
                    <td className="td text-right">
                      {r.best_stop_loss_pips}/{r.best_take_profit_pips}/{r.best_break_even_trigger_pips}
                    </td>
                    <td className={`td text-right ${r.best_net_profit >= 0 ? 'text-term-good' : 'text-term-bad'}`}>
                      {signed(r.best_net_profit)}
                    </td>
                    <td className={`td text-right ${(r.best_validation_net_profit ?? 0) >= 0 ? 'text-term-good' : 'text-term-bad'}`}>
                      {r.best_validation_net_profit != null ? signed(r.best_validation_net_profit) : '—'}
                    </td>
                    <td className="td text-right">{r.best_validation_profit_factor ?? '—'}</td>
                    <td className="td text-right">
                      <button
                        onClick={() => loadHistoricalRun(r.id)}
                        className="btn-ghost !px-2 !py-1 text-xs"
                        title="Ver la tabla completa de este barrido"
                      >
                        <Eye className="w-3.5 h-3.5" /> Ver tabla
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Panel>
  );
}

const DEFAULT_FORM = {
  dataset: '',
  symbol: 'EURUSD',
  timeframe: 'M15',
  date_from: '',
  date_to: '',
  initial_balance: 10000,
  spread_pips: 1.0,
  strategy_name: 'ma_rsi_crossover',
  risk_per_trade_pct: 1.0,
  stop_loss_pips: 30,
  take_profit_pips: 60,
  atr_sl_enabled: false,
  atr_period: 14,
  atr_sl_multiplier: 1.5,
  atr_tp_ratio: 2.0,
  atr_sl_min_pips: 5,
  break_even_enabled: true,
  break_even_trigger_pips: 20,
  trailing_stop_enabled: false,
  trailing_stop_pips: 15,
  max_drawdown_pct: 0,
  drawdown_cooldown_bars: 480,
  strategy_params: {},
};

export default function Backtest() {
  const [datasets, setDatasets] = useState([]);
  const [strategies, setStrategies] = useState([]);
  const [runs, setRuns] = useState([]);
  const [form, setForm] = useState(DEFAULT_FORM);
  const [result, setResult] = useState(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const fileRef = useRef(null);

  const refreshDatasets = () => api.get('/backtest/datasets').then(setDatasets).catch(() => {});
  const refreshRuns = () => api.get('/backtest/runs').then(setRuns).catch(() => {});

  useEffect(() => {
    refreshDatasets();
    refreshRuns();
    api.get('/bot/strategies').then((list) => {
      setStrategies(list);
      // Poblar los parámetros de la estrategia por defecto para que sus
      // valores se envíen aunque el usuario no toque las casillas.
      const active = list.find((s) => s.name === DEFAULT_FORM.strategy_name);
      if (active) {
        setForm((f) => ({
          ...f,
          strategy_params:
            Object.keys(f.strategy_params ?? {}).length ? f.strategy_params : active.default_params,
        }));
      }
    }).catch(() => {});
  }, []);

  const set = (field) => (e) => {
    const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
    setForm({ ...form, [field]: value });
  };

  // Parámetros numéricos de la estrategia seleccionada (ej. EMA_TREND_PERIOD).
  const selectedStrategy = strategies.find((s) => s.name === form.strategy_name);
  const strategyNumericParams = Object.entries(selectedStrategy?.default_params ?? {})
    .filter(([, v]) => typeof v === 'number');

  const changeStrategy = (e) => {
    // Al cambiar de estrategia, cargar sus parámetros por defecto.
    const next = strategies.find((s) => s.name === e.target.value);
    setForm({ ...form, strategy_name: e.target.value, strategy_params: next?.default_params ?? {} });
  };

  const setStrategyParam = (name) => (e) =>
    setForm({ ...form, strategy_params: { ...form.strategy_params, [name]: e.target.value } });

  const upload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setError('');
    try {
      const info = await api.upload('/backtest/datasets', file);
      await refreshDatasets();
      setForm((f) => ({ ...f, dataset: info.filename }));
    } catch (err) {
      setError(err.message);
    } finally {
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const removeDataset = async (filename) => {
    if (!window.confirm(`¿Eliminar ${filename}?`)) return;
    await api.del(`/backtest/datasets/${encodeURIComponent(filename)}`);
    refreshDatasets();
  };

  const run = async () => {
    setError('');
    setRunning(true);
    setResult(null);
    try {
      // Convertir los parámetros de estrategia a número antes de enviarlos.
      const strategy_params = {};
      for (const [name, value] of Object.entries(form.strategy_params ?? {})) {
        strategy_params[name] = typeof value === 'number' ? value : +value;
      }
      const payload = {
        ...form,
        strategy_params,
        initial_balance: +form.initial_balance,
        spread_pips: +form.spread_pips,
        risk_per_trade_pct: +form.risk_per_trade_pct,
        stop_loss_pips: +form.stop_loss_pips,
        take_profit_pips: +form.take_profit_pips,
        atr_period: +form.atr_period,
        atr_sl_multiplier: +form.atr_sl_multiplier,
        atr_tp_ratio: +form.atr_tp_ratio,
        atr_sl_min_pips: +form.atr_sl_min_pips,
        break_even_trigger_pips: +form.break_even_trigger_pips,
        trailing_stop_pips: +form.trailing_stop_pips,
        max_drawdown_pct: +form.max_drawdown_pct,
        drawdown_cooldown_bars: +form.drawdown_cooldown_bars,
        date_from: form.date_from ? new Date(form.date_from).toISOString() : null,
        date_to: form.date_to ? new Date(form.date_to).toISOString() : null,
      };
      const res = await api.post('/backtest/run', payload);
      setResult(res);
      refreshRuns();
    } catch (err) {
      setError(err.message);
    } finally {
      setRunning(false);
    }
  };

  const m = result?.metrics;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        {/* ── Datasets ─────────────────────────────────────────────── */}
        <Panel
          title="Datos históricos"
          actions={
            <button onClick={() => fileRef.current?.click()} className="btn-ghost !py-1 !px-2 text-xs">
              <FileUp className="w-3.5 h-3.5" /> Subir CSV
            </button>
          }
        >
          <input ref={fileRef} type="file" accept=".csv" onChange={upload} className="hidden" />
          <ul className="space-y-2 max-h-56 overflow-y-auto">
            {datasets.length === 0 && (
              <li className="text-sm text-term-muted py-4 text-center">
                Suba un CSV con columnas time, open, high, low, close.
              </li>
            )}
            {datasets.map((d) => (
              <li
                key={d.filename}
                className={`flex items-center justify-between gap-2 rounded-md border px-3 py-2 cursor-pointer transition-colors ${
                  form.dataset === d.filename
                    ? 'border-term-accent bg-term-accent/10'
                    : 'border-term-border hover:border-term-muted'
                }`}
                onClick={() => setForm({ ...form, dataset: d.filename })}
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate">{d.filename}</p>
                  <p className="text-xs text-term-muted tabular">
                    {d.rows.toLocaleString('es')} velas · {d.date_from.slice(0, 10)} →{' '}
                    {d.date_to.slice(0, 10)}
                  </p>
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    removeDataset(d.filename);
                  }}
                  className="text-term-muted hover:text-term-bad shrink-0"
                  title="Eliminar dataset"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </li>
            ))}
          </ul>
        </Panel>

        {/* ── Configuración de la simulación ──────────────────────── */}
        <Panel title="Parámetros de simulación" className="xl:col-span-2">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div>
              <label className="label">Par</label>
              <input className="input" value={form.symbol} onChange={set('symbol')} />
            </div>
            <div>
              <label className="label">Timeframe</label>
              <select className="input" value={form.timeframe} onChange={set('timeframe')}>
                {['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1'].map((tf) => (
                  <option key={tf}>{tf}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Desde</label>
              <input type="date" className="input" value={form.date_from} onChange={set('date_from')} />
            </div>
            <div>
              <label className="label">Hasta</label>
              <input type="date" className="input" value={form.date_to} onChange={set('date_to')} />
            </div>
            <div>
              <label className="label">Balance inicial</label>
              <input type="number" className="input" value={form.initial_balance} onChange={set('initial_balance')} />
            </div>
            <div>
              <label className="label">Spread (pips)</label>
              <input type="number" step="0.1" className="input" value={form.spread_pips} onChange={set('spread_pips')} />
            </div>
            <div className="col-span-2">
              <label className="label">Estrategia</label>
              <select className="input" value={form.strategy_name} onChange={changeStrategy}>
                {strategies.map((s) => (
                  <option key={s.name} value={s.name}>{s.name}</option>
                ))}
              </select>
            </div>
            {/* Parámetros de la estrategia (ej. EMA_TREND_PERIOD para el filtro) */}
            {strategyNumericParams.map(([name, def]) => (
              <div key={name}>
                <label className="label">{name}</label>
                <input
                  type="number"
                  className="input"
                  value={form.strategy_params?.[name] ?? def}
                  onChange={setStrategyParam(name)}
                />
              </div>
            ))}
            <div>
              <label className="label">Riesgo %</label>
              <input type="number" step="0.1" className="input" value={form.risk_per_trade_pct} onChange={set('risk_per_trade_pct')} />
            </div>
            <div>
              <label className="label">SL (pips)</label>
              <input type="number" className="input" value={form.stop_loss_pips} onChange={set('stop_loss_pips')} />
            </div>
            <div>
              <label className="label">TP (pips)</label>
              <input type="number" className="input" value={form.take_profit_pips} onChange={set('take_profit_pips')} />
            </div>
            <label className="flex items-center gap-2 text-sm text-term-dim col-span-2">
              <input type="checkbox" checked={form.atr_sl_enabled} onChange={set('atr_sl_enabled')} />
              SL/TP por ATR (ignora SL/TP fijos de arriba)
            </label>
            <div>
              <label className="label">ATR período</label>
              <input type="number" className="input" value={form.atr_period} onChange={set('atr_period')} />
            </div>
            <div>
              <label className="label">ATR × mult. (SL)</label>
              <input type="number" step="0.1" className="input" value={form.atr_sl_multiplier} onChange={set('atr_sl_multiplier')} />
            </div>
            <div>
              <label className="label">ATR ratio R:R (TP)</label>
              <input type="number" step="0.1" className="input" value={form.atr_tp_ratio} onChange={set('atr_tp_ratio')} />
            </div>
            <div>
              <label className="label">ATR SL mínimo (pips)</label>
              <input type="number" className="input" value={form.atr_sl_min_pips} onChange={set('atr_sl_min_pips')} />
            </div>
            <div>
              <label className="label">BE trigger (pips)</label>
              <input type="number" className="input" value={form.break_even_trigger_pips} onChange={set('break_even_trigger_pips')} />
            </div>
            <label className="flex items-center gap-2 text-sm text-term-dim col-span-2">
              <input type="checkbox" checked={form.break_even_enabled} onChange={set('break_even_enabled')} />
              Break-even activado
            </label>
            <label className="flex items-center gap-2 text-sm text-term-dim">
              <input type="checkbox" checked={form.trailing_stop_enabled} onChange={set('trailing_stop_enabled')} />
              Trailing stop
            </label>
            <div>
              <label className="label">Trailing (pips)</label>
              <input type="number" className="input" value={form.trailing_stop_pips} onChange={set('trailing_stop_pips')} />
            </div>
            <div>
              <label className="label">Freno drawdown %</label>
              <input type="number" className="input" placeholder="0 = off" value={form.max_drawdown_pct} onChange={set('max_drawdown_pct')} />
              <p className="mt-1 text-[11px] text-term-muted">
                Pausa las entradas si la cuenta cae este % desde su máximo (0 = desactivado).
              </p>
            </div>
            <div>
              <label className="label">Enfriamiento (velas)</label>
              <input type="number" className="input" value={form.drawdown_cooldown_bars} onChange={set('drawdown_cooldown_bars')} />
              <p className="mt-1 text-[11px] text-term-muted">
                Velas en pausa tras activar el freno (M15: 480 ≈ 5 días).
              </p>
            </div>
          </div>

          <div className="mt-4 flex items-center gap-3">
            <button onClick={run} disabled={running || !form.dataset} className="btn-primary">
              {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
              {running ? 'Simulando…' : 'Ejecutar backtest'}
            </button>
            {!form.dataset && <span className="text-xs text-term-muted">Seleccione un dataset</span>}
            {error && <span className="text-sm text-term-bad">{error}</span>}
          </div>
        </Panel>
      </div>

      {/* ── Resultados ───────────────────────────────────────────── */}
      {m && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 xl:grid-cols-8 gap-4">
            <StatCard label="Trades" value={m.total_trades} />
            <StatCard label="Win rate" value={`${m.win_rate}%`} />
            <StatCard label="Profit factor" value={m.profit_factor} />
            <StatCard
              label="P/L neto"
              value={signed(m.net_profit)}
              tone={m.net_profit >= 0 ? 'good' : 'bad'}
              sub={`${signed(m.return_pct)}%`}
            />
            <StatCard label="Drawdown máx" value={`${m.max_drawdown_pct}%`} tone="bad" />
            <StatCard label="Sharpe" value={m.sharpe_ratio} />
            <StatCard label="Mejor trade" value={signed(m.best_trade)} tone="good" />
            <StatCard label="Peor trade" value={signed(m.worst_trade)} tone="bad" />
          </div>

          <Panel title="Curva de equity">
            <div className="h-72">
              <ResponsiveContainer>
                <AreaChart data={result.equity_curve} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
                  <defs>
                    <linearGradient id="btFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#3987e5" stopOpacity={0.25} />
                      <stop offset="100%" stopColor="#3987e5" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#1e2b45" vertical={false} />
                  <XAxis
                    dataKey="time"
                    stroke="#64748b"
                    fontSize={11}
                    tickLine={false}
                    minTickGap={60}
                    tickFormatter={(v) => v?.slice(0, 10)}
                  />
                  <YAxis stroke="#64748b" fontSize={11} tickLine={false} width={80} domain={['auto', 'auto']} tickFormatter={(v) => fmt(v)} />
                  <Tooltip content={<ChartTooltip formatter={fmt} />} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Area type="monotone" dataKey="equity" name="Equity" stroke="#3987e5" strokeWidth={2} fill="url(#btFill)" dot={false} />
                  <Area type="monotone" dataKey="balance" name="Balance" stroke="#199e70" strokeWidth={2} strokeDasharray="5 4" fill="none" dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </Panel>

          <Panel title={`Operaciones simuladas (${result.trades.length})`}>
            <div className="overflow-x-auto -m-4 max-h-80 overflow-y-auto">
              <table className="w-full">
                <thead className="border-b border-term-border sticky top-0 bg-term-panel">
                  <tr>
                    <th className="th">Entrada</th>
                    <th className="th">Dir</th>
                    <th className="th">Lote</th>
                    <th className="th">Precio</th>
                    <th className="th">Salida</th>
                    <th className="th">Motivo</th>
                    <th className="th text-right">Pips</th>
                    <th className="th text-right">P/L</th>
                  </tr>
                </thead>
                <tbody>
                  {result.trades.map((t, i) => (
                    <tr key={i} className="border-b border-term-border/50 hover:bg-term-panel2">
                      <td className="td text-xs text-term-dim">{t.entry_time?.slice(0, 16).replace('T', ' ')}</td>
                      <td className="td"><DirectionBadge direction={t.direction} /></td>
                      <td className="td">{t.lot_size}</td>
                      <td className="td">{t.entry_price}</td>
                      <td className="td">{t.exit_price ?? '—'}</td>
                      <td className="td text-xs text-term-dim">{t.status.replace('CLOSED_', '')}</td>
                      <td className={`td text-right ${t.profit_pips >= 0 ? 'text-term-good' : 'text-term-bad'}`}>
                        {signed(t.profit_pips)}
                      </td>
                      <td className={`td text-right font-medium ${t.profit >= 0 ? 'text-term-good' : 'text-term-bad'}`}>
                        {signed(t.profit)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      )}

      {/* ── Optimización de parámetros ──────────────────────────── */}
      <OptimizationPanel form={form} strategies={strategies} />

      {/* ── Historial de simulaciones ───────────────────────────── */}
      <Panel title="Simulaciones anteriores">
        <div className="overflow-x-auto -m-4">
          <table className="w-full">
            <thead className="border-b border-term-border">
              <tr>
                <th className="th">Fecha</th>
                <th className="th">Estrategia</th>
                <th className="th">Par</th>
                <th className="th text-right">Trades</th>
                <th className="th text-right">Win rate</th>
                <th className="th text-right">PF</th>
                <th className="th text-right">DD máx</th>
                <th className="th text-right">Sharpe</th>
                <th className="th text-right">Balance final</th>
              </tr>
            </thead>
            <tbody>
              {runs.length === 0 && (
                <tr>
                  <td colSpan={9} className="td text-center text-term-muted py-6">
                    Sin simulaciones todavía
                  </td>
                </tr>
              )}
              {runs.map((r) => (
                <tr key={r.id} className="border-b border-term-border/50 hover:bg-term-panel2">
                  <td className="td text-xs text-term-dim">
                    {new Date(r.created_at).toLocaleString('es')}
                  </td>
                  <td className="td">{r.strategy_name}</td>
                  <td className="td font-semibold">{r.symbol}</td>
                  <td className="td text-right">{r.total_trades}</td>
                  <td className="td text-right">{r.win_rate}%</td>
                  <td className="td text-right">{r.profit_factor}</td>
                  <td className="td text-right text-term-bad">{r.max_drawdown_pct}%</td>
                  <td className="td text-right">{r.sharpe_ratio}</td>
                  <td className={`td text-right font-medium ${r.final_balance >= r.initial_balance ? 'text-term-good' : 'text-term-bad'}`}>
                    {fmt(r.final_balance)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
