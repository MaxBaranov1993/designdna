<script lang="ts">
  import { flow, flowChannels } from "../flow/state";
  import { commitNodeText, flushNodeText } from "../flow/textcommit";
  import type { PageBridgeNodeData } from "../flow/types";

  /* Каналы Page Bridge живут здесь, а не в отдельной колонке. */
  let { id, data }: { id: number; data: PageBridgeNodeData } = $props();
  let channelNames = $derived(Object.keys($flowChannels).filter((key) => $flowChannels[key]));
</script>

<div class="dna-insp-fields">
  <div class="dna-field">
    <div class="dna-field-cap">Mode</div>
    <div class="dna-insp-seg">
      <button class:active={data.mode === "send"} onclick={() => $flow.setNodeData(id, { mode: "send" })}>Send</button>
      <button class:active={data.mode === "receive"} onclick={() => $flow.setNodeData(id, { mode: "receive" })}>Receive</button>
    </div>
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Channel</div>
    <input type="text" value={data.channel} placeholder="shared-component"
      oninput={(e) => {
        const value = e.currentTarget.value;
        commitNodeText(`pagebridge:${id}:channel`, () => $flow.setNodeData(id, { channel: value }));
      }}
      onblur={() => { flushNodeText(`pagebridge:${id}:channel`); $flow.runNode(id); }} />
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Active project channels</div>
    {#if channelNames.length}
      {#each channelNames as name (name)}
        <button class="dna-field-value" style="cursor: pointer; text-align: left" onclick={() => { $flow.setNodeData(id, { channel: name }); $flow.runNode(id); }}>
          <span>{name}</span><span class="dna-out-kind">{data.channel === name ? "current" : "select"}</span>
        </button>
      {/each}
    {:else}
      <div class="dna-field-hint">Page Bridge shares a completed component between pages through a named channel. Channels appear after the first send.</div>
    {/if}
  </div>
</div>
