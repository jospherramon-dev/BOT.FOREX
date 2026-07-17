/** Pantalla de acceso: login JWT + registro de usuario. */

import { CandlestickChart, Loader2 } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../store/auth';

export default function Login() {
  const [mode, setMode] = useState('login'); // 'login' | 'register'
  const [form, setForm] = useState({ username: '', email: '', password: '' });
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');
  const [busy, setBusy] = useState(false);
  const { login, register } = useAuth();
  const navigate = useNavigate();

  const update = (field) => (e) => setForm({ ...form, [field]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    setInfo('');
    setBusy(true);
    try {
      if (mode === 'register') {
        await register(form.username, form.email, form.password);
        setInfo('Cuenta creada. Ya puede iniciar sesión.');
        setMode('login');
      } else {
        await login(form.username, form.password);
        navigate('/');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="flex items-center justify-center gap-2 mb-6">
          <CandlestickChart className="w-8 h-8 text-term-accent" />
          <h1 className="text-2xl font-bold tracking-wide">
            BOT<span className="text-term-accent">.FOREX</span>
          </h1>
        </div>

        <div className="panel p-6">
          {/* Selector login / registro */}
          <div className="grid grid-cols-2 gap-1 mb-5 rounded-md bg-term-panel2 p-1">
            {['login', 'register'].map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`rounded py-1.5 text-sm font-medium transition-colors ${
                  mode === m ? 'bg-term-accent text-white' : 'text-term-dim hover:text-term-text'
                }`}
              >
                {m === 'login' ? 'Iniciar sesión' : 'Crear cuenta'}
              </button>
            ))}
          </div>

          <form onSubmit={submit} className="space-y-4">
            <div>
              <label className="label">Usuario</label>
              <input
                className="input"
                value={form.username}
                onChange={update('username')}
                autoComplete="username"
                required
                minLength={3}
              />
            </div>

            {mode === 'register' && (
              <div>
                <label className="label">Email</label>
                <input
                  type="email"
                  className="input"
                  value={form.email}
                  onChange={update('email')}
                  autoComplete="email"
                  required
                />
              </div>
            )}

            <div>
              <label className="label">Contraseña</label>
              <input
                type="password"
                className="input"
                value={form.password}
                onChange={update('password')}
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                required
                minLength={8}
              />
            </div>

            {error && <p className="text-sm text-term-bad">{error}</p>}
            {info && <p className="text-sm text-term-good">{info}</p>}

            <button type="submit" disabled={busy} className="btn-primary w-full justify-center">
              {busy && <Loader2 className="w-4 h-4 animate-spin" />}
              {mode === 'login' ? 'Entrar' : 'Registrarse'}
            </button>
          </form>
        </div>

        <p className="mt-4 text-center text-xs text-term-muted">
          Terminal de trading algorítmico — acceso restringido
        </p>
      </div>
    </div>
  );
}
