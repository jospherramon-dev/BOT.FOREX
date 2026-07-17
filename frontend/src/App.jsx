/**
 * Enrutador principal.
 *
 * /login             → pantalla de acceso.
 * /* (protegido)     → DashboardLayout con las 4 secciones.
 */

import { Navigate, Route, Routes } from 'react-router-dom';
import DashboardLayout from './layouts/DashboardLayout';
import Analytics from './pages/Analytics';
import Backtest from './pages/Backtest';
import LiveTrading from './pages/LiveTrading';
import Login from './pages/Login';
import Settings from './pages/Settings';
import { useAuth } from './store/auth';

function Protected({ children }) {
  const token = useAuth((s) => s.token);
  return token ? children : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <Protected>
            <DashboardLayout />
          </Protected>
        }
      >
        <Route index element={<LiveTrading />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="backtest" element={<Backtest />} />
        <Route path="settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
