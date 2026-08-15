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
import { SourceLensBar } from "./SourceLensBar";
import { SmartAxisPanel } from "./SmartAxisPanel";
import { QualityGatePanel } from "./QualityGatePanel";
import { HarmonizerPanel } from "./HarmonizerPanel";

export function EditorApp() {
  const isOpen = useEditorStore((s) => s.isOpen);

  // клавиатура редактора (порт keydown из editor.js) — активна только в открытой сессии
  useEffect(() => {
    const handler = (e: KeyboardEvent) => ctl.onKeydown(e);
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  // фаза 2 открытия — когда overlay уже display:flex и есть раскладка для zoomFit
  useLayoutEffect(() => {
    if (isOpen) ctl.finishOpen();
  }, [isOpen]);

  return (
    <div
      className="dna-editor"
      ref={(el) => { ctl.dom.overlay = el; }}
      style={{ display: isOpen ? "flex" : "none" }}
    >
      <TopBar />
      <SourceLensBar />
      <div className="fe-body">
        <LayersPanel />
        <CanvasStage />
        <InspectorPanel />
      </div>
      <DnaPanel />
      <SmartAxisPanel />
      <QualityGatePanel />
      <HarmonizerPanel />
    </div>
  );
}
