<script lang="ts">
  /* Левая рейка инструментов DNA-редактора: 8 плоских кнопок без flyout-группы
   * (модель прототипа handoff). Хоткей — мелкой буквой в углу кнопки, активная —
   * фиолетовая (--dna-violet-l). data-tool — стабильный якорь тестов;
   * сами хоткеи обрабатывает controller.onKeydown. */
  import * as ctl from "./controller";
  import { editorUi } from "./state";
  import { cn } from "../lib/utils";

  type ToolDef = { tool: string; title: string; key: string };

  const TOOLS: ToolDef[] = [
    { tool: "select", title: "Select (Move)", key: "V" },
    { tool: "hand", title: "Hand (Pan)", key: "H" },
    { tool: "frame", title: "Frame", key: "F" },
    { tool: "rect", title: "Rectangle", key: "R" },
    { tool: "ellipse", title: "Ellipse", key: "O" },
    { tool: "line", title: "Line", key: "L" },
    { tool: "image", title: "Image", key: "I" },
    { tool: "text", title: "Text", key: "T" },
  ];

  const tool = $derived($editorUi.tool);
</script>

{#snippet toolIcon(name: string)}
  {#if name === "select"}
    <svg width="14" height="14" viewBox="0 0 16 16"><path d="M3 1l11 6.5-5 1.2L7.5 14z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" /></svg>
  {:else if name === "hand"}
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M5.2 7.2V4.6a1.1 1.1 0 0 1 2.2 0v1.4M7.4 5.6V3.8a1.1 1.1 0 0 1 2.2 0v2.4M9.6 6V4.4a1.1 1.1 0 0 1 2.2 0V9.2c0 2.2-1.5 3.8-3.6 3.8H7.6c-1.7 0-3.2-1-3.8-2.5L3 8.4a1.15 1.15 0 0 1 2-1.1l.2.4V7.2" /></svg>
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
  {#each TOOLS as t (t.tool)}
    <button
      class={cn("fe-rail-btn", tool === t.tool && "active")}
      data-tool={t.tool}
      data-tip={`${t.title} (${t.key})`}
      aria-label={`${t.title} (${t.key})`}
      aria-pressed={tool === t.tool}
      onclick={() => ctl.setTool(t.tool)}
    >
      {@render toolIcon(t.tool)}
      <span class="fe-key" aria-hidden="true">{t.key}</span>
    </button>
  {/each}
</div>
