// SPEC-404 §Phase2 view=t2mi — the T2-MI packet face (TS 102 773 §5.1):
// per-packet structure-JSON rows (the json_map chain wire, 禁手写 mirror) +
// CRC-32 校验结果 + BBFrame 载荷指针 (frame_index/plp_id). The locator's
// packet_index selects the row (FirstFailureRef packet_position locator);
// unmatched locators stay honest — rows render, no fabricated selection.
// wire enums (payload_kind bbframe|padding|unknown) render verbatim.
import type { T2miPacketDTO, T2miStructureViewDTO } from "../../../api";
import type { DiagnosisEvidenceDTO } from "../types";
import { FieldRow, hex2 } from "./fields";

function PacketDetail({ packet }: { packet: T2miPacketDTO }) {
  return (
    <div className="dvb-pi-fields" data-testid={`t2mi-detail-${packet.packet_index}`}>
      <FieldRow name="packet_type" value={hex2(packet.packet_type)} note="包头字节 0（TS 102 773 §5.1）" />
      <FieldRow name="packet_counter" value={String(packet.packet_counter)} note={`包头字节 1（mod-256，${hex2(packet.packet_counter)}）`} />
      <FieldRow name="payload_kind" testid={`t2mi-payload-kind-${packet.packet_index}`} value={packet.payload_kind} note="wire 枚举原样" />
      <FieldRow name="payload_bytes_len" value={String(packet.payload_bytes_len)} />
      <FieldRow
        name="crc32_valid"
        testid={`t2mi-crc32-${packet.packet_index}`}
        value={packet.crc32_valid ? "true" : "false"}
        note={packet.crc32_valid ? "CRC-32 校验通过" : "CRC-32 校验失败——坏包标记（解析继续，不静默丢弃）"}
      />
      {packet.frame_index === null || packet.frame_index === undefined ? (
        <FieldRow name="frame_index" value="null" note="非 BBFRAME 载荷——诚实三态，不伪造指针" />
      ) : (
        <FieldRow
          name="frame_index"
          testid={`t2mi-frame-pointer-${packet.packet_index}`}
          value={String(packet.frame_index)}
          note="BBFrame 载荷指针（view=bbframe 的 frame_index）"
        />
      )}
      {packet.plp_id === null || packet.plp_id === undefined ? (
        <FieldRow name="plp_id" value="null" note="传输前缀未声明（非 BBFRAME 包）" />
      ) : (
        <FieldRow name="plp_id" testid={`t2mi-plp-${packet.packet_index}`} value={String(packet.plp_id)} note="传输前缀 PLP id" />
      )}
    </div>
  );
}

export function T2miStructureView({
  structure,
  locator,
}: {
  structure: T2miStructureViewDTO;
  locator: DiagnosisEvidenceDTO | null;
}) {
  const selectedIndex =
    locator === null
      ? null
      : structure.packets?.find((packet) => packet.packet_index === locator.packet_index) ?? null;
  const selected =
    selectedIndex !== null && selectedIndex !== undefined ? (
      <PacketDetail packet={selectedIndex} />
    ) : locator !== null ? (
      <p className="dvb-pi-note" data-testid="t2mi-locator-unmatched">
        locator packet {locator.packet_index} 不在本层行集内（packet_count={structure.packet_count}）——行照常呈现，不伪造选中。
      </p>
    ) : null;

  return (
    <div className="dvb-pi-structure" data-testid="t2mi-structure-view">
      <h4 className="dvb-pi-section">T2-MI 包视图（TS 102 773 §5.1）</h4>
      <p className="dvb-pi-line" data-testid="t2mi-summary">
        packet_count={structure.packet_count}
        {structure.truncated && (
          <>
            {" "}
            · <span data-testid="t2mi-truncated">truncated=true · 尾部 {structure.trailing_bytes} 字节原样保留计数（不静默丢弃）</span>
          </>
        )}
      </p>
      <div className="dvb-pi-rows" data-testid="t2mi-rows">
        {structure.packets?.map((packet) => (
          <div
            className={`dvb-pi-row${packet.packet_index === locator?.packet_index ? " dvb-pi-row-selected" : ""}`}
            data-testid={`t2mi-row-${packet.packet_index}`}
            key={packet.packet_index}
          >
            <span className="dvb-pi-row-key">#{packet.packet_index}</span>
            <span className="dvb-pi-row-cell">type={hex2(packet.packet_type)}</span>
            <span className="dvb-pi-row-cell">counter={packet.packet_counter}</span>
            <span className="dvb-pi-row-cell">{packet.payload_kind}</span>
            <span className="dvb-pi-row-cell">{packet.payload_bytes_len}B</span>
            <span className={`dvb-pi-row-cell${packet.crc32_valid ? "" : " dvb-pi-row-bad"}`}>
              crc32={packet.crc32_valid ? "ok" : "BAD"}
            </span>
            <span className="dvb-pi-row-cell">
              {packet.frame_index === null || packet.frame_index === undefined ? "" : `frame=${packet.frame_index}`}
            </span>
            <span className="dvb-pi-row-cell">
              {packet.plp_id === null || packet.plp_id === undefined ? "" : `plp=${packet.plp_id}`}
            </span>
          </div>
        ))}
      </div>
      {structure.packets === undefined && (
        <p className="dvb-pi-note" data-testid="t2mi-rows-absent">
          wire 未携带 packets 行集（键缺省）——诚实缺席，不伪造行。
        </p>
      )}
      {selected}
    </div>
  );
}
