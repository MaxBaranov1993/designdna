<script lang="ts">
  import { useSvelteFlow, useViewport } from "@xyflow/svelte";
  import { onMount } from "svelte";
  import Button from "./components/ui/Button.svelte";
  import { buildExportPayload, downloadJson, parseLegacyPayload } from "./flow/serialize";
  import { useFlowStore } from "./flow/store";
  import { toast } from "./flow/toast";

  /* Топбар — зеркало header.topbar (nodes.html): Fit, Экспорт JSON, Импорт, Очистить,
   * счётчик кэша, zoom-label */
  const { fitView, setViewport } = useSvelteFlow();
  const viewport = useViewport();
  let cacheStat = $state("");
  let fileInput: HTMLInputElement | null = null;

  onMount(() => {
    fetch("/api/cache/stats")
      .then((r) => r.json())
      .then((s) => {
        cacheStat = s.hits_total > 0 ? `💾 кэш сэкономил ${s.hits_total} вызов(ов)` : "";
      })
      .catch(() => {});
  });

  const onFit = () => {
    if (!useFlowStore.getState().nodes.length) {
      void setViewport({ x: 80, y: 40, zoom: 1 });
      return;
    }
    void fitView();
  };

  const onExport = () => {
    downloadJson("designai-graph.json", buildExportPayload(useFlowStore.getState()));
  };

  const onImportFile = (e: Event) => {
    const input = e.currentTarget as HTMLInputElement;
    const f = input.files && input.files[0];
    if (!f) return;
    const rd = new FileReader();
    rd.onload = () => {
      try {
        useFlowStore.getState().loadGraph(parseLegacyPayload(JSON.parse(String(rd.result))));
        toast("Граф загружен", "ok");
      } catch (err) {
        toast("Не удалось прочитать JSON: " + (err instanceof Error ? err.message : String(err)), "error");
      }
    };
    rd.readAsText(f);
    input.value = "";
  };

  const onClear = () => {
    const st = useFlowStore.getState();
    if (!st.nodes.length) return;
    if (!window.confirm("Удалить все ноды графа?")) return;
    st.clearGraph();
  };
</script>

<header class="flex h-12 shrink-0 items-center gap-3 border-b bg-background px-4">
  <span class="text-sm font-extrabold tracking-tight">
    DNA<span class="text-muted-foreground">·</span>Web
  </span>
  <span class="hidden text-xs text-muted-foreground lg:inline">
    ПКМ — создать ноду · колесо — зум · drag фона — панорама
  </span>
  <div class="flex-1"></div>
  <span
    id="cache-stat"
    class="max-w-64 truncate text-xs text-muted-foreground"
    title="Повторные запросы Source Import отданы из кэша — токены не тратились"
  >
    {cacheStat}
  </span>
  <span class="w-11 text-center text-xs tabular-nums text-muted-foreground">
    {Math.round(viewport.current.zoom * 100)}%
  </span>
  <Button variant="outline" size="sm" id="btn-fit" onclick={onFit}>⤢ Всё</Button>
  <Button variant="outline" size="sm" id="btn-export" onclick={onExport}>Экспорт JSON</Button>
  <Button variant="outline" size="sm" id="btn-import" onclick={() => fileInput?.click()}>Импорт</Button>
  <Button variant="outline" size="sm" id="btn-clear" onclick={onClear}>Очистить</Button>
  <input bind:this={fileInput} type="file" accept="application/json" class="hidden" onchange={onImportFile} />
</header>
