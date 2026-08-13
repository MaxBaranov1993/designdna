/* Slide-over панель Style DNA. Каркас — React (id/классы — контракт тестов
 * ui_style_dna_test.py / ui_style_projection_test.py), тело #feDnaBody заполняет
 * контроллер (токены, normalize preview, Tailwind projection). */
import * as ctl from "./controller";

export function DnaPanel() {
  return (
    <div className="fe-dna-panel" id="feDnaPanel" ref={(el) => { ctl.dom.dnaPanel = el; }}>
      <div className="fe-dna-head">
        <h3>🧬 Style DNA</h3>
        <span className="fe-dna-tag" id="feDnaMode" ref={(el) => { ctl.dom.dnaMode = el; }}>light</span>
        <button className="fe-tbtn" data-act="close-style-dna" title="Закрыть" onClick={() => ctl.handleAct("close-style-dna")}>✕</button>
      </div>
      <div className="fe-dna-body" id="feDnaBody" ref={(el) => { ctl.dom.dnaBody = el; }}>
        <div className="fe-dna-empty">Загрузка токенов…</div>
      </div>
      <div className="fe-dna-foot" id="feDnaFoot" ref={(el) => { ctl.dom.dnaFoot = el; }}></div>
      <div className="fe-dna-actions">
        <button className="fe-btn" data-act="reset-style-dna" onClick={() => ctl.handleAct("reset-style-dna")}>Сбросить</button>
        <button className="fe-btn primary" data-act="apply-style-dna" onClick={() => ctl.handleAct("apply-style-dna")}>Применить</button>
      </div>
    </div>
  );
}
