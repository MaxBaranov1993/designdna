import { useRef } from "react";
import { Handle, Position } from "@xyflow/react";
import type { NodeProps } from "@xyflow/react";
import { IrPreview } from "../components/IrPreview";
import { toast } from "../flow/toast";
import { useFlowStore } from "../flow/store";
import { useEditorStore } from "../editor/store";
import type { EditFlowNode } from "../flow/types";
import { NodeShell, NodeStatus } from "./NodeShell";
import { OutPorts } from "./PortHandles";

/* «Редактор (DNA)» в графе — thin node.
 * Нода не дублирует Figma/Pen.dev-инструменты: внутри графа только read-only
 * превью, а вся работа с GeoEdit/Inspector/Layers/Tools/Undo живёт в
 * полноэкранном React DNA Editor (frontend/src/editor). Одна редактирующая
 * поверхность и один контракт сохранения IR. */

export function EditNode({ id, data, selected }: NodeProps<EditFlowNode>) {
  const nodeId = Number(id);
  const hasIr = Boolean(data.ir);
  const inputs = data.inputs || ["ir"];
  const addEditInput = useFlowStore((s) => s.addEditInput);
  const removeEditInput = useFlowStore((s) => s.removeEditInput);
  const reorderEditInputs = useFlowStore((s) => s.reorderEditInputs);
  const dragFrom = useRef<number | null>(null);
  const sources = Object.values(data.sourceRegistry || {});

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
      <div className="edit-inputs-label">Компоненты · порядок сверху вниз</div>
      {inputs.map((name, index) => (
        <div
          key={name}
          className="edit-input-row port-row in"
          data-port={name}
          data-kind="ir"
          draggable
          onDragStart={() => { dragFrom.current = index; }}
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            if (dragFrom.current !== null) reorderEditInputs(nodeId, dragFrom.current, index);
            dragFrom.current = null;
          }}
        >
          <Handle id={name} type="target" position={Position.Left} className={"port-dot port-ir pp-in-" + name} />
          <span className="page-grip nodrag">⠿</span>
          <span className="cap">{name}</span>
          <span className="page-row-ctl nodrag">
            <button className="mx" title="Выше" disabled={index === 0} onClick={() => reorderEditInputs(nodeId, index, index - 1)}>↑</button>
            <button className="mx" title="Ниже" disabled={index === inputs.length - 1} onClick={() => reorderEditInputs(nodeId, index, index + 1)}>↓</button>
            <button className="mx" title="Убрать вход" onClick={() => removeEditInput(nodeId, name)}>✕</button>
          </span>
        </div>
      ))}
      <button className="btn-node small edit-add-input nodrag" onClick={() => addEditInput(nodeId)}>+ компонент</button>
      <div className="edit-preview-card nodrag">
        <IrPreview
          ir={data.ir}
          height={240}
          fitHeight
          className="f-preview"
          empty="Подключите IR — здесь будет только превью"
        />
        <div className="edit-preview-meta">
          <span>{hasIr ? `${sources.length || 1} источн.` : "Нет IR на входе"}</span>
          <span>{hasIr ? "Source Lens внутри" : "подключите компоненты"}</span>
        </div>
      </div>
      {sources.length ? (
        <div className="edit-source-list" aria-label="Источники компонентов">
          {sources.map((source) => (
            <span key={source.id} className="edit-source-chip" title={`${source.label} · confidence ${Math.round((source.confidence ?? 1) * 100)}%`}>
              <b>{source.symbol || "S"}</b>{source.label}
            </span>
          ))}
        </div>
      ) : null}
      <button className="btn-node primary small f-open-editor nodrag" style={{ width: "100%" }} onClick={openEditor}>
        ✦ Открыть DNA-редактор
      </button>
      <NodeStatus id={id} />
      <OutPorts type="edit" />
    </NodeShell>
  );
}
