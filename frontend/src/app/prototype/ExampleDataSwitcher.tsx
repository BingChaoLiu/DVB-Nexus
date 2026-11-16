// PROTOTYPE (issue #87): floating bottom variant switcher for the example-data
// suite + the per-variant plan card (体验路径 / 后端增量 / 诚实纪律 / 30 分钟贡献)
// so the reviewer compares while experiencing. CLICK-ONLY by design: the
// ←/→ arrow keys belong to the #86 journey switcher when both suites are on.
// Hidden entirely when the suite is off (or in production builds).
import { useNavigate } from "react-router";
import { DATA_PLANS, DATA_PLANS_FOOTER, writeExampleDataVariant, type ExampleDataVariantKey } from "./exampleDataPrototype";
import "./exampleDataPrototype.css";

export const DATA_SWITCHER_ITEMS: ReadonlyArray<{ key: "off" | ExampleDataVariantKey; label: string }> = [
  { key: "off", label: "原样(对照)" },
  { key: "A", label: "A·演示Session开门" },
  { key: "B", label: "B·开局即得baseline" },
  { key: "C", label: "C·示例骨架填充" },
];

export function ExampleDataSwitcher({ current }: { current: "off" | ExampleDataVariantKey }) {
  const navigate = useNavigate();
  if (current === "off") return null;

  const cycle = (dir: 1 | -1) => {
    const keys = DATA_SWITCHER_ITEMS.map((item) => item.key);
    const at = keys.indexOf(current);
    const next = keys[(at + dir + keys.length) % keys.length]!;
    writeExampleDataVariant(next);
    navigate({ pathname: location.pathname, search: next === "off" ? "" : `?data=${next}` }, { replace: true });
  };

  const plan = DATA_PLANS[current];
  return (
    <>
      <div className="dvb-proto-dataplan" data-testid="proto-dataplan">
        <details open>
          <summary>示例数据原型 · {plan.label}(issue #87,评审用)</summary>
          <p className="dvb-proto-dataplan-tag">{plan.tagline}</p>
          <p>
            <b>怎么体验:</b>
            {plan.experience}
          </p>
          <p>
            <b>后端增量(逐项):</b>
          </p>
          <ul>
            {plan.backend.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <p>
            <b>诚实纪律核对:</b>
            {plan.honesty}
          </p>
          <p>
            <b>30 分钟贡献:</b>
            {plan.contribution}
          </p>
          <p className="dvb-proto-dataplan-foot">{DATA_PLANS_FOOTER}</p>
        </details>
      </div>
      <div className="dvb-proto-switcher dvb-proto-switcher-data" data-testid="proto-data-switcher" title="示例数据方案切换(issue #87)——评审用,不入生产">
        <button type="button" className="dvb-proto-switcher-arrow" onClick={() => cycle(-1)} aria-label="上一个示例数据方案">
          ←
        </button>
        <span className="dvb-proto-switcher-label">数据 {DATA_SWITCHER_ITEMS.find((item) => item.key === current)?.label}</span>
        <button type="button" className="dvb-proto-switcher-arrow" onClick={() => cycle(1)} aria-label="下一个示例数据方案">
          →
        </button>
      </div>
    </>
  );
}
