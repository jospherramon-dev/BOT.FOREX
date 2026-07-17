/** Tooltip unificado para todos los gráficos Recharts del dashboard. */

export default function ChartTooltip({ active, payload, label, formatter }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-term-border bg-term-panel2 px-3 py-2 text-xs shadow-xl">
      {label !== undefined && <p className="text-term-muted mb-1">{label}</p>}
      {payload.map((entry) => (
        <p key={entry.dataKey} className="flex items-center gap-2 tabular">
          <span
            className="inline-block w-2 h-2 rounded-sm"
            style={{ background: entry.color ?? entry.fill }}
          />
          <span className="text-term-dim">{entry.name}:</span>
          <span className="text-term-text font-medium">
            {formatter ? formatter(entry.value, entry) : entry.value}
          </span>
        </p>
      ))}
    </div>
  );
}
