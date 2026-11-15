// Node inspector form (SPEC-402 §4.1, APPROVED 0.5.0): the draft-composition
// surface for the canvas selection. Declarative only — every rendered field
// comes from GENERATOR_FIELD_INVENTORY (the component holds ZERO field
// literals; fieldInventory.test.ts pins the table to the generated schema).
// It never talks to the network and never validates (SPEC-402 §2.2: no
// real-time checking — the only gates are the completeness statement and the
// server reports wired by the page via inspectorGate). Apply is the single
// way edits enter the draft (editorState "configApplied", approved additive).
import { useMemo, useState } from "react";

import type { TopologyFlowNode } from "../graphMapping";
import { nodeTypeSpec } from "../nodeTypes";
import { GENERATOR_FIELD_INVENTORY, initialValueFor, type FieldDescriptor } from "./fieldInventory";
import type { FieldError } from "./locChain";
import "./inspector.css";

/** Scalar leaf kinds rendered as a single input (group/rows recurse). */
type ScalarKind = "number" | "text" | "select" | "locked-checkbox";

function isScalar(descriptor: FieldDescriptor): descriptor is FieldDescriptor & { kind: ScalarKind } {
  return descriptor.kind === "number" || descriptor.kind === "text" || descriptor.kind === "select" || descriptor.kind === "locked-checkbox";
}

function isRows(descriptor: FieldDescriptor): descriptor is FieldDescriptor & { kind: "rows" } {
  return descriptor.kind === "rows";
}

/** Local form state: raw input strings (numbers stay editable text — "0" is
 * a filled value, "" is unfilled) + rows as string maps. */
interface FormState {
  scalars: Record<string, string>;
  rows: Record<string, string>[]; // keys = row-field paths
}

function readPath(config: unknown, path: string): unknown {
  let current: unknown = config;
  for (const segment of path.split(".")) {
    if (typeof current !== "object" || current === null) return undefined;
    current = (current as Record<string, unknown>)[segment]!;
  }
  return current;
}

function toInputString(value: unknown): string {
  if (value === undefined || value === null) return "";
  return String(value);
}

/** Project one rows descriptor (array of wire objects) into string-map rows. */
function projectRows(descriptor: FieldDescriptor & { kind: "rows" }, config: unknown): Record<string, string>[] {
  const stored = readPath(config, descriptor.path);
  const storedRows = Array.isArray(stored) ? stored : [];
  return storedRows.map((row) => {
    const rowState: Record<string, string> = {};
    for (const field of descriptor.rowFields ?? []) {
      rowState[field.path] = toInputString(readPath(row, field.path.split(".").pop()!) ?? initialValueFor(field));
    }
    return rowState;
  });
}

/** Build the local state from the stored config: filled keys verbatim,
 * missing optional keys from their wire default / pinned initial, missing
 * required keys empty (the 配置待填 subjects). */
function projectFrom(config: unknown): FormState {
  const scalars: Record<string, string> = {};
  let rows: Record<string, string>[] = [];
  for (const descriptor of GENERATOR_FIELD_INVENTORY) {
    if (descriptor.kind === "group") {
      for (const child of descriptor.children ?? []) {
        if (isScalar(child)) {
          scalars[child.path] = toInputString(readPath(config, child.path) ?? initialValueFor(child));
        } else if (isRows(child)) {
          rows = projectRows(child, config); // the rows child reads the SAME config root (dot path)
        }
      }
    } else if (isRows(descriptor)) {
      rows = projectRows(descriptor, config);
    } else if (isScalar(descriptor)) {
      scalars[descriptor.path] = toInputString(readPath(config, descriptor.path) ?? initialValueFor(descriptor));
    }
  }
  return { scalars, rows };
}

function serializeScalar(descriptor: FieldDescriptor & { kind: ScalarKind }, raw: string | undefined): unknown {
  const value = (raw ?? "").trim();
  if (descriptor.kind === "locked-checkbox") return descriptor.wireDefault ?? true;
  if (descriptor.kind === "select") return value !== "" ? value : (initialValueFor(descriptor) ?? descriptor.wireDefault);
  if (descriptor.kind === "number") {
    if (value === "") return descriptor.required ? undefined : (descriptor.wireDefault ?? undefined);
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined; // mid-typing garbage → unfilled (G1 states it)
  }
  // text
  if (value !== "") return value;
  return descriptor.required ? undefined : (descriptor.wireDefault ?? "");
}

function serializeRow(row: Record<string, string>, fields: FieldDescriptor[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const field of fields) {
    if (!isScalar(field)) continue;
    const value = serializeScalar(field, row[field.path]);
    if (value !== undefined) out[field.path.split(".").pop()!] = value;
  }
  return out;
}

function serializeForm(state: FormState): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const descriptor of GENERATOR_FIELD_INVENTORY) {
    if (descriptor.kind === "group") {
      const group: Record<string, unknown> = {};
      for (const child of descriptor.children ?? []) {
        if (isScalar(child)) {
          const value = serializeScalar(child, state.scalars[child.path]);
          if (value !== undefined) group[child.path.split(".").pop()!] = value;
        } else if (isRows(child)) {
          group[child.path.split(".").pop()!] = state.rows.map((row) => serializeRow(row, child.rowFields ?? []));
        }
      }
      out[descriptor.path] = group;
    } else if (isScalar(descriptor)) {
      const value = serializeScalar(descriptor, state.scalars[descriptor.path]);
      if (value !== undefined) out[descriptor.path] = value;
    }
  }
  return out;
}

/** Row group helper: the single "rows" descriptor lives under program. */
function rowsDescriptor(): FieldDescriptor | undefined {
  return GENERATOR_FIELD_INVENTORY.find((f) => f.path === "program")?.children?.find((f) => f.path === "program.streams");
}

function FieldRow({
  descriptor,
  value,
  onChange,
  errors,
  disabled,
}: {
  descriptor: FieldDescriptor & { kind: ScalarKind };
  value: string;
  onChange: (next: string) => void;
  errors: FieldError[];
  disabled?: boolean;
}) {
  const id = `dvb-inspector-${descriptor.path}`;
  return (
    <div className="dvb-inspector-field" data-field={descriptor.path}>
      <label htmlFor={id}>
        <span className="dvb-inspector-field-name">{descriptor.path}</span>
        {descriptor.kind === "number" && (
          <input
            id={id}
            type="number"
            value={value}
            onChange={(event) => onChange(event.target.value)}
            disabled={disabled}
          />
        )}
        {descriptor.kind === "text" && (
          <input id={id} type="text" value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled} />
        )}
        {descriptor.kind === "select" && (
          <select id={id} value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled}>
            {(descriptor.options ?? []).map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        )}
        {descriptor.kind === "locked-checkbox" && (
          <input id={id} type="checkbox" checked disabled title={descriptor.hint} />
        )}
      </label>
      {descriptor.hint !== undefined && <span className="dvb-inspector-hint">{descriptor.hint}</span>}
      {errors.map((error) => (
        <span key={error.message} className="dvb-inspector-field-error" role="alert">
          {error.message}
        </span>
      ))}
    </div>
  );
}

export function NodeInspector({
  node,
  fieldErrors,
  onApply,
}: {
  node: TopologyFlowNode | null;
  fieldErrors: FieldError[];
  onApply: (nodeId: string, config: Record<string, unknown>) => void;
}) {
  const [form, setForm] = useState<FormState>(() => projectFrom(node?.data.node.config));
  const [edited, setEdited] = useState(false);

  // Selection switches reset the local form via the parent-supplied `key`
  // (remount; unapplied edits are dropped — the divergence hint stated this
  // while they existed). No effect-based reset by design.

  const spec = useMemo(() => (node === null ? undefined : nodeTypeSpec(node.data.node.node_type)), [node]);

  if (node === null) {
    return (
      <section className="dvb-inspector" aria-label="节点属性表单">
        <h4 className="dvb-inspector-title">节点属性</h4>
        <p className="dvb-inspector-empty">未选中节点</p>
      </section>
    );
  }

  const nodeErrors = fieldErrors.filter((error) => error.nodeId === node.id);
  const rootErrors = nodeErrors.filter((error) => error.fieldPath === "config");
  const nodeLevelErrors = nodeErrors.filter((error) => error.fieldPath === null);
  const errorsFor = (path: string) => nodeErrors.filter((error) => error.fieldPath === path);

  if (spec === undefined || spec.config_schema === null) {
    return (
      <section className="dvb-inspector" aria-label="节点属性表单">
        <h4 className="dvb-inspector-title">节点属性 — {node.id}</h4>
        <p className="dvb-inspector-empty">该类型无配置字段（config 恒 {'{}'}）</p>
        {spec === undefined && <p className="dvb-inspector-note">未注册类型</p>}
        {nodeLevelErrors.map((error) => (
          <span key={error.message} className="dvb-inspector-field-error" role="alert">
            {error.message}
          </span>
        ))}
      </section>
    );
  }

  const rows = rowsDescriptor();

  const setScalar = (path: string, value: string) => {
    setForm((current) => ({ ...current, scalars: { ...current.scalars, [path]: value } }));
    setEdited(true);
  };
  const addRow = () => {
    const template: Record<string, string> = {};
    for (const field of rows?.rowFields ?? []) template[field.path] = toInputString(initialValueFor(field));
    setForm((current) => ({ ...current, rows: [...current.rows, template] }));
    setEdited(true);
  };
  const removeRow = (index: number) => {
    setForm((current) => ({ ...current, rows: current.rows.filter((_, i) => i !== index) }));
    setEdited(true);
  };

  return (
    <section className="dvb-inspector" aria-label="节点属性表单">
      <h4 className="dvb-inspector-title">节点属性 — {node.id}</h4>
      {nodeLevelErrors.map((error) => (
        <span key={error.message} className="dvb-inspector-field-error" role="alert">
          {error.message}
        </span>
      ))}
      {rootErrors.map((error) => (
        <p key={error.message} className="dvb-inspector-banner" role="alert">
          {error.message}
        </p>
      ))}
      {edited && <p className="dvb-inspector-note">有未应用修改</p>}
      {GENERATOR_FIELD_INVENTORY.map((descriptor) => {
        if (descriptor.kind === "group") {
          return (
            <fieldset key={descriptor.path} className="dvb-inspector-group" data-field={descriptor.path}>
              <legend>{descriptor.label}</legend>
              {(descriptor.children ?? []).map((child) => {
                if (isScalar(child)) {
                  return (
                    <FieldRow
                      key={child.path}
                      descriptor={child}
                      value={form.scalars[child.path] ?? ""}
                      onChange={(next) => setScalar(child.path, next)}
                      errors={errorsFor(child.path)}
                    />
                  );
                }
                if (isRows(child)) {
                  return (
                    <div key={child.path} className="dvb-inspector-rows" data-field={child.path}>
                      <div className="dvb-inspector-rows-head">
                        <span className="dvb-inspector-field-name">{child.path}</span>
                        {errorsFor(child.path).map((error) => (
                          <span key={error.message} className="dvb-inspector-field-error" role="alert">
                            {error.message}
                          </span>
                        ))}
                      </div>
                      {form.rows.map((row, index) => (
                        <div key={index} className="dvb-inspector-row">
                          {(child.rowFields ?? []).map((field) =>
                            isScalar(field) ? (
                              <FieldRow
                                key={field.path}
                                descriptor={field}
                                value={row[field.path] ?? ""}
                                onChange={(next) =>
                                  setForm((current) => ({
                                    ...current,
                                    rows: current.rows.map((r, i) => (i === index ? { ...r, [field.path]: next } : r)),
                                  }))
                                }
                                errors={errorsFor(field.path)}
                              />
                            ) : null,
                          )}
                          <button type="button" onClick={() => removeRow(index)}>
                            删行
                          </button>
                        </div>
                      ))}
                      <button type="button" className="dvb-inspector-add-row" onClick={addRow}>
                        增行
                      </button>
                    </div>
                  );
                }
                return null;
              })}
            </fieldset>
          );
        }
        if (isScalar(descriptor)) {
          return (
            <FieldRow
              key={descriptor.path}
              descriptor={descriptor}
              value={form.scalars[descriptor.path] ?? ""}
              onChange={(next) => setScalar(descriptor.path, next)}
              errors={errorsFor(descriptor.path)}
            />
          );
        }
        return null;
      })}
      {rows === undefined && null}
      <button
        type="button"
        className="dvb-inspector-apply"
        onClick={() => {
          onApply(node.id, serializeForm(form));
          setEdited(false);
        }}
      >
        应用到草稿
      </button>
    </section>
  );
}
