<script lang="ts">
  import * as ctl from "./controller";
  import { editorUi } from "./state";

  const proposal = $derived($editorUi.smartAxisProposal);
</script>

{#if proposal}
  <div
    class="fe-smart-axis-backdrop"
    role="presentation"
    onmousedown={(event) => {
      if (event.target === event.currentTarget) ctl.dismissSmartAxisProposal();
    }}
  >
    <div class="fe-smart-axis-card" role="dialog" aria-modal="true" aria-labelledby="smart-axis-title">
      <div class="fe-smart-axis-kicker">AI Layout Director · безопасный патч</div>
      <h2 id="smart-axis-title">Единая ширина контента: {proposal.targetWidth}px</h2>
      <p>Ось взята из «{proposal.referenceLabel}». Фоны останутся на всю ширину, изменится только внутренняя сетка.</p>
      <div class="fe-smart-axis-preview" aria-label="Предпросмотр оси">
        <span class="fe-smart-axis-page"><i style="width: {Math.min(88, Math.max(42, proposal.targetWidth / 16))}%"></i></span>
        <b>{proposal.targetWidth}px</b><small>отступ {proposal.gutter}px · responsive включён</small>
      </div>
      <div class="fe-smart-axis-list">
        {#each proposal.affectedLabels.slice(0, 6) as label (label)}
          <span>✓ {label}</span>
        {/each}
        {#if proposal.affectedLabels.length > 6}
          <span>+ ещё {proposal.affectedLabels.length - 6}</span>
        {/if}
      </div>
      <div class="fe-smart-axis-note">Изменение атомарное. После применения его можно отменить обычным Undo.</div>
      <div class="fe-smart-axis-actions">
        <button class="fe-btn" data-act="dismiss-smart-axis" onclick={() => ctl.dismissSmartAxisProposal()}>Отмена</button>
        <button class="fe-btn primary" data-act="apply-smart-axis" onclick={() => ctl.applySmartAxisProposal(proposal)}>Применить</button>
      </div>
    </div>
  </div>
{/if}
