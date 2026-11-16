// PROTOTYPE (issue #86): floating bottom-centre variant switcher. Cycles
// off → A → B → C via arrows or ←/→ keys (skipped while typing in inputs).
// Writes both the ?variant= URL param (shareable) and localStorage (survives
// in-app navigation that drops the param). DEV-only — never rendered in a
// production build.
import { useEffect } from "react";
import { useNavigate } from "react-router";
import { writeJourneyVariant, type JourneyVariantKey } from "./journeyPrototype";
import "./journeyPrototype.css";

export const SWITCHER_ITEMS: ReadonlyArray<{ key: "off" | JourneyVariantKey; label: string }> = [
  { key: "off", label: "原样(对照)" },
  { key: "A", label: "A·旅程门厅(首页)" },
  { key: "B", label: "B·Lab即起点" },
  { key: "C", label: "C·全局旅程主干带" },
];

export function PrototypeSwitcher({ current }: { current: "off" | JourneyVariantKey }) {
  const navigate = useNavigate();

  const cycle = (dir: 1 | -1) => {
    const keys = SWITCHER_ITEMS.map((item) => item.key);
    const at = keys.indexOf(current);
    const next = keys[(at + dir + keys.length) % keys.length]!;
    writeJourneyVariant(next);
    const search = next === "off" ? "" : `?variant=${next}`;
    navigate({ pathname: location.pathname, search }, { replace: true });
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable)
      ) {
        return;
      }
      if (event.key === "ArrowLeft") cycle(-1);
      if (event.key === "ArrowRight") cycle(1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const active = SWITCHER_ITEMS.find((item) => item.key === current) ?? SWITCHER_ITEMS[0]!;
  return (
    <div className="dvb-proto-switcher" data-testid="proto-switcher" title="原型变体切换(issue #86)——评审用,不入生产">
      <button type="button" className="dvb-proto-switcher-arrow" onClick={() => cycle(-1)} aria-label="上一个变体">
        ←
      </button>
      <span className="dvb-proto-switcher-label">原型 {active.label}</span>
      <button type="button" className="dvb-proto-switcher-arrow" onClick={() => cycle(1)} aria-label="下一个变体">
        →
      </button>
    </div>
  );
}
