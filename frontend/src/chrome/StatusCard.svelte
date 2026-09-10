<script lang="ts">
  import { NODE_DEFS } from "../flow/ports";
  import { flow } from "../flow/state";
  import { useFlowStore, bindPageState } from "../flow/store";
  import { focusFlowNode } from "../flow/graphdev";
  import { buildExportPayload, downloadJson, parseLegacyPayload } from "../flow/serialize";
  import { embedGraphAssets, restoreGraphAssets } from "../flow/portable-assets";
  import { toast } from "../flow/toast";
  import { selectOnlyNode } from "../flow/ui";
  import { subscribeTick } from "../flow/ticker";
  import EngineStatus from "../desktop/EngineStatus.svelte";
  import type { NodeType } from "../flow/types";

  /* Правая карточка (Weavy: credits · Share · Tasks): честный статус движка,
   * меню экспорта/импорта и очередь запусков нод с прогрессом и отменой. */
  let menuOpen = $state(false);
  let tasksOpen = $state(false);
  let transferBusy = $state(false);
  let fileInput: HTMLInputElement | null = null;

  let tasks = $derived.by(() => {
    const state = $flow;
    return state.pages.flatMap(page => {
      const runtime = page.id === state.activePageId ? state : state.pageRuntimes[page.id];
      const nodes = page.id === state.activePageId ? state.nodes : page.nodes;
      return Object.keys(runtime?.busy || {}).filter(id => runtime!.busy[Number(id)]).flatMap(id => {
        const node = nodes.find(n => Number(n.id) === Number(id));
        if (!node) return [];
        const def = node.type ? NODE_DEFS[node.type as NodeType] : null;
        return [{ id: Number(id), pageId: page.id, pageName: page.name,
          key: JSON.stringify([page.id, id]), title: def?.title || `Нода ${id}`, progress: runtime!.progresses[Number(id)] || null }];
      });
    });
  });
  const showTask = (task: { id: number; pageId: string }) => {
    useFlowStore.getState().switchPage(task.pageId);
    selectOnlyNode(task.id);
    void focusFlowNode(String(task.id), () => useFlowStore.getState().activePageId === task.pageId);
  };
  let now = $state(Date.now());
  $effect(() => {
    if (!tasks.length) return;
    return subscribeTick((value) => (now = value));
  });
  const clock = (startedAt: number) => {
    const total = Math.max(0, Math.floor((now - startedAt) / 1000));
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
  };

  const onExport = async () => {
    menuOpen = false;
    transferBusy = true;
    try { downloadJson("designai-graph.json", await embedGraphAssets(buildExportPayload(useFlowStore.getState()))); }
    catch (error) { toast("Экспорт не завершён: " + (error instanceof Error ? error.message : String(error)), "error"); }
    finally { transferBusy = false; }
  };
  const onImportFile = (event: Event) => {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    const get = bindPageState();
    const initial = get();
    reader.onload = async () => {
      transferBusy = true;
      try {
        const restored = await restoreGraphAssets(JSON.parse(String(reader.result)));
        const now = get();
        if (now.nodes !== initial.nodes || now.edges !== initial.edges || now.activePageId !== initial.activePageId) throw new Error("Граф изменился во время импорта. Повторите импорт в нужном листе");
        now.loadGraph(parseLegacyPayload(restored));
        toast("Граф загружен", "ok");
      } catch (error) {
        toast("Не удалось прочитать JSON: " + (error instanceof Error ? error.message : String(error)), "error");
      } finally { transferBusy = false; }
    };
    reader.readAsText(file);
    input.value = "";
  };
  const closeOnOutside = (node: HTMLElement) => {
    const onDown = (event: MouseEvent) => {
      if (!node.contains(event.target as Node)) menuOpen = false;
    };
    window.addEventListener("mousedown", onDown, true);
    return { destroy: () => window.removeEventListener("mousedown", onDown, true) };
  };
</script>

<div class="float-card tr" use:closeOnOutside>
  <div style="padding: 0 6px 0 4px"><EngineStatus /></div>
  <span class="pc-vsep"></span>
  <div style="position: relative">
    <button class="sc-btn" disabled={transferBusy} aria-busy={transferBusy} aria-haspopup="menu" aria-expanded={menuOpen} onclick={() => (menuOpen = !menuOpen)}>{transferBusy ? "Ресурсы…" : "Экспорт ▾"}</button>
    {#if menuOpen}
      <div class="sc-menu" role="menu">
        <button class="pc-item" id="btn-export" role="menuitem" onclick={onExport}><span class="name">Экспорт графа · JSON</span></button>
        <button class="pc-item" id="btn-import" role="menuitem" onclick={() => { fileInput?.click(); menuOpen = false; }}><span class="name">Импорт графа · JSON</span></button>
      </div>
    {/if}
  </div>
  <input bind:this={fileInput} type="file" accept="application/json" class="hidden" onchange={onImportFile} />
</div>

<div class="sc-tasks" aria-live="polite">
  <button class="sc-tasks-head" aria-expanded={tasksOpen} onclick={() => (tasksOpen = !tasksOpen)}>
    <span>Задачи</span>
    {#if tasks.length}<span class="n">{tasks.length}</span>{/if}
    <span style="color: var(--dna-dim); font-size: 9px">{tasksOpen ? "▲" : "▼"}</span>
  </button>
  {#if tasksOpen}
    <div class="sc-tasks-list">
      {#if !tasks.length}
        <div class="task-row"><span>Сейчас ничего не выполняется.</span></div>
      {/if}
      {#each tasks as task (task.key)}
        {@const measured = !!task.progress && Number.isFinite(task.progress.percent)}
        <div class="task-row" role="button" tabindex="0" title="Показать ноду" onclick={() => showTask(task)} onkeydown={(event) => event.key === "Enter" && showTask(task)}>
          <b>{task.pageName} · {task.title}</b>
          <button class="task-x" title="Отменить" aria-label="Отменить задачу" onclick={(event) => { event.stopPropagation(); void bindPageState(task.pageId)().cancelRun(task.id); }}>✕</button>
          <span>{task.progress ? `${task.progress.label}${task.progress.stage ? ` · ${task.progress.stage}` : ""} · ${clock(task.progress.startedAt)}` : "выполняется…"}</span>
          <div class="task-bar" class:indeterminate={!measured}><i style={measured ? `width: ${Math.round(Number(task.progress!.percent))}%` : ""}></i></div>
        </div>
      {/each}
    </div>
  {/if}
</div>
