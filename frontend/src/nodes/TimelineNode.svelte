<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import { toast } from "../flow/toast";
  import IrPreview from "../components/IrPreview.svelte";
  import { flow } from "../flow/state";
  import { videoPages } from "../flow/video-inputs";
  import type { TimelineFlowNode } from "../flow/types";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import InPorts from "./InPorts.svelte";
  import OutPorts from "./OutPorts.svelte";
  import VideoPlayer from "./VideoPlayer.svelte";

  /* «Видео» — результат-первый (Weavy Video node): готовый ролик с
   * транспортом, а до рендера — кадр исходной страницы с меткой сценария;
   * короткий промпт под кадром, футер «+ Страница» · «Редактор» · «По промпту».
   * Модель, формат, страницы-источники и версии — в инспекторе. */
  let { id, data, selected }: NodeProps<TimelineFlowNode> = $props();

  let nodeId = $derived(Number(id));
  let busy = $derived(Boolean($flow.busy[nodeId]));
  let open = $state(false);
  let preparing = $state(false);
  let startWithPrompt = $state(false);
  let TimelineWorkspace = $state<any>(null);
  let timeline = $derived(data.timeline as Record<string, any> | null);
  let layers = $derived(Array.isArray(timeline?.layers) ? timeline.layers.length : 0);
  let actions = $derived(Array.isArray(timeline?.story?.actions) ? timeline.story.actions.length : 0);
  let duration = $derived(Number(timeline?.composition?.duration || data.settings.duration || 0));
  const inputs = $derived(data.inputs || ["ir"]);
  let rendered = $derived(data.renderJob && data.renderJob.status === "complete" && data.renderJob.downloadUrl ? data.renderJob : null);
  let ratio = $derived((() => {
    const w = data.settings.width, h = data.settings.height;
    return w === h ? "1:1" : w > h ? "16:9" : "9:16";
  })());

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
  {#snippet footer()}
    <div class="foot-left">
      <button class="btn-node small add-input nodrag" disabled={inputs.length >= 8 || busy} onclick={() => $flow.addVideoInput(nodeId)}>+ Страница</button>
    </div>
    <div class="foot-right">
      <button class="btn-node small nodrag" disabled={busy || preparing || !data.ir} onclick={() => void openWorkspace()}>Редактор</button>
      <button class="btn-node primary small nodrag" disabled={busy || preparing || !data.ir || !data.prompt?.trim()} title={!data.prompt?.trim() ? "Опишите ролик, чтобы собрать его по промпту" : ""} onclick={() => void openWorkspace(true)}>
        {#if busy || preparing}<span class="spinner"></span>{/if} По промпту
      </button>
    </div>
  {/snippet}
  <InPorts type="timeline" {data} />
  {#if rendered}
    <VideoPlayer src={rendered.downloadUrl!} label="Готовый ролик" />
  {:else}
    <div class="n-hero nodrag">
      <IrPreview ir={data.ir} height={200} fitHeight empty="Подключите готовую страницу" />
      {#if data.ir}
        <span class="n-hero-tag">{actions ? `${actions} действ. · ` : ""}{(duration / 1000).toFixed(1)} s</span>
      {/if}
    </div>
  {/if}
  <div class="n-meta">
    <span>{layers ? `${layers} слоёв` : "монтаж не собран"}{data.revisions?.length ? ` · ${data.revisions.length} версий` : ""}</span>
    <span>{ratio} · {data.settings.width}×{data.settings.height} · {data.settings.fps} fps</span>
  </div>
  <textarea class="video-prompt nodrag nowheel" rows="2" aria-label="Промпт видео" value={data.prompt || ""}
    placeholder="Что должно происходить в ролике? Например: заполни форму и перейди к странице «Готово»"
    disabled={busy || preparing}
    oninput={(event) => $flow.setNodeData(nodeId, { prompt: event.currentTarget.value })}></textarea>
  <NodeStatus {id} />
  <OutPorts type="timeline" {data} />
  {#if open && TimelineWorkspace}
    <TimelineWorkspace {nodeId} {data} {startWithPrompt} onClose={() => (open = false)} />
  {/if}
</NodeShell>

<style>
  .video-prompt { min-height: 48px; resize: none; }
</style>
