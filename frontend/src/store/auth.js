/** Store de autenticación (zustand): sesión JWT + datos del usuario. */

import { create } from 'zustand';
import { api, getToken, setToken } from '../api/client';

export const useAuth = create((set) => ({
  token: getToken(),
  user: null,

  async login(username, password) {
    const { access_token } = await api.login(username, password);
    setToken(access_token);
    const user = await api.get('/auth/me');
    set({ token: access_token, user });
  },

  async register(username, email, password) {
    await api.post('/auth/register', { username, email, password });
  },

  async fetchMe() {
    const user = await api.get('/auth/me');
    set({ user });
  },

  logout() {
    setToken(null);
    set({ token: null, user: null });
  },
}));
