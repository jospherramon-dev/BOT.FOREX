/** Contenedor estándar de sección con cabecera opcional. */

export default function Panel({ title, actions, children, className = '' }) {
  return (
    <section className={`panel ${className}`}>
      {(title || actions) && (
        <header className="flex items-center justify-between px-4 py-2.5 border-b border-term-border">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-term-dim">
            {title}
          </h2>
          {actions}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}
