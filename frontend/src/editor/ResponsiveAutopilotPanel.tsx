import * as ctl from "./controller";
import { useEditorStore } from "./store";

export function ResponsiveAutopilotPanel() {
  const proposal = useEditorStore((state) => state.responsiveProposal);
  if (!proposal) return null;
  return (
    <div className="fe-responsive-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget && proposal.status !== "loading") ctl.dismissResponsiveProposal();
    }}>
      <section className="fe-responsive-card" role="dialog" aria-modal="true" aria-labelledby="responsive-title">
        <div className="fe-responsive-kicker">AI Responsive Autopilot · preview first</div>
        <h2 id="responsive-title">{proposal.status === "loading" ? "Строю адаптивные ограничения…" : "Tablet и mobile готовы"}</h2>
        {proposal.status === "loading" ? <div className="fe-responsive-loader"><i/><span>Reflow, ширина, отступы, типографика и проверка overflow</span></div> : null}
        {proposal.status === "error" ? <div className="fe-responsive-error">Autopilot недоступен: {proposal.error}</div> : null}
        {proposal.status === "ready" ? (
          <>
            <div className="fe-responsive-devices"><span>D<b>1440</b></span><i>→</i><span>T<b>768</b></span><i>→</i><span>M<b>390</b></span></div>
            <div className="fe-responsive-decisions">{proposal.decisions.map((item) => <div key={item.kind}><b>{item.count}</b><span>{item.label}</span></div>)}</div>
            <div className={"fe-responsive-validation " + (proposal.warnings.length ? "warn" : "pass")}>
              {proposal.warnings.length ? `Quality Gate оставил предупреждений: ${proposal.warnings.length}` : "✓ Кандидат прошёл детерминированный Quality Gate"}
            </div>
            <p>Импортированные pixel-faithful блоки не перестраиваются автоматически. Все решения применяются одной операцией и доступны через Undo.</p>
          </>
        ) : null}
        <div className="fe-responsive-actions">
          <button className="fe-btn" disabled={proposal.status === "loading"} onClick={() => ctl.dismissResponsiveProposal()}>Отмена</button>
          {proposal.status === "ready" ? <button className="fe-btn primary" data-act="apply-responsive-autopilot" onClick={() => ctl.applyResponsiveProposal(proposal)}>Применить адаптив</button> : null}
        </div>
      </section>
    </div>
  );
}
