import type { NodeProps } from "@xyflow/react";
import { IrPreview } from "../components/IrPreview";
import { useFlowStore } from "../flow/store";
import type { QualityPassFlowNode } from "../flow/types";
import { NodeShell, NodeStatus } from "./NodeShell";
import { InPorts, OutPorts } from "./PortHandles";
import { FloatingSelect } from "../components/ui/floating-select";

/* Premium Quality Pass: независимый judge выдаёт scorecard, а backend при
 * необходимости выполняет адресный repair и повторно оценивает IR. */
export function QualityPassNode({ id, data, selected }: NodeProps<QualityPassFlowNode>) {
  const setNodeData = useFlowStore((s) => s.setNodeData);
  const runNode = useFlowStore((s) => s.runNode);
  const busy = useFlowStore((s) => !!s.busy[Number(id)]);
  const result = data.result as {
    passed?: boolean;
    scorecard?: { score?: number; verdict?: string; summary?: string; issues?: Array<{ severity?: string; problem?: string }> };
    repair?: { applied?: boolean; error?: string | null };
  } | null;
  const score = result?.scorecard?.score;
  const issues = result?.scorecard?.issues || [];

  return (
    <NodeShell id={id} type="qualitypass" selected={selected}>
      <InPorts type="qualitypass" />
      <textarea className="f-prompt nodrag nowheel" placeholder="Бриф для оценки (необязательно, но повышает точность)"
        value={data.brief} onChange={(e) => setNodeData(Number(id), { brief: e.target.value })} />
      <div className="ctl-row qp-controls">
        <label className="qp-label nodrag">порог
          <FloatingSelect
            className="f-count"
            value={String(data.minScore)}
            options={[75, 85, 95].map((score) => ({ value: String(score), label: String(score) }))}
            onChange={(value) => setNodeData(Number(id), { minScore: Number(value), result: null })}
            ariaLabel="Порог качества"
          />
        </label>
        <label className="qp-label nodrag" title="Исправить замечания судьи и проверить результат повторно">
          <input type="checkbox" checked={data.repair}
            onChange={(e) => setNodeData(Number(id), { repair: e.target.checked, result: null })} /> repair
        </label>
        <button className="btn-node primary small f-run nodrag" style={{ marginLeft: "auto" }} disabled={busy}
          onClick={() => runNode(Number(id))}>{busy ? <span className="spinner" /> : null} ✓ Проверить</button>
      </div>
      {result ? <div className={"qp-score " + (result.passed ? "pass" : "warn")}>
        <strong>{score ?? "?"}/100</strong> · {result.passed ? "готово" : "нужна правка"}{result.repair?.applied ? " · repair применён" : ""}
      </div> : null}
      {result?.scorecard?.summary ? <div className="qp-summary">{result.scorecard.summary}</div> : null}
      {issues.length ? <details className="rs-log f-log"><summary>замечания · {issues.length}</summary><div className="rs-log-lines">
        {issues.slice(0, 6).map((issue, i) => <div key={i}><b>{issue.severity || "minor"}</b>: {issue.problem || "без описания"}</div>)}
      </div></details> : null}
      {result?.repair?.error ? <div className="qp-error">repair: {result.repair.error}</div> : null}
      <IrPreview className="f-preview" ir={data.ir} height={160} empty="Подключите IR и запустите проверку" />
      <NodeStatus id={id} />
      <OutPorts type="qualitypass" />
    </NodeShell>
  );
}
