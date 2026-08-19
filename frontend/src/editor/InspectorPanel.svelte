<script lang="ts">
  /* Правая панель инспектора — чистый Svelte (без window.Inspector/innerHTML).
   * Контроллер хранит сессию (sel/ir/viewport/geo) и бампит store.inspectorTick;
   * панель перечитывает сессию и перемонтирует дерево по key={tick} — как legacy
   * перестраивал innerHTML. События — нативные, навешивает wireInspector после
   * монтирования (инпуты неконтролируемые: коммит по change, как в editor.js). */
  import * as ctl from "./controller";
  import { editorUi } from "./state";
  import SharedInspector from "./inspector/SharedInspector.svelte";
  import { wireInspector } from "./inspector/wireInspector";
  import { tick as afterDomUpdate } from "svelte";

  const tick = $derived($editorUi.inspectorTick);

  const sess = $derived.by(() => {
    void $editorUi.inspectorTick;
    return ctl.getSession();
  });
  const selCount = $derived(sess ? sess.sel.length : 0);
  const source = $derived(selCount ? ctl.sourceForSelection() : null);
  let contentRoot = $state<HTMLDivElement | null>(null);
  const wiredRoots = new WeakSet<HTMLDivElement>();

  $effect(() => {
    const version = tick;
    const node = contentRoot;
    if (!node) return;
    void afterDomUpdate().then(() => {
      requestAnimationFrame(() => {
        if (
          contentRoot === node &&
          tick === version &&
          node.isConnected &&
          !wiredRoots.has(node)
        ) {
          wiredRoots.add(node);
          wireInspector(node);
        }
      });
    });
  });
</script>

<div class="fe-inspector">
  {#if selCount}
    {#key tick}
      <div bind:this={contentRoot}>
        {#if source}
          <div class="fe-source-origin" style="--source-color: {source.color}">
            <span class="fe-source-origin-symbol">{source.symbol || "S"}</span>
            <span><b>{source.label}</b><small>{source.kind || "source"} · {Math.round((source.confidence ?? 1) * 100)}%</small></span>
            <span class="fe-source-origin-state">linked</span>
          </div>
        {/if}
        <div class="fe-shared-insp">
          <SharedInspector />
        </div>
      </div>
    {/key}
  {:else}
    <div class="fe-insp-empty"><span>✦</span><strong>Выберите объект</strong><p>Нажмите элемент на холсте или в слоях. Затем опишите AI, что изменить.</p></div>
  {/if}
</div>
