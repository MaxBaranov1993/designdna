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
    <div class="dna-field-cap">Режим</div>
    <div class="dna-insp-seg">
      <button class:active={data.mode === "send"} onclick={() => $flow.setNodeData(id, { mode: "send" })}>Передать</button>
      <button class:active={data.mode === "receive"} onclick={() => $flow.setNodeData(id, { mode: "receive" })}>Получить</button>
    </div>
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Канал</div>
    <input type="text" value={data.channel} placeholder="shared-component"
      oninput={(e) => {
        const value = e.currentTarget.value;
        commitNodeText(`pagebridge:${id}:channel`, () => $flow.setNodeData(id, { channel: value }));
      }}
      onblur={() => { flushNodeText(`pagebridge:${id}:channel`); $flow.runNode(id); }} />
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Активные каналы проекта</div>
    {#if channelNames.length}
      {#each channelNames as name (name)}
        <button class="dna-field-value" style="cursor: pointer; text-align: left" onclick={() => { $flow.setNodeData(id, { channel: name }); $flow.runNode(id); }}>
          <span>{name}</span><span class="dna-out-kind">{data.channel === name ? "текущий" : "выбрать"}</span>
        </button>
      {/each}
    {:else}
      <div class="dna-field-hint">Page Bridge передаёт готовый компонент между страницами через именованный канал. Каналы появятся после первой передачи.</div>
    {/if}
  </div>
</div>
