import type { ChangeEvent } from "react";
import type { NodeProps } from "@xyflow/react";
import { useFlowStore } from "../flow/store";
import type { ReproduceFlowNode } from "../flow/types";
import { NodeShell, NodeStatus } from "./NodeShell";
import { OutPorts } from "./PortHandles";

/* «Reproduce (pixel)» — run-based. B1: контролы и три out-handles (ir/html/diff)
 * по таблице PORTS; вызов /api/reproduce и блок результатов — в Фазе B2. */
export function ReproduceNode({ id, data, selected }: NodeProps<ReproduceFlowNode>) {
  const setNodeData = useFlowStore((s) => s.setNodeData);
  const runNode = useFlowStore((s) => s.runNode);

  const onFile = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    const rd = new FileReader();
    rd.onload = () => setNodeData(Number(id), { image: String(rd.result), fileName: f.name });
    rd.readAsDataURL(f);
    e.target.value = "";
  };

  return (
    <NodeShell id={id} type="reproduce" selected={selected}>
      {data.image ? (
        <img className="ref-img" alt="скриншот" src={data.image} style={{ maxHeight: 120, objectFit: "contain" }} />
      ) : null}
      <label className="ref-drop nodrag">
        {data.image ? (data.fileName || "скриншот") + " (заменить)" : "Кликните: скриншот UI для воспроизведения"}
        <input type="file" accept="image/*" className="f-file" hidden onChange={onFile} />
      </label>
      <input
        type="text"
        className="f-url nodrag"
        placeholder="или URL сайта — повторные запросы из кэша, без токенов"
        value={data.url}
        onChange={(e) => setNodeData(Number(id), { url: e.target.value })}
      />
      <div className="ctl-row">
        <select
          className="f-provider nodrag"
          value={data.provider}
          onChange={(e) => setNodeData(Number(id), { provider: e.target.value })}
        >
          <option value="qwen">qwen (vision)</option>
          <option value="gemini">gemini</option>
          <option value="groq">groq</option>
          <option value="xai">xai grok</option>
          <option value="glm">glm-4v</option>
          <option value="openrouter">openrouter (auto)</option>
        </select>
        <button
          className="btn-node primary small f-run nodrag"
          style={{ marginLeft: "auto" }}
          onClick={() => runNode(Number(id))}
        >
          ◎ Reproduce
        </button>
      </div>
      <NodeStatus id={id} />
      <OutPorts type="reproduce" />
    </NodeShell>
  );
}
