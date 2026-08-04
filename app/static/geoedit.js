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
 *           destroy(), selection, selections }
 *
 * Адресация узлов: ref = {secIdx: number|null (артборд), path: string|null}.
 * path — от корня секции: "children.0", "children.1.children.0", ...
 */
(function (global) {
  "use strict";

  /* ---------- CSS (инжектится один раз) ---------- */

  const GEO_CSS = `
  /* Оверлей живёт ВНУТРИ трансформированного контейнера (canvas-координаты).
     --geo-inv = 1/zoom: ручки, чипы и линии держат постоянный экранный размер. */
  .geo-overlay { position:absolute; inset:0; pointer-events:auto; z-index:50; overflow:visible; cursor:default; }
  .geo-overlay[data-tool="rect"], .geo-overlay[data-tool="frame"], .geo-overlay[data-tool="text"] { cursor:crosshair; }
  .geo-overlay[data-tool="hand"] { cursor:grab; }
  .geo-overlay.geo-handling { cursor:grabbing; }
  .geo-overlay * { pointer-events:none; }
  .geo-overlay .geo-h { pointer-events:auto; }
  .geo-box { position:absolute; border:calc(1.5px * var(--geo-inv,1)) solid transparent; pointer-events:none; }
  .geo-box.hover { border-color:rgba(120,120,160,.55); border-style:dashed; }
  .geo-box.selected { border-color:#5B5BD6; }
  .geo-chip { position:absolute; top:calc(-20px * var(--geo-inv,1)); left:calc(-1px * var(--geo-inv,1));
    background:#5B5BD6; color:#fff; font-family:'Inter',system-ui,sans-serif; font-weight:600;
    font-size:calc(10px * var(--geo-inv,1)); padding:calc(1px * var(--geo-inv,1)) calc(7px * var(--geo-inv,1));
    border-radius:calc(4px * var(--geo-inv,1)) calc(4px * var(--geo-inv,1)) 0 0;
    white-space:nowrap; pointer-events:none; }
  .geo-h { position:absolute; width:calc(8px * var(--geo-inv,1)); height:calc(8px * var(--geo-inv,1));
    background:#fff; border:calc(1.5px * var(--geo-inv,1)) solid #5B5BD6;
    border-radius:2px; pointer-events:auto; z-index:2; }
  .geo-h.h-nw { top:calc(-4px * var(--geo-inv,1)); left:calc(-4px * var(--geo-inv,1)); cursor:nwse-resize; }
  .geo-h.h-n  { top:calc(-4px * var(--geo-inv,1)); left:calc(50% - 4px * var(--geo-inv,1)); cursor:ns-resize; }
  .geo-h.h-ne { top:calc(-4px * var(--geo-inv,1)); right:calc(-4px * var(--geo-inv,1)); cursor:nesw-resize; }
  .geo-h.h-e  { top:calc(50% - 4px * var(--geo-inv,1)); right:calc(-4px * var(--geo-inv,1)); cursor:ew-resize; }
  .geo-h.h-se { bottom:calc(-4px * var(--geo-inv,1)); right:calc(-4px * var(--geo-inv,1)); cursor:nwse-resize; }
  .geo-h.h-s  { bottom:calc(-4px * var(--geo-inv,1)); left:calc(50% - 4px * var(--geo-inv,1)); cursor:ns-resize; }
  .geo-h.h-sw { bottom:calc(-4px * var(--geo-inv,1)); left:calc(-4px * var(--geo-inv,1)); cursor:nesw-resize; }
  .geo-h.h-w  { top:calc(50% - 4px * var(--geo-inv,1)); left:calc(-4px * var(--geo-inv,1)); cursor:ew-resize; }
  .geo-marquee { position:absolute; border:calc(1px * var(--geo-inv,1)) solid #5B5BD6; background:rgba(91,91,214,.08);
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

  /* ---------- attach ---------- */

  function attach(opts) {
    const { previewEl, getIR, getScale, onCommit, onSelect } = opts;
    const scrollEl = opts.scrollEl || null;          // скролл-контейнер для инструмента «рука»
    const onToolChange = opts.onToolChange || null; // уведомление владельца о смене инструмента
    let _onMutated = opts.onMutated || function(){};
    function blockContentEarly() {
      const irEl = previewEl.querySelector('[class^="ir-"]');
      if (irEl) irEl.classList.add("geo-content-block");
    }
    function onMutated() { _onMutated(); requestAnimationFrame(blockContentEarly); }
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
    let tool = "select";   // select | rect | text | frame | hand (панель как в pen.dev)
    let hand = null;
    let create = null;
    let destroyed = false;
    let rafId = null;
    let pendingPointer = null;
    let containerCtx = null;  // ref контейнера, в который вошли (dbl-click enter)

    function scale() { const s = getScale(); return s > 0 ? s : 1; }

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

    /** Конвертирует экранные координаты в координаты превью (учитывая scale и скролл). */
    function screenToCanvas(clientX, clientY) {
      const base = previewEl.getBoundingClientRect();
      const s = scale();
      return { x: (clientX - base.left + previewEl.scrollLeft) / s,
               y: (clientY - base.top + previewEl.scrollTop) / s };
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
          x: (sr.left - base.left + previewEl.scrollLeft) / s,
          y: (sr.top - base.top + previewEl.scrollTop) / s,
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
            x: (r.left - base.left + previewEl.scrollLeft) / s,
            y: (r.top - base.top + previewEl.scrollTop) / s,
            w: r.width / s,
            h: r.height / s,
          });
        });
      });
      return targets;
    }

    /** Геометрический hit-test: возвращает ref элемента под точкой (или null).
     *  deep=true: пропустить контейнеры (секции), выбрать самый вложенный child. */
    function hitTest(clientX, clientY, deep) {
      const pt = screenToCanvas(clientX, clientY);
      const targets = collectHitTargets();
      // идём с конца (верхний z-order первый)
      for (let i = targets.length - 1; i >= 0; i--) {
        const t = targets[i];
        if (pt.x >= t.x && pt.x <= t.x + t.w && pt.y >= t.y && pt.y <= t.y + t.h) {
          // deep mode: пропустить секцию (path===null), вернуть child
          if (deep && t.ref.path === null) continue;
          // если в containerCtx — принимать только children этого контейнера
          if (containerCtx && t.ref.path === null) continue;
          return t.ref;
        }
      }
      // fallback: если deep и не нашли child, вернуть секцию
      if (deep) {
        for (let i = targets.length - 1; i >= 0; i--) {
          const t = targets[i];
          if (pt.x >= t.x && pt.x <= t.x + t.w && pt.y >= t.y && pt.y <= t.y + t.h) {
            return t.ref;
          }
        }
      }
      return null;
    }

    /** Проверяет попадание в resize-хендл текущего выделения. Возвращает направление или null. */
    function hitTestHandle(clientX, clientY) {
      if (!selections.length) return null;
      const primary = selections[selections.length - 1];
      const el = domAt(primary.ref);
      if (!el) return null;
      const s = scale();
      const r = el.getBoundingClientRect();
      const base = previewEl.getBoundingClientRect();
      const hx = (r.left - base.left) / s;
      const hy = (r.top - base.top) / s;
      const hw = r.width / s;
      const hh = r.height / s;
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

    const SNAP_THRESHOLD = 4; // px в canvas-координатах

    /** Вычисляет alignment guides для перемещаемого элемента.
     *  Возвращает { guides: [{axis:'h'|'v', pos:number}], snaps: {dx,dy}, distances: [{...}] } */
    function computeGuides(movingRef, movingRect) {
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
            if (Math.abs(diff) < SNAP_THRESHOLD && Math.abs(diff) < Math.abs(bestDx)) {
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
            if (Math.abs(diff) < SNAP_THRESHOLD && Math.abs(diff) < Math.abs(bestDy)) {
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

      return { guides: uniqueGuides, snaps: { dx: snapDx, dy: snapDy }, distances: Object.values(closestDist) };
    }

    function renderGuides(guidesData) {
      // очистить предыдущие
      overlay().querySelectorAll(".geo-guide, .geo-dist, .geo-dist-line").forEach(el => el.remove());
      if (!guidesData) return;

      // оверлей в canvas-координатах (живёт внутри трансформированного контейнера)
      const inv = 1 / scale();
      guidesData.guides.forEach(g => {
        const el = document.createElement("div");
        el.className = "geo-guide " + (g.axis === "h" ? "geo-guide-h" : "geo-guide-v");
        if (g.axis === "h") el.style.top = g.pos + "px";
        else el.style.left = g.pos + "px";
        overlay().appendChild(el);
      });

      // зелёные distance labels + линии
      guidesData.distances.forEach(d => {
        // линия
        const line = document.createElement("div");
        line.className = "geo-dist-line " + (d.type === "h" ? "geo-dist-line-h" : "geo-dist-line-v");
        if (d.type === "h") {
          line.style.left = d.from + "px";
          line.style.width = (d.to - d.from) + "px";
          line.style.top = d.y + "px";
        } else {
          line.style.top = d.from + "px";
          line.style.height = (d.to - d.from) + "px";
          line.style.left = d.x + "px";
        }
        overlay().appendChild(line);

        // метка
        const label = document.createElement("div");
        label.className = "geo-dist";
        label.textContent = Math.round(d.val) + "px";
        if (d.type === "h") {
          label.style.left = ((d.from + d.to) / 2 - 12 * inv) + "px";
          label.style.top = (d.y - 12 * inv) + "px";
        } else {
          label.style.left = (d.x + 4 * inv) + "px";
          label.style.top = ((d.from + d.to) / 2 - 6 * inv) + "px";
        }
        overlay().appendChild(label);
      });
    }

    function clearGuides() {
      overlay().querySelectorAll(".geo-guide, .geo-dist, .geo-dist-line").forEach(el => el.remove());
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
      ov.dataset.tool = tool;
      syncZoom(ov);
      return ov;
    }

    /** Компенсация зума: экранные размеры ручек/чипов постоянны при любом scale. */
    function syncZoom(ov) {
      (ov || overlay()).style.setProperty("--geo-inv", String(1 / scale()));
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

    /** Перерисовка всех боксов выделения. */
    function renderSelectionBoxes() {
      const cont = selContainer();
      cont.innerHTML = "";
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
        if (i === selections.length - 1) {
          ["nw", "n", "ne", "e", "se", "s", "sw", "w"].forEach(d => {
            const h = document.createElement("span");
            h.className = "geo-h h-" + d;
            h.dataset.dir = d;
            box.appendChild(h);
          });
        }
        placeBox(box, boxRect(el));
        cont.appendChild(box);
      });
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
      el.style.left = x + "px"; el.style.top = y + "px";
      el.style.width = w + "px"; el.style.height = h + "px";
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

      const hits = [];
      const ir = getIR();
      if (ir && ir.tree) {
        ir.tree.forEach((sec, si) => {
          collectIntersecting({ secIdx: si, path: null }, mx, my, mw, mh, hits);
          (sec.children || []).forEach((_, ci) => {
            collectIntersecting({ secIdx: si, path: "children." + ci }, mx, my, mw, mh, hits);
          });
        });
      }

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

    function startCreate(e) {
      const pt = screenToCanvas(e.clientX, e.clientY);
      const cont = containerAt(pt);
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
      create.el.style.left = x + "px"; create.el.style.top = y + "px";
      create.el.style.width = w + "px"; create.el.style.height = h + "px";
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
      const fr = { x: Math.round(rx - cont.x), y: Math.round(ry - cont.y) };
      // как в pen.dev: layoutPosition:absolute — новый элемент не ломает раскладку родителя
      if (!parentFree) fr.absolute = true;
      let child;
      if (tool === "rect") {
        fr.width = Math.round(clicked ? 120 : Math.max(16, rw));
        fr.height = Math.round(clicked ? 90 : Math.max(16, rh));
        child = { type: "rect", fill: "#8B5CF6", radius: 8, frame: fr };
      } else if (tool === "text") {
        child = { type: "text", text: "Новый текст", frame: fr };
      } else {
        fr.width = Math.round(clicked ? 240 : Math.max(40, rw));
        fr.height = Math.round(clicked ? 160 : Math.max(40, rh));
        child = { type: "card", children: [], frame: fr };
      }
      contNode.children = contNode.children || [];
      contNode.children.push(child);
      const newPath = (cont.ref.path ? cont.ref.path + "." : "") + "children." + (contNode.children.length - 1);
      selections = [];
      select({ secIdx: cont.ref.secIdx, path: newPath });
      onMutated();
    }

    function collectIntersecting(ref, mx, my, mw, mh, out) {
      const el = domAt(ref);
      if (!el) return;
      const r = boxRect(el);
      if (r.left < mx + mw && r.left + r.width > mx && r.top < my + mh && r.top + r.height > my) {
        out.push(ref);
      }
    }

    /* --- мутации IR --- */

    function relPos(el, baseEl) {
      const s = scale();
      const base = baseEl.getBoundingClientRect();
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(baseEl);
      const pl = parseFloat(cs.paddingLeft) || 0, pt = parseFloat(cs.paddingTop) || 0;
      return { x: Math.round((r.left - base.left) / s - pl),
               y: Math.round((r.top - base.top) / s - pt) };
    }

    function ensureParentFree(ref) {
      const parent = parentOf(ref);
      if (!parent || !parent.dom) return;
      if (parent.node.frame && parent.node.frame.layout === "free") return;
      const s = scale();
      parent.siblings.forEach((sib, j) => {
        const sibEl = siblingDom(parent, j);
        if (!sibEl) return;
        const pos = relPos(sibEl, parent.dom);
        sib.frame = sib.frame || {};
        if (typeof sib.frame.x !== "number") sib.frame.x = Math.round(pos.x);
        if (typeof sib.frame.y !== "number") sib.frame.y = Math.round(pos.y);
      });
      parent.node.frame = Object.assign({}, parent.node.frame, {
        layout: "free",
        height: parent.node.frame.height || Math.round(parent.dom.getBoundingClientRect().height / s),
      });
    }

    function commitMoveFor(d, dx, dy) {
      const parent = parentOf(d.ref);
      if (!parent || !parent.dom) return;
      const curFrame = getFrame(d.ref);
      if (parent.node.frame && parent.node.frame.layout === "free") {
        // НЕ используем relPos — на элементе висит CSS transform от drag,
        // что даст двойное смещение. Берём текущее значение frame + delta.
        const f = Object.assign({}, curFrame);
        f.x = Math.round((typeof f.x === "number" ? f.x : 0) + dx);
        f.y = Math.round((typeof f.y === "number" ? f.y : 0) + dy);
        setFrameData(d.ref, f);
      } else {
        // родитель не free — конвертируем всех сиблингов в free
        const s = scale();
        parent.siblings.forEach((sib, j) => {
          const sibEl = siblingDom(parent, j);
          if (!sibEl) return;
          const sibRef = { secIdx: d.ref.secIdx, path: parent.isRoot ? null : siblingPath(parent, j) };
          const pos = relPos(sibEl, parent.dom);
          const sf = Object.assign({}, getFrame(sibRef));
          if (typeof sf.x !== "number") sf.x = Math.round(pos.x);
          if (typeof sf.y !== "number") sf.y = Math.round(pos.y);
          setFrameData(sibRef, sf);
        });
        parent.node.frame = Object.assign({}, parent.node.frame, {
          layout: "free",
          height: parent.node.frame.height || Math.round(parent.dom.getBoundingClientRect().height / s),
        });
        const f = Object.assign({}, curFrame);
        f.x = Math.round((typeof f.x === "number" ? f.x : 0) + dx);
        f.y = Math.round((typeof f.y === "number" ? f.y : 0) + dy);
        setFrameData(d.ref, f);
      }
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
      f.width = Math.round(d.wLive);
      f.height = Math.round(d.hLive);
      const parent = parentOf(d.ref);
      if (parent && parent.node.frame && parent.node.frame.layout === "free" && (d.txLive || d.tyLive)) {
        f.x = Math.round((typeof f.x === "number" ? f.x : 0) + d.txLive);
        f.y = Math.round((typeof f.y === "number" ? f.y : 0) + d.tyLive);
      }
      setFrameData(d.ref, f);
      onMutated();
    }

    /* --- drag (плавный, через rAF) --- */

    function onPointerDown(e) {
      if (e.button !== 0) return;
      e.preventDefault();
      e.stopPropagation();

      // инструменты панели (как левый тулбар pen.dev)
      if (tool === "hand") { startHand(e); return; }
      if (tool === "rect" || tool === "text" || tool === "frame") { startCreate(e); return; }

      // 1) Проверяем resize-хендлы (геометрически)
      const handleDir = hitTestHandle(e.clientX, e.clientY);
      if (handleDir) {
        startResize(handleDir, e);
        return;
      }

      // 2) Геометрический hit-test по элементам
      // Cmd/Ctrl+click = deep select: пропустить контейнер, выбрать вложенный
      const ref = hitTest(e.clientX, e.clientY, !!(e.ctrlKey || e.metaKey));

      if (!ref) {
        // клик по пустому месту → marquee или deselect
        if (!e.shiftKey) clear();
        startMarquee(e);
        return;
      }

      // 3) Shift+клик → toggle selection
      if (e.shiftKey) {
        toggleSelect(ref);
        return;
      }

      // 4) Клик по невыделенному → выделить
      const alreadySelected = selections.some(s => refKey(s.ref) === refKey(ref));
      if (!alreadySelected) {
        select(ref);
      }

      // 5) Готовим drag (move)
      drag = { startX: e.clientX, startY: e.clientY, moved: false, type: "move", els: [] };
      // pointer capture для непрерывности drag
      overlay().setPointerCapture(e.pointerId);
      overlay().addEventListener("pointermove", onDragMove);
      overlay().addEventListener("pointerup", onDragUp, { once: true });
    }

    function startResize(dir, e) {
      if (!selections.length) return;
      e.preventDefault();
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
        }
      }
      const s = scale();
      if (drag.type === "move") {
        let tx = dx / s, ty = dy / s;

        // smart guides: вычислить alignment и snap
        if (drag.els.length === 1) {
          const d0 = drag.els[0];
          const elRect = boxRect(d0.el); // canvas-координаты
          // исходная позиция без drag + текущее смещение
          const guidesData = computeGuides(d0.ref, { x: elRect.left + tx, y: elRect.top + ty, w: elRect.width, h: elRect.height });
          tx += guidesData.snaps.dx;
          ty += guidesData.snaps.dy;
          renderGuides(guidesData);
        } else {
          clearGuides();
        }

        drag.els.forEach(d => {
          d.el.style.transform = `translate(${tx}px, ${ty}px)`;
        });
        const chip = overlay().querySelector(".geo-box.selected:last-child .geo-chip");
        if (chip) chip.textContent = `Δ ${Math.round(tx)} · ${Math.round(ty)}`;
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
      const dx = (e.clientX - d.startX) / s, dy = (e.clientY - d.startY) / s;
      if (!d.moved) { clearGuides(); return; }
      // очищаем CSS transform ДО commit чтобы relPos не включал drag offset
      if (d.type === "move") {
        d.els && d.els.forEach(de => { if (de.el) de.el.style.transform = ""; });
        clearGuides();
        commitMoveAll(dx, dy);
      }
      else { d.el.style.transform = ""; commitResize(d); }
    }

    /* --- выравнивание (Figma-like) --- */

    function selectedRects() {
      return selections
        .filter(s => s.ref.secIdx != null)
        .map(s => {
          const el = domAt(s.ref);
          if (!el) return null;
          const r = boxRect(el); // canvas-координаты
          return { ref: s.ref, x: r.left, y: r.top, w: r.width, h: r.height };
        })
        .filter(Boolean);
    }

    /** Контентный бокс родителя в canvas-координатах (для одиночного выравнивания). */
    function parentContentRect(ref) {
      const parent = parentOf(ref);
      if (!parent || !parent.dom) return null;
      const r = boxRect(parent.dom);
      const cs = getComputedStyle(parent.dom);
      const pl = parseFloat(cs.paddingLeft) || 0, pr = parseFloat(cs.paddingRight) || 0;
      const pt = parseFloat(cs.paddingTop) || 0, pb = parseFloat(cs.paddingBottom) || 0;
      return { w: r.width - pl - pr, h: r.height - pt - pb };
    }

    function applyAlign(mutator, single) {
      const rects = selectedRects();
      if (!rects.length) return;
      onCommit();
      if (rects.length === 1) {
        // как в Pencil: одиночное выделение выравнивается внутри родителя
        const pc = parentContentRect(rects[0].ref);
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

    /* --- клавиатура: nudge, escape, delete --- */

    function onKeydown(e) {
      const ae = document.activeElement;
      if (ae && (ae.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName))) return;

      // хоткеи инструментов как в pen.dev: V/R/T/F/H
      const toolKeys = { v: "select", r: "rect", t: "text", f: "frame", h: "hand" };
      const tk = toolKeys[e.key.toLowerCase()];
      if (tk && !e.ctrlKey && !e.metaKey && !e.altKey) { setTool(tk); return; }

      // Esc: выйти из контейнера или снять выделение
      if (e.key === "Escape") {
        if (containerCtx) {
          containerCtx = null;
          clear();
          renderContainerBadge();
          return;
        }
        if (selections.length) { clear(); return; }
      }

      // Arrow keys: nudge выделенных элементов
      if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key) && selections.length) {
        e.preventDefault();
        const step = e.shiftKey ? 10 : 1;
        let dx = 0, dy = 0;
        if (e.key === "ArrowLeft") dx = -step;
        if (e.key === "ArrowRight") dx = step;
        if (e.key === "ArrowUp") dy = -step;
        if (e.key === "ArrowDown") dy = step;
        onCommit();
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

      // Delete / Backspace: удалить выделенные элементы
      if ((e.key === "Delete" || e.key === "Backspace") && selections.length) {
        e.preventDefault();
        onCommit();
        const ir = getIR();
        // удаляем в обратном порядке чтобы индексы не съехали
        const toDelete = selections
          .filter(s => s.ref.secIdx != null && s.ref.path && s.ref.path.startsWith("children."))
          .sort((a, b) => {
            const ai = parseInt(a.ref.path.split(".")[1]);
            const bi = parseInt(b.ref.path.split(".")[1]);
            return bi - ai;
          });
        toDelete.forEach(sel => {
          const sec = ir.tree[sel.ref.secIdx];
          if (!sec || !sec.children) return;
          const idx = parseInt(sel.ref.path.split(".")[1]);
          if (idx >= 0 && idx < sec.children.length) {
            sec.children.splice(idx, 1);
          }
        });
        clear();
        onMutated();
        return;
      }

      // Cmd/Ctrl+D: duplicate
      if ((e.key === "d" || e.key === "D") && (e.ctrlKey || e.metaKey) && selections.length) {
        e.preventDefault();
        onCommit();
        const ir = getIR();
        const newRefs = [];
        selections.forEach(sel => {
          if (sel.ref.secIdx == null || !sel.ref.path) return;
          const sec = ir.tree[sel.ref.secIdx];
          if (!sec) return;
          const node = getByPath(sec, sel.ref.path);
          if (!node) return;
          const dup = JSON.parse(JSON.stringify(node));
          // сдвиг на 10px
          if (dup.frame) { dup.frame.x = (dup.frame.x || 0) + 10; dup.frame.y = (dup.frame.y || 0) + 10; }
          if (sel.ref.path.startsWith("children.") && sec.children) {
            sec.children.push(dup);
            newRefs.push({ secIdx: sel.ref.secIdx, path: `children.${sec.children.length - 1}` });
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
          setByPath(sec, path, newText);
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
        badge.style.cssText = "position:absolute;top:4px;left:4px;background:#5B5BD6;color:#fff;font:600 11px 'Inter',system-ui,sans-serif;padding:2px 8px;border-radius:4px;pointer-events:none;z-index:55;";
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
    document.addEventListener("keydown", onKeydown);
    window.addEventListener("resize", onResizeWin);

    function destroy() {
      if (destroyed) return;
      destroyed = true;
      if (rafId) cancelAnimationFrame(rafId);
      const ov = overlay();
      ov.removeEventListener("pointerdown", onPointerDown);
      ov.removeEventListener("pointermove", onHover);
      ov.removeEventListener("pointerleave", hideHover);
      ov.removeEventListener("dblclick", onDblClick);
      document.removeEventListener("keydown", onKeydown);
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
      setFrame,
      setFrameProps,
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
      destroy,
      get selection() { return selections[0] || null; },
      get selections() { return selections; },
    };
  }

  global.GeoEdit = { attach };
})(window);
