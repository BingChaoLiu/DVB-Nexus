// Verify request form (SPEC-403 §4.6, REQ-UI-403-005): the request face for
// POST .../runs/{run_id}/verify. The kind dropdown is locked to the frozen
// six-kind closed set; at least one criterion row is required (the wire's
// min-1). ui_state is NEVER emitted — the engine accepts-and-ignores it and
// it must not become an evidence channel (CONTEXT.md 通关 ban).
import { useState } from "react";
import type { FormEvent } from "react";
import type { PassCriterionDTO, VerifyRunRequest } from "../types";
import { VERIFY_CRITERION_KINDS } from "./VerifyResultCard";

export interface VerifyRunPayload {
  recoveryRunId: string;
  body: VerifyRunRequest;
}

interface CriterionDraft {
  criterion_id: string;
  kind: string;
  mandatory: boolean;
  fault_id: string;
}

export function VerifyRunForm({
  runCandidates,
  onSubmit,
}: {
  /** Run ids observed on the page (run registry + journal observations). */
  runCandidates: readonly string[];
  onSubmit: (payload: VerifyRunPayload) => void;
}) {
  const [recoveryRunId, setRecoveryRunId] = useState("");
  const [baselineRunId, setBaselineRunId] = useState("");
  const [scenarioId, setScenarioId] = useState("");
  const [version, setVersion] = useState("");
  const [contentHash, setContentHash] = useState("");
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
        <input aria-label="scenario_id" value={scenarioId} onChange={(e) => setScenarioId(e.target.value)} />
      </label>
      <label>
        version
        <input aria-label="version" value={version} onChange={(e) => setVersion(e.target.value)} />
      </label>
      <label>
        content_hash
        <input aria-label="content_hash" value={contentHash} onChange={(e) => setContentHash(e.target.value)} />
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
