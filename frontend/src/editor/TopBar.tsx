/* Верхний тулбар DNA-редактора: зум, вьюпорты, выравнивание, история, Style DNA,
 * закрыть/сохранить. Разметка 1:1 из legacy editor.js (data-act — контракт тестов).
 * Динамика (zoom-текст, hidden-группы, disabled undo/redo) — императивно через dom-refs
 * контроллера, React эти атрибуты не трогает. */
import * as ctl from "./controller";

export function TopBar() {
  return (
    <div className="fe-toolbar">
      <span className="fe-logo">✦ DNA Editor</span>
      <button className="fe-tbtn" data-act="zoom-out" title="Уменьшить" onClick={() => ctl.handleAct("zoom-out")}>−</button>
      <span className="fe-zoom" ref={(el) => { dom_zoom(el); }}>100%</span>
      <button className="fe-tbtn" data-act="zoom-in" title="Увеличить" onClick={() => ctl.handleAct("zoom-in")}>+</button>
      <button className="fe-tbtn" data-act="zoom-fit" title="Вписать" onClick={() => ctl.handleAct("zoom-fit")}>⊡</button>
      <span className="fe-sep"></span>
      <span className="fe-viewports" hidden ref={(el) => { ctl.dom.viewports = el; }}>
        <button className="fe-tbtn active" data-viewport="desktop" title="Desktop 1440 px" onClick={() => ctl.setViewport("desktop")}>D</button>
        <button className="fe-tbtn" data-viewport="tablet" title="Tablet 768 px" onClick={() => ctl.setViewport("tablet")}>T</button>
        <button className="fe-tbtn" data-viewport="mobile" title="Mobile 390 px" onClick={() => ctl.setViewport("mobile")}>M</button>
        <input
          className="fe-viewport-width" type="number" min={320} max={2560} step={1} defaultValue={1440}
          title="Custom canvas width"
          ref={(el) => { ctl.dom.viewportWidth = el; }}
          onChange={(e) => ctl.setPreviewWidth(e.target.value)}
        />
      </span>
      <span className="fe-sep fe-responsive-sep" hidden ref={(el) => { ctl.dom.responsiveSep = el; }}></span>
      <span className="fe-align-group" hidden ref={(el) => { ctl.dom.alignGroup = el; }}>
        <button className="fe-tbtn" data-act="align-left" title="По левому краю" onClick={() => ctl.handleAct("align-left")}>⫷</button>
        <button className="fe-tbtn" data-act="align-center-h" title="По центру по горизонтали" onClick={() => ctl.handleAct("align-center-h")}>⫿</button>
        <button className="fe-tbtn" data-act="align-right" title="По правому краю" onClick={() => ctl.handleAct("align-right")}>⫸</button>
        <span className="fe-sep"></span>
        <button className="fe-tbtn" data-act="align-top" title="По верхнему краю" onClick={() => ctl.handleAct("align-top")}>⊤</button>
        <button className="fe-tbtn" data-act="align-center-v" title="По центру по вертикали" onClick={() => ctl.handleAct("align-center-v")}>⊶</button>
        <button className="fe-tbtn" data-act="align-bottom" title="По нижнему краю" onClick={() => ctl.handleAct("align-bottom")}>⊥</button>
        <span className="fe-sep"></span>
        <button className="fe-tbtn" data-act="distribute-h" title="Распределить по горизонтали" onClick={() => ctl.handleAct("distribute-h")}>↔</button>
        <button className="fe-tbtn" data-act="distribute-v" title="Распределить по вертикали" onClick={() => ctl.handleAct("distribute-v")}>↕</button>
        <span className="fe-sep"></span>
      </span>
      <button className="fe-tbtn" data-act="forward" title="Выше (])" onClick={() => ctl.handleAct("forward")}>⇈</button>
      <button className="fe-tbtn" data-act="backward" title="Ниже ([)" onClick={() => ctl.handleAct("backward")}>⇊</button>
      <button className="fe-tbtn" data-act="group" title="Группа (Ctrl+G)" onClick={() => ctl.handleAct("group")}>⧉</button>
      <button className="fe-tbtn" data-act="ungroup" title="Разгруппировать (Ctrl+Shift+G)" onClick={() => ctl.handleAct("ungroup")}>⧠</button>
      <button className="fe-tbtn" data-act="undo" title="Отменить (Ctrl+Z)" ref={(el) => { ctl.dom.undoBtn = el; }} onClick={() => ctl.handleAct("undo")}>↩</button>
      <button className="fe-tbtn" data-act="redo" title="Повторить (Ctrl+Shift+Z)" ref={(el) => { ctl.dom.redoBtn = el; }} onClick={() => ctl.handleAct("redo")}>↪</button>
      <button className="fe-tbtn" data-act="style-dna" title="Style DNA" onClick={() => ctl.handleAct("style-dna")}>🧬</button>
      <button className="fe-btn fe-smart-axis-trigger" data-act="smart-axis" title="AI найдёт общую ось контента и покажет безопасный патч" onClick={() => ctl.handleAct("smart-axis")}>✦ Выровнять ширину</button>
      <span className="fe-spacer"></span>
      <button className="fe-btn danger" data-act="close" onClick={() => ctl.handleAct("close")}>Закрыть</button>
      <button className="fe-btn primary" data-act="save" onClick={() => ctl.handleAct("save")}>💾 Сохранить</button>
    </div>
  );
}

function dom_zoom(el: HTMLSpanElement | null) {
  ctl.dom.zoomLabel = el;
}
