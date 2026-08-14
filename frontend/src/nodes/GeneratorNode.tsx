import type { NodeProps } from "@xyflow/react";
import { IrPreview } from "../components/IrPreview";
import { useFlowStore } from "../flow/store";
import type { GeneratorFlowNode } from "../flow/types";
import { NodeShell, NodeStatus } from "./NodeShell";
import { InPorts, OutPorts } from "./PortHandles";
import { FloatingSelect } from "../components/ui/floating-select";

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
  const quality = (data.qa || [])[data.active];
  const rejected = data.rejected || [];
  const tasteWeight = typeof data.tasteWeight === "number" ? data.tasteWeight : 0.35;
  return (
    <NodeShell id={id} type="generator" selected={selected}>
      <InPorts type="generator" />
      <textarea
        className="f-own nodrag nowheel"
        aria-label="Промпт генерации"
        placeholder="Свой промпт (если нет провода)"
        value={data.ownPrompt}
        onChange={(e) => setNodeData(Number(id), { ownPrompt: e.target.value })}
      />
      <div className="generator-model-row">
        <span className="f-provider" title="Модель и endpoint задаются через CODEX_BASE_URL / CODEX_MODEL">
          GPT Codex
        </span>
      </div>
      <div className="ctl-row">
        <FloatingSelect
          className="f-count nodrag"
          value={String(data.count)}
          options={[1, 2, 3, 4, 5].map((count) => ({ value: String(count), label: String(count) }))}
          onChange={(value) => setNodeData(Number(id), { count: Number(value) })}
          ariaLabel="Количество вариантов"
        />
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
      <div className="generator-taste nodrag">
        <label className="generator-taste-toggle">
          <input
            type="checkbox"
            checked={data.tasteEnabled !== false}
            onChange={(event) => setNodeData(Number(id), { tasteEnabled: event.target.checked })}
          />
          <span>Учитывать Taste Memory</span>
        </label>
        {data.tasteEnabled !== false ? (
          <div className="generator-taste-row">
            <FloatingSelect
              value={String(tasteWeight)}
              options={[
                { value: "0.15", label: "Влияние 15%" },
                { value: "0.35", label: "Влияние 35%" },
                { value: "0.65", label: "Влияние 65%" },
              ]}
              onChange={(value) => setNodeData(Number(id), { tasteWeight: Number(value) })}
              ariaLabel="Сила Taste Memory"
            />
            <FloatingSelect
              value={data.tasteScope || "project"}
              options={[
                { value: "project", label: "Весь проект" },
                { value: "recent", label: "Последние запросы" },
              ]}
              onChange={(value) => setNodeData(Number(id), { tasteScope: value })}
              ariaLabel="Область Taste Memory"
            />
          </div>
        ) : null}
      </div>
      {data.variants.length ? (
        <div className="thumbs">
          {data.variants.map((v, i) => (
            <div
              key={i}
              className={"thumb nodrag" + (i === data.active ? " active" : "")}
              title={"Вариант " + (i + 1)}
              role="button"
              tabIndex={0}
              aria-label={`Выбрать вариант ${i + 1}${(data.qa || [])[i]?.score ? `, quality ${(data.qa || [])[i]?.score} из 100` : ""}`}
              onClick={() => {
                if (busy) return;
                setNodeData(Number(id), { active: i });
                propagate(Number(id));
              }}
              onKeyDown={(event) => {
                if (busy || (event.key !== "Enter" && event.key !== " ")) return;
                event.preventDefault();
                setNodeData(Number(id), { active: i });
                propagate(Number(id));
              }}
            >
              <span className="tbadge">{(data.qa || [])[i]?.score ?? i + 1}</span>
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
      {(quality || rejected.length || data.design?.skills?.length) ? (
        <section className="generator-quality nodrag" aria-live="polite" aria-label="Результат проверки качества">
          <div className="generator-quality-head">
            <strong>{quality ? `Quality ${quality.score}/100` : "Quality rejected"}</strong>
            {quality ? <span className={`generator-quality-verdict ${quality.verdict}`}>{quality.verdict === "pass" ? "Принято" : "Отклонено"}</span> : null}
          </div>
          {quality?.summary ? <p>{quality.summary}</p> : null}
          {quality?.issues?.length ? <ul>{quality.issues.slice(0, 3).map((issue, issueIndex) => <li key={issueIndex}>{issue.problem}</li>)}</ul> : null}
          {rejected.length ? <details><summary>Отклонено вариантов: {rejected.length}</summary><ul>{rejected.map((item) => <li key={item.index}>№{item.index}: {item.error || item.reason}</li>)}</ul></details> : null}
          {data.design?.skills?.length ? <div className="generator-skills">Skills: {data.design.skills.join(" · ")}</div> : null}
        </section>
      ) : null}
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
