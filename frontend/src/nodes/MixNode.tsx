import { Handle, Position } from "@xyflow/react";
import type { NodeProps } from "@xyflow/react";
import { useFlowStore } from "../flow/store";
import type { MixFlowNode } from "../flow/types";
import { cn } from "../lib/utils";
import { NodeShell, NodeStatus } from "./NodeShell";
import { OutPorts } from "./PortHandles";

/* «Микс» — run-based. Входы динамические из data.inputs (зеркало renderMixInputs,
 * nodes.js:781-813): handle kind "ir" на каждый вход, слайдер веса 0..100,
 * «+ вход» (макс. 4) и «✕» со снятием проводов удалённого входа. */
export function MixNode({ id, data, selected }: NodeProps<MixFlowNode>) {
  const setNodeData = useFlowStore((s) => s.setNodeData);
  const addMixInput = useFlowStore((s) => s.addMixInput);
  const removeMixInput = useFlowStore((s) => s.removeMixInput);
  const runNode = useFlowStore((s) => s.runNode);
  return (
    <NodeShell id={id} type="mix" selected={selected}>
      {data.inputs.map((name) => {
        const weight = data.weights[name] ?? 50;
        return (
          <div key={name} className="mix-row port-row in" data-port={name} data-kind="ir">
            <Handle
              id={name}
              type="target"
              position={Position.Left}
              className={cn("port-dot port-ir", "pp-in-" + name)}
            />
            <span className="cap">{name}</span>
            <input
              type="range"
              min={0}
              max={100}
              value={weight}
              className="nodrag"
              onChange={(e) =>
                setNodeData(Number(id), {
                  weights: { ...data.weights, [name]: Number(e.target.value) },
                })
              }
            />
            <span className="wv">{weight}</span>
            <button className="mx nodrag" title="Убрать вход" onClick={() => removeMixInput(Number(id), name)}>
              ✕
            </button>
          </div>
        );
      })}
      <div className="ctl-row">
        <button className="btn-node small f-add-in nodrag" onClick={() => addMixInput(Number(id))}>
          + вход
        </button>
        <button
          className="btn-node primary small f-run nodrag"
          style={{ marginLeft: "auto" }}
          onClick={() => runNode(Number(id))}
        >
          Смешать по весам
        </button>
      </div>
      <NodeStatus id={id} />
      <OutPorts type="mix" data={data} />
    </NodeShell>
  );
}
