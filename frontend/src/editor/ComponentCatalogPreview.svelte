<script lang="ts">
  import { componentMasterPreview as normalizedPreview, selectedComponentMaster } from "../engine/componentMaster";
  import type { IRObject } from "../flow/types";

  let {
    component,
    variantKey = "default",
    viewport = "desktop",
  }: {
    component: Record<string, any>;
    variantKey?: string;
    viewport?: "desktop" | "tablet" | "mobile";
  } = $props();

  let host = $state<HTMLElement | null>(null);
  let renderVersion = 0;
  let visible = $state(false);

  function exactMaster(): IRObject | null {
    return selectedComponentMaster(component, variantKey);
  }

  async function ensureRenderer(): Promise<boolean> {
    if ((window as any).IRRenderer) return true;
    await import('../engine/index');
    return !!(window as any).IRRenderer;
  }

  async function render(master: IRObject | null, version: number) {
    if (!host) return;
    if (!master) { host.textContent = 'Исходный мастер варианта недоступен'; return; }
    const ready = await ensureRenderer();
    if (!host || version !== renderVersion) return;
    host.innerHTML = "";
    if (!ready) {
      host.textContent = "Preview unavailable";
      return;
    }
    try {
      (window as any).IRRenderer.renderIR(host, normalizedPreview(master), { viewport });
    } catch (error) {
      host.textContent = `Preview error: ${String(error).slice(0, 64)}`;
    }
  }

  $effect(() => {
    if (!host) return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) { visible = true; observer.disconnect(); }
    }, { rootMargin: '240px' });
    observer.observe(host);
    return () => observer.disconnect();
  });

  $effect(() => {
    const master = exactMaster();
    const currentHost = host;
    viewport;
    variantKey;
    component;
    if (!currentHost || !visible) return;
    const version = ++renderVersion;
    void render(master, version);
  });
</script>

<div class="catalog-preview-frame" aria-hidden="true">
  <div class="catalog-preview" bind:this={host}></div>
</div>

<style>
  .catalog-preview-frame {
    position: relative;
    height: 124px;
    overflow: hidden;
    border: 1px solid #282f3a;
    border-radius: 9px;
    background:
      linear-gradient(90deg, rgb(255 255 255 / 3%) 1px, transparent 1px),
      linear-gradient(rgb(255 255 255 / 3%) 1px, transparent 1px),
      #0d1016;
    background-size: 12px 12px;
  }
  .catalog-preview {
    width: 100%;
    min-height: 124px;
    color: #778195;
    font-size: 9px;
  }
</style>
