<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import { flow } from "../flow/state";
  import type { StyleDnaFlowNode } from "../flow/types";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import InPorts from "./InPorts.svelte";
  import OutPorts from "./OutPorts.svelte";

  let { id, data, selected }: NodeProps<StyleDnaFlowNode> = $props();

  let busy = $derived(!!$flow.busy[Number(id)]);
  let tokensText = $derived(data.tokens ? JSON.stringify(data.tokens, null, 2) : "");
</script>

<NodeShell {id} type="styledna" {selected}>
  <InPorts type="styledna" />
  <div class="ctl-row">
    <button class="btn-node primary small f-run nodrag" disabled={busy} onclick={() => $flow.runNode(Number(id))}>
      {#if busy}<span class="spinner"></span>{/if} Extract DNA
    </button>
  </div>
  {#if data.summary}
    <pre class="dna-summary">{data.summary}</pre>
  {:else}
    <div class="bp-hint">IR или tokens → палитра, шрифты, радиусы, отступы</div>
  {/if}
  {#if tokensText}
    <details class="rs-log f-log">
      <summary>tokens</summary>
      <div class="rs-log-lines">
        <pre>{tokensText.slice(0, 1400)}</pre>
      </div>
    </details>
  {/if}
  <NodeStatus {id} />
  <OutPorts type="styledna" {data} />
</NodeShell>
