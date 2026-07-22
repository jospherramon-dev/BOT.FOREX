/**
 * Configuración RECOMENDADA para la estrategia EMA 9/21 + ADX (scalping_ema_adx).
 *
 * Es el punto de partida analizado para EUR/USD en XM (M5, spread real ~1.9,
 * SL/TP por ATR, filtro de sesión en hora del broker, ADX 24 con confirmación
 * de fuerza y salida por debilidad de ADX). Se usa como valores por defecto del
 * formulario de backtest y como preset de un clic en Ajustes → Riesgo.
 *
 * IMPORTANTE: el filtro de sesión (session_start_hour/end) va en HORA DEL BROKER.
 * ~15:00-19:00 en un servidor GMT+2/+3 (XM) equivale al solape Londres-NY. Si el
 * backtest arroja muy pocas operaciones, esto es lo primero a revisar/ampliar.
 */

export const EMA_ADX_STRATEGY = 'scalping_ema_adx';

// Overrides de los PARÁMETROS DE ESTRATEGIA. Los no listados quedan en su valor
// por defecto (ema 9/21/50, adx_period 14, require_candle_confirm 1,
// exit_on_ema_fast_flip 0), que ya coinciden con la recomendación.
export const EMA_ADX_STRATEGY_PARAMS = {
  adx_threshold: 24,        // un pelo más estricto que el 22 base: filtra más rango
  require_adx_rising: 1,    // exige que la fuerza (ADX) esté subiendo
  di_min_gap: 3,            // separación mínima +DI/-DI (checklist del manual)
  exit_adx_below: 20,       // salida técnica si la tendencia se disuelve (regla 5.4)
  session_start_hour: 15,   // solape Londres-NY en hora del servidor XM…
  session_end_hour: 19,     // …verificar contra tus propios datos
};

// Riesgo recomendado para el BOT EN VIVO (enfriamiento del freno en HORAS).
export const EMA_ADX_RISK_BOT = {
  risk_per_trade_pct: 0.5,
  atr_sl_enabled: true,
  atr_period: 14,
  atr_sl_multiplier: 1.5,
  atr_tp_ratio: 2.0,
  atr_sl_min_pips: 5,
  break_even_enabled: true,
  break_even_trigger_pips: 10,
  trailing_stop_enabled: false,
  max_open_trades: 1,
  max_drawdown_pct: 15,
  drawdown_cooldown_hours: 48,
};

// Riesgo recomendado para el BACKTEST (enfriamiento del freno en VELAS;
// en M5, 48 h ≈ 576 velas). Incluye timeframe y spread reales.
export const EMA_ADX_BACKTEST = {
  timeframe: 'M5',
  spread_pips: 1.9,
  risk_per_trade_pct: 0.5,
  atr_sl_enabled: true,
  atr_period: 14,
  atr_sl_multiplier: 1.5,
  atr_tp_ratio: 2.0,
  atr_sl_min_pips: 5,
  break_even_enabled: true,
  break_even_trigger_pips: 10,
  trailing_stop_enabled: false,
  max_drawdown_pct: 15,
  drawdown_cooldown_bars: 576,
};
