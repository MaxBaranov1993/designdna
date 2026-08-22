<script lang="ts">
  /* Design System Editor (ТЗ §12): библиотека foundations/компонентов/states/mock,
   * канвас мастер-компонента с viewport-переключением, инспектор, validation,
   * publish. Переиспользует IrPreview (тот же рендерер, что DNA Editor). */
    
  import type { DesignSystemNodeData } from "../flow/types";

  let { nodeId, onClose }: { nodeId: number; onClose: () => void } = $props();

  function nodeData(): DesignSystemNodeData & { document?: any } {
    const store = (window as any).__flowStore;
    const node = store?.getState?.().nodes.find((n: any) => Number(n.id) === Number(nodeId));
    return (node?.data || {}) as DesignSystemNodeData & { document?: any };
  }
  // reactive proxy поверх данных ноды (панель не владеет данными — пишет в ноду)
  let onUpdated: (() => void) | undefined = undefined;
  const data = $derived.by(() => nodeData());


  let activeTab = $state<"foundations" | "components" | "mock" | "validation">("components");
  let selectedKey = $state<string>("");
  let viewport = $state<"desktop" | "tablet" | "mobile">("desktop");
  let publishing = $state(false);
  let validationResult = $state<{ errors: Array<{ message: string }> } | null>(null);

  const doc = $derived(data.document || {});
  const components = $derived(Object.entries(doc.components || {}) as Array<[string, any]>);
  const foundations = $derived(doc.foundations || {});
  const mockSchemas = $derived(Object.entries(doc.mockData?.schemas || {}) as Array<[string, any]>);
  let selectedComp = $state<any>(null);
  let hasSelection = $state(false);
  let previewHost = $state<HTMLElement | null>(null);
  let currentIr: any = null;

  /** Прямой DOM-рендер выбранного мастер-компонента через IRRenderer —
   *  минуя Svelte-реактивность (производные от zustand-стора ненадёжны) */
  let rendererReady = false;
  async function loadRenderer() {
    if (rendererReady) return;
    // engine.js — IIFE-бандл рендерера, тот же что использует DNA Editor
    const existing = document.querySelector('script[data-engine]');
    if (!existing) {
      const script = document.createElement("script");
      script.src = "/static/flow/engine.js";
      script.dataset.engine = "1";
      document.head.appendChild(script);
      await new Promise((resolve) => { script.onload = resolve; script.onerror = resolve; });
    }
    rendererReady = !!(window as any).IRRenderer;
  }

  function renderSelected() {
    if (!previewHost) return;
    previewHost.innerHTML = "";
    if (!currentIr) { hasSelection = false; return; }
    hasSelection = true;
    const container = document.createElement("div");
    container.className = "ir-preview";
    container.style.cssText = "flex:1;min-height:0;overflow:auto;";
    previewHost.appendChild(container);
    try {
      const renderer = (window as any).IRRenderer;
      if (renderer) {
        renderer.renderIR(container, JSON.parse(JSON.stringify(currentIr)), { viewport });
      } else {
        container.textContent = "IRRenderer не загружен";
      }
    } catch (e) {
      container.textContent = "Ошибка рендера: " + String(e).slice(0, 100);
    }
  }

  function selectComponent(comp: any) {
    selectedComp = comp;
    currentIr = comp?.templateIr || null;
    hasSelection = !!comp;
    // рендер в следующем кадре — previewHost должен существовать
    requestAnimationFrame(async () => { await loadRenderer(); renderSelected(); });
  }

  const originIcon = (origin: string) => origin === "observed" ? "⬤" : origin === "inferred" ? "◐" : "◇";

  async function validate() {
    const resp = await fetch("/api/design-system/validate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document: doc }),
    });
    validationResult = await resp.json();
    activeTab = "validation";
  }

  async function publish() {
    publishing = true;
    try {
      const resp = await fetch("/api/design-system/publish", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document: doc }),
      });
      const result = await resp.json();
      if (result.errors?.length) {
        validationResult = result;
        activeTab = "validation";
        return;
      }
      data.status = "published";
      data.revision = result.document.revision;
      data.summary = result.summary;
      data.document = result.document;
      onUpdated?.();
    } finally {
      publishing = false;
    }
  }

  async function setDefault() {
    await fetch("/api/design-system/default", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ systemId: data.systemId }),
    });
    data.defaultSet = true;
    onUpdated?.();
  }

  function editMaster() {
    if (!selectedComp) return;
    // открыть DNA Editor на templateIr выбранного компонента (ТЗ §12.5 —
    // переиспользование renderer/geoedit/undo без второго canvas-engine)
    window.dispatchEvent(new CustomEvent("designdna:edit-ds-master", {
      detail: { systemId: data.systemId, componentKey: selectedComp.componentKey, templateIr: selectedComp.templateIr },
    }));
  }
</script>

<div class="ds-editor-overlay" role="dialog" aria-modal="true" aria-label="Design System Editor">
  <header class="ds-editor-top">
    <div>
      <strong>◈ {data.name}</strong>
      <span class="ds-editor-meta">
        {data.status === "published" ? `Published · v${data.revision}` : "Draft"}
        {data.defaultSet ? " · проект по умолчанию" : ""}
        · {components.length} компонентов
      </span>
    </div>
    <div class="ds-editor-actions">
      <button onclick={validate}>Validate</button>
      <button onclick={publish} disabled={publishing || data.status === "published"}>
        {publishing ? "…" : "Опубликовать ревизию"}
      </button>
      {#if data.status === "published" && !data.defaultSet}
        <button onclick={setDefault}>По умолчанию</button>
      {/if}
      <button class="close" onclick={() => onClose()}>✕</button>
    </div>
  </header>

  <div class="ds-editor-body">
    <aside class="ds-editor-lib">
      <nav>
        <button class:active={activeTab === "components"} onclick={() => (activeTab = "components")}>Components ({components.length})</button>
        <button class:active={activeTab === "foundations"} onclick={() => (activeTab = "foundations")}>Foundations</button>
        <button class:active={activeTab === "mock"} onclick={() => (activeTab = "mock")}>Mock Data ({mockSchemas.length})</button>
        <button class:active={activeTab === "validation"} onclick={() => (activeTab = "validation")}>Validation{validationResult?.errors?.length ? ` (${validationResult.errors.length})` : ""}</button>
      </nav>

      {#if activeTab === "components"}
        <ul class="ds-comp-list">
          {#each components as [key, comp] (key)}
            <li>
              <button class:active={selectedKey === key} onclick={() => { selectedKey = key; selectComponent(comp); }}>
                <span class="ds-origin" data-origin={comp.origin} title={comp.origin}>{originIcon(comp.origin)}</span>
                <span class="ds-comp-name">{comp.name}</span>
                <span class="ds-comp-cat">{comp.category}</span>
              </button>
            </li>
          {/each}
        </ul>
      {:else if activeTab === "foundations"}
        <div class="ds-foundations">
          <h4>Цвета (semantic)</h4>
          <div class="ds-swatches">
            {#each Object.entries(foundations.colors?.semantic || {}) as [name, hex] (name)}
              <span class="ds-swatch"><i style="background:{hex}"></i>{name}</span>
            {/each}
          </div>
          <h4>Типографика</h4>
          <p>{(foundations.typography?.families || []).join(", ") || "—"} · веса {(foundations.typography?.weights || []).join("/")}</p>
          <h4>Spacing</h4>
          <p>{Object.entries(foundations.spacing || {}).map(([k, v]) => `${k}=${v}`).join(" · ")}</p>
          <h4>Радиусы</h4>
          <p>{(foundations.radii || []).join(", ")}</p>
          <h4>Breakpoints</h4>
          <p>{Object.entries(foundations.breakpoints || {}).map(([k, v]) => `${k}≥${v}`).join(" · ")}</p>
        </div>
      {:else if activeTab === "mock"}
        <div class="ds-mock-list">
          {#each mockSchemas as [id, schema] (id)}
            <div class="ds-mock-item">
              <strong>{id}</strong>
              <small>{(schema.fields || []).map((f: any) => f.name).join(", ")}</small>
            </div>
          {/each}
        </div>
      {:else if activeTab === "validation"}
        <div class="ds-validation">
          {#if validationResult?.errors?.length}
            {#each validationResult.errors as err}
              <div class="ds-val-error">⛔ {err.message}</div>
            {/each}
          {:else if validationResult}
            <div class="ds-val-ok">✓ Блокирующих ошибок нет — можно публиковать</div>
          {:else}
            <p>Запустите Validate для проверки перед публикацией.</p>
          {/if}
        </div>
      {/if}
    </aside>

    <main class="ds-editor-canvas">
      <div class="ds-canvas-head" style:display={hasSelection ? "flex" : "none"}>
        <div class="ds-viewport-switch">
          {#each ["desktop", "tablet", "mobile"] as vp ("desktop-tablet-mobile")}
            <button class:active={viewport === vp} onclick={() => { viewport = vp as "desktop" | "tablet" | "mobile"; renderSelected(); }}>{vp}</button>
          {/each}
        </div>
        <button class="ds-edit-master" onclick={editMaster}>✎ Редактировать мастер</button>
      </div>
      <div class="ds-canvas-empty" style:display={hasSelection ? "none" : "grid"}>Выберите компонент слева</div>
      <div class="ds-canvas-preview" bind:this={previewHost}></div>
    </main>

    <aside class="ds-editor-inspector">
      <div style:display={hasSelection ? "block" : "none"}>
        <h3>{selectedComp.name}</h3>
        <dl>
          <dt>Key</dt><dd><code>{selectedComp.componentKey}</code></dd>
          <dt>Origin</dt><dd>{originIcon(selectedComp.origin)} {selectedComp.origin} {selectedComp.confidence != null ? `· ${Math.round(selectedComp.confidence * 100)}%` : ""}</dd>
          <dt>Category</dt><dd>{selectedComp.category}</dd>
          {#if selectedComp.description}<dt>Описание</dt><dd>{selectedComp.description}</dd>{/if}
          <dt>Props</dt><dd>{Object.keys(selectedComp.propsSchema || {}).join(", ") || "—"}</dd>
          <dt>Variants</dt><dd>{Object.keys(selectedComp.variants || {}).join(", ") || "—"}</dd>
          <dt>States</dt>
          <dd>
            {#each Object.entries((selectedComp.states || {}) as Record<string, any>) as [name, st]}
              <span class="ds-state" class:unconfirmed={st.origin === "generated" && !st.confirmed}>{name}{st.origin === "generated" && !st.confirmed ? "?" : ""}</span>
            {/each}
          </dd>
          {#if selectedComp.dependencies?.length}<dt>Зависимости</dt><dd>{selectedComp.dependencies.join(", ")}</dd>{/if}
          {#if selectedComp.provenance?.sourceBlock}<dt>Source</dt><dd>{selectedComp.provenance.sourceBlock}</dd>{/if}
        </dl>
      </div>
      <p class="ds-insp-empty" style:display={hasSelection ? "none" : "block"}>Инспектор компонента</p>
    </aside>
  </div>
</div>

<style>
  .ds-editor-overlay { position: fixed; inset: 0; z-index: 200; background: #0d0f14; display: flex; flex-direction: column; }
  .ds-editor-top { display: flex; justify-content: space-between; align-items: center; padding: 10px 16px; border-bottom: 1px solid #23263a; }
  .ds-editor-top strong { font-size: 14px; }
  .ds-editor-meta { margin-left: 10px; font-size: 11px; color: #8b8fa3; }
  .ds-editor-actions { display: flex; gap: 8px; }
  .ds-editor-actions button { padding: 5px 12px; border-radius: 6px; border: 1px solid #2a2e3d; background: #171923; color: #e2e5ee; cursor: pointer; font-size: 11.5px; }
  .ds-editor-actions button:disabled { opacity: .5; }
  .ds-editor-actions .close { border-color: transparent; font-size: 14px; padding: 5px 8px; }
  .ds-editor-body { display: flex; flex: 1; min-height: 0; }
  .ds-editor-lib { width: 240px; border-right: 1px solid #23263a; padding: 10px; overflow-y: auto; }
  .ds-editor-lib nav { display: flex; flex-direction: column; gap: 2px; margin-bottom: 12px; }
  .ds-editor-lib nav button { text-align: left; padding: 6px 10px; border-radius: 6px; border: none; background: transparent; color: #aab0c0; cursor: pointer; font-size: 12px; }
  .ds-editor-lib nav button.active { background: #23263a; color: #fff; }
  .ds-comp-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
  .ds-comp-list button { display: flex; align-items: center; gap: 8px; width: 100%; text-align: left; padding: 6px 8px; border-radius: 6px; border: none; background: transparent; color: #d5d9e4; cursor: pointer; font-size: 12px; }
  .ds-comp-list button.active { background: #23263a; }
  .ds-comp-list button:hover { background: #1c1f2b; }
  .ds-origin { font-size: 10px; }
  .ds-origin[data-origin="observed"] { color: #4ade80; }
  .ds-origin[data-origin="inferred"] { color: #fbbf24; }
  .ds-origin[data-origin="generated"] { color: #a78bfa; }
  .ds-comp-cat { margin-left: auto; font-size: 10px; color: #6b7080; }
  .ds-editor-canvas { flex: 1; display: flex; flex-direction: column; padding: 14px; overflow: auto; }
  .ds-canvas-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
  .ds-viewport-switch { display: flex; gap: 4px; }
  .ds-viewport-switch button { padding: 4px 10px; border-radius: 6px; border: 1px solid #2a2e3d; background: transparent; color: #8b8fa3; cursor: pointer; font-size: 11px; }
  .ds-viewport-switch button.active { color: #fff; border-color: #7c6cf0; }
  .ds-edit-master { padding: 4px 12px; border-radius: 6px; border: 1px solid #7c6cf0; background: transparent; color: #7c6cf0; cursor: pointer; font-size: 11px; }
  .ds-canvas-preview { flex: 1; display: flex; flex-direction: column; min-height: 0; }
  .ds-canvas-empty { flex: 1; display: grid; place-items: center; color: #4a4f60; font-size: 13px; }
  .ds-editor-inspector { width: 260px; border-left: 1px solid #23263a; padding: 14px; overflow-y: auto; }
  .ds-editor-inspector h3 { margin: 0 0 10px; font-size: 14px; }
  .ds-editor-inspector dl { display: grid; grid-template-columns: auto 1fr; gap: 4px 10px; font-size: 11.5px; }
  .ds-editor-inspector dt { color: #6b7080; }
  .ds-editor-inspector dd { margin: 0; color: #d5d9e4; }
  .ds-state { display: inline-block; margin: 1px 4px 1px 0; padding: 1px 6px; border-radius: 4px; border: 1px solid #2a2e3d; font-size: 10.5px; }
  .ds-state.unconfirmed { border-style: dashed; color: #a78bfa; }
  .ds-foundations h4 { margin: 10px 0 4px; font-size: 11px; color: #8b8fa3; text-transform: uppercase; }
  .ds-foundations p { margin: 0 0 8px; font-size: 11.5px; color: #d5d9e4; }
  .ds-swatches { display: flex; flex-wrap: wrap; gap: 6px; }
  .ds-swatch { display: inline-flex; align-items: center; gap: 4px; font-size: 10.5px; color: #aab0c0; }
  .ds-swatch i { width: 14px; height: 14px; border-radius: 3px; border: 1px solid #3a3f52; }
  .ds-mock-item { padding: 6px 0; border-bottom: 1px solid #1c1f2b; }
  .ds-mock-item strong { display: block; font-size: 11.5px; }
  .ds-mock-item small { color: #6b7080; font-size: 10.5px; }
  .ds-val-error { padding: 6px 8px; border-radius: 6px; background: #2d1517; color: #f87171; font-size: 11px; margin-bottom: 4px; }
  .ds-val-ok { padding: 6px 8px; border-radius: 6px; background: #14261a; color: #4ade80; font-size: 11px; }
  .ds-insp-empty { color: #4a4f60; font-size: 12px; }
</style>
