<script lang="ts">
  import * as ctl from "./controller";
  import { editorUi } from "./state";

  const view = $derived.by(() => {
    void $editorUi.sourceTick;
    return ctl.getSourceLensView();
  });
</script>

{#if view.sources.length}
  <div class="fe-source-lens" aria-label="Source Lens">
    <button
      class={"fe-source-lens-toggle" + (view.enabled ? " active" : "")}
      onclick={() => ctl.toggleSourceLens()}
      title="Цветом показать происхождение компонентов"
    >
      ◉ Source Lens
    </button>
    <div class="fe-source-lens-list">
      {#each view.sources as source (source.id)}
        <button
          class={"fe-source-filter" + (source.active ? " active" : " muted")}
          style="--source-color: {source.color}"
          onclick={() => ctl.toggleSourceFilter(source.id)}
          title={`${source.label} · ${Math.round((source.confidence ?? 1) * 100)}% confidence · ${source.count} layers`}
        >
          <span class="fe-source-filter-symbol">{source.symbol || "S"}</span>
          <span>{source.label}</span>
          <small>{source.count}</small>
        </button>
      {/each}
    </div>
    <span class="fe-source-lens-help">Выберите слой — его источник появится в инспекторе</span>
  </div>
{/if}
