import type { NodeProps } from "@xyflow/react";
import { IrPreview } from "../components/IrPreview";
import { toast } from "../flow/toast";
import type { EditFlowNode } from "../flow/types";
import { NodeShell, NodeStatus } from "./NodeShell";
import { InPorts, OutPorts } from "./PortHandles";

/* «Редактор (DNA)» — потребитель IR по проводу (propagate кладёт клон в data.ir).
 * Превью — renderer.js через IrPreview; прокид ir на выход даёт outValue(edit).
 * GeoEdit-правка монтируется в Фазе B3 (FLOW-MIGRATION.md §6). */
export function EditNode({ id, data, selected }: NodeProps<EditFlowNode>) {
  return (
    <NodeShell id={id} type="edit" selected={selected}>
      <InPorts type="edit" />
      <IrPreview
        className="f-preview"
        ir={data.ir}
        height={280}
        empty="Подключите IR к входу (или через GraphDev.setIR)"
      />
      <button
        className="btn-node primary small f-open-editor nodrag"
        style={{ width: "100%" }}
        onClick={() => toast("GeoEdit-правка монтируется в Фазе B3")}
      >
        ✦ Открыть DNA-редактор
      </button>
      <NodeStatus id={id} />
      <OutPorts type="edit" />
    </NodeShell>
  );
}
