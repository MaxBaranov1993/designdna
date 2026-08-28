<script lang="ts">
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

  function exactMaster(): IRObject | null {
    const variant = (component?.variants || {})[variantKey] || (component?.variants || {}).default;
    if (variant?.masterRef !== "self" && variant?.masterIr) return variant.masterIr as IRObject;
    return (component?.masterIr || component?.templateIr || null) as IRObject | null;
  }

  function normalizedPreview(master: IRObject): IRObject {
    const clone = JSON.parse(JSON.stringify(master)) as Record<string, any>;
    const root = (clone.tree as Array<Record<string, any>> | undefined)?.[0];
    if (!root || root.type === "source-block") return clone;

    const rootFrame = root.frame && typeof root.frame === "object" ? root.frame : {};
    root.frame = { ...rootFrame, x: 0, y: 0 };
    const responsive = root.responsive && typeof root.responsive === "object" ? root.responsive : {};
    const wrapperResponsive: Record<string, any> = {};
    for (const [name, override] of Object.entries(responsive) as Array<[string, any]>) {
      if (!override?.frame) continue;
      override.frame = { ...override.frame, x: 0, y: 0 };
      wrapperResponsive[name] = {
        frame: {
          width: override.frame.width ?? rootFrame.width,
          height: override.frame.height ?? rootFrame.height,
          layout: "free",
        },
      };
    }
    const width = Number(rootFrame.width) || 320;
    const height = Number(rootFrame.height) || 120;
    return {
      version: clone.version || "1.1",
      tokens: clone.tokens,
      frame: { width, height, layout: "free" },
      tree: [{
        id: "catalog-master-preview",
        type: "source-block",
        variant: "component-master",
        frame: { width, height, layout: "free" },
        responsive: wrapperResponsive,
        props: {},
        children: [root],
      }],
    } as IRObject;
  }

  async function ensureRenderer(): Promise<boolean> {
    if ((window as any).IRRenderer) return true;
    const globalWindow = window as any;
    if (!globalWindow.__ddnaCatalogRendererPromise) {
      globalWindow.__ddnaCatalogRendererPromise = new Promise<void>((resolve) => {
        const existing = document.querySelector<HTMLScriptElement>('script[data-engine]');
        if (existing) {
          if ((window as any).IRRenderer) resolve();
          else {
            existing.addEventListener("load", () => resolve(), { once: true });
            existing.addEventListener("error", () => resolve(), { once: true });
          }
          return;
        }
        const script = document.createElement("script");
        script.src = "/static/flow/engine.js";
        script.dataset.engine = "1";
        script.addEventListener("load", () => resolve(), { once: true });
        script.addEventListener("error", () => resolve(), { once: true });
        document.head.appendChild(script);
      });
    }
    await globalWindow.__ddnaCatalogRendererPromise;
    return !!(window as any).IRRenderer;
  }

  async function render(master: IRObject | null, version: number) {
    if (!host || !master) return;
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
    const master = exactMaster();
    const currentHost = host;
    viewport;
    variantKey;
    component;
    if (!currentHost) return;
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
