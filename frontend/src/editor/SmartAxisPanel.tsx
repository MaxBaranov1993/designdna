import * as ctl from "./controller";
import { useEditorStore } from "./store";

export function SmartAxisPanel() {
  const proposal = useEditorStore((state) => state.smartAxisProposal);
  if (!proposal) return null;
  return (
    <div className="fe-smart-axis-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) ctl.dismissSmartAxisProposal();
    }}>
      <section className="fe-smart-axis-card" role="dialog" aria-modal="true" aria-labelledby="smart-axis-title">
        <div className="fe-smart-axis-kicker">AI Layout Director · безопасный патч</div>
        <h2 id="smart-axis-title">Единая ширина контента: {proposal.targetWidth}px</h2>
        <p>Ось взята из «{proposal.referenceLabel}». Фоны останутся на всю ширину, изменится только внутренняя сетка.</p>
        <div className="fe-smart-axis-preview" aria-label="Предпросмотр оси">
          <span className="fe-smart-axis-page"><i style={{ width: `${Math.min(88, Math.max(42, proposal.targetWidth / 16))}%` }} /></span>
          <b>{proposal.targetWidth}px</b><small>отступ {proposal.gutter}px · responsive включён</small>
        </div>
        <div className="fe-smart-axis-list">
          {proposal.affectedLabels.slice(0, 6).map((label) => <span key={label}>✓ {label}</span>)}
          {proposal.affectedLabels.length > 6 && <span>+ ещё {proposal.affectedLabels.length - 6}</span>}
        </div>
        <div className="fe-smart-axis-note">Изменение атомарное. После применения его можно отменить обычным Undo.</div>
        <div className="fe-smart-axis-actions">
          <button className="fe-btn" onClick={() => ctl.dismissSmartAxisProposal()}>Отмена</button>
          <button className="fe-btn primary" data-act="apply-smart-axis" onClick={() => ctl.applySmartAxisProposal(proposal)}>Применить</button>
        </div>
      </section>
    </div>
  );
}
