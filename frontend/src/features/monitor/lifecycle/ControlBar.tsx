// Control bar (SPEC-403 §4.2, REQ-UI-403-001): the six lifecycle actions and
// the status badge. Enablement is TABLE-DRIVEN (STATE_ACTIONS / isActionEnabled
// — the SPEC-200 §5 exhaustive derivation); per-button if-chains are banned.
// The badge renders the wire lifecycle string verbatim (lowercase domain enum
// values — no aliasing, no case conversion). A 409
// SIM_INVALID_LIFECYCLE_TRANSITION resyncs the badge from details.current,
// renders details.allowed, and notifies the page (snapshot re-pull).
import { useState } from "react";
import type { ReactNode } from "react";
import { isApiError } from "../../../api/client";
import { Badge } from "../../../components/ui";
import { LIFECYCLE_ACTIONS, isActionEnabled, type LifecycleAction, type LifecycleWire } from "./lifecycleTable";

const STATE_TONE: Record<LifecycleWire, "good" | "warn" | "bad" | "neutral" | "info"> = {
  created: "neutral",
  validating: "info",
  ready: "info",
  running: "good",
  paused: "warn",
  stopping: "warn",
  stopped: "neutral",
  failed: "bad",
  disposed: "neutral",
};

interface TransitionNotice {
  text: string;
}

export function ControlBar({
  lifecycle,
  onAction,
  onResync,
}: {
  /** The authoritative wire lifecycle (from session view / action answers); null = unknown. */
  lifecycle: LifecycleWire | null;
  /** Execute one action (the endpoint call); rejects with ApiError on failure. */
  onAction?: (action: LifecycleAction) => Promise<unknown>;
  /** 409 resync hook: called with details.current so the page re-pulls truth. */
  onResync?: (current: LifecycleWire) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<TransitionNotice | null>(null);

  const run = async (action: LifecycleAction) => {
    if (busy || lifecycle === null || !isActionEnabled(lifecycle, action)) return;
    setBusy(true);
    setNotice(null);
    try {
      await onAction?.(action);
    } catch (error) {
      if (isApiError(error) && error.errorCode === "SIM_INVALID_LIFECYCLE_TRANSITION") {
        const current = typeof error.details.current === "string" ? (error.details.current as LifecycleWire) : lifecycle;
        const allowed = Array.isArray(error.details.allowed) ? (error.details.allowed as string[]).join(", ") : "";
        setNotice({
          text: `服务端视图为 ${current}${allowed === "" ? "" : `（合法目标：${allowed}）`} — 已回同步`,
        });
        // the server view is authoritative: the page re-pulls the snapshot
        if (current !== null) onResync?.(current);
      } else if (isApiError(error)) {
        setNotice({ text: `${error.errorCode}: ${error.message}` });
      } else {
        setNotice({ text: String(error) });
      }
    } finally {
      setBusy(false);
    }
  };

  const badge: ReactNode =
    lifecycle === null ? (
      <Badge tone="neutral">未知</Badge>
    ) : (
      <Badge tone={STATE_TONE[lifecycle] ?? "neutral"}>{lifecycle}</Badge>
    );

  return (
    <div className="dvb-mon-controlbar">
      <span data-testid="lifecycle-badge" className="dvb-mon-badge">
        {badge}
      </span>
      <div className="dvb-mon-actions-bar" role="group" aria-label="运行控制">
        {LIFECYCLE_ACTIONS.map((action) => (
          <button
            key={action}
            type="button"
            name={action}
            disabled={busy || lifecycle === null || !isActionEnabled(lifecycle, action)}
            onClick={() => void run(action)}
          >
            {action}
          </button>
        ))}
      </div>
      {notice !== null && (
        <p data-testid="lifecycle-error" className="dvb-mon-error">
          {notice.text}
        </p>
      )}
    </div>
  );
}
