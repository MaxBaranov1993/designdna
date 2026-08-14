import { useState } from "react";
import * as ctl from "./controller";
import { useEditorStore } from "./store";

export function TopBar() {
  const dirty = useEditorStore((s) => s.dirty);
  const previewing = useEditorStore((s) => s.previewing);
  const [customOpen, setCustomOpen] = useState(false);
  const [customWidth, setCustomWidth] = useState("1440");
  return (
    <div className="fe-toolbar">
      <div className="fe-toolbar-brand">
        <span className="fe-logo">✦ Редактор</span>
        <span className={`fe-save-state${dirty ? " dirty" : ""}`} data-editor-status>
          {dirty ? "Есть изменения" : "Сохранено"}
        </span>
      </div>

      <div className="fe-toolbar-cluster fe-zoom-controls" aria-label="Масштаб">
        <button className="fe-tbtn" data-act="zoom-out" title="Уменьшить" onClick={() => ctl.handleAct("zoom-out")}>−</button>
        <span className="fe-zoom" ref={(el) => { ctl.dom.zoomLabel = el; }}>100%</span>
        <button className="fe-tbtn" data-act="zoom-in" title="Увеличить" onClick={() => ctl.handleAct("zoom-in")}>+</button>
        <button className="fe-tbtn fe-tbtn-label" data-act="zoom-fit" title="По размеру" onClick={() => ctl.handleAct("zoom-fit")}>Вписать</button>
      </div>

      <span className="fe-sep"></span>

      <div className="fe-viewports" hidden ref={(el) => { ctl.dom.viewports = el; }} aria-label="Viewport">
        <button className="fe-tbtn active" data-viewport="desktop" title="Desktop 1440 px" onClick={() => ctl.setViewport("desktop")}>Desktop</button>
        <button className="fe-tbtn" data-viewport="tablet" title="Tablet 768 px" onClick={() => ctl.setViewport("tablet")}>Tablet</button>
        <button className="fe-tbtn" data-viewport="mobile" title="Mobile 390 px" onClick={() => ctl.setViewport("mobile")}>Mobile</button>
        <div className="fe-viewport-custom-wrap">
          <button
            className="fe-tbtn fe-custom-trigger"
            data-act="custom-width"
            aria-expanded={customOpen}
            title="Задать ширину viewport"
            onClick={() => setCustomOpen((open) => {
              if (!open) setCustomWidth(String(ctl.getSession()?.previewWidth || 1440));
              return !open;
            })}
          >
            Своя
          </button>
          {customOpen && (
            <label className="fe-viewport-custom">
              <span>Ширина</span>
              <input
                className="fe-viewport-width"
                type="number"
                min={320}
                max={2560}
                step={1}
                value={customWidth}
                title="Custom canvas width"
                ref={(el) => { ctl.dom.viewportWidth = el; }}
                onChange={(e) => {
                  setCustomWidth(e.target.value);
                  ctl.setPreviewWidth(e.target.value);
                }}
              />
            </label>
          )}
        </div>
      </div>

      <span className="fe-sep fe-responsive-sep" hidden ref={(el) => { ctl.dom.responsiveSep = el; }}></span>

      <div className="fe-context-actions" hidden ref={(el) => { ctl.dom.alignGroup = el; }} aria-label="Действия выделения">
        <span className="fe-context-label">Выделение</span>
        <button className="fe-tbtn" data-act="align-left" title="По левому краю" onClick={() => ctl.handleAct("align-left")}>⇤</button>
        <button className="fe-tbtn" data-act="align-center-h" title="По центру по горизонтали" onClick={() => ctl.handleAct("align-center-h")}>↔</button>
        <button className="fe-tbtn" data-act="align-right" title="По правому краю" onClick={() => ctl.handleAct("align-right")}>⇥</button>
        <button className="fe-tbtn" data-act="align-top" title="По верхнему краю" onClick={() => ctl.handleAct("align-top")}>⇡</button>
        <button className="fe-tbtn" data-act="align-center-v" title="По центру по вертикали" onClick={() => ctl.handleAct("align-center-v")}>↕</button>
        <button className="fe-tbtn" data-act="align-bottom" title="По нижнему краю" onClick={() => ctl.handleAct("align-bottom")}>⇣</button>
        <button className="fe-tbtn" data-act="distribute-h" title="Распределить по горизонтали" onClick={() => ctl.handleAct("distribute-h")}>⇆</button>
        <button className="fe-tbtn" data-act="distribute-v" title="Распределить по вертикали" onClick={() => ctl.handleAct("distribute-v")}>⇅</button>
        <button className="fe-tbtn" data-act="stretch-width" title="Растянуть по ширине" onClick={() => ctl.handleAct("stretch-width")}>↔▣</button>
        <button className="fe-tbtn" data-act="forward" title="Выше (])" onClick={() => ctl.handleAct("forward")}>⇈</button>
        <button className="fe-tbtn" data-act="backward" title="Ниже ([)" onClick={() => ctl.handleAct("backward")}>⇊</button>
        <button className="fe-tbtn" data-act="group" title="Группа (Ctrl+G)" onClick={() => ctl.handleAct("group")}>⧉</button>
        <button className="fe-tbtn" data-act="ungroup" title="Разгруппировать (Ctrl+Shift+G)" onClick={() => ctl.handleAct("ungroup")}>⧠</button>
      </div>

      <div className="fe-toolbar-cluster fe-history-controls">
        <button className="fe-tbtn" data-act="undo" title="Отменить (Ctrl+Z)" ref={(el) => { ctl.dom.undoBtn = el; }} onClick={() => ctl.handleAct("undo")}>↶</button>
        <button className="fe-tbtn" data-act="redo" title="Повторить (Ctrl+Shift+Z)" ref={(el) => { ctl.dom.redoBtn = el; }} onClick={() => ctl.handleAct("redo")}>↷</button>
      </div>

      <span className="fe-spacer"></span>

      <div className="fe-toolbar-cluster fe-primary-actions">
        <button className="fe-btn" data-act="ai" onClick={() => ctl.handleAct("ai")}>AI</button>
        <button className={`fe-btn${previewing ? " active" : ""}`} data-act="preview" onClick={() => ctl.handleAct("preview")}>
          {previewing ? "Вернуться к правкам" : "Как в браузере"}
        </button>
        <button className="fe-btn fe-secondary-action" data-act="style-dna" title="Стиль сайта" onClick={() => ctl.handleAct("style-dna")}>Стиль сайта</button>
        <button className="fe-btn danger" data-act="close" onClick={() => ctl.handleAct("close")}>Закрыть</button>
        <button className="fe-btn primary" data-act="save" onClick={() => ctl.handleAct("save")}>Сохранить</button>
      </div>
    </div>
  );
}
