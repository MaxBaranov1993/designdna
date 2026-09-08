<script lang="ts">
  import { flow, flowActivePageId, flowNodes, flowPages } from "../flow/state";
  import { confirmDialog } from "../flow/confirm";

  /* Карточка проекта (слева сверху): страница-селектор с dropdown, где
   * переключение, переименование (двойной клик), удаление и «+ Страница» /
   * «+ Видео-цепочка». Заменяет прежнюю левую колонку «Страницы». */
  const isDesktop = typeof window !== "undefined" && !!window.designDNA;
  let open = $state(false);
  let editingId = $state<string | null>(null);
  let pages = $derived($flowPages);
  let activePageId = $derived($flowActivePageId);
  let activePage = $derived(pages.find((page) => page.id === activePageId) || null);

  const countNodes = (pageId: string) => pageId === activePageId
    ? $flowNodes.length
    : pages.find((page) => page.id === pageId)?.nodes.length || 0;

  const closeOnOutside = (node: HTMLElement) => {
    const onDown = (event: MouseEvent) => {
      if (!node.contains(event.target as Node)) { open = false; editingId = null; }
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && open) { open = false; editingId = null; event.stopPropagation(); }
    };
    window.addEventListener("mousedown", onDown, true);
    window.addEventListener("keydown", onKey, true);
    return { destroy: () => { window.removeEventListener("mousedown", onDown, true); window.removeEventListener("keydown", onKey, true); } };
  };

  const removePage = (pageId: string, name: string, event: MouseEvent) => {
    event.stopPropagation();
    void confirmDialog({
      title: `Удалить страницу «${name}»?`,
      message: "Ноды и связи этой страницы будут удалены. Действие нельзя отменить.",
      confirmLabel: "Удалить",
      danger: true,
    }).then((ok) => {
      if (ok) $flow.deletePage(pageId);
    });
  };
</script>

<div class="float-card tl" use:closeOnOutside>
  {#if !isDesktop}
    <!-- В десктопе имя и окружение живут в полосе заголовка окна -->
    <span class="pc-name">DesignDNA</span>
    <span class="pc-badge">браузер</span>
    <span class="pc-vsep"></span>
  {/if}
  <div style="position: relative">
    <button class="pc-page" aria-haspopup="menu" aria-expanded={open} title="Страницы проекта" onclick={() => (open = !open)}>
      <span class="pc-page-name">{activePage?.name || "Страница"}</span>
      <span class="count">{$flowNodes.length}</span>
      <span class="chev">▼</span>
    </button>
    {#if open}
      <div class="pc-menu" role="menu" aria-label="Страницы">
        {#each pages as page (page.id)}
          <div
            class="pc-item"
            class:active={page.id === activePageId}
            role="menuitem"
            tabindex="0"
            onclick={() => { if (editingId !== page.id) { $flow.switchPage(page.id); open = false; } }}
            ondblclick={(event) => { event.stopPropagation(); editingId = page.id; }}
            onkeydown={(event) => { if (event.key === "Enter" && editingId !== page.id) { $flow.switchPage(page.id); open = false; } }}
          >
            <span class="dot"></span>
            {#if editingId === page.id}
              <input
                value={page.name}
                aria-label="Название страницы"
                oninput={(event) => $flow.renamePage(page.id, event.currentTarget.value)}
                onblur={() => (editingId = null)}
                onkeydown={(event) => { if (event.key === "Enter" || event.key === "Escape") { editingId = null; event.stopPropagation(); } }}
                onclick={(event) => event.stopPropagation()}
              />
            {:else}
              <span class="name">{page.name}</span>
              <span class="count">{countNodes(page.id)}</span>
            {/if}
            <button class="x" disabled={pages.length <= 1} title="Удалить страницу" aria-label="Удалить страницу" onclick={(event) => removePage(page.id, page.name, event)}>✕</button>
          </div>
        {/each}
        <span class="pc-sep"></span>
        <button class="pc-item add" role="menuitem" onclick={() => { $flow.createPage(); open = false; }}><span class="dot"></span><span class="name">+ Страница</span></button>
        <button class="pc-item add" role="menuitem" onclick={() => { $flow.addVideoChainPage(); open = false; }}><span class="dot"></span><span class="name">+ Видео-цепочка</span></button>
        <span class="pc-sep"></span>
        <div class="dna-field-hint" style="padding: 4px 8px 6px">Двойной клик — переименовать · Ctrl+PgUp / PgDn — переключить</div>
      </div>
    {/if}
  </div>
</div>
