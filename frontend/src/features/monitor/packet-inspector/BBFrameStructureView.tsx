// SPEC-404 §Phase2 view=bbframe — the BBFrame face (EN 302 755 §5.1.7):
// BBHEADER 10-byte fields (MATYPE/UPL/DFL/SYNC/SYNCD/CRC-8) per frame row +
// CRC-8 校验 + UP 边界标注 (up_count/up_indices) + the SYNCD teaching anchor
// VERBATIM (SPEC-404 §Phase2: 「SYNCD 是数据字段内首个 UP 的位距离，不是同步字节」).
// All wire keys render verbatim; units stay as declared (upl/dfl/syncd in
// bits — the #129 wire notes). No packet_index→frame mapping is fabricated:
// the locator triple keeps its packet semantics, rows are frame-indexed.
import type { BBFrameStructureRowDTO, BBFrameStructureViewDTO } from "../../../api";
import { FieldRow, hex2, hex4 } from "./fields";

/** The teaching anchor, verbatim per SPEC-404 §Phase2 (copy discipline: this
 * sentence is pinned word-for-word by the component tests). */
export const SYNCD_TEACHING_ANCHOR = "SYNCD 是数据字段内首个 UP 的位距离，不是同步字节";

function FrameDetail({ frame }: { frame: BBFrameStructureRowDTO }) {
  return (
    <div className="dvb-pi-fields" data-testid={`bbframe-detail-${frame.frame_index}`}>
      <FieldRow name="MATYPE" value={hex4(frame.matype)} note="16-bit raw（EN 302 755 §5.1.7）" />
      <FieldRow name="UPL" value={String(frame.upl)} note="bits（User Packet Length）" />
      <FieldRow name="DFL" value={String(frame.dfl)} note="bits（Data Field Length，实际载荷）" />
      <FieldRow name="SYNC" value={hex2(frame.sync)} note="UP 内同步字节原样值" />
      <FieldRow name="SYNCD" testid={`bbframe-syncd-${frame.frame_index}`} value={String(frame.syncd)} note="bits——见教学锚点" />
      <FieldRow
        name="CRC-8"
        testid={`bbframe-crc8-${frame.frame_index}`}
        value={frame.crc8_valid ? "true" : "false"}
        note={frame.crc8_valid ? "CRC-8 校验通过（头 9 字节）" : "CRC-8 校验失败——帧标记（解析继续，不静默丢弃）"}
      />
      <FieldRow name="up_count" testid={`bbframe-up-count-${frame.frame_index}`} value={String(frame.up_count)} note="恢复出的 UP 数" />
      <FieldRow
        name="up_indices"
        testid={`bbframe-up-indices-${frame.frame_index}`}
        value={(frame.up_indices ?? []).join(",")}
        note="UP 边界（数据字段内字节偏移）"
      />
      <FieldRow name="state" value={frame.state} note="wire 状态原样（§8 显式态）" />
    </div>
  );
}

export function BBFrameStructureView({ structure }: { structure: BBFrameStructureViewDTO }) {
  return (
    <div className="dvb-pi-structure" data-testid="bbframe-structure-view">
      <h4 className="dvb-pi-section">BBFrame 视图（EN 302 755 §5.1.7）</h4>
      <p className="dvb-pi-line" data-testid="bbframe-summary">
        frame_count={structure.frame_count}
      </p>
      <p className="dvb-pi-note" data-testid="bbframe-syncd-anchor">
        {SYNCD_TEACHING_ANCHOR}
      </p>
      <div className="dvb-pi-rows" data-testid="bbframe-rows">
        {structure.frames?.map((frame) => (
          <div className="dvb-pi-row" data-testid={`bbframe-row-${frame.frame_index}`} key={frame.frame_index}>
            <span className="dvb-pi-row-key">#{frame.frame_index}</span>
            <span className="dvb-pi-row-cell">matype={hex4(frame.matype)}</span>
            <span className="dvb-pi-row-cell">dfl={frame.dfl}b</span>
            <span className="dvb-pi-row-cell">syncd={frame.syncd}b</span>
            <span className={`dvb-pi-row-cell${frame.crc8_valid ? "" : " dvb-pi-row-bad"}`}>
              crc8={frame.crc8_valid ? "ok" : "BAD"}
            </span>
            <span className="dvb-pi-row-cell">ups={frame.up_count}</span>
            <span className="dvb-pi-row-cell">{frame.state}</span>
          </div>
        ))}
      </div>
      {structure.frames === undefined && (
        <p className="dvb-pi-note" data-testid="bbframe-rows-absent">
          wire 未携带 frames 行集（键缺省）——诚实缺席，不伪造行。
        </p>
      )}
      {structure.frames?.map((frame) => <FrameDetail frame={frame} key={frame.frame_index} />)}
    </div>
  );
}
