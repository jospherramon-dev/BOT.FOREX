/**
 * Sección Configuración, en 4 pestañas:
 * - Broker   : credenciales cifradas + probar conexión.
 * - Activos  : watchlist de pares que el bot monitorea.
 * - Riesgo   : parámetros del motor (SL/TP, break-even, trailing, lote).
 * - Telegram : token + chat_id + probar conexión.
 */

import {
  CheckCircle2,
  KeyRound,
  Loader2,
  PlugZap,
  Plus,
  Send,
  Trash2,
  XCircle,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from '../api/client';
import Panel from '../components/Panel';

const TABS = [
  { id: 'broker', label: 'Broker' },
  { id: 'assets', label: 'Activos' },
  { id: 'risk', label: 'Riesgo' },
  { id: 'telegram', label: 'Telegram' },
];

export default function Settings() {
  const [tab, setTab] = useState('broker');
  return (
    <div className="space-y-5">
      <div className="flex gap-1 border-b border-term-border">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === t.id
                ? 'border-term-accent text-term-text'
                : 'border-transparent text-term-dim hover:text-term-text'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === 'broker' && <BrokerTab />}
      {tab === 'assets' && <AssetsTab />}
      {tab === 'risk' && <RiskTab />}
      {tab === 'telegram' && <TelegramTab />}
    </div>
  );
}

/* ────────────────────────── Broker ────────────────────────── */

function BrokerTab() {
  const [creds, setCreds] = useState([]);
  const [form, setForm] = useState({
    broker_type: 'OANDA', label: 'Mi cuenta', login: '', password: '',
    api_key: '', server: '', account_id: '', is_demo: true, terminal_path: '',
  });
  const [testResult, setTestResult] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const refresh = () => api.get('/broker/credentials').then(setCreds).catch(() => {});
  useEffect(() => { refresh(); }, []);

  const set = (f) => (e) =>
    setForm({ ...form, [f]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });

  const save = async (e) => {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      await api.post('/broker/credentials', form);
      setForm({ ...form, login: '', password: '', api_key: '' });
      refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const test = async (id) => {
    setTestResult({ ...testResult, [id]: { loading: true } });
    try {
      const res = await api.post(`/broker/credentials/${id}/test`);
      setTestResult({ ...testResult, [id]: res });
    } catch (err) {
      setTestResult({ ...testResult, [id]: { success: false, message: err.message } });
    }
  };

  const remove = async (id) => {
    if (!window.confirm('¿Eliminar esta credencial?')) return;
    await api.del(`/broker/credentials/${id}`);
    refresh();
  };

  const isMt5 = form.broker_type !== 'OANDA';

  return (
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
      <Panel title="Nueva conexión de broker">
        <form onSubmit={save} className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Broker</label>
              <select className="input" value={form.broker_type} onChange={set('broker_type')}>
                <option value="OANDA">OANDA (REST v20)</option>
                <option value="MT5">MetaTrader 5</option>
                <option value="PEPPERSTONE">Pepperstone (MT5)</option>
              </select>
            </div>
            <div>
              <label className="label">Etiqueta</label>
              <input className="input" value={form.label} onChange={set('label')} />
            </div>
          </div>

          {isMt5 ? (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Login</label>
                <input className="input" value={form.login} onChange={set('login')} required />
              </div>
              <div>
                <label className="label">Password</label>
                <input type="password" className="input" value={form.password} onChange={set('password')} required />
              </div>
              <div className="col-span-2">
                <label className="label">Servidor</label>
                <input className="input" placeholder="XMGlobal-MT5 7" value={form.server} onChange={set('server')} required />
                <p className="mt-1 text-xs text-term-muted">
                  Debe coincidir EXACTO con el de su cuenta en MT5 (clic derecho
                  sobre la cuenta en el Navegador → Propiedades).
                </p>
              </div>
              <div className="col-span-2">
                <label className="label">Ruta del terminal (opcional)</label>
                <input
                  className="input"
                  placeholder="C:\Program Files\XM MT5\terminal64.exe"
                  value={form.terminal_path}
                  onChange={set('terminal_path')}
                />
                <p className="mt-1 text-xs text-term-muted">
                  Sólo si tiene VARIOS terminales MT5 instalados (ej. XM e IC
                  Markets). Indica cuál usar para esta cuenta.
                </p>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <div>
                <label className="label">API Key</label>
                <input type="password" className="input" value={form.api_key} onChange={set('api_key')} required />
              </div>
              <div>
                <label className="label">Account ID</label>
                <input className="input" placeholder="101-001-1234567-001" value={form.account_id} onChange={set('account_id')} required />
              </div>
            </div>
          )}

          <label className="flex items-center gap-2 text-sm text-term-dim">
            <input type="checkbox" checked={form.is_demo} onChange={set('is_demo')} />
            Cuenta demo / practice
          </label>

          {error && <p className="text-sm text-term-bad">{error}</p>}
          <p className="text-xs text-term-muted flex items-center gap-1.5">
            <KeyRound className="w-3.5 h-3.5" />
            Las credenciales se cifran (Fernet/AES) antes de guardarse y nunca se muestran.
          </p>
          <button type="submit" disabled={busy} className="btn-primary">
            {busy && <Loader2 className="w-4 h-4 animate-spin" />} Guardar credenciales
          </button>
        </form>
      </Panel>

      <Panel title="Conexiones guardadas">
        <ul className="space-y-3">
          {creds.length === 0 && (
            <li className="text-sm text-term-muted py-6 text-center">Sin credenciales guardadas.</li>
          )}
          {creds.map((c) => {
            const t = testResult[c.id];
            return (
              <li key={c.id} className="rounded-md border border-term-border p-3">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold">
                      {c.label}{' '}
                      <span className="text-xs font-normal text-term-muted">
                        {c.broker_type} · {c.is_demo ? 'demo' : 'LIVE'}
                      </span>
                    </p>
                    <p className="text-xs text-term-dim">{c.server ?? c.account_id ?? ''}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button onClick={() => test(c.id)} className="btn-ghost !py-1 !px-2 text-xs">
                      {t?.loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <PlugZap className="w-3.5 h-3.5" />}
                      Probar
                    </button>
                    <button onClick={() => remove(c.id)} className="text-term-muted hover:text-term-bad" title="Eliminar">
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
                {t && !t.loading && (
                  <p className={`mt-2 flex items-center gap-1.5 text-xs ${t.success ? 'text-term-good' : 'text-term-bad'}`}>
                    {t.success ? <CheckCircle2 className="w-3.5 h-3.5" /> : <XCircle className="w-3.5 h-3.5" />}
                    {t.message}
                    {t.account_balance != null && ` — Balance: ${t.account_balance} ${t.account_currency}`}
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      </Panel>
    </div>
  );
}

/* ────────────────────────── Activos ───────────────────────── */

function AssetsTab() {
  const [assets, setAssets] = useState([]);
  const [suggested, setSuggested] = useState([]);
  const [symbol, setSymbol] = useState('');
  const [timeframe, setTimeframe] = useState('M15');
  const [error, setError] = useState('');

  const refresh = () => api.get('/assets').then(setAssets).catch(() => {});
  useEffect(() => {
    refresh();
    api.get('/assets/suggested').then(setSuggested).catch(() => {});
  }, []);

  const add = async (e) => {
    e.preventDefault();
    setError('');
    try {
      await api.post('/assets', { symbol: symbol.toUpperCase(), timeframe });
      setSymbol('');
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const toggle = async (id) => { await api.patch(`/assets/${id}/toggle`); refresh(); };
  const remove = async (id) => { await api.del(`/assets/${id}`); refresh(); };

  return (
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
      <Panel title="Añadir par a la watchlist">
        <form onSubmit={add} className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Par</label>
              <input
                className="input uppercase"
                list="suggested-pairs"
                placeholder="EURUSD"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                pattern="[A-Za-z]{6,12}"
                required
              />
              <datalist id="suggested-pairs">
                {suggested.map((s) => <option key={s} value={s} />)}
              </datalist>
            </div>
            <div>
              <label className="label">Timeframe</label>
              <select className="input" value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
                {['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1'].map((tf) => <option key={tf}>{tf}</option>)}
              </select>
            </div>
          </div>
          {error && <p className="text-sm text-term-bad">{error}</p>}
          <button type="submit" className="btn-primary"><Plus className="w-4 h-4" /> Añadir</button>
        </form>
      </Panel>

      <Panel title={`Pares monitoreados (${assets.filter((a) => a.enabled).length} activos)`}>
        <ul className="space-y-2">
          {assets.length === 0 && (
            <li className="text-sm text-term-muted py-6 text-center">La watchlist está vacía.</li>
          )}
          {assets.map((a) => (
            <li key={a.id} className="flex items-center justify-between rounded-md border border-term-border px-3 py-2">
              <div className="flex items-center gap-3">
                <span className={`font-semibold text-sm ${a.enabled ? '' : 'text-term-muted line-through'}`}>
                  {a.symbol}
                </span>
                <span className="text-xs text-term-muted">{a.timeframe} · pip {a.pip_size}</span>
              </div>
              <div className="flex items-center gap-3">
                {/* Toggle de monitoreo */}
                <button
                  onClick={() => toggle(a.id)}
                  role="switch"
                  aria-checked={a.enabled}
                  className={`relative h-5 w-9 rounded-full transition-colors ${a.enabled ? 'bg-term-good' : 'bg-term-border'}`}
                  title={a.enabled ? 'Desactivar' : 'Activar'}
                >
                  <span
                    className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all ${a.enabled ? 'left-4.5 translate-x-4' : 'translate-x-0.5 left-0'}`}
                  />
                </button>
                <button onClick={() => remove(a.id)} className="text-term-muted hover:text-term-bad" title="Eliminar">
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}

/* ────────────────────────── Riesgo ────────────────────────── */

const RISK_FIELDS = [
  ['risk_per_trade_pct', 'Riesgo por trade (%)', 0.1],
  ['stop_loss_pips', 'Stop Loss (pips)', 1],
  ['take_profit_pips', 'Take Profit (pips)', 1],
  ['break_even_trigger_pips', 'Disparo break-even (pips)', 1],
  ['trailing_stop_pips', 'Trailing stop (pips)', 1],
  ['max_open_trades', 'Máx. operaciones abiertas', 1],
  ['max_drawdown_pct', 'Freno drawdown % (0=off)', 1],
  ['drawdown_cooldown_hours', 'Enfriamiento freno (horas)', 1],
];

function RiskTab() {
  const [config, setConfig] = useState(null);
  const [strategies, setStrategies] = useState([]);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api.get('/bot/config').then(setConfig).catch(() => {});
    api.get('/bot/strategies').then(setStrategies).catch(() => {});
  }, []);

  if (!config) return <p className="text-sm text-term-muted">Cargando…</p>;

  const activeStrategy = strategies.find((s) => s.name === config.strategy_name);
  // Parámetros numéricos de la estrategia activa: valor guardado si existe,
  // si no el default — así "Aplicar al bot" desde el optimizador siempre
  // queda visible aquí, sin importar si tocó todos los parámetros o no.
  const strategyNumericParams = Object.entries(activeStrategy?.default_params ?? {}).filter(
    ([, v]) => typeof v === 'number',
  );

  const set = (f) => (e) => {
    setSaved(false);
    setConfig({ ...config, [f]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  };

  const setStrategyParam = (name) => (e) => {
    setSaved(false);
    setConfig({
      ...config,
      strategy_params: { ...config.strategy_params, [name]: e.target.value },
    });
  };

  const changeStrategy = (e) => {
    setSaved(false);
    const nextStrategy = strategies.find((s) => s.name === e.target.value);
    // Al cambiar de estrategia, sus parámetros vuelven al default: los de
    // la estrategia anterior no tienen sentido para la nueva.
    setConfig({
      ...config,
      strategy_name: e.target.value,
      strategy_params: nextStrategy?.default_params ?? {},
    });
  };

  const save = async (e) => {
    e.preventDefault();
    setError('');
    try {
      const payload = { ...config };
      for (const [field] of RISK_FIELDS) payload[field] = +payload[field];
      for (const [name] of strategyNumericParams) {
        payload.strategy_params[name] = +payload.strategy_params[name];
      }
      const updated = await api.put('/bot/config', payload);
      setConfig(updated);
      setSaved(true);
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <Panel
      title="Gestión de riesgo del motor"
      actions={
        <span className="text-xs text-term-dim">
          Estrategia activa:{' '}
          <span className="font-semibold text-term-accent">{config.strategy_name}</span>
        </span>
      }
    >
      <form onSubmit={save} className="space-y-4 max-w-2xl">
        <div>
          <label className="label">Estrategia</label>
          <select className="input" value={config.strategy_name} onChange={changeStrategy}>
            {strategies.map((s) => (
              <option key={s.name} value={s.name}>{s.name}</option>
            ))}
          </select>
          {activeStrategy && (
            <p className="mt-1 text-xs text-term-muted">{activeStrategy.description}</p>
          )}
        </div>

        {strategyNumericParams.length > 0 && (
          <div>
            <label className="label">Parámetros de la estrategia</label>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              {strategyNumericParams.map(([name, def]) => (
                <div key={name}>
                  <label className="text-xs text-term-muted">{name}</label>
                  <input
                    type="number"
                    className="input"
                    value={config.strategy_params?.[name] ?? def}
                    onChange={setStrategyParam(name)}
                  />
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          {RISK_FIELDS.map(([field, label, step]) => (
            <div key={field}>
              <label className="label">{label}</label>
              <input type="number" step={step} className="input" value={config[field]} onChange={set(field)} />
            </div>
          ))}
        </div>
        <div className="flex flex-wrap gap-6">
          <label className="flex items-center gap-2 text-sm text-term-dim">
            <input type="checkbox" checked={config.break_even_enabled} onChange={set('break_even_enabled')} />
            Break-even automático
          </label>
          <label className="flex items-center gap-2 text-sm text-term-dim">
            <input type="checkbox" checked={config.trailing_stop_enabled} onChange={set('trailing_stop_enabled')} />
            Trailing stop
          </label>
        </div>
        <p className="text-xs text-term-muted">
          Los cambios se aplican en caliente: el motor relee la configuración en cada ciclo.
        </p>
        {error && <p className="text-sm text-term-bad">{error}</p>}
        <div className="flex items-center gap-3">
          <button type="submit" className="btn-primary">Guardar cambios</button>
          {saved && (
            <span className="flex items-center gap-1 text-sm text-term-good">
              <CheckCircle2 className="w-4 h-4" /> Guardado
            </span>
          )}
        </div>
      </form>
    </Panel>
  );
}

/* ────────────────────────── Telegram ──────────────────────── */

function TelegramTab() {
  const [config, setConfig] = useState(null);
  const [token, setToken] = useState('');
  const [chatId, setChatId] = useState('');
  const [enabled, setEnabled] = useState(false);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get('/telegram/config').then((c) => {
      setConfig(c);
      setChatId(c.chat_id ?? '');
      setEnabled(c.enabled);
    }).catch(() => {});
  }, []);

  const save = async (e) => {
    e.preventDefault();
    setResult(null);
    try {
      const updated = await api.put('/telegram/config', {
        enabled,
        chat_id: chatId,
        bot_token: token || null, // null conserva el token ya guardado
      });
      setConfig(updated);
      setToken('');
      setResult({ success: true, message: 'Configuración guardada' });
    } catch (err) {
      setResult({ success: false, message: err.message });
    }
  };

  const test = async () => {
    setBusy(true);
    setResult(null);
    try {
      setResult(await api.post('/telegram/test'));
    } catch (err) {
      setResult({ success: false, message: err.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title="Notificaciones de Telegram" className="max-w-2xl">
      <form onSubmit={save} className="space-y-3">
        <div>
          <label className="label">
            Token del bot {config?.token_set && <span className="text-term-good">(ya configurado)</span>}
          </label>
          <input
            type="password"
            className="input"
            placeholder={config?.token_set ? '•••••••• (dejar vacío para conservar)' : 'Token de @BotFather'}
            value={token}
            onChange={(e) => setToken(e.target.value)}
          />
        </div>
        <div>
          <label className="label">Chat ID</label>
          <input className="input" placeholder="123456789" value={chatId} onChange={(e) => setChatId(e.target.value)} required />
        </div>
        <label className="flex items-center gap-2 text-sm text-term-dim">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          Enviar alertas (apertura, break-even, cierre con P/L)
        </label>

        {result && (
          <p className={`flex items-center gap-1.5 text-sm ${result.success ? 'text-term-good' : 'text-term-bad'}`}>
            {result.success ? <CheckCircle2 className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
            {result.message}
          </p>
        )}

        <div className="flex gap-3">
          <button type="submit" className="btn-primary">Guardar</button>
          <button type="button" onClick={test} disabled={busy || !config?.token_set} className="btn-ghost">
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            Probar conexión
          </button>
        </div>
      </form>
    </Panel>
  );
}
