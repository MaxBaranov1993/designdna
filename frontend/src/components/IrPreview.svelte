<script lang="ts">
  import { onMount } from "svelte";
  import { deepClone } from "../flow/dataflow";
  import type { IRObject, SourceViewport } from "../flow/types";
  import { cn } from "../lib/utils";
  import { IRRenderer } from "../engine/renderer";

  let {
    ir,
    height = 180,
    empty = "IR появится после запуска",
    class: className = undefined,
    viewport = undefined,
    fitHeight = false,
    minHeight = 32,
    interactive = false,
    onclickcapture = undefined,
  }: {
    ir: IRObject | null;
    height?: number;
    empty?: string;
    class?: string;
    viewport?: SourceViewport;
    fitHeight?: boolean;
    minHeight?: number;
    interactive?: boolean;
    onclickcapture?: (event: MouseEvent) => void;
  } = $props();

  let outer: HTMLDivElement | null = null;
  let inner: HTMLDivElement | null = null;
  let measuredHeight = $state<number | null>(null);

  function syncPreviewSize() {
    const el = inner;
    if (!el) return;
    IRRenderer.fitPreview(el, null);
    if (!fitHeight || !ir) return;
    const renderedHeight = Number.parseFloat(el.style.height) || el.getBoundingClientRect().height;
    const nextHeight = Math.max(minHeight, Math.min(height, Math.ceil(renderedHeight)));
    if (measuredHeight !== nextHeight) measuredHeight = nextHeight;
  }

  $effect(() => {
    const el = inner;
    if (!el) return;
    const currentIr = ir;
    const vp = viewport;
    if (!currentIr) {
      el.innerHTML = "";
      measuredHeight = null;
      return;
    }

    const meta =
      currentIr.meta && typeof currentIr.meta === "object" && !Array.isArray(currentIr.meta)
        ? (currentIr.meta as Record<string, unknown>)
        : {};
    const activeViewport =
      vp ||
      (meta.activeViewport === "desktop" || meta.activeViewport === "tablet" || meta.activeViewport === "mobile"
        ? (meta.activeViewport as SourceViewport)
        : undefined);
    IRRenderer.renderIR(el, deepClone(currentIr), activeViewport ? { viewport: activeViewport } : undefined);
    const frame = requestAnimationFrame(syncPreviewSize);
    return () => cancelAnimationFrame(frame);
  });

  onMount(() => {
    const el = outer;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(syncPreviewSize);
    ro.observe(el);
    return () => ro.disconnect();
  });
</script>

<div
  bind:this={outer}
  class={cn("ir-preview", interactive && "ir-preview-interactive", className)}
  style:height="{(fitHeight && ir && measuredHeight !== null ? measuredHeight : height)}px"
  {onclickcapture}
>
  <div bind:this={inner} class="ir-preview-inner"></div>
  {#if !ir && empty}
    <div class="ir-preview-empty">{empty}</div>
  {/if}
</div>
