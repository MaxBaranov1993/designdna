import * as ctl from "./controller";
import { useEditorStore } from "./store";

function issueText(issue: { rule?: string; path?: string; message?: string }) {
  return issue.message || issue.rule || issue.path || "Нарушение дизайн-ограничения";
}

export function QualityGatePanel() {
  const proposal = useEditorStore((state) => state.qualityProposal);
  if (!proposal) return null;
  const fixCount = proposal.journal.length;
  return (
    <div className="fe-quality-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget && proposal.status !== "loading") ctl.dismissQualityProposal();
    }}>
      <section className="fe-quality-card" role="dialog" aria-modal="true" aria-labelledby="quality-title">
        <div className="fe-quality-kicker">AI Quality Copilot · проверка перед экспортом</div>
        <h2 id="quality-title">{proposal.status === "loading" ? "Проверяю макет…" : proposal.passed ? "Критичных проблем нет" : `Найдено проблем: ${proposal.violations.length}`}</h2>
        {proposal.status === "loading" ? <div className="fe-quality-loader"><i /><span>Сетка, overflow, ограничения и структура</span></div> : null}
        {proposal.status === "error" ? <div className="fe-quality-error">Не удалось выполнить проверку: {proposal.error}</div> : null}
        {proposal.status === "ready" ? (
          <>
            <div className="fe-quality-score"><b>{Math.max(0, 100 - proposal.violations.length * 8)}</b><span>техническое качество<br/><small>{fixCount} исправлений подготовлено</small></span></div>
            <div className="fe-quality-issues">
              {proposal.violations.slice(0, 7).map((issue, index) => (
                <div key={`${issue.rule || "issue"}-${index}`}><b>{issue.severity || "check"}</b><span>{issueText(issue)}<small>{issue.path || issue.rule || "document"}</small></span></div>
              ))}
              {!proposal.violations.length && <div className="fe-quality-pass">✓ Макет проходит детерминированные правила</div>}
            </div>
            <p>AI показывает результат до изменения. Автоисправление не меняет контент и откатывается через Undo.</p>
          </>
        ) : null}
        <div className="fe-quality-actions">
          <button className="fe-btn" disabled={proposal.status === "loading"} onClick={() => ctl.dismissQualityProposal()}>Закрыть</button>
          {proposal.status === "ready" && fixCount > 0 ? <button className="fe-btn primary" data-act="apply-quality-fixes" onClick={() => ctl.applyQualityProposal(proposal)}>Исправить {fixCount}</button> : null}
        </div>
      </section>
    </div>
  );
}
