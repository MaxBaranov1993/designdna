<script lang="ts">
  import { SvelteFlowProvider } from "@xyflow/svelte";
  import { onMount } from "svelte";
  import type { Component } from "svelte";

  import TopBar from "./TopBar.svelte";
  import PagesPanel from "./PagesPanel.svelte";
  import FlowCanvas from "./FlowCanvas.svelte";
  import GraphInspector from "./GraphInspector.svelte";
  import ToastViewport from "./flow/ToastViewport.svelte";
  import { installGraphDev } from "./flow/graphdev";
  import { toast } from "./flow/toast";
  import { useFlowStore } from "./flow/store";
  import { getConfig } from "./flow/api";
  import { installRendererLiveCommands } from "./desktop/live-command-handler";

  type WorkspaceSurface = "design" | "map" | "agents";
  type LazyComponent = Component<Record<string, never>>;

  let surface = $state<WorkspaceSurface>("design");
  let EditorComponent = $state<LazyComponent | null>(null);
  let ProjectMapComponent = $state<LazyComponent | null>(null);
  let AgentComponent = $state<LazyComponent | null>(null);
  let editorLoad: Promise<LazyComponent> | null = null;
  let dsEditorNodeId = $state<number | null>(null);
  let DsEditorComponent: any = $state(null);
  const isDesktop = typeof window !== "undefined" && !!window.designDNA;
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
    };
  });
</script>

<div class="dna-scroll">
  <div class="dna-app">
    <header class="dna-topbar">
      <div class="dna-topbar-group">
        <div class="dna-logo-badge">D</div>
        <div class="dna-logo-name">DesignDNA</div>
        <div class="dna-version-pill">{isDesktop ? "v2 · local" : "v2 · browser"}</div>
      </div>
      <div class="dna-seg" aria-label="Workspace surface">
        <button class:active={surface === "design"} onclick={() => showSurface("design")}>Design</button>
        <button class:active={surface === "map"} onclick={() => showSurface("map")}>Project Map</button>
        <button class:active={surface === "agents"} onclick={() => showSurface("agents")}>Agents</button>
      </div>
      <div class="dna-topbar-group">
        <span class="dna-badge lg" style="--badge-tone: {isDesktop ? '#22C55E' : '#8A8A93'}">
          {isDesktop ? "Runner онлайн" : "Browser mode"}
        </span>
        <div class="dna-avatar">M</div>
      </div>
    </header>
    <div class="min-h-0 flex-1" style="display: flex; flex-direction: column;">
      {#if surface === "design"}
        <div class="flex h-full min-h-0 flex-1 flex-col">
          <SvelteFlowProvider>
            <TopBar />
            <div class="dna-body">
              <PagesPanel />
              <main class="dna-canvas">
                <FlowCanvas />
              </main>
              <GraphInspector />
            </div>
          </SvelteFlowProvider>
          <ToastViewport />
          {#if EditorComponent}<EditorComponent />{/if}
          {#if DsEditorComponent && dsEditorNodeId != null}
            <DsEditorComponent nodeId={dsEditorNodeId} onClose={() => (dsEditorNodeId = null)} />
          {/if}
        </div>
      {:else if surface === "map"}
        {#if ProjectMapComponent}
          <ProjectMapComponent />
        {:else}
          <div class="grid h-full place-items-center text-sm text-muted-foreground">Загрузка Project Map…</div>
        {/if}
      {:else}
        {#if AgentComponent}
          <AgentComponent />
        {:else}
          <div class="grid h-full place-items-center text-sm text-muted-foreground">Загрузка Agents…</div>
        {/if}
      {/if}
    </div>
  </div>
</div>
