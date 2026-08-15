/* Правая панель инспектора — чистый React (фаза A2, без window.Inspector/innerHTML).
 * Контроллер хранит сессию (sel/ir/viewport/geo) и бампит store.inspectorTick;
 * панель перечитывает сессию и перемонтирует дерево по key={tick} — как legacy
 * перестраивал innerHTML. События — нативные, навешивает wireInspector после
 * монтирования (инпуты неконтролируемые: коммит по change, как в editor.js). */
import { useEffect, useRef } from "react";
import type { CSSProperties } from "react";
import * as ctl from "./controller";
import { useEditorStore } from "./store";
import { SharedInspector } from "./inspector/SharedInspector";
import { TypeGroups } from "./inspector/TypeGroups";
import { wireInspector } from "./inspector/wireInspector";

export function InspectorPanel() {
  const tick = useEditorStore((s) => s.inspectorTick);
  const contentRef = useRef<HTMLDivElement>(null);
  const wiredRef = useRef<HTMLDivElement | null>(null);

  const sess = ctl.getSession();
  const selCount = sess ? sess.sel.length : 0;
  const source = selCount ? ctl.sourceForSelection() : null;

  // проводка событий — один раз на свежесмонтированное дерево (key={tick})
  useEffect(() => {
    const content = contentRef.current;
    if (!content || wiredRef.current === content) return;
    wiredRef.current = content;
    wireInspector(content);
  });

  return (
    <div className="fe-inspector">
      {selCount ? (
        <div key={tick} ref={contentRef}>
          {source ? (
            <div className="fe-source-origin" style={{ "--source-color": source.color } as CSSProperties}>
              <span className="fe-source-origin-symbol">{source.symbol || "S"}</span>
              <span><b>{source.label}</b><small>{source.kind || "source"} · {Math.round((source.confidence ?? 1) * 100)}%</small></span>
              <span className="fe-source-origin-state">linked</span>
            </div>
          ) : null}
          <div className="fe-shared-insp">
            <SharedInspector />
          </div>
          {selCount === 1 ? <TypeGroups /> : null}
        </div>
      ) : (
        <div className="fe-insp-empty">Выделите элемент на канвасе или в слоях</div>
      )}
    </div>
  );
}
