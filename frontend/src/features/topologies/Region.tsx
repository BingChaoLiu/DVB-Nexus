// Topologies route region — placeholder shell; the topology editor (canvas,
// node panel, forms) lands with SPEC-401 (#62), which owns this directory.
import { EmptyState, Panel } from "../../components/ui";

export default function TopologiesRegion() {
  return (
    <Panel title="Topologies">
      <EmptyState
        title="拓扑编辑器落地中"
        note="本路由区由 SPEC-401（#62）实现：拖放建节点、端口级连线（ADR-0009 @xyflow/react）。"
      />
    </Panel>
  );
}
