/* DesignAI Web — DNA Editor: полноэкранный редактор дизайна.
 * Открывается из ноды Edit по кнопке «Редактировать».
 * Тулбар + линейки + слои + канвас (pan/zoom/GeoEdit) + инспектор свойств.
 * Editor.open(node, onSave) — node.data.ir редактируется in-place.
 */
(function (global) {
  "use strict";

  let overlay = null;
  let state = null; // { ir, node, onSave, geo, history (IRHistory), sel, zoom, panX, panY, tool }

  function getByPath(obj, path) {
    return path.split(".").reduce((o, k) => (o == null ? o : o[k]), obj);
  }

  const FONT_FAMILIES = ["Inter", "Sora", "Manrope", "Playfair Display", "Space Grotesk", "DM Sans", "IBM Plex Mono", "Montserrat"];
  const COLOR_KEYS = ["primary", "secondary", "accent", "background", "surface", "text", "textMuted", "border"];
  const COLOR_LABELS = { primary: "Primary", secondary: "Secondary", accent: "Accent", background: "Фон", surface: "Surface", text: "Текст", textMuted: "Muted", border: "Border" };

  /* ---------- CSS ---------- */

  const CSS = `
  .dna-editor { position:fixed; inset:0; z-index:9999; display:flex; flex-direction:column;
    background:#1e1e2e; color:#cdd6f4; font-family:'Inter',system-ui,sans-serif; font-size:13px; }
  .dna-editor * { box-sizing:border-box; margin:0; padding:0; }

  /* тулбар */
  .fe-toolbar { display:flex; align-items:center; gap:6px; padding:6px 12px;
    background:#181825; border-bottom:1px solid #313244; flex:none; height:42px; }
  .fe-toolbar .fe-logo { font-weight:800; font-size:13px; color:#cba6f7; margin-right:8px; letter-spacing:-.02em; }
  .fe-tbtn { display:inline-flex; align-items:center; justify-content:center; width:30px; height:30px;
    border-radius:6px; border:none; background:transparent; color:#cdd6f4; cursor:pointer; font-size:14px; transition:.12s; }
  .fe-tbtn:hover { background:#313244; }
  .fe-tbtn.active { background:#45475a; color:#cba6f7; }
  .fe-tbtn:disabled { opacity:.35; cursor:default; }
  .fe-sep { width:1px; height:20px; background:#313244; margin:0 4px; }
  .fe-zoom { font-size:11px; color:#a6adc8; width:44px; text-align:center; font-variant-numeric:tabular-nums; }
  .fe-spacer { flex:1; }
  .fe-align-group { display:inline-flex; align-items:center; gap:2px; }
  .fe-btn { padding:5px 12px; border-radius:6px; border:1px solid #45475a; background:#313244;
    color:#cdd6f4; font:600 12px 'Inter',sans-serif; cursor:pointer; transition:.12s; }
  .fe-btn:hover { background:#45475a; }
  .fe-btn.primary { background:#cba6f7; border-color:#cba6f7; color:#1e1e2e; }
  .fe-btn.primary:hover { background:#b4befe; }
  .fe-btn.danger { border-color:#f38ba8; color:#f38ba8; }
  .fe-btn.danger:hover { background:rgba(243,139,168,.12); }

  /* основная раскладка */
  .fe-body { display:flex; flex:1; overflow:hidden; }

  /* слои */
  .fe-layers { width:220px; flex:none; background:#181825; border-right:1px solid #313244;
    overflow-y:auto; padding:8px 0; }
  .fe-layers-head { padding:4px 12px 8px; font-size:10px; font-weight:700; text-transform:uppercase;
    letter-spacing:.08em; color:#6c7086; }
  .fe-layer { display:flex; align-items:center; gap:6px; padding:4px 12px; cursor:pointer;
    font-size:12px; color:#bac2de; transition:.1s; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .fe-layer:hover { background:#313244; }
  .fe-layer.selected { background:#45475a; color:#cba6f7; }
  .fe-layer .fe-li { width:14px; text-align:center; font-size:10px; color:#6c7086; flex:none; }
  .fe-layer .fe-ln { overflow:hidden; text-overflow:ellipsis; flex:1; }
  .fe-layer .fe-lbtn { visibility:hidden; border:none; background:none; color:#9aa0b5; cursor:pointer;
    font-size:11px; padding:0 3px; flex:none; }
  .fe-layer:hover .fe-lbtn, .fe-layer.flag-hidden .fe-lbtn, .fe-layer.flag-locked .fe-lbtn { visibility:visible; }
  .fe-layer.flag-hidden .fe-ln { opacity:.45; text-decoration:line-through; }
  .fe-layer.flag-locked .fe-li { color:#e0af58; }
  .fe-search { margin:4px 8px 6px; width:calc(100% - 16px); background:#1e2030; border:1px solid #313244;
    color:#cdd6f4; border-radius:6px; padding:4px 8px; font-size:11px; }
  .fe-layer.depth-1 { padding-left:24px; }
  .fe-layer.depth-2 { padding-left:36px; }
  .fe-layer.depth-3 { padding-left:48px; }

  /* канвас */
  .fe-canvas { flex:1; position:relative; overflow:hidden; background:#11111b;
    background-image:radial-gradient(circle, #313244 1px, transparent 1px); background-size:20px 20px; }
  .fe-canvas-inner { position:absolute; top:0; left:0; transform-origin:0 0; }
  .fe-canvas-inner [class^="ir-"] { box-shadow:0 4px 40px rgba(0,0,0,.5); }

  /* линейки */
  .fe-ruler-h { position:absolute; top:0; left:24px; right:0; height:24px; background:#181825;
    border-bottom:1px solid #313244; z-index:10; overflow:hidden; }
  .fe-ruler-v { position:absolute; top:24px; left:0; bottom:0; width:24px; background:#181825;
    border-right:1px solid #313244; z-index:10; overflow:hidden; }
  .fe-ruler-corner { position:absolute; top:0; left:0; width:24px; height:24px; background:#181825;
    border-right:1px solid #313244; border-bottom:1px solid #313244; z-index:11; }
  .fe-ruler-h canvas, .fe-ruler-v canvas { display:block; }

  /* левая панель инструментов как в pen.dev */
  .fe-rail { position:absolute; left:34px; top:50%; transform:translateY(-50%); z-index:20;
    display:flex; flex-direction:column; gap:4px; background:#181825; border:1px solid #313244;
    border-radius:10px; padding:6px; box-shadow:0 4px 16px rgba(0,0,0,.4); }
  .fe-rail-btn { width:30px; height:30px; display:inline-flex; align-items:center; justify-content:center;
    background:transparent; border:none; border-radius:8px; color:#cdd6f4; cursor:pointer; }
  .fe-rail-btn:hover { background:#313244; }
  .fe-rail-btn.active { background:#cba6f7; color:#1e1e2e; }

  /* инспектор */
  .fe-inspector { width:260px; flex:none; background:#181825; border-left:1px solid #313244;
    overflow-y:auto; padding:12px; }
  .fe-insp-empty { color:#6c7086; font-size:12px; text-align:center; padding:40px 12px; }
  .fe-insp-group { margin-bottom:14px; }
  .fe-insp-group > .fe-glabel { display:block; font-size:10px; font-weight:700; text-transform:uppercase;
    letter-spacing:.07em; color:#6c7086; margin-bottom:6px; }
  .fe-row { display:flex; gap:6px; margin-bottom:6px; }
  .fe-field { display:flex; align-items:center; gap:5px; flex:1; }
  .fe-field label { font-size:10px; color:#6c7086; font-weight:700; width:14px; flex:none; }
  .fe-field input { width:100%; background:#313244; border:1px solid #45475a; color:#cdd6f4;
    border-radius:5px; padding:4px 6px; font-size:12px; outline:none; font-variant-numeric:tabular-nums; }
  .fe-field input:focus { border-color:#cba6f7; }
  .fe-field input:disabled { opacity:.4; }
  .fe-color-row { display:flex; align-items:center; gap:8px; margin-bottom:5px; }
  .fe-color-row label { flex:1; font-size:11px; color:#a6adc8; }
  .fe-color-row input[type=color] { width:28px; height:22px; border:1px solid #45475a; border-radius:4px;
    background:none; padding:1px; cursor:pointer; }
  .fe-color-row .fe-hex { font-family:monospace; font-size:10px; color:#6c7086; width:56px; }
  .fe-inspector select { width:100%; background:#313244; border:1px solid #45475a; color:#cdd6f4;
    border-radius:5px; padding:4px 6px; font-size:12px; outline:none; margin-bottom:6px; }
  .fe-inspector select:focus { border-color:#cba6f7; }
  .fe-inspector textarea { width:100%; background:#313244; border:1px solid #45475a; color:#cdd6f4;
    border-radius:5px; padding:5px 7px; font-size:12px; outline:none; resize:vertical; min-height:48px; }
  .fe-inspector textarea:focus { border-color:#cba6f7; }
  .fe-node-type { font-size:11px; color:#cba6f7; font-weight:700; margin-bottom:8px; }
  `;

  /* ---------- DOM ---------- */

  function ensureOverlay() {
    if (overlay) return;
    const style = document.createElement("style");
    style.textContent = CSS;
    document.head.appendChild(style);

    overlay = document.createElement("div");
    overlay.className = "dna-editor";
    overlay.style.display = "none";
    overlay.innerHTML = `
      <div class="fe-toolbar">
        <span class="fe-logo">✦ DNA Editor</span>
        <button class="fe-tbtn" data-act="zoom-out" title="Уменьшить">−</button>
        <span class="fe-zoom">100%</span>
        <button class="fe-tbtn" data-act="zoom-in" title="Увеличить">+</button>
        <button class="fe-tbtn" data-act="zoom-fit" title="Вписать">⊡</button>
        <span class="fe-sep"></span>
        <span class="fe-align-group" hidden>
          <button class="fe-tbtn" data-act="align-left" title="По левому краю">⫷</button>
          <button class="fe-tbtn" data-act="align-center-h" title="По центру по горизонтали">⫿</button>
          <button class="fe-tbtn" data-act="align-right" title="По правому краю">⫸</button>
          <span class="fe-sep"></span>
          <button class="fe-tbtn" data-act="align-top" title="По верхнему краю">⊤</button>
          <button class="fe-tbtn" data-act="align-center-v" title="По центру по вертикали">⊶</button>
          <button class="fe-tbtn" data-act="align-bottom" title="По нижнему краю">⊥</button>
          <span class="fe-sep"></span>
          <button class="fe-tbtn" data-act="distribute-h" title="Распределить по горизонтали">↔</button>
          <button class="fe-tbtn" data-act="distribute-v" title="Распределить по вертикали">↕</button>
          <span class="fe-sep"></span>
        </span>
        <button class="fe-tbtn" data-act="undo" title="Отменить (Ctrl+Z)">↩</button>
        <span class="fe-spacer"></span>
        <button class="fe-btn danger" data-act="close">Закрыть</button>
        <button class="fe-btn primary" data-act="save">💾 Сохранить</button>
      </div>
      <div class="fe-body">
        <div class="fe-layers"><div class="fe-layers-head">Слои</div><input class="fe-search" placeholder="Поиск слоёв…"><div class="fe-layers-tree"></div></div>
        <div class="fe-canvas">
          <div class="fe-ruler-corner"></div>
          <div class="fe-ruler-h"><canvas></canvas></div>
          <div class="fe-ruler-v"><canvas></canvas></div>
          <div class="fe-rail">
            <button class="fe-rail-btn active" data-tool="select" title="Выделение (V)"><svg width="14" height="14" viewBox="0 0 16 16"><path d="M3 1l11 6.5-5 1.2L7.5 14z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg></button>
            <button class="fe-rail-btn" data-tool="rect" title="Прямоугольник (R)"><svg width="14" height="14" viewBox="0 0 16 16"><rect x="2.5" y="2.5" width="11" height="11" fill="none" stroke="currentColor" stroke-width="1.4"/></svg></button>
            <button class="fe-rail-btn" data-tool="text" title="Текст (T)"><svg width="14" height="14" viewBox="0 0 16 16"><path d="M3 3h10M8 3v10" stroke="currentColor" stroke-width="1.4" fill="none"/></svg></button>
            <button class="fe-rail-btn" data-tool="frame" title="Фрейм (F)"><svg width="14" height="14" viewBox="0 0 16 16"><path d="M5 1v14M11 1v14M1 5h14M1 11h14" stroke="currentColor" stroke-width="1.2" fill="none"/></svg></button>
            <button class="fe-rail-btn" data-tool="hand" title="Рука — панорама (H)"><svg width="14" height="14" viewBox="0 0 16 16"><path d="M8 2v12M2 8h12M8 2L6 4M8 2l2 2M8 14l-2-2M8 14l2-2M2 8l2-2M2 8l2 2M14 8l-2-2M14 8l-2 2" stroke="currentColor" stroke-width="1.1" fill="none"/></svg></button>
          </div>
          <div class="fe-canvas-inner"></div>
        </div>
        <div class="fe-inspector"><div class="fe-insp-empty">Выделите элемент на канвасе или в слоях</div></div>
      </div>`;
    document.body.appendChild(overlay);
    wireToolbar();
    overlay.querySelector(".fe-rail").addEventListener("click", (e) => {
      const b = e.target.closest("[data-tool]");
      if (b) setTool(b.dataset.tool);
    });
    overlay.querySelector(".fe-search").addEventListener("input", (e) => {
      if (!state) return;
      state.layerQuery = e.target.value.trim();
      renderLayers();
    });
  }

  /* ---------- тулбар ---------- */

  function wireToolbar() {
    overlay.querySelector(".fe-toolbar").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-tool],[data-act]");
      if (!btn) return;
      if (btn.dataset.tool) setTool(btn.dataset.tool);
      else handleAct(btn.dataset.act);
    });
  }

  function setTool(tool) {
    state.tool = tool;
    overlay.querySelectorAll("[data-tool]").forEach(b => b.classList.toggle("active", b.dataset.tool === tool));
    const canvas = overlay.querySelector(".fe-canvas");
    canvas.style.cursor = tool === "hand" ? "grab" : "default";
    // синхронизируем geoedit: создание rect/text/frame и hand-панорама
    if (state.geo && state.geo.getTool() !== tool) state.geo.setTool(tool);
  }

  function handleAct(act) {
    if (act === "save") save();
    else if (act === "close") close();
    else if (act === "undo") undo();
    else if (act === "zoom-in") zoomBy(1.2);
    else if (act === "zoom-out") zoomBy(1 / 1.2);
    else if (act === "zoom-fit") zoomFit();
    else if (act.startsWith("align-") || act.startsWith("distribute-")) {
      if (!state.geo) return;
      const map = {
        "align-left": "alignLeft", "align-center-h": "alignCenterH", "align-right": "alignRight",
        "align-top": "alignTop", "align-center-v": "alignCenterV", "align-bottom": "alignBottom",
        "distribute-h": "distributeH", "distribute-v": "distributeV",
      };
      const fn = map[act];
      if (fn && state.geo[fn]) state.geo[fn]();
    }
  }

  /* ---------- открытие / закрытие ---------- */

  function open(node, onSave) {
    ensureOverlay();
    state = {
      ir: node.data.ir,
      node,
      onSave,
      geo: null,
      history: IRHistory.createHistory({ limit: 50 }),
      sel: [], // массив выделенных {ref, label, node}
      zoom: 1,
      panX: 40,
      panY: 40,
      tool: "select",
      layerFlags: {}, // refKey -> {hidden, locked}; сессия редактора, не часть IR
      layerQuery: "",
    };
    overlay.style.display = "flex";
    renderCanvas();
    renderLayers();
    renderInspector();
    attachCanvasEvents();
    setTool("select");
  }

  function save() {
    if (state.onSave) state.onSave(state.ir);
    close();
  }

  function close() {
    if (state && state.geo) { state.geo.destroy(); state.geo = null; }
    state = null;
    overlay.style.display = "none";
  }

  function pushHistory() {
    // ключ коалесценции — текущее выделение: серии быстрых правок
    // одного выделения (nudge стрелками) сливаются в одну запись
    const key = state.sel.map(s => s.ref.secIdx + ":" + (s.ref.path || "")).join(",");
    state.history.push(() => state.ir, key);
    updateUndoBtn();
  }

  function undo() {
    const snap = state.history.undo(() => state.ir);
    if (!snap) return;
    state.ir = snap;
    state.node.data.ir = state.ir;
    if (state.geo) { state.geo.destroy(); state.geo = null; }
    renderCanvas();
    renderLayers();
    state.sel = [];
    renderInspector();
    updateUndoBtn();
    updateAlignVisibility();
  }

  function updateUndoBtn() {
    const btn = overlay.querySelector('[data-act="undo"]');
    if (btn) btn.disabled = !state.history.canUndo();
  }

  function updateAlignVisibility() {
    const group = overlay.querySelector(".fe-align-group");
    if (group) group.hidden = state.sel.length < 2;
  }

  /* ---------- канвас ---------- */

  function renderCanvas() {
    const inner = overlay.querySelector(".fe-canvas-inner");
    IRRenderer.renderIR(inner, state.ir); // _frames применяет сам рендерер
    applyLayerFlags();
    applyTransform();
    attachGeoEdit();
  }

  /* ---------- флаги слоёв (hide/lock): сессия редактора, вне IR ---------- */

  function refKeyOf(ref) { return ref.secIdx + ":" + (ref.path || ""); }

  /** true если ref или любой предок (карточка/секция/артборд) несёт флаг kind. */
  function refFlag(ref, kind) {
    if (!state || !state.layerFlags) return false;
    const check = (si, p) => {
      const f = state.layerFlags[si + ":" + (p || "")];
      return !!(f && f[kind]);
    };
    let path = ref.path || null;
    while (path) {
      if (check(ref.secIdx, path)) return true;
      const segs = path.split(".");
      segs.pop(); segs.pop();
      path = segs.length ? segs.join(".") : null;
    }
    if (ref.secIdx != null && check(ref.secIdx, null)) return true;
    return check(null, null);
  }

  function domAtCanvas(ref) {
    const inner = overlay.querySelector(".fe-canvas-inner");
    if (ref.secIdx == null) return inner.querySelector('[class^="ir-"]');
    const secEl = inner.querySelector(`[data-ir-sec="${ref.secIdx}"]`);
    if (!secEl) return null;
    if (ref.path == null) return secEl;
    return secEl.querySelector(`[data-ir-path="${ref.path}"]`) ||
           secEl.querySelector(`[data-ir-path^="${ref.path}"]`);
  }

  /** hidden-слои убираются с канваса; locked живут, но не выделяются (geoedit.isLocked). */
  function applyLayerFlags() {
    if (!state || !state.layerFlags) return;
    for (const [key, f] of Object.entries(state.layerFlags)) {
      const [si, path] = key.split(":");
      const el = domAtCanvas({ secIdx: si === "null" ? null : Number(si), path: path || null });
      if (el) el.style.display = f.hidden ? "none" : "";
    }
  }

  function toggleLayerFlag(ref, kind) {
    const key = refKeyOf(ref);
    const f = state.layerFlags[key] || (state.layerFlags[key] = {});
    f[kind] = !f[kind];
    if (f[kind] && state.sel.some(s => refKeyOf(s.ref) === key) && state.geo) state.geo.clear();
    applyLayerFlags();
    renderLayers();
  }

  function applyTransform() {
    const inner = overlay.querySelector(".fe-canvas-inner");
    inner.style.transform = `translate(${state.panX}px, ${state.panY}px) scale(${state.zoom})`;
    const canvas = overlay.querySelector(".fe-canvas");
    canvas.style.backgroundSize = `${20 * state.zoom}px ${20 * state.zoom}px`;
    canvas.style.backgroundPosition = `${state.panX}px ${state.panY}px`;
    overlay.querySelector(".fe-zoom").textContent = Math.round(state.zoom * 100) + "%";
    drawRulers();
  }

  function drawRulers() {
    const canvas = overlay.querySelector(".fe-canvas");
    const cr = canvas.getBoundingClientRect();
    const rulerH = overlay.querySelector(".fe-ruler-h canvas");
    const rulerV = overlay.querySelector(".fe-ruler-v canvas");
    const w = Math.ceil(cr.width - 24), h = Math.ceil(cr.height - 24);
    if (w <= 0 || h <= 0) return;
    rulerH.width = w; rulerH.height = 24;
    rulerV.width = 24; rulerV.height = h;
    const ctxH = rulerH.getContext("2d");
    const ctxV = rulerV.getContext("2d");
    ctxH.clearRect(0, 0, w, 24);
    ctxV.clearRect(0, 0, 24, h);
    ctxH.fillStyle = "#6c7086"; ctxH.font = "9px Inter, sans-serif"; ctxH.textBaseline = "top";
    ctxV.fillStyle = "#6c7086"; ctxV.font = "9px Inter, sans-serif"; ctxV.textBaseline = "middle";

    const z = state.zoom;
    // адаптивный шаг: при малом зуме показываем только крупные деления
    const minorStep = z >= 0.5 ? 8 : z >= 0.25 ? 16 : 32;
    const majorStep = z >= 0.5 ? 100 : z >= 0.25 ? 200 : 400;
    const offsetX = state.panX - 24; // сдвиг линейки относительно канваса (24px = ширина вертикальной линейки)
    const offsetY = state.panY - 24;

    // горизонтальная линейка
    const startX = Math.floor(-offsetX / z / minorStep) * minorStep;
    const endX = Math.ceil((w - offsetX) / z / minorStep) * minorStep;
    for (let px = startX; px <= endX; px += minorStep) {
      const screenX = px * z + offsetX;
      if (screenX < 0 || screenX > w) continue;
      const isMajor = px % majorStep === 0;
      ctxH.strokeStyle = isMajor ? "#a6adc8" : "#45475a";
      ctxH.beginPath();
      ctxH.moveTo(screenX, isMajor ? 0 : 16);
      ctxH.lineTo(screenX, 24);
      ctxH.stroke();
      if (isMajor) ctxH.fillText(String(px), screenX + 2, 2);
    }

    // вертикальная линейка
    const startY = Math.floor(-offsetY / z / minorStep) * minorStep;
    const endY = Math.ceil((h - offsetY) / z / minorStep) * minorStep;
    for (let py = startY; py <= endY; py += minorStep) {
      const screenY = py * z + offsetY;
      if (screenY < 0 || screenY > h) continue;
      const isMajor = py % majorStep === 0;
      ctxV.strokeStyle = isMajor ? "#a6adc8" : "#45475a";
      ctxV.beginPath();
      ctxV.moveTo(isMajor ? 0 : 16, screenY);
      ctxV.lineTo(24, screenY);
      ctxV.stroke();
      if (isMajor) {
        ctxV.save();
        ctxV.translate(10, screenY + 2);
        ctxV.rotate(-Math.PI / 2);
        ctxV.fillText(String(py), 0, 0);
        ctxV.restore();
      }
    }
  }

  function zoomBy(factor) {
    const canvas = overlay.querySelector(".fe-canvas");
    const r = canvas.getBoundingClientRect();
    const cx = r.width / 2, cy = r.height / 2;
    const z = Math.min(3, Math.max(0.15, state.zoom * factor));
    state.panX = cx - (cx - state.panX) * (z / state.zoom);
    state.panY = cy - (cy - state.panY) * (z / state.zoom);
    state.zoom = z;
    applyTransform();
  }

  function zoomFit() {
    const inner = overlay.querySelector(".fe-canvas-inner");
    const irEl = inner.querySelector('[class^="ir-"]');
    if (!irEl) return;
    const canvas = overlay.querySelector(".fe-canvas");
    const cr = canvas.getBoundingClientRect();
    const iw = irEl.offsetWidth || 960, ih = irEl.offsetHeight || 600;
    const z = Math.min(1, Math.min((cr.width - 60) / iw, (cr.height - 60) / ih));
    state.zoom = Math.max(0.15, z);
    state.panX = (cr.width - iw * state.zoom) / 2;
    state.panY = (cr.height - ih * state.zoom) / 2;
    applyTransform();
  }

  function attachCanvasEvents() {
    const canvas = overlay.querySelector(".fe-canvas");
    // панорама
    canvas.addEventListener("pointerdown", (e) => {
      if (state.tool !== "hand" && e.button !== 1) return;
      if (e.target.closest('[class^="ir-"]') || e.target.closest('.fe-rail')) return;
      e.preventDefault();
      canvas.style.cursor = "grabbing";
      const sx = e.clientX, sy = e.clientY, px = state.panX, py = state.panY;
      const move = (ev) => { state.panX = px + ev.clientX - sx; state.panY = py + ev.clientY - sy; applyTransform(); };
      const up = () => { canvas.style.cursor = state.tool === "hand" ? "grab" : "default"; window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up, { once: true });
    });
    // зум колесом
    canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
      const r = canvas.getBoundingClientRect();
      const mx = e.clientX - r.left, my = e.clientY - r.top;
      const z = Math.min(3, Math.max(0.15, state.zoom * factor));
      state.panX = mx - (mx - state.panX) * (z / state.zoom);
      state.panY = my - (my - state.panY) * (z / state.zoom);
      state.zoom = z;
      applyTransform();
    }, { passive: false });
  }

  /** Адаптер: «скролл» руки = панорама канваса (panX/panY). */
  const panAdapter = {
    get scrollLeft() { return state ? -state.panX : 0; },
    set scrollLeft(v) { if (state) { state.panX = -v; applyTransform(); } },
    get scrollTop() { return state ? -state.panY : 0; },
    set scrollTop(v) { if (state) { state.panY = -v; applyTransform(); } },
  };

  function attachGeoEdit() {
    if (state.geo) state.geo.destroy();
    const inner = overlay.querySelector(".fe-canvas-inner");
    const previewEl = inner;
    state.geo = GeoEdit.attach({
      previewEl,
      tools: true,
      escapeViaHandle: true, // Esc обрабатываем сами через geo.consumeEscape()
      isLocked: (ref) => refFlag(ref, "locked"), // locked-слои не выделяются на канвасе
      scrollEl: panAdapter,
      onToolChange: (t) => { if (state && state.tool !== t) setTool(t); },
      getIR: () => state.ir,
      getScale: () => {
        const irEl = inner.querySelector('[class^="ir-"]');
        if (!irEl) return 1;
        const dw = Number(irEl.dataset.designWidth) || IRRenderer.DESIGN_WIDTH;
        const w = irEl.getBoundingClientRect().width;
        return w > 0 ? w / dw : 1;
      },
      onCommit: () => pushHistory(),
      onMutated: () => {
        const savedRefs = state.sel.map(s => s.ref);
        IRRenderer.renderIR(inner, state.ir);
        applyLayerFlags();
        applyTransform();
        attachGeoEdit();
        renderLayers();
        if (savedRefs.length && state.geo) {
          state.geo.selectMulti(savedRefs);
        }
        renderInspector();
      },
      onSelect: (sels) => {
        state.sel = sels || [];
        renderInspector();
        renderLayers();
        updateAlignVisibility();
      },
    });
    // инструмент переживает ре-аттач после мутаций
    if (state.tool !== "select") state.geo.setTool(state.tool);
  }

  /* ---------- слои ---------- */

  function propsElements(sec) {
    const p = sec.props || {};
    const items = [];
    if (p.logoText) items.push({ path: "props.logoText", label: "logo: " + p.logoText, icon: "◆" });
    if (p.links) p.links.forEach((l, i) => items.push({ path: `props.links.${i}`, label: "link: " + (l.label || ""), icon: "→" }));
    if (p.cta && p.cta.text) items.push({ path: "props.cta", label: "cta: " + p.cta.text, icon: "⬛" });
    if (p.badge) items.push({ path: "props.badge", label: "badge: " + p.badge, icon: "•" });
    if (p.heading) items.push({ path: "props.heading", label: "heading: " + String(p.heading).slice(0, 22), icon: "H" });
    if (p.subheading) items.push({ path: "props.subheading", label: "sub: " + String(p.subheading).slice(0, 22), icon: "T" });
    if (p.ctaPrimary && p.ctaPrimary.text) items.push({ path: "props.ctaPrimary", label: "btn: " + p.ctaPrimary.text, icon: "⬛" });
    if (p.ctaSecondary && p.ctaSecondary.text) items.push({ path: "props.ctaSecondary", label: "btn: " + p.ctaSecondary.text, icon: "⬜" });
    if (p.media) items.push({ path: "props.media", label: "media", icon: "▣" });
    if (p.text && !p.heading) items.push({ path: "props.text", label: "text: " + String(p.text).slice(0, 22), icon: "T" });
    if (p.tiers) p.tiers.forEach((tier, i) => items.push({ path: `props.tiers.${i}`, label: "tier: " + tier.name, icon: "$" }));
    if (p.items && sec.type === "faq") p.items.forEach((item, i) => items.push({ path: `props.items.${i}`, label: "faq: " + String(item.question).slice(0, 20), icon: "?" }));
    if (p.items && sec.type === "stats") p.items.forEach((item, i) => items.push({ path: `props.items.${i}`, label: "stat: " + item.value, icon: "#" }));
    return items;
  }

  function renderLayers() {
    const tree = overlay.querySelector(".fe-layers-tree");
    tree.innerHTML = "";
    if (!state.ir || !state.ir.tree) return;
    // артборд
    addLayerItem(tree, state.ir, { secIdx: null, path: null }, 0, "Артборд");
    state.ir.tree.forEach((sec, si) => {
      const secLabel = sec.type + (sec.props && sec.props.heading ? ` · ${String(sec.props.heading).slice(0, 18)}` : "");
      addLayerItem(tree, sec, { secIdx: si, path: null }, 1, secLabel);
      // props-элементы
      propsElements(sec).forEach(pe => {
        addLayerItem(tree, getByPath(sec, pe.path) || {}, { secIdx: si, path: pe.path }, 2, pe.label, pe.icon);
      });
      // children-элементы
      (sec.children || []).forEach((el, ci) => {
        addLayerItem(tree, el, { secIdx: si, path: `children.${ci}` }, 2, el.type + (el.text ? ` · ${el.text.slice(0, 16)}` : el.title ? ` · ${el.title.slice(0, 16)}` : ""));
        (el.children || []).forEach((ch, chi) => {
          addLayerItem(tree, ch, { secIdx: si, path: `children.${ci}.children.${chi}` }, 3, ch.type + (ch.text ? ` · ${ch.text.slice(0, 14)}` : ch.title ? ` · ${ch.title.slice(0, 14)}` : ""));
        });
      });
    });
  }

  function addLayerItem(container, irNode, ref, depth, label, iconOverride) {
    if (state.layerQuery && !label.toLowerCase().includes(state.layerQuery.toLowerCase())) return;
    const key = refKeyOf(ref);
    const fl = state.layerFlags[key] || {};
    const div = document.createElement("div");
    div.className = "fe-layer depth-" + Math.min(depth, 3);
    div.dataset.key = key;
    if (fl.hidden) div.classList.add("flag-hidden");
    if (fl.locked) div.classList.add("flag-locked");
    if (state.sel.some(s => s.ref.secIdx === ref.secIdx && s.ref.path === ref.path)) div.classList.add("selected");
    const icons = { navbar: "☰", hero: "◈", card: "▢", heading: "H", text: "T", button: "⬛", image: "▣", badge: "•", pricing: "$", faq: "?", footer: "⊥" };
    const icon = iconOverride || icons[irNode.type] || "◇";
    div.innerHTML = `<span class="fe-li">${icon}</span><span class="fe-ln">${esc(label)}</span>` +
      `<button class="fe-lbtn" data-flag="hidden" title="Скрыть/показать слой">${fl.hidden ? "🚫" : "👁"}</button>` +
      `<button class="fe-lbtn" data-flag="locked" title="Залочить/разлочить">${fl.locked ? "🔒" : "🔓"}</button>`;
    div.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-flag]");
      if (btn) { toggleLayerFlag(ref, btn.dataset.flag); return; }
      if (refFlag(ref, "locked")) return; // залочен — не выделяется
      if (state.geo) state.geo.select(ref);
    });
    container.appendChild(div);
  }

  /* ---------- инспектор ---------- */

  function renderInspector() {
    const panel = overlay.querySelector(".fe-inspector");
    if (!state.sel.length) {
      panel.innerHTML = '<div class="fe-insp-empty">Выделите элемент на канвасе или в слоях</div>';
      return;
    }

    // Position / Alignment / Flex Layout — общий инспектор (модель pen.dev), тот же что в ноде Edit
    let html = `<div class="fe-shared-insp"></div>`;

    if (state.sel.length > 1) {
      panel.innerHTML = html;
      Inspector.render(panel.querySelector(".fe-shared-insp"), { ir: state.ir, selections: state.sel, geo: state.geo });
      return;
    }

    const sel = state.sel[0];
    const node = sel.node || {};
    const isRoot = sel.ref.secIdx == null;
    const t = state.ir.tokens || {};

    // --- текст (heading / text / button) ---
    if (node.type === "heading" || node.type === "text") {
      html += `<div class="fe-insp-group"><span class="fe-glabel">Текст</span>
        <textarea data-textprop="${node.text !== undefined ? "text" : "title"}">${esc(node.text || node.title || "")}</textarea>
        <div class="fe-row" style="margin-top:6px">
          <div class="fe-field"><label>Sz</label><select data-el-prop="size"><option value="xs" ${node.size==="xs"?"selected":""}>XS</option><option value="sm" ${node.size==="sm"?"selected":""}>SM</option><option value="md" ${(!node.size||node.size==="md")?"selected":""}>MD</option><option value="lg" ${node.size==="lg"?"selected":""}>LG</option><option value="xl" ${node.size==="xl"?"selected":""}>XL</option><option value="display" ${node.size==="display"?"selected":""}>Display</option></select></div>
          <div class="fe-field"><label>≡</label><select data-el-prop="align"><option value="left" ${(!node.align||node.align==="left")?"selected":""}>Left</option><option value="center" ${node.align==="center"?"selected":""}>Center</option><option value="right" ${node.align==="right"?"selected":""}>Right</option></select></div>
        </div>`;
      if (node.type === "heading") {
        html += `<div class="fe-row"><div class="fe-field"><label>H</label><select data-el-prop="level"><option value="1" ${node.level===1?"selected":""}>H1</option><option value="2" ${(!node.level||node.level===2)?"selected":""}>H2</option><option value="3" ${node.level===3?"selected":""}>H3</option><option value="4" ${node.level===4?"selected":""}>H4</option></select></div></div>`;
      }
      html += `</div>`;
    }

    if (node.type === "button") {
      html += `<div class="fe-insp-group"><span class="fe-glabel">Кнопка</span>
        <div class="fe-field" style="margin-bottom:6px"><label>Txt</label><input type="text" data-el-prop="text" value="${esc(node.text || "")}"></div>
        <div class="fe-field"><label>Var</label><select data-el-prop="variant"><option value="primary" ${(!node.variant||node.variant==="primary")?"selected":""}>Primary</option><option value="secondary" ${node.variant==="secondary"?"selected":""}>Secondary</option><option value="outline" ${node.variant==="outline"?"selected":""}>Outline</option><option value="ghost" ${node.variant==="ghost"?"selected":""}>Ghost</option></select></div></div>`;
    }

    // --- цвета токенов (для артборда) ---
    if (isRoot && t.color) {
      html += `<div class="fe-insp-group"><span class="fe-glabel">Цвета (токены)</span>`;
      for (const k of COLOR_KEYS) {
        const v = t.color[k];
        if (!v) continue;
        html += `<div class="fe-color-row"><label>${COLOR_LABELS[k] || k}</label>
          <input type="color" data-color="${k}" value="${toFullHex(v)}"><span class="fe-hex">${v}</span></div>`;
      }
      html += `</div>`;
    }

    // --- шрифты (для артборда) ---
    if (isRoot && t.font) {
      html += `<div class="fe-insp-group"><span class="fe-glabel">Шрифты</span>
        <div class="fe-field" style="margin-bottom:4px"><label>D</label><select data-font="display">${FONT_FAMILIES.map(ff => `<option ${ff===t.font.display.family?"selected":""}>${ff}</option>`).join("")}</select></div>
        <div class="fe-field" style="margin-bottom:4px"><label>B</label><select data-font="body">${FONT_FAMILIES.map(ff => `<option ${ff===t.font.body.family?"selected":""}>${ff}</option>`).join("")}</select></div>
        <div class="fe-field"><label>Sc</label><select data-token="font.scale"><option value="compact" ${t.font.scale==="compact"?"selected":""}>Compact</option><option value="default" ${(!t.font.scale||t.font.scale==="default")?"selected":""}>Default</option><option value="spacious" ${t.font.scale==="spacious"?"selected":""}>Spacious</option></select></div></div>`;
    }

    // --- радиусы / отступы / тени (для артборда) ---
    if (isRoot) {
      html += `<div class="fe-insp-group"><span class="fe-glabel">Форма и отступы</span>
        <div class="fe-row">
          <div class="fe-field"><label>R</label><select data-token="radius.card"><option value="none" ${t.radius&&t.radius.card==="none"?"selected":""}>None</option><option value="sm" ${t.radius&&t.radius.card==="sm"?"selected":""}>SM</option><option value="md" ${(!t.radius||t.radius.card==="md")?"selected":""}>MD</option><option value="lg" ${t.radius&&t.radius.card==="lg"?"selected":""}>LG</option><option value="xl" ${t.radius&&t.radius.card==="xl"?"selected":""}>XL</option><option value="full" ${t.radius&&t.radius.card==="full"?"selected":""}>Full</option></select></div>
          <div class="fe-field"><label>Sp</label><select data-token="spacing.section"><option value="sm" ${t.spacing&&t.spacing.section==="sm"?"selected":""}>SM</option><option value="md" ${(!t.spacing||t.spacing.section==="md")?"selected":""}>MD</option><option value="lg" ${t.spacing&&t.spacing.section==="lg"?"selected":""}>LG</option><option value="xl" ${t.spacing&&t.spacing.section==="xl"?"selected":""}>XL</option></select></div>
        </div>
        <div class="fe-field"><label>Sh</label><select data-token="shadow"><option value="none" ${t.shadow==="none"?"selected":""}>None</option><option value="sm" ${(!t.shadow||t.shadow==="sm")?"selected":""}>SM</option><option value="md" ${t.shadow==="md"?"selected":""}>MD</option><option value="lg" ${t.shadow==="lg"?"selected":""}>LG</option></select></div></div>`;
    }

    panel.innerHTML = html;
    Inspector.render(panel.querySelector(".fe-shared-insp"), { ir: state.ir, selections: state.sel, geo: state.geo });
    wireInspectorEvents(panel);
  }

  function wireInspectorEvents(panel) {
    // element props (text/size/align/level/variant)
    panel.querySelectorAll("[data-el-prop]").forEach(inp => {
      inp.addEventListener("change", () => {
        if (!state.sel.length) return;
        const node = state.sel[0].node;
        if (!node) return;
        pushHistory();
        const key = inp.dataset.elProp;
        let val = inp.value;
        if (key === "level") val = Number(val);
        node[key] = val;
        rerenderEditorCanvas();
      });
    });
    // text content
    panel.querySelectorAll("[data-textprop]").forEach(ta => {
      ta.addEventListener("change", () => {
        if (!state.sel.length) return;
        pushHistory();
        state.sel[0].node[ta.dataset.textprop] = ta.value;
        rerenderEditorCanvas();
      });
    });
    // token colors: снапшот ДО мутации (по первому input серии) —
    // pushHistory на change снимал бы уже изменённый цвет, и undo его не возвращал
    panel.querySelectorAll("[data-color]").forEach(inp => {
      let armed = false;
      inp.addEventListener("focus", () => { armed = true; });
      inp.addEventListener("input", () => {
        if (armed) { pushHistory(); armed = false; }
        state.ir.tokens.color[inp.dataset.color] = inp.value;
        inp.nextElementSibling.textContent = inp.value;
        rerenderEditorCanvas();
      });
    });
    // font family
    panel.querySelectorAll("[data-font]").forEach(sel => {
      sel.addEventListener("change", () => {
        pushHistory();
        state.ir.tokens.font[sel.dataset.font].family = sel.value;
        rerenderEditorCanvas();
      });
    });
    // token-level props (font.scale, radius.card, spacing.section, shadow)
    panel.querySelectorAll("[data-token]").forEach(sel => {
      sel.addEventListener("change", () => {
        pushHistory();
        const path = sel.dataset.token.split(".");
        let obj = state.ir.tokens;
        for (let i = 0; i < path.length - 1; i++) obj = obj[path[i]];
        obj[path[path.length - 1]] = sel.value;
        rerenderEditorCanvas();
      });
    });
  }

  function rerenderEditorCanvas() {
    const inner = overlay.querySelector(".fe-canvas-inner");
    IRRenderer.renderIR(inner, state.ir); // _frames применяет сам рендерер
    applyLayerFlags();
    applyTransform();
    attachGeoEdit();
    renderLayers();
    if (state.sel.length) state.geo.selectMulti(state.sel.map(s => s.ref));
    renderInspector();
  }

  /* ---------- клавиатура ---------- */

  document.addEventListener("keydown", (e) => {
    if (!state || overlay.style.display === "none") return;
    const ae = document.activeElement;
    if (ae && (ae.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName))) return;
    if (e.key === "v" || e.key === "V" || e.key === "м" || e.key === "М") setTool("select");
    if (e.key === "h" || e.key === "H" || e.key === "р" || e.key === "Р") setTool("hand");
    if ((e.key === "z" || e.key === "Z" || e.key === "я" || e.key === "Я") && (e.ctrlKey || e.metaKey)) { e.preventDefault(); undo(); }
    // Esc: сначала отдаём GeoEdit (выход из контейнера / снятие выделения);
    // закрываем редактор, только если geoedit событие не поглотил
    if (e.key === "Escape") {
      if (state.geo && state.geo.consumeEscape()) return;
      close();
    }
  });

  /* ---------- утилиты ---------- */

  function esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
  function toFullHex(hex) {
    if (/^#[0-9a-fA-F]{6}$/.test(hex)) return hex;
    if (/^#[0-9a-fA-F]{3}$/.test(hex)) return "#" + [...hex.slice(1)].map(c => c + c).join("");
    return "#888888";
  }

  global.Editor = { open, close, isOpen: () => !!state };
})(window);
