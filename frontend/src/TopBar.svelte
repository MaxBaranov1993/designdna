<script lang="ts">
  import { useSvelteFlow, useViewport } from "@xyflow/svelte";
  import { onMount } from "svelte";
  import { buildExportPayload, downloadJson, parseLegacyPayload } from "./flow/serialize";
  import { useFlowStore } from "./flow/store";
  import { toast } from "./flow/toast";
  import { leftPanelOpen, requestNodeMenu } from "./flow/ui";

  const { fitView, setViewport } = useSvelteFlow();
  const viewport = useViewport();
  let cacheStat = $state("");
  let fileInput: HTMLInputElement | null = null;

  onMount(() => {
    fetch("/api/cache/stats")
      .then((response) => response.json())
      .then((stats) => {
        cacheStat = stats.hits_total > 0 ? `Кэш сэкономил ${stats.hits_total} вызовов` : "";
      })
      .catch(() => {});
  });

  const onFit = () => {
    if (!useFlowStore.getState().nodes.length) {
      void setViewport({ x: 80, y: 40, zoom: 1 });
      return;
    }
    void fitView({ padding: 0.14 });
  };

  const stepZoom = (delta: number) => {
    const current = viewport.current;
    void setViewport({ x: current.x, y: current.y, zoom: Math.min(2, Math.max(0.3, current.zoom + delta)) });
  };

  const onExport = () => downloadJson("designai-graph.json", buildExportPayload(useFlowStore.getState()));

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
</script>

<header class="dna-strip">
  <div class="dna-strip-left">
    <button class="dna-collapse" title={$leftPanelOpen ? "Свернуть страницы" : "Показать страницы"} onclick={() => ($leftPanelOpen = !$leftPanelOpen)}>
      {$leftPanelOpen ? "⟨" : "⟩"}
    </button>
    <span class="dna-strip-title">DNA · Web</span>
    <span class="dna-vsep"></span>
    <div class="dna-hints" aria-label="Управление холстом">
      <span class="dna-hint-chip">ПКМ — нода</span>
      <span class="dna-hint-chip">Колесо — зум</span>
      <span class="dna-hint-chip">Drag или СКМ — панорама</span>
    </div>
  </div>
  <div class="dna-strip-right">
    {#if cacheStat}<span class="dna-cache-chip" title="Повторные Source Import отданы из кэша">{cacheStat}</span>{/if}
    <div class="dna-zoom" aria-label="Масштаб холста">
      <button class="dna-zoom-step" title="Уменьшить" onclick={() => stepZoom(-0.1)}>−</button>
      <button class="dna-zoom-pct" title="Сбросить масштаб" onclick={() => void setViewport({ x: viewport.current.x, y: viewport.current.y, zoom: 1 })}>
        {Math.round(viewport.current.zoom * 100)}%
      </button>
      <button class="dna-zoom-step" title="Увеличить" onclick={() => stepZoom(0.1)}>+</button>
      <button class="dna-zoom-fit" id="btn-fit" onclick={onFit}>Всё</button>
    </div>
    <div class="dna-tools">
      <button class="dna-tool-btn" id="btn-import" onclick={() => fileInput?.click()}>Импорт</button>
      <button class="dna-tool-btn" id="btn-export" onclick={onExport}>Экспорт JSON</button>
      <button class="dna-btn-primary" onclick={requestNodeMenu}>+ Нода</button>
    </div>
    <input bind:this={fileInput} type="file" accept="application/json" class="hidden" onchange={onImportFile} />
  </div>
</header>
