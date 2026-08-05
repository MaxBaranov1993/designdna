/* DesignAI Web — нодовый редактор (Houdini-like граф, Figma-инструменты в ноде Edit).
 * Чистый vanilla JS. Данные: nodes[] + edges[] + view; автосейв в localStorage.
 * Dataflow: pull-based. Генератор и микс выполняются по кнопке; текстовые ноды
 * (Промпт/Референс) propagate живой текст; нода Edit мутирует IR инструментами GeoEdit.
 */
(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const viewport = $("#viewport");
  const world = $("#world");
  const wiresSvg = $("#wires");

  /* ---------- состояние ---------- */

  let nodes = [];   // {id, type, x, y, data, el, geo?}
  let edges = [];   // {from:{node,port}, to:{node,port}}
  let view = { x: 80, y: 40, zoom: 1 };
  let nextId = 1;
  let selectedId = null;

  const LS_KEY = "designai-graph-v1";

  const NODE_DEFS = {
    prompt:    { title: "Промпт",            icon: "✎", w: 260 },
    reference: { title: "Референс",          icon: "▣", w: 270 },
    generator: { title: "Генератор",         icon: "◈", w: 300 },
    edit:      { title: "Редактор (DNA)",    icon: "⬚", w: 780 },
    mix:       { title: "Микс",              icon: "⊕", w: 290 },
    clone:     { title: "Клон (сайт)",       icon: "", w: 310 },
    reproduce: { title: "Reproduce (pixel)", icon: "◎", w: 340 },
  };

  // декларация портов (у mix входы динамические — в data.inputs)
  const PORTS = {
    prompt:    { in: [], out: [{ name: "out", label: "текст", kind: "text" }] },
    reference: { in: [{ name: "ir", label: "IR", kind: "ir" }],
                 out: [{ name: "out", label: "стиль", kind: "text" }] },
    generator: { in: [{ name: "prompt", label: "промт", kind: "text" },
                       { name: "style", label: "стиль", kind: "text" }],
                 out: [{ name: "ir", label: "варианты", kind: "ir" }] },
    edit:      { in: [{ name: "ir", label: "IR", kind: "ir" }],
                 out: [{ name: "ir", label: "IR", kind: "ir" }] },
    mix:       { in: [], out: [{ name: "ir", label: "IR", kind: "ir" }] },
    clone:     { in: [], out: [{ name: "ir", label: "IR", kind: "ir" }] },
    reproduce: { in: [], out: [{ name: "ir", label: "IR", kind: "ir" },
                                { name: "html", label: "HTML", kind: "text" },
                                { name: "diff", label: "diff", kind: "text" }] },
  };

  /* ---------- утилиты ---------- */

  function toast(msg, kind) {
    const el = document.createElement("div");
    el.className = "toast" + (kind ? " " + kind : "");
    el.textContent = msg;
    $("#toasts").appendChild(el);
    setTimeout(() => el.remove(), kind === "error" ? 7000 : 3500);
  }

  async function api(path, body) {
    const resp = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    let data;
    try { data = await resp.json(); } catch { data = {}; }
    if (!resp.ok) throw new Error(data.detail || ("HTTP " + resp.status));
    return data;
  }

  const clone = (o) => JSON.parse(JSON.stringify(o));
  const nodeById = (id) => nodes.find(n => n.id === id);

  function portsOf(n) {
    if (n.type === "mix") {
      return {
        in: (n.data.inputs || []).map(name => ({ name, label: name, kind: "ir" })),
        out: PORTS.mix.out,
      };
    }
    return PORTS[n.type];
  }

  /* ---------- вид: панорама и зум ---------- */

  function applyView() {
    world.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`;
    viewport.style.backgroundPosition = `${view.x}px ${view.y}px`;
    viewport.style.backgroundSize = `${24 * view.zoom}px ${24 * view.zoom}px`;
    $("#zoom-label").textContent = Math.round(view.zoom * 100) + "%";
  }

  function toWorld(clientX, clientY) {
    const r = viewport.getBoundingClientRect();
    return { x: (clientX - r.left - view.x) / view.zoom, y: (clientY - r.top - view.y) / view.zoom };
  }

  viewport.addEventListener("wheel", (e) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
    const z = Math.min(2, Math.max(0.25, view.zoom * factor));
    const r = viewport.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    // зум к курсору
    view.x = mx - (mx - view.x) * (z / view.zoom);
    view.y = my - (my - view.y) * (z / view.zoom);
    view.zoom = z;
    applyView();
  }, { passive: false });

  // панорама: drag по фону (не по нодам)
  viewport.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 && e.button !== 1) return;
    if (e.target.closest(".node")) return;
    hideCtxMenu();
    selectNode(null);
    const start = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
    viewport.classList.add("panning");
    const move = (ev) => {
      view.x = start.vx + (ev.clientX - start.x);
      view.y = start.vy + (ev.clientY - start.y);
      applyView();
    };
    const up = () => {
      viewport.classList.remove("panning");
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up, { once: true });
  });

  function fitAll() {
    if (!nodes.length) { view = { x: 80, y: 40, zoom: 1 }; applyView(); return; }
    const xs = nodes.map(n => n.x), ys = nodes.map(n => n.y);
    const xe = nodes.map(n => n.x + (n.el ? n.el.offsetWidth : 300));
    const ye = nodes.map(n => n.y + (n.el ? n.el.offsetHeight : 200));
    const minX = Math.min(...xs) - 60, minY = Math.min(...ys) - 60;
    const maxX = Math.max(...xe) + 60, maxY = Math.max(...ye) + 60;
    const r = viewport.getBoundingClientRect();
    const z = Math.min(1, Math.max(0.25, Math.min(r.width / (maxX - minX), r.height / (maxY - minY))));
    view.zoom = z;
    view.x = (r.width - (maxX - minX) * z) / 2 - minX * z;
    view.y = (r.height - (maxY - minY) * z) / 2 - minY * z;
    applyView();
  }

  /* ---------- ноды: DOM ---------- */

  function portRowHtml(dir, p) {
    return `<div class="port-row ${dir}" data-port="${p.name}" data-kind="${p.kind}">
      ${dir === "in" ? '<span class="port"></span>' : ""}<span class="plabel">${p.label}</span>${dir === "out" ? '<span class="port"></span>' : ""}
    </div>`;
  }

  function bodyHtml(n) {
    const ports = portsOf(n);
    // у mix входы динамические — их строки (с портами) собирает renderMixInputs
    const ins = n.type === "mix" ? "" : ports.in.map(p => portRowHtml("in", p)).join("");
    const outs = ports.out.map(p => portRowHtml("out", p)).join("");
    let inner = "";

    if (n.type === "prompt") {
      inner = `<textarea class="f-text" placeholder="Что нужно сделать? Например: шапка маркетплейса объявлений…">${esc(n.data.text || "")}</textarea>`;
    }

    if (n.type === "reference") {
      inner = `<img class="ref-img" alt="референс">
        <label class="ref-drop">Кликните, чтобы выбрать скриншот/изображение<input type="file" accept="image/*" class="f-file" hidden></label>
        <textarea class="f-brief" placeholder="Описание стиля / что взять из референса (уходит в провод)">${esc(n.data.brief || "")}</textarea>
        <label class="ref-decompose" style="display:flex;align-items:center;gap:8px;margin-top:6px;cursor:pointer;font-size:12px;color:var(--muted)">
          <input type="checkbox" class="f-decompose" style="accent-color:var(--accent);width:15px;height:15px;cursor:pointer">
          <span>Разбить на компоненты</span>
        </label>`;
    }

    if (n.type === "generator") {
      inner = `<textarea class="f-own" placeholder="Свой промпт (если нет провода)">${esc(n.data.ownPrompt || "")}</textarea>
        <div class="ctl-row">
          <select class="f-provider"><option value="qwen">qwen3.7-max</option><option value="kimi">kimi k3</option><option value="openrouter">openrouter (auto)</option></select>
          <select class="f-count"><option value="1">1</option><option value="2">2</option><option value="3">3</option></select>
          <button class="btn primary small f-run">▶</button>
        </div>
        <div class="thumbs"></div>
        <div class="gen-actions" style="display:flex;gap:6px;margin-top:6px">
          <button class="btn small f-to-editor" style="flex:1">→ Editor</button>
          <button class="btn small f-to-reference" style="flex:1">→ Reference</button>
        </div>`;
    }

    if (n.type === "edit") {
      inner = `<div class="edit-wrap">
        <div class="edit-left">
          <div class="edit-preview"><div class="edit-inner"><div class="placeholder">Подключите IR к входу (или через GraphDev.setIR)</div></div></div>
          <div class="geo-tools"><span class="sel-label">—</span>
            <button class="btn small f-zoom-out" title="Уменьшить">−</button><span class="zoom-label">—</span><button class="btn small f-zoom-in" title="Увеличить">+</button>
            <button class="btn small f-frame-reset" style="margin-left:auto">Сбросить frame</button></div>
        </div>
        <div class="edit-inspector"></div>
      </div>
      <button class="btn primary small f-open-editor" style="width:100%;margin-top:6px">✦ Открыть DNA-редактор</button>`;
    }

    if (n.type === "mix") {
      inner = `<div class="mix-inputs"></div>
        <div class="ctl-row"><button class="btn small f-add-in">+ вход</button>
        <button class="btn primary small f-run" style="margin-left:auto">Смешать по весам</button></div>`;
    }

    if (n.type === "clone") {
      inner = `<input type="text" class="f-url" placeholder="https://example.com/page" value="${esc(n.data.url || "")}">
        <textarea class="f-component" placeholder="Какой компонент клонировать? Например: шапка с навигацией, карточка товара, боковая панель…">${esc(n.data.component || "")}</textarea>
        <div class="ctl-row">
          <select class="f-provider"><option value="qwen">qwen3.7-max</option><option value="kimi">kimi k3</option><option value="openrouter">openrouter (auto)</option></select>
          <button class="btn primary small f-run" style="margin-left:auto">⧉ Клонировать</button>
        </div>`;
    }

    if (n.type === "reproduce") {
      inner = `<img class="ref-img" alt="скриншот" style="max-height:120px;object-fit:contain">
        <label class="ref-drop">Кликните: скриншот UI для воспроизведения<input type="file" accept="image/*" class="f-file" hidden></label>
        <div class="ctl-row">
          <select class="f-provider">
            <option value="qwen">qwen (vision)</option>
            <option value="gemini">gemini</option>
            <option value="groq">groq</option>
            <option value="xai">xai grok</option>
            <option value="glm">glm-4v</option>
            <option value="openrouter">openrouter (auto)</option>
          </select>
          <button class="btn primary small f-run" style="margin-left:auto">◎ Reproduce</button>
        </div>
        <div class="repro-results" style="display:none;margin-top:6px">
          <div class="repro-diff" style="font-size:11px;color:var(--muted)"></div>
          <div class="repro-colors" style="font-size:11px;margin-top:4px"></div>
          <div style="display:flex;gap:6px;margin-top:6px">
            <button class="btn small f-view-html" style="flex:1">HTML</button>
            <button class="btn small f-view-diff" style="flex:1">Diff</button>
            <button class="btn small f-to-editor" style="flex:1">→ Editor</button>
          </div>
          <div class="repro-preview" style="margin-top:6px;border:1px solid var(--border);border-radius:6px;overflow:hidden"></div>
        </div>`;
    }

    return `${ins}${inner}<div class="n-status"></div>${outs}`;
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function addNode(type, x, y) {
    const def = NODE_DEFS[type];
    const n = { id: nextId++, type, x: Math.round(x), y: Math.round(y), data: defaultData(type) };
    nodes.push(n);
    buildNodeDom(n);
    $("#empty-note").style.display = "none";
    selectNode(n.id);
    save();
    return n;
  }

  function defaultData(type) {
    if (type === "prompt") return { text: "" };
    if (type === "reference") return { brief: "", image: null, fileName: "", decomposed: false };
    if (type === "generator") return { provider: "qwen", count: 2, ownPrompt: "", variants: [], active: 0 };
    if (type === "edit") return { ir: null };
    if (type === "mix") return { inputs: ["a", "b"], weights: { a: 70, b: 30 }, ir: null };
    if (type === "clone") return { url: "", component: "", ir: null };
    if (type === "reproduce") return { image: null, fileName: "", provider: "qwen", result: null };
    return {};
  }

  function buildNodeDom(n) {
    const def = NODE_DEFS[n.type];
    const el = document.createElement("div");
    el.className = "node n-" + n.type;
    el.dataset.id = n.id;
    el.style.left = n.x + "px";
    el.style.top = n.y + "px";
    el.style.width = def.w + "px";
    el.innerHTML = `<div class="node-head"><span class="n-icon">${def.icon}</span>
      <span class="n-title">${def.title}</span><button class="n-x" title="Удалить ноду (Del)">✕</button></div>
      <div class="node-body">${bodyHtml(n)}</div>`;
    world.appendChild(el);
    n.el = el;
    wireNodeEvents(n);
    if (n.type === "generator") renderThumbs(n);
    if (n.type === "edit") setupEditNode(n);
    if (n.type === "mix") renderMixInputs(n);
    if (n.type === "reference" && n.data.image) showRefImage(n);
    refreshPortStates();
  }

  function removeNode(id) {
    const i = nodes.findIndex(n => n.id === id);
    if (i < 0) return;
    const n = nodes[i];
    if (n.geo) n.geo.destroy();
    n.el.remove();
    nodes.splice(i, 1);
    edges = edges.filter(e => e.from.node !== id && e.to.node !== id);
    if (selectedId === id) selectedId = null;
    drawWires();
    save();
    if (!nodes.length) $("#empty-note").style.display = "";
  }

  function selectNode(id) {
    selectedId = id;
    for (const n of nodes) n.el.classList.toggle("selected", n.id === id);
  }

  function setStatus(n, text, kind) {
    const el = n.el.querySelector(".n-status");
    el.textContent = text || "";
    el.className = "n-status" + (kind ? " " + kind : "");
  }

  /* ---------- события ноды ---------- */

  function wireNodeEvents(n) {
    const el = n.el;

    // перетаскивание ноды (за любое место, кроме контролов и портов)
    el.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      if (e.target.closest("textarea, button, select, input, label, .port, .thumb, a")) return;
      selectNode(n.id);
      e.preventDefault();
      const start = { x: e.clientX, y: e.clientY, nx: n.x, ny: n.y };
      const move = (ev) => {
        n.x = Math.round(start.nx + (ev.clientX - start.x) / view.zoom);
        n.y = Math.round(start.ny + (ev.clientY - start.y) / view.zoom);
        el.style.left = n.x + "px";
        el.style.top = n.y + "px";
        drawWires();
      };
      const up = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
        save();
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up, { once: true });
    });

    el.querySelector(".n-x").addEventListener("click", () => removeNode(n.id));

    // старт соединения с выходного порта
    for (const row of el.querySelectorAll(".port-row.out")) {
      row.querySelector(".port").addEventListener("pointerdown", (e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        e.stopPropagation();
        startWireDrag(n, row.dataset.port, row.dataset.kind, e);
      });
    }

    // тип-специфичные контролы
    if (n.type === "prompt") {
      const ta = el.querySelector(".f-text");
      ta.addEventListener("input", () => { n.data.text = ta.value; propagate(n.id); save(); });
    }

    if (n.type === "reference") {
      const file = el.querySelector(".f-file");
      file.addEventListener("change", () => {
        const f = file.files && file.files[0];
        if (!f) return;
        const rd = new FileReader();
        rd.onload = () => { n.data.image = rd.result; n.data.fileName = f.name; showRefImage(n); save(); };
        rd.readAsDataURL(f);
      });
      const brief = el.querySelector(".f-brief");
      brief.addEventListener("input", () => { n.data.brief = brief.value; propagate(n.id); save(); });
      const decomposeCb = el.querySelector(".f-decompose");
      if (decomposeCb) {
        decomposeCb.checked = !!n.data.decomposed;
        decomposeCb.addEventListener("change", () => {
          if (decomposeCb.checked) runDecompose(n);
          else n.data.decomposed = false;
          save();
        });
      }
    }

    if (n.type === "generator") {
      el.querySelector(".f-provider").value = n.data.provider;
      el.querySelector(".f-count").value = String(n.data.count);
      el.querySelector(".f-provider").addEventListener("change", (e) => { n.data.provider = e.target.value; save(); });
      el.querySelector(".f-count").addEventListener("change", (e) => { n.data.count = Number(e.target.value); save(); });
      el.querySelector(".f-own").addEventListener("input", (e) => { n.data.ownPrompt = e.target.value; save(); });
      el.querySelector(".f-run").addEventListener("click", () => runGenerator(n));
      el.querySelector(".f-to-editor").addEventListener("click", () => sendToNode(n, "edit"));
      el.querySelector(".f-to-reference").addEventListener("click", () => sendToNode(n, "reference"));
    }

    if (n.type === "mix") {
      el.querySelector(".f-add-in").addEventListener("click", () => {
        if (n.data.inputs.length >= 4) { toast("Максимум 4 входа", "error"); return; }
        const name = ["a", "b", "c", "d"][n.data.inputs.length];
        n.data.inputs.push(name);
        n.data.weights[name] = 50;
        renderMixInputs(n);
        refreshPortStates();
        drawWires();
        save();
      });
      el.querySelector(".f-run").addEventListener("click", () => runMix(n));
    }

    if (n.type === "clone") {
      el.querySelector(".f-url").addEventListener("input", (e) => { n.data.url = e.target.value; save(); });
      el.querySelector(".f-component").addEventListener("input", (e) => { n.data.component = e.target.value; save(); });
      el.querySelector(".f-provider").value = n.data.provider || "qwen";
      el.querySelector(".f-provider").addEventListener("change", (e) => { n.data.provider = e.target.value; save(); });
      el.querySelector(".f-run").addEventListener("click", () => runClone(n));
    }

    if (n.type === "reproduce") {
      const file = el.querySelector(".f-file");
      file.addEventListener("change", () => {
        const f = file.files && file.files[0];
        if (!f) return;
        const rd = new FileReader();
        rd.onload = () => {
          n.data.image = rd.result;
          n.data.fileName = f.name;
          const img = el.querySelector(".ref-img");
          img.src = rd.result;
          img.style.display = "block";
          el.querySelector(".ref-drop").textContent = f.name + " (заменить)";
          save();
        };
        rd.readAsDataURL(f);
      });
      el.querySelector(".f-provider").value = n.data.provider || "qwen";
      el.querySelector(".f-provider").addEventListener("change", (e) => { n.data.provider = e.target.value; save(); });
      el.querySelector(".f-run").addEventListener("click", () => runReproduce(n));
      el.querySelector(".f-view-html").addEventListener("click", () => {
        if (!n.data.result || !n.data.result.html) { toast("Сначала запустите Reproduce", "error"); return; }
        const w = window.open("", "_blank");
        w.document.write(n.data.result.html);
        w.document.close();
      });
      el.querySelector(".f-view-diff").addEventListener("click", () => {
        if (!n.data.result || !n.data.result.diff) { toast("Сначала запустите Reproduce", "error"); return; }
        const d = n.data.result.diff;
        const lines = [`Overall: ${d.overall_pct}%`, `Mean RGB: ${d.mean_rgb.join(", ")}`];
        if (d.regions) for (const [k, v] of Object.entries(d.regions)) lines.push(`${k}: ${v.pct}% (max ${v.max})`);
        alert(lines.join("\n"));
      });
      el.querySelector(".f-to-editor").addEventListener("click", () => sendToNode(n, "edit"));
      // восстановить изображение из сейва
      if (n.data.image) {
        const img = el.querySelector(".ref-img");
        img.src = n.data.image;
        img.style.display = "block";
        el.querySelector(".ref-drop").textContent = (n.data.fileName || "скриншот") + " (заменить)";
      }
      if (n.data.result) renderReproResults(n);
    }
  }

  function showRefImage(n) {
    const img = n.el.querySelector(".ref-img");
    img.src = n.data.image;
    img.style.display = "block";
    n.el.querySelector(".ref-drop").textContent = n.data.fileName || "Заменить изображение";
  }

  /* ---------- генератор ---------- */

  function renderThumbs(n) {
    const box = n.el.querySelector(".thumbs");
    box.innerHTML = "";
    n.data.variants.forEach((ir, i) => {
      const t = document.createElement("div");
      t.className = "thumb" + (i === n.data.active ? " active" : "");
      t.innerHTML = `<span class="tbadge">${i + 1}</span><div class="tprev"></div>`;
      t.addEventListener("click", () => {
        n.data.active = i;
        renderThumbs(n);
        propagate(n.id);
        save();
      });
      box.appendChild(t);
      IRRenderer.renderIR(t.querySelector(".tprev"), ir);
    });
  }

  async function runGenerator(n) {
    const brief = (pullInput(n, "prompt") || n.data.ownPrompt || "").trim();
    if (!brief) { setStatus(n, "Нет промта: подключите провод или заполните поле", "err"); return; }
    const styleHint = pullInput(n, "style") || undefined;
    setStatus(n, `Генерация (${n.data.provider}, ${n.data.count})… 20–120 сек`);
    n.el.querySelector(".f-run").disabled = true;
    try {
      const res = await api("/api/generate", { brief, count: n.data.count, provider: n.data.provider, styleHint });
      n.data.variants = res.variants;
      n.data.active = 0;
      renderThumbs(n);
      const errNote = res.errors && res.errors.length ? `, ошибок: ${res.errors.length}` : "";
      setStatus(n, `Готово: вариантов ${res.variants.length}${errNote}`, "ok");
      propagate(n.id);
      save();
    } catch (e) {
      setStatus(n, "Ошибка: " + e.message, "err");
    } finally {
      n.el.querySelector(".f-run").disabled = false;
    }
  }

  /* ---------- быстрое создание подключённой ноды ---------- */

  function sendToNode(srcNode, targetType) {
    const ir = outValue(srcNode);
    if (!ir) { toast("Сначала запустите ноду (▶ / ◎ Reproduce)", "error"); return; }
    const def = NODE_DEFS[srcNode.type];
    const newX = srcNode.x + (def ? def.w : 270) + 60;
    const newY = srcNode.y;
    const target = addNode(targetType, newX, newY);

    if (targetType === "edit") {
      target.data.ir = clone(ir);
      if (target.refreshEdit) target.refreshEdit();
    } else if (targetType === "reference") {
      target.data.ir = clone(ir);
      setStatus(target, "IR получен от генератора", "ok");
    }

    // соединяем проводом
    connect(
      { node: srcNode.id, port: "ir" },
      { node: target.id, port: "ir" }
    );
    toast(`→ ${NODE_DEFS[targetType].title}`, "ok");
    save();
  }

  /* ---------- декомпозиция IR на компоненты (free-layout) ---------- */

  /** Конвертирует IR из flow-раскладки в free-layout: каждая секция — absolute с измеренной позицией. */
  function decomposeIR(ir) {
    const out = JSON.parse(JSON.stringify(ir));
    const tree = out.tree || [];
    if (!tree.length) return out;

    // рендерим в скрытый контейнер для измерения высот
    const tmp = document.createElement("div");
    tmp.style.cssText = "position:fixed;left:-9999px;top:0;width:960px;visibility:hidden;pointer-events:none";
    document.body.appendChild(tmp);
    IRRenderer.renderIR(tmp, out);

    const designW = 960;
    let cumY = 0;
    tree.forEach((sec, i) => {
      const secEl = tmp.querySelector(`[data-ir-sec="${i}"]`);
      const h = secEl ? secEl.offsetHeight : 400;
      sec.frame = Object.assign({}, sec.frame, {
        x: 0, y: cumY, width: designW, height: h,
      });
      cumY += h;
    });

    out.frame = Object.assign({}, out.frame, {
      layout: "free", width: designW, height: cumY,
    });

    tmp.remove();
    return out;
  }

  async function runDecompose(refNode) {
    const brief = (refNode.data.brief || "").trim();

    // ищем IR: 1) на самой ноде (от провода), 2) vision из скриншота, 3) генерим из brief
    let ir = refNode.data.ir || null;

    if (!ir) {
      const inEdge = edges.find(e => e.to.node === refNode.id && e.to.port === "ir");
      if (inEdge) {
        const src = nodeById(inEdge.from.node);
        if (src) ir = outValue(src);
      }
    }

    // vision-анализ скриншота (pixel-perfect)
    if (!ir && refNode.data.image) {
      setStatus(refNode, "Vision-анализ скриншота (pixel-perfect)… 30–90 сек");
      try {
        const res = await api("/api/vision-decompose", {
          image: refNode.data.image,
          brief: brief || "",
          provider: "qwen",
        });
        if (res.ir) ir = res.ir;
      } catch (e) {
        setStatus(refNode, "Vision ошибка: " + e.message, "err");
        refNode.el.querySelector(".f-decompose").checked = false;
        return;
      }
    }

    // fallback: генерация из текста
    if (!ir && brief) {
      setStatus(refNode, "Генерация IR из описания…");
      try {
        const res = await api("/api/generate", { brief, count: 1, provider: "qwen" });
        if (res.variants && res.variants.length) ir = res.variants[0];
      } catch (e) {
        setStatus(refNode, "Ошибка генерации: " + e.message, "err");
        refNode.el.querySelector(".f-decompose").checked = false;
        return;
      }
    }

    if (!ir) {
      toast("Не удалось получить IR — загрузите скриншот или подключите генератор", "error");
      refNode.el.querySelector(".f-decompose").checked = false;
      return;
    }

    const decomposed = decomposeIR(ir);
    refNode.data.decomposed = true;

    const editNode = addNode("edit", refNode.x + 310, refNode.y);
    editNode.data.ir = decomposed;
    editNode.refreshEdit();

    setStatus(refNode, "Декомпозиция готова → Editor", "ok");
    toast("Компоненты разбиты в Editor-ноде", "ok");
    save();
  }

  /* ---------- редактор (Figma-инструменты через GeoEdit) ---------- */

  /* ---------- undo/redo Edit-ноды ---------- */

  function applyEditSnapshot(n, snap) {
    n.data.ir = snap;
    if (n.refreshEdit) n.refreshEdit();
    propagate(n.id);
    save();
  }
  function undoEditNode(n) {
    if (!n.history || !n.data.ir) return;
    const snap = n.history.undo(() => n.data.ir);
    if (snap) applyEditSnapshot(n, snap);
  }
  function redoEditNode(n) {
    if (!n.history || !n.data.ir) return;
    const snap = n.history.redo(() => n.data.ir);
    if (snap) applyEditSnapshot(n, snap);
  }

  /* Edit-нода: превью слева + инспектор (модель pen.dev) справа.
   * refreshEdit — единственная точка lifecycle: рендер → attach GeoEdit → инспектор.
   * Оверлей GeoEdit живёт внутри .edit-inner (трансформированный контейнер),
   * поэтому рамки выделения всегда совпадают с элементами при любом зуме. */
  function setupEditNode(n) {
    const prev = n.el.querySelector(".edit-preview");
    const inner = n.el.querySelector(".edit-inner");
    const selLabel = n.el.querySelector(".sel-label");
    const inspEl = n.el.querySelector(".edit-inspector");
    const zoomLabel = n.el.querySelector(".geo-tools .zoom-label");

    // общая snapshot-история IR на ноду (undo/redo, коалесценция быстрых серий)
    if (!n.history) n.history = IRHistory.createHistory({ limit: 50 });
    // ключ коалесценции: выделение, актуальное к моменту onCommit
    let selKey = "";

    if (!n._editWired) {
      n._editWired = true;
      // скролл превью не должен зумить граф
      prev.addEventListener("wheel", (e) => e.stopPropagation(), { passive: true });
      n.el.querySelector(".f-zoom-in").addEventListener("click", () => zoomBy(1.25));
      n.el.querySelector(".f-zoom-out").addEventListener("click", () => zoomBy(1 / 1.25));
      n.el.querySelector(".f-frame-reset").addEventListener("click", () => {
        if (n.geo) n.geo.resetFrame();
      });
      n.el.querySelector(".f-open-editor").addEventListener("click", () => {
        if (!n.data.ir) { toast("Сначала подключите IR к входу ноды", "error"); return; }
        Editor.open(n, (ir) => {
          n.data.ir = ir;
          n.refreshEdit();
          propagate(n.id);
          save();
          toast("IR сохранён из редактора", "ok");
        });
      });
    }

    function currentZoom() {
      const irEl = inner.querySelector('[class^="ir-"]');
      if (!irEl) return 1;
      const dw = Number(irEl.dataset.designWidth) || IRRenderer.DESIGN_WIDTH;
      const fit = Math.min(1, (prev.clientWidth || 300) / dw);
      return n.editZoom == null ? fit : n.editZoom;
    }

    function applyZoom() {
      const irEl = inner.querySelector('[class^="ir-"]');
      if (!irEl) { if (zoomLabel) zoomLabel.textContent = "—"; return; }
      const z = currentZoom();
      irEl.style.transform = `scale(${z})`;
      inner.style.height = (irEl.offsetHeight * z) + "px";
      if (zoomLabel) zoomLabel.textContent = Math.round(z * 100) + "%";
      if (n.geo) n.geo.syncZoom();
    }

    function zoomBy(factor) {
      n.editZoom = Math.min(2, Math.max(0.05, currentZoom() * factor));
      applyZoom();
      save();
    }

    function renderInsp() {
      Inspector.render(inspEl, {
        ir: n.data.ir,
        selections: n.geo ? n.geo.selections : [],
        geo: n.geo,
      });
    }

    n.refreshEdit = function () {
      const prevRefs = n.geo ? n.geo.selections.map(s => s.ref) : [];
      if (n.geo) { n.geo.destroy(); n.geo = null; }
      renderEditPreview(n);
      n.geo = GeoEdit.attach({
        previewEl: inner,
        getIR: () => n.data.ir,
        getScale: () => {
          const irEl = inner.querySelector('[class^="ir-"]');
          if (!irEl) return 1;
          const dw = Number(irEl.dataset.designWidth) || IRRenderer.DESIGN_WIDTH;
          const w = irEl.getBoundingClientRect().width;
          return w > 0 ? w / dw : 1;
        },
        onCommit: () => {
          // снапшот ДО мутации; быстрые серии с одним выделением IRHistory сольёт сам
          if (n.data.ir) n.history.push(() => n.data.ir, selKey);
        },
        onMutated: () => {
          n.refreshEdit();
          propagate(n.id);
          save();
        },
        onSelect: (sels) => {
          selKey = (sels || []).map(s => s.ref.secIdx + ":" + (s.ref.path || "")).join(",");
          selLabel.textContent = sels && sels.length ? sels[0].label : (n.data.ir ? "—" : "нет IR на входе");
          renderInsp();
        },
      });
      // после rAF fitPreview применяем свой зум и синхронизируем оверлей
      requestAnimationFrame(applyZoom);
      if (prevRefs.length) n.geo.selectMulti(prevRefs);
      renderInsp();
    };

    n.refreshEdit();
  }

  function renderEditPreview(n) {
    const inner = n.el.querySelector(".edit-inner");
    if (!n.data.ir) {
      inner.innerHTML = '<div class="placeholder">Подключите IR к входу (или через GraphDev.setIR)</div>';
      return;
    }
    IRRenderer.renderIR(inner, n.data.ir);
  }

  /* ---------- микс ---------- */

  function renderMixInputs(n) {
    const box = n.el.querySelector(".mix-inputs");
    box.innerHTML = "";
    // пересоздаём строки входов вместе с портами
    n.data.inputs.forEach((name) => {
      const row = document.createElement("div");
      row.className = "mix-row";
      row.innerHTML = `${portRowHtml("in", { name, label: "", kind: "ir" })}
        <span class="cap">${name}</span>
        <input type="range" min="0" max="100" value="${n.data.weights[name] ?? 50}">
        <span class="wv">${n.data.weights[name] ?? 50}%</span>
        ${n.data.inputs.length > 1 ? '<button class="mx" title="Убрать вход">✕</button>' : ""}`;
      const range = row.querySelector("input");
      range.addEventListener("input", () => {
        n.data.weights[name] = Number(range.value);
        row.querySelector(".wv").textContent = range.value + "%";
        save();
      });
      const mx = row.querySelector(".mx");
      if (mx) mx.addEventListener("click", () => {
        n.data.inputs = n.data.inputs.filter(x => x !== name);
        delete n.data.weights[name];
        edges = edges.filter(e => !(e.to.node === n.id && e.to.port === name));
        renderMixInputs(n);
        refreshPortStates();
        drawWires();
        save();
      });
      // порт должен слушать старт соединения? нет — только входные: принимающие
      box.appendChild(row);
    });
    // входные порты: drop-цели, глобальный pointerup обрабатывает попадание
  }

  async function runMix(n) {
    const irs = [], weights = [], labels = [];
    for (const name of n.data.inputs) {
      const ir = pullInput(n, name);
      if (ir) {
        irs.push(ir);
        weights.push((n.data.weights[name] ?? 50) / 100);
        labels.push(`${name}:${n.data.weights[name] ?? 50}%`);
      }
    }
    if (irs.length < 2) { setStatus(n, "Нужно минимум 2 подключённых IR-входа", "err"); return; }
    setStatus(n, "Смешиваю…");
    try {
      const res = await api("/api/mix", { irs, weights });
      n.data.ir = res.ir;
      setStatus(n, "Готово: " + labels.join(" + "), "ok");
      propagate(n.id);
      save();
    } catch (e) {
      setStatus(n, "Ошибка: " + e.message, "err");
    }
  }

  async function runClone(n) {
    const url = (n.data.url || "").trim();
    const component = (n.data.component || "").trim();
    if (!url) { setStatus(n, "Введите URL сайта", "err"); return; }
    if (!component) { setStatus(n, "Опишите, какой компонент клонировать", "err"); return; }
    setStatus(n, `Загрузка ${url.slice(0, 30)}…`);
    n.el.querySelector(".f-run").disabled = true;
    try {
      const res = await api("/api/clone", { url, component, provider: n.data.provider || "qwen" });
      n.data.ir = res.ir;
      setStatus(n, "Клон готов", "ok");
      propagate(n.id);
      save();
    } catch (e) {
      setStatus(n, "Ошибка: " + e.message, "err");
    } finally {
      n.el.querySelector(".f-run").disabled = false;
    }
  }

  /* ---------- reproduce (pixel-perfect) ---------- */

  async function runReproduce(n) {
    if (!n.data.image) { setStatus(n, "Загрузите скриншот UI", "err"); return; }
    setStatus(n, `Reproduce (${n.data.provider}): VLM → пиксели → HTML → diff… 30–120 сек`);
    n.el.querySelector(".f-run").disabled = true;
    try {
      const res = await api("/api/reproduce", {
        image: n.data.image,
        provider: n.data.provider || "qwen",
      });
      n.data.result = res;
      renderReproResults(n);
      const diffPct = res.diff && res.diff.overall_pct != null ? res.diff.overall_pct : "?";
      setStatus(n, `Готово: diff ${diffPct}%, цветов ${Object.keys(res.colors.colors || {}).length}, иконок ${res.icons_count}`, "ok");
      propagate(n.id);
      save();
    } catch (e) {
      setStatus(n, "Ошибка: " + e.message, "err");
    } finally {
      n.el.querySelector(".f-run").disabled = false;
    }
  }

  function renderReproResults(n) {
    const box = n.el.querySelector(".repro-results");
    if (!n.data.result) { box.style.display = "none"; return; }
    box.style.display = "block";
    const r = n.data.result;

    // diff
    const diffEl = n.el.querySelector(".repro-diff");
    if (r.diff && r.diff.overall_pct != null) {
      diffEl.innerHTML = `<b>Diff: ${r.diff.overall_pct}%</b> (цель < 5%) · RGB mean: ${r.diff.mean_rgb.join(", ")}`;
    } else if (r.diff && r.diff.error) {
      diffEl.textContent = "Diff: " + r.diff.error;
    } else {
      diffEl.textContent = "Diff: нет данных";
    }

    // colors
    const colorsEl = n.el.querySelector(".repro-colors");
    const colors = r.colors && r.colors.colors ? r.colors.colors : {};
    const swatches = Object.entries(colors).slice(0, 8).map(([name, info]) =>
      `<span style="display:inline-block;width:12px;height:12px;background:${info.hex};border:1px solid #888;border-radius:2px;vertical-align:middle" title="${name}: ${info.hex} (${info.pixels}px)"></span>`
    ).join(" ");
    colorsEl.innerHTML = swatches ? `Цвета: ${swatches}` : "";

    // preview (repro screenshot)
    const prev = n.el.querySelector(".repro-preview");
    if (r.repro_png) {
      prev.innerHTML = `<img src="${r.repro_png}" style="width:100%;display:block" alt="reproduction">`;
    } else {
      prev.innerHTML = '<div style="padding:8px;font-size:11px;color:var(--muted)">Нет скриншота reproduction</div>';
    }
  }

  /* ---------- dataflow ---------- */

  function outValue(n) {
    if (n.type === "prompt") return n.data.text || "";
    if (n.type === "reference") return n.data.brief || (n.data.fileName ? "Референс: " + n.data.fileName : "");
    if (n.type === "generator") return n.data.variants.length ? n.data.variants[n.data.active] || null : null;
    if (n.type === "edit") return n.data.ir || null;
    if (n.type === "mix") return n.data.ir || null;
    if (n.type === "clone") return n.data.ir || null;
    if (n.type === "reproduce") return n.data.result ? n.data.result.ir || null : null;
    return null;
  }

  function pullInput(n, port) {
    const e = edges.find(e => e.to.node === n.id && e.to.port === port);
    if (!e) return null;
    const src = nodeById(e.from.node);
    return src ? outValue(src) : null;
  }

  /** Распространение изменения выхода: edit-потребители заменяют IR (клон!),
   *  mix помечается как stale. Через generator/mix поток не идёт — они run-based. */
  function propagate(startId, visited) {
    visited = visited || new Set();
    if (visited.has(startId)) return;
    visited.add(startId);
    for (const e of edges.filter(e => e.from.node === startId)) {
      const cons = nodeById(e.to.node);
      if (!cons) continue;
      if (cons.type === "edit") {
        const ir = pullInput(cons, "ir");
        if (ir) {
          cons.data.ir = clone(ir);
          if (cons.refreshEdit) cons.refreshEdit(); else renderEditPreview(cons);
          propagate(cons.id, visited);
        }
      } else if (cons.type === "reference") {
        const ir = pullInput(cons, "ir");
        if (ir) {
          cons.data.ir = clone(ir);
          setStatus(cons, "IR получен — можно разбить на компоненты", "ok");
          propagate(cons.id, visited);
        }
      } else if (cons.type === "mix") {
        setStatus(cons, "Входы обновлены — нажмите «Смешать»");
      }
    }
  }

  /* ---------- провода ---------- */

  function portPos(nodeId, portName, dir) {
    const n = nodeById(nodeId);
    if (!n || !n.el) return null;
    const row = n.el.querySelector(`.port-row.${dir}[data-port="${portName}"]`);
    if (!row) return null;
    const p = row.querySelector(".port");
    // getBoundingClientRect даёт экранные координаты; toWorld переводит в мировые
    const r = p.getBoundingClientRect();
    return toWorld(r.left + r.width / 2, r.top + r.height / 2);
  }

  function wirePath(p1, p2) {
    const dx = Math.max(46, Math.abs(p2.x - p1.x) / 2);
    return `M ${p1.x} ${p1.y} C ${p1.x + dx} ${p1.y}, ${p2.x - dx} ${p2.y}, ${p2.x} ${p2.y}`;
  }

  function edgeKind(e) {
    const src = nodeById(e.from.node);
    if (!src) return "text";
    const p = portsOf(src).out.find(p => p.name === e.from.port);
    return p ? p.kind : "text";
  }

  function drawWires(temp) {
    wiresSvg.querySelectorAll("path:not(.w-temp)").forEach(p => p.remove());
    for (const e of edges) {
      const p1 = portPos(e.from.node, e.from.port, "out");
      const p2 = portPos(e.to.node, e.to.port, "in");
      if (!p1 || !p2) continue;
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", wirePath(p1, p2));
      path.setAttribute("class", "w-" + edgeKind(e));
      wiresSvg.appendChild(path);
    }
    if (temp) {
      let t = wiresSvg.querySelector(".w-temp");
      if (!t) {
        t = document.createElementNS("http://www.w3.org/2000/svg", "path");
        t.setAttribute("class", "w-temp");
        wiresSvg.appendChild(t);
      }
      t.setAttribute("d", wirePath(temp.from, temp.to));
    } else {
      const t = wiresSvg.querySelector(".w-temp");
      if (t) t.remove();
    }
  }

  function refreshPortStates() {
    for (const n of nodes) {
      for (const row of n.el.querySelectorAll(".port-row")) {
        const dir = row.classList.contains("in") ? "in" : "out";
        const used = edges.some(e => dir === "in"
          ? e.to.node === n.id && e.to.port === row.dataset.port
          : e.from.node === n.id && e.from.port === row.dataset.port);
        row.classList.toggle("connected", used);
      }
    }
  }

  function reachable(fromId, toId, skipEdge) {
    // есть ли путь fromId -> toId по рёбрам (для проверки циклов)
    const stack = [fromId];
    const seen = new Set();
    while (stack.length) {
      const cur = stack.pop();
      if (cur === toId) return true;
      if (seen.has(cur)) continue;
      seen.add(cur);
      for (const e of edges) {
        if (skipEdge && e === skipEdge) continue;
        if (e.from.node === cur) stack.push(e.to.node);
      }
    }
    return false;
  }

  function connect(from, to) {
    const src = nodeById(from.node), dst = nodeById(to.node);
    if (!src || !dst || src === dst) return false;
    const outP = portsOf(src).out.find(p => p.name === from.port);
    const inP = portsOf(dst).in.find(p => p.name === to.port);
    if (!outP || !inP) return false;
    if (outP.kind !== inP.kind) {
      toast(`Несовместимые порты: ${outP.kind} → ${inP.kind}`, "error");
      return false;
    }
    if (reachable(to.node, from.node)) {
      toast("Нельзя: соединение создаёт цикл", "error");
      return false;
    }
    edges = edges.filter(e => !(e.to.node === to.node && e.to.port === to.port)); // один провод на вход
    edges.push({ from: { node: from.node, port: from.port }, to: { node: to.node, port: to.port } });
    refreshPortStates();
    drawWires();
    propagate(from.node);
    save();
    return true;
  }

  function startWireDrag(srcNode, portName, kind, e) {
    const from = portPos(srcNode.id, portName, "out");
    if (!from) return;
    const move = (ev) => {
      const w = toWorld(ev.clientX, ev.clientY);
      drawWires({ from, to: w });
    };
    const up = (ev) => {
      window.removeEventListener("pointermove", move);
      drawWires();
      const target = document.elementFromPoint(ev.clientX, ev.clientY);
      const row = target && target.closest && target.closest(".port-row.in");
      const nodeEl = target && target.closest && target.closest(".node");
      if (row && nodeEl) {
        connect({ node: srcNode.id, port: portName },
                { node: Number(nodeEl.dataset.id), port: row.dataset.port });
      }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up, { once: true });
  }

  /* ---------- контекстное меню ---------- */

  const CTX_ITEMS = [
    { type: "prompt", note: "текст задачи" },
    { type: "reference", note: "изображение + стиль" },
    { type: "generator", note: "LLM → варианты IR" },
    { type: "edit", note: "DNA-редактор" },
    { type: "mix", note: "смешение по весам" },
    { type: "clone", note: "клон с сайта по URL" },
    { type: "reproduce", note: "pixel-perfect из скриншота" },
  ];

  function showCtxMenu(x, y, worldPt) {
    const menu = $("#ctx-menu");
    menu.innerHTML = '<div class="ctx-cap">Создать ноду</div>' + CTX_ITEMS.map(it =>
      `<div class="ctx-item" data-type="${it.type}"><span class="ci">${NODE_DEFS[it.type].icon}</span>
       ${NODE_DEFS[it.type].title}<small>${it.note}</small></div>`).join("");
    menu.style.display = "block";
    menu.style.left = Math.min(x, window.innerWidth - 210) + "px";
    menu.style.top = Math.min(y, window.innerHeight - 240) + "px";
    menu.onclick = (e) => {
      const item = e.target.closest(".ctx-item");
      if (!item) return;
      addNode(item.dataset.type, worldPt.x, worldPt.y);
      hideCtxMenu();
    };
  }

  function hideCtxMenu() { $("#ctx-menu").style.display = "none"; }

  viewport.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    if (e.target.closest(".node")) return; // на нодах своё не делаем — просто игнор
    showCtxMenu(e.clientX, e.clientY, toWorld(e.clientX, e.clientY));
  });
  document.addEventListener("pointerdown", (e) => {
    if (!e.target.closest("#ctx-menu")) hideCtxMenu();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") hideCtxMenu();
    // Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z — undo/redo IR в выделенной Edit-ноде
    if ((e.ctrlKey || e.metaKey) && !e.altKey && selectedId != null
        && "zyяnн".includes(e.key.toLowerCase())) {
      const ae = document.activeElement;
      if (ae && (ae.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName))) return;
      if (Editor.isOpen()) return; // у полноэкранного редактора своя история
      const n = nodeById(selectedId);
      if (!n || n.type !== "edit" || !n.history) return;
      e.preventDefault();
      const isRedo = e.shiftKey || "yн".includes(e.key.toLowerCase());
      if (isRedo) redoEditNode(n); else undoEditNode(n);
      return;
    }
    if ((e.key === "Delete" || e.key === "Backspace") && selectedId != null) {
      const ae = document.activeElement;
      if (ae && (ae.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName))) return;
      removeNode(selectedId);
    }
  });

  /* ---------- сохранение ---------- */

  let saveTimer = null;
  let lastSaveOk = true;

  /** Fallback при квоте: выкидываем base64/data-URL строки (скриншоты нод
   *  Reproduce/Scrape), остальной IR и граф сохраняются. */
  function stripHeavy(v) {
    if (Array.isArray(v)) return v.map(stripHeavy);
    if (v && typeof v === "object") {
      const out = {};
      for (const [k, val] of Object.entries(v)) {
        if (typeof val === "string" && (val.startsWith("data:") || val.length > 200000)) continue;
        out[k] = stripHeavy(val);
      }
      return out;
    }
    return v;
  }

  function save() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      const data = {
        nodes: nodes.map(n => ({ id: n.id, type: n.type, x: n.x, y: n.y, data: n.data })),
        edges, view, nextId,
      };
      try {
        localStorage.setItem(LS_KEY, JSON.stringify(data));
        lastSaveOk = true;
      } catch (e) {
        try {
          localStorage.setItem(LS_KEY, JSON.stringify(stripHeavy(data)));
          lastSaveOk = true;
          toast("localStorage переполнен — сохранил без скриншотов", "error");
        } catch (e2) {
          lastSaveOk = false;
          toast("Не удалось сохранить граф (localStorage переполнен). Экспортируйте в файл.", "error");
        }
      }
    }, 300);
  }

  // флаш при закрытии вкладки, если последняя запись не удалась
  window.addEventListener("beforeunload", (e) => {
    if (!lastSaveOk) { e.preventDefault(); e.returnValue = ""; }
  });

  function load(data) {
    for (const n of nodes) if (n.geo) n.geo.destroy();
    nodes = [];
    edges = data.edges || [];
    view = data.view || { x: 80, y: 40, zoom: 1 };
    nextId = data.nextId || 1;
    world.querySelectorAll(".node").forEach(el => el.remove());
    for (const raw of data.nodes || []) {
      const n = { id: raw.id, type: raw.type, x: raw.x, y: raw.y, data: raw.data };
      nodes.push(n);
      buildNodeDom(n);
    }
    nextId = Math.max(nextId, ...nodes.map(n => n.id + 1), 1);
    applyView();
    refreshPortStates();
    drawWires();
    if (!nodes.length) $("#empty-note").style.display = "";
  }

  function loadFromStorage() {
    try {
      const raw = localStorage.getItem(LS_KEY);
      if (raw) { load(JSON.parse(raw)); return; }
    } catch (e) { /* битый сейв — начинаем пусто */ }
    applyView();
  }

  /* ---------- топбар ---------- */

  $("#btn-fit").addEventListener("click", fitAll);
  $("#btn-clear").addEventListener("click", () => {
    if (!nodes.length) return;
    if (!confirm("Удалить все ноды графа?")) return;
    load({ nodes: [], edges: [], view: { x: 80, y: 40, zoom: 1 }, nextId: 1 });
    save();
  });
  $("#btn-export").addEventListener("click", () => {
    const data = {
      nodes: nodes.map(n => ({ id: n.id, type: n.type, x: n.x, y: n.y, data: n.data })),
      edges, view,
    };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "designai-graph.json";
    a.click();
    URL.revokeObjectURL(a.href);
  });
  $("#btn-import").addEventListener("click", () => $("#import-file").click());
  $("#import-file").addEventListener("change", (e) => {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    const rd = new FileReader();
    rd.onload = () => {
      try {
        load(JSON.parse(rd.result));
        save();
        toast("Граф загружен", "ok");
      } catch (err) {
        toast("Не удалось прочитать JSON: " + err.message, "error");
      }
    };
    rd.readAsText(f);
    e.target.value = "";
  });

  /* ---------- dev-хук и старт ---------- */

  window.GraphDev = {
    add: (type, x, y) => addNode(type, x == null ? 100 : x, y == null ? 100 : y),
    connect: (fromId, fromPort, toId, toPort) =>
      connect({ node: fromId, port: fromPort }, { node: toId, port: toPort }),
    setIR: (nodeId, ir) => {
      const n = nodeById(nodeId);
      if (!n || n.type !== "edit") return false;
      n.data.ir = clone(ir);
      if (n.refreshEdit) n.refreshEdit();
      propagate(n.id);
      save();
      return true;
    },
    setText: (nodeId, text) => {
      const n = nodeById(nodeId);
      if (!n) return false;
      if (n.type === "prompt") {
        n.data.text = text;
        n.el.querySelector(".f-text").value = text;
        propagate(n.id);
        save();
        return true;
      }
      return false;
    },
    run: (nodeId) => {
      const n = nodeById(nodeId);
      if (n && n.type === "generator") return runGenerator(n);
      if (n && n.type === "mix") return runMix(n);
      if (n && n.type === "reproduce") return runReproduce(n);
    },
    state: () => ({ nodes: nodes.map(n => ({ id: n.id, type: n.type, x: n.x, y: n.y })), edges }),
    node: nodeById,
    fit: fitAll,
  };

  loadFromStorage();
})();
