/**
 * Layout del dashboard: sidebar colapsable + topbar + contenido.
 *
 * Aquí vive la conexión WebSocket global: se abre una vez con el JWT y
 * alimenta el store `useLive` para todas las secciones.
 */

import {
  Activity,
  BarChart3,
  CandlestickChart,
  ChevronLeft,
  ChevronRight,
  FlaskConical,
  LogOut,
  Pause,
  Play,
  Settings as SettingsIcon,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { api } from '../api/client';
import { connectLive } from '../api/ws';
import { useAuth } from '../store/auth';
import { useLive } from '../store/live';

const NAV = [
  { to: '/', label: 'Live Trading', icon: Activity, end: true },
  { to: '/analytics', label: 'Analytics', icon: BarChart3 },
  { to: '/backtest', label: 'Backtest', icon: FlaskConical },
  { to: '/settings', label: 'Configuración', icon: SettingsIcon },
];

const TITLES = {
  '/': 'Live Trading',
  '/analytics': 'Analytics',
  '/backtest': 'Backtest',
  '/settings': 'Configuración',
};

export default function DashboardLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const [busy, setBusy] = useState(false);
  const { token, user, fetchMe, logout } = useAuth();
  const { account, botRunning, wsConnected, handleEvent, setWsConnected, setBotRunning } =
    useLive();
  const location = useLocation();

  // Conexión WS global (una por sesión) + estado inicial del bot.
  useEffect(() => {
    if (!token) return undefined;
    fetchMe().catch(() => {});
    api.get('/bot/status').then((s) => setBotRunning(s.running)).catch(() => {});
    const disconnect = connectLive(token, handleEvent, setWsConnected);
    return disconnect;
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleBot = async () => {
    setBusy(true);
    try {
      const result = botRunning
        ? await api.post('/bot/stop')
        : await api.post('/bot/start');
      setBotRunning(result.running);
    } catch (err) {
      alert(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-screen overflow-hidden">
      {/* ── Sidebar ──────────────────────────────────────────────── */}
      <aside
        className={`flex flex-col border-r border-term-border bg-term-panel2 transition-all duration-200 ${
          collapsed ? 'w-16' : 'w-60'
        }`}
      >
        <div className="flex items-center gap-3 px-4 h-14 border-b border-term-border">
          <CandlestickChart className="w-6 h-6 text-term-accent shrink-0" />
          {!collapsed && (
            <span className="font-bold tracking-wide text-sm">
              BOT<span className="text-term-accent">.FOREX</span>
            </span>
          )}
        </div>

        <nav className="flex-1 py-3 space-y-1 px-2">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              title={label}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? 'bg-term-panel text-term-text border border-term-border'
                    : 'text-term-dim hover:text-term-text hover:bg-term-panel'
                }`
              }
            >
              <Icon className="w-4 h-4 shrink-0" />
              {!collapsed && label}
            </NavLink>
          ))}
        </nav>

        <div className="p-2 border-t border-term-border space-y-1">
          <button
            onClick={logout}
            title="Cerrar sesión"
            className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm text-term-dim hover:text-term-bad transition-colors"
          >
            <LogOut className="w-4 h-4 shrink-0" />
            {!collapsed && 'Cerrar sesión'}
          </button>
          <button
            onClick={() => setCollapsed(!collapsed)}
            title={collapsed ? 'Expandir' : 'Colapsar'}
            className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm text-term-muted hover:text-term-text transition-colors"
          >
            {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
            {!collapsed && 'Colapsar'}
          </button>
        </div>
      </aside>

      {/* ── Zona principal ───────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="flex items-center justify-between h-14 px-5 border-b border-term-border bg-term-panel2">
          <h1 className="text-sm font-semibold tracking-wide uppercase text-term-dim">
            {TITLES[location.pathname] ?? 'Dashboard'}
          </h1>

          <div className="flex items-center gap-4">
            {/* Equity en vivo */}
            {account && (
              <div className="hidden md:flex items-center gap-2 text-sm tabular">
                <span className="text-term-muted">Equity</span>
                <span className="font-semibold">
                  {account.equity?.toLocaleString('es', { minimumFractionDigits: 2 })}{' '}
                  {account.currency}
                </span>
              </div>
            )}

            {/* Estado de conexión WS */}
            <div
              className="flex items-center gap-1.5 text-xs"
              title={wsConnected ? 'Datos en vivo conectados' : 'Sin conexión en vivo'}
            >
              {wsConnected ? (
                <Wifi className="w-4 h-4 text-term-good" />
              ) : (
                <WifiOff className="w-4 h-4 text-term-bad" />
              )}
              <span className={wsConnected ? 'text-term-good' : 'text-term-bad'}>
                {wsConnected ? 'LIVE' : 'OFFLINE'}
              </span>
            </div>

            {/* Estado + control del bot */}
            <span
              className={`flex items-center gap-1.5 text-xs font-semibold px-2 py-1 rounded-md border ${
                botRunning
                  ? 'text-term-good border-term-good/40 bg-term-good/10'
                  : 'text-term-muted border-term-border'
              }`}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  botRunning ? 'bg-term-good animate-pulse' : 'bg-term-muted'
                }`}
              />
              BOT {botRunning ? 'ACTIVO' : 'DETENIDO'}
            </span>
            <button
              onClick={toggleBot}
              disabled={busy}
              className={botRunning ? 'btn-danger' : 'btn-success'}
            >
              {botRunning ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
              {botRunning ? 'Detener' : 'Iniciar'}
            </button>

            {user && (
              <span className="text-xs text-term-muted hidden lg:block">@{user.username}</span>
            )}
          </div>
        </header>

        <main className="flex-1 overflow-y-auto p-5">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
