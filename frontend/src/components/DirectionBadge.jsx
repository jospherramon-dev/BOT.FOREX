/**
 * Badge BUY/SELL — el texto siempre acompaña al color (accesibilidad CVD:
 * el rojo/verde jamás carga el significado en solitario).
 */

import { TrendingDown, TrendingUp } from 'lucide-react';

export default function DirectionBadge({ direction }) {
  const isBuy = direction === 'BUY';
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-bold ${
        isBuy
          ? 'text-term-good bg-term-good/10 border border-term-good/30'
          : 'text-term-bad bg-term-bad/10 border border-term-bad/30'
      }`}
    >
      {isBuy ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
      {direction}
    </span>
  );
}
