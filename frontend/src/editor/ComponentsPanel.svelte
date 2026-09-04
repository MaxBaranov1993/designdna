<script lang="ts">
  /* Панель «Компоненты»: вставить мастер дизайн-системы в текущую страницу,
   * не выходя из редактора (у Open Design — только чат, у Pencil мастер
   * открывается отдельной нодой). Секция приходит с сервера уже с
   * sourceMeta.componentRef, поэтому strict-режим ДС принимает её как копию. */
  import * as ctl from "./controller";
  import { editorUi } from "./state";
  import { useFlowStore } from "../flow/store";
  import { toast } from "../flow/toast";

  type SystemRow = { systemId: string; name?: string; status?: string; revision?: number };
  type Component = { componentKey: string; name?: string; category?: string; variants?: Record<string, { label?: string }> };

  const open = $derived($editorUi.componentsOpen);
  let systems: SystemRow[] = $state([]);
  let systemId = $state("");
  let revision = $state(0);
  let components: Component[] = $state([]);
  let variantChoice: Record<string, string> = $state({});
  let loading = $state(false);
  let inserting = $state("");
  let error = $state("");

  function pickInitialSystem(): { systemId: string; revision: number } | null {
    const fst = useFlowStore.getState();
    const nodeId = $editorUi.nodeId;
    const node = nodeId == null ? null : fst.nodes.find((n) => Number(n.id) === nodeId);
    const master = node ? ((node.data as Record<string, unknown>)._dsMaster as { systemId?: string } | undefined) : undefined;
    const registry = fst.designSystems;
    const rows: SystemRow[] = (registry.systems || []).map((s) => ({
      systemId: s.systemId, name: s.name, status: s.status, revision: s.revision,
    }));
    systems = rows;
    if (master?.systemId && rows.some((r) => r.systemId === master.systemId)) {
      const row = rows.find((r) => r.systemId === master.systemId)!;
      return { systemId: row.systemId, revision: row.status === "published" ? Number(row.revision) || 0 : 0 };
    }
    const def = registry.defaultSystemRef?.systemId;
    const row = rows.find((r) => r.systemId === def) || rows[0];
    return row ? { systemId: row.systemId, revision: row.status === "published" ? Number(row.revision) || 0 : 0 } : null;
  }

  async function loadComponents() {
    if (!systemId) { components = []; return; }
    loading = true;
    error = "";
    try {
      const res = await fetch("/api/design-system/get", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ systemId, revision }),
      });
      const body = await res.json();
      if (!res.ok || body.error) throw new Error(body.error || `HTTP ${res.status}`);
      const doc = (body.document || body) as { components?: Record<string, Component>; reviewComponents?: Record<string, Component> };
      const list = Object.entries({ ...(doc.reviewComponents || {}), ...(doc.components || {}) })
        .map(([key, comp]) => ({ ...comp, componentKey: comp.componentKey || key }));
      components = list.sort((a, b) => String(a.category || "").localeCompare(String(b.category || "")) || String(a.name || a.componentKey).localeCompare(String(b.name || b.componentKey)));
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      components = [];
    } finally {
      loading = false;
    }
  }

  async function insert(comp: Component) {
    inserting = comp.componentKey;
    error = "";
    try {
      const res = await fetch("/api/design-system/component-section", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ systemId, revision, componentKey: comp.componentKey, variantKey: variantChoice[comp.componentKey] || "default" }),
      });
      const body = await res.json();
      if (!res.ok || body.error) throw new Error(body.error || `HTTP ${res.status}`);
      const ok = ctl.insertDesignSystemSection(body.section, body.meta);
      if (ok) toast(`Вставлен компонент «${body.name || comp.componentKey}»`, "ok");
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      inserting = "";
    }
  }

  $effect(() => {
    if (!open) return;
    const initial = pickInitialSystem();
    systemId = initial?.systemId || "";
    revision = initial?.revision || 0;
    void loadComponents();
  });

  function switchSystem(next: string) {
    const row = systems.find((r) => r.systemId === next);
    systemId = next;
    revision = row && row.status === "published" ? Number(row.revision) || 0 : 0;
    void loadComponents();
  }
</script>

{#if open}
  <div
    class="fe-locks-backdrop"
    role="presentation"
    onmousedown={(event) => {
      if (event.target === event.currentTarget) ctl.handleAct("close-components");
    }}
  >
    <div class="fe-locks-card fe-comps-card" role="dialog" aria-modal="true" aria-labelledby="comps-title" data-components-panel>
      <div class="fe-locks-kicker">Дизайн-система · компоненты</div>
      <h2 id="comps-title">Вставить компонент в страницу</h2>
      <p>Мастер добавится последней секцией с привязкой к дизайн-системе: strict-проверка примет его как точную копию, Quality Gate не тронет.</p>
      {#if systems.length}
        <label class="fe-comps-system">
          <span>Система</span>
          <select data-components-system value={systemId} onchange={(e) => switchSystem(e.currentTarget.value)}>
            {#each systems as row (row.systemId)}
              <option value={row.systemId}>{row.name || row.systemId} · {row.status === "published" ? `v${row.revision}` : "черновик"}</option>
            {/each}
          </select>
        </label>
      {:else}
        <div class="fe-rules-empty">В проекте нет дизайн-систем: соберите её из Source или загрузите JSON в ноду «Design System».</div>
      {/if}
      {#if loading}
        <div class="fe-rules-empty">Загружаю компоненты…</div>
      {:else if systemId && !components.length && !error}
        <div class="fe-rules-empty">В системе пока нет мастеров.</div>
      {:else if components.length}
        <div class="fe-comps-list">
          {#each components as comp (comp.componentKey)}
            <div class="fe-comps-row" data-component-key={comp.componentKey}>
              <div class="fe-comps-name"><b>{comp.name || comp.componentKey}</b><small>{comp.category || ""} · {comp.componentKey}</small></div>
              {#if comp.variants && Object.keys(comp.variants).length > 1}
                <select class="fe-comps-variant" value={variantChoice[comp.componentKey] || "default"} onchange={(e) => (variantChoice = { ...variantChoice, [comp.componentKey]: e.currentTarget.value })}>
                  {#each Object.entries(comp.variants) as [key, v] (key)}
                    <option value={key}>{v.label || key}</option>
                  {/each}
                </select>
              {/if}
              <button class="fe-btn primary" data-component-insert={comp.componentKey} disabled={!!inserting} onclick={() => void insert(comp)}>{inserting === comp.componentKey ? "…" : "Вставить"}</button>
            </div>
          {/each}
        </div>
      {/if}
      {#if error}<div class="fe-rules-error" role="alert">{error}</div>{/if}
      <div class="fe-locks-actions">
        <button class="fe-btn" data-act="close-components" onclick={() => ctl.handleAct("close-components")}>Закрыть</button>
      </div>
    </div>
  </div>
{/if}
