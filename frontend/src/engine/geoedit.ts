// @ts-nocheck
/* DesignAI Web — GeoEdit: ядро Figma-геометрии поверх IR-превью.
 * Самостоятельный модуль без глобального состояния приложения.
 * Используется editor.js (полноэкранный редактор) и nodes.js (нода Edit).
 *
 * const handle = GeoEdit.attach({
 *   previewEl,   // контейнер, куда IRRenderer.renderIR рендерит IR
 *   getIR,       // () => ir — текущий IR (объект мутируется in-place)
 *   getScale,    // () => number — масштаб превью (screen px / px артборда)
 *   onCommit,    // () => void — перед мутацией IR (владелец пишет историю)
 *   onMutated,   // () => void — после мутации (владелец перерисовывает превью)
 *   onSelect,    // (selections[]) => void — массив выделенных {ref,label,node}
 * });
 * handle: { select(ref), selectMulti(refs), clear(), setFrame(obj), resetFrame(),
 *           alignLeft(), alignCenterH(), alignRight(),
 *           alignTop(), alignCenterV(), alignBottom(),
 *           distributeH(), distributeV(),
 *           selectAll(), copySelection(), cutSelection(), pasteClipboard(),
 *           destroy(), selection, selections }
 *
 * Адресация узлов: ref = {secIdx: number|null (артборд), path: string|null}.
 * path — от корня секции: "children.0", "children.1.children.0", ...
 */

  /* ---------- CSS (инжектится один раз) ---------- */

  const GEO_CSS = `
  /* Оверлей живёт ВНУТРИ трансформированного контейнера (canvas-координаты).
     --geo-inv = 1/zoom: ручки, чипы и линии держат постоянный экранный размер. */
  .geo-overlay { position:absolute; left:0; top:0; width:100%; height:100%; pointer-events:auto; z-index:50; overflow:visible; cursor:default; }
  .geo-overlay[data-tool="rect"], .geo-overlay[data-tool="frame"], .geo-overlay[data-tool="text"],
  .geo-overlay[data-tool="ellipse"], .geo-overlay[data-tool="line"], .geo-overlay[data-tool="image"] { cursor:crosshair; }
  .geo-overlay[data-tool="hand"] { cursor:grab; }
  .geo-overlay.geo-handling { cursor:grabbing; }
  .geo-overlay * { pointer-events:none; }
  .geo-overlay .geo-h { pointer-events:auto; }
  .geo-box { position:absolute; border:calc(1.5px * var(--geo-inv,1)) solid transparent; pointer-events:none; }
  .geo-box.hover { border-color:rgba(120,120,160,.55); border-style:dashed; }
  .geo-box.selected { border-color:#0D99FF; }
  .geo-chip { position:absolute; top:calc(-20px * var(--geo-inv,1)); left:calc(-1px * var(--geo-inv,1));
    background:#0D99FF; color:#fff; font-family:'Inter',system-ui,sans-serif; font-weight:600;
    font-size:calc(10px * var(--geo-inv,1)); padding:calc(1px * var(--geo-inv,1)) calc(7px * var(--geo-inv,1));
    border-radius:calc(4px * var(--geo-inv,1)) calc(4px * var(--geo-inv,1)) 0 0;
    white-space:nowrap; pointer-events:none; }
  .geo-h { position:absolute; width:calc(8px * var(--geo-inv,1)); height:calc(8px * var(--geo-inv,1));
    background:#fff; border:calc(1.5px * var(--geo-inv,1)) solid #0D99FF;
    border-radius:2px; pointer-events:auto; z-index:2; }
  .geo-h.h-nw { top:calc(-4px * var(--geo-inv,1)); left:calc(-4px * var(--geo-inv,1)); cursor:nwse-resize; }
  .geo-h.h-n  { top:calc(-4px * var(--geo-inv,1)); left:calc(50% - 4px * var(--geo-inv,1)); cursor:ns-resize; }
  .geo-h.h-ne { top:calc(-4px * var(--geo-inv,1)); right:calc(-4px * var(--geo-inv,1)); cursor:nesw-resize; }
  .geo-h.h-e  { top:calc(50% - 4px * var(--geo-inv,1)); right:calc(-4px * var(--geo-inv,1)); cursor:ew-resize; }
  .geo-h.h-se { bottom:calc(-4px * var(--geo-inv,1)); right:calc(-4px * var(--geo-inv,1)); cursor:nwse-resize; }
  .geo-h.h-s  { bottom:calc(-4px * var(--geo-inv,1)); left:calc(50% - 4px * var(--geo-inv,1)); cursor:ns-resize; }
  .geo-h.h-sw { bottom:calc(-4px * var(--geo-inv,1)); left:calc(-4px * var(--geo-inv,1)); cursor:nesw-resize; }
  .geo-h.h-w  { top:calc(50% - 4px * var(--geo-inv,1)); left:calc(-4px * var(--geo-inv,1)); cursor:ew-resize; }
  .geo-marquee { position:absolute; border:calc(1px * var(--geo-inv,1)) solid #0D99FF; background:rgba(13,153,255,.08);
    pointer-events:none; z-index:60; }
  .geo-guide { position:absolute; pointer-events:none; z-index:58; }
  .geo-guide-h { left:0; right:0; height:calc(1px * var(--geo-inv,1)); background:#ff3b30; }
  .geo-guide-v { top:0; bottom:0; width:calc(1px * var(--geo-inv,1)); background:#ff3b30; }
  .geo-dist { position:absolute; pointer-events:none; z-index:58; font-family:'Inter',system-ui,sans-serif;
    font-weight:500; font-size:calc(9px * var(--geo-inv,1));
    color:#34c759; background:rgba(52,199,89,.12); padding:0 calc(3px * var(--geo-inv,1)); border-radius:2px; white-space:nowrap; }
  .geo-dist-line { position:absolute; pointer-events:none; z-index:57; background:#34c759; }
  .geo-dist-line-h { height:calc(1px * var(--geo-inv,1)); }
  .geo-dist-line-v { width:calc(1px * var(--geo-inv,1)); }
  /* equal spacing (фиолетовые метки равных зазоров, как в Figma) */
  .geo-eq { position:absolute; pointer-events:none; z-index:57;
    background:rgba(151,71,255,.16); outline:calc(1px * var(--geo-inv,1)) solid rgba(151,71,255,.45); }
  .geo-eq-label { position:absolute; pointer-events:none; z-index:58; font-family:'Inter',system-ui,sans-serif;
    font-weight:500; font-size:calc(9px * var(--geo-inv,1));
    color:#9747ff; background:rgba(151,71,255,.12); padding:0 calc(3px * var(--geo-inv,1)); border-radius:2px; white-space:nowrap; }
  .geo-hint { position:absolute; left:50%; top:calc(8px * var(--geo-inv,1)); transform:translateX(-50%);
    background:rgba(24,24,27,.92); color:#e4e4e7; border:1px solid #3f3f46; border-radius:6px;
    font-family:'Inter',system-ui,sans-serif; font-weight:500; font-size:calc(11px * var(--geo-inv,1));
    padding:calc(5px * var(--geo-inv,1)) calc(10px * var(--geo-inv,1)); white-space:nowrap;
    pointer-events:none; z-index:70; }
  /* контекстное меню канваса (правый клик; паттерн OpenPencil/Figma) */
  /* .geo-overlay * гасит pointer-events — меню и пункты включают их явно */
  .geo-ctx-menu, .geo-ctx-menu * { pointer-events:auto; }
  .geo-ctx-menu { position:absolute; z-index:90; min-width:calc(190px * var(--geo-inv,1));
    background:rgba(24,24,27,.97); border:1px solid #3f3f46; border-radius:calc(6px * var(--geo-inv,1));
    padding:calc(4px * var(--geo-inv,1)); pointer-events:auto;
    box-shadow:0 calc(8px * var(--geo-inv,1)) calc(24px * var(--geo-inv,1)) rgba(0,0,0,.45);
    font-family:'Inter',system-ui,sans-serif; }
  .geo-ctx-item { display:flex; justify-content:space-between; align-items:center;
    gap:calc(18px * var(--geo-inv,1)); width:100%; background:none; border:none; color:#e4e4e7;
    text-align:left; cursor:pointer; font-family:inherit;
    font-size:calc(12px * var(--geo-inv,1)); line-height:1.2;
    padding:calc(5px * var(--geo-inv,1)) calc(8px * var(--geo-inv,1));
    border-radius:calc(4px * var(--geo-inv,1)); white-space:nowrap; }
  .geo-ctx-item:hover:not(.disabled) { background:#0D99FF; color:#fff; }
  .geo-ctx-item.disabled { opacity:.38; cursor:default; }
  .geo-ctx-item kbd { color:#a1a1aa; font-family:inherit; font-size:calc(10px * var(--geo-inv,1)); }
  .geo-ctx-item:hover:not(.disabled) kbd { color:rgba(255,255,255,.85); }
  .geo-ctx-sep { height:1px; background:#3f3f46; margin:calc(4px * var(--geo-inv,1)) calc(4px * var(--geo-inv,1)); }
  .geo-content-block { pointer-events:none !important; }
  .geo-content-block * { pointer-events:none !important; }
  .geo-content-block [data-ir-path].editing,
  .geo-content-block [data-ir-path].editing * { pointer-events:auto !important; }
  `;

  let cssInjected = false;
  function injectCSS() {
    if (cssInjected) return;
    cssInjected = true;
    const s = document.createElement("style");
    s.textContent = GEO_CSS;
    document.head.appendChild(s);
  }

  /* ---------- буфер обмена (уровень модуля: переживает re-attach владельца) ---------- */

  let geoClipboard = [];  // [{node, parentRef, intoTree}]
  let geoUidCounter = 0;
  /** Уникальный id создаваемых/вставляемых узлов (IR не требует id, но он полезен). */
  function nextUid() {
    return "geo-" + Date.now().toString(36) + "-" + (++geoUidCounter);
  }

  /* ---------- утилиты ---------- */

  function getByPath(obj, path) {
    return path.split(".").reduce((o, k) => (o == null ? o : o[k]), obj);
  }

  function setByPath(obj, path, value) {
    const keys = path.split(".");
    const last = keys.pop();
    const target = keys.reduce((o, k) => (o == null ? o : o[k]), obj);
    if (target != null) target[last] = value;
  }

  /** Для props-текстовых объектов (cta, heading и т.п.) редактируем поле .text,
   *  а не заменяем весь объект строкой. */
  function editableTextPath(path) {
    if (!path || !path.startsWith("props.")) return path;
    const base = path.replace(/\.text$/, "");
    const textProps = ["cta", "ctaPrimary", "ctaSecondary", "badge", "heading", "subheading", "text", "logoText"];
    const key = base.slice("props.".length);
    if (textProps.includes(key)) return base + ".text";
    return path;
  }

  /** Guard для координат из внешнего IR: строки/NaN не должны попадать в арифметику. */
  function finiteNum(v) {
    const n = typeof v === "number" ? v : parseFloat(v);
    return Number.isFinite(n) ? n : 0;
  }

  /* ---------- attach ---------- */

  function attach(opts) {
    const { previewEl, getIR, getScale, onCommit, onSelect } = opts;
    const scrollEl = opts.scrollEl || null;          // скролл-контейнер для инструмента «рука»
    const onToolChange = opts.onToolChange || null; // уведомление владельца о смене инструмента
    const toolsEnabled = !!opts.tools;              // хоткеи V/R/T/F/H только там, где есть панель
    // если владелец сам опрашивает consumeEscape() с handle (DNA-редактор),
    // собственный document-обработчик Esc не срабатывает — порядок не должен быть контрактом
    const escapeViaHandle = !!opts.escapeViaHandle;
    // владелец может залочить слои: такие ref не попадают в hit-test/marquee
    const isLocked = opts.isLocked || null;
    function skipLocked(ref) { return !!isLocked && isLocked(ref); }
    let _onMutated = opts.onMutated || function(){};
    function blockContentEarly() {
      const irEl = previewEl.querySelector('[class^="ir-"]');
      if (irEl) irEl.classList.add("geo-content-block");
    }
    function onMutated() {
      _onMutated();
      requestAnimationFrame(blockContentEarly);
      // владелец мог перерисовать превью целиком — восстановить рамки выделения
      scheduleBoxSync();
    }
    injectCSS();

    // КРИТИЧНО: previewEl должен быть positioned-контейнером для оверлея
    // (как в tldraw/Excalidraw — canvas container всегда position:relative).
    // overflow НЕ трогаем: владелец сам решает, скроллится ли превью (нода Edit — да).
    const prevStyle = previewEl.style;
    if (!prevStyle.position || prevStyle.position === "static") {
      prevStyle.position = "relative";
    }

    let selections = [];   // [{ref, label, node}]
    let drag = null;
    let marquee = null;
    let tool = "select";   // select | rect | ellipse | line | image | text | frame | hand (панель как в pen.dev)
    let hand = null;
    let create = null;
    let destroyed = false;
    let rafId = null;
    let boxSyncRaf = null;
    let pendingPointer = null;
    let containerCtx = null;  // ref контейнера, в который вошли (dbl-click enter)
    // Батчинг nudge (паттерн OpenPencil nudge.ts): серия стрелок короче 300 мс
    // между нажатиями — ОДИН undo-шаг; onCommit только на старте серии.
    let nudgeSessionUntil = 0;
    // Тот же паттерн для потоковых записей стиля (drag в color picker,
    // нативный color-input): onCommit один раз на серию быстрее 300 мс.
    let styleSessionUntil = 0;

    function scale() { const s = getScale(); return s > 0 ? s : 1; }

    /** Собственный transform previewEl: в DNA-редакторе оверлей живёт внутри
     *  трансформированного контейнера (overlayScale == scale), в ноде Edit зум
     *  висит на артборде-ребёнке, а оверлей вне его (overlayScale == 1). */
    function overlayScale() {
      const ow = previewEl.offsetWidth;
      return ow > 0 ? previewEl.getBoundingClientRect().width / ow : 1;
    }

    /** Перевод canvas-координат в координаты оверлея (для визуальных элементов). */
    function canvasK() {
      const os = overlayScale();
      return os > 0 ? scale() / os : 1;
    }

    /** Перерисовка рамок через кадр: владелец (Edit-нода) применяет зум через rAF
     *  уже после ре-рендера — без этого рамки встали бы по до-зумовой геометрии. */
    function scheduleBoxSync() {
      if (boxSyncRaf || destroyed) return;
      boxSyncRaf = requestAnimationFrame(() => {
        boxSyncRaf = null;
        if (!destroyed && selections.length) renderSelectionBoxes();
      });
    }

    /* --- адресация: IR-узел <-> DOM --- */

    function artboardEl() { return previewEl.querySelector('[class^="ir-"]'); }

    function irNodeAt(ref) {
      const ir = getIR();
      if (ref.secIdx == null) return ir;
      if (ref.path == null) return ir.tree[ref.secIdx];
      return getByPath(ir.tree[ref.secIdx], ref.path);
    }

    function getFrame(ref) {
      if (ref.secIdx == null) return (getIR().frame) || {};
      if (ref.path == null) return (getIR().tree[ref.secIdx].frame) || {};
      if (ref.path.startsWith("props.")) {
        const sec = getIR().tree[ref.secIdx];
        return (sec._frames && sec._frames[ref.path]) || {};
      }
      const node = irNodeAt(ref);
      return (node && node.frame) || {};
    }

    function setFrameData(ref, frame) {
      if (ref.secIdx == null) { getIR().frame = frame; return; }
      if (ref.path == null) { getIR().tree[ref.secIdx].frame = frame; return; }
      if (ref.path.startsWith("props.")) {
        const sec = getIR().tree[ref.secIdx];
        if (!sec._frames) sec._frames = {};
        if (frame && Object.keys(frame).length) sec._frames[ref.path] = frame;
        else delete sec._frames[ref.path];
        return;
      }
      const node = irNodeAt(ref);
      if (node) {
        if (frame && Object.keys(frame).length) node.frame = frame;
        else delete node.frame;
      }
    }

    function domAt(ref) {
      if (ref.secIdx == null) return artboardEl();
      const secEl = previewEl.querySelector(`[data-ir-sec="${ref.secIdx}"]`);
      if (!secEl) return null;
      if (ref.path == null) return secEl;
      if (ref.path.startsWith("props.")) {
        return secEl.querySelector(`[data-ir-path^="${ref.path}"]`);
      }
      return secEl.querySelector(`[data-ir-path="${ref.path}"]`);
    }

    function refFromTarget(target) {
      // 1) Ищем ближайший предок с data-ir-path (обычный путь)
      let el = target.closest && target.closest('[data-ir-path^="children"], [data-ir-path^="props"]');
      // 2) Если не нашли — клик по обёртке (<a>, <div>), ищем data-ir-path ВНУТРИ target
      if ((!el || !previewEl.contains(el)) && target.querySelector) {
        el = target.querySelector('[data-ir-path^="children"], [data-ir-path^="props"]');
      }
      if (el && previewEl.contains(el)) {
        const secEl = el.closest("[data-ir-sec]");
        if (!secEl) return null;
        const secIdx = Number(secEl.getAttribute("data-ir-sec"));
        const rawPath = el.getAttribute("data-ir-path");
        return { secIdx, path: normalizePropsPath(rawPath) };
      }
      // 3) Fallback: вся секция
      const secEl = target.closest && target.closest('[data-ir-sec]');
      if (!secEl || !previewEl.contains(secEl)) return null;
      const secIdx = Number(secEl.getAttribute("data-ir-sec"));
      return { secIdx, path: null };
    }

    function normalizePropsPath(p) {
      if (!p || !p.startsWith("props.")) return p;
      const m = p.match(/^(props\.(?:links|tiers|items|columns)\.\d+)(\..+)?$/);
      if (m) return m[1];
      const m2 = p.match(/^(props\.(?:cta|ctaPrimary|ctaSecondary|media|logoText|badge|heading|subheading|text))(\..+)?$/);
      if (m2) return m2[1];
      return p;
    }

    function labelOf(ref) {
      const node = irNodeAt(ref);
      if (ref.secIdx == null) return "артборд";
      if (ref.path == null) return "section · " + (node ? node.type : "?");
      if (ref.path && ref.path.startsWith("props.")) return ref.path.replace("props.", "");
      return node && node.type ? node.type : "узел";
    }

    /* --- геометрический hit-testing (модель tldraw/Excalidraw) --- */

    /** Конвертирует экранные координаты в координаты превью (учитывая scale и pan/scroll).
     *  getBoundingClientRect уже включает transform и scroll, дополнительный offset не нужен. */
    function screenToCanvas(clientX, clientY) {
      const base = previewEl.getBoundingClientRect();
      const s = scale();
      return { x: (clientX - base.left) / s,
               y: (clientY - base.top) / s };
    }

    /** Собирает ВСЕ элементы с data-ir-path из IR в плоский список {ref, x, y, w, h}.
     *  Включает children, props-элементы и сами секции.
     *  Координаты — в системе previewEl (как boxRect и screenToCanvas). */
    function collectHitTargets() {
      const ir = getIR();
      if (!ir || !ir.tree) return [];
      const targets = [];
      const base = previewEl.getBoundingClientRect();
      const s = scale();

      ir.tree.forEach((sec, si) => {
        const secEl = previewEl.querySelector(`[data-ir-sec="${si}"]`);
        if (!secEl) return;

        // сама секция
        const sr = secEl.getBoundingClientRect();
        targets.push({
          ref: { secIdx: si, path: null },
          depth: 0,
          x: (sr.left - base.left ) / s,
          y: (sr.top - base.top ) / s,
          w: sr.width / s,
          h: sr.height / s,
        });

        // ВСЕ элементы с data-ir-path внутри секции (children + props)
        secEl.querySelectorAll("[data-ir-path]").forEach(el => {
          const rawPath = el.getAttribute("data-ir-path");
          if (!rawPath) return;
          const r = el.getBoundingClientRect();
          // пропускаем нулевые размеры
          if (r.width < 2 || r.height < 2) return;
          targets.push({
            ref: { secIdx: si, path: normalizePropsPath(rawPath) },
            depth: rawPath.startsWith("children.") ? rawPath.split(".children.").length : 1,
            x: (r.left - base.left ) / s,
            y: (r.top - base.top ) / s,
            w: r.width / s,
            h: r.height / s,
          });
        });
      });
      return targets;
    }

    function parentRef(ref) {
      if (!ref || ref.secIdx == null || !ref.path || !ref.path.startsWith("children.")) return null;
      const parts = ref.path.split(".");
      if (parts.length <= 2) return { secIdx: ref.secIdx, path: null };
      parts.pop(); parts.pop();
      return { secIdx: ref.secIdx, path: parts.join(".") };
    }

    function nearestSelectableContainer(ref, hitKeys) {
      const hitNode = irNodeAt(ref);
      // Controls are already meaningful selectable containers. When the DOM
      // hit lands on the control wrapper itself, do not hoist it to an
      // auto-layout form/card parent.
      if (hitNode && ["button", "input"].includes(hitNode.type)) return ref;
      let parent = parentRef(ref);
      while (parent) {
        const node = irNodeAt(parent);
        if (parent.path && node && node.children && node.children.length && hitKeys.has(refKey(parent)) && !skipLocked(parent)) {
          // Text/heading children inside buttons or inputs belong to the control.
          if (["button", "input"].includes(node.type)) return parent;
          // Free-layout containers (source-block reproduction, absolute groups)
          // keep their children individually selectable; do not hoist to parent.
          const layout = node && node.frame && node.frame.layout;
          if (layout !== "free") return parent;
        }
        parent = parentRef(parent);
      }
      return null;
    }

    /** Геометрический hit-test: возвращает ref элемента под точкой (или null).
     *  deep=true: пропустить контейнеры (секции), выбрать самый вложенный child. */
    function hitTest(clientX, clientY, deep) {
      const pt = screenToCanvas(clientX, clientY);
      const targets = collectHitTargets();
      const hits = [];
      // идём с конца (верхний z-order первый)
      for (let i = targets.length - 1; i >= 0; i--) {
        const t = targets[i];
        if (pt.x >= t.x && pt.x <= t.x + t.w && pt.y >= t.y && pt.y <= t.y + t.h) {
          if (skipLocked(t.ref)) continue; // залоченные слои прозрачны для выделения
          hits.push(t);
          // deep mode: пропустить секцию (path===null), вернуть child
          if (deep && t.ref.path === null) continue;
          // если в containerCtx — принимать только children этого контейнера
          if (containerCtx && t.ref.path === null) continue;
          if (!deep) {
            const hitKeys = new Set(hits.map(h => refKey(h.ref)).concat(targets
              .filter(q => pt.x >= q.x && pt.x <= q.x + q.w && pt.y >= q.y && pt.y <= q.y + q.h)
              .map(q => refKey(q.ref))));
            const container = nearestSelectableContainer(t.ref, hitKeys);
            if (container) return container;
          }
          return t.ref;
        }
      }
      // fallback: если deep и не нашли child, вернуть секцию
      if (deep) {
        for (let i = targets.length - 1; i >= 0; i--) {
          const t = targets[i];
          if (pt.x >= t.x && pt.x <= t.x + t.w && pt.y >= t.y && pt.y <= t.y + t.h) {
            if (skipLocked(t.ref)) continue;
            return t.ref;
          }
        }
      }
      return null;
    }

    /** Проверяет попадание в resize-хендл текущего выделения. Возвращает направление или null. */
    function hitTestHandle(clientX, clientY) {
      if (!selections.length) return null;
      const s = scale();
      const base = previewEl.getBoundingClientRect();
      let hx, hy, hw, hh;
      if (selections.length > 1) {
        // мультивыделение: ручки на объединяющей рамке (как рисует renderSelectionBoxes)
        const rects = selectedRects();
        if (rects.length < 2) return null;
        hx = Math.min(...rects.map(r => r.x));
        hy = Math.min(...rects.map(r => r.y));
        hw = Math.max(...rects.map(r => r.x + r.w)) - hx;
        hh = Math.max(...rects.map(r => r.y + r.h)) - hy;
      } else {
        const primary = selections[selections.length - 1];
        const el = domAt(primary.ref);
        if (!el) return null;
        const r = el.getBoundingClientRect();
        hx = (r.left - base.left ) / s;
        hy = (r.top - base.top ) / s;
        hw = r.width / s;
        hh = r.height / s;
      }
      const pt = screenToCanvas(clientX, clientY);
      const handles = [
        { dir: "nw", cx: hx, cy: hy },
        { dir: "n",  cx: hx + hw / 2, cy: hy },
        { dir: "ne", cx: hx + hw, cy: hy },
        { dir: "e",  cx: hx + hw, cy: hy + hh / 2 },
        { dir: "se", cx: hx + hw, cy: hy + hh },
        { dir: "s",  cx: hx + hw / 2, cy: hy + hh },
        { dir: "sw", cx: hx, cy: hy + hh },
        { dir: "w",  cx: hx, cy: hy + hh / 2 },
      ];
      // радиус хита постоянный экранный (6px) независимо от зума
      const HS = Math.max(4, 6 / scale());
      for (const h of handles) {
        if (Math.abs(pt.x - h.cx) <= HS && Math.abs(pt.y - h.cy) <= HS) {
          return h.dir;
        }
      }
      return null;
    }

    /* --- smart guides + distance labels --- */

    const SNAP_THRESHOLD = 4; // px в экранных координатах

    /** Вычисляет alignment guides для перемещаемого элемента.
     *  Возвращает { guides: [{axis:'h'|'v', pos:number}], snaps: {dx,dy}, distances: [{...}] } */
    function computeGuides(movingRef, movingRect) {
      // порог в canvas-координатах: 4 экранных px при любом зуме
      // (при зуме 0.15 прежние 4 canvas-px превращались в 0.6 экранных — snap не работал)
      const snapThr = SNAP_THRESHOLD / scale();
      const targets = collectHitTargets().filter(t => refKey(t.ref) !== refKey(movingRef));
      const guides = [];
      const distances = [];
      let snapDx = 0, snapDy = 0;
      let bestDx = Infinity, bestDy = Infinity;

      // края и центры moving-элемента
      const mL = movingRect.x, mR = movingRect.x + movingRect.w;
      const mCx = movingRect.x + movingRect.w / 2;
      const mT = movingRect.y, mB = movingRect.y + movingRect.h;
      const mCy = movingRect.y + movingRect.h / 2;

      const mEdgesX = [mL, mCx, mR];
      const mEdgesY = [mT, mCy, mB];

      for (const t of targets) {
        const tL = t.x, tR = t.x + t.w;
        const tCx = t.x + t.w / 2;
        const tT = t.y, tB = t.y + t.h;
        const tCy = t.y + t.h / 2;

        const tEdgesX = [tL, tCx, tR];
        const tEdgesY = [tT, tCy, tB];

        // вертикальные guides (alignment по X)
        for (const mx of mEdgesX) {
          for (const tx of tEdgesX) {
            const diff = tx - mx;
            if (Math.abs(diff) < snapThr && Math.abs(diff) < Math.abs(bestDx)) {
              bestDx = diff;
              snapDx = diff;
              guides.push({ axis: "v", pos: tx });
            }
          }
        }

        // горизонтальные guides (alignment по Y)
        for (const my of mEdgesY) {
          for (const ty of tEdgesY) {
            const diff = ty - my;
            if (Math.abs(diff) < snapThr && Math.abs(diff) < Math.abs(bestDy)) {
              bestDy = diff;
              snapDy = diff;
              guides.push({ axis: "h", pos: ty });
            }
          }
        }

        // distance labels: расстояние до ближайшего соседа по каждой стороне
        // горизонтальное расстояние (moving справа от target или слева)
        if (mCy > tT && mCy < tB) { // вертикально пересекаются
          if (mL > tR) {
            const gap = mL - tR;
            if (gap > 0 && gap < 200) distances.push({ type: "h", from: tR, to: mL, y: mCy, val: gap });
          } else if (mR < tL) {
            const gap = tL - mR;
            if (gap > 0 && gap < 200) distances.push({ type: "h", from: mR, to: tL, y: mCy, val: gap });
          }
        }
        // вертикальное расстояние
        if (mCx > tL && mCx < tR) { // горизонтально пересекаются
          if (mT > tB) {
            const gap = mT - tB;
            if (gap > 0 && gap < 200) distances.push({ type: "v", from: tB, to: mT, x: mCx, val: gap });
          } else if (mB < tT) {
            const gap = tT - mB;
            if (gap > 0 && gap < 200) distances.push({ type: "v", from: mB, to: tT, x: mCx, val: gap });
          }
        }
      }

      // дедупликация guides
      const seen = new Set();
      const uniqueGuides = guides.filter(g => {
        const k = g.axis + ":" + Math.round(g.pos);
        if (seen.has(k)) return false;
        seen.add(k);
        return true;
      });

      // оставить только ближайшие distance по каждой стороне
      const closestDist = {};
      distances.forEach(d => {
        const k = d.type + ":" + (d.type === "h" ? "y" + Math.round(d.y) : "x" + Math.round(d.x));
        if (!closestDist[k] || d.val < closestDist[k].val) closestDist[k] = d;
      });

      // equal spacing: фиолетовые метки, когда зазор рядом с moving равен соседнему
      // (3+ элементов в ряду/колонке; допуск — snap-порог в экранных px, как у snap)
      const eq = [];
      const eqSeen = new Set();
      // ряд/колонка — только сиблинги moving (как в Figma: равные зазоры между
      // братьями); вложенные элементы чужих контейнеров не дробят зазоры
      const eqPar = parentOf(movingRef);
      const sibKeys = new Set();
      if (eqPar) {
        eqPar.siblings.forEach((sib, j) => {
          const r = eqPar.isRoot ? { secIdx: j, path: null }
                                 : { secIdx: eqPar.secIdx, path: siblingPath(eqPar, j) };
          sibKeys.add(refKey(r));
        });
      }
      function eqMembers(axis) {
        const mates = targets.filter(t => {
          if (!sibKeys.has(refKey(t.ref))) return false;
          const overlap = axis === "h"
            ? Math.min(mB, t.y + t.h) - Math.max(mT, t.y)
            : Math.min(mR, t.x + t.w) - Math.max(mL, t.x);
          return overlap > 0;
        });
        const self = { x: movingRect.x, y: movingRect.y, w: movingRect.w, h: movingRect.h, _moving: true };
        const list = mates.concat([self]);
        list.sort((a, b) => (axis === "h" ? a.x - b.x : a.y - b.y));
        return list;
      }
      function pushEqRegion(type, a, b, gap) {
        // регион — сам зазор; поперечный диапазон — пересечение элементов,
        // при его отсутствии — диапазон moving
        let from, to, c0, c1;
        if (type === "h") {
          from = a.x + a.w; to = b.x;
          c0 = Math.max(a.y, b.y); c1 = Math.min(a.y + a.h, b.y + b.h);
          if (c1 - c0 < 2) { c0 = mT; c1 = mB; }
        } else {
          from = a.y + a.h; to = b.y;
          c0 = Math.max(a.x, b.x); c1 = Math.min(a.x + a.w, b.x + b.w);
          if (c1 - c0 < 2) { c0 = mL; c1 = mR; }
        }
        const key = type + ":" + Math.round(from) + ":" + Math.round(to);
        if (eqSeen.has(key)) return;
        eqSeen.add(key);
        eq.push({ type, from, to, cross0: c0, cross1: c1, val: gap });
      }
      ["h", "v"].forEach(axis => {
        const members = eqMembers(axis);
        if (members.length < 3) return;
        const gaps = [];
        for (let j = 0; j + 1 < members.length; j++) {
          gaps.push(axis === "h"
            ? members[j + 1].x - (members[j].x + members[j].w)
            : members[j + 1].y - (members[j].y + members[j].h));
        }
        const mi = members.findIndex(m => m._moving);
        for (let j = 0; j + 1 < gaps.length; j++) {
          // пара смежных зазоров должна касаться moving (он в одном из трёх элементов)
          if (mi < j || mi > j + 2) continue;
          const g1 = gaps[j], g2 = gaps[j + 1];
          if (g1 > 0.5 && g2 > 0.5 && Math.abs(g1 - g2) <= snapThr) {
            pushEqRegion(axis, members[j], members[j + 1], g1);
            pushEqRegion(axis, members[j + 1], members[j + 2], g2);
          }
        }
      });

      return { guides: uniqueGuides, snaps: { dx: snapDx, dy: snapDy }, distances: Object.values(closestDist), eq };
    }

    function renderGuides(guidesData) {
      // очистить предыдущие
      overlay().querySelectorAll(".geo-guide, .geo-dist, .geo-dist-line, .geo-eq, .geo-eq-label").forEach(el => el.remove());
      if (!guidesData) return;

      // guides/eq/dist приходят в canvas-координатах; оверлей может жить вне
      // transform артборда (нода Edit) — переводим в координаты оверлея через k
      const k = canvasK();
      const inv = 1 / overlayScale(); // экранные смещения меток в координатах оверлея
      guidesData.guides.forEach(g => {
        const el = document.createElement("div");
        el.className = "geo-guide " + (g.axis === "h" ? "geo-guide-h" : "geo-guide-v");
        if (g.axis === "h") el.style.top = (g.pos * k) + "px";
        else el.style.left = (g.pos * k) + "px";
        overlay().appendChild(el);
      });

      // зелёные distance labels + линии
      guidesData.distances.forEach(d => {
        // линия
        const line = document.createElement("div");
        line.className = "geo-dist-line " + (d.type === "h" ? "geo-dist-line-h" : "geo-dist-line-v");
        if (d.type === "h") {
          line.style.left = (d.from * k) + "px";
          line.style.width = ((d.to - d.from) * k) + "px";
          line.style.top = (d.y * k) + "px";
        } else {
          line.style.top = (d.from * k) + "px";
          line.style.height = ((d.to - d.from) * k) + "px";
          line.style.left = (d.x * k) + "px";
        }
        overlay().appendChild(line);

        // метка
        const label = document.createElement("div");
        label.className = "geo-dist";
        label.textContent = Math.round(d.val) + "px";
        if (d.type === "h") {
          label.style.left = ((d.from + d.to) / 2 * k - 12 * inv) + "px";
          label.style.top = (d.y * k - 12 * inv) + "px";
        } else {
          label.style.left = (d.x * k + 4 * inv) + "px";
          label.style.top = ((d.from + d.to) / 2 * k - 6 * inv) + "px";
        }
        overlay().appendChild(label);
      });

      // фиолетовые equal-spacing регионы и метки
      (guidesData.eq || []).forEach(d => {
        const region = document.createElement("div");
        region.className = "geo-eq";
        if (d.type === "h") {
          region.style.left = (d.from * k) + "px";
          region.style.width = (Math.max(1, d.to - d.from) * k) + "px";
          region.style.top = (d.cross0 * k) + "px";
          region.style.height = (Math.max(2, d.cross1 - d.cross0) * k) + "px";
        } else {
          region.style.top = (d.from * k) + "px";
          region.style.height = (Math.max(1, d.to - d.from) * k) + "px";
          region.style.left = (d.cross0 * k) + "px";
          region.style.width = (Math.max(2, d.cross1 - d.cross0) * k) + "px";
        }
        overlay().appendChild(region);

        const label = document.createElement("div");
        label.className = "geo-eq-label";
        label.textContent = Math.round(d.val) + "px";
        if (d.type === "h") {
          label.style.left = ((d.from + d.to) / 2 * k - 12 * inv) + "px";
          label.style.top = (d.cross0 * k - 12 * inv) + "px";
        } else {
          label.style.left = (d.cross0 * k + 4 * inv) + "px";
          label.style.top = ((d.from + d.to) / 2 * k - 6 * inv) + "px";
        }
        overlay().appendChild(label);
      });
    }

    function clearGuides() {
      overlay().querySelectorAll(".geo-guide, .geo-dist, .geo-dist-line, .geo-eq, .geo-eq-label").forEach(el => el.remove());
    }

    function parentOf(ref) {
      const ir = getIR();
      if (ref.secIdx == null) return null;
      if (ref.path == null) {
        return { node: ir, siblings: ir.tree, dom: artboardEl(), isRoot: true };
      }
      const keys = ref.path.split(".");
      keys.pop(); keys.pop();
      const parentPath = keys.join(".");
      const sec = ir.tree[ref.secIdx];
      const parentNode = parentPath ? getByPath(sec, parentPath) : sec;
      const parentDom = domAt(parentPath ? { secIdx: ref.secIdx, path: parentPath }
                                         : { secIdx: ref.secIdx, path: null });
      return { node: parentNode, siblings: (parentNode && parentNode.children) || [],
               dom: parentDom, parentPath, secIdx: ref.secIdx };
    }

    function siblingDom(parent, j) {
      if (parent.isRoot) return previewEl.querySelector(`[data-ir-sec="${j}"]`);
      const prefix = parent.parentPath ? parent.parentPath + "." : "";
      return domAt({ secIdx: parent.secIdx, path: prefix + "children." + j });
    }

    function siblingPath(parent, j) {
      if (parent.isRoot) return null;
      return parent.parentPath ? parent.parentPath + ".children." + j : "children." + j;
    }

    function refKey(ref) {
      return ref.secIdx + ":" + (ref.path || "");
    }

    /* --- оверлей --- */

    function overlay() {
      let ov = previewEl.querySelector(":scope > .geo-overlay");
      if (!ov) {
        ov = document.createElement("div");
        ov.className = "geo-overlay";
        ov.innerHTML = '<div class="geo-box hover" hidden></div><div class="geo-sel-container"></div>';
        previewEl.appendChild(ov);
      }
      // Cover the full content size so zoomed/panned source blocks are still
      // interactable even when the transformed bounding box is smaller than
      // the viewport.
      ov.style.width = Math.max(previewEl.scrollWidth, previewEl.offsetWidth) + "px";
      ov.style.height = Math.max(previewEl.scrollHeight, previewEl.offsetHeight) + "px";
      ov.dataset.tool = tool;
      syncZoom(ov);
      return ov;
    }

    /** Короткая подсказка об отказе операции (group и т.п.); исчезает сама. */
    function hint(text) {
      const el = document.createElement("div");
      el.className = "geo-hint";
      el.textContent = text;
      overlay().appendChild(el);
      setTimeout(() => el.remove(), 2500);
    }

    /** Компенсация зума: экранные размеры ручек/чипов постоянны при любом scale.
     *  Зависят от собственного transform оверлея, а не от зума артборда. */
    function syncZoom(ov) {
      (ov || overlay()).style.setProperty("--geo-inv", String(1 / overlayScale()));
    }

    function selContainer() {
      return overlay().querySelector(".geo-sel-container");
    }

    function boxRect(el) {
      const base = previewEl.getBoundingClientRect();
      const r = el.getBoundingClientRect();
      // previewEl может иметь transform: scale(zoom) — оверлей в локальных координатах
      const ow = previewEl.offsetWidth;
      const s = ow > 0 ? previewEl.getBoundingClientRect().width / ow : 1;
      return { left: (r.left - base.left) / s, top: (r.top - base.top) / s,
               width: r.width / s, height: r.height / s };
    }

    function placeBox(box, r) {
      box.style.left = r.left + "px";
      box.style.top = r.top + "px";
      box.style.width = r.width + "px";
      box.style.height = r.height + "px";
      box.hidden = false;
    }

    function chipText(ref) {
      const f = (irNodeAt(ref) || {}).frame || {};
      const el = domAt(ref);
      const s = scale();
      const w = typeof f.width === "number" ? f.width : el ? Math.round(el.getBoundingClientRect().width / s) : "?";
      const h = typeof f.height === "number" ? f.height : el ? Math.round(el.getBoundingClientRect().height / s) : "?";
      return `${labelOf(ref)} · ${w}×${h}`;
    }

    function addHandles(box) {
      ["nw", "n", "ne", "e", "se", "s", "sw", "w"].forEach(d => {
        const h = document.createElement("span");
        h.className = "geo-h h-" + d;
        h.dataset.dir = d;
        box.appendChild(h);
      });
    }

    /** Объединяющий прямоугольник выделения в координатах оверлея (или null). */
    function selectionUnionBox() {
      let u = null;
      selections.forEach(sel => {
        const el = domAt(sel.ref);
        if (!el) return;
        const r = boxRect(el);
        if (!u) { u = { left: r.left, top: r.top, right: r.left + r.width, bottom: r.top + r.height }; return; }
        u.left = Math.min(u.left, r.left); u.top = Math.min(u.top, r.top);
        u.right = Math.max(u.right, r.left + r.width); u.bottom = Math.max(u.bottom, r.top + r.height);
      });
      return u && { left: u.left, top: u.top, width: u.right - u.left, height: u.bottom - u.top };
    }

    /** Перерисовка всех боксов выделения. При мультивыделении ручки resize —
     *  на объединяющей рамке (resize масштабирует все выделенные пропорционально). */
    function renderSelectionBoxes() {
      const cont = selContainer();
      cont.innerHTML = "";
      const multi = selections.length > 1;
      selections.forEach((sel, i) => {
        const el = domAt(sel.ref);
        if (!el) return;
        const box = document.createElement("div");
        box.className = "geo-box selected";
        box.dataset.idx = i;
        const chip = document.createElement("span");
        chip.className = "geo-chip";
        chip.textContent = chipText(sel.ref);
        box.appendChild(chip);
        if (!multi && i === selections.length - 1) addHandles(box);
        placeBox(box, boxRect(el));
        cont.appendChild(box);
      });
      if (multi) {
        const u = selectionUnionBox();
        if (u) {
          // без chip: внешние счётчики (.geo-box.selected .geo-chip) не должны
          // видеть объединяющую рамку как лишний выделенный элемент
          const box = document.createElement("div");
          box.className = "geo-box selected geo-union";
          addHandles(box);
          placeBox(box, u);
          cont.appendChild(box);
        }
      }
    }

    function hideHover() {
      const box = overlay().querySelector(".geo-box.hover");
      if (box) box.hidden = true;
    }

    function onHover(e) {
      if (drag || marquee) return;
      const box = overlay().querySelector(".geo-box.hover");
      // геометрический hit-test вместо DOM event target
      const ref = hitTest(e.clientX, e.clientY);
      if (!ref || selections.some(s => refKey(s.ref) === refKey(ref))) {
        box.hidden = true;
        overlay().style.cursor = "default";
        return;
      }
      const el = domAt(ref);
      if (el) {
        placeBox(box, boxRect(el));
        overlay().style.cursor = "move";
      }
    }

    /* --- выделение --- */

    function select(ref) {
      if (!ref) return clear();
      const node = irNodeAt(ref);
      if (!node) return clear();
      selections = [{ ref, label: labelOf(ref), node }];
      renderSelectionBoxes();
      scheduleBoxSync();
      hideHover();
      if (onSelect) onSelect(selections);
    }

    function selectMulti(refs) {
      selections = [];
      const seen = new Set();
      refs.forEach(ref => {
        const k = refKey(ref);
        if (seen.has(k)) return;
        seen.add(k);
        const node = irNodeAt(ref);
        if (!node) return;
        selections.push({ ref, label: labelOf(ref), node });
      });
      renderSelectionBoxes();
      scheduleBoxSync();
      hideHover();
      if (onSelect) onSelect(selections);
    }

    function toggleSelect(ref) {
      const k = refKey(ref);
      const idx = selections.findIndex(s => refKey(s.ref) === k);
      if (idx >= 0) {
        selections.splice(idx, 1);
      } else {
        const node = irNodeAt(ref);
        if (node) selections.push({ ref, label: labelOf(ref), node });
      }
      renderSelectionBoxes();
      scheduleBoxSync();
      hideHover();
      if (onSelect) onSelect(selections);
    }

    function clear() {
      if (!selections.length) return;
      selections = [];
      renderSelectionBoxes();
      if (onSelect) onSelect(selections);
    }

    /* --- marquee (резиновое выделение) --- */

    function startMarquee(e) {
      const base = previewEl.getBoundingClientRect();
      const s = scale();
      marquee = {
        startX: (e.clientX - base.left) / s,
        startY: (e.clientY - base.top) / s,
        shiftKey: e.shiftKey,
        prevSelections: e.shiftKey ? selections.slice() : [],
      };
      const rect = document.createElement("div");
      rect.className = "geo-marquee";
      overlay().appendChild(rect);
      marquee.el = rect;
      overlay().setPointerCapture(e.pointerId);
      overlay().addEventListener("pointermove", onMarqueeMove);
      overlay().addEventListener("pointerup", onMarqueeUp, { once: true });
    }

    function onMarqueeMove(e) {
      if (!marquee) return;
      const base = previewEl.getBoundingClientRect();
      const s = scale();
      const cx = (e.clientX - base.left) / s, cy = (e.clientY - base.top) / s;
      const x = Math.min(marquee.startX, cx), y = Math.min(marquee.startY, cy);
      const w = Math.abs(cx - marquee.startX), h = Math.abs(cy - marquee.startY);
      const el = marquee.el;
      const k = canvasK(); // canvas → координаты оверлея
      el.style.left = (x * k) + "px"; el.style.top = (y * k) + "px";
      el.style.width = (w * k) + "px"; el.style.height = (h * k) + "px";
    }

    function onMarqueeUp(e) {
      overlay().removeEventListener("pointermove", onMarqueeMove);
      try { overlay().releasePointerCapture(e.pointerId); } catch (_) {}
      if (!marquee) return;
      const base = previewEl.getBoundingClientRect();
      const s = scale();
      const cx = (e.clientX - base.left) / s, cy = (e.clientY - base.top) / s;
      const mx = Math.min(marquee.startX, cx), my = Math.min(marquee.startY, cy);
      const mw = Math.abs(cx - marquee.startX), mh = Math.abs(cy - marquee.startY);
      if (marquee.el) marquee.el.remove();

      if (mw < 4 / s && mh < 4 / s) {
        marquee = null;
        clear();
        return;
      }

      // кандидаты — единый источник collectHitTargets (секции, children любой
      // глубины, props-элементы). Секции и children глубины 1 берутся по
      // пересечению (прежнее поведение), вложенные и props — только полностью
      // внутри marquee, как в Figma
      const hits = [];
      collectHitTargets().forEach(t => {
        if (skipLocked(t.ref)) return; // залоченные слои не выделяются marquee
        const shallow = t.ref.path === null || /^children\.\d+$/.test(t.ref.path);
        const inside = t.x >= mx && t.y >= my && t.x + t.w <= mx + mw && t.y + t.h <= my + mh;
        if (!inside && !shallow) return;
        const intersects = t.x < mx + mw && t.x + t.w > mx && t.y < my + mh && t.y + t.h > my;
        if (inside || (shallow && intersects)) hits.push(t.ref);
      });

      if (marquee.shiftKey) {
        const merged = marquee.prevSelections.slice();
        const seen = new Set(merged.map(s => refKey(s.ref)));
        hits.forEach(ref => {
          const k = refKey(ref);
          if (!seen.has(k)) { seen.add(k); merged.push(ref); }
        });
        selectMulti(merged.map(s => s.ref || s));
      } else {
        selectMulti(hits);
      }
      marquee = null;
    }

    /* ---------- инструменты: hand (скролл) и rect/text/frame (создание), как в pen.dev ---------- */

    function setTool(t) {
      tool = t;
      overlay().dataset.tool = t;
      if (t !== "select") clearGuides();
      if (onToolChange) onToolChange(t);
    }

    function startHand(e) {
      const sc = scrollEl || previewEl;
      hand = { sx: e.clientX, sy: e.clientY, sl: sc.scrollLeft, st: sc.scrollTop };
      overlay().setPointerCapture(e.pointerId);
      overlay().addEventListener("pointermove", onHandMove);
      overlay().addEventListener("pointerup", onHandUp, { once: true });
      overlay().classList.add("geo-handling");
    }

    function onHandMove(e) {
      if (!hand) return;
      const sc = scrollEl || previewEl;
      sc.scrollLeft = hand.sl - (e.clientX - hand.sx);
      sc.scrollTop = hand.st - (e.clientY - hand.sy);
    }

    function onHandUp(e) {
      overlay().removeEventListener("pointermove", onHandMove);
      try { overlay().releasePointerCapture(e.pointerId); } catch (_) {}
      overlay().classList.remove("geo-handling");
      hand = null;
    }

    /** Глубочайший контейнер под точкой (секция или card); на корне не создаём. */
    function containerAt(pt) {
      const targets = collectHitTargets();
      for (let i = targets.length - 1; i >= 0; i--) {
        const t = targets[i];
        if (!(pt.x >= t.x && pt.x <= t.x + t.w && pt.y >= t.y && pt.y <= t.y + t.h)) continue;
        if (t.ref.secIdx == null) continue;
        const node = irNodeAt(t.ref);
        if (node && (t.ref.path == null || node.type === "card" || Array.isArray(node.children))) {
          return t;
        }
      }
      return null;
    }

    /** Фолбэк для startCreate: под курсором нет контейнера (пустое место артборда) —
     *  рисуем в корневую секцию. Возвращает target в формате collectHitTargets. */
    function rootSectionFallback(pt) {
      const ir = getIR();
      if (!ir || !ir.tree || !ir.tree.length) return null;
      const board = artboardEl();
      const secEl = previewEl.querySelector('[data-ir-sec="0"]');
      if (!board || !secEl) return null;
      // только если точка внутри артборда — клик по серому канвасу вокруг не создаёт элементы
      const base = previewEl.getBoundingClientRect();
      const s = scale();
      const br = board.getBoundingClientRect();
      const bx = (br.left - base.left ) / s;
      const by = (br.top - base.top ) / s;
      if (!(pt.x >= bx && pt.x <= bx + br.width / s && pt.y >= by && pt.y <= by + br.height / s)) return null;
      const r = secEl.getBoundingClientRect();
      return {
        ref: { secIdx: 0, path: null },
        x: (r.left - base.left ) / s,
        y: (r.top - base.top ) / s,
        w: r.width / s,
        h: r.height / s,
      };
    }

    function startCreate(e) {
      const pt = screenToCanvas(e.clientX, e.clientY);
      const cont = containerAt(pt) || rootSectionFallback(pt);
      if (!cont) return;
      const el = document.createElement("div");
      el.className = "geo-marquee";
      overlay().appendChild(el);
      create = { start: pt, cont, el };
      overlay().setPointerCapture(e.pointerId);
      overlay().addEventListener("pointermove", onCreateMove);
      overlay().addEventListener("pointerup", onCreateUp, { once: true });
    }

    function onCreateMove(e) {
      if (!create) return;
      const pt = screenToCanvas(e.clientX, e.clientY);
      const x = Math.min(create.start.x, pt.x), y = Math.min(create.start.y, pt.y);
      const w = Math.abs(pt.x - create.start.x), h = Math.abs(pt.y - create.start.y);
      const k = canvasK(); // canvas → координаты оверлея
      create.el.style.left = (x * k) + "px"; create.el.style.top = (y * k) + "px";
      create.el.style.width = (w * k) + "px"; create.el.style.height = (h * k) + "px";
    }

    function onCreateUp(e) {
      overlay().removeEventListener("pointermove", onCreateMove);
      try { overlay().releasePointerCapture(e.pointerId); } catch (_) {}
      if (!create) return;
      const pt = screenToCanvas(e.clientX, e.clientY);
      const rx = Math.min(create.start.x, pt.x), ry = Math.min(create.start.y, pt.y);
      const rw = Math.abs(pt.x - create.start.x), rh = Math.abs(pt.y - create.start.y);
      const clicked = rw < 6 && rh < 6;
      const cont = create.cont;
      const contNode = irNodeAt(cont.ref);
      create.el.remove();
      create = null;
      if (!contNode) return;

      onCommit();
      const parentFree = !!(contNode.frame && contNode.frame.layout === "free");
      // x/y нового элемента — от padding-box контейнера (контракт frame.x/y)
      const contEl = domAt(cont.ref);
      const contCs = contEl ? getComputedStyle(contEl) : null;
      const cbl = contCs ? parseFloat(contCs.borderLeftWidth) || 0 : 0;
      const cbt = contCs ? parseFloat(contCs.borderTopWidth) || 0 : 0;
      const fr = { x: Math.round(rx - cont.x - cbl), y: Math.round(ry - cont.y - cbt) };
      // как в pen.dev: layoutPosition:absolute — новый элемент не ломает раскладку родителя
      if (!parentFree) fr.absolute = true;
      let child;
      if (tool === "rect") {
        fr.width = Math.round(clicked ? 120 : Math.max(16, rw));
        fr.height = Math.round(clicked ? 90 : Math.max(16, rh));
        child = { type: "rect", sourceKey: nextUid(), fill: "#8B5CF6", radius: 8, frame: fr };
      } else if (tool === "ellipse") {
        // как rect, но pill/эллипс: renderer читает node.radius
        fr.width = Math.round(clicked ? 120 : Math.max(16, rw));
        fr.height = Math.round(clicked ? 90 : Math.max(16, rh));
        child = { type: "rect", sourceKey: nextUid(), fill: "#8B5CF6", radius: 9999, frame: fr };
      } else if (tool === "line") {
        // линия — тонкий rect; доминантная ось drag'а задаёт направление
        const horizontal = clicked || rw >= rh;
        if (horizontal) { fr.width = Math.round(clicked ? 120 : Math.max(8, rw)); fr.height = 2; }
        else { fr.width = 2; fr.height = Math.round(Math.max(8, rh)); }
        child = { type: "rect", sourceKey: nextUid(), fill: "#6b7280", frame: fr };
      } else if (tool === "image") {
        fr.width = Math.round(clicked ? 240 : Math.max(40, rw));
        fr.height = Math.round(clicked ? 160 : Math.max(40, rh));
        child = { type: "image", sourceKey: nextUid(), alt: "изображение", frame: fr };
      } else if (tool === "text") {
        child = { type: "text", sourceKey: nextUid(), text: "Новый текст", frame: fr };
      } else {
        fr.width = Math.round(clicked ? 240 : Math.max(40, rw));
        fr.height = Math.round(clicked ? 160 : Math.max(40, rh));
        child = { type: "card", sourceKey: nextUid(), children: [], frame: fr };
      }
      contNode.children = contNode.children || [];
      contNode.children.push(child);
      const newPath = (cont.ref.path ? cont.ref.path + "." : "") + "children." + (contNode.children.length - 1);
      selections = [];
      select({ secIdx: cont.ref.secIdx, path: newPath });
      onMutated();
    }

    /* --- мутации IR --- */

    function relPos(el, baseEl) {
      const s = scale();
      const base = baseEl.getBoundingClientRect();
      const r = el.getBoundingClientRect();
      // контракт frame.x/y — от padding-box родителя (как у CSS absolute),
      // поэтому вычитаем border, а не padding
      const cs = getComputedStyle(baseEl);
      const bl = parseFloat(cs.borderLeftWidth) || 0, bt = parseFloat(cs.borderTopWidth) || 0;
      return { x: Math.round((r.left - base.left) / s - bl),
               y: Math.round((r.top - base.top) / s - bt) };
    }

    /** Конвертация родителя в free-layout: измеряем позиции всех детей ДО
     *  перерендера, записываем их во frame и возвращаем массив измеренных
     *  позиций (по индексу сиблинга). Общая для ensureParentFree/commitMoveFor. */
    function makeParentFree(parent) {
      const s = scale();
      const cs = getComputedStyle(parent.dom);
      const bl = parseFloat(cs.borderLeftWidth) || 0, bt = parseFloat(cs.borderTopWidth) || 0;
      // измеряем всё разом: DOM ещё в состоянии до конвертации. Координаты —
      // от padding-box родителя: единый контракт frame.x/y (как у CSS absolute)
      const base = parent.dom.getBoundingClientRect();
      const measured = parent.siblings.map((sib, j) => {
        const sibEl = siblingDom(parent, j);
        if (!sibEl) return null;
        const r = sibEl.getBoundingClientRect();
        return { x: Math.round((r.left - base.left) / s - bl),
                 y: Math.round((r.top - base.top) / s - bt),
                 w: Math.round(r.width / s), h: Math.round(r.height / s) };
      });
      parent.siblings.forEach((sib, j) => {
        const m = measured[j];
        if (!m) return;
        // root-родитель: сиблинг — секция с ref {secIdx: j}; иначе — путь внутри секции
        const sibRef = parent.isRoot ? { secIdx: j, path: null }
                                     : { secIdx: parent.secIdx, path: siblingPath(parent, j) };
        const sf = Object.assign({}, getFrame(sibRef));
        if (typeof sf.x !== "number") sf.x = m.x;
        if (typeof sf.y !== "number") sf.y = m.y;
        // fill у absolute-ребёнка тянется на весь padding-box родителя — это другая
        // семантика, чем в раскладке; фиксируем измеренный размер, чтобы конверсия
        // не «ломала» геометрию (баг «при перетаскивании всё ломается»)
        if (sf.width === "fill") sf.width = m.w;
        if (sf.height === "fill") sf.height = m.h;
        setFrameData(sibRef, sf);
      });
      // дефолтный padding секции при конверсии в free сохраняет рендерер (sec-free)
      parent.node.frame = Object.assign({}, parent.node.frame, {
        layout: "free",
        // frame у родителя может отсутствовать (свежий IR от LLM) — берём измеренную высоту
        height: (parent.node.frame && parent.node.frame.height) || Math.round(parent.dom.getBoundingClientRect().height / s),
      });
      return measured;
    }

    function ensureParentFree(ref) {
      const parent = parentOf(ref);
      if (!parent || !parent.dom || !parent.node) return;
      if (parent.node.frame && parent.node.frame.layout === "free") return;
      makeParentFree(parent);
    }

    function commitMoveFor(d, dx, dy) {
      const parent = parentOf(d.ref);
      if (!parent || !parent.dom || !parent.node) return;
      if (parent.node.frame && parent.node.frame.layout === "free") {
        // НЕ используем relPos — на элементе висит CSS transform от drag,
        // что даст двойное смещение. Берём текущее значение frame + delta.
        const f = Object.assign({}, getFrame(d.ref));
        f.x = Math.round((typeof f.x === "number" ? f.x : 0) + dx);
        f.y = Math.round((typeof f.y === "number" ? f.y : 0) + dy);
        setFrameData(d.ref, f);
        return;
      }
      // родитель не free — dragged-ребёнок покидает поток (absolute), родитель
      // остаётся auto (Figma/pen.dev): сиблинги не трогаем, padding в IR не пишем.
      // Исключение — корень: секцию нельзя выводить в absolute, пока артборд не
      // free (он тогда не позиционированный якорь) — корень конвертируем в free.
      if (parent.isRoot) {
        const measured = makeParentFree(parent);
        const mr = measured[parent.siblings.indexOf(irNodeAt(d.ref))] || null;
        const fr = Object.assign({}, getFrame(d.ref));
        fr.x = Math.round((mr ? mr.x : (typeof fr.x === "number" ? fr.x : 0)) + dx);
        fr.y = Math.round((mr ? mr.y : (typeof fr.y === "number" ? fr.y : 0)) + dy);
        setFrameData(d.ref, fr);
        return;
      }
      const childDom = domAt(d.ref);
      // измеренная позиция (padding-box родителя), а не старый frame:
      // в auto-раскладке x/y может не быть, и элемент телепортировался бы в начало координат
      const m = childDom ? relPos(childDom, parent.dom) : null;
      const f = Object.assign({}, getFrame(d.ref));
      const bx = m ? m.x : (typeof f.x === "number" ? f.x : 0);
      const by = m ? m.y : (typeof f.y === "number" ? f.y : 0);
      if (childDom) {
        // fill у absolute-ребёнка тянется на весь padding-box родителя — другая семантика,
        // чем в раскладке; фиксируем измеренный размер, иначе «при перетаскивании всё ломается»
        const rect = childDom.getBoundingClientRect();
        const s = scale();
        if (f.width === "fill") f.width = Math.round(rect.width / s);
        if (f.height === "fill") f.height = Math.round(rect.height / s);
      }
      f.absolute = true;
      f.x = Math.round(bx + dx);
      f.y = Math.round(by + dy);
      setFrameData(d.ref, f);
    }

    function commitMoveAll(dx, dy) {
      onCommit();
      const movedRefs = selections.filter(s => s.ref.secIdx != null);
      movedRefs.forEach(sel => {
        commitMoveFor({ ref: sel.ref }, dx, dy);
      });
      onMutated();
    }

    function liveResize(d, dx, dy) {
      const dir = d.dir;
      let w = d.w0, h = d.h0, tx = 0, ty = 0;
      if (dir.includes("e")) w = d.w0 + dx;
      if (dir.includes("s")) h = d.h0 + dy;
      if (dir.includes("w")) { w = d.w0 - dx; tx = dx; }
      if (dir.includes("n")) { h = d.h0 - dy; ty = dy; }
      w = Math.max(8, w); h = Math.max(8, h);
      // в auto-родителе commitResize сдвиг x/y не коммитит — не показываем его
      // и в live-превью, иначе превью расходится с результатом
      const parent = parentOf(d.ref);
      if (!parent || !parent.node.frame || parent.node.frame.layout !== "free") { tx = 0; ty = 0; }
      d.wLive = w; d.hLive = h; d.txLive = tx; d.tyLive = ty;
      d.el.style.width = w + "px";
      d.el.style.height = h + "px";
      d.el.style.transform = (tx || ty) ? `translate(${tx}px, ${ty}px)` : "";
      const chip = overlay().querySelector(".geo-box.selected:last-child .geo-chip");
      if (chip) chip.textContent = `${Math.round(w)}×${Math.round(h)}`;
    }

    function commitResize(d) {
      const node = irNodeAt(d.ref);
      if (!node || d.wLive == null) { onMutated(); return; }
      onCommit();
      const f = Object.assign({}, getFrame(d.ref));
      const oldW = (typeof f.width === "number") ? f.width : d.w0;
      const oldH = (typeof f.height === "number") ? f.height : d.h0;
      f.width = Math.round(d.wLive);
      f.height = Math.round(d.hLive);
      const parent = parentOf(d.ref);
      if (parent && parent.node.frame && parent.node.frame.layout === "free" && (d.txLive || d.tyLive)) {
        f.x = Math.round((typeof f.x === "number" ? f.x : 0) + d.txLive);
        f.y = Math.round((typeof f.y === "number" ? f.y : 0) + d.tyLive);
      }
      setFrameData(d.ref, f);
      applyConstraints(d.ref, oldW, oldH, f.width, f.height);
      onMutated();
    }

    /** Live-превью multi-resize: двигаем/растягиваем только объединяющую рамку. */
    function liveResizeMulti(d, dx, dy) {
      const dir = d.dir, u0 = d.union0;
      let w = u0.w, h = u0.h, tx = 0, ty = 0;
      if (dir.includes("e")) w = u0.w + dx;
      if (dir.includes("s")) h = u0.h + dy;
      if (dir.includes("w")) { w = u0.w - dx; tx = dx; }
      if (dir.includes("n")) { h = u0.h - dy; ty = dy; }
      w = Math.max(8, w); h = Math.max(8, h);
      d.wLive = w; d.hLive = h; d.txLive = tx; d.tyLive = ty;
      const k = canvasK(); // union0 в canvas-координатах, рамка — в координатах оверлея
      d.el.style.width = (w * k) + "px";
      d.el.style.height = (h * k) + "px";
      d.el.style.transform = (tx || ty) ? `translate(${tx * k}px, ${ty * k}px)` : "";
    }

    /** Коммит multi-resize: все выделенные узлы масштабируются пропорционально
     *  объединяющей рамке (позиции — дельтами, чтобы не зависеть от родителя). */
    function commitResizeMulti(d) {
      if (d.wLive == null) { onMutated(); return; }
      onCommit();
      const u0 = d.union0;
      const sx = u0.w > 0 ? d.wLive / u0.w : 1;
      const sy = u0.h > 0 ? d.hLive / u0.h : 1;
      const nx = u0.x + (d.txLive || 0), ny = u0.y + (d.tyLive || 0);
      d.items.forEach(it => {
        ensureParentFree(it.ref);
        const f = Object.assign({}, getFrame(it.ref));
        const baseX = typeof f.x === "number" ? f.x : 0;
        const baseY = typeof f.y === "number" ? f.y : 0;
        f.x = Math.round(baseX + nx + (it.x - u0.x) * sx - it.x);
        f.y = Math.round(baseY + ny + (it.y - u0.y) * sy - it.y);
        f.width = Math.max(1, Math.round(it.w * sx));
        f.height = Math.max(1, Math.round(it.h * sy));
        setFrameData(it.ref, f);
      });
      onMutated();
    }

    /** Constraints (модель Figma): как дети реагируют на resize родителя.
     *  child.frame.constraints = {h: left|center|right|scale, v: top|center|bottom|scale};
     *  по умолчанию left/top (ничего не делаем). Работает во free-родителях,
     *  где у детей есть x/y. */
    function applyConstraints(ref, oldW, oldH, newW, newH) {
      const node = irNodeAt(ref);
      if (!node || !node.children) return;
      const dw = newW - oldW, dh = newH - oldH;
      if (!dw && !dh) return;
      node.children.forEach(c => {
        const cf = c.frame;
        if (!cf || !cf.constraints) return;
        const cs = cf.constraints;
        const hasX = typeof cf.x === "number", hasY = typeof cf.y === "number";
        if (cs.h === "right" && hasX) cf.x = Math.round(cf.x + dw);
        else if (cs.h === "center" && hasX) cf.x = Math.round(cf.x + dw / 2);
        else if (cs.h === "scale" && oldW > 0) {
          if (hasX) cf.x = Math.round(cf.x * newW / oldW);
          if (typeof cf.width === "number") cf.width = Math.max(8, Math.round(cf.width * newW / oldW));
        }
        if (cs.v === "bottom" && hasY) cf.y = Math.round(cf.y + dh);
        else if (cs.v === "center" && hasY) cf.y = Math.round(cf.y + dh / 2);
        else if (cs.v === "scale" && oldH > 0) {
          if (hasY) cf.y = Math.round(cf.y * newH / oldH);
          if (typeof cf.height === "number") cf.height = Math.max(8, Math.round(cf.height * newH / oldH));
        }
      });
    }

    /* --- drag (плавный, через rAF) --- */

    function onPointerDown(e) {
      // клики внутри контекстного меню — его own pointer-events: не гасим
      // pointerdown (иначе suppress-ится совместимый click по пункту)
      if (ctxMenuEl && e.target instanceof Node && ctxMenuEl.contains(e.target)) return;
      if (e.button !== 0) return;
      e.preventDefault();
      e.stopPropagation();

      // инструменты панели (как левый тулбар pen.dev)
      if (tool === "hand") { startHand(e); return; }
      if (["rect", "text", "frame", "ellipse", "line", "image"].includes(tool)) { startCreate(e); return; }

      // 1) Проверяем resize-хендлы (геометрически)
      const handleDir = hitTestHandle(e.clientX, e.clientY);
      if (handleDir) {
        startResize(handleDir, e);
        return;
      }

      // 2) Геометрический hit-test по элементам
      const deep = !!(e.ctrlKey || e.metaKey);
      const ref = hitTest(e.clientX, e.clientY, deep);

      if (!ref) {
        // клик по пустому месту → marquee или deselect
        if (!e.shiftKey) clear();
        startMarquee(e);
        return;
      }

      // 3) Shift+клик → toggle selection (добавить/убрать, как в Figma)
      if (e.shiftKey) {
        toggleSelect(ref);
        return;
      }

      // 3.5) Ctrl/Cmd+клик — выделение точного элемента под курсором (без хоума
      // к контейнеру); повторный клик по тому же единственному выделению снимает
      // его (Figma-паттерн «выделил/отменил»). Ctrl+drag после этого тащит элемент.
      if (deep) {
        const k = refKey(ref);
        const already = selections.some(s => refKey(s.ref) === k);
        if (already && selections.length === 1) {
          clear();
          return; // сняли выделение — drag не нужен
        }
        if (!already) select(ref);
      } else {
        // 4) Клик по невыделенному → выделить
        const alreadySelected = selections.some(s => refKey(s.ref) === refKey(ref));
        if (!alreadySelected) {
          select(ref);
        }
      }

      // 5) Готовим drag (move); Alt+drag на drop создаст копию (как в Figma)
      drag = { startX: e.clientX, startY: e.clientY, moved: false, type: "move", els: [],
               altKey: e.altKey };
      // pointer capture для непрерывности drag
      overlay().setPointerCapture(e.pointerId);
      overlay().addEventListener("pointermove", onDragMove);
      overlay().addEventListener("pointerup", onDragUp, { once: true });
    }

    function startResize(dir, e) {
      if (!selections.length) return;
      e.preventDefault();
      if (selections.length > 1) {
        // мультивыделение: resize объединяющей рамки, коммит масштабирует все узлы
        const rects = selectedRects()
          .filter(r => r.ref.path == null || r.ref.path.startsWith("children."));
        if (rects.length < 2) return;
        const ux = Math.min(...rects.map(r => r.x));
        const uy = Math.min(...rects.map(r => r.y));
        drag = { type: "resize-multi", dir, startX: e.clientX, startY: e.clientY, moved: true,
                 union0: { x: ux, y: uy,
                           w: Math.max(...rects.map(r => r.x + r.w)) - ux,
                           h: Math.max(...rects.map(r => r.y + r.h)) - uy },
                 items: rects,
                 el: overlay().querySelector(".geo-box.geo-union") };
        overlay().setPointerCapture(e.pointerId);
        overlay().addEventListener("pointermove", onDragMove);
        overlay().addEventListener("pointerup", onDragUp, { once: true });
        return;
      }
      const primary = selections[selections.length - 1];
      const el = domAt(primary.ref);
      if (!el) return;
      const s = scale();
      const r = el.getBoundingClientRect();
      drag = { ref: primary.ref, type: "resize", dir, startX: e.clientX, startY: e.clientY,
               moved: true, el, w0: r.width / s, h0: r.height / s };
      overlay().setPointerCapture(e.pointerId);
      overlay().addEventListener("pointermove", onDragMove);
      overlay().addEventListener("pointerup", onDragUp, { once: true });
    }

    function onDragMove(e) {
      if (!drag) return;
      pendingPointer = e;
      if (rafId) return;
      rafId = requestAnimationFrame(applyDragFrame);
    }

    function applyDragFrame() {
      rafId = null;
      if (!drag || !pendingPointer) return;
      const e = pendingPointer;
      const dx = e.clientX - drag.startX, dy = e.clientY - drag.startY;
      if (!drag.moved && Math.hypot(dx, dy) < 3) return;
      if (!drag.moved) {
        drag.moved = true;
        if (drag.type === "move") {
          drag.els = selections.filter(s => s.ref.secIdx != null).map(s => ({ ref: s.ref, el: domAt(s.ref) })).filter(d => d.el);
          // canvas-позиция элемента ДО drag (без transform) в системе координат
          // collectHitTargets; boxRect в Edit-ноде даёт экранные px и смешал бы единицы
          if (drag.els.length === 1) {
            const t = collectHitTargets().find(tt => refKey(tt.ref) === refKey(drag.els[0].ref));
            if (t) drag.originRect = { x: t.x, y: t.y, w: t.w, h: t.h };
          }
        }
      }
      const s = scale();
      if (drag.type === "move") {
        let tx = dx / s, ty = dy / s;

        // Shift — движение только по доминантной оси (как в Figma)
        let constrain = null;
        if (e.shiftKey) {
          constrain = Math.abs(dx) >= Math.abs(dy) ? "y" : "x";
          if (constrain === "y") ty = 0; else tx = 0;
        }

        // smart guides: вычислить alignment и snap
        if (drag.els.length === 1) {
          const d0 = drag.els[0];
          // исходная позиция без drag + текущее смещение (canvas-координаты)
          let moving;
          if (drag.originRect) {
            const o = drag.originRect;
            moving = { x: o.x + tx, y: o.y + ty, w: o.w, h: o.h };
          } else {
            const r = boxRect(d0.el);
            moving = { x: r.left + tx, y: r.top + ty, w: r.width, h: r.height };
          }
          const guidesData = computeGuides(d0.ref, moving);
          tx += guidesData.snaps.dx;
          ty += guidesData.snaps.dy;
          // snap не должен возрождать заблокированную Shift-ом ось
          if (constrain === "y") ty = 0; else if (constrain === "x") tx = 0;
          renderGuides(guidesData);
        } else {
          clearGuides();
        }

        drag.els.forEach(d => {
          d.el.style.transform = `translate(${tx}px, ${ty}px)`;
        });
        const chip = overlay().querySelector(".geo-box.selected:last-child .geo-chip");
        if (chip) chip.textContent = `Δ ${Math.round(tx)} · ${Math.round(ty)}`;
      } else if (drag.type === "resize-multi") {
        if (drag.el) liveResizeMulti(drag, dx / s, dy / s);
      } else {
        if (!drag.el) drag.el = domAt(drag.ref);
        if (drag.el) liveResize(drag, dx / s, dy / s);
      }
    }

    function onDragUp(e) {
      overlay().removeEventListener("pointermove", onDragMove);
      try { overlay().releasePointerCapture(e.pointerId); } catch (_) {}
      if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
      const d = drag;
      drag = null;
      pendingPointer = null;
      if (!d) return;
      const s = scale();
      let dx = (e.clientX - d.startX) / s, dy = (e.clientY - d.startY) / s;
      // Shift-constrain применяется и к коммиту, не только к визуальному transform
      if (e.shiftKey && d.type === "move") {
        if (Math.abs(dx) >= Math.abs(dy)) dy = 0; else dx = 0;
      }
      if (!d.moved) { clearGuides(); return; }
      // очищаем CSS transform ДО commit чтобы relPos не включал drag offset
      if (d.type === "move") {
        d.els && d.els.forEach(de => { if (de.el) de.el.style.transform = ""; });
        clearGuides();
        if (d.altKey) commitDuplicateMove(dx, dy);
        else commitMoveAll(dx, dy);
      }
      else if (d.type === "resize-multi") { if (d.el) d.el.style.transform = ""; commitResizeMulti(d); }
      else { d.el.style.transform = ""; commitResize(d); }
    }

    /** Копии выделенных children/секций вставляются рядом с оригиналами.
     *  НЕ зовёт onCommit/onMutated — владелец решает сам. Возвращает ref'ы копий. */
    function duplicateSelections() {
      const targets = [];
      selections.forEach(sel => {
        if (sel.ref.secIdx == null) return;
        if (sel.ref.path != null && !sel.ref.path.startsWith("children.")) return;
        const parent = parentOf(sel.ref);
        if (!parent) return;
        const idx = sel.ref.path == null ? sel.ref.secIdx
                                         : parseInt(sel.ref.path.split(".").pop());
        if (!Number.isInteger(idx) || idx < 0 || idx >= parent.siblings.length) return;
        targets.push({ ref: sel.ref, arr: parent.siblings, idx });
      });
      // в пределах одного массива идём от головы: каждая вставка сдвигает индексы
      targets.sort((a, b) => (a.arr === b.arr ? a.idx - b.idx : 0));
      const shifts = new Map();
      const newRefs = [];
      targets.forEach(t => {
        const at = t.idx + (shifts.get(t.arr) || 0);
        const node = t.arr[at];
        if (!node) return;
        t.arr.splice(at + 1, 0, JSON.parse(JSON.stringify(node)));
        shifts.set(t.arr, (shifts.get(t.arr) || 0) + 1);
        if (t.ref.path == null) newRefs.push({ secIdx: at + 1, path: null });
        else {
          const segs = t.ref.path.split(".");
          segs[segs.length - 1] = String(at + 1);
          newRefs.push({ secIdx: t.ref.secIdx, path: segs.join(".") });
        }
      });
      return newRefs;
    }

    /** Z-order: сдвиг выделенного элемента среди сиблингов (+1 вверх / -1 вниз). */
    function zOrder(dir) {
      if (selections.length !== 1) return;
      const ref = selections[0].ref;
      if (ref.secIdx == null) return;
      const parent = parentOf(ref);
      if (!parent) return;
      const idx = ref.path == null ? ref.secIdx : parseInt(ref.path.split(".").pop(), 10);
      const to = idx + dir;
      if (!Number.isInteger(idx) || to < 0 || to >= parent.siblings.length) return;
      onCommit();
      const [node] = parent.siblings.splice(idx, 1);
      parent.siblings.splice(to, 0, node);
      const newRef = ref.path == null
        ? { secIdx: to, path: null }
        : Object.assign({}, ref, {
            path: ref.path.split(".").slice(0, -1).concat(String(to)).join("."),
          });
      select(newRef);
      onMutated();
    }
    function bringForward() { zOrder(1); }
    function sendBackward() { zOrder(-1); }

    /** Reorder: переставить ref на newIndex среди сиблингов (drag&drop в layers).
     *  Конвенция: перетаскиваемый занимает слот цели (цель сдвигается к источнику). */
    function moveSibling(ref, newIndex) {
      if (ref.secIdx == null) return;
      const parent = parentOf(ref);
      if (!parent) return;
      // guard: корневые секции идут по secIdx, без обращения к path.split
      const idx = ref.path == null ? ref.secIdx : parseInt(ref.path.split(".").pop(), 10);
      if (!Number.isInteger(idx) || newIndex < 0 || newIndex >= parent.siblings.length
          || idx === newIndex) return;
      onCommit();
      const [node] = parent.siblings.splice(idx, 1);
      // после remove+insert финальный индекс перемещённой ноды — ровно newIndex
      parent.siblings.splice(newIndex, 0, node);
      // ремоппим все выделения, затронутые сдвигом (перемещённую ноду и соседей):
      // иначе мультивыделение останется на старых, уже чужих позициях
      const shift = j => (j === idx ? newIndex
        : idx < newIndex ? (j > idx && j <= newIndex ? j - 1 : j)
        : (j >= newIndex && j < idx ? j + 1 : j));
      const prefixSegs = ref.path == null ? null : ref.path.split(".").slice(0, -1);
      selections = selections.map(s => {
        const r = s.ref;
        if (prefixSegs == null) {
          // двигали корневую секцию: сдвигаются secIdx всех секций диапазона
          if (r.secIdx == null) return s;
          const j = shift(r.secIdx);
          return j === r.secIdx ? s
            : Object.assign({}, s, { ref: Object.assign({}, r, { secIdx: j }) });
        }
        if (r.secIdx !== ref.secIdx || r.path == null) return s;
        const segs = r.path.split(".");
        if (segs.length <= prefixSegs.length) return s;
        for (let i = 0; i < prefixSegs.length; i++) if (segs[i] !== prefixSegs[i]) return s;
        const j0 = parseInt(segs[prefixSegs.length], 10);
        if (!Number.isInteger(j0)) return s;
        const j = shift(j0);
        if (j === j0) return s;
        segs[prefixSegs.length] = String(j);
        return Object.assign({}, s, { ref: Object.assign({}, r, { path: segs.join(".") }) });
      });
      onMutated();
      renderSelectionBoxes();
      scheduleBoxSync();
      if (onSelect) onSelect(selections);
    }

    /** Group: выделенные сиблинги одного родителя → card-контейнер (free) с их
     *  относительными позициями. Ungroup — обратно, с офсетом контейнера. */
    function groupSelection() {
      // секции верхнего уровня (path == null) не группируются: понятный отказ
      // вместо тихого пропуска (и без TypeError на r.path.split)
      if (selections.some(s => s.ref.secIdx != null && s.ref.path == null)) {
        hint("Группировка недоступна для секций верхнего уровня");
        return;
      }
      const refs = selections.map(s => s.ref).filter(r => r.secIdx != null && r.path != null
        && r.path.startsWith("children."));
      if (refs.length < 2) return;
      const parentPathOf = r => r.path.split(".").slice(0, -2).join(".");
      const secIdx = refs[0].secIdx;
      if (!refs.every(r => r.secIdx === secIdx && parentPathOf(r) === parentPathOf(refs[0]))) return;
      const parent = parentOf(refs[0]);
      if (!parent || !parent.dom) return;
      // локальные координаты от padding-box родителя — меряем из DOM, как makeParentFree
      const s = scale();
      const cs = getComputedStyle(parent.dom);
      const bl = parseFloat(cs.borderLeftWidth) || 0, bt = parseFloat(cs.borderTopWidth) || 0;
      const base = parent.dom.getBoundingClientRect();
      const idxs = refs.map(r => parseInt(r.path.split(".").pop(), 10))
        .filter(Number.isInteger).sort((a, b) => a - b);
      if (idxs.length !== refs.length) return;
      const meas = [];
      for (const i of idxs) {
        const el = siblingDom(parent, i);
        if (!el) return; // stale DOM — прерываемся до onCommit
        const r = el.getBoundingClientRect();
        meas.push({ x: (r.left - base.left) / s - bl, y: (r.top - base.top) / s - bt,
                    w: r.width / s, h: r.height / s });
      }
      const gx = Math.min(...meas.map(m => m.x)), gy = Math.min(...meas.map(m => m.y));
      const gw = Math.max(...meas.map(m => m.x + m.w)) - gx;
      const gh = Math.max(...meas.map(m => m.y + m.h)) - gy;
      onCommit();
      const taken = idxs.map(i => parent.siblings[i]);
      const group = {
        type: "card",
        frame: { layout: "free", x: Math.round(gx), y: Math.round(gy),
                 width: Math.round(gw), height: Math.round(gh) },
        children: taken.map((n, k) => {
          const c = JSON.parse(JSON.stringify(n));
          c.frame = Object.assign({}, c.frame, {
            x: Math.round(meas[k].x - gx), y: Math.round(meas[k].y - gy),
          });
          // fill/hug в free-группе теряют смысл — фиксируем измеренные размеры
          if (c.frame.width === "fill" || c.frame.width === "hug") c.frame.width = Math.round(meas[k].w);
          if (c.frame.height === "fill" || c.frame.height === "hug") c.frame.height = Math.round(meas[k].h);
          return c;
        }),
      };
      // вынимаем с хвоста, вставляем группу на место первого
      for (let k = idxs.length - 1; k >= 0; k--) parent.siblings.splice(idxs[k], 1);
      parent.siblings.splice(idxs[0], 0, group);
      select({ secIdx, path: (parentPathOf(refs[0])
        ? parentPathOf(refs[0]) + ".children." : "children.") + idxs[0] });
      onMutated();
    }

    function ungroupSelection() {
      if (selections.length !== 1) return;
      const ref = selections[0].ref;
      if (ref.secIdx == null || ref.path == null) return;
      const node = irNodeAt(ref);
      // разгруппировываем только free-контейнеры (то, что groupSelection создаёт)
      if (!node || !node.children || !node.children.length
          || !node.frame || node.frame.layout !== "free") return;
      const parent = parentOf(ref);
      if (!parent) return;
      const idx = parseInt(ref.path.split(".").pop(), 10);
      if (!Number.isInteger(idx)) return;
      onCommit();
      // координаты из внешнего IR бывают строками/NaN: в арифметике только конечные числа
      const gx = finiteNum(node.frame.x), gy = finiteNum(node.frame.y);
      const parentFree = !!(parent.node.frame && parent.node.frame.layout === "free");
      const kids = node.children.map(c => {
        const k = JSON.parse(JSON.stringify(c));
        k.frame = Object.assign({}, k.frame);
        // width/height: строку-число нормализуем, ключевые слова (fill/hug) не трогаем
        ["width", "height"].forEach(d => {
          if (typeof k.frame[d] === "string") {
            const n = parseFloat(k.frame[d]);
            if (Number.isFinite(n)) k.frame[d] = n;
          }
        });
        // офсет группы имеет смысл только во free-родителе; в auto он лишь засоряет IR
        if (parentFree) {
          k.frame.x = Math.round(finiteNum(k.frame.x) + gx);
          k.frame.y = Math.round(finiteNum(k.frame.y) + gy);
        }
        return k;
      });
      parent.siblings.splice(idx, 1, ...kids);
      // выделение переходит на раскрытых детей
      const base = ref.path.split(".").slice(0, -1);
      selectMulti(kids.map((_, k) => ({
        secIdx: ref.secIdx,
        path: (base.length ? base.join(".") + ".children." : "children.") + (idx + k),
      })));
      onMutated();
    }

    /** Alt+drag: оригиналы остаются, копии уходят на дельту (один undo-шаг).
     *  В auto-родителе копия без x/y встаёт в поток — как в Figma auto-layout. */
    function commitDuplicateMove(dx, dy) {
      onCommit();
      const newRefs = duplicateSelections();
      newRefs.forEach(r => {
        const node = irNodeAt(r);
        if (node && node.frame &&
            (typeof node.frame.x === "number" || typeof node.frame.y === "number")) {
          node.frame = Object.assign({}, node.frame, {
            x: Math.round((node.frame.x || 0) + dx),
            y: Math.round((node.frame.y || 0) + dy),
          });
        }
      });
      if (newRefs.length) selectMulti(newRefs);
      onMutated();
    }

    /* --- выравнивание (Figma-like) --- */

    function selectedRects() {
      // canvas-координаты (boxRect в ноде Edit даёт единицы оверлея — не те)
      const targets = collectHitTargets();
      return selections
        .filter(s => s.ref.secIdx != null)
        .map(s => {
          const t = targets.find(tt => refKey(tt.ref) === refKey(s.ref));
          if (!t) return null;
          return { ref: s.ref, x: t.x, y: t.y, w: t.w, h: t.h };
        })
        .filter(Boolean);
    }

    /** Padding-box родителя в canvas-координатах (для одиночного выравнивания):
     *  frame.x/y считаются от padding-box — как CSS absolute. */
    function parentBox(ref) {
      const parent = parentOf(ref);
      if (!parent || !parent.dom) return null;
      const s = scale();
      const r = parent.dom.getBoundingClientRect();
      const cs = getComputedStyle(parent.dom);
      const bl = parseFloat(cs.borderLeftWidth) || 0, br = parseFloat(cs.borderRightWidth) || 0;
      const bt = parseFloat(cs.borderTopWidth) || 0, bb = parseFloat(cs.borderBottomWidth) || 0;
      return { w: r.width / s - bl - br, h: r.height / s - bt - bb };
    }

    function applyAlign(mutator, single) {
      const rects = selectedRects();
      if (!rects.length) return;
      onCommit();
      if (rects.length === 1) {
        // как в Pencil: одиночное выделение выравнивается внутри родителя
        const pc = parentBox(rects[0].ref);
        if (pc) {
          ensureParentFree(rects[0].ref);
          const f = Object.assign({}, getFrame(rects[0].ref));
          single(f, rects[0], pc);
          setFrameData(rects[0].ref, f);
        }
      } else {
        rects.forEach(r => {
          const f = Object.assign({}, getFrame(r.ref));
          ensureParentFree(r.ref);
          mutator(f, r, rects);
          setFrameData(r.ref, f);
        });
      }
      onMutated();
    }

    function alignLeft() {
      applyAlign((f, r, rects) => {
        const minX = Math.min(...rects.map(q => q.x));
        f.x = Math.round(minX);
      }, (f) => { f.x = 0; });
    }

    function alignCenterH() {
      applyAlign((f, r, rects) => {
        const minX = Math.min(...rects.map(q => q.x));
        const maxX = Math.max(...rects.map(q => q.x + q.w));
        const center = (minX + maxX) / 2;
        f.x = Math.round(center - r.w / 2);
      }, (f, r, pc) => { f.x = Math.round((pc.w - r.w) / 2); });
    }

    function alignRight() {
      applyAlign((f, r, rects) => {
        const maxX = Math.max(...rects.map(q => q.x + q.w));
        f.x = Math.round(maxX - r.w);
      }, (f, r, pc) => { f.x = Math.round(pc.w - r.w); });
    }

    function alignTop() {
      applyAlign((f, r, rects) => {
        const minY = Math.min(...rects.map(q => q.y));
        f.y = Math.round(minY);
      }, (f) => { f.y = 0; });
    }

    function alignCenterV() {
      applyAlign((f, r, rects) => {
        const minY = Math.min(...rects.map(q => q.y));
        const maxY = Math.max(...rects.map(q => q.y + q.h));
        const center = (minY + maxY) / 2;
        f.y = Math.round(center - r.h / 2);
      }, (f, r, pc) => { f.y = Math.round((pc.h - r.h) / 2); });
    }

    function alignBottom() {
      applyAlign((f, r, rects) => {
        const maxY = Math.max(...rects.map(q => q.y + q.h));
        f.y = Math.round(maxY - r.h);
      }, (f, r, pc) => { f.y = Math.round(pc.h - r.h); });
    }

    function distributeH() {
      const rects = selectedRects();
      if (rects.length < 3) return;
      rects.sort((a, b) => a.x - b.x);
      onCommit();
      const totalW = rects.reduce((s, r) => s + r.w, 0);
      const span = rects[rects.length - 1].x + rects[rects.length - 1].w - rects[0].x;
      const gap = (span - totalW) / (rects.length - 1);
      let cx = rects[0].x;
      rects.forEach(r => {
        const f = Object.assign({}, getFrame(r.ref));
        ensureParentFree(r.ref);
        f.x = Math.round(cx);
        setFrameData(r.ref, f);
        cx += r.w + gap;
      });
      onMutated();
    }

    function distributeV() {
      const rects = selectedRects();
      if (rects.length < 3) return;
      rects.sort((a, b) => a.y - b.y);
      onCommit();
      const totalH = rects.reduce((s, r) => s + r.h, 0);
      const span = rects[rects.length - 1].y + rects[rects.length - 1].h - rects[0].y;
      const gap = (span - totalH) / (rects.length - 1);
      let cy = rects[0].y;
      rects.forEach(r => {
        const f = Object.assign({}, getFrame(r.ref));
        ensureParentFree(r.ref);
        f.y = Math.round(cy);
        setFrameData(r.ref, f);
        cy += r.h + gap;
      });
      onMutated();
    }

    /* --- публичные методы записи --- */

    function setFrame(partial) {
      if (!selections.length) return;
      onCommit();
      selections.forEach(sel => {
        const node = irNodeAt(sel.ref);
        if (!node && !sel.ref.path?.startsWith("props.")) return;
        const f = Object.assign({}, getFrame(sel.ref));
        for (const k of ["x", "y", "width", "height"]) {
          const val = partial[k];
          if (val === undefined) continue;
          if (val === null) delete f[k];
          else if (!Number.isNaN(Number(val))) f[k] = Math.round(Number(val));
        }
        if (!Object.keys(f).length) setFrameData(sel.ref, null);
        else setFrameData(sel.ref, f);
        // absolute-элемент позиционируется по x/y без перевода родителя в free
        if (sel.ref.secIdx != null && (partial.x !== undefined || partial.y !== undefined) && !f.absolute) {
          ensureParentFree(sel.ref);
        }
      });
      onMutated();
    }

    /** Произвольное слияние свойств frame (rotation, clip, absolute, layout, gap, padding…).
     *  null удаляет ключ. Модель — как инспектор pen.dev. */
    function setFrameProps(partial) {
      if (!selections.length) return;
      onCommit();
      selections.forEach(sel => {
        const f = Object.assign({}, getFrame(sel.ref));
        for (const [k, v] of Object.entries(partial)) {
          if (v === undefined) continue;
          if (v === null) delete f[k];
          else f[k] = v;
        }
        if (!Object.keys(f).length) setFrameData(sel.ref, null);
        else setFrameData(sel.ref, f);
        if (sel.ref.secIdx != null &&
            (((partial.x !== undefined || partial.y !== undefined) && !f.absolute) || partial.layout === "free")) {
          ensureParentFree(sel.ref);
        }
      });
      onMutated();
    }

    function setNodeStyle(partial) {
      if (!selections.length) return;
      const now = Date.now();
      if (now >= styleSessionUntil) onCommit();
      styleSessionUntil = now + 300;
      selections.forEach(sel => {
        const node = irNodeAt(sel.ref);
        if (!node) return;
        const style = Object.assign({}, node.style || {});
        for (const [k, v] of Object.entries(partial)) {
          if (v === undefined) continue;
          if (v === null || v === "") delete style[k];
          else style[k] = v;
        }
        // text-узлы не должны нести фон/рамку/тень — это всегда родительский контейнер
        if (node.type === "text" || node.type === "heading") {
          for (const k of ["background", "borderColor", "borderWidth", "borderRadius", "boxShadow"]) delete style[k];
          delete node.fill;
        }
        if (node.type === "rect") {
          if (partial.background !== undefined) {
            if (partial.background === null || partial.background === "") delete node.fill;
            else node.fill = partial.background;
          }
          if (partial.borderRadius !== undefined) {
            if (partial.borderRadius === null || partial.borderRadius === "") delete node.radius;
            else node.radius = Math.max(0, Math.round(Number(partial.borderRadius) || 0));
          }
        }
        if (Object.keys(style).length) node.style = style;
        else delete node.style;
      });
      onMutated();
    }

    /** Измеренная позиция элемента относительно родителя (canvas-px). */
    function posOf(ref) {
      const el = domAt(ref);
      const parent = parentOf(ref);
      if (!el || !parent || !parent.dom) return null;
      return relPos(el, parent.dom);
    }

    function frameOf(ref) {
      return getFrame(ref);
    }

    /** Измеренный размер элемента в canvas-px. */
    function sizeOf(ref) {
      const el = domAt(ref);
      if (!el) return null;
      const s = scale();
      const r = el.getBoundingClientRect();
      return { w: Math.round(r.width / s), h: Math.round(r.height / s) };
    }

    function resetFrame() {
      if (!selections.length) return;
      onCommit();
      selections.forEach(sel => {
        const f = getFrame(sel.ref);
        if (f && Object.keys(f).length) setFrameData(sel.ref, null);
      });
      onMutated();
    }

    /* --- буфер обмена + выделение всего (clipboard уровня модуля) --- */

    /** Ctrl+A: все top-level children текущего контекста (вошедшего контейнера
     *  или всех секций); залоченные слои пропускаем, как hit-test/marquee. */
    function selectAllInContext() {
      const ir = getIR();
      if (!ir || !ir.tree) return;
      const refs = [];
      if (containerCtx) {
        const node = irNodeAt(containerCtx);
        ((node && node.children) || []).forEach((_, j) => {
          refs.push({ secIdx: containerCtx.secIdx,
                      path: (containerCtx.path ? containerCtx.path + "." : "") + "children." + j });
        });
      } else {
        ir.tree.forEach((sec, si) => {
          ((sec && sec.children) || []).forEach((_, j) => refs.push({ secIdx: si, path: "children." + j }));
        });
      }
      const visible = refs.filter(r => !skipLocked(r));
      if (visible.length) selectMulti(visible);
    }

    /** Ctrl+C: глубокие клоны выделенных узлов + ref исходного контейнера. */
    function copySelection() {
      const items = collectSelectionItems();
      if (items.length) geoClipboard = items;
      return items.length;
    }

    /** Глубокие клоны выделенных узлов без записи в буфер (база для Ctrl+C и Ctrl+D). */
    function collectSelectionItems() {
      const items = [];
      selections.forEach(sel => {
        if (sel.ref.secIdx == null) return;
        if (sel.ref.path != null && !sel.ref.path.startsWith("children.")) return;
        const node = irNodeAt(sel.ref);
        if (!node) return;
        if (sel.ref.path == null) {
          // секция целиком: при вставке уходит в ir.tree, а не в контейнер
          items.push({ node: JSON.parse(JSON.stringify(node)), intoTree: true });
          return;
        }
        const parent = parentOf(sel.ref);
        if (!parent) return;
        items.push({ node: JSON.parse(JSON.stringify(node)),
                     parentRef: { secIdx: sel.ref.secIdx, path: parent.parentPath || null } });
      });
      return items;
    }

    /** Удаление выделенных (Delete / Ctrl+X): общая механика сплайса с хвоста. */
    function deleteSelections() {
      if (!selections.length) return;
      onCommit();
      const targets = [];
      selections.forEach(sel => {
        if (sel.ref.secIdx == null) return;
        // props.* не удаляем — только children и секции (path === null)
        if (sel.ref.path != null && !sel.ref.path.startsWith("children.")) return;
        const parent = parentOf(sel.ref);
        if (!parent) return;
        // parentOf даёт сам массив сиблингов: для секции это ir.tree,
        // для children.a.children.b — children узла по пути родителя
        const idx = sel.ref.path == null ? sel.ref.secIdx
                                         : parseInt(sel.ref.path.split(".").pop());
        if (!Number.isInteger(idx) || idx < 0 || idx >= parent.siblings.length) return;
        targets.push({ arr: parent.siblings, idx });
      });
      // в пределах одного массива удаляем с хвоста, чтобы индексы не съехали
      targets.sort((a, b) => (a.arr === b.arr ? b.idx - a.idx : 0));
      targets.forEach(t => t.arr.splice(t.idx, 1));
      clear();
      onMutated();
    }

    /** Ctrl+X: копия + удаление. */
    function cutSelection() {
      if (!copySelection()) return;
      deleteSelections();
    }

    /** Вставка набора клонов в текущий контейнер (контекст → исходный родитель →
     *  корневая секция), свежие ключи, сдвиг +16/+16 чтобы вставка была видна.
     *  Схема IR: id разрешён только секциям — дочерним узлам даём sourceKey.
     *  НЕ зовёт onCommit/onMutated — владелец решает сам. Возвращает ref'ы копий. */
    function insertItems(items) {
      const ir = getIR();
      if (!ir || !ir.tree || !ir.tree.length) return [];
      const rekey = (n, isSection) => {
        if (!n || typeof n !== "object") return;
        if (isSection) {
          if ("id" in n) n.id = nextUid();
        } else {
          delete n.id;
          n.sourceKey = nextUid();
        }
        (n.children || []).forEach((c) => rekey(c, false));
      };
      const newRefs = [];
      items.forEach(item => {
        const node = JSON.parse(JSON.stringify(item.node));
        rekey(node, !!item.intoTree);
        if (node.frame) {
          if (typeof node.frame.x === "number") node.frame.x += 16;
          if (typeof node.frame.y === "number") node.frame.y += 16;
        }
        if (item.intoTree) {
          ir.tree.push(node);
          newRefs.push({ secIdx: ir.tree.length - 1, path: null });
          return;
        }
        let contRef = containerCtx;
        let contNode = contRef ? irNodeAt(contRef) : null;
        if (!contNode && item.parentRef) {
          contRef = item.parentRef;
          contNode = irNodeAt(contRef);
        }
        if (!contNode) {
          contRef = { secIdx: 0, path: null };
          contNode = ir.tree[0];
        }
        if (!contNode) return;
        contNode.children = contNode.children || [];
        contNode.children.push(node);
        newRefs.push({ secIdx: contRef.secIdx,
                       path: (contRef.path ? contRef.path + "." : "") + "children." + (contNode.children.length - 1) });
      });
      return newRefs;
    }

    /** Ctrl+V: вставка буфера обмена. */
    function pasteClipboard() {
      if (!geoClipboard.length) return;
      const ir = getIR();
      if (!ir || !ir.tree || !ir.tree.length) return;
      onCommit();
      const newRefs = insertItems(geoClipboard);
      if (newRefs.length) selectMulti(newRefs);
      onMutated();
    }

    /** Ctrl+D: дубликат выделения in-place (Figma-стандарт): как paste, но из
     *  текущего выделения и не трогая буфер обмена. */
    function duplicateSelection() {
      const items = collectSelectionItems();
      if (!items.length) return;
      const ir = getIR();
      if (!ir || !ir.tree || !ir.tree.length) return;
      onCommit();
      const newRefs = insertItems(items);
      if (newRefs.length) selectMulti(newRefs);
      onMutated();
      return newRefs.length;
    }

    /* ---------- контекстное меню канваса (правый клик; паттерн OpenPencil/Figma) ---------- */

    let ctxMenuEl = null;

    function closeContextMenu() {
      if (ctxMenuEl) { ctxMenuEl.remove(); ctxMenuEl = null; }
      document.removeEventListener("pointerdown", onDocDownCloseCtx, true);
    }

    function onDocDownCloseCtx(ev) {
      // клик внутри самого меню не закрывает его: иначе DOM удалится на
      // pointerdown и click по пункту не успеет сработать
      if (ctxMenuEl && ev.target instanceof Node && ctxMenuEl.contains(ev.target)) return;
      closeContextMenu();
    }

    /** items: [{label, hint?, disabled?, run?} | {sep:true}]. Позиция — в
     *  координатах оверлея, кламп в пределы артборда. */
    function openContextMenu(clientX, clientY, items) {
      closeContextMenu();
      const m = document.createElement("div");
      m.className = "geo-ctx-menu";
      items.forEach(it => {
        if (it.sep) {
          const s = document.createElement("div");
          s.className = "geo-ctx-sep";
          m.appendChild(s);
          return;
        }
        const b = document.createElement("button");
        b.type = "button";
        b.className = "geo-ctx-item" + (it.disabled ? " disabled" : "");
        const lbl = document.createElement("span");
        lbl.textContent = it.label;
        b.appendChild(lbl);
        if (it.hint) {
          const k = document.createElement("kbd");
          k.textContent = it.hint;
          b.appendChild(k);
        }
        if (!it.disabled && it.run) {
          b.addEventListener("click", (ev) => { ev.stopPropagation(); closeContextMenu(); it.run(); });
        }
        m.appendChild(b);
      });
      overlay().appendChild(m);
      const pt = screenToCanvas(clientX, clientY);
      const W = previewEl.clientWidth, H = previewEl.clientHeight;
      m.style.left = Math.max(0, Math.min(Math.round(pt.x), Math.max(0, W - m.offsetWidth))) + "px";
      m.style.top = Math.max(0, Math.min(Math.round(pt.y), Math.max(0, H - m.offsetHeight))) + "px";
      ctxMenuEl = m;
      // любой клик вне меню закрывает его (capture — раньше overlay-хендлеров)
      document.addEventListener("pointerdown", onDocDownCloseCtx, true);
    }

    function buildCtxItems() {
      const hasSel = selections.length > 0;
      const multiSel = selections.length > 1;
      const last = hasSel ? selections[selections.length - 1] : null;
      const lastNode = last ? irNodeAt(last.ref) : null;
      const canUngroup = hasSel && !multiSel && lastNode && Array.isArray(lastNode.children)
        && lastNode.children.length > 0 && lastNode.frame && lastNode.frame.layout === "free";
      const groupable = !selections.some(s => s.ref.secIdx != null && s.ref.path == null)
        && selections.filter(s => s.ref.secIdx != null && s.ref.path != null
          && s.ref.path.startsWith("children.")).length >= 2;
      const items = [
        { label: "Копировать", hint: "Ctrl+C", disabled: !hasSel, run: copySelection },
        { label: "Вырезать", hint: "Ctrl+X", disabled: !hasSel, run: cutSelection },
        { label: "Вставить", hint: "Ctrl+V", disabled: !geoClipboard.length, run: pasteClipboard },
        { label: "Дублировать", hint: "Ctrl+D", disabled: !hasSel, run: duplicateSelection },
        { sep: true },
        { label: "Выше", hint: "]", disabled: !hasSel, run: bringForward },
        { label: "Ниже", hint: "[", disabled: !hasSel, run: sendBackward },
        { label: "Группа", hint: "Ctrl+G", disabled: !groupable, run: groupSelection },
        { label: "Разгруппировать", hint: "Ctrl+Shift+G", disabled: !canUngroup, run: ungroupSelection },
        { sep: true },
        { label: "Удалить", hint: "Del", disabled: !hasSel, run: deleteSelections },
      ];
      if (hasSel && !multiSel && last) {
        const pathLabel = last.ref.path == null
          ? `tree[${last.ref.secIdx}]`
          : `tree[${last.ref.secIdx}].${last.ref.path}`;
        items.push({ sep: true });
        items.push({
          label: "Копировать IR-путь", hint: pathLabel,
          run: () => {
            if (navigator.clipboard) navigator.clipboard.writeText(pathLabel);
            hint("IR-путь скопирован");
          },
        });
      }
      return items;
    }

    /** Правый клик: невыделенный элемент под курсором сначала выделяется
     *  (поведение Figma), затем открывается меню. */
    function onContextMenu(e) {
      if (destroyed) return;
      e.preventDefault();
      e.stopPropagation();
      const ref = hitTest(e.clientX, e.clientY, false);
      if (ref) {
        const already = selections.some(s => refKey(s.ref) === refKey(ref));
        if (!already) select(ref);
      }
      openContextMenu(e.clientX, e.clientY, buildCtxItems());
    }

    /* --- клавиатура: nudge, escape, delete --- */

    /** Esc: выйти из контейнера или снять выделение.
     *  Возвращает true, если geoedit поглотил событие (есть что сбрасывать). */
    function consumeEscape() {
      if (containerCtx) {
        containerCtx = null;
        clear();
        renderContainerBadge();
        return true;
      }
      if (selections.length) { clear(); return true; }
      return false;
    }

    function onKeydown(e) {
      const ae = document.activeElement;
      if (ae && (ae.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName))) return;

      // хоткеи инструментов как в pen.dev: V/R/O/L/I/T/F/H (только если владелец включил панель)
      if (toolsEnabled) {
        const toolKeys = { v: "select", r: "rect", o: "ellipse", l: "line", i: "image",
                           t: "text", f: "frame", h: "hand" };
        const tk = toolKeys[e.key.toLowerCase()];
        if (tk && !e.ctrlKey && !e.metaKey && !e.altKey) { setTool(tk); return; }
      }

      // выделение всего и буфер обмена (Ctrl+A/C/X/V), как в Figma
      if (e.ctrlKey || e.metaKey) {
        const ck = e.key.toLowerCase();
        if (ck === "a" && !e.altKey) {
          e.preventDefault();
          e.stopPropagation();
          selectAllInContext();
          return;
        }
        if (!e.shiftKey && !e.altKey) {
          if (ck === "c" && selections.length) { copySelection(); return; }
          if (ck === "x" && selections.length) { e.preventDefault(); e.stopPropagation(); cutSelection(); return; }
          if (ck === "v" && geoClipboard.length) { e.preventDefault(); e.stopPropagation(); pasteClipboard(); return; }
          if (ck === "d" && selections.length) { e.preventDefault(); e.stopPropagation(); duplicateSelection(); return; }
        }
      }

      // Esc: выйти из контейнера или снять выделение.
      // При escapeViaHandle владелец сам явно зовёт consumeEscape() (editor.js)
      if (e.key === "Escape") {
        // открытое контекстное меню закрывается первым, до сброса выделения
        if (ctxMenuEl) {
          e.preventDefault();
          e.stopPropagation();
          closeContextMenu();
          return;
        }
        if (!escapeViaHandle) consumeEscape();
        return;
      }

      // Arrow keys: nudge выделенных элементов.
      // Серия нажатий с интервалом < 300 мс — один undo-шаг (паттерн OpenPencil):
      // onCommit только когда предыдущая серия истекла.
      if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key) && selections.length) {
        e.preventDefault();
        const step = e.shiftKey ? 10 : 1;
        let dx = 0, dy = 0;
        if (e.key === "ArrowLeft") dx = -step;
        if (e.key === "ArrowRight") dx = step;
        if (e.key === "ArrowUp") dy = -step;
        if (e.key === "ArrowDown") dy = step;
        const now = Date.now();
        if (now >= nudgeSessionUntil) onCommit();
        nudgeSessionUntil = now + 300;
        selections.forEach(sel => {
          if (sel.ref.secIdx == null) return;
          ensureParentFree(sel.ref);
          const f = Object.assign({}, getFrame(sel.ref));
          f.x = Math.round((typeof f.x === "number" ? f.x : 0) + dx);
          f.y = Math.round((typeof f.y === "number" ? f.y : 0) + dy);
          setFrameData(sel.ref, f);
        });
        onMutated();
        return;
      }

      // Delete / Backspace: удалить выделенные элементы (любую вложенность) и секции
      if ((e.key === "Delete" || e.key === "Backspace") && selections.length) {
        e.preventDefault();
        e.stopPropagation(); // не дать графу удалить саму ноду-редактор
        deleteSelections();
        return;
      }

      // Z-order: ] вверх, [ вниз (Shift — сразу наверх/вниз не делаем, как в Figma)
      if (e.key === "]" && selections.length === 1) { bringForward(); return; }
      if (e.key === "[" && selections.length === 1) { sendBackward(); return; }

      // Group / Ungroup
      if ((e.key === "g" || e.key === "G" || e.key === "п" || e.key === "П") && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        if (e.shiftKey) ungroupSelection(); else groupSelection();
        return;
      }

      // Cmd/Ctrl+D: дублировать рядом с оригиналом (любая вложенность и секции)
      if ((e.key === "d" || e.key === "D") && (e.ctrlKey || e.metaKey) && selections.length) {
        e.preventDefault();
        e.stopPropagation(); // событие потреблено здесь
        onCommit();
        const newRefs = duplicateSelections();
        newRefs.forEach(r => {
          const node = irNodeAt(r);
          const parent = parentOf(r);
          const parentFree = !!(parent && parent.node.frame && parent.node.frame.layout === "free");
          // сдвиг копии на 10px только во free-родителе, чтобы не сливалась с оригиналом;
          // в auto-раскладке копия остаётся в потоке — как при Alt+drag (commitDuplicateMove)
          if (parentFree && node && node.frame) {
            node.frame.x = (node.frame.x || 0) + 10;
            node.frame.y = (node.frame.y || 0) + 10;
          }
        });
        if (newRefs.length) selectMulti(newRefs);
        onMutated();
        return;
      }
    }

    function onResizeWin() {
      if (selections.length) renderSelectionBoxes();
    }

    /* --- двойной клик: enter container или inline-текст --- */

    function onDblClick(e) {
      const ref = hitTest(e.clientX, e.clientY, true); // deep: сразу вложенный
      if (!ref) return;
      e.preventDefault();

      const node = irNodeAt(ref);

      // если попали в секцию (контейнер) — войти в неё
      if (ref.path === null && node && node.type) {
        containerCtx = ref;
        clear();
        renderContainerBadge();
        return;
      }

      // inline-редактирование текста
      const el = domAt(ref);
      if (!el) return;

      let textEl = el.querySelector("[data-ir-path]") || el;
      if (textEl.classList.contains("editing")) return;

      const irEl = previewEl.querySelector('[class^="ir-"]');
      if (irEl) irEl.classList.remove("geo-content-block");

      textEl.classList.add("editing");
      textEl.contentEditable = "true";
      textEl.style.pointerEvents = "auto";
      textEl.focus();
      document.execCommand && document.execCommand("selectAll", false, null);

      const path = textEl.getAttribute("data-ir-path") || (ref.path || "");
      const secIdx = ref.secIdx;

      const commit = () => {
        textEl.contentEditable = "false";
        textEl.classList.remove("editing");
        textEl.style.pointerEvents = "";
        if (irEl) irEl.classList.add("geo-content-block");
        const newText = textEl.textContent;
        if (secIdx == null || secIdx < 0) return;
        const sec = getIR().tree[secIdx];
        if (!sec) return;
        onCommit();
        if (path.startsWith("children.")) {
          const n = getByPath(sec, path);
          if (n) {
            if (n.text !== undefined) n.text = newText;
            else if (n.title !== undefined) n.title = newText;
          }
        } else if (path.startsWith("props.")) {
          setByPath(sec, editableTextPath(path), newText);
        }
        onMutated();
      };
      textEl.addEventListener("blur", commit, { once: true });
      textEl.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); textEl.blur(); }
        if (ev.key === "Escape") { textEl.textContent = textEl.dataset.origText || textEl.textContent; textEl.blur(); }
      });
      textEl.dataset.origText = textEl.textContent;
    }

    /** Бейдж «Editing: ...» при входе в контейнер. */
    function renderContainerBadge() {
      let badge = overlay().querySelector(".geo-container-badge");
      if (!containerCtx) {
        if (badge) badge.remove();
        return;
      }
      if (!badge) {
        badge = document.createElement("div");
        badge.className = "geo-container-badge";
        badge.style.cssText = "position:absolute;top:4px;left:4px;background:#0D99FF;color:#fff;font:600 11px 'Inter',system-ui,sans-serif;padding:2px 8px;border-radius:4px;pointer-events:none;z-index:55;";
        overlay().appendChild(badge);
      }
      const node = irNodeAt(containerCtx);
      badge.textContent = `✎ ${node ? node.type : "container"} (Esc — выйти)`;
    }

    /* --- монтаж --- */

    // блокируем pointer events на контенте чтобы оверлей ловил всё
    blockContentEarly();

    overlay().addEventListener("pointerdown", onPointerDown);
    overlay().addEventListener("pointermove", onHover);
    overlay().addEventListener("pointerleave", hideHover);
    overlay().addEventListener("dblclick", onDblClick);
    overlay().addEventListener("contextmenu", onContextMenu);
    // capture-фаза: граф (nodes.js) тоже слушает Delete на document и удаляет
    // ноду — перехватываем клавиши раньше него
    document.addEventListener("keydown", onKeydown, true);
    window.addEventListener("resize", onResizeWin);

    function destroy() {
      if (destroyed) return;
      destroyed = true;
      if (rafId) cancelAnimationFrame(rafId);
      closeContextMenu();
      const ov = overlay();
      ov.removeEventListener("pointerdown", onPointerDown);
      ov.removeEventListener("pointermove", onHover);
      ov.removeEventListener("pointerleave", hideHover);
      ov.removeEventListener("dblclick", onDblClick);
      ov.removeEventListener("contextmenu", onContextMenu);
      document.removeEventListener("keydown", onKeydown, true);
      window.removeEventListener("resize", onResizeWin);
      // разблокируем контент
      const irEl = previewEl.querySelector('[class^="ir-"]');
      if (irEl) irEl.classList.remove("geo-content-block");
      ov.remove();
      selections = [];
    }

    return {
      select,
      selectMulti,
      clear,
      consumeEscape,
      setFrame,
      setFrameProps,
      setNodeStyle,
      frameOf,
      posOf,
      sizeOf,
      setTool,
      getTool: () => tool,
      syncZoom: () => syncZoom(),
      resetFrame,
      alignLeft,
      alignCenterH,
      alignRight,
      alignTop,
      alignCenterV,
      alignBottom,
      distributeH,
      distributeV,
      bringForward,
      sendBackward,
      moveSibling,
      groupSelection,
      ungroupSelection,
      selectAll: selectAllInContext,
      copySelection,
      cutSelection,
      pasteClipboard,
      duplicateSelection,
      destroy,
      get selection() { return selections[0] || null; },
      get selections() { return selections; },
    };
  }

export const GeoEdit = { attach };
