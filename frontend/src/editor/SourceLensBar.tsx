import type { CSSProperties } from "react";
import * as ctl from "./controller";
import { useEditorStore } from "./store";

export function SourceLensBar() {
  useEditorStore((state) => state.sourceTick);
  const view = ctl.getSourceLensView();
  if (!view.sources.length) return null;
  return (
    <div className="fe-source-lens" aria-label="Source Lens">
      <button
        className={"fe-source-lens-toggle" + (view.enabled ? " active" : "")}
        onClick={() => ctl.toggleSourceLens()}
        title="Цветом показать происхождение компонентов"
      >
        ◉ Source Lens
      </button>
      <div className="fe-source-lens-list">
        {view.sources.map((source) => (
          <button
            key={source.id}
            className={"fe-source-filter" + (source.active ? " active" : " muted")}
            style={{ "--source-color": source.color } as CSSProperties}
            onClick={() => ctl.toggleSourceFilter(source.id)}
            title={`${source.label} · ${Math.round((source.confidence ?? 1) * 100)}% confidence · ${source.count} layers`}
          >
            <span className="fe-source-filter-symbol">{source.symbol || "S"}</span>
            <span>{source.label}</span>
            <small>{source.count}</small>
          </button>
        ))}
      </div>
      <span className="fe-source-lens-help">Выберите слой — его источник появится в инспекторе</span>
    </div>
  );
}
