import type { NodeProps } from "@xyflow/react";
import { IrPreview } from "../components/IrPreview";
import { useFlowStore } from "../flow/store";
import type { ReskinFlowNode, ReskinMask } from "../flow/types";
import { NodeShell, NodeStatus } from "./NodeShell";
import { InPorts, OutPorts } from "./PortHandles";

/* Подписи чекбоксов маски — что модели разрешено менять (остальное merge-back
 * принудительно вернёт из входного IR, server.py _MASK_LABELS) */
const MASK_FIELDS: { key: keyof ReskinMask; label: string }[] = [
  { key: "colors", label: "цвета" },
  { key: "fonts", label: "шрифты" },
  { key: "radii", label: "радиусы" },
  { key: "shadows", label: "тени" },
  { key: "texts", label: "тексты" },
  { key: "images", label: "изображения" },
];

/* «Reskin» — controlled AI-нода (см. docs/NODES.md): вход ir
 * (обязателен) и tokens (опционально) приходят проводами (pull-модель),
 * POST /api/reskin {ir, prompt, tokens?, mask}. Пустая маска запуск блокирует.
 * Результат: превью IR + свёрнутый журнал merge-back со счётчиком записей. */
export function ReskinNode({ id, data, selected }: NodeProps<ReskinFlowNode>) {
  const setNodeData = useFlowStore((s) => s.setNodeData);
  const runNode = useFlowStore((s) => s.runNode);
  const busy = useFlowStore((s) => !!s.busy[Number(id)]);
  const maskAny = MASK_FIELDS.some((f) => data.mask[f.key]);
  return (
    <NodeShell id={id} type="reskin" selected={selected}>
      <InPorts type="reskin" />
      <textarea
        className="f-prompt nodrag nowheel"
        placeholder="Пожелания по новому стилю"
        value={data.prompt}
        onChange={(e) => setNodeData(Number(id), { prompt: e.target.value })}
      />
      <div className="rs-mask">
        {MASK_FIELDS.map((f) => (
          <label key={f.key} className="nodrag" title={"Разрешить менять: " + f.label}>
            <input
              type="checkbox"
              className={"f-mask-" + f.key}
              checked={data.mask[f.key]}
              onChange={(e) =>
                setNodeData(Number(id), { mask: { ...data.mask, [f.key]: e.target.checked } })
              }
            />
            {f.label}
          </label>
        ))}
      </div>
      <div className="ctl-row">
        <button
          className="btn-node primary small f-run nodrag"
          style={{ marginLeft: "auto" }}
          disabled={busy || !maskAny}
          title={!maskAny ? "Пустая маска: отметьте, что разрешено менять" : undefined}
          onClick={() => runNode(Number(id))}
        >
          {busy ? <span className="spinner" /> : null} ✦ Reskin
        </button>
      </div>
      {!maskAny ? (
        <div className="rs-hint">Пустая маска: запуск заблокирован (IR вернулся бы без изменений)</div>
      ) : null}
      <IrPreview
        className="f-preview"
        ir={data.ir}
        height={160}
        empty="Результат появится после запуска"
      />
      {data.log.length ? (
        <details className="rs-log f-log">
          <summary>журнал merge-back · {data.log.length}</summary>
          <div className="rs-log-lines">
            {data.log.slice(-8).map((line, i) => (
              <div key={i}>{line}</div>
            ))}
          </div>
        </details>
      ) : null}
      <NodeStatus id={id} />
      <OutPorts type="reskin" />
    </NodeShell>
  );
}
