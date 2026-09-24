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
      title="Color-code component provenance"
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
    <span class="fe-source-lens-help">Select a layer to see its source in the inspector</span>
  </div>
{/if}
