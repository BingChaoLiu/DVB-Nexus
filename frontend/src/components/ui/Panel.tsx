import type { ReactNode } from "react";

export function Panel({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="dvb-panel">
      {title !== undefined && <h3 className="dvb-panel-title">{title}</h3>}
      {children}
    </section>
  );
}
