<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import { toast } from "../flow/toast";
  import ProviderPicker from "../components/ProviderPicker.svelte";
  import IrPreview from "../components/IrPreview.svelte";
  import { flow } from "../flow/state";
  import { videoPages } from "../flow/video-inputs";
  import type { TimelineFlowNode } from "../flow/types";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import InPorts from "./InPorts.svelte";
  import OutPorts from "./OutPorts.svelte";

  let { id, data, selected }: NodeProps<TimelineFlowNode> = $props();

  let nodeId = $derived(Number(id));
  let busy = $derived(Boolean($flow.busy[nodeId]));
  let open = $state(false);
  let preparing = $state(false);
  let startWithPrompt = $state(false);
  let TimelineWorkspace = $state<any>(null);
  let timeline = $derived(data.timeline as Record<string, any> | null);
  let layers = $derived(Array.isArray(timeline?.layers) ? timeline.layers.length : 0);
  let duration = $derived(Number(timeline?.composition?.duration || 0));
  const inputs = $derived(data.inputs || ["ir"]);
  function renamePage(port: string, name: string) {
    const pageNames = { ...data.pageNames, [port]: name.slice(0, 120) };
    const sourcePages = (data.sourcePages || []).map((p) => ({ ...p, name: pageNames[p.id] || p.name }));
    const next = data.timeline ? JSON.parse(JSON.stringify(data.timeline)) : null;
    if (next?.story) next.story.pages = next.story.pages.map((p: any) => ({ ...p, name: pageNames[p.id] || p.name }));
    $flow.setNodeData(nodeId, { pageNames, sourcePages, ...(next ? { timeline: next } : {}) });
  }

  const openWorkspace = async (withPrompt = false) => {
    if (preparing || busy) return;
    if (inputs.some((port) => !(data.sourcePages || []).some((p) => p.id === port)) && inputs.length > 1) {
      toast("Подключите все страницы или удалите пустой вход", "error"); return;
    }
    preparing = true;
    try {
      if (!data.timeline) await $flow.runTimeline(nodeId);
      const current = $flow.nodes.find((node) => node.id === id);
      if (current?.type !== "timeline" || !current.data.timeline) return;
      if (!(current.data.timeline as any).story) {
        const pages = videoPages($flow.nodes, $flow.edges, current, true);
        if (!pages.length) throw new Error("Подключите исходную страницу для сценария");
        const upgraded = JSON.parse(JSON.stringify(current.data.timeline));
        upgraded.story = { pages, initialPageId: pages[0].id, actions: [] };
        $flow.setNodeData(nodeId, { sourcePages: pages });
        if (!$flow.commitTimeline(nodeId, current.data.timeline, $flow.getNodeIrRevision(nodeId), upgraded,
          { kind: "manual", label: "Добавлен сценарий страниц" })) throw new Error("Страницы изменились — откройте редактор повторно");
      }
      startWithPrompt = withPrompt;
      if (!TimelineWorkspace) TimelineWorkspace = (await import("../editor/TimelineWorkspace.svelte")).default;
      open = true;
    } catch (error) {
      open = false;
      toast(`Не удалось открыть редактор: ${error instanceof Error ? error.message : String(error)}`, "error");
    } finally {
      preparing = false;
    }
  };
</script>

<NodeShell {id} type="timeline" {selected}>
  <InPorts type="timeline" {data} />
  <div class="timeline-node-body nodrag" style:padding-top={`${8 + (inputs.length - 1) * 24}px`}>
    <div class="video-pages">
      {#each inputs as port, index (port)}
        <div class="video-page-row">
          <span>{index + 1}</span>
          <input aria-label={`Название страницы ${index + 1}`} value={data.pageNames?.[port] || `Страница ${index + 1}`} maxlength="120"
            onchange={(event) => renamePage(port, event.currentTarget.value.trim() || `Страница ${index + 1}`)} />
          {#if port !== "ir"}<button title="Удалить вход страницы" onclick={() => $flow.removeVideoInput(nodeId, port)}>×</button>{/if}
        </div>
      {/each}
      <button class="btn-node small" disabled={inputs.length >= 8 || busy} onclick={() => $flow.addVideoInput(nodeId)}>+ Страница</button>
    </div>
    <IrPreview ir={data.ir} height={130} fitHeight empty="Подключите готовую страницу" />
    <label class="video-prompt">
      <span>Что должно происходить в ролике</span>
      <textarea rows="3" aria-label="Промпт видео" value={data.prompt || ""}
        placeholder="На странице «Форма» заполни поля, нажми «Разместить» и перейди к странице «Готово»"
        disabled={busy || preparing}
        oninput={(event) => $flow.setNodeData(nodeId, { prompt: event.currentTarget.value })}></textarea>
    </label>
    <div inert={busy || preparing}>
      <ProviderPicker accountsOnly provider={data.provider === "claude" ? "claude" : "codex"} effort={data.effort || "medium"}
        onChange={(choice) => $flow.setNodeData(nodeId, choice)} />
    </div>
    <div class="timeline-node-meta">
      <span>{layers} слоёв</span>
      <span>{(duration / 1000).toFixed(1)}s · {data.settings.fps} fps</span>
    </div>
    <div class="timeline-node-format">{data.settings.width}×{data.settings.height} · без звука · {data.revisions?.length || 0} версий</div>
  </div>
  <div class="ctl-row">
    <button class="btn-node primary small nodrag" disabled={busy || preparing || !data.ir || !data.prompt?.trim()} onclick={() => void openWorkspace(true)}>
      {#if busy || preparing}<span class="spinner"></span>{/if} Создать по промпту
    </button>
    <button class="btn-node small nodrag" disabled={busy || preparing || !data.ir} onclick={() => void openWorkspace()}>Открыть редактор</button>
  </div>
  <div class="video-footer"><NodeStatus {id} /></div>
  <OutPorts type="timeline" {data} />
  {#if open && TimelineWorkspace}
    <TimelineWorkspace {nodeId} {data} {startWithPrompt} onClose={() => (open = false)} />
  {/if}
</NodeShell>

<style>
  .timeline-node-body { display: grid; gap: 10px; padding: 8px 10px 4px; font-size: 12px; color: var(--c-text, #d7dae0); }
  .video-prompt { display: grid; gap: 5px; }
  .video-prompt span { font-size: 11px; color: var(--dna-text-2); }
  .video-prompt textarea { width: 100%; resize: vertical; min-height: 68px; }
  .video-footer { min-height: 58px; padding-right: 100px; }
  .video-pages { display: grid; gap: 5px; }
  .video-page-row { display: flex; gap: 7px; align-items: center; }
  .video-page-row > span { color: var(--dna-dim); font-size: 10px; }
  .video-page-row input { width: 100%; min-width: 0; font-size: 11px; padding: 5px; }
  .timeline-node-meta { display: flex; justify-content: space-between; gap: 8px; }
  .timeline-node-format { margin-top: 4px; color: var(--c-text-dim, #8b909a); font-size: 11px; }
</style>
