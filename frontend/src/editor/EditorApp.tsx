/* Корень React DNA-редактора. Overlay смонтирован всегда (display flex/none —
 * жёсткий контракт тестов: style.display === 'flex' когда редактор открыт).
 * React отвечает только за каркас; сессия и движки — в controller.ts. */
import { useEffect, useLayoutEffect } from "react";
import "./editor.css";
import * as ctl from "./controller";
import { useEditorStore } from "./store";
import { TopBar } from "./TopBar";
import { LayersPanel } from "./LayersPanel";
import { CanvasStage } from "./CanvasStage";
import { InspectorPanel } from "./InspectorPanel";
import { DnaPanel } from "./DnaPanel";
import { AiAssistPanel } from "./AiAssistPanel";

export function EditorApp() {
  const isOpen = useEditorStore((s) => s.isOpen);
  const previewing = useEditorStore((s) => s.previewing);
  const closeConfirm = useEditorStore((s) => s.closeConfirm);

  // клавиатура редактора (порт keydown из editor.js) — активна только в открытой сессии
  useEffect(() => {
    const handler = (e: KeyboardEvent) => ctl.onKeydown(e);
    const keyup = (e: KeyboardEvent) => ctl.onKeyup(e);
    document.addEventListener("keydown", handler);
    document.addEventListener("keyup", keyup);
    return () => {
      document.removeEventListener("keydown", handler);
      document.removeEventListener("keyup", keyup);
    };
  }, []);

  // фаза 2 открытия — когда overlay уже display:flex и есть раскладка для zoomFit
  useLayoutEffect(() => {
    if (isOpen) ctl.finishOpen();
  }, [isOpen]);

  return (
    <div
      className={`dna-editor${previewing ? " previewing" : ""}`}
      ref={(el) => { ctl.dom.overlay = el; }}
      style={{ display: isOpen ? "flex" : "none" }}
    >
      <TopBar />
      <div className="fe-body">
        <LayersPanel />
        <CanvasStage />
        <InspectorPanel />
      </div>
      <DnaPanel />
      <AiAssistPanel />
      {closeConfirm ? (
        <div className="fe-close-modal" role="dialog" aria-modal="true" aria-labelledby="fe-close-title">
          <div className="fe-close-card">
            <p id="fe-close-title">Выйти без сохранения изменений?</p>
            <div className="fe-close-actions">
              <button className="fe-btn" data-act="stay" type="button" onClick={ctl.cancelCloseConfirm}>Остаться</button>
              <button className="fe-btn danger" data-act="discard-close" type="button" onClick={ctl.confirmDiscard}>Выйти</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
