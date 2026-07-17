/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      // Tema "trading terminal": paneles oscuros azulados de alta densidad.
      colors: {
        term: {
          bg: '#0a0f1a',      // plano de página
          panel: '#111a2b',   // superficie de paneles/gráficos
          panel2: '#0d1524',  // superficie hundida (inputs, consola)
          border: '#1e2b45',  // bordes hairline
          text: '#e6edf7',    // tinta primaria
          dim: '#94a3b8',     // tinta secundaria
          muted: '#64748b',   // ejes, etiquetas terciarias
          accent: '#3987e5',  // serie 1 (azul) — validado sobre panel
          aqua: '#199e70',    // serie 2 (aqua) — validado sobre panel
          good: '#0ca30c',    // ganancia / BUY (siempre con texto/signo)
          bad: '#d03b3b',     // pérdida / SELL (siempre con texto/signo)
          warn: '#fab219',
        },
      },
      fontFamily: {
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
};
