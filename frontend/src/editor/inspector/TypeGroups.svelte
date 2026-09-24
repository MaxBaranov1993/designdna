<script lang="ts">
  /* Type-specific группы инспектора — порт добавок editor.js renderInspector
   * поверх общего Inspector: responsive-статус (data-responsive-act/copy), текст
   * (data-textprop / data-el-prop), кнопка (data-node-style-*), артборд-токены
   * (data-color / data-font / data-token). События навешивает wireInspector.ts. */
  import * as ctl from "../controller";
  import FontOptions from "./FontOptions.svelte";
  import ColorPicker from "./ColorPicker.svelte";
  import { applyInspectorColor } from "./wireInspector";
  import { pageFlow } from "../../flow/state";
  import { useFlowStore } from "../../flow/store";
  import {
    COLOR_ROLE_LABELS, COLOR_ROLE_ORDER, TYPE_ROLE_LABELS, TYPE_ROLE_ORDER,
  } from "../../engine/tokensV2";
  import { kitColors as readSitePalette } from "../ui-kit-model";

  const flow = pageFlow();

  const COLOR_KEYS = ["primary", "secondary", "accent", "background", "surface", "text", "textMuted", "border"];
  const COLOR_LABELS: Record<string, string> = {
    primary: "Primary", secondary: "Secondary", accent: "Accent", background: "Background",
    surface: "Surface", text: "Text", textMuted: "Muted", border: "Border",
  };

  function toFullHex(hex: string): string {
    if (/^#[0-9a-fA-F]{6}$/.test(hex)) return hex;
    if (/^#[0-9a-fA-F]{3}$/.test(hex)) return "#" + [...hex.slice(1)].map((c) => c + c).join("");
    return "#888888";
  }

  const sess = ctl.getSession();
  const sel = sess && sess.sel.length === 1 ? sess.sel[0] : null;
  const node = sel?.node || {};
  const isRoot = sel ? sel.ref.secIdx == null : false;
  const t = sess?.ir?.tokens || {};
  const hasResponsive = !!(sess?.ir?.responsive && sess.ir.responsive.viewports);

  const canonical = sel ? (ctl.canonicalNode(sel.ref) || {}) : {};
  const override = sess && sess.viewport !== "desktop" ? (canonical.responsive || {})[sess.viewport] || null : null;
  const frameSource = override && override.frame ? sess!.viewport : "shared";
  const styleSource = override && override.style ? sess!.viewport : "shared";

  const st = node.style || {};
  const fill = toFullHex(st.background || node.fill || "");
  const textColor = toFullHex(st.color || "");
  const radius = typeof st.borderRadius === "number" ? st.borderRadius : typeof node.radius === "number" ? node.radius : "";
  const fontSize = typeof st.fontSize === "number" ? st.fontSize : "";
  const fontWeight = typeof st.fontWeight === "number" ? st.fontWeight : "";
  const colorKeys = COLOR_KEYS.filter((k) => t.color && t.color[k]);
  // Токены v2 — источник правды для документов после миграции; v1-группы
  // остаются для документов, у которых v2 ещё нет.
  const v2 = t.v2 && typeof t.v2 === "object" ? t.v2 : null;
  const v2ColorRoles = COLOR_ROLE_ORDER.filter((r) => v2?.color && v2.color[r]);
  const v2Type = v2?.type && v2.type.roles ? v2.type : null;
  const v2TypeRoles = v2Type ? TYPE_ROLE_ORDER.filter((r) => v2Type.roles[r]) : [];

  type KitSwatch = { name: string; hex: string; source: string };
  let colorTarget = $state<"background" | "color">("background");
  /** Local DS document cache — node.document is null after save until UI Kit panel opens. */
  let kitDocs = $state<Record<string, Record<string, any>>>({});
  let kitLoading = $state(false);
  const kitFetchStarted = new Set<string>();

  function isHexColor(value: unknown): value is string {
    return typeof value === "string" && /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(value.trim());
  }

  function dsDocKey(systemId: string, revision: number): string {
    return `${systemId}@${Number(revision) || 0}`;
  }

  /** Active page + other pages: DNA Editor often runs while DS document is unloaded. */
  function listDesignSystemRefs(): Array<{ systemId: string; revision: number; document?: Record<string, any> | null }> {
    const st = useFlowStore.getState();
    const out: Array<{ systemId: string; revision: number; document?: Record<string, any> | null }> = [];
    const seen = new Set<string>();
    const pushNode = (n: any) => {
      if (!n || n.type !== "designsystem") return;
      const data = n.data || {};
      const systemId = String(data.systemId || "");
      if (!systemId) return;
      const revision = Number(data.revision) || 0;
      const key = dsDocKey(systemId, revision);
      if (seen.has(key)) return;
      seen.add(key);
      out.push({ systemId, revision, document: data.document || null });
    };
    for (const n of st.nodes || []) pushNode(n);
    for (const page of st.pages || []) {
      if (page.id === st.activePageId) continue;
      for (const n of page.nodes || []) pushNode(n);
    }
    const def = st.designSystems?.defaultSystemRef;
    if (def?.systemId) {
      const key = dsDocKey(String(def.systemId), Number(def.revision) || 0);
      if (!seen.has(key)) {
        seen.add(key);
        out.push({ systemId: String(def.systemId), revision: Number(def.revision) || 0, document: null });
      }
    }
    return out;
  }

  // Pull Site palette documents the same way DesignSystemPanel does.
  $effect(() => {
    void $flow.nodes;
    void $flow.pages;
    void $flow.designSystems;
    const refs = listDesignSystemRefs();
    const missing = refs.filter((r) => !r.document && !kitDocs[dsDocKey(r.systemId, r.revision)]);
    if (!missing.length) {
      kitLoading = false;
      return;
    }
    let cancelled = false;
    kitLoading = true;
    void (async () => {
      for (const ref of missing) {
        if (cancelled) return;
        const key = dsDocKey(ref.systemId, ref.revision);
        if (kitFetchStarted.has(key) || kitDocs[key]) continue;
        kitFetchStarted.add(key);
        try {
          const resp = await fetch("/api/design-system/get", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ systemId: ref.systemId, revision: ref.revision }),
          });
          const got = await resp.json();
          if (!resp.ok || !got?.document) throw new Error(got?.error || got?.detail || `HTTP ${resp.status}`);
          if (cancelled) return;
          kitDocs = { ...kitDocs, [key]: got.document };
        } catch {
          kitFetchStarted.delete(key);
        }
      }
      if (!cancelled) kitLoading = false;
    })();
    return () => { cancelled = true; };
  });

  /** Same palette as UI Kit Overview «Site palette» (semantic || styleGuide.tokens). */
  const kitColors = $derived.by((): KitSwatch[] => {
    const out: KitSwatch[] = [];
    const seen = new Set<string>();
    const push = (name: string, value: string, source: string) => {
      if (!isHexColor(value)) return;
      const hex = toFullHex(value);
      const key = `${name.toLowerCase()}|${hex.toLowerCase()}`;
      if (seen.has(key)) return;
      seen.add(key);
      out.push({ name, hex, source });
    };

    for (const ref of listDesignSystemRefs()) {
      const key = dsDocKey(ref.systemId, ref.revision);
      const doc = (ref.document && typeof ref.document === "object" ? ref.document : null)
        || kitDocs[key]
        || null;
      if (!doc) continue;
      for (const color of readSitePalette(doc)) {
        push(color.label, String(color.value || "").trim(), "UI Kit");
      }
    }
    return out;
  });

  function applyKitColor(hex: string) {
    applyInspectorColor(colorTarget, hex);
  }
</script>

<!-- svelte-ignore a11y_label_has_associated_control -->
{#if sel && sess}
  {#if !isRoot}
    <div class="fe-responsive-status">
      {#if hasResponsive}
        <div class="fe-responsive-status-head">
          <span>{sess.viewport} · {sess.previewWidth} px</span>
          <span><span class="fe-source-tag">frame {frameSource}</span> <span class="fe-source-tag">style {styleSource}</span></span>
        </div>
      {/if}
      <div class="fe-responsive-actions">
        {#if hasResponsive}
          <button class="fe-btn" data-responsive-act="reset" aria-label="Reset override" disabled={sess.viewport === "desktop"}>Reset override</button>
          <button class="fe-btn" data-responsive-act="all" aria-label="Apply to all">Apply to all</button>
          <button class="fe-btn" data-responsive-copy="mobile" aria-label="Copy to mobile">Copy to M</button>
          <button class="fe-btn" data-responsive-copy="tablet" aria-label="Copy to tablet">Copy to T</button>
          <button class="fe-btn" data-responsive-copy="desktop" aria-label="Copy to desktop">Copy to D</button>
        {/if}
        <button class="fe-btn" data-act="stretch-width" aria-label="Stretch to full width">Stretch width</button>
        <button class="fe-btn" data-act="reset-frame" aria-label="Reset geometry">Reset frame</button>
      </div>
    </div>
  {/if}

  {#if node.type === "heading" || node.type === "text"}
    <div class="fe-insp-group"><span class="fe-glabel">Text</span>
      <textarea data-el-prop={node.text !== undefined ? "text" : "title"} value={node.text || node.title || ""}></textarea>
      <div class="fe-row" style="margin-top: 6px">
        <div class="fe-field"><label>Sz</label>
          <select data-el-prop="size" value={node.size || "md"}>
            <option value="xs">XS</option><option value="sm">SM</option><option value="md">MD</option>
            <option value="lg">LG</option><option value="xl">XL</option><option value="display">Display</option>
          </select>
        </div>
        <div class="fe-field"><label>≡</label>
          <select data-el-prop="align" value={node.align || "left"}>
            <option value="left">Left</option><option value="center">Center</option><option value="right">Right</option>
          </select>
        </div>
      </div>
      {#if node.type === "heading"}
        <div class="fe-row"><div class="fe-field"><label>H</label>
          <select data-el-prop="level" value={node.level || 2}>
            <option value="1">H1</option><option value="2">H2</option><option value="3">H3</option><option value="4">H4</option>
          </select>
        </div></div>
      {/if}
      <!-- Текстовый стиль: роль типографики tokens.v2 вместо кегля в каждом поле.
           «Auto» — роль по тегу (h1–h4 / p). Правка роли в корне меняет все элементы. -->
      <div class="fe-row" style="margin-top: 6px">
        <div class="fe-field"><label>Style</label>
          <select data-el-prop="typeRole" data-type-role-select value={node.typeRole || ""}>
            <option value="">Auto (by tag)</option>
            {#each TYPE_ROLE_ORDER as role (role)}
              <option value={role}>{TYPE_ROLE_LABELS[role]}</option>
            {/each}
          </select>
        </div>
        <button class="fe-btn" data-type-role-apply-all title="Assign this role to all matching elements on the page"
          disabled={!node.typeRole}>Apply to matching</button>
      </div>
    </div>
  {/if}

  {#if node.type === "button"}
    <div class="fe-insp-group"><span class="fe-glabel">Button</span>
      <div class="fe-field" style="margin-bottom: 6px"><label>Txt</label><input type="text" data-el-prop="text" value={node.text || ""} /></div>
      <div class="fe-field" style="margin-bottom: 6px"><label>Var</label>
        <select data-el-prop="variant" value={node.variant || "primary"}>
          <option value="primary">Primary</option><option value="secondary">Secondary</option>
          <option value="outline">Outline</option><option value="ghost">Ghost</option>
        </select>
      </div>

      <div class="fe-kit-colors">
        <div class="fe-kit-head">
          <span class="fe-kit-title">UI Kit · colors</span>
          <div class="fe-kit-targets" role="group" aria-label="Where to apply the token">
            <button type="button" class:active={colorTarget === "background"}
              onclick={() => colorTarget = "background"}>Fill</button>
            <button type="button" class:active={colorTarget === "color"}
              onclick={() => colorTarget = "color"}>Text</button>
          </div>
        </div>
        {#if kitColors.length}
          <div class="fe-kit-grid">
            {#each kitColors as swatch (swatch.name + swatch.hex)}
              <button
                type="button"
                class="fe-kit-swatch"
                title={`${swatch.name} · ${swatch.hex} (${swatch.source})`}
                aria-label={`Apply ${swatch.name} to ${colorTarget === "background" ? "Fill" : "Text"}`}
                onclick={() => applyKitColor(swatch.hex)}
              >
                <span class="fe-kit-chip" style="background: {swatch.hex}"></span>
                <span class="fe-kit-name">{swatch.name}</span>
              </button>
            {/each}
          </div>
          <p class="fe-kit-hint">Click a swatch to set the button {colorTarget === "background" ? "fill" : "text"} to a Site palette color.</p>
        {:else if kitLoading}
          <p class="fe-kit-empty">Loading Site palette from UI Kit…</p>
        {:else}
          <p class="fe-kit-empty">No Site palette colors yet. Add a Design System / UI Kit node (or a default DS) with a palette from Source.</p>
        {/if}
      </div>

      <div class="fe-color-pickers">
        <ColorPicker styleKey="background" label="Fill" hex={fill} raw={st.background || node.fill || ""} transparent={!st.background && !node.fill} />
        <ColorPicker styleKey="color" label="Text" hex={textColor} raw={st.color || ""} transparent={!st.color} />
      </div>
      <div class="fe-row">
        <div class="fe-field"><label>Font</label><select data-node-style-select="fontFamily" value={st.fontFamily || ""}><FontOptions autoLabel="Auto" /></select></div>
      </div>
      <div class="fe-row">
        <div class="fe-field"><label>Sz</label><input type="text" inputmode="decimal" data-node-style-num="fontSize" value={fontSize} placeholder="auto" /></div>
        <div class="fe-field"><label>Wt</label><input type="text" inputmode="decimal" data-node-style-num="fontWeight" value={fontWeight} placeholder="auto" /></div>
      </div>
      <div class="fe-row">
        <div class="fe-field"><label>R</label><input type="text" inputmode="decimal" data-node-style-num="borderRadius" value={radius} placeholder="auto" /></div>
      </div>
    </div>
  {/if}

  {#if isRoot}
    {#if v2ColorRoles.length}
      <div class="fe-insp-group"><span class="fe-glabel">Colors (v2 roles)</span>
        {#each v2ColorRoles as role (role)}
          <div class="fe-color-row"><label>{COLOR_ROLE_LABELS[role] || role}</label>
            <input type="color" data-color-v2={role} value={toFullHex(v2.color[role])} /><span class="fe-hex">{v2.color[role]}</span>
          </div>
        {/each}
      </div>
    {:else if t.color}
      <div class="fe-insp-group"><span class="fe-glabel">Colors (tokens)</span>
        {#each colorKeys as k (k)}
          <div class="fe-color-row"><label>{COLOR_LABELS[k] || k}</label>
            <input type="color" data-color={k} value={toFullHex(t.color[k])} /><span class="fe-hex">{t.color[k]}</span>
          </div>
        {/each}
      </div>
    {/if}
    {#if v2Type}
      <div class="fe-insp-group"><span class="fe-glabel">Typography (v2 roles)</span>
        <div class="fe-field" style="margin-bottom: 4px"><label>D</label>
          <select data-font-v2="display" value={v2Type.families?.display?.family || ""}><FontOptions /></select>
        </div>
        <div class="fe-field" style="margin-bottom: 4px"><label>B</label>
          <select data-font-v2="body" value={v2Type.families?.body?.family || ""}><FontOptions /></select>
        </div>
        <div class="fe-row">
          <div class="fe-field"><label>Base</label>
            <input type="text" inputmode="decimal" data-token-num="v2.type.base" value={v2Type.base} />
          </div>
          <div class="fe-field"><label>Ratio</label>
            <input type="text" inputmode="decimal" data-token-num="v2.type.ratio" value={v2Type.ratio} />
          </div>
        </div>
        <div class="fe-type-ladder">
          {#each v2TypeRoles as role (role)}
            <div class="fe-type-role">
              <span>{TYPE_ROLE_LABELS[role] || role}</span>
              <input type="text" inputmode="decimal" data-type-role={role} data-type-field="size" value={v2Type.roles[role].size} />
              <input type="text" inputmode="decimal" data-type-role={role} data-type-field="weight" value={v2Type.roles[role].weight} />
            </div>
          {/each}
        </div>
      </div>
    {:else if t.font}
      <div class="fe-insp-group"><span class="fe-glabel">Fonts</span>
        <div class="fe-field" style="margin-bottom: 4px"><label>D</label><select data-font="display" value={t.font.display.family}><FontOptions /></select></div>
        <div class="fe-field" style="margin-bottom: 4px"><label>B</label><select data-font="body" value={t.font.body.family}><FontOptions /></select></div>
        <div class="fe-field"><label>Sc</label>
          <select data-token="font.scale" value={t.font.scale || "default"}>
            <option value="compact">Compact</option><option value="default">Default</option><option value="spacious">Spacious</option>
          </select>
        </div>
      </div>
    {/if}
    <div class="fe-insp-group"><span class="fe-glabel">Shape and spacing</span>
      <div class="fe-row">
        <div class="fe-field"><label>R</label>
          <select data-token="radius.card" value={(t.radius && t.radius.card) || "md"}>
            <option value="none">None</option><option value="sm">SM</option><option value="md">MD</option>
            <option value="lg">LG</option><option value="xl">XL</option><option value="full">Full</option>
          </select>
        </div>
        <div class="fe-field"><label>Sp</label>
          <select data-token="spacing.section" value={(t.spacing && t.spacing.section) || "md"}>
            <option value="sm">SM</option><option value="md">MD</option><option value="lg">LG</option><option value="xl">XL</option>
          </select>
        </div>
      </div>
      <div class="fe-field"><label>Sh</label>
        <select data-token="shadow" value={t.shadow || "sm"}>
          <option value="none">None</option><option value="sm">SM</option><option value="md">MD</option><option value="lg">LG</option>
        </select>
      </div>
    </div>
  {/if}
{/if}

<style>
  /* Лестница ролей: кегль и вес рядом, чтобы иерархия читалась одним взглядом. */
  .fe-type-ladder { display: grid; gap: 3px; margin-top: 6px; }
  .fe-type-role { display: grid; grid-template-columns: 1fr 52px 52px; gap: 4px; align-items: center; }
  .fe-type-role > span { color: var(--dna-faint, #888); font-size: 10.5px; }
  .fe-type-role > input { min-width: 0; }

  .fe-kit-colors {
    margin: 8px 0 10px;
    padding: 8px;
    border: 1px solid hsl(var(--border));
    border-radius: 10px;
    background: hsl(var(--muted) / 0.35);
  }
  .fe-kit-head {
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
    margin-bottom: 8px;
  }
  .fe-kit-title {
    font-size: 10px; font-weight: 700; letter-spacing: .04em;
    text-transform: uppercase; color: hsl(var(--muted-foreground));
  }
  .fe-kit-targets { display: inline-flex; gap: 4px; }
  .fe-kit-targets button {
    height: 22px; padding: 0 8px; border-radius: 6px;
    border: 1px solid hsl(var(--border)); background: transparent;
    color: hsl(var(--muted-foreground)); font: 600 10.5px/1 Inter, system-ui, sans-serif;
    cursor: pointer;
  }
  .fe-kit-targets button.active {
    border-color: #0D99FF; background: rgba(13, 153, 255, .16); color: #fff;
  }
  .fe-kit-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(72px, 1fr)); gap: 6px;
  }
  .fe-kit-swatch {
    display: flex; flex-direction: column; align-items: stretch; gap: 4px;
    padding: 0; border: 0; background: transparent; cursor: pointer; text-align: left;
  }
  .fe-kit-chip {
    display: block; height: 28px; border-radius: 7px;
    border: 1px solid rgba(255,255,255,.12);
    box-shadow: inset 0 0 0 1px rgba(0,0,0,.25);
  }
  .fe-kit-swatch:hover .fe-kit-chip { outline: 2px solid #0D99FF; outline-offset: 1px; }
  .fe-kit-name {
    font-size: 9.5px; line-height: 1.2; color: hsl(var(--muted-foreground));
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .fe-kit-hint, .fe-kit-empty {
    margin: 8px 0 0; font-size: 10.5px; line-height: 1.35;
    color: hsl(var(--muted-foreground));
  }
  .fe-color-pickers { display: grid; gap: 6px; margin-bottom: 8px; }
</style>
