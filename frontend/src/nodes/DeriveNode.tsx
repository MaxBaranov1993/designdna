import type { NodeProps } from "@xyflow/react";
import { IrPreview } from "../components/IrPreview";
import { useFlowStore } from "../flow/store";
import type { DeriveFlowNode } from "../flow/types";
import { NodeShell, NodeStatus } from "./NodeShell";
import { InPorts, OutPorts } from "./PortHandles";

export function DeriveNode({ id, data, selected }: NodeProps<DeriveFlowNode>) {
  const setNodeData = useFlowStore((s) => s.setNodeData);
  const propagate = useFlowStore((s) => s.propagate);
  const runNode = useFlowStore((s) => s.runNode);
  const sendToNode = useFlowStore((s) => s.sendToNode);
  const busy = useFlowStore((s) => !!s.busy[Number(id)]);
  const activeIr = data.variants.length ? data.variants[data.active] || null : null;

  return (
    <NodeShell id={id} type="derive" selected={selected}>
      <InPorts type="derive" />
      <textarea
        className="f-own nodrag nowheel"
        placeholder="например: сделай footer в том же стиле, сохрани плотность и радиусы"
        value={data.prompt}
        onChange={(e) => setNodeData(Number(id), { prompt: e.target.value })}
      />
      <div className="ctl-row">
        <span className="f-provider">OpenRouter</span>
        <select className="f-count nodrag" value={String(data.count)} onChange={(e) => setNodeData(Number(id), { count: Number(e.target.value) })}>
          <option value="1">1</option>
          <option value="2">2</option>
          <option value="3">3</option>
        </select>
        <button className="btn-node primary small f-run nodrag" disabled={busy} onClick={() => runNode(Number(id))}>
          {busy ? <span className="spinner" /> : null} Derive
        </button>
      </div>
      {data.variants.length ? (
        <div className="thumbs">
          {data.variants.map((v, i) => (
            <div
              key={i}
              className={"thumb nodrag" + (i === data.active ? " active" : "")}
              onClick={() => {
                if (busy) return;
                setNodeData(Number(id), { active: i });
                propagate(Number(id));
              }}
            >
              <span className="tbadge">{i + 1}</span>
              <IrPreview ir={v} height={96} empty="" />
            </div>
          ))}
        </div>
      ) : null}
      <IrPreview className="f-preview" ir={activeIr} height={160} empty="варианты появятся после запуска" />
      <div className="gen-actions">
        <button className="btn-node small f-to-editor nodrag" onClick={() => sendToNode(Number(id), "edit")}>
          → Editor
        </button>
      </div>
      <NodeStatus id={id} />
      <OutPorts type="derive" />
    </NodeShell>
  );
}
