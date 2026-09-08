<script lang="ts">
  import { NODE_DEFS } from "../flow/ports";
  import { flowBusy, flowNodes, flowProgresses } from "../flow/state";
  import { useFlowStore } from "../flow/store";
  import { buildExportPayload, downloadJson, parseLegacyPayload } from "../flow/serialize";
  import { toast } from "../flow/toast";
  import { selectOnlyNode } from "../flow/ui";
  import { subscribeTick } from "../flow/ticker";
  import EngineStatus from "../desktop/EngineStatus.svelte";
  import type { NodeType } from "../flow/types";

  /* Правая карточка (Weavy: credits · Share · Tasks): честный статус движка,
   * меню экспорта/импорта и очередь запусков нод с прогрессом и отменой. */
  let menuOpen = $state(false);
  let tasksOpen = $state(false);
  let fileInput: HTMLInputElement | null = null;

  let tasks = $derived.by(() => {
    const busy = $flowBusy;
    const progresses = $flowProgresses;
    return Object.keys(busy).filter((id) => busy[Number(id)]).map((id) => {
      const node = $flowNodes.find((n) => Number(n.id) === Number(id));
      const def = node?.type ? NODE_DEFS[node.type as NodeType] : null;
      return { id: Number(id), title: def?.title || `Нода ${id}`, progress: progresses[Number(id)] || null };
    });
  });
  let now = $state(Date.now());
  $effect(() => {
    if (!tasks.length) return;
    return subscribeTick((value) => (now = value));
  });
  const clock = (startedAt: number) => {
    const total = Math.max(0, Math.floor((now - startedAt) / 1000));
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
  };

  const onExport = () => {
    downloadJson("designai-graph.json", buildExportPayload(useFlowStore.getState()));
    menuOpen = false;
  };
  const onImportFile = (event: Event) => {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        useFlowStore.getState().loadGraph(parseLegacyPayload(JSON.parse(String(reader.result))));
        toast("Граф загружен", "ok");
      } catch (error) {
        toast("Не удалось прочитать JSON: " + (error instanceof Error ? error.message : String(error)), "error");
      }
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
    <button class="sc-btn" aria-haspopup="menu" aria-expanded={menuOpen} onclick={() => (menuOpen = !menuOpen)}>Экспорт ▾</button>
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
      {#each tasks as task (task.id)}
        {@const measured = !!task.progress && Number.isFinite(task.progress.percent)}
        <div class="task-row" role="button" tabindex="0" title="Показать ноду" onclick={() => selectOnlyNode(task.id)} onkeydown={(event) => event.key === "Enter" && selectOnlyNode(task.id)}>
          <b>{task.title}</b>
          <button class="task-x" title="Отменить" aria-label="Отменить задачу" onclick={(event) => { event.stopPropagation(); void useFlowStore.getState().cancelRun(task.id); }}>✕</button>
          <span>{task.progress ? `${task.progress.label}${task.progress.stage ? ` · ${task.progress.stage}` : ""} · ${clock(task.progress.startedAt)}` : "выполняется…"}</span>
          <div class="task-bar" class:indeterminate={!measured}><i style={measured ? `width: ${Math.round(Number(task.progress!.percent))}%` : ""}></i></div>
        </div>
      {/each}
    </div>
  {/if}
</div>
