// Verify request form (SPEC-403 §4.6, REQ-UI-403-005): the request face for
// POST .../runs/{run_id}/verify. The kind dropdown is locked to the frozen
// six-kind closed set; at least one criterion row is required (the wire's
// min-1). ui_state is NEVER emitted — the engine accepts-and-ignores it and
// it must not become an evidence channel (CONTEXT.md 通关 ban).
//
// SPEC-408 §7.5 (ticket #95): the identity triple arrives as an editable
// prefill — scenario_id ← the session detail read-back, version/content_hash
// ← the scenario detail (real pinned hash; the SPEC-406 §7.4 marker-string
// posture is retired). The run candidates come through the datalist ONLY:
// runs are never auto-guessed — until the user picks/types both runs there
// is no submission (提交即声明; prefill never becomes a silent request).
// Every prefilled value stays user-editable: an explicit user edit wins over
// the prefill for the rest of the form's life.
import { useState } from "react";
import type { FormEvent } from "react";
import type { PassCriterionDTO, VerifyRunRequest } from "../types";
import { VERIFY_CRITERION_KINDS } from "./VerifyResultCard";

export interface VerifyRunPayload {
  recoveryRunId: string;
  body: VerifyRunRequest;
}

/** Editable prefill sources (SPEC-408 §7.5). `null` = the source honestly has
 * nothing (e.g. a plain session's scenario_id) — the field stays empty. */
export interface VerifyPrefill {
  scenarioId?: string | null;
  version?: string | null;
  contentHash?: string | null;
}

interface CriterionDraft {
  criterion_id: string;
  kind: string;
  mandatory: boolean;
  fault_id: string;
}

export function VerifyRunForm({
  runCandidates,
  prefill,
  onSubmit,
}: {
  /** Run ids observed on the page (run registry + journal observations). */
  runCandidates: readonly string[];
  /** Three-source identity prefill (§7.5); absent = manual-only posture. */
  prefill?: VerifyPrefill;
  onSubmit: (payload: VerifyRunPayload) => void;
}) {
  const [recoveryRunId, setRecoveryRunId] = useState("");
  const [baselineRunId, setBaselineRunId] = useState("");
  // override = the user's explicit edit; it wins over any prefill value.
  // Otherwise the live prefill is mirrored (so late-arriving read-backs land).
  const [scenarioOverride, setScenarioOverride] = useState<string | null>(null);
  const [versionOverride, setVersionOverride] = useState<string | null>(null);
  const [hashOverride, setHashOverride] = useState<string | null>(null);
  const scenarioId = scenarioOverride ?? prefill?.scenarioId ?? "";
  const version = versionOverride ?? prefill?.version ?? "";
  const contentHash = hashOverride ?? prefill?.contentHash ?? "";
  const [criteria, setCriteria] = useState<CriterionDraft[]>([
    { criterion_id: "", kind: VERIFY_CRITERION_KINDS[4]!, mandatory: true, fault_id: "" },
  ]);

  const complete =
    recoveryRunId.trim() !== "" &&
    baselineRunId.trim() !== "" &&
    scenarioId.trim() !== "" &&
    version.trim() !== "" &&
    contentHash.trim() !== "" &&
    criteria.length >= 1 &&
    criteria.every((c) => c.criterion_id.trim() !== "" && c.kind !== "");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!complete) return;
    const pass_criteria: PassCriterionDTO[] = criteria.map((c) => ({
      criterion_id: c.criterion_id.trim(),
      kind: c.kind,
      mandatory: c.mandatory,
      ...(c.fault_id.trim() !== "" ? { fault_id: c.fault_id.trim() } : {}),
    }));
    onSubmit({
      recoveryRunId: recoveryRunId.trim(),
      body: {
        baseline_run_id: baselineRunId.trim(),
        scenario: { scenario_id: scenarioId.trim(), version: version.trim(), content_hash: contentHash.trim() },
        pass_criteria,
      },
    });
  };

  const datalistId = "verify-run-candidates";

  return (
    <form className="dvb-mon-verify-form" onSubmit={submit}>
      <datalist id={datalistId}>
        {runCandidates.map((runId) => (
          <option key={runId} value={runId} />
        ))}
      </datalist>
      <label>
        recovery_run_id
        <input
          list={datalistId}
          aria-label="recovery_run_id"
          value={recoveryRunId}
          onChange={(e) => setRecoveryRunId(e.target.value)}
        />
      </label>
      <label>
        baseline_run_id
        <input
          list={datalistId}
          aria-label="baseline_run_id"
          value={baselineRunId}
          onChange={(e) => setBaselineRunId(e.target.value)}
        />
      </label>
      <label>
        scenario_id
        <input
          aria-label="scenario_id"
          value={scenarioId}
          onChange={(e) => setScenarioOverride(e.target.value)}
        />
      </label>
      <label>
        version
        <input aria-label="version" value={version} onChange={(e) => setVersionOverride(e.target.value)} />
      </label>
      <label>
        content_hash
        <input
          aria-label="content_hash"
          value={contentHash}
          onChange={(e) => setHashOverride(e.target.value)}
        />
      </label>
      <fieldset className="dvb-mon-criteria">
        <legend>pass_criteria（min 1）</legend>
        {criteria.map((draft, index) => (
          <div key={index} className="dvb-mon-criterion">
            <label>
              criterion_id
              <input
                aria-label="criterion_id"
                value={draft.criterion_id}
                onChange={(e) =>
                  setCriteria(criteria.map((c, i) => (i === index ? { ...c, criterion_id: e.target.value } : c)))
                }
              />
            </label>
            <label>
              kind
              <select
                aria-label="kind"
                value={draft.kind}
                onChange={(e) =>
                  setCriteria(criteria.map((c, i) => (i === index ? { ...c, kind: e.target.value } : c)))
                }
              >
                {VERIFY_CRITERION_KINDS.map((kind) => (
                  <option key={kind} value={kind}>
                    {kind}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <input
                type="checkbox"
                aria-label="mandatory"
                checked={draft.mandatory}
                onChange={(e) =>
                  setCriteria(criteria.map((c, i) => (i === index ? { ...c, mandatory: e.target.checked } : c)))
                }
              />
              mandatory
            </label>
            <label>
              fault_id
              <input
                aria-label="fault_id"
                value={draft.fault_id}
                onChange={(e) =>
                  setCriteria(criteria.map((c, i) => (i === index ? { ...c, fault_id: e.target.value } : c)))
                }
              />
            </label>
            <button type="button" onClick={() => setCriteria(criteria.filter((_, i) => i !== index))}>
              移除判据
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() =>
            setCriteria([...criteria, { criterion_id: "", kind: VERIFY_CRITERION_KINDS[0]!, mandatory: true, fault_id: "" }])
          }
        >
          添加判据
        </button>
      </fieldset>
      <button type="submit" disabled={!complete}>
        verify
      </button>
    </form>
  );
}
