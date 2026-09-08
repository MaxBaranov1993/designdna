<script lang="ts">
  import { CTX_GROUPS } from "../flow/ports";
  import { requestNodeMenu } from "../flow/ui";

  /* Рельса 56px (Weavy): логотип, Поиск, категории библиотеки нод, поверхности
   * Design / Map / Agents, внизу «?» и профиль. Подписи 9.5px под иконками. */
  type Surface = "design" | "map" | "agents";
  let { surface, onselect }: { surface: Surface; onselect: (next: Surface) => void } = $props();

  const isDesktop = typeof window !== "undefined" && !!window.designDNA;

  /* Категории — стадии пайплайна из CTX_GROUPS; короткие подписи для рельсы. */
  const CATEGORY_META: Record<string, { short: string; icon: string }> = {
    "ИСТОЧНИК": { short: "Источник", icon: "M4 6h16M4 12h10M4 18h7" },
    "ГЕНЕРАЦИЯ": { short: "Генерация", icon: "M12 3v4m0 10v4M3 12h4m10 0h4M5.6 5.6l2.8 2.8m7.2 7.2 2.8 2.8M18.4 5.6l-2.8 2.8m-7.2 7.2-2.8 2.8" },
    "СБОРКА": { short: "Сборка", icon: "M4 5h16v5H4zM4 14h7v5H4zM13 14h7v5h-7z" },
    "КОНТРОЛЬ И ДВИЖЕНИЕ": { short: "Видео", icon: "M4 6h12a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2zm14 4 4-2v8l-4-2z" },
  };
  const categories = CTX_GROUPS.map((group) => ({ label: group.label, ...(CATEGORY_META[group.label] || { short: group.label, icon: "M4 12h16" }) }));

  const openCategory = (event: MouseEvent, label: string) => {
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    requestNodeMenu({ x: rect.right + 10, y: rect.top, group: label });
  };
  const openSearch = (event: MouseEvent) => {
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    requestNodeMenu({ x: rect.right + 10, y: rect.top });
  };
  const openCheatsheet = () => window.dispatchEvent(new CustomEvent("designdna:open-cheatsheet"));
</script>

<nav class="dna-rail" aria-label="Разделы">
  <div class="rail-logo" title="DesignDNA">D</div>

  <button class="rail-btn" title="Найти ноду или команду (Ctrl+K)" onclick={openSearch}>
    <span class="rail-ic"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5" /><path d="m20 20-4.2-4.2" /></svg></span>
    <span>Поиск</span>
  </button>

  <span class="rail-sep"></span>

  {#each categories as category (category.label)}
    <button class="rail-btn" title={`Ноды: ${category.label.toLocaleLowerCase("ru")}`} data-group={category.label} onclick={(event) => openCategory(event, category.label)}>
      <span class="rail-ic"><svg viewBox="0 0 24 24" aria-hidden="true"><path d={category.icon} /></svg></span>
      <span>{category.short}</span>
    </button>
  {/each}

  <span class="rail-sep"></span>

  <button class="rail-btn" class:active={surface === "design"} aria-pressed={surface === "design"} title="Граф и канвас" onclick={() => onselect("design")}>
    <span class="rail-ic"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="7" height="6" rx="1.5" /><rect x="14" y="14" width="7" height="6" rx="1.5" /><path d="M10 7h2a3 3 0 0 1 3 3v4" /></svg></span>
    <span>Граф</span>
  </button>
  {#if isDesktop}
    <button class="rail-btn" class:active={surface === "map"} aria-pressed={surface === "map"} title="Project Map — семантическая карта репозитория" onclick={() => onselect("map")}>
      <span class="rail-ic"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m3 6 6-2 6 2 6-2v14l-6 2-6-2-6 2zM9 4v14M15 6v14" /></svg></span>
      <span>Карта</span>
    </button>
    <button class="rail-btn" class:active={surface === "agents"} aria-pressed={surface === "agents"} title="Agents — чат с агентами и MCP" onclick={() => onselect("agents")}>
      <span class="rail-ic"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H9l-5 4z" /><path d="M8 9h8M8 12h5" /></svg></span>
      <span>Агенты</span>
    </button>
  {/if}

  <span class="rail-spacer"></span>

  <button class="rail-btn" title="Горячие клавиши (?)" onclick={openCheatsheet}>
    <span class="rail-ic"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7M12 17h.01" /></svg></span>
    <span>Помощь</span>
  </button>
  <div class="rail-avatar" title={isDesktop ? "Локальный профиль" : "Браузер"}>M</div>
</nav>
