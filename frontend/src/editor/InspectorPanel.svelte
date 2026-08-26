<script lang="ts">
  /* Правая панель инспектора — чистый Svelte (без window.Inspector/innerHTML).
   * Контроллер хранит сессию (sel/ir/viewport/geo) и бампит store.inspectorTick;
   * панель перечитывает сессию и перемонтирует дерево по key={tick} — как legacy
   * перестраивал innerHTML. События — нативные, навешивает wireInspector после
   * монтирования (инпуты неконтролируемые: коммит по change, как в editor.js). */
  import * as ctl from "./controller";
  import { editorUi } from "./state";
  import SharedInspector from "./inspector/SharedInspector.svelte";
  import TypeGroups from "./inspector/TypeGroups.svelte";
  import { wireInspector } from "./inspector/wireInspector";
  import { tick as afterDomUpdate } from "svelte";

  const tick = $derived($editorUi.inspectorTick);
  const busy = $derived($editorUi.aiBusy);
  const previewing = $derived(!!$editorUi.aiPreview);

  // The controller mutates selection inside the long-lived session object.
  // Depend on the explicit revision instead of the session reference, whose
  // identity does not change and can otherwise leave the empty state mounted.
  const selCount = $derived.by(() => {
    void $editorUi.inspectorTick;
    return ctl.getSession()?.sel.length ?? 0;
  });
  const source = $derived.by(() => {
    void $editorUi.inspectorTick;
    return selCount ? ctl.sourceForSelection() : null;
  });
  let contentRoot = $state<HTMLDivElement | null>(null);
  const wiredRoots = new WeakSet<HTMLDivElement>();
  let undoBtn: HTMLButtonElement | null = $state(null);
  let redoBtn: HTMLButtonElement | null = $state(null);

  // История доступна всегда (не только при выделении): disabled-состояние
  // обновляет контроллер через dom-refs
  $effect(() => {
    ctl.dom.undoBtn = undoBtn;
    ctl.dom.redoBtn = redoBtn;
    ctl.updateUndoBtn();
  });

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
  <div class="fe-insp-actions">
    <button class="fe-abtn" data-act="semantic-select" title="Выделить элементы обычным текстовым запросом" aria-label="Умное выделение" disabled={busy} onclick={() => ctl.handleAct("semantic-select")}>⌘ Умное выделение</button>
    <button class="fe-abtn" data-act="smart-axis" title="AI найдёт общую ось контента и покажет безопасный патч" aria-label="Выровнять ширину" disabled={busy} onclick={() => ctl.handleAct("smart-axis")}>✦ Выровнять ширину</button>
    <button class="fe-abtn" data-act="quality-gate" title="Проверить сетку, overflow и ограничения; показать исправления до применения" aria-label="AI-проверка" disabled={busy} onclick={() => ctl.handleAct("quality-gate")}>✓ AI‑проверка</button>
    <button class="fe-abtn" data-act="harmonize" title="Свести цвета, типографику, радиусы и тени разных источников в одну Style DNA" aria-label="Сделать цельно" disabled={busy} onclick={() => ctl.handleAct("harmonize")}>✦ Сделать цельно</button>
    <button class="fe-abtn" data-act="responsive-autopilot" title="AI подготовит tablet/mobile constraints и проверит их до применения" aria-label="Адаптировать" disabled={busy} onclick={() => ctl.handleAct("responsive-autopilot")}>▣ Адаптировать</button>
    <button class="fe-abtn" data-act="intent-locks" title="Защитить выбранные блоки от изменений AI" aria-label="Не менять" disabled={busy} onclick={() => ctl.handleAct("intent-locks")}>🔒 Не менять</button>
    <button class="fe-abtn" data-act="style-dna" title="Style DNA" aria-label="Style DNA" disabled={busy} onclick={() => ctl.handleAct("style-dna")}>🧬 Style DNA</button>
    <span class="fe-abtn-sep"></span>
    <button class="fe-abtn" data-act="undo" bind:this={undoBtn} title="Отменить (Ctrl+Z)" aria-label="Отменить" aria-keyshortcuts="Control+Z" onclick={() => ctl.handleAct("undo")}>↩ Отменить</button>
    <button class="fe-abtn" data-act="redo" bind:this={redoBtn} title="Повторить (Ctrl+Shift+Z)" aria-label="Вернуть" aria-keyshortcuts="Control+Shift+Z" onclick={() => ctl.handleAct("redo")}>↪ Вернуть</button>
    <button class="fe-abtn" data-act="forward" title="Выше (])" aria-label="Выше" aria-keyshortcuts="]" disabled={busy || previewing} onclick={() => ctl.handleAct("forward")}>⇈ Выше</button>
    <button class="fe-abtn" data-act="backward" title="Ниже ([)" aria-label="Ниже" aria-keyshortcuts="[" disabled={busy || previewing} onclick={() => ctl.handleAct("backward")}>⇊ Ниже</button>
  </div>
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
          {#if !previewing}
            <TypeGroups />
          {/if}
        </div>
      </div>
    {/key}
  {:else}
    <div class="fe-insp-empty"><span>✦</span><strong>Выберите объект</strong><p>Нажмите элемент на холсте или в слоях. Затем опишите AI, что изменить.</p></div>
  {/if}
</div>
