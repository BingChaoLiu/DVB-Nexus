import type { ReactNode } from "react";

export function EmptyState({ title, note }: { title: string; note?: ReactNode }) {
  return (
    <div className="dvb-empty-state">
      <p className="dvb-empty-title">{title}</p>
      {note !== undefined && <p className="dvb-empty-note">{note}</p>}
    </div>
  );
}
