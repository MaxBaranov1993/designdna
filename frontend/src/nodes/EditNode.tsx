import type { NodeProps } from "@xyflow/react";
import { IrPreview } from "../components/IrPreview";
import { deepClone } from "../flow/dataflow";
import { useFlowStore } from "../flow/store";
import { toast } from "../flow/toast";
import { useEditorStore } from "../editor/store";
import type { EditFlowNode, IRObject } from "../flow/types";
import { NodeShell, NodeStatus } from "./NodeShell";
import { InPorts, OutPorts } from "./PortHandles";

declare global {
  interface Window {
    Editor?: {
      open: (
        node: { data: { ir: IRObject | null } },
        onSave: (ir: IRObject) => void,
        onClose?: (saved: boolean) => void,
      ) => void;
      close: () => void;
      isOpen: () => boolean;
    };
  }
}

/* «Редактор (DNA)» в графе — thin node.
 * Нода не дублирует Figma/Pen.dev-инструменты: внутри графа только read-only
 * превью, а вся работа с GeoEdit/Inspector/Layers/Tools/Undo живёт в
 * полноэкранном DNA Editor (app/static/editor.js). Так у продукта одна
 * редактирующая поверхность и один контракт сохранения IR. */

export function EditNode({ id, data, selected }: NodeProps<EditFlowNode>) {
  const nodeId = Number(id);
  const hasIr = Boolean(data.ir);

  const openEditor = () => {
    if (!data.ir) {
      toast("Сначала подключите IR к входу ноды", "error");
      return;
    }

    // По умолчанию — React DNA Editor (frontend/src/editor): та же семантика
    // snapshot/save/propagate внутри editor store. Legacy editor.js — fallback,
    // если движки-«острова» ещё не загрузились.
    if (useEditorStore.getState().openEditor(nodeId)) return;

    if (!window.Editor) {
      toast("DNA-редактор ещё не загружен", "error");
      return;
    }

    // DNA Editor мутирует IR in-place. Write-through shim держит граф и редактор
    // на одном объекте, чтобы undo/redo и инспектор сразу отражались в ноде.
    // Для «Закрыть без сохранения» делаем снапшот до открытия и восстанавливаем.
    const snapshot = data.ir ? deepClone(data.ir) : null;
    let saved = false;
    const nodeLike: { data: { ir: IRObject | null } } = {
      data: {
        get ir(): IRObject | null {
          const n = useFlowStore.getState().nodes.find((x) => Number(x.id) === nodeId);
          return n ? (n.data as { ir?: IRObject | null }).ir ?? null : null;
        },
        set ir(v: IRObject | null) {
          useFlowStore.getState().setNodeData(nodeId, { ir: v });
        },
      },
    };

    window.Editor.open(
      nodeLike,
      (savedIr: IRObject) => {
        saved = true;
        const st = useFlowStore.getState();
        st.setNodeData(nodeId, { ir: savedIr });
        st.propagate(nodeId);
        toast("IR сохранён из редактора", "ok");
      },
      () => {
        if (!saved && snapshot) {
          const st = useFlowStore.getState();
          st.setNodeData(nodeId, { ir: snapshot });
          st.propagate(nodeId);
        }
      },
    );
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
