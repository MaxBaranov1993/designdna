import type { ChangeEvent } from "react";
import type { NodeProps } from "@xyflow/react";
import { IrPreview } from "../components/IrPreview";
import { useFlowStore } from "../flow/store";
import type { SourceImportFlowNode } from "../flow/types";
import type { SourceViewport } from "../flow/types";
import { NodeShell, NodeStatus } from "./NodeShell";
import { OutPorts } from "./PortHandles";

export function SourceImportNode({ id, data, selected }: NodeProps<SourceImportFlowNode>) {
  const setNodeData = useFlowStore((s) => s.setNodeData);
  const deleteEdge = useFlowStore((s) => s.deleteEdge);
  const runNode = useFlowStore((s) => s.runNode);
  const busy = useFlowStore((s) => !!s.busy[Number(id)]);
  const propagate = useFlowStore((s) => s.propagate);
  const previewMode = data.previewMode || "reference";

  const setViewport = (viewport: SourceViewport) => {
    setNodeData(Number(id), { activeViewport: viewport });
    queueMicrotask(() => propagate(Number(id)));
  };

  const onFile = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    const rd = new FileReader();
    rd.onload = () => setNodeData(Number(id), { image: String(rd.result), fileName: f.name, mode: "screenshot" });
    rd.readAsDataURL(f);
    e.target.value = "";
  };

  const toggleLit = (name: string, lit: boolean) => {
    setNodeData(Number(id), {
      blocks: data.blocks.map((b) => (b.name === name ? { ...b, lit } : b)),
    });
    if (!lit) {
      useFlowStore
        .getState()
        .edges.filter((e) => e.source === id && e.sourceHandle === name)
        .forEach((e) => deleteEdge(e.id));
      useFlowStore.getState().propagate(Number(id));
    }
  };

  return (
    <NodeShell id={id} type="sourceimport" selected={selected}>
      <div className="seg-row nodrag">
        <button
          className={"seg-btn" + (data.mode === "url" ? " active" : "")}
          onClick={() => setNodeData(Number(id), { mode: "url" })}
        >
          URL
        </button>
        <button
          className={"seg-btn" + (data.mode === "screenshot" ? " active" : "")}
          onClick={() => setNodeData(Number(id), { mode: "screenshot" })}
        >
          screenshot
        </button>
      </div>
      {data.mode === "url" ? (
        <>
          <input
            type="text"
            className="f-url nodrag"
            placeholder="https://site.com/page"
            value={data.url}
            onChange={(e) => setNodeData(Number(id), { url: e.target.value })}
            onBlur={(e) => {
              const value = e.target.value.trim();
              if (value && !/^[a-z][a-z\d+.-]*:\/\//i.test(value)) {
                setNodeData(Number(id), { url: value.startsWith("//") ? `https:${value}` : `https://${value}` });
              }
            }}
          />
          <label className="bp-mine nodrag" title="Импортируйте только свои страницы или страницы, на которые есть право">
            <input
              type="checkbox"
              className="f-mine"
              checked={data.mine}
              onChange={(e) => setNodeData(Number(id), { mine: e.target.checked })}
            />
            это мой сайт / есть право
          </label>
          <div className="source-viewports nodrag" aria-label="Source viewport">
            {(["desktop", "tablet", "mobile"] as SourceViewport[]).map((viewport) => (
              <button
                key={viewport}
                className={"source-viewport" + (data.activeViewport === viewport ? " active" : "")}
                onClick={() => setViewport(viewport)}
                title={viewport === "desktop" ? "1440 px" : viewport === "tablet" ? "768 px" : "390 px"}
              >
                {viewport === "desktop" ? "Desktop" : viewport === "tablet" ? "Tablet" : "Mobile"}
              </button>
            ))}
          </div>
        </>
      ) : (
        <>
          {data.image ? (
            <img className="ref-img" alt="screenshot" src={data.image} style={{ maxHeight: 120, objectFit: "contain" }} />
          ) : null}
          <label className="ref-drop nodrag">
            {data.image ? (data.fileName || "screenshot") + " (заменить)" : "загрузить скриншот элемента"}
            <input type="file" accept="image/*" hidden onChange={onFile} />
          </label>
        </>
      )}
      {data.mode === "url" && !data.mine ? <div className="bp-hint">Запуск доступен после отметки «это мой сайт / есть право»</div> : null}
      <div className="ctl-row">
        <button
          className="btn-node primary small f-run nodrag"
          style={{ marginLeft: "auto" }}
          disabled={busy || (data.mode === "url" && !data.mine)}
          onClick={() => runNode(Number(id))}
        >
          {busy ? <span className="spinner" /> : null} Import
        </button>
      </div>
      {data.blocks.length ? (
        <div className="bp-blocks">
          {data.blocks.map((b) => (
            <div key={b.name} className="bp-block" data-block={b.name}>
              <label className="bp-lit">
                <input
                  type="checkbox"
                  className="f-lit nodrag"
                  disabled={!!b.error}
                  checked={b.lit}
                  onChange={(e) => toggleLit(b.name, e.target.checked)}
                />
                <span className="bp-name">{b.label || b.name}</span>
                {b.kind ? <span className="bp-kind">{b.kind}</span> : null}
                {b.cached ? <span className="bp-cached">из кэша</span> : null}
                {b.source ? <span className="bp-cached">{b.source}{b.layers ? ` · ${b.layers} layers` : ""}</span> : null}
                {b.repeat?.count && b.repeat.count > 1 ? (
                  <span className="bp-repeat">{b.repeat.count}× {b.repeat.kind || "item"} → 1 block</span>
                ) : null}
              </label>
              {b.error ? (
                <div className="bp-error">{b.error}</div>
              ) : (
                <>
                  <div className="source-preview-mode nodrag" aria-label="Source preview mode">
                    {(["reference", "ir", "compare"] as const).map((mode) => (
                      <button
                        key={mode}
                        className={previewMode === mode ? "active" : ""}
                        onClick={() => setNodeData(Number(id), { previewMode: mode })}
                      >
                        {mode === "reference" ? "Reference" : mode === "ir" ? "IR" : "Compare"}
                      </button>
                    ))}
                  </div>
                  {previewMode === "reference" ? (
                    <SourceReferencePreview src={b.previews?.[data.activeViewport] || b.preview} />
                  ) : previewMode === "compare" ? (
                    <div className="source-compare">
                      <SourceReferencePreview src={b.previews?.[data.activeViewport] || b.preview} />
                      <IrPreview
                        className="bp-preview"
                        ir={b.ir || null}
                        height={72}
                        viewport={data.activeViewport}
                        empty=""
                      />
                    </div>
                  ) : (
                    <IrPreview
                      className="bp-preview"
                      ir={b.ir || null}
                      height={72}
                      viewport={data.activeViewport}
                      empty=""
                    />
                  )}
                </>
              )}
              {!b.error ? (
                <div className="source-health">
                  <span>{b.layersByViewport?.[data.activeViewport] ?? b.layers ?? 0} layers</span>
                  <span>{Math.round(b.coverage?.[data.activeViewport] ?? b.fidelity?.[data.activeViewport] ?? 0)}% coverage</span>
                  {b.warnings?.length ? <span className="source-warning">{b.warnings.length} warning</span> : null}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
      <NodeStatus id={id} />
      <OutPorts type="sourceimport" data={data} />
    </NodeShell>
  );
}

function SourceReferencePreview({ src }: { src?: string }) {
  if (!src) return <div className="bp-preview source-reference-empty" />;
  return (
    <div className="bp-preview source-reference-preview">
      <img alt="Source reference" src={src} />
    </div>
  );
}
