// SPEC-404 §4 — minimal evidence drill-down panel (controlled presentation:
// locator in via props, wire facts rendered verbatim, no local derivation of
// any diagnosis/verdict semantics — CONTEXT.md 诊断/通关 bans apply). All
// non-ready branches render explicit states; no branch may masquerade as
// success (SPEC-404 §8).
import "./packet-inspector.css";
import type { DiagnosisEvidenceDTO } from "../types";
import { MONITOR_EMPTY_STATE_COPY } from "../copy";
import { ThreeQuestionState } from "../ThreeQuestionState";
import { type HexRow, TS_SYNC_BYTE } from "./decode";
import { usePacketDrillDown } from "./usePacketDrillDown";

const AFC_LABEL: Record<number, string> = {
  0b00: "reserved/invalid（SPEC-100 §3）",
  0b01: "payload only",
  0b10: "adaptation only",
  0b11: "adaptation + payload",
};

const SCRAMBLING_LABEL: Record<number, string> = {
  0b00: "不扰码",
  0b01: "用户定义",
  0b10: "用户定义（DVB 惯例：偶钥）",
  0b11: "用户定义（DVB 惯例：奇钥）",
};

const hex2 = (n: number) => `0x${n.toString(16).padStart(2, "0")}`;
const hex4 = (n: number) => `0x${n.toString(16).padStart(4, "0")}`;
const bits2 = (n: number) => n.toString(2).padStart(2, "0");

function FieldRow({ name, testid, value, note }: { name: string; testid?: string; value: string; note?: string }) {
  return (
    <div className="dvb-pi-field" data-testid={testid}>
      <span className="dvb-pi-field-name">{name}</span>
      <span className="dvb-pi-field-value">{value}</span>
      {note !== undefined && <span className="dvb-pi-field-note">{note}</span>}
    </div>
  );
}

function HexDump({ rows }: { rows: HexRow[] }) {
  return (
    <div className="dvb-pi-hex" aria-label="hex dump">
      {rows.map((row) => (
        <div className="dvb-pi-hex-row" data-testid={`inspect-hex-row-${row.offset / 16}`} key={row.offset}>
          <span className="dvb-pi-hex-offset">{row.offset.toString(16).padStart(4, "0")}</span>
          <span className="dvb-pi-hex-cells">
            {row.hex.map((cell, i) => (
              <span key={i} className={row.offset + i < 4 ? "dvb-pi-hex-header-byte" : undefined}>
                {cell}
              </span>
            ))}
          </span>
          <span className="dvb-pi-hex-ascii">{row.ascii}</span>
        </div>
      ))}
    </div>
  );
}

export function PacketInspectorSection({
  locator,
  onClose,
}: {
  locator: DiagnosisEvidenceDTO | null;
  onClose: () => void;
}) {
  const state = usePacketDrillDown(locator);

  if (locator === null || state.phase === "idle") {
    // §4.6 Monitor 组行 7(文案逐字):未进入下钻时的显式指路面;不渲染
    // packet-inspector 面板本体(无假面板)。
    return <ThreeQuestionState copy={MONITOR_EMPTY_STATE_COPY.packetInspector} />;
  }

  return (
    <section className="dvb-pi-panel" data-testid="packet-inspector" aria-label="packet inspector">
      <div className="dvb-pi-head">
        <span className="dvb-pi-title">包证据下钻</span>
        <span className="dvb-pi-locator">
          artifact {locator.artifact_id} / <span data-testid="inspect-locator-pid">pid {locator.pid}</span> /{" "}
          <span data-testid="inspect-packet-index">packet {locator.packet_index}</span>
        </span>
        <button type="button" className="dvb-pi-close" onClick={onClose}>
          关闭
        </button>
      </div>

      {state.phase === "loading-meta" && <p className="dvb-pi-line" data-testid="inspect-loading">读取 artifact 元数据…</p>}
      {state.phase === "loading-content" && <p className="dvb-pi-line" data-testid="inspect-loading">按 Range 取单包…</p>}

      {state.phase === "meta-invalid" && (
        <p className="dvb-pi-error" data-testid="inspect-meta-invalid">
          非 188 包几何：artifact 声明 packet_size={state.packetSize ?? "（未声明）"}（SPEC-100 §3 要求 188），不下钻。
        </p>
      )}
      {state.phase === "out-of-range" && (
        <p className="dvb-pi-error" data-testid="inspect-out-of-range">
          packet {state.packetIndex} 越界：artifact 共 {state.packetCount} 包（416 语义预判；服务端裁决为准）。
        </p>
      )}
      {state.phase === "truncated" && (
        <p className="dvb-pi-error" data-testid="inspect-truncated">
          响应截断：期待 188 字节，实到 {state.byteCount} 字节（Content-Range: {state.contentRange ?? "缺失"}），不解码。
        </p>
      )}
      {state.phase === "error" && (
        <p className="dvb-pi-error" data-testid="inspect-error">
          取包失败（{state.source === "meta" ? "元数据" : "内容"}）：HTTP {state.status} · {state.errorCode} · {state.message}
        </p>
      )}

      {state.phase === "ready" && (
        <>
          <p className="dvb-pi-line" data-testid="inspect-content-range">
            206 · Content-Range: {state.contentRange ?? "缺失"} · Accept-Ranges: {state.acceptRanges ?? "缺失"} ·{" "}
            {state.byteCount} 字节
          </p>
          {!state.view.header.sync_byte_ok && (
            <p className="dvb-pi-error" data-testid="inspect-sync-warning">
              sync_byte = {hex2(state.view.header.sync_byte)} ≠ 0x47（TS_SYNC_BYTE，SPEC-100 §3）——包对齐可疑，字段仍按位呈现。
            </p>
          )}
          <HexDump rows={state.hexRows} />

          <div className="dvb-pi-fields">
            <h4 className="dvb-pi-section">TS Header（SPEC-100 §3）</h4>
            <FieldRow name="sync_byte" testid="inspect-field-sync" value={hex2(state.view.header.sync_byte)} note={state.view.header.sync_byte_ok ? "固定 0x47" : "≠ 0x47"} />
            <FieldRow name="transport_error_indicator" testid="inspect-field-tei" value={state.view.header.transport_error_indicator ? "1" : "0"} note="TEI" />
            <FieldRow name="payload_unit_start_indicator" testid="inspect-field-pusi" value={state.view.header.payload_unit_start_indicator ? "1" : "0"} note="PUSI" />
            <FieldRow name="transport_priority" testid="inspect-field-priority" value={state.view.header.transport_priority ? "1" : "0"} />
            <FieldRow
              name="pid"
              testid="inspect-field-pid"
              value={hex4(state.view.header.pid)}
              note={state.view.header.pid_is_null ? "0x1FFF = null 包" : undefined}
            />
            <FieldRow name="transport_scrambling_control" testid="inspect-field-scrambling" value={bits2(state.view.header.transport_scrambling_control)} note={SCRAMBLING_LABEL[state.view.header.transport_scrambling_control]} />
            <FieldRow name="adaptation_field_control" testid="inspect-field-afc" value={bits2(state.view.header.adaptation_field_control)} note={AFC_LABEL[state.view.header.adaptation_field_control]} />
            <FieldRow name="continuity_counter" testid="inspect-field-cc" value={String(state.view.header.continuity_counter)} note="per-PID 连续" />

            {state.view.adaptation_field !== null ? (
              <div className="dvb-pi-af" data-testid="inspect-af">
                <h4 className="dvb-pi-section">Adaptation Field（SPEC-100 §5.2）</h4>
                <FieldRow name="af_length" testid="inspect-af-length" value={String(state.view.adaptation_field.af_length)} note={state.view.adaptation_field.flags_present ? undefined : "length=0 → 无 flags 字节"} />
                {state.view.adaptation_field.flags !== null && (
                  <>
                    <FieldRow name="flags (raw)" testid="inspect-af-flags" value={hex2(state.view.adaptation_field.flags)} />
                    <FieldRow name="discontinuity_indicator" value={state.view.adaptation_field.discontinuity_indicator ? "1" : "0"} />
                    <FieldRow name="random_access_indicator" testid="inspect-field-rai" value={state.view.adaptation_field.random_access_indicator ? "1" : "0"} note="flags 0x40" />
                    <FieldRow name="elementary_stream_priority_indicator" value={state.view.adaptation_field.elementary_stream_priority_indicator ? "1" : "0"} />
                    <FieldRow name="PCR_flag" testid="inspect-field-pcr-flag" value={state.view.adaptation_field.pcr_flag ? "1" : "0"} note="flags 0x10" />
                    <FieldRow name="OPCR_flag" value={state.view.adaptation_field.opcr_flag ? "1" : "0"} />
                    <FieldRow name="splice_countdown_flag" value={state.view.adaptation_field.splice_countdown_flag ? "1" : "0"} />
                    <FieldRow name="transport_private_data_flag" value={state.view.adaptation_field.transport_private_data_flag ? "1" : "0"} />
                    <FieldRow name="adaptation_field_extension_flag" value={state.view.adaptation_field.adaptation_field_extension_flag ? "1" : "0"} />
                    {state.view.adaptation_field.pcr !== null && (
                      <div className="dvb-pi-pcr" data-testid="inspect-pcr">
                        <FieldRow name="pcr_base (33 bit)" testid="inspect-pcr-base" value={String(state.view.adaptation_field.pcr.base)} />
                        <FieldRow name="pcr_extension (9 bit)" testid="inspect-pcr-extension" value={String(state.view.adaptation_field.pcr.extension)} note={state.view.adaptation_field.pcr.reserved_ok ? "reserved 111111" : "reserved 位异常（须 111111）"} />
                        <FieldRow name="combined_ticks (base×300+ext)" testid="inspect-pcr-ticks" value={String(state.view.adaptation_field.pcr.combined_ticks)} note="27 MHz（SPEC-105）" />
                      </div>
                    )}
                  </>
                )}
              </div>
            ) : (
              state.view.header.adaptation_field_control === 0b00 && (
                <p className="dvb-pi-note" data-testid="inspect-afc-reserved">
                  AFC=00 reserved/invalid（SPEC-100 §3）——AF 区域不解析（wire 原样呈现）。
                </p>
              )
            )}
          </div>
        </>
      )}
    </section>
  );
}

// TS_SYNC_BYTE is re-exported for the presentation gate only; keeps the
// constant usage explicit without widening decode's export surface here.
void TS_SYNC_BYTE;
