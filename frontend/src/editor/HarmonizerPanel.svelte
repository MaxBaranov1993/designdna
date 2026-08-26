<script lang="ts">
  import * as ctl from "./controller";
  import { editorUi } from "./state";

  const proposal = $derived($editorUi.harmonizerProposal);

  function colors(tokens: any): string[] {
    const source = tokens?.semantic?.color || tokens?.color || {};
    return [...new Set(Object.values(source).filter((value): value is string => typeof value === "string" && /^#[0-9a-f]{3,8}$/i.test(value)))].slice(0, 8);
  }

  const palette = $derived(proposal ? colors(proposal.tokens) : []);
  const displayFont = $derived(proposal?.tokens?.font?.display?.family || proposal?.tokens?.semantic?.font?.display || "из Style DNA");
  const bodyFont = $derived(proposal?.tokens?.font?.body?.family || proposal?.tokens?.semantic?.font?.body || "из Style DNA");
</script>

{#if proposal}
  <div
    class="fe-harmonize-backdrop"
    role="presentation"
    onmousedown={(event) => {
      if (event.target === event.currentTarget && proposal.status !== "loading") ctl.dismissHarmonizerProposal();
    }}
  >
    <div class="fe-harmonize-card" role="dialog" aria-modal="true" aria-labelledby="harmonize-title">
      <div class="fe-harmonize-kicker">AI Harmonizer · {proposal.sourceCount} источн.</div>
      <h2 id="harmonize-title">{proposal.status === "loading" ? "Собираю общую Style DNA…" : "Сделать страницу визуально цельной"}</h2>
      {#if proposal.status === "loading"}
        <div class="fe-harmonize-loader"><i></i><span>Ищу повторяющиеся цвета, шрифты, радиусы, тени и semantic roles</span></div>
      {/if}
      {#if proposal.status === "error"}
        <div class="fe-harmonize-error">Harmonizer недоступен: {proposal.error}</div>
      {/if}
      {#if proposal.status === "ready"}
        <p>Структура, тексты и изображения сохранятся. Изменятся только стилевые фасеты, связанные с общей системой.</p>
        <div class="fe-harmonize-preview">
          <div><small>Палитра</small><span class="fe-harmonize-palette">{#each palette as color (color)}<i style="background: {color}" title={color}></i>{/each}</span></div>
          <div><small>Типографика</small><b>{displayFont}</b><span>{bodyFont}</span></div>
          <div><small>Нормализация</small><b>цвет · тип · радиус · тень</b><span>через semantic bindings</span></div>
        </div>
        <div class="fe-harmonize-note">Предпросмотр не изменил IR. После Apply доступен обычный Undo.</div>
      {/if}
      <div class="fe-harmonize-actions">
        <button class="fe-btn" data-act="dismiss-harmonizer" onclick={() => ctl.dismissHarmonizerProposal()}>Отмена</button>
        {#if proposal.status === "ready"}
          <button class="fe-btn primary" data-act="apply-harmonizer" onclick={() => ctl.applyHarmonizerProposal(proposal)}>Применить Style DNA</button>
        {/if}
      </div>
    </div>
  </div>
{/if}
