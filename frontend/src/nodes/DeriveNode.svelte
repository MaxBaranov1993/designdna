<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import ProviderPicker from "../components/ProviderPicker.svelte";
  import IrPreview from "../components/IrPreview.svelte";
  import ResultAssets from "../components/ResultAssets.svelte";
  import { flow, flowBusy } from "../flow/state";
  import type { DeriveFlowNode } from "../flow/types";
  import DesignSystemPicker from "../components/DesignSystemPicker.svelte";
import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import InPorts from "./InPorts.svelte";
  import OutPorts from "./OutPorts.svelte";

  let { id, data, selected }: NodeProps<DeriveFlowNode> = $props();

  let busy = $derived(!!$flowBusy[Number(id)]);
  let activeIr = $derived(data.variants.length ? data.variants[data.active] || null : null);
</script>

<NodeShell {id} type="derive" {selected}>
  <InPorts type="derive" />
  <textarea
    class="f-own nodrag nowheel"
    placeholder="например: сделай footer в том же стиле, сохрани плотность и радиусы"
    value={data.prompt}
    oninput={(e) => $flow.setNodeData(Number(id), { prompt: e.currentTarget.value })}
  ></textarea>
  <div class="ctl-row">
    <ProviderPicker provider={data.provider || "openai"} effort={data.effort || "medium"} onChange={(next) => $flow.setNodeData(Number(id), next)} />
    <select
      class="f-count nodrag"
      value={String(data.count)}
      onchange={(e) => $flow.setNodeData(Number(id), { count: Number(e.currentTarget.value) })}
    >
      <option value="1">1</option>
      <option value="2">2</option>
      <option value="3">3</option>
    </select>
    <button class="btn-node primary small f-run nodrag" disabled={busy} onclick={() => $flow.runNode(Number(id))}>
      {#if busy}<span class="spinner"></span>{/if} Derive
    </button>
  </div>
  {#if data.variants.length}
    <div class="thumbs">
      {#each data.variants as v, i (i)}
        <div
          class={"thumb nodrag" + (i === data.active ? " active" : "")}
          role="button"
          tabindex="0"
          onkeydown={(event) => {
            if (event.key !== "Enter" && event.key !== " ") return;
            event.preventDefault();
            if (busy) return;
            $flow.setNodeData(Number(id), { active: i });
            $flow.propagate(Number(id));
          }}
          onclick={() => {
            if (busy) return;
            $flow.setNodeData(Number(id), { active: i });
            $flow.propagate(Number(id));
          }}
        >
          <span class="tbadge">{i + 1}</span>
          <IrPreview ir={v} height={96} empty="" />
        </div>
      {/each}
    </div>
  {/if}
  <IrPreview class="f-preview" ir={activeIr} height={160} empty="варианты появятся после запуска" />
  <div class="gen-actions">
    <button class="btn-node small f-to-editor nodrag" onclick={() => $flow.sendToNode(Number(id), "edit")}>
      → Editor
    </button>
  </div>
  <DesignSystemPicker selection={(data as any).designSystemSelection || "inherit"} usageMode={(data as any).designSystemUsageMode || "strict"} fixtureProfile={(data as any).designSystemFixture || "typical"} onChange={(v, meta) => $flow.setNodeData(Number(id), { designSystemSelection: v, designSystemUsageMode: meta?.usageMode, designSystemFixture: meta?.fixtureProfile } as any)} />
  <NodeStatus {id} />
  <ResultAssets {id} type="derive" {data} />
  <OutPorts type="derive" />
</NodeShell>
