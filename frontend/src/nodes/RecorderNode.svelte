<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import IrPreview from "../components/IrPreview.svelte";
  import { flow } from "../flow/state";
  import type {
    InteractionDraftEvent,
    InteractionDraftScene,
    InteractionLiveAction,
    IRObject,
    RecorderFlowNode,
    SourceViewport,
  } from "../flow/types";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import InPorts from "./InPorts.svelte";
  import OutPorts from "./OutPorts.svelte";

  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  const PHONE_RE = /^\+?[\d\s().-]{7,}$/;
  const TOKEN_RE = /^(?:bearer\s+)?[a-z0-9_-]{24,}(?:\.[a-z0-9_-]{10,}){0,2}$/i;

  function sanitizeTypedValue(value: string): string {
    const trimmed = value.trim();
    if (EMAIL_RE.test(trimmed)) return "[EMAIL]";
    if (PHONE_RE.test(trimmed)) return "[PHONE]";
    if (TOKEN_RE.test(trimmed)) return "[TOKEN]";
    return value;
  }

  function escapePointer(value: string): string {
    return value.replace(/~/g, "~0").replace(/\//g, "~1");
  }

  function valueAtPath(root: unknown, path: string): unknown {
    return path.split(".").filter(Boolean).reduce<unknown>((value, part) => {
      if (!value || typeof value !== "object") return undefined;
      return (value as Record<string, unknown>)[part];
    }, root);
  }

  function valueAtPointer(root: unknown, pointer: string): unknown {
    return pointer.split("/").slice(1).reduce<unknown>((value, part) => {
      if (!value || typeof value !== "object") return undefined;
      const key = part.replace(/~1/g, "/").replace(/~0/g, "~");
      return (value as Record<string, unknown>)[key];
    }, root);
  }

  function findSourceKey(value: unknown): string {
    if (!value || typeof value !== "object") return "";
    const record = value as Record<string, unknown>;
    if (typeof record.sourceKey === "string") return record.sourceKey;
    return "";
  }

  function hasOwn(value: Record<string, unknown>, key: string): boolean {
    return Object.prototype.hasOwnProperty.call(value, key);
  }

  function targetFromPreview(ir: IRObject, target: HTMLElement): { sourceKey: string; path: string } | null {
    const sectionElement = target.closest<HTMLElement>("[data-ir-sec]");
    if (!sectionElement) return null;
    const sectionIndex = Number(sectionElement.dataset.irSec);
    const tree = Array.isArray(ir.tree) ? ir.tree : [];
    const section = tree[sectionIndex] as Record<string, unknown> | undefined;
    if (!section) return null;

    const pathElement = target.closest<HTMLElement>("[data-ir-path]");
    const dotPath = pathElement?.dataset.irPath || "";
    const selected = dotPath ? valueAtPath(section, dotPath) : section;
    const parentPath = dotPath.includes(".") ? dotPath.slice(0, dotPath.lastIndexOf(".")) : "";
    const sourceKey = findSourceKey(selected) || findSourceKey(valueAtPath(section, parentPath)) || findSourceKey(section);
    if (!sourceKey) return null;
    const pointer = ["tree", String(sectionIndex), ...dotPath.split(".").filter(Boolean)]
      .map(escapePointer)
      .join("/");
    return { sourceKey, path: `/${pointer}` };
  }

  function nextTime(events: InteractionDraftEvent[]): number {
    return events.length ? events[events.length - 1].time + 500 : 0;
  }

  function upsertPatch(
    patch: InteractionDraftScene["patch"],
    next: InteractionDraftScene["patch"][number],
  ): InteractionDraftScene["patch"] {
    return [...patch.filter((item) => item.path !== next.path), next];
  }

  let { id, data, selected }: NodeProps<RecorderFlowNode> = $props();

  let nodeId = $derived(Number(id));
  let busy = $derived(Boolean($flow.busy[nodeId]));
  let typedValue = $state("");
  let scrollY = $state("640");
  let liveActions = $state<InteractionLiveAction[]>([]);
  let liveType = $state<InteractionLiveAction["type"]>("click");
  let liveSourceKey = $state("");
  let liveSelector = $state("");
  let liveValue = $state("");
  let currentSceneId = $derived(data.draftScenes.at(-1)?.id || "scene-0");
  let privacyReport = $derived(data.interaction?.privacyReport as Record<string, unknown> | undefined);

  const appendEvent = (event: Omit<InteractionDraftEvent, "id" | "time">) => {
    const draftEvents = [
      ...data.draftEvents,
      { ...event, id: `event-${data.draftEvents.length + 1}`, time: nextTime(data.draftEvents) },
    ];
    $flow.setNodeData(nodeId, { draftEvents, interaction: null });
  };

  const selectTarget = (event: MouseEvent) => {
    if (!data.ir) return;
    const element = event.target as HTMLElement;
    const target = targetFromPreview(data.ir, element);
    if (!target) return;
    $flow.setNodeData(nodeId, { selectedTarget: target.sourceKey, selectedPath: target.path });
    if (data.recording) {
      appendEvent({ type: "click", targetSourceKey: target.sourceKey, payload: {}, resultingSceneId: currentSceneId });
    }
  };

  const addTypeEvent = () => {
    if (!data.selectedTarget || !data.selectedPath || !typedValue) return;
    const safeValue = sanitizeTypedValue(typedValue);
    const nextSceneId = `scene-${data.draftScenes.length}`;
    const previousPatch = data.draftScenes.at(-1)?.patch || [];
    const selectedValue = valueAtPointer(data.ir, data.selectedPath);
    const selectedRecord = selectedValue && typeof selectedValue === "object"
      ? selectedValue as Record<string, unknown>
      : null;
    const property = selectedRecord
      ? (hasOwn(selectedRecord, "value") ? "value" : hasOwn(selectedRecord, "text") ? "text" : "value")
      : "";
    const valuePath = property ? `${data.selectedPath}/${property}` : data.selectedPath;
    const op = selectedRecord && !hasOwn(selectedRecord, property) ? "add" : "replace";
    const scene: InteractionDraftScene = {
      id: nextSceneId,
      viewport: "desktop",
      patch: upsertPatch(previousPatch, { op, path: valuePath, value: safeValue }),
    };
    $flow.setNodeData(nodeId, {
      draftScenes: [...data.draftScenes, scene],
      draftEvents: [
        ...data.draftEvents,
        {
          id: `event-${data.draftEvents.length + 1}`,
          time: nextTime(data.draftEvents),
          type: "type",
          targetSourceKey: data.selectedTarget,
          payload: { value: safeValue },
          resultingSceneId: nextSceneId,
        },
      ],
      interaction: null,
    });
    typedValue = "";
  };

  const addScrollEvent = () => {
    const y = Number(scrollY);
    if (!Number.isFinite(y)) return;
    appendEvent({
      type: "scroll",
      targetSourceKey: data.selectedTarget || "document-root",
      payload: { y },
      resultingSceneId: currentSceneId,
    });
  };

  const reset = () => {
    typedValue = "";
    $flow.setNodeData(nodeId, {
      interaction: null,
      recording: false,
      selectedTarget: "",
      selectedPath: "",
      draftEvents: [],
      draftScenes: [{ id: "scene-0", viewport: "desktop", patch: [] }],
    });
  };

  const addLiveAction = () => {
    const targetSourceKey = liveSourceKey.trim() || liveSelector.trim() || "document-root";
    if (!["scroll", "navigate"].includes(liveType) && !liveSelector.trim()) return;
    const action: InteractionLiveAction = {
      type: liveType,
      targetSourceKey,
      selector: liveSelector.trim(),
    };
    if (liveType === "type") action.value = liveValue;
    if (liveType === "scroll") action.y = Number(liveValue) || 0;
    if (liveType === "navigate") action.url = liveValue.trim();
    liveActions = [...liveActions, action];
    liveValue = "";
  };

  const captureLive = async () => {
    const complete = await $flow.runLiveRecorder(nodeId, liveActions);
    if (complete) {
      liveActions = [];
      liveValue = "";
    }
  };
</script>

<NodeShell {id} type="recorder" {selected}>
  <InPorts type="recorder" />
  <div class="recorder-mode nodrag" role="tablist" aria-label="Recorder source">
    <button class={data.mode !== "live" ? "active" : ""} onclick={() => $flow.setNodeData(nodeId, { mode: "preview" })}>Preview</button>
    <button class={data.mode === "live" ? "active" : ""} onclick={() => $flow.setNodeData(nodeId, { mode: "live" })}>Live URL</button>
  </div>
  {#if data.mode !== "live"}
    <div class="recorder-preview nodrag">
      <IrPreview
        ir={data.ir}
        height={210}
        fitHeight
        interactive
        onclickcapture={selectTarget}
        empty="Connect Design IR to record interactions"
      />
      <div class="recorder-preview-bar">
        <span>{data.selectedTarget || "Click a preview element"}</span>
        <button
          class={`btn-node small ${data.recording ? "recording" : ""}`}
          onclick={() => $flow.setNodeData(nodeId, { recording: !data.recording })}
          disabled={!data.ir}
        >
          {data.recording ? "Pause" : "Record"}
        </button>
      </div>
    </div>
  {:else}
    <div class="recorder-live nodrag">
      <input
        type="text"
        value={data.liveUrl || ""}
        placeholder="https://your-site.com/signup"
        oninput={(event) => $flow.setNodeData(nodeId, { liveUrl: event.currentTarget.value, interaction: null })}
      />
      <div class="recorder-live-meta">
        <select
          value={data.liveViewport || "desktop"}
          onchange={(event) => $flow.setNodeData(nodeId, { liveViewport: event.currentTarget.value as SourceViewport })}
        >
          <option value="desktop">Desktop</option>
          <option value="tablet">Tablet</option>
          <option value="mobile">Mobile</option>
        </select>
        <label><input type="checkbox" checked={Boolean(data.mine)} onchange={(event) => $flow.setNodeData(nodeId, { mine: event.currentTarget.checked })} /> My site / permission</label>
      </div>
      <div class="recorder-live-builder">
        <select bind:value={liveType}>
          <option value="click">Click</option>
          <option value="type">Type</option>
          <option value="focus">Focus</option>
          <option value="submit">Submit</option>
          <option value="scroll">Scroll</option>
          <option value="navigate">Navigate</option>
        </select>
        <input type="text" bind:value={liveSourceKey} placeholder="sourceKey" />
        <input type="text" bind:value={liveSelector} placeholder="CSS selector" />
        {#if liveType === "type" || liveType === "scroll" || liveType === "navigate"}
          <input
            type={liveType === "scroll" ? "number" : "text"}
            bind:value={liveValue}
            placeholder={liveType === "type" ? "Transient value" : liveType === "scroll" ? "Scroll Y" : "/next-path"}
          />
        {/if}
        <button class="btn-node small" onclick={addLiveAction}>Add step</button>
      </div>
      {#if liveActions.length}
        <div class="recorder-live-steps">
          {#each liveActions as action, index (`${index}-${action.type}`)}
            <div>
              <strong>{index + 1}. {action.type}</strong>
              <span>{action.targetSourceKey}</span>
              <button title="Remove step" onclick={() => (liveActions = liveActions.filter((_, item) => item !== index))}>x</button>
            </div>
          {/each}
        </div>
      {:else}
        <div class="bp-hint">Add selectors in the order Chromium should replay them.</div>
      {/if}
    </div>
  {/if}
  {#if data.mode !== "live"}
    <div class="recorder-tools nodrag">
      <div class="recorder-input-row">
        <input type="text" bind:value={typedValue} placeholder="Type value (PII is redacted)" />
        <button class="btn-node small" onclick={addTypeEvent} disabled={!data.selectedTarget || !typedValue}>Type</button>
      </div>
      <div class="recorder-input-row">
        <input type="number" bind:value={scrollY} aria-label="Scroll Y" />
        <button class="btn-node small" onclick={addScrollEvent}>Scroll</button>
      </div>
    </div>
  {/if}
  <div class="recorder-summary">
    <span>{data.mode === "live" ? liveActions.length : data.draftEvents.length} {data.mode === "live" ? "steps" : "events"}</span>
    {#if data.mode !== "live"}<span>{data.draftScenes.length} scenes</span>{/if}
    {#if privacyReport}<span>{Number(privacyReport.sanitizedCount || 0)} redacted</span>{/if}
  </div>
  {#if data.mode !== "live" && data.draftEvents.length}
    <div class="recorder-events nodrag">
      {#each data.draftEvents.slice(-4) as event (event.id)}
        <div><strong>{event.type}</strong><span>{event.targetSourceKey}</span></div>
      {/each}
    </div>
  {/if}
  <div class="ctl-row">
    <button
      class="btn-node primary small nodrag"
      disabled={busy || !data.ir || (data.mode === "live" && (!data.mine || !data.liveUrl || !liveActions.length))}
      onclick={() => (data.mode === "live" ? void captureLive() : $flow.runNode(nodeId))}
    >
      {#if busy}<span class="spinner"></span>{/if} {data.mode === "live" ? "Capture live flow" : "Build Interaction IR"}
    </button>
    <button class="btn-node small nodrag" onclick={() => (data.mode === "live" ? (liveActions = []) : reset())}>Reset</button>
  </div>
  <NodeStatus {id} />
  <OutPorts type="recorder" {data} />
</NodeShell>
