<script lang="ts">
  import { flow, flowActivePageId, flowChannels, flowNodes, flowPages } from "./flow/state";
  import { leftPanelOpen } from "./flow/ui";

  let editingId = $state<string | null>(null);
  let pages = $derived($flowPages);
  let activePageId = $derived($flowActivePageId);
  let channelNames = $derived(Object.keys($flowChannels).filter((key) => $flowChannels[key]));

  const countNodes = (pageId: string) => pageId === activePageId
    ? $flowNodes.length
    : pages.find((page) => page.id === pageId)?.nodes.length || 0;

  /* SEND/RECV — из реального mode нод Page Bridge, а не чередования строк */
  const channelHasSender = (name: string) => {
    const isSender = (node: { type?: string; data?: unknown }) => {
      if (node.type !== "pagebridge") return false;
      const data = node.data as { channel?: string; mode?: string } | undefined;
      return data?.channel === name && data?.mode === "send";
    };
    if ($flowNodes.some(isSender)) return true;
    return pages.some((page) => page.id !== activePageId && page.nodes.some(isSender));
  };
</script>

<aside class:closed={!$leftPanelOpen} class="dna-left">
  <div class="dna-left-head">
    <span class="dna-panel-cap">СТРАНИЦЫ</span>
    <div style="display:flex; gap:6px">
      <button class="dna-chip-sm" onclick={() => $flow.addVideoChainPage()}>+ Видео</button>
      <button class="dna-chip-sm" onclick={() => $flow.createPage()}>+ Page</button>
    </div>
  </div>
  <div class="dna-left-list">
    {#each pages as page (page.id)}
      <div class:active={page.id === activePageId} class="dna-page-card">
        <button class="dna-page-main" onclick={() => $flow.switchPage(page.id)} ondblclick={() => (editingId = page.id)}>
          <span class="dna-page-dot"></span>
          {#if editingId === page.id}
            <input
              class="dna-page-rename"
              value={page.name}
              aria-label="Название страницы"
              oninput={(event) => $flow.renamePage(page.id, event.currentTarget.value)}
              onblur={() => (editingId = null)}
              onkeydown={(event) => event.key === "Enter" && (editingId = null)}
              onclick={(event) => event.stopPropagation()}
            />
          {:else}
            <span class="dna-page-name">{page.name}</span>
          {/if}
          <span class="dna-page-count">{countNodes(page.id)}</span>
        </button>
        <button
          class="dna-page-x"
          disabled={pages.length <= 1}
          title="Удалить страницу"
          onclick={(event) => {
            event.stopPropagation();
            if (window.confirm(`Удалить страницу «${page.name}»?`)) $flow.deletePage(page.id);
          }}
        >✕</button>
      </div>
    {/each}
  </div>

  <div class="dna-left-cap dna-panel-cap">BRIDGE CHANNELS</div>
  <div class="dna-left-list">
    {#if channelNames.length}
      {#each channelNames as name (name)}
        {@const send = channelHasSender(name)}
        <div class="dna-bridge-row">
          <div class="dna-bridge-main">
            <span class:send class:recv={!send} class="dna-bridge-ic">{send ? "S" : "R"}</span>
            <span class="dna-bridge-name">{name}</span>
          </div>
          <span class="dna-badge" style="--badge-tone: {send ? '#FF691D' : '#9B5CFF'}">{send ? "SEND" : "RECV"}</span>
        </div>
      {/each}
    {:else}
      <p class="dna-bridge-empty">Page Bridge передаёт готовый компонент между страницами через именованный канал.</p>
    {/if}
  </div>

  <div class="dna-ir-card">
    <strong>Design IR</strong>
    <p>Единый источник истины для графа, DNA-редактора и генерации.</p>
  </div>
</aside>
