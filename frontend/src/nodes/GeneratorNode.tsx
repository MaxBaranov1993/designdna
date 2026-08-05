import type { NodeProps } from "@xyflow/react";
import { useFlowStore } from "../flow/store";
import { toast } from "../flow/toast";
import type { GeneratorFlowNode } from "../flow/types";
import { NodeShell, NodeStatus } from "./NodeShell";
import { InPorts, OutPorts } from "./PortHandles";

/* «Генератор» — run-based нода. B1: контролы и handles по таблице PORTS,
 * LLM-вызов (/api/generate) и миниатюры подключаются в Фазе B2. */
export function GeneratorNode({ id, data, selected }: NodeProps<GeneratorFlowNode>) {
  const setNodeData = useFlowStore((s) => s.setNodeData);
  const runNode = useFlowStore((s) => s.runNode);
  return (
    <NodeShell id={id} type="generator" selected={selected}>
      <InPorts type="generator" />
      <textarea
        className="f-own nodrag nowheel"
        placeholder="Свой промпт (если нет провода)"
        value={data.ownPrompt}
        onChange={(e) => setNodeData(Number(id), { ownPrompt: e.target.value })}
      />
      <div className="ctl-row">
        <select
          className="f-provider nodrag"
          value={data.provider}
          onChange={(e) => setNodeData(Number(id), { provider: e.target.value })}
        >
          <option value="qwen">qwen3.7-max</option>
          <option value="kimi">kimi k3</option>
          <option value="openrouter">openrouter (auto)</option>
        </select>
        <select
          className="f-count nodrag"
          value={String(data.count)}
          onChange={(e) => setNodeData(Number(id), { count: Number(e.target.value) })}
        >
          <option value="1">1</option>
          <option value="2">2</option>
          <option value="3">3</option>
        </select>
        <button className="btn-node primary small f-run nodrag" onClick={() => runNode(Number(id))}>
          ▶
        </button>
      </div>
      <div className="thumbs-note">
        {data.variants.length
          ? `Вариантов: ${data.variants.length}`
          : "Варианты появятся после запуска (Фаза B2)"}
      </div>
      <div className="gen-actions">
        <button
          className="btn-node small f-to-editor nodrag"
          onClick={() => toast("«→ Editor» появится в Фазе B2")}
        >
          → Editor
        </button>
        <button
          className="btn-node small f-to-reference nodrag"
          onClick={() => toast("«→ Reference» появится в Фазе B2")}
        >
          → Reference
        </button>
      </div>
      <NodeStatus id={id} />
      <OutPorts type="generator" />
    </NodeShell>
  );
}
