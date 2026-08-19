<script lang="ts">
  /* Панель слоёв: поиск (Svelte) + дерево слоёв (императивный остров контроллера —
   * строки, drag-reorder, hide/lock-флаги строятся портом renderLayers из editor.js). */
  import * as ctl from "./controller";

  let search: HTMLInputElement | null = $state(null);
  let layersTree: HTMLDivElement | null = $state(null);

  $effect(() => {
    ctl.dom.search = search;
    ctl.dom.layersTree = layersTree;
  });
</script>

<div class="fe-layers">
  <div class="fe-layers-head">Слои</div>
  <input
    class="fe-search"
    placeholder="Поиск слоёв…"
    bind:this={search}
    oninput={(e) => ctl.setLayerQuery(e.currentTarget.value)}
  />
  <div class="fe-layers-tree" bind:this={layersTree}></div>
</div>
