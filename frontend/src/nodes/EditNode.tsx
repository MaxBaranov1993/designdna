import type { NodeProps } from "@xyflow/react";
import { toast } from "../flow/toast";
import type { EditFlowNode } from "../flow/types";
import { NodeShell, NodeStatus } from "./NodeShell";
import { InPorts, OutPorts } from "./PortHandles";

/* «Редактор (DNA)» — потребитель IR по проводу (propagate кладёт клон в data.ir).
 * B1: заглушка тела с правильными handles (in ir / out ir); превью через renderer.js
 * и GeoEdit-инструменты монтируются в Фазе B2 (FLOW-MIGRATION.md §6, прямое монтирование). */
export function EditNode({ id, data, selected }: NodeProps<EditFlowNode>) {
  return (
    <NodeShell id={id} type="edit" selected={selected}>
      <InPorts type="edit" />
      <div className="edit-placeholder">
        {data.ir
          ? "IR получен. Превью и Figma-инструменты (renderer.js + GeoEdit) монтируются в Фазе B2"
          : "Подключите IR к входу (или через GraphDev.setIR)"}
      </div>
      <button
        className="btn-node primary small f-open-editor nodrag"
        style={{ width: "100%" }}
        onClick={() => toast("DNA-редактор монтируется в Фазе B2")}
      >
        ✦ Открыть DNA-редактор
      </button>
      <NodeStatus id={id} />
      <OutPorts type="edit" />
    </NodeShell>
  );
}
