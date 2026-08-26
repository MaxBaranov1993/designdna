<script lang="ts">
  /* Type-specific группы инспектора — порт добавок editor.js renderInspector
   * поверх общего Inspector: responsive-статус (data-responsive-act/copy), текст
   * (data-textprop / data-el-prop), кнопка (data-node-style-*), артборд-токены
   * (data-color / data-font / data-token). События навешивает wireInspector.ts. */
  import * as ctl from "../controller";
  import FontOptions from "./FontOptions.svelte";

  const COLOR_KEYS = ["primary", "secondary", "accent", "background", "surface", "text", "textMuted", "border"];
  const COLOR_LABELS: Record<string, string> = {
    primary: "Primary", secondary: "Secondary", accent: "Accent", background: "Фон",
    surface: "Surface", text: "Текст", textMuted: "Muted", border: "Border",
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
        <button class="fe-btn" data-act="stretch-width" aria-label="Растянуть по ширине">Stretch width</button>
        <button class="fe-btn" data-act="reset-frame" aria-label="Сбросить геометрию">Reset frame</button>
      </div>
    </div>
  {/if}

  {#if node.type === "heading" || node.type === "text"}
    <div class="fe-insp-group"><span class="fe-glabel">Текст</span>
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
    </div>
  {/if}

  {#if node.type === "button"}
    <div class="fe-insp-group"><span class="fe-glabel">Кнопка</span>
      <div class="fe-field" style="margin-bottom: 6px"><label>Txt</label><input type="text" data-el-prop="text" value={node.text || ""} /></div>
      <div class="fe-field" style="margin-bottom: 6px"><label>Var</label>
        <select data-el-prop="variant" value={node.variant || "primary"}>
          <option value="primary">Primary</option><option value="secondary">Secondary</option>
          <option value="outline">Outline</option><option value="ghost">Ghost</option>
        </select>
      </div>
      <div class="fe-color-row"><label>Fill</label><input type="color" data-node-style-color="background" value={fill} /><span class="fe-hex">{st.background || ""}</span></div>
      <div class="fe-color-row"><label>Text</label><input type="color" data-node-style-color="color" value={textColor} /><span class="fe-hex">{st.color || ""}</span></div>
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
    {#if t.color}
      <div class="fe-insp-group"><span class="fe-glabel">Цвета (токены)</span>
        {#each colorKeys as k (k)}
          <div class="fe-color-row"><label>{COLOR_LABELS[k] || k}</label>
            <input type="color" data-color={k} value={toFullHex(t.color[k])} /><span class="fe-hex">{t.color[k]}</span>
          </div>
        {/each}
      </div>
    {/if}
    {#if t.font}
      <div class="fe-insp-group"><span class="fe-glabel">Шрифты</span>
        <div class="fe-field" style="margin-bottom: 4px"><label>D</label><select data-font="display" value={t.font.display.family}><FontOptions /></select></div>
        <div class="fe-field" style="margin-bottom: 4px"><label>B</label><select data-font="body" value={t.font.body.family}><FontOptions /></select></div>
        <div class="fe-field"><label>Sc</label>
          <select data-token="font.scale" value={t.font.scale || "default"}>
            <option value="compact">Compact</option><option value="default">Default</option><option value="spacious">Spacious</option>
          </select>
        </div>
      </div>
    {/if}
    <div class="fe-insp-group"><span class="fe-glabel">Форма и отступы</span>
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
