<script lang="ts">
  import { onMount } from "svelte";
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
  let activated = $state(false);

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
    if (!activated) return;
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
    // renderIR сам работает на глубокой копии — второй clone здесь мегабайтный простой
    IRRenderer.renderIR(el, currentIr, activeViewport ? { viewport: activeViewport } : undefined);
    const frame = requestAnimationFrame(syncPreviewSize);
    return () => cancelAnimationFrame(frame);
  });

  onMount(() => {
    const el = outer;
    if (!el) return;
    // Keep node instances and rendered previews alive across pan/zoom. Delay
    // only the FIRST expensive IR render until its card approaches the screen.
    const visibility = typeof IntersectionObserver === "undefined" ? null : new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        activated = true;
        visibility?.disconnect();
      }
    }, { rootMargin: "500px" });
    if (visibility) visibility.observe(el);
    else activated = true;
    if (typeof ResizeObserver === "undefined") return () => visibility?.disconnect();
    // ResizeObserver callbacks run inside the browser's layout-delivery loop.
    // fitPreview/fitHeight write dimensions, so doing that synchronously can
    // recursively invalidate the observed outer box and flood Electron with
    // "ResizeObserver loop ... undelivered notifications". Coalesce the write
    // into the next frame, outside the observer delivery phase.
    let resizeFrame = 0;
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(resizeFrame);
      resizeFrame = requestAnimationFrame(syncPreviewSize);
    });
    ro.observe(el);
    return () => {
      visibility?.disconnect();
      ro.disconnect();
      cancelAnimationFrame(resizeFrame);
    };
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
