/**
 * Cliente HTTP del dashboard.
 *
 * - Adjunta el JWT (localStorage) en cada petición.
 * - Ante un 401 limpia la sesión y redirige al login.
 * - Normaliza los errores: siempre lanza Error con el `detail` del backend.
 */

const BASE = '/api/v1';

export function getToken() {
  return localStorage.getItem('botforex_token');
}

export function setToken(token) {
  if (token) localStorage.setItem('botforex_token', token);
  else localStorage.removeItem('botforex_token');
}

async function request(path, { method = 'GET', body, formData } = {}) {
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  const resp = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: formData ?? (body !== undefined ? JSON.stringify(body) : undefined),
  });

  if (resp.status === 401) {
    setToken(null);
    window.location.href = '/login';
    throw new Error('Sesión expirada');
  }
  if (resp.status === 204) return null;

  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const detail = data?.detail;
    throw new Error(
      typeof detail === 'string' ? detail : JSON.stringify(detail ?? resp.statusText),
    );
  }
  return data;
}

export const api = {
  get: (path) => request(path),
  post: (path, body) => request(path, { method: 'POST', body }),
  put: (path, body) => request(path, { method: 'PUT', body }),
  patch: (path, body) => request(path, { method: 'PATCH', body }),
  del: (path) => request(path, { method: 'DELETE' }),
  upload: (path, file) => {
    const formData = new FormData();
    formData.append('file', file);
    return request(path, { method: 'POST', formData });
  },
  /** Login: el flujo OAuth2 password espera x-www-form-urlencoded, no JSON. */
  login: async (username, password) => {
    const resp = await fetch(`${BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ username, password }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data?.detail ?? 'Error de autenticación');
    return data;
  },
};
