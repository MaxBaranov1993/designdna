<script lang="ts">
  import * as ctl from "./controller";
  import { editorUi } from "./state";

  const EXAMPLES = ["все кнопки", "заголовки", "все карточки", "изображения", "элементы источника B"];

  const open = $derived($editorUi.semanticSelectOpen);
  let query = $state("");
  let count: number | null = $state(null);

  function run() {
    count = ctl.semanticSelect(query);
  }
</script>

{#if open}
  <div
    class="fe-semantic-backdrop"
    role="presentation"
    onmousedown={(event) => {
      if (event.target === event.currentTarget) ctl.closeSemanticSelect();
    }}
  >
    <div class="fe-semantic-card" role="dialog" aria-modal="true" aria-labelledby="semantic-title">
      <div class="fe-semantic-kicker">Semantic Selection · AI понимает смысл и источник</div>
      <h2 id="semantic-title">Что выделить?</h2>
      <div class="fe-semantic-input">
        <input
          value={query}
          oninput={(event) => { query = event.currentTarget.value; count = null; }}
          onkeydown={(event) => { if (event.key === "Enter") run(); }}
          placeholder="Например: все CTA из Header"
          aria-label="Запрос умного выделения"
        />
        <button class="fe-btn primary" data-act="run-semantic-select" disabled={!query.trim()} onclick={run}>Выделить</button>
      </div>
      <div class="fe-semantic-examples">
        {#each EXAMPLES as example (example)}
          <button onclick={() => { query = example; count = null; }}>{example}</button>
        {/each}
      </div>
      {#if count !== null}
        <div class={"fe-semantic-result " + (count ? "found" : "empty")}>{count ? `Выделено элементов: ${count}` : "Совпадений нет — уточните тип или название источника"}</div>
      {/if}
      <p>Запрос комбинирует семантику элемента и provenance. Например, «кнопки из Imported header» не затронет CTA из других источников.</p>
      <div class="fe-semantic-actions"><button class="fe-btn" data-act="dismiss-semantic-select" onclick={() => ctl.closeSemanticSelect()}>Готово</button></div>
    </div>
  </div>
{/if}
