<script lang="ts">
  import * as ctl from "./controller";
  import { editorUi } from "./state";

  const proposal = $derived($editorUi.qualityProposal);
  const fixCount = $derived(proposal ? proposal.journal.length : 0);

  function issueText(issue: { rule?: string; path?: string; message?: string }) {
    return issue.message || issue.rule || issue.path || "Нарушение дизайн-ограничения";
  }
</script>

{#if proposal}
  <div
    class="fe-quality-backdrop"
    role="presentation"
    onmousedown={(event) => {
      if (event.target === event.currentTarget && proposal.status !== "loading") ctl.dismissQualityProposal();
    }}
  >
    <div class="fe-quality-card" role="dialog" aria-modal="true" aria-labelledby="quality-title">
      <div class="fe-quality-kicker">AI Quality Copilot · проверка перед экспортом</div>
      <h2 id="quality-title">{proposal.status === "loading" ? "Проверяю макет…" : proposal.passed ? "Критичных проблем нет" : `Найдено проблем: ${proposal.violations.length}`}</h2>
      {#if proposal.status === "loading"}
        <div class="fe-quality-loader"><i></i><span>Сетка, overflow, ограничения и структура</span></div>
      {/if}
      {#if proposal.status === "error"}
        <div class="fe-quality-error">Не удалось выполнить проверку: {proposal.error}</div>
      {/if}
      {#if proposal.status === "ready"}
        <div class="fe-quality-score"><b>{Math.max(0, 100 - proposal.violations.length * 8)}</b><span>техническое качество<br/><small>{fixCount} исправлений подготовлено</small></span></div>
        <div class="fe-quality-issues">
          {#each proposal.violations.slice(0, 7) as issue, index (`${issue.rule || "issue"}-${index}`)}
            <div><b>{issue.severity || "check"}</b><span>{issueText(issue)}<small>{issue.path || issue.rule || "document"}</small></span></div>
          {/each}
          {#if !proposal.violations.length}
            <div class="fe-quality-pass">✓ Макет проходит детерминированные правила</div>
          {/if}
        </div>
        <p>AI показывает результат до изменения. Автоисправление не меняет контент и откатывается через Undo.</p>
      {/if}
      <div class="fe-quality-actions">
        <button class="fe-btn" data-act="dismiss-quality-gate" onclick={() => ctl.dismissQualityProposal()}>Закрыть</button>
        {#if proposal.status === "ready" && fixCount > 0}
          <button class="fe-btn primary" data-act="apply-quality-fixes" onclick={() => ctl.applyQualityProposal(proposal)}>Исправить {fixCount}</button>
        {/if}
      </div>
    </div>
  </div>
{/if}
