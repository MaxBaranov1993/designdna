<script lang="ts">
  import { SvelteFlowProvider } from "@xyflow/svelte";
  import { onMount } from "svelte";
  import type { Component } from "svelte";

  import Button from "./components/ui/Button.svelte";
  import Card from "./components/ui/Card.svelte";
  import CardContent from "./components/ui/CardContent.svelte";
  import CardHeader from "./components/ui/CardHeader.svelte";
  import CardTitle from "./components/ui/CardTitle.svelte";
  import TopBar from "./TopBar.svelte";
  import PagesPanel from "./PagesPanel.svelte";
  import FlowCanvas from "./FlowCanvas.svelte";
  import ToastViewport from "./flow/ToastViewport.svelte";
  import { installGraphDev } from "./flow/graphdev";
  import { useFlowStore } from "./flow/store";
  import { getConfig } from "./flow/api";

  type WorkspaceSurface = "design" | "map" | "agents";
  type LazyComponent = Component<Record<string, never>>;

  let surface = $state<WorkspaceSurface>("design");
  let EditorComponent = $state<LazyComponent | null>(null);
  let ProjectMapComponent = $state<LazyComponent | null>(null);
  let AgentComponent = $state<LazyComponent | null>(null);
  let editorLoad: Promise<LazyComponent> | null = null;
  let dsEditorNodeId: number | null = null;
  let DsEditorComponent: any = $state(null);
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
      void ensureDsEditor();
    });
    window.addEventListener("designdna:ensure-editor", onEditorRequest);
    installGraphDev();
    void useFlowStore.getState().loadPersistedProject();
    // Load runtime config/feature flags once on boot. Failures are non-fatal.
    void getConfig().catch(() => ({ flags: {} }));
    // Keep the initial graph path lean, then warm the editor before the first likely click.
    const editorWarmup = window.setTimeout(ensureEditor, 500);
    return () => {
      window.clearTimeout(editorWarmup);
      window.removeEventListener("designdna:ensure-editor", onEditorRequest);
    };
  });
</script>

<div class="flex h-full flex-col">
  <nav class="flex h-11 shrink-0 items-center justify-between border-b bg-background px-3">
    <strong class="text-sm tracking-tight">DesignDNA</strong>
    <div class="flex rounded-lg border bg-muted/50 p-0.5" aria-label="Workspace surface">
      <Button variant={surface === "design" ? "default" : "ghost"} size="sm" onclick={() => showSurface("design")}>
        Design
      </Button>
      <Button variant={surface === "map" ? "default" : "ghost"} size="sm" onclick={() => showSurface("map")}>
        Project Map
      </Button>
      <Button variant={surface === "agents" ? "default" : "ghost"} size="sm" onclick={() => showSurface("agents")}>
        Agents
      </Button>
    </div>
    <span class="text-[11px] text-muted-foreground">{window.designDNA ? "Desktop · local" : "Browser mode"}</span>
  </nav>
  <div class="min-h-0 flex-1">
    {#if surface === "design"}
      <div class="flex h-full flex-col">
        <SvelteFlowProvider>
          <TopBar />
          <div class="flex min-h-0 flex-1">
            <aside class="w-72 shrink-0 space-y-4 overflow-y-auto border-r p-4">
              <PagesPanel />
              <Card>
                <CardHeader>
                  <CardTitle>Инспектор</CardTitle>
                </CardHeader>
                <CardContent>
                  <p class="text-xs leading-relaxed text-muted-foreground">
                    Design IR — единый источник истины для графа, редактора DNA и генерации.
                  </p>
                </CardContent>
              </Card>
            </aside>
            <main class="min-w-0 flex-1">
              <FlowCanvas />
            </main>
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
