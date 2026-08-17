import { useRef } from "react";
import { Handle, Position } from "@xyflow/react";
import type { NodeProps } from "@xyflow/react";
import { IrPreview } from "../components/IrPreview";
import { useFlowStore } from "../flow/store";
import type { PageFlowNode, SourceViewport } from "../flow/types";
import { NodeShell, NodeStatus } from "./NodeShell";
import { OutPorts } from "./PortHandles";

/* «Страница» — компоновщик: собирает подключённые блоки (Генератор/Source
 * Import/Редактор) в одну страницу. Детерминированно, без LLM (composePage).
 * Входы динамические из data.inputs (паттерн MixNode): drag-порядок строк =
 * порядок секций на странице, «+ вход» (макс. 8), «✕» снимает провода входа.
 * Вход tokens (style DNA) задаёт токены страницы; без него — токены последнего
 * стилизованного блока (main content, а не Header). Артборд 1440, секции width:"fill", responsive-override'ы сохраняются. */
export function PageNode({ id, data, selected }: NodeProps<PageFlowNode>) {
  const setNodeData = useFlowStore((s) => s.setNodeData);
  const propagate = useFlowStore((s) => s.propagate);
  const runNode = useFlowStore((s) => s.runNode);
  const sendToNode = useFlowStore((s) => s.sendToNode);
  const addPageInput = useFlowStore((s) => s.addPageInput);
  const removePageInput = useFlowStore((s) => s.removePageInput);
  const reorderPageInputs = useFlowStore((s) => s.reorderPageInputs);
  const dragFrom = useRef<number | null>(null);
  const setViewport = (viewport: SourceViewport) => {
    setNodeData(Number(id), { activeViewport: viewport });
    // вьюпорт едет вниз по графу через outValue → meta.activeViewport
    queueMicrotask(() => propagate(Number(id)));
  };
  return (
    <NodeShell id={id} type="page" selected={selected}>
      <div className="port-row in" data-port="tokens" data-kind="tokens">
        <Handle id="tokens" type="target" position={Position.Left} className="port-dot port-tokens pp-in-tokens" />
        <span className="plabel">style DNA</span>
      </div>
      {data.inputs.map((name, idx) => (
        <div
          key={name}
          className="mix-row port-row in page-row"
          data-port={name}
          data-kind="ir"
          draggable
          onDragStart={(e) => {
            dragFrom.current = idx;
            e.dataTransfer.effectAllowed = "move";
          }}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            if (dragFrom.current !== null) reorderPageInputs(Number(id), dragFrom.current, idx);
            dragFrom.current = null;
          }}
          title="Порядок строк = порядок секций на странице (таскайте)"
        >
          <Handle
            id={name}
            type="target"
            position={Position.Left}
            className={"port-dot port-ir pp-in-" + name}
          />
          <span className="page-grip nodrag">⠿</span>
          <span className="cap">{name}</span>
          <span className="page-row-ctl nodrag">
            <button
              className="mx"
              title="Выше"
              disabled={idx === 0}
              onClick={() => reorderPageInputs(Number(id), idx, idx - 1)}
            >
              ↑
            </button>
            <button
              className="mx"
              title="Ниже"
              disabled={idx === data.inputs.length - 1}
              onClick={() => reorderPageInputs(Number(id), idx, idx + 1)}
            >
              ↓
            </button>
            <button className="mx" title="Убрать вход" onClick={() => removePageInput(Number(id), name)}>
              ✕
            </button>
          </span>
        </div>
      ))}
      <div className="ctl-row">
        <button className="btn-node small f-add-in nodrag" onClick={() => addPageInput(Number(id))}>
          + вход
        </button>
        <button
          className="btn-node primary small f-run nodrag"
          style={{ marginLeft: "auto" }}
          onClick={() => runNode(Number(id))}
        >
          ▤ Собрать страницу
        </button>
      </div>
      <div className="source-viewports nodrag" aria-label="Page viewport">
        {(["desktop", "tablet", "mobile"] as SourceViewport[]).map((viewport) => (
          <button
            key={viewport}
            className={"source-viewport" + (data.activeViewport === viewport ? " active" : "")}
            onClick={() => setViewport(viewport)}
            title={viewport === "desktop" ? "1440 px" : viewport === "tablet" ? "768 px" : "390 px"}
          >
            {viewport === "desktop" ? "Desktop" : viewport === "tablet" ? "Tablet" : "Mobile"}
          </button>
        ))}
      </div>
      <IrPreview
        className="f-preview"
        ir={data.ir}
        height={320}
        fitHeight
        viewport={data.activeViewport}
        empty="Подключите блоки и нажмите «Собрать страницу»"
      />
      <div className="gen-actions">
        <button className="btn-node small f-to-editor nodrag" onClick={() => sendToNode(Number(id), "edit")}>
          → Editor
        </button>
      </div>
      <NodeStatus id={id} />
      <OutPorts type="page" data={data} />
    </NodeShell>
  );
}
