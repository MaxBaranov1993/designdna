/* DesignAI Web — Inspector: панель свойств выделенного узла, модель pen.dev.
 * Секции как в Pencil: Alignment (6 кнопок + distribute), Position (X/Y/R + Absolute Position),
 * Flex Layout (direction none/vertical/horizontal, 3×3 alignment grid, gap, space-between/around,
 * padding [v,h]), Dimensions (W/H + Fill/Hug + Clip Content).
 *
 * Inspector.render(container, ctx):
 *   ctx.ir         — текущий IR
 *   ctx.selections — [{ref,label,node}]
 *   ctx.geo        — handle GeoEdit: setFrame, setFrameProps, frameOf, posOf, sizeOf, align, resetFrame
 */
(function (global) {
  "use strict";

  let cssDone = false;
  const CSS = `
  .pi { font-size:12px; color:var(--text,#cdd6f4); }
  .pi .pi-empty { color:var(--muted,#6c7086); font-size:11.5px; text-align:center; padding:28px 8px; }
  .pi .pi-type { font-size:11px; font-weight:700; color:var(--accent,#cba6f7); margin-bottom:8px;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .pi .pi-group { border-top:1px solid var(--border-soft,#313244); padding:9px 0; }
  .pi .pi-group:first-of-type { border-top:none; padding-top:2px; }
  .pi .pi-glabel { display:block; font-size:10px; font-weight:700; text-transform:uppercase;
    letter-spacing:.07em; color:var(--muted,#6c7086); margin-bottom:7px; }
  .pi .pi-row { display:flex; gap:6px; margin-bottom:6px; align-items:center; }
  .pi .pi-row:last-child { margin-bottom:0; }
  .pi .pi-field { display:flex; align-items:center; gap:5px; flex:1; min-width:0; }
  .pi .pi-field > label { font-size:10px; color:var(--muted,#6c7086); font-weight:700; flex:none; }
  .pi input[type=number], .pi input[type=text] { width:100%; min-width:0; background:var(--panel,#313244);
    border:1px solid var(--border,#45475a); color:var(--text,#cdd6f4); border-radius:6px; padding:4px 6px;
    font-size:11.5px; outline:none; font-variant-numeric:tabular-nums; }
  .pi input[type=color] { width:28px; height:24px; flex:none; background:transparent;
    border:1px solid var(--border,#45475a); border-radius:6px; padding:1px; cursor:pointer; }
  .pi-clear-color { width:24px; height:24px; flex:none; padding:0; font-size:14px; line-height:1; }
  .pi input:focus { border-color:var(--accent,#cba6f7); }
  .pi input:disabled { opacity:.4; }
  .pi select { width:100%; min-width:0; background:var(--panel,#313244); border:1px solid var(--border,#45475a);
    color:var(--text,#cdd6f4); border-radius:6px; padding:4px 6px; font-size:11.5px; outline:none; }
  .pi select:focus { border-color:var(--accent,#cba6f7); }
  .pi .pi-btnrow { display:flex; gap:4px; }
  .pi .pi-ibtn { flex:1; height:24px; display:inline-flex; align-items:center; justify-content:center;
    background:var(--panel,#313244); border:1px solid var(--border,#45475a); border-radius:6px;
    color:var(--text,#cdd6f4); cursor:pointer; font-size:11px; transition:.12s; padding:0; }
  .pi .pi-ibtn:hover { border-color:var(--accent,#cba6f7); }
  .pi .pi-ibtn.active { background:var(--accent,#cba6f7); border-color:var(--accent,#cba6f7);
    color:#fff; }
  .pi .pi-grid3 { display:grid; grid-template-columns:repeat(3,1fr); gap:4px; }
  .pi .pi-grid3 .pi-ibtn { height:22px; }
  .pi .pi-grid3 .pi-ibtn .dot { width:5px; height:5px; border-radius:50%; background:currentColor; }
  .pi .pi-check { display:flex; align-items:center; gap:7px; font-size:11px; color:var(--text,#cdd6f4);
    cursor:pointer; user-select:none; }
  .pi .pi-check input { accent-color:var(--accent,#cba6f7); width:13px; height:13px; cursor:pointer; }
  .pi .pi-checks { display:grid; grid-template-columns:1fr 1fr; gap:6px 8px; }
  .pi .pi-radio { display:flex; align-items:center; gap:7px; font-size:11px; cursor:pointer; user-select:none; }
  .pi .pi-radio input { accent-color:var(--accent,#cba6f7); width:13px; height:13px; cursor:pointer; }
  .pi .pi-wide { width:100%; }
  .pi .pi-sel-list { font-size:11px; color:var(--muted,#a6adc8); }
  .pi .pi-sel-list div { padding:1px 0; }
  `;

  function injectCSS() {
    if (cssDone) return;
    cssDone = true;
    const s = document.createElement("style");
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function getByPath(obj, path) {
    return path.split(".").reduce((o, k) => (o == null ? o : o[k]), obj);
  }

  function nodeOf(ir, ref) {
    if (ref.secIdx == null) return ir;
    if (ref.path == null) return ir.tree ? ir.tree[ref.secIdx] : null;
    return getByPath(ir.tree[ref.secIdx], ref.path);
  }

  function isContainer(ir, ref) {
    if (ref.secIdx == null || ref.path == null) return true;
    const n = nodeOf(ir, ref);
    return !!(n && (n.type === "card" || (n.children && n.children.length)));
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function fullHex(v, fallback) {
    const s = String(v || "").trim();
    if (/^#[0-9a-f]{3}$/i.test(s)) return "#" + s.slice(1).split("").map(c => c + c).join("").toLowerCase();
    if (/^#[0-9a-f]{6}$/i.test(s)) return s.toLowerCase();
    return fallback;
  }

  const FONT_CATALOG = global.DesignAIFontCatalog || null;
  const FONTS = FONT_CATALOG ? FONT_CATALOG.families : ["Inter", "Sora", "Manrope", "Playfair Display", "Space Grotesk", "DM Sans", "IBM Plex Mono", "Montserrat"];
  function fontOptionsHtml(selected, autoLabel) {
    const auto = autoLabel == null ? "" : `<option value="">${autoLabel}</option>`;
    if (!FONT_CATALOG || !FONT_CATALOG.groups) {
      return auto + FONTS.map(fnt => `<option value="${fnt}" ${selected === fnt ? "selected" : ""}>${fnt}</option>`).join("");
    }
    return auto + FONT_CATALOG.groups.map(group =>
      `<optgroup label="${esc(group.label)}">${group.fonts.map(fnt =>
        `<option value="${fnt}" ${selected === fnt ? "selected" : ""}>${fnt}</option>`).join("")}</optgroup>`
    ).join("");
  }

  /* ---------- рендер ---------- */

  function render(container, ctx) {
    injectCSS();
    const sels = ctx.selections || [];
    if (!sels.length) {
      container.innerHTML = `<div class="pi"><div class="pi-empty">Выделите элемент<br>на превью</div></div>`;
      return;
    }
    if (sels.length > 1) return renderMulti(container, ctx, sels);
    return renderSingle(container, ctx, sels[0]);
  }

  function alignButtonsHtml() {
    return `
      <div class="pi-btnrow">
        <button class="pi-ibtn" data-act="align-left" title="По левому краю">⫷</button>
        <button class="pi-ibtn" data-act="align-center-h" title="Центр по горизонтали">⫿</button>
        <button class="pi-ibtn" data-act="align-right" title="По правому краю">⫸</button>
      </div>
      <div class="pi-btnrow" style="margin-top:4px">
        <button class="pi-ibtn" data-act="align-top" title="По верхнему краю">⊤</button>
        <button class="pi-ibtn" data-act="align-center-v" title="Центр по вертикали">⊶</button>
        <button class="pi-ibtn" data-act="align-bottom" title="По нижнему краю">⊥</button>
      </div>
      <div class="pi-btnrow" style="margin-top:4px">
        <button class="pi-ibtn" data-act="distribute-h" title="Распределить по горизонтали">↔</button>
        <button class="pi-ibtn" data-act="distribute-v" title="Распределить по вертикали">↕</button>
      </div>`;
  }

  function renderMulti(container, ctx, sels) {
    let html = `<div class="pi"><div class="pi-type">Выделено: ${sels.length}</div>
      <div class="pi-group"><span class="pi-glabel">Alignment</span>${alignButtonsHtml()}</div>
      <div class="pi-group"><span class="pi-glabel">Элементы</span><div class="pi-sel-list">` +
      sels.map(s => `<div>${esc(s.label)}</div>`).join("") + `</div></div></div>`;
    container.innerHTML = html;
    wireActs(container, ctx);
  }

  function renderSingle(container, ctx, sel) {
    const ir = ctx.ir, geo = ctx.geo, ref = sel.ref;
    const f = (geo && geo.frameOf(ref)) || {};
    const node = nodeOf(ir, ref) || {};
    const isRoot = ref.secIdx == null;
    const cont = isContainer(ir, ref);
    const pos = (!isRoot && geo && geo.posOf) ? geo.posOf(ref) : null;
    const size = (geo && geo.sizeOf) ? geo.sizeOf(ref) : null;

    const x = typeof f.x === "number" ? f.x : (pos ? pos.x : "");
    const y = typeof f.y === "number" ? f.y : (pos ? pos.y : "");
    const rot = typeof f.rotation === "number" ? f.rotation : 0;
    const w = typeof f.width === "number" ? f.width : (size ? size.w : "");
    const h = typeof f.height === "number" ? f.height : (size ? size.h : "");

    let padV = "", padH = "";
    if (typeof f.padding === "number") { padV = f.padding; padH = f.padding; }
    else if (Array.isArray(f.padding) && f.padding.length >= 2) { padV = f.padding[0]; padH = f.padding[1]; }

    const dir = f.layout === "free" ? "free" : (f.direction === "row" ? "row" : "column");
    const justify = f.justify || "start";
    const align = f.align || "start";

    let html = `<div class="pi"><div class="pi-type">${esc(sel.label)}</div>`;

    /* Alignment */
    html += `<div class="pi-group"><span class="pi-glabel">Alignment</span>${alignButtonsHtml()}</div>`;

    /* Position */
    html += `<div class="pi-group"><span class="pi-glabel">Position</span>
      <div class="pi-row">
        <div class="pi-field"><label title="Тяни горизонтально — scrub; можно выражения: 100*2">X</label><input type="text" inputmode="decimal" data-pi="x" value="${x}" ${isRoot ? "disabled" : ""}></div>
        <div class="pi-field"><label title="Тяни горизонтально — scrub; можно выражения: 100*2">Y</label><input type="text" inputmode="decimal" data-pi="y" value="${y}" ${isRoot ? "disabled" : ""}></div>
      </div>
      <div class="pi-row">
        <div class="pi-field"><label>R</label><input type="text" inputmode="decimal" data-pi="rotation" value="${rot}" ${isRoot ? "disabled" : ""}></div>
        <div class="pi-field"></div>
      </div>
      ${isRoot ? "" : `<div class="pi-row"><label class="pi-check"><input type="checkbox" data-pi="absolute" ${f.absolute ? "checked" : ""}> Absolute Position</label></div>`}
      ${isRoot ? "" : `<div class="pi-row" title="Constraints: реакция на resize родителя">
        <div class="pi-field"><label>CH</label><select data-pi="constr-h">
          ${["left", "center", "right", "scale"].map(o => `<option value="${o}" ${f.constraints && f.constraints.h === o ? "selected" : ""}>${o}</option>`).join("")}
        </select></div>
        <div class="pi-field"><label>CV</label><select data-pi="constr-v">
          ${["top", "center", "bottom", "scale"].map(o => `<option value="${o}" ${f.constraints && f.constraints.v === o ? "selected" : ""}>${o}</option>`).join("")}
        </select></div>
      </div>`}
      </div>`;

    /* Flex Layout */
    if (cont) {
      html += `<div class="pi-group"><span class="pi-glabel">Flex Layout</span>
        <div class="pi-btnrow">
          <button class="pi-ibtn ${dir === "free" ? "active" : ""}" data-pi-dir="free" title="Без раскладки: дети по x/y (layout:none в pen.dev)">⊞</button>
          <button class="pi-ibtn ${dir === "column" ? "active" : ""}" data-pi-dir="column" title="Колонка (vertical)">↓</button>
          <button class="pi-ibtn ${dir === "row" ? "active" : ""}" data-pi-dir="row" title="Ряд (horizontal)">→</button>
        </div>
        <div class="pi-row" style="margin-top:6px"><label style="font-size:10px;color:var(--muted,#6c7086);font-weight:700">Alignment</label></div>
        <div class="pi-grid3">` +
        ["start", "center", "end"].map(a =>
          ["start", "center", "end"].map(j =>
            `<button class="pi-ibtn ${justify === j && align === a ? "active" : ""}" data-pi-ja="${j}|${a}" title="justify:${j} align:${a}"><span class="dot"></span></button>`
          ).join("")).join("") +
        `</div>
        <div class="pi-row" style="margin-top:6px">
          <div class="pi-field"><label>Gap</label><input type="text" inputmode="decimal" data-pi="gap" value="${typeof f.gap === "number" ? f.gap : ""}"></div>
        </div>
        <div class="pi-row"><label class="pi-radio"><input type="radio" name="pi-justify-${containerId(container)}" data-pi-justify="space-between" ${justify === "space-between" ? "checked" : ""}> Space Between</label></div>
        <div class="pi-row"><label class="pi-radio"><input type="radio" name="pi-justify-${containerId(container)}" data-pi-justify="space-around" ${justify === "space-around" ? "checked" : ""}> Space Around</label></div>
        <div class="pi-row" style="margin-top:6px">
          <div class="pi-field"><label>Pad↕</label><input type="text" inputmode="decimal" data-pi="padv" value="${padV}"></div>
          <div class="pi-field"><label>Pad↔</label><input type="text" inputmode="decimal" data-pi="padh" value="${padH}"></div>
        </div>
      </div>`;
    }

    /* Dimensions */
    html += `<div class="pi-group"><span class="pi-glabel">Dimensions</span>
      <div class="pi-row">
        <div class="pi-field"><label title="Можно выражения: 960/3">W</label><input type="text" inputmode="decimal" data-pi="width" value="${w}"></div>
        <div class="pi-field"><label title="Можно выражения: 960/3">H</label><input type="text" inputmode="decimal" data-pi="height" value="${h}"></div>
      </div>
      <div class="pi-checks" style="margin-top:6px">
        <label class="pi-check"><input type="checkbox" data-pi="fillw" ${f.width === "fill" ? "checked" : ""}> Fill Width</label>
        <label class="pi-check"><input type="checkbox" data-pi="fillh" ${f.height === "fill" ? "checked" : ""}> Fill Height</label>
        <label class="pi-check"><input type="checkbox" data-pi="hugw" ${f.width === "hug" ? "checked" : ""}> Hug Width</label>
        <label class="pi-check"><input type="checkbox" data-pi="hugh" ${f.height === "hug" ? "checked" : ""}> Hug Height</label>
        <label class="pi-check"><input type="checkbox" data-pi="clip" ${f.clip ? "checked" : ""}> Clip Content</label>
      </div>
      </div>`;

    /* Appearance */
    if (!isRoot) {
      const st = node.style || {};
      const fill = fullHex(st.background || node.fill, "#ffffff");
      const color = fullHex(st.color, "#111111");
      const stroke = fullHex(st.borderColor, "#e0e0e0");
      const radius = typeof st.borderRadius === "number" ? st.borderRadius : (typeof node.radius === "number" ? node.radius : "");
      const fontFamily = st.fontFamily || "";
      const fontSize = typeof st.fontSize === "number" ? st.fontSize : "";
      const fontWeight = typeof st.fontWeight === "number" ? st.fontWeight : "";
      const isText = node.type === "text" || node.type === "heading" || node.type === "button" || node.text != null || node.title != null;
      html += `<div class="pi-group"><span class="pi-glabel">Appearance</span>
        <div class="pi-row">
          <div class="pi-field"><label>Fill</label><input type="color" data-style-color="background" value="${fill}"><input type="text" data-style-text="background" value="${esc(st.background || node.fill || "")}" placeholder="auto"><button class="pi-ibtn pi-clear-color" data-clear-style="background" title="Transparent">×</button></div>
        </div>
        ${isText ? `<div class="pi-row">
          <div class="pi-field"><label>Text</label><input type="color" data-style-color="color" value="${color}"><input type="text" data-style-text="color" value="${esc(st.color || "")}" placeholder="auto"><button class="pi-ibtn pi-clear-color" data-clear-style="color" title="Transparent">×</button></div>
        </div>` : ""}
        <div class="pi-row">
          <div class="pi-field"><label>Line</label><input type="color" data-style-color="borderColor" value="${stroke}"><input type="text" data-style-text="borderColor" value="${esc(st.borderColor || "")}" placeholder="auto"><button class="pi-ibtn pi-clear-color" data-clear-style="borderColor" title="Transparent">×</button></div>
        </div>
        <div class="pi-row">
          <div class="pi-field"><label>R</label><input type="text" inputmode="decimal" data-style-num="borderRadius" value="${radius}" placeholder="0"></div>
          <div class="pi-field"><label>BW</label><input type="text" inputmode="decimal" data-style-num="borderWidth" value="${typeof st.borderWidth === "number" ? st.borderWidth : ""}" placeholder="0"></div>
        </div>
        ${isText ? `<div class="pi-row">
          <div class="pi-field"><label>Font</label><select data-style-select="fontFamily">${fontOptionsHtml(fontFamily, "Auto")}</select></div>
        </div>
        <div class="pi-row">
          <div class="pi-field"><label>Sz</label><input type="text" inputmode="decimal" data-style-num="fontSize" value="${fontSize}" placeholder="auto"></div>
          <div class="pi-field"><label>Wt</label><input type="text" inputmode="decimal" data-style-num="fontWeight" value="${fontWeight}" placeholder="auto"></div>
        </div>` : ""}
      </div>`;
    }

    if (!isRoot) {
      html += `<div class="pi-group"><button class="pi-ibtn pi-wide" data-act="reset-frame">Сбросить frame</button></div>`;
    }

    html += `</div>`;
    container.innerHTML = html;
    wireActs(container, ctx);
    wireSingle(container, ctx, sel);
  }

  let cid = 0;
  function containerId(el) {
    if (!el.__piId) el.__piId = ++cid;
    return el.__piId;
  }

  /** Безопасный калькулятор для числовых полей (W: 100*2): цифры и + - * / ( ) .
   *  Без eval — ручной рекурсивный парсер; возвращает null если не выражение. */
  function evalMath(expr) {
    const s = String(expr).replace(/\s+/g, "");
    if (!s || !/^[0-9+\-*/().]+$/.test(s)) return null;
    if (!/[+\-*/]/.test(s)) return null; // обычное число парсит Number
    let i = 0;
    function factor() {
      if (s[i] === "(") { i++; const v = expr2(); if (s[i] !== ")") return null; i++; return v; }
      if (s[i] === "-" || s[i] === "+") { const op = s[i++]; const v = factor(); return v == null ? null : (op === "-" ? -v : v); }
      const m = /^[0-9.]+/.exec(s.slice(i));
      if (!m) return null;
      i += m[0].length;
      const n = Number(m[0]);
      return Number.isFinite(n) ? n : null;
    }
    function term() {
      let v = factor();
      while (v != null && (s[i] === "*" || s[i] === "/")) {
        const op = s[i++]; const r = factor();
        if (r == null) return null;
        if (op === "*") v *= r;
        else { if (r === 0) return null; v /= r; }
      }
      return v;
    }
    function expr2() {
      let v = term();
      while (v != null && (s[i] === "+" || s[i] === "-")) {
        const op = s[i++]; const r = term();
        if (r == null) return null;
        v = op === "+" ? v + r : v - r;
      }
      return v;
    }
    const v = expr2();
    return (v != null && i === s.length) ? v : null;
  }

  /** Значение числового инпута: выражение → число; пусто → null; мусор → undefined. */
  function readNumInput(inp) {
    const raw = String(inp.value).trim();
    if (raw === "") return null;
    const m = evalMath(raw);
    if (m != null) return Math.round(m);
    const n = Number(raw);
    return Number.isFinite(n) ? Math.round(n) : undefined;
  }

  function applyNum(geo, key, v) {
    if (key === "x" || key === "y" || key === "width" || key === "height") {
      geo.setFrame({ [key]: v });
    } else if (key === "rotation") {
      geo.setFrameProps({ rotation: (v == null || v === 0) ? null : v });
    } else if (key === "gap") {
      geo.setFrameProps({ gap: v == null ? null : Math.max(0, v) });
    }
  }

  /* ---------- события ---------- */

  function wireActs(container, ctx) {
    const geo = ctx.geo;
    container.querySelectorAll("[data-act]").forEach(btn => {
      btn.addEventListener("click", () => {
        if (!geo) return;
        const map = {
          "align-left": "alignLeft", "align-center-h": "alignCenterH", "align-right": "alignRight",
          "align-top": "alignTop", "align-center-v": "alignCenterV", "align-bottom": "alignBottom",
          "distribute-h": "distributeH", "distribute-v": "distributeV", "reset-frame": "resetFrame",
        };
        const fn = map[btn.dataset.act];
        if (fn && geo[fn]) geo[fn]();
      });
    });
  }

  function wireSingle(container, ctx, sel) {
    const geo = ctx.geo;
    if (!geo) return;
    const ref = sel.ref;
    const f = () => geo.frameOf(ref) || {};

    container.querySelectorAll("[data-pi]").forEach(inp => {
      inp.addEventListener("change", () => {
        const key = inp.dataset.pi;
        const cur = f();
        if (key === "x" || key === "y" || key === "width" || key === "height" ||
            key === "rotation" || key === "gap") {
          // numeric math: «100*2», «960/3» и т.п. схлопываются в число
          const v = readNumInput(inp);
          if (v === undefined) return; // не распознано — не применяем
          if (v !== null) inp.value = String(v);
          applyNum(geo, key, v);
        } else if (key === "constr-h" || key === "constr-v") {
          const cur = f().constraints || {};
          const axis = key === "constr-h" ? "h" : "v";
          geo.setFrameProps({ constraints: Object.assign({}, cur, { [axis]: inp.value }) });
        } else if (key === "padv" || key === "padh") {
          const v = Math.max(0, readNumInput(container.querySelector('[data-pi="padv"]')) || 0);
          const h = Math.max(0, readNumInput(container.querySelector('[data-pi="padh"]')) || 0);
          geo.setFrameProps({ padding: v === h ? v : [v, h, v, h] });
        } else if (key === "absolute") {
          if (inp.checked) {
            const extra = {};
            if (typeof cur.x !== "number" || typeof cur.y !== "number") {
              const p = geo.posOf(ref);
              if (p) { extra.x = p.x; extra.y = p.y; }
            }
            geo.setFrameProps(Object.assign({ absolute: true }, extra));
          } else {
            geo.setFrameProps({ absolute: null });
          }
        } else if (key === "clip") {
          geo.setFrameProps({ clip: inp.checked ? true : null });
        } else if (key === "fillw") {
          geo.setFrameProps({ width: inp.checked ? "fill" : null });
        } else if (key === "hugw") {
          geo.setFrameProps({ width: inp.checked ? "hug" : null });
        } else if (key === "fillh") {
          geo.setFrameProps({ height: inp.checked ? "fill" : null });
        } else if (key === "hugh") {
          geo.setFrameProps({ height: inp.checked ? "hug" : null });
        }
      });
    });

    container.querySelectorAll("[data-style-color]").forEach(inp => {
      inp.addEventListener("input", () => {
        const key = inp.dataset.styleColor;
        const text = container.querySelector(`[data-style-text="${key}"]`);
        if (text) text.value = inp.value;
        geo.setNodeStyle({ [key]: inp.value });
      });
    });
    container.querySelectorAll("[data-style-text]").forEach(inp => {
      inp.addEventListener("change", () => {
        const key = inp.dataset.styleText;
        const value = String(inp.value || "").trim();
        geo.setNodeStyle({ [key]: (!value || value.toLowerCase() === "transparent") ? null : value });
      });
    });
    container.querySelectorAll("[data-clear-style]").forEach(btn => {
      btn.addEventListener("click", () => {
        const key = btn.dataset.clearStyle;
        const text = container.querySelector(`[data-style-text="${key}"]`);
        const color = container.querySelector(`[data-style-color="${key}"]`);
        if (text) { text.value = ""; text.dispatchEvent(new Event("change")); }
        if (color) color.value = "#ffffff";
        geo.setNodeStyle({ [key]: null });
      });
    });
    container.querySelectorAll("[data-style-num]").forEach(inp => {
      inp.addEventListener("change", () => {
        const key = inp.dataset.styleNum;
        const v = readNumInput(inp);
        if (v === undefined) return;
        if (v !== null) inp.value = String(Math.max(0, v));
        geo.setNodeStyle({ [key]: v == null ? null : Math.max(0, v) });
      });
    });
    container.querySelectorAll("[data-style-select]").forEach(sel => {
      sel.addEventListener("change", () => {
        geo.setNodeStyle({ [sel.dataset.styleSelect]: sel.value || null });
      });
    });

    // drag-scrub: тянуть лейбл горизонтально = менять значение (Shift — шаг 10)
    container.querySelectorAll(".pi-field").forEach(field => {
      const inp = field.querySelector("input[data-pi]");
      const lab = field.querySelector("label");
      if (!inp || !lab || inp.disabled) return;
      const key = inp.dataset.pi;
      if (!["x", "y", "width", "height", "rotation", "gap"].includes(key)) return;
      lab.style.cursor = "ew-resize";
      lab.addEventListener("pointerdown", (e) => {
        e.preventDefault();
        const base = readNumInput(inp);
        const start = typeof base === "number" ? base : 0;
        const sx = e.clientX;
        lab.setPointerCapture(e.pointerId);
        // пока scrub жив, владелец не перестраивает инспектор (иначе умрёт capture)
        global.Inspector.scrubbing = true;
        const move = (ev) => {
          const step = ev.shiftKey ? 10 : 1;
          const v = start + Math.round(ev.clientX - sx) * step;
          inp.value = String(v);
          // ctx.geo — живой getter: после ре-аттача geoedit ручка обновится сама
          applyNum(ctx.geo, key, v);
        };
        const up = () => {
          lab.removeEventListener("pointermove", move);
          global.Inspector.scrubbing = false;
        };
        lab.addEventListener("pointermove", move);
        lab.addEventListener("pointerup", up, { once: true });
      });
    });

    container.querySelectorAll("[data-pi-dir]").forEach(btn => {
      btn.addEventListener("click", () => {
        const d = btn.dataset.piDir;
        if (d === "free") geo.setFrameProps({ layout: "free" });
        else geo.setFrameProps({ layout: "auto", direction: d });
      });
    });

    container.querySelectorAll("[data-pi-ja]").forEach(btn => {
      btn.addEventListener("click", () => {
        const [j, a] = btn.dataset.piJa.split("|");
        geo.setFrameProps({ justify: j, align: a });
      });
    });

    container.querySelectorAll("[data-pi-justify]").forEach(radio => {
      radio.addEventListener("change", () => {
        if (radio.checked) geo.setFrameProps({ justify: radio.dataset.piJustify });
      });
    });
  }

  global.Inspector = { render };
})(window);
