<script lang="ts">
  import * as ctl from "./controller";
  import { editorUi } from "./state";

  const proposal = $derived($editorUi.responsiveProposal);
</script>

{#if proposal}
  <div
    class="fe-responsive-backdrop"
    role="presentation"
    onmousedown={(event) => {
      if (event.target === event.currentTarget && proposal.status !== "loading") ctl.dismissResponsiveProposal();
    }}
  >
    <div class="fe-responsive-card" role="dialog" aria-modal="true" aria-labelledby="responsive-title">
      <div class="fe-responsive-kicker">AI Responsive Autopilot · preview first</div>
      <h2 id="responsive-title">{proposal.status === "loading" ? "Строю адаптивные ограничения…" : "Tablet и mobile готовы"}</h2>
      {#if proposal.status === "loading"}
        <div class="fe-responsive-loader"><i></i><span>Reflow, ширина, отступы, типографика и проверка overflow</span></div>
      {/if}
      {#if proposal.status === "error"}
        <div class="fe-responsive-error">Autopilot недоступен: {proposal.error}</div>
      {/if}
      {#if proposal.status === "ready"}
        <div class="fe-responsive-devices"><span>D<b>1440</b></span><i>→</i><span>T<b>768</b></span><i>→</i><span>M<b>390</b></span></div>
        <div class="fe-responsive-decisions">
          {#each proposal.decisions as item (item.kind)}
            <div><b>{item.count}</b><span>{item.label}</span></div>
          {/each}
        </div>
        <div class={"fe-responsive-validation " + (proposal.warnings.length ? "warn" : "pass")}>
          {proposal.warnings.length ? `Quality Gate оставил предупреждений: ${proposal.warnings.length}` : "✓ Кандидат прошёл детерминированный Quality Gate"}
        </div>
        <p>Импортированные pixel-faithful блоки не перестраиваются автоматически. Все решения применяются одной операцией и доступны через Undo.</p>
      {/if}
      <div class="fe-responsive-actions">
        <button class="fe-btn" disabled={proposal.status === "loading"} onclick={() => ctl.dismissResponsiveProposal()}>Отмена</button>
        {#if proposal.status === "ready"}
          <button class="fe-btn primary" data-act="apply-responsive-autopilot" onclick={() => ctl.applyResponsiveProposal(proposal)}>Применить адаптив</button>
        {/if}
      </div>
    </div>
  </div>
{/if}
