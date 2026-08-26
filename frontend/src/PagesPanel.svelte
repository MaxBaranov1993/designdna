<script lang="ts">
  import Button from "./components/ui/Button.svelte";
  import Card from "./components/ui/Card.svelte";
  import CardContent from "./components/ui/CardContent.svelte";
  import CardHeader from "./components/ui/CardHeader.svelte";
  import CardTitle from "./components/ui/CardTitle.svelte";
  import { flow, flowActivePageId, flowChannels, flowNodes, flowPages } from "./flow/state";

  let pages = $derived($flowPages);
  let activePageId = $derived($flowActivePageId);
  let channelNames = $derived(Object.keys($flowChannels).filter((key) => $flowChannels[key]));

  const countNodes = (pageId: string) => {
    if (pageId === activePageId) return $flowNodes.length;
    return pages.find((page) => page.id === pageId)?.nodes.length || 0;
  };
</script>

<Card>
  <CardHeader>
    <div class="flex items-center justify-between gap-2">
      <CardTitle>Страницы</CardTitle>
      <div class="flex items-center gap-2">
        <Button variant="outline" size="sm" onclick={() => $flow.addVideoChainPage()} title="Параллельная ветка: Source Import rsale.net → Generator → Recorder → видео (MP4), AI через Z.AI без ключа">+ Видео</Button>
        <Button variant="outline" size="sm" onclick={() => $flow.createPage()}>+ Page</Button>
      </div>
    </div>
  </CardHeader>
  <CardContent class="space-y-3">
    <div class="page-list">
      {#each pages as page (page.id)}
        <div class={page.id === activePageId ? "page-row active" : "page-row"}>
          <button class="page-switch" onclick={() => $flow.switchPage(page.id)}>
            <span>{page.name}</span>
            <small>{countNodes(page.id)} nodes</small>
          </button>
          <input
            class="page-name"
            value={page.name}
            oninput={(e) => $flow.renamePage(page.id, e.currentTarget.value)}
            aria-label="Page name"
          />
          <button
            class="page-delete"
            disabled={pages.length <= 1}
            onclick={() => {
              if (window.confirm(`Удалить страницу "${page.name}"?`)) $flow.deletePage(page.id);
            }}
            title="Удалить страницу"
          >
            ×
          </button>
        </div>
      {/each}
    </div>
    <div class="page-channels">
      <div class="panel-label">Bridge channels</div>
      {#if channelNames.length}
        {#each channelNames as name (name)}
          <div class="channel-row">
            <span>{name}</span>
            <small>IR</small>
          </div>
        {/each}
      {:else}
        <p class="text-xs leading-relaxed text-muted-foreground">
          Создайте Page Bridge: Send на одной странице и Receive на другой с тем же channel.
        </p>
      {/if}
    </div>
  </CardContent>
</Card>
