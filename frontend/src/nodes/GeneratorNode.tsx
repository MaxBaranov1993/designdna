import type { NodeProps } from "@xyflow/react";
import { IrPreview } from "../components/IrPreview";
import { useFlowStore } from "../flow/store";
import type { GeneratorFlowNode } from "../flow/types";
import { NodeShell, NodeStatus } from "./NodeShell";
import { InPorts, OutPorts } from "./PortHandles";

/* «Генератор» — run-based: бриф тянет из входов prompt/style (pull-based,
 * fallback ownPrompt), POST /api/generate (payload — зеркало runGenerator,
 * nodes.js:498-518). Варианты — миниатюрами, активный — в IrPreview и на
 * выход ir (outValue) для нод ниже по графу. */
const PRESETS: { id: string; label: string }[] = [
  { id: "minimal", label: "Minimal" },
  { id: "bento", label: "Bento" },
  { id: "editorial", label: "Editorial" },
  { id: "brutal", label: "Brutal" },
  { id: "glass", label: "Glass" },
];

export function GeneratorNode({ id, data, selected }: NodeProps<GeneratorFlowNode>) {
  const setNodeData = useFlowStore((s) => s.setNodeData);
  const propagate = useFlowStore((s) => s.propagate);
  const runNode = useFlowStore((s) => s.runNode);
  const sendToNode = useFlowStore((s) => s.sendToNode);
  const busy = useFlowStore((s) => !!s.busy[Number(id)]);
  const activeIr = data.variants.length ? data.variants[data.active] || null : null;
  const provider = data.provider === "kimi" ? "kimi" : "codex";
  const count = Math.max(1, Math.min(2, Number(data.count) || 1));
  return (
    <NodeShell id={id} type="generator" selected={selected}>
      <InPorts type="generator" />
      <textarea
        className="f-own nodrag nowheel"
        placeholder="Свой промпт (если нет провода)"
        value={data.ownPrompt}
        onChange={(e) => setNodeData(Number(id), { ownPrompt: e.target.value })}
      />
      <div className="generator-model-row">
        <select
          className="f-provider-select nodrag"
          value={provider}
          onChange={(event) => setNodeData(Number(id), { provider: event.target.value })}
          aria-label="Модель генератора"
        >
          <option value="codex">GPT Codex · ChatGPT</option>
          <option value="kimi">Kimi K2.5 · API key</option>
        </select>
      </div>
      <div className="ctl-row">
        <select
          className="f-count nodrag"
          value={String(count)}
          onChange={(e) => setNodeData(Number(id), { count: Number(e.target.value) })}
        >
          <option value="1">1</option>
          <option value="2">2</option>
        </select>
        <button
          className="btn-node primary small f-run nodrag"
          disabled={busy}
          onClick={() => runNode(Number(id))}
        >
          {busy ? <span className="spinner" /> : <span>▶</span>} Сгенерировать
        </button>
      </div>
      <div className="f-presets nodrag">
        {PRESETS.map((p) => (
          <button
            key={p.id}
            className={"f-preset" + (data.preset === p.id ? " on" : "")}
            title={"Стилевое направление: " + p.label}
            onClick={() => setNodeData(Number(id), { preset: data.preset === p.id ? "" : p.id })}
          >
            {p.label}
          </button>
        ))}
      </div>
      {data.variants.length ? (
        <div className="thumbs">
          {data.variants.map((v, i) => (
            <div
              key={i}
              className={"thumb nodrag" + (i === data.active ? " active" : "")}
              title={"Вариант " + (i + 1)}
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
      <IrPreview
        className="f-preview"
        ir={activeIr}
        height={180}
        empty="Варианты появятся после запуска"
      />
      <div className="gen-actions">
        <button
          className="btn-node small f-to-editor nodrag"
          onClick={() => sendToNode(Number(id), "edit")}
        >
          → Editor
        </button>
        <button
          className="btn-node small f-to-reference nodrag"
          onClick={() => sendToNode(Number(id), "reference")}
        >
          → Reference
        </button>
      </div>
      <NodeStatus id={id} />
      <OutPorts type="generator" />
    </NodeShell>
  );
}
