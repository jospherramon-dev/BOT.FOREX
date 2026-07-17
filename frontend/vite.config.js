import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// El dev-server proxea API y WebSocket al backend FastAPI (puerto 8000),
// así el frontend usa rutas relativas y no hay problemas de CORS en dev.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
});
