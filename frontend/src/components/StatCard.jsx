/**
 * Tarjeta de métrica (stat tile).
 *
 * `tone`: 'default' | 'good' | 'bad' — colorea el valor; el signo del
 * propio número es la codificación secundaria (nunca color solo).
 */

export default function StatCard({ label, value, sub, icon: Icon, tone = 'default' }) {
  const toneClass =
    tone === 'good' ? 'text-term-good' : tone === 'bad' ? 'text-term-bad' : 'text-term-text';

  return (
    <div className="panel px-4 py-3 flex items-start justify-between">
      <div className="min-w-0">
        <p className="text-[11px] font-medium uppercase tracking-wider text-term-muted truncate">
          {label}
        </p>
        <p className={`mt-1 text-xl font-semibold tabular ${toneClass}`}>{value}</p>
        {sub && <p className="mt-0.5 text-xs text-term-dim truncate">{sub}</p>}
      </div>
      {Icon && <Icon className="w-4 h-4 text-term-muted shrink-0 mt-1" />}
    </div>
  );
}
