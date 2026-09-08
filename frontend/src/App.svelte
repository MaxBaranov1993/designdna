<script lang="ts">
  import { SvelteFlowProvider } from "@xyflow/svelte";
  import { onMount } from "svelte";
  import type { Component } from "svelte";

  import Rail from "./chrome/Rail.svelte";
  import ProjectCard from "./chrome/ProjectCard.svelte";
  import StatusCard from "./chrome/StatusCard.svelte";
  import FlowCanvas from "./FlowCanvas.svelte";
  import GraphInspector from "./GraphInspector.svelte";
  import ToastViewport from "./flow/ToastViewport.svelte";
  import ConflictDialog from "./flow/ConflictDialog.svelte";
  import ConfirmHost from "./flow/ConfirmHost.svelte";
  import HotkeyCheatsheet from "./flow/HotkeyCheatsheet.svelte";
  import type { ProjectConflictDetail } from "./flow/serialize";
  import { installGraphDev } from "./flow/graphdev";
  import { toast } from "./flow/toast";
  import { useFlowStore } from "./flow/store";
  import { getConfig } from "./flow/api";
  import { installRendererLiveCommands } from "./desktop/live-command-handler";

  /* Каркас по мотивам Weavy: канвас на весь экран, слева рельса 56px, над
   * канвасом плавают карточка проекта (страницы), правая карточка (движок,
   * экспорт, очередь задач) и инспектор, который появляется только при
   * выделении ноды. Поверхности Project Map / Agents переключаются в рельсе. */
  type WorkspaceSurface = "design" | "map" | "agents";
  type LazyComponent = Component<Record<string, never>>;

  let surface = $state<WorkspaceSurface>("design");
  let EditorComponent = $state<LazyComponent | null>(null);
  let ProjectMapComponent = $state<LazyComponent | null>(null);
  let AgentComponent = $state<LazyComponent | null>(null);
  let editorLoad: Promise<LazyComponent> | null = null;
  let dsEditorNodeId = $state<number | null>(null);
  /* Конфликт 409 автосейва: пока не null — модалка ConflictDialog */
  let projectConflict = $state<ProjectConflictDetail | null>(null);
  let DsEditorComponent: any = $state(null);
  /* Десктоп: системная шапка скрыта (titleBarStyle hidden), свою полосу 36px
   * с зоной перетаскивания рисуем сами; оверлеи редакторов (portal в body)
   * сдвигаются через html[data-desktop]. */
  const isDesktop = typeof window !== "undefined" && !!window.designDNA;
  if (isDesktop && typeof document !== "undefined") document.documentElement.dataset.desktop = "1";
  async function ensureDsEditor() {
    if (!DsEditorComponent) {
      const mod = await import("./editor/DesignSystemPanel.svelte");
      DsEditorComponent = mod.default;
    }
  }

  const ensureEditor = () => {
    if (EditorComponent) return;
    editorLoad ??= import("./editor/EditorApp.svelte").then((module) => module.default);
    void editorLoad.then((component) => {
      EditorComponent = component;
    });
  };

  const showSurface = (next: WorkspaceSurface) => {
    surface = next;
    if (next === "map" && !ProjectMapComponent) {
      void import("./desktop/ProjectMapPanel.svelte").then((module) => {
        ProjectMapComponent = module.default;
      });
    }
    if (next === "agents" && !AgentComponent) {
      void import("./desktop/AgentWorkspace.svelte").then((module) => {
        AgentComponent = module.default;
      });
    }
  };

  onMount(() => {
    const onEditorRequest = () => ensureEditor();
    window.addEventListener("designdna:open-ds-editor", (event: Event) => {
      dsEditorNodeId = (event as CustomEvent).detail?.nodeId ?? null;
      // Без catch отказ динамического импорта был невидим: окно просто
      // не открывалось, а причина тонула в unhandled rejection.
      void ensureDsEditor().catch((error) => {
        dsEditorNodeId = null;
        console.error("Design System editor failed to load", error);
        toast(`Не удалось открыть редактор дизайн-системы: ${error?.message || error}`);
      });
    });
    window.addEventListener("designdna:ensure-editor", onEditorRequest);
    // Fail-closed сейв (serialize.ts): после 409 автосохранение в БД молчит,
    // пока пользователь не решит конфликт — без слушателя это тихая потеря работы.
    const onProjectConflict = (event: Event) => {
      const detail = (event as CustomEvent<ProjectConflictDetail>).detail;
      projectConflict = detail || { expectedRevision: null, currentRevision: null, error: "stale_revision" };
    };
    window.addEventListener("designdna:project-conflict", onProjectConflict);
    // «Передать в Генератор» из панели DS: система становится выбором проекта,
    // Генератор подхватывает её через pinnedDesignSystemRef.
    const onDsToGenerator = (event: Event) => {
      const systemId = String((event as CustomEvent).detail?.systemId || "");
      if (!systemId) return;
      useFlowStore.getState().setDesignSystemPicker({ selection: systemId });
      toast("Дизайн-система передана в Генератор", "ok");
    };
    window.addEventListener("designdna:ds-to-generator", onDsToGenerator);
    installGraphDev();
    const uninstallLiveCommands = installRendererLiveCommands();
    void useFlowStore.getState().loadPersistedProject();
    // Load runtime config/feature flags once on boot. Failures are non-fatal.
    void getConfig().catch(() => ({ flags: {} }));
    // Keep the initial graph path lean, then warm the editor before the first likely click.
    const editorWarmup = window.setTimeout(ensureEditor, 500);
    return () => {
      window.clearTimeout(editorWarmup);
      uninstallLiveCommands();
      window.removeEventListener("designdna:ensure-editor", onEditorRequest);
      window.removeEventListener("designdna:project-conflict", onProjectConflict);
      window.removeEventListener("designdna:ds-to-generator", onDsToGenerator);
    };
  });
</script>

<div class="dna-scroll">
  <div class="dna-app" class:desktop={isDesktop} data-surface={surface}>
    {#if isDesktop}
      <div class="dna-titlebar" role="presentation">
        <span class="tb-name">DesignDNA</span>
        <span class="tb-badge">локально</span>
      </div>
    {/if}
    <Rail {surface} onselect={showSurface} />
    {#if surface === "design"}
      <SvelteFlowProvider>
        <main class="dna-canvas">
          <FlowCanvas />
        </main>
        <ProjectCard />
        <StatusCard />
        <GraphInspector />
      </SvelteFlowProvider>
      <ToastViewport />
      <HotkeyCheatsheet />
      {#if projectConflict}
        <ConflictDialog detail={projectConflict} onclose={() => (projectConflict = null)} />
      {/if}
      {#if EditorComponent}<EditorComponent />{/if}
      {#if DsEditorComponent && dsEditorNodeId != null}
        <DsEditorComponent nodeId={dsEditorNodeId} onClose={() => (dsEditorNodeId = null)} />
      {/if}
    {:else if surface === "map"}
      <div class="dna-surface">
        {#if ProjectMapComponent}
          <ProjectMapComponent />
        {:else}
          <div class="grid h-full place-items-center text-sm text-muted-foreground">Загрузка Project Map…</div>
        {/if}
      </div>
    {:else}
      <div class="dna-surface">
        {#if AgentComponent}
          <AgentComponent />
        {:else}
          <div class="grid h-full place-items-center text-sm text-muted-foreground">Загрузка Agents…</div>
        {/if}
      </div>
    {/if}
    <!-- Фирменный confirm вне переключателя поверхностей: нужен и графу, и Project Map -->
    <ConfirmHost />
  </div>
</div>
