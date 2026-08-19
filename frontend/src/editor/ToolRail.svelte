<script lang="ts">
  /* Левая рейка инструментов (модель pen.dev/Figma/OpenPencil): 5 кнопок,
   * фигуры собраны в flyout-группу под Прямоугольником (R): rect/ellipse/line/image.
   * data-tool на лидере группы — стабильный якорь тестов ([data-tool="rect"]);
   * пункты flyout несут data-tool + data-fly-item. Активный инструмент — из store;
   * если текущий инструмент из группы, лидер показывает его иконку (как в Figma). */
  import * as ctl from "./controller";
  import { editorUi } from "./state";
  import { cn } from "../lib/utils";

  type ToolDef = { tool: string; title: string };

  const SHAPE_GROUP: ToolDef[] = [
    { tool: "rect", title: "Прямоугольник (R)" },
    { tool: "ellipse", title: "Эллипс (O)" },
    { tool: "line", title: "Линия (L)" },
    { tool: "image", title: "Изображение (I)" },
  ];
  const SHAPE_TOOLS = SHAPE_GROUP.map((t) => t.tool);

  const SINGLE_TOOLS: ToolDef[] = [
    { tool: "select", title: "Выделение (V)" },
    { tool: "hand", title: "Рука — панорама (H)" },
    { tool: "frame", title: "Фрейм (F)" },
  ];

  const tool = $derived($editorUi.tool);

  let flyOpen = $state(false);
  let lastShape = $state("rect");
  let openTimer: ReturnType<typeof setTimeout> | null = null;
  let closeTimer: ReturnType<typeof setTimeout> | null = null;

  $effect(() => {
    return () => {
      if (openTimer) clearTimeout(openTimer);
      if (closeTimer) clearTimeout(closeTimer);
    };
  });

  /* хоткеи/внешние setTool синхронизируются: инструмент группы, включённый
   * мимо flyout, становится и отображаемым на лидере, и lastShape */
  $effect(() => {
    if (SHAPE_TOOLS.includes(tool)) lastShape = tool;
  });

  function scheduleOpen() {
    if (closeTimer) { clearTimeout(closeTimer); closeTimer = null; }
    if (openTimer) clearTimeout(openTimer);
    openTimer = setTimeout(() => (flyOpen = true), 200);
  }
  function scheduleClose() {
    if (openTimer) { clearTimeout(openTimer); openTimer = null; }
    if (closeTimer) clearTimeout(closeTimer);
    closeTimer = setTimeout(() => (flyOpen = false), 250);
  }

  function pickShape(t: string) {
    ctl.setTool(t);
    lastShape = t;
    flyOpen = false;
  }

  const displayShape = $derived(SHAPE_TOOLS.includes(tool) ? tool : lastShape);
  const displayDef = $derived(SHAPE_GROUP.find((t) => t.tool === displayShape) || SHAPE_GROUP[0]);
</script>

{#snippet toolIcon(name: string)}
  {#if name === "select"}
    <svg width="14" height="14" viewBox="0 0 16 16"><path d="M3 1l11 6.5-5 1.2L7.5 14z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" /></svg>
  {:else if name === "hand"}
    <svg width="14" height="14" viewBox="0 0 16 16"><path d="M8 2v12M2 8h12M8 2L6 4M8 2l2 2M8 14l-2-2M8 14l2 2M2 8l2-2M2 8l2 2M14 8l-2-2M14 8l-2 2" stroke="currentColor" stroke-width="1.1" fill="none" /></svg>
  {:else if name === "frame"}
    <svg width="14" height="14" viewBox="0 0 16 16"><path d="M5 1v14M11 1v14M1 5h14M1 11h14" stroke="currentColor" stroke-width="1.2" fill="none" /></svg>
  {:else if name === "rect"}
    <svg width="14" height="14" viewBox="0 0 16 16"><rect x="2.5" y="2.5" width="11" height="11" fill="none" stroke="currentColor" stroke-width="1.4" /></svg>
  {:else if name === "ellipse"}
    <svg width="14" height="14" viewBox="0 0 16 16"><ellipse cx="8" cy="8" rx="5.5" ry="4" fill="none" stroke="currentColor" stroke-width="1.4" /></svg>
  {:else if name === "line"}
    <svg width="14" height="14" viewBox="0 0 16 16"><path d="M3 13L13 3" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linecap="round" /></svg>
  {:else if name === "text"}
    <svg width="14" height="14" viewBox="0 0 16 16"><path d="M3 3h10M8 3v10" stroke="currentColor" stroke-width="1.4" fill="none" /></svg>
  {:else if name === "image"}
    <svg width="14" height="14" viewBox="0 0 16 16"><rect x="2" y="3" width="12" height="10" rx="1" fill="none" stroke="currentColor" stroke-width="1.2" /><circle cx="5.5" cy="6.5" r="1.2" fill="currentColor" /><path d="M2.5 12l3.5-3 2.5 2 3-2.5 2 1.5" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round" /></svg>
  {/if}
{/snippet}

<div class="fe-rail">
  {#each SINGLE_TOOLS.slice(0, 3) as t (t.tool)}
    <button
      class={cn("fe-rail-btn", tool === t.tool && "active")}
      data-tool={t.tool}
      data-tip={t.title}
      aria-label={t.title}
      onclick={() => ctl.setTool(t.tool)}
    >
      {@render toolIcon(t.tool)}
    </button>
  {/each}

  <div
    class="fe-rail-group"
    role="group"
    onmouseenter={scheduleOpen}
    onmouseleave={scheduleClose}
  >
    <button
      class={cn("fe-rail-btn", SHAPE_TOOLS.includes(tool) && "active")}
      data-tool="rect"
      data-flyout="shapes"
      data-tip={`${displayDef.title} — удерживайте/наведите для выбора фигуры`}
      aria-label={displayDef.title}
      onclick={() => ctl.setTool(displayShape)}
    >
      {@render toolIcon(displayDef.tool)}
      <span class="fe-fly-arrow">▾</span>
    </button>
    {#if flyOpen}
      <div
        class="fe-rail-flyout"
        role="group"
        onmouseenter={() => {
          if (closeTimer) { clearTimeout(closeTimer); closeTimer = null; }
        }}
        onmouseleave={scheduleClose}
      >
        {#each SHAPE_GROUP as t (t.tool)}
          <button
            class={cn("fe-rail-btn", tool === t.tool && "active")}
            data-tool={t.tool}
            data-fly-item={t.tool}
            data-tip={t.title}
            aria-label={t.title}
            onclick={() => pickShape(t.tool)}
          >
            {@render toolIcon(t.tool)}
          </button>
        {/each}
      </div>
    {/if}
  </div>

  <button
    class={cn("fe-rail-btn", tool === "text" && "active")}
    data-tool="text"
    data-tip="Текст (T)"
    aria-label="Текст (T)"
    onclick={() => ctl.setTool("text")}
  >
    {@render toolIcon("text")}
  </button>
</div>
