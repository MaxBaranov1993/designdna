import type { NodeProps } from "@xyflow/react";
import { IrPreview } from "../components/IrPreview";
import { useFlowStore } from "../flow/store";
import type { CloneFlowNode } from "../flow/types";
import { NodeShell, NodeStatus } from "./NodeShell";
import { OutPorts } from "./PortHandles";

/* «Клон (сайт)» — run-based: url + компонент -> POST /api/clone
 * (payload — зеркало runClone, nodes.js:838-857), результат ir в превью
 * и на выход для нод ниже по графу. */
export function CloneNode({ id, data, selected }: NodeProps<CloneFlowNode>) {
  const setNodeData = useFlowStore((s) => s.setNodeData);
  const runNode = useFlowStore((s) => s.runNode);
  const busy = useFlowStore((s) => !!s.busy[Number(id)]);
  return (
    <NodeShell id={id} type="clone" selected={selected}>
      <input
        type="text"
        className="f-url nodrag"
        placeholder="https://example.com/page"
        value={data.url}
        onChange={(e) => setNodeData(Number(id), { url: e.target.value })}
      />
      <textarea
        className="f-component nodrag nowheel"
        placeholder="Какой компонент клонировать? Например: шапка с навигацией, карточка товара, боковая панель…"
        value={data.component}
        onChange={(e) => setNodeData(Number(id), { component: e.target.value })}
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
        <button
          className="btn-node primary small f-run nodrag"
          style={{ marginLeft: "auto" }}
          disabled={busy}
          onClick={() => runNode(Number(id))}
        >
          {busy ? <span className="spinner" /> : null} ⧉ Клонировать
        </button>
      </div>
      <IrPreview
        className="f-preview"
        ir={data.ir}
        height={160}
        empty="Укажите URL и компонент — клон появится здесь"
      />
      <NodeStatus id={id} />
      <OutPorts type="clone" />
    </NodeShell>
  );
}
