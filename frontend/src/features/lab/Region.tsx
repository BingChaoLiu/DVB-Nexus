// Lab route region — placeholder shell; the Training Lab (scenario library,
// hints, eight-step stepper) lands with SPEC-406 (#67), which owns this
// directory.
import { EmptyState, Panel } from "../../components/ui";

export default function LabRegion() {
  return (
    <Panel title="Lab">
      <EmptyState
        title="Training Lab 落地中"
        note="本路由区由 SPEC-406（#67）实现：场景库 + hints 渐进揭示 + 八步闭环 stepper。"
      />
    </Panel>
  );
}
