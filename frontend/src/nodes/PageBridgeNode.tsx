import type { NodeProps } from "@xyflow/react";
import { useFlowStore } from "../flow/store";
import type { PageBridgeFlowNode } from "../flow/types";
import { NodeShell, NodeStatus } from "./NodeShell";
import { InPorts, OutPorts } from "./PortHandles";

export function PageBridgeNode({ id, data, selected }: NodeProps<PageBridgeFlowNode>) {
  const setNodeData = useFlowStore((s) => s.setNodeData);
  const runNode = useFlowStore((s) => s.runNode);
  const hasComponent = Boolean(data.ir);

  return (
    <NodeShell id={id} type="pagebridge" selected={selected}>
      <InPorts type="pagebridge" data={data} />
      <div className="bridge-mode nodrag">
        <button
          className={data.mode === "send" ? "active" : ""}
          onClick={() => setNodeData(Number(id), { mode: "send" })}
        >
          Send
        </button>
        <button
          className={data.mode === "receive" ? "active" : ""}
          onClick={() => setNodeData(Number(id), { mode: "receive" })}
        >
          Receive
        </button>
      </div>
      <label className="field">
        <span>Channel</span>
        <input
          className="nodrag"
          value={data.channel}
          onChange={(e) => setNodeData(Number(id), { channel: e.target.value })}
          onBlur={() => runNode(Number(id))}
          placeholder="shared-component"
        />
      </label>
      <button className="btn-node primary small f-run nodrag" onClick={() => runNode(Number(id))}>
        {data.mode === "send" ? "Передать" : "Получить"}
      </button>
      <div className="bridge-chip">{hasComponent ? "component ready" : "empty channel"}</div>
      <NodeStatus id={id} />
      <OutPorts type="pagebridge" data={data} />
    </NodeShell>
  );
}
