import type { NodeProps } from "@xyflow/react";
import { IrPreview } from "../components/IrPreview";
import { toast } from "../flow/toast";
import { useEditorStore } from "../editor/store";
import type { EditFlowNode } from "../flow/types";
import { NodeShell, NodeStatus } from "./NodeShell";
import { InPorts, OutPorts } from "./PortHandles";

/* «Редактор (DNA)» в графе — thin node.
 * Нода не дублирует Figma/Pen.dev-инструменты: внутри графа только read-only
 * превью, а вся работа с GeoEdit/Inspector/Layers/Tools/Undo живёт в
 * полноэкранном React DNA Editor (frontend/src/editor). Одна редактирующая
 * поверхность и один контракт сохранения IR. */

export function EditNode({ id, data, selected }: NodeProps<EditFlowNode>) {
  const nodeId = Number(id);
  const hasIr = Boolean(data.ir);

  const openEditor = () => {
    if (!data.ir) {
      toast("Сначала подключите IR к входу ноды", "error");
      return;
    }
    // React DNA Editor: snapshot/save/propagate — внутри editor store.
    useEditorStore.getState().openEditor(nodeId);
  };

  return (
    <NodeShell id={id} type="edit" selected={selected}>
      <InPorts type="edit" />
      <div className="edit-preview-card nodrag">
        <IrPreview
          ir={data.ir}
          height={240}
          fitHeight
          className="f-preview"
          empty="Подключите IR — здесь будет только превью"
        />
        <div className="edit-preview-meta">
          <span>{hasIr ? "Read-only preview" : "Нет IR на входе"}</span>
          <span>{hasIr ? "редактирование внутри" : "подключите провод IR"}</span>
        </div>
      </div>
      <button className="btn-node primary small f-open-editor nodrag" style={{ width: "100%" }} onClick={openEditor}>
        ✦ Открыть DNA-редактор
      </button>
      <NodeStatus id={id} />
      <OutPorts type="edit" />
    </NodeShell>
  );
}
