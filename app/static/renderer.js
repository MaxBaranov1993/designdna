/* DesignAI Web — renderer: Design IR -> DOM. Чистый vanilla JS, без зависимостей. */
(function (global) {
  "use strict";

  const DESIGN_WIDTH = 960;

  const DEFAULT_TOKENS = {
    mode: "light",
    color: { primary: "#5B5BD6", background: "#ffffff", surface: "#f5f5f7", text: "#1a1a1a", textMuted: "#666666", border: "#e0e0e0" },
    font: { display: { family: "Inter", weight: 700 }, body: { family: "Inter", weight: 400 }, scale: "default" },
    radius: { card: "md", button: "md", input: "md" },
    spacing: { section: "md", container: "default" },
    shadow: "sm",
  };

  // дозаполняет пробелы в tokens дефолтами (модель могла вернуть частичный IR)
  function mergeDefaults(tokens) {
    const out = JSON.parse(JSON.stringify(DEFAULT_TOKENS));
    if (!tokens || typeof tokens !== "object") return out;
    for (const k of Object.keys(tokens)) {
      if (tokens[k] && typeof tokens[k] === "object" && !Array.isArray(tokens[k]) && out[k] && typeof out[k] === "object") {
        Object.assign(out[k], tokens[k]);
        if (k === "font") for (const f of ["display", "body"]) if (tokens.font[f]) Object.assign(out.font[f], tokens.font[f]);
        if (k === "color") for (const c of Object.keys(tokens.color)) if (tokens.color[c]) out.color[c] = tokens.color[c];
      } else if (tokens[k] !== undefined) {
        out[k] = tokens[k];
      }
    }
    return out;
  }

  const RADIUS_PX = { none: "0px", sm: "4px", md: "8px", lg: "14px", xl: "22px", full: "999px" };
  const SECTION_PY = { sm: "36px", md: "64px", lg: "96px", xl: "140px" };
  const CONTAINER_W = { narrow: "640px", default: "880px", wide: "1120px", full: "100%" };
  const SHADOWS = {
    none: "none",
    sm: "0 1px 3px rgba(0,0,0,.12)",
    md: "0 6px 20px rgba(0,0,0,.16)",
    lg: "0 18px 50px rgba(0,0,0,.24)",
  };
  const TYPE_SCALE = { compact: 0.9, default: 1, spacious: 1.1 };

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function fontsUrl(tokens) {
    const fams = new Set();
    for (const key of ["display", "body"]) {
      const f = tokens.font && tokens.font[key];
      if (f && f.family) fams.add(f.family.replace(/ /g, "+") + ":wght@" + (f.weight || 400));
    }
    return "https://fonts.googleapis.com/css2?" + [...fams].map(f => "family=" + f).join("&") + "&display=swap";
  }

  function cssVars(tokens) {
    const c = tokens.color, scale = TYPE_SCALE[tokens.font.scale] || 1;
    return `
      --c-primary:${c.primary};--c-secondary:${c.secondary || c.primary};--c-accent:${c.accent || c.primary};
      --c-bg:${c.background};--c-surface:${c.surface};--c-text:${c.text};--c-muted:${c.textMuted};--c-border:${c.border};
      --font-display:'${tokens.font.display.family}',sans-serif;--font-body:'${tokens.font.body.family}',sans-serif;
      --fw-display:${tokens.font.display.weight};--fw-body:${tokens.font.body.weight};
      --fs:${scale};
      --r-card:${RADIUS_PX[tokens.radius.card]};--r-btn:${RADIUS_PX[tokens.radius.button]};--r-input:${RADIUS_PX[tokens.radius.input]};
      --sec-py:${SECTION_PY[tokens.spacing.section]};--container:${CONTAINER_W[tokens.spacing.container]};
      --shadow:${SHADOWS[tokens.shadow]};
    `;
  }

  function baseCss(uid) {
    return `
      .ir-${uid} { background:var(--c-bg); color:var(--c-text); font-family:var(--font-body); font-weight:var(--fw-body);
        font-size:calc(15px * var(--fs)); line-height:1.6; width:${DESIGN_WIDTH}px; transform-origin:top left; }
      .ir-${uid} * { margin:0; padding:0; box-sizing:border-box; }
      .ir-${uid} h1,.ir-${uid} h2,.ir-${uid} h3,.ir-${uid} h4 { font-family:var(--font-display); font-weight:var(--fw-display); line-height:1.15; }
      .ir-${uid} h1 { font-size:calc(46px * var(--fs)); letter-spacing:-.02em; }
      .ir-${uid} h2 { font-size:calc(30px * var(--fs)); letter-spacing:-.01em; }
      .ir-${uid} h3 { font-size:calc(20px * var(--fs)); }
      .ir-${uid} h4 { font-size:calc(16px * var(--fs)); }
      .ir-${uid} .sec, .ir-${uid} .sec-free { padding:var(--sec-py) 32px; position:relative; }
      .ir-${uid} .wrap { max-width:var(--container); margin:0 auto; }
      .ir-${uid} .muted { color:var(--c-muted); }
      .ir-${uid} .btn { display:inline-flex; align-items:center; gap:8px; padding:12px 22px; border-radius:var(--r-btn);
        font-weight:600; font-size:calc(14px * var(--fs)); cursor:pointer; border:1px solid transparent; text-decoration:none; }
      .ir-${uid} .btn-primary { background:var(--c-primary); color:#fff; }
      .ir-${uid} .btn-secondary { background:var(--c-secondary); color:#fff; }
      .ir-${uid} .btn-outline { border-color:var(--c-border); color:var(--c-text); background:transparent; }
      .ir-${uid} .btn-ghost { color:var(--c-primary); background:transparent; padding:8px 12px; }
      .ir-${uid} .card { background:var(--c-surface); border:1px solid var(--c-border); border-radius:var(--r-card);
        padding:24px; box-shadow:var(--shadow); position:relative; }
      .ir-${uid} .badge { display:inline-block; padding:5px 12px; border-radius:var(--r-btn); font-size:calc(12px * var(--fs));
        font-weight:600; background:var(--c-surface); border:1px solid var(--c-border); color:var(--c-muted); }
      .ir-${uid} .badge.tone-primary { background:var(--c-primary); color:#fff; border-color:transparent; }
      .ir-${uid} .badge.tone-accent { background:var(--c-accent); color:#fff; border-color:transparent; }
      .ir-${uid} .input { width:100%; padding:12px 16px; border-radius:var(--r-input); border:1px solid var(--c-border);
        background:var(--c-bg); color:var(--c-text); font-size:calc(14px * var(--fs)); }
      .ir-${uid} .icon-dot { width:34px; height:34px; border-radius:var(--r-btn); background:var(--c-primary);
        color:#fff; display:inline-flex; align-items:center; justify-content:center; font-size:15px; flex:none; }
      .ir-${uid} .img-ph { background:linear-gradient(135deg, var(--c-surface), var(--c-border)); border-radius:var(--r-card);
        display:flex; align-items:center; justify-content:center; color:var(--c-muted); font-size:12px; min-height:180px; padding:16px; text-align:center; }
      .ir-${uid} .sec-head { text-align:center; max-width:640px; margin:0 auto 40px; }
      .ir-${uid} .sec-head h2 { margin-bottom:12px; }
      .ir-${uid} .divider { height:1px; background:var(--c-border); margin:16px 0; }
      .ir-${uid} .avatar { width:44px; height:44px; border-radius:50%; background:var(--c-primary); color:#fff;
        display:inline-flex; align-items:center; justify-content:center; font-weight:700; flex:none; }
      .ir-${uid} .stars { color:var(--c-accent); letter-spacing:2px; }
      .ir-${uid} [data-ir-path].editing { outline:2px dashed var(--c-primary); outline-offset:2px; cursor:text; }
    `;
  }

  /* ---------- геометрия: frame (модель Figma) ---------- */

  const FLEX_JUSTIFY = { start: "flex-start", center: "center", end: "flex-end", "space-between": "space-between", "space-around": "space-around" };
  const FLEX_ALIGN = { start: "flex-start", center: "center", end: "flex-end", stretch: "stretch", baseline: "baseline" };

  /** frame -> CSS. container=true добавляет раскладку детей (auto-layout/free);
   *  parentFree=true — родитель имеет layout:"free", значит x/y работают (absolute). */
  function frameCss(f, parentFree, container) {
    if (!f || typeof f !== "object") return "";
    const s = [];
    if (typeof f.width === "number") s.push(`width:${f.width}px`);
    else if (f.width === "fill") s.push("width:100%", "flex:1 1 auto", "min-width:0");
    else if (f.width === "hug") s.push("width:fit-content");
    if (typeof f.height === "number") s.push(`height:${f.height}px`);
    else if (f.height === "fill") s.push("align-self:stretch", "flex-grow:1");
    else if (f.height === "hug") s.push("height:fit-content");
    if (typeof f.minWidth === "number") s.push(`min-width:${f.minWidth}px`);
    if (typeof f.maxWidth === "number") s.push(`max-width:${f.maxWidth}px`);
    if (typeof f.minHeight === "number") s.push(`min-height:${f.minHeight}px`);
    if (typeof f.maxHeight === "number") s.push(`max-height:${f.maxHeight}px`);
    if (f.clip) s.push("overflow:hidden");
    if (typeof f.rotation === "number" && f.rotation) s.push(`transform:rotate(${f.rotation}deg)`);
    // absolute — элемент выведен из раскладки родителя (аналог layoutPosition:absolute в pen.dev)
    const placed = (parentFree || f.absolute) && (typeof f.x === "number" || typeof f.y === "number");
    if (placed) {
      s.push("position:absolute", `left:${typeof f.x === "number" ? f.x : 0}px`, `top:${typeof f.y === "number" ? f.y : 0}px`);
    }
    if (typeof f.padding === "number") s.push(`padding:${f.padding}px`);
    else if (Array.isArray(f.padding) && f.padding.length === 4) s.push(`padding:${f.padding.map(n => n + "px").join(" ")}`);
    else if (Array.isArray(f.padding) && f.padding.length === 2) s.push(`padding:${f.padding[0]}px ${f.padding[1]}px`);
    if (container) {
      // relative нужен и free, и auto: якорь для детей с absolute.
      // placed-узлу НЕ добавляем: position:relative в inline-стиле перезаписал бы
      // position:absolute (конфликт), а absolute-узел сам содержит absolute-детей
      if ((f.layout === "free" || f.layout === "auto") && !placed) s.push("position:relative");
      if (f.layout === "auto") {
        s.push("display:flex", `flex-direction:${f.direction === "row" ? "row" : "column"}`);
        if (typeof f.gap === "number") s.push(`gap:${f.gap}px`);
        if (f.wrap) s.push("flex-wrap:wrap");
        if (f.justify && FLEX_JUSTIFY[f.justify]) s.push(`justify-content:${FLEX_JUSTIFY[f.justify]}`);
        if (f.align && FLEX_ALIGN[f.align]) s.push(`align-items:${FLEX_ALIGN[f.align]}`);
      }
    }
    return s.join(";");
  }

  /** Оборачивает html в div-бокс по frame (для секций и листовых элементов).
 *  data-ir-path переносится на обёртку чтобы GeoEdit работал с frame-контейнером.
 *  cls — опциональный класс обёртки (например sec-free для дефолтного padding). */
  function withFrame(html, frame, parentFree, container, irPath, cls) {
    const css = frameCss(frame, parentFree, container);
    if (!css && !cls) return html;
    const pathAttr = irPath ? ` data-ir-path="${esc(irPath)}"` : "";
    const clsAttr = cls ? ` class="${cls}"` : "";
    return `<div data-ir-frame${pathAttr}${clsAttr} style="${css}">${html}</div>`;
  }

  /* ---------- элементы (children) ---------- */

  function renderElement(el, uid, parentFree) {
    const irPath = el.__path || null;
    const html = renderElementInner(el, uid, parentFree);
    if (el.type === "card") return html; // card ставит data-ir-path сам
    const wrapped = withFrame(html, el.frame, parentFree, false, irPath);
    // если frame пустой и withFrame не обернул — добавляем span-обёртку с path
    if (wrapped === html && irPath) {
      return `<span data-ir-path="${esc(irPath)}" style="display:inline-block">${html}</span>`;
    }
    return wrapped;
  }

  function renderElementInner(el, uid, parentFree) {
    // data-ir-path НЕ ставится здесь — он добавляется на withFrame-обёртку в renderElement
    // или на card-корень. Исключение: props-элементы секций ставят path сами.
    switch (el.type) {
      case "heading": {
        const lvl = Math.min(4, Math.max(1, el.level || 2));
        const align = el.align ? ` style="text-align:${el.align}"` : "";
        return `<h${lvl}${align}>${esc(el.text || el.title || "")}</h${lvl}>`;
      }
      case "text": {
        const align = el.align ? ` style="text-align:${el.align}"` : "";
        const cls = el.size === "sm" || el.size === "xs" ? ' class="muted"' : "";
        return `<p${cls}${align}>${esc(el.text || "")}</p>`;
      }
      case "button":
        return `<a class="btn btn-${el.variant || "primary"}"><span>${esc(el.text || "")}</span></a>`;
      case "badge":
        return `<span class="badge${el.tone && el.tone !== "default" ? " tone-" + el.tone : ""}">${esc(el.text || el.label || "")}</span>`;
      case "icon":
        return `<span class="icon-dot">${esc((el.icon || "✦").slice(0, 2))}</span>`;
      case "image":
        if (el.src) {
          return `<img src="${esc(el.src)}" alt="${esc(el.alt || "")}" style="display:block;width:100%;height:100%;object-fit:contain" loading="lazy">`;
        }
        return `<div class="img-ph">${esc(el.alt || el.imagePrompt || "изображение")}</div>`;
      case "divider":
        return `<div class="divider"></div>`;
      case "rect": {
        const bg = /^#[0-9a-fA-F]{3,8}$/.test(el.fill || "") ? el.fill : "#8B5CF6";
        const rad = typeof el.radius === "number" ? el.radius : 8;
        return `<div style="background:${bg};border-radius:${rad}px;min-height:16px;width:100%;height:100%"></div>`;
      }
      case "avatar":
        return `<span style="display:inline-flex;align-items:center;gap:12px"><span class="avatar">${esc(initials(el.name))}</span>
          <span><strong>${esc(el.name || "")}</strong><br><span class="muted" style="font-size:13px">${esc(el.role || "")}</span></span></span>`;
      case "rating": {
        const v = Math.round(Number(el.value) || 5);
        return `<span class="stars">${"★".repeat(v)}${"☆".repeat(5 - v)}</span>`;
      }
      case "stat":
        return `<div style="text-align:center"><div style="font-family:var(--font-display);font-weight:var(--fw-display);font-size:calc(34px * var(--fs));color:var(--c-primary)">${esc(el.value)}</div>
          <div class="muted">${esc(el.label || "")}</div></div>`;
      case "list":
        return `<ul style="list-style:none;display:flex;flex-direction:column;gap:8px">${(el.items || []).map(i =>
          `<li style="display:flex;gap:8px;align-items:flex-start"><span style="color:var(--c-primary)">✓</span><span>${esc(i)}</span></li>`).join("")}</ul>`;
      case "input":
        return `<input class="input" placeholder="${esc(el.placeholder || el.label || "")}">`;
      case "card": {
        const free = el.frame && el.frame.layout === "free";
        const inner = (el.children || []).map(c => renderElement(c, uid, free)).join("");
        const fcss = frameCss(el.frame, parentFree, true);
        const cardPath = el.__path ? ` data-ir-path="${esc(el.__path)}"` : "";
        return `<div class="card"${cardPath}${fcss ? ` style="${fcss}"` : ""}>
          ${el.icon ? `<span class="icon-dot" style="margin-bottom:12px">${esc(el.icon.slice(0, 2))}</span>` : ""}
          ${el.title ? `<h3 style="margin-bottom:8px">${esc(el.title)}</h3>` : ""}
          ${el.text ? `<p class="muted">${esc(el.text)}</p>` : ""}
          ${inner}</div>`;
      }
      default:
        return `<div class="card">${esc(el.text || el.title || el.type)}</div>`;
    }
  }

  function initials(name) {
    return (name || "?").split(/\s+/).map(w => w[0]).join("").slice(0, 2).toUpperCase();
  }

  function renderChildren(children, uid, cols, parentFrame) {
    if (!children || !children.length) return "";
    const free = parentFrame && parentFrame.layout === "free";
    const hasAbs = children.some(c => c.frame && c.frame.absolute);
    // во free-контейнере дети позиционируются по своим x/y — grid-сетка не нужна;
    // position:relative — якорь для absolute-детей и free-позиционирования
    const style = (free || hasAbs) ? ' style="position:relative"'
      : cols ? ` style="display:grid;grid-template-columns:repeat(${cols},1fr);gap:20px"` : "";
    return `<div${style}>${children.map(c => renderElement(c, uid, free)).join("")}</div>`;
  }

  /* ---------- секции ---------- */

  function btnHtml(btn, defVariant, path) {
    if (!btn) return "";
    const p = path ? ` data-ir-path="${esc(path)}"` : "";
    return `<a class="btn btn-${btn.variant || defVariant}"><span${p}>${esc(btn.text || "")}</span></a>`;
  }

  function renderSection(sec, uid, parentFree) {
    const isFree = !!(sec.frame && sec.frame.layout === "free");
    const hasChildren = sec.children && sec.children.length > 0;
    // free-layout с children: рендерим ТОЛЬКО children (reproduction-режим),
    // inner HTML секции пропускаем чтобы не перекрывать извлечённые изображения
    const html = (isFree && hasChildren) ? "" : renderSectionInner(sec, uid);
    let childrenHtml = "";
    if (isFree && hasChildren) {
      childrenHtml = sec.children.map(c => renderElement(c, uid, true)).join("");
    }
    const combined = html + childrenHtml;
    // free-секция рендерится без .sec-внутренностей — класс sec-free сохраняет
    // дефолтный padding секции, иначе при конверсии в free дети «уплывают»
    return withFrame(combined, sec.frame, parentFree, isFree, null,
      (isFree && hasChildren) ? "sec-free" : "");
  }

  function renderSectionInner(sec, uid) {
    const t = sec.type, v = sec.variant || "", p = sec.props || {};
    const base = `sec-${sec.id || "x"}`;

    if (t === "navbar") {
      const links = (p.links || []).map((l, i) =>
        `<a style="color:var(--c-muted);text-decoration:none;font-size:calc(14px * var(--fs));font-weight:500" href="#" onclick="return false">
          <span data-ir-path="props.links.${i}.label">${esc(l.label)}</span></a>`).join("");
      const logo = `<a style="font-family:var(--font-display);font-weight:var(--fw-display);font-size:calc(19px * var(--fs));color:var(--c-text);text-decoration:none" href="#" onclick="return false">
          <span data-ir-path="props.logoText">${esc(p.logoText || "")}</span></a>`;
      const cta = v === "minimal" ? "" : btnHtml(p.cta, "primary", "props.cta.text");
      let inner;
      if (v === "centered") {
        inner = `<div style="display:flex;align-items:center;justify-content:space-between;gap:24px">
          <div style="display:flex;gap:24px;align-items:center;flex:1">${(p.links || []).slice(0, 3).map((l, i) => `<a style="color:var(--c-muted);text-decoration:none;font-size:calc(14px*var(--fs))" href="#" onclick="return false"><span data-ir-path="props.links.${i}.label">${esc(l.label)}</span></a>`).join("")}</div>
          ${logo}
          <div style="display:flex;gap:24px;align-items:center;flex:1;justify-content:flex-end">${(p.links || []).slice(3).map((l, i) => `<a style="color:var(--c-muted);text-decoration:none;font-size:calc(14px*var(--fs))" href="#" onclick="return false"><span data-ir-path="props.links.${i + 3}.label">${esc(l.label)}</span></a>`).join("")}${cta}</div></div>`;
      } else {
        inner = `<div style="display:flex;align-items:center;gap:32px">
          ${logo}
          <div style="display:flex;gap:24px;align-items:center;flex:1${v === "minimal" ? ";justify-content:flex-end" : ""}">${links}</div>
          ${cta}</div>`;
      }
      return `<nav class="sec ${base}" style="padding-top:16px;padding-bottom:16px;${p.sticky ? "position:sticky;top:0;z-index:10;" : ""}${p.transparent ? "" : "background:var(--c-bg);border-bottom:1px solid var(--c-border);"}">
        <div class="wrap" style="max-width:1120px">${inner}</div></nav>`;
    }

    if (t === "hero") {
      const badge = p.badge ? `<span class="badge tone-primary" style="margin-bottom:16px"><span data-ir-path="props.badge">${esc(p.badge)}</span></span>` : "";
      const head = `<h1 data-ir-path="props.heading" style="margin-bottom:16px">${esc(p.heading || "")}</h1>`;
      const sub = p.subheading ? `<p class="muted" data-ir-path="props.subheading" style="font-size:calc(17px*var(--fs));margin-bottom:28px;max-width:560px">${esc(p.subheading)}</p>` : "";
      const btns = `<div style="display:flex;gap:12px;flex-wrap:wrap">${btnHtml(p.ctaPrimary, "primary", "props.ctaPrimary.text")}${btnHtml(p.ctaSecondary, "outline", "props.ctaSecondary.text")}</div>`;
      if (v === "split" || v === "split-reverse") {
        const media = p.media ? `<div class="img-ph" style="min-height:320px">${esc(p.media.alt || p.media.imagePrompt || "")}</div>` : `<div class="img-ph" style="min-height:320px">медиа</div>`;
        const txt = `<div style="display:flex;flex-direction:column;justify-content:center">${badge}${head}${sub}${btns}</div>`;
        return `<section class="sec ${base}"><div class="wrap" style="display:grid;grid-template-columns:1fr 1fr;gap:48px;align-items:center">
          ${v === "split" ? txt + media : media + txt}</div></section>`;
      }
      if (v === "media-bg" || v === "gradient") {
        const bg = v === "gradient"
          ? "background:linear-gradient(135deg,var(--c-primary) 0%,var(--c-bg) 90%);"
          : "background:linear-gradient(rgba(0,0,0,.45),rgba(0,0,0,.45)),linear-gradient(135deg,var(--c-surface),var(--c-border));";
        return `<section class="sec ${base}" style="${bg}text-align:center"><div class="wrap" style="display:flex;flex-direction:column;align-items:center">
          ${badge}${head}${sub.replace("max-width:560px", "max-width:640px;margin-left:auto;margin-right:auto")}<div style="display:flex;gap:12px">${btnHtml(p.ctaPrimary, "primary", "props.ctaPrimary.text")}${btnHtml(p.ctaSecondary, "outline", "props.ctaSecondary.text")}</div></div></section>`;
      }
      const align = p.align === "left" ? "left" : "center";
      return `<section class="sec ${base}" style="text-align:${align}"><div class="wrap" style="display:flex;flex-direction:column;${align === "center" ? "align-items:center" : ""}">
        ${badge}${head}${sub}${btns}</div></section>`;
    }

    if (t === "logo-cloud") {
      const logos = (sec.children && sec.children.length ? sec.children : [{ type: "text", text: "Партнёр" }, { type: "text", text: "Бренд" }, { type: "text", text: "Компания" }, { type: "text", text: "Сервис" }])
        .map(c => `<span class="muted" style="font-family:var(--font-display);font-weight:700;font-size:calc(18px*var(--fs));opacity:.7">${esc(c.text || c.title || c.alt || "logo")}</span>`).join("");
      const marquee = v === "marquee" ? ";overflow:hidden;white-space:nowrap" : "";
      return `<section class="sec ${base}" style="padding-top:32px;padding-bottom:32px${marquee}"><div class="wrap" style="text-align:center">
        ${p.heading ? `<p class="muted" data-ir-path="props.heading" style="margin-bottom:20px;font-size:calc(13px*var(--fs));text-transform:uppercase;letter-spacing:.08em">${esc(p.heading)}</p>` : ""}
        <div style="display:flex;gap:48px;justify-content:center;align-items:center;flex-wrap:wrap">${logos}</div></div></section>`;
    }

    if (t === "feature-grid") {
      const cols = v === "grid-2" ? 2 : v === "grid-4" ? 4 : 3;
      return `<section class="sec ${base}"><div class="wrap">
        ${secHead(p)}
        ${renderChildren(sec.children, uid, v === "bento" ? 3 : cols, sec.frame)}
        </div></section>`;
    }

    if (t === "feature-alternating") {
      const rows = (sec.children || []).map((c, i) => {
        const media = `<div class="img-ph" style="min-height:240px">${esc(c.alt || c.imagePrompt || "изображение")}</div>`;
        const txt = `<div style="display:flex;flex-direction:column;justify-content:center;gap:12px">
          ${c.title || c.text ? `<h3>${esc(c.title || "")}</h3><p class="muted">${esc(c.text || "")}</p>` : renderElement(c, uid)}
          ${(c.children || []).map(ch => renderElement(ch, uid)).join("")}</div>`;
        return `<div style="display:grid;grid-template-columns:1fr 1fr;gap:48px;align-items:center;margin-bottom:48px">${i % 2 ? txt + media : media + txt}</div>`;
      }).join("");
      return `<section class="sec ${base}"><div class="wrap">${secHead(p)}${rows}</div></section>`;
    }

    if (t === "stats") {
      const items = (p.items || []).map((it, i) =>
        `<div style="text-align:center"><div data-ir-path="props.items.${i}.value" style="font-family:var(--font-display);font-weight:var(--fw-display);font-size:calc(38px*var(--fs));color:var(--c-primary)">${esc(it.value)}</div>
        <div class="muted" data-ir-path="props.items.${i}.label">${esc(it.label)}</div></div>`).join("");
      return `<section class="sec ${base}"><div class="wrap">
        ${p.heading ? `<h2 data-ir-path="props.heading" style="text-align:center;margin-bottom:40px">${esc(p.heading)}</h2>` : ""}
        <div style="display:grid;grid-template-columns:repeat(${Math.min(4, (p.items || []).length || 3)},1fr);gap:24px">${items}</div></div></section>`;
    }

    if (t === "steps") {
      return `<section class="sec ${base}"><div class="wrap">${secHead(p)}
        <div style="display:grid;grid-template-columns:repeat(${Math.min(4, (sec.children || []).length || 3)},1fr);gap:20px">
        ${(sec.children || []).map((c, i) => `<div class="card"><div class="icon-dot" style="margin-bottom:12px">${i + 1}</div>
          <h3 style="margin-bottom:8px">${esc(c.title || c.text || "Шаг " + (i + 1))}</h3><p class="muted">${esc(c.text || "")}</p></div>`).join("")}</div></div></section>`;
    }

    if (t === "gallery") {
      return `<section class="sec ${base}"><div class="wrap">${secHead(p)}
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px">
        ${(sec.children || []).map((c, i) => `<div class="img-ph" style="min-height:${v === "masonry" ? 140 + ((i * 67) % 120) : 200}px">${esc(c.alt || c.imagePrompt || "фото")}</div>`).join("")}</div></div></section>`;
    }

    if (t === "testimonials") {
      const cols = v === "grid-2" ? 2 : v === "single-featured" ? 1 : 3;
      return `<section class="sec ${base}"><div class="wrap">${secHead(p)}
        <div style="display:grid;grid-template-columns:repeat(${cols},1fr);gap:20px">
        ${(sec.children || []).map(c => `<div class="card">
          ${c.children && c.children.some(x => x.type === "rating") ? "" : '<span class="stars">★★★★★</span>'}
          <p style="margin:12px 0 16px">${esc(c.text || "")}</p>
          <span style="display:flex;align-items:center;gap:12px"><span class="avatar">${esc(initials(c.name || c.title))}</span>
          <span><strong>${esc(c.name || c.title || "")}</strong><br><span class="muted" style="font-size:13px">${esc(c.role || "")}</span></span></span></div>`).join("")}</div></div></section>`;
    }

    if (t === "pricing") {
      return `<section class="sec ${base}"><div class="wrap">${secHead(p)}
        <div style="display:grid;grid-template-columns:repeat(${(p.tiers || []).length || 3},1fr);gap:20px;align-items:stretch">
        ${(p.tiers || []).map((tier, i) => `<div class="card" style="display:flex;flex-direction:column;${tier.highlighted ? "border-color:var(--c-primary);box-shadow:var(--shadow);position:relative" : ""}">
          ${tier.highlighted ? '<span class="badge tone-primary" style="position:absolute;top:-12px;left:50%;transform:translateX(-50%)">Популярный</span>' : ""}
          <h3 data-ir-path="props.tiers.${i}.name">${esc(tier.name)}</h3>
          <div style="margin:12px 0"><span data-ir-path="props.tiers.${i}.price" style="font-family:var(--font-display);font-weight:var(--fw-display);font-size:calc(34px*var(--fs))">${esc(tier.price)}</span>
          ${tier.period ? `<span class="muted" data-ir-path="props.tiers.${i}.period"> ${esc(tier.period)}</span>` : ""}</div>
          <ul style="list-style:none;display:flex;flex-direction:column;gap:8px;flex:1;margin-bottom:20px">
          ${(tier.features || []).map((f, j) => `<li style="display:flex;gap:8px"><span style="color:var(--c-primary)">✓</span><span data-ir-path="props.tiers.${i}.features.${j}" class="muted">${esc(f)}</span></li>`).join("")}</ul>
          <a class="btn ${tier.highlighted ? "btn-primary" : "btn-outline"}" style="justify-content:center"><span data-ir-path="props.tiers.${i}.cta">${esc(tier.cta)}</span></a></div>`).join("")}</div></div></section>`;
    }

    if (t === "faq") {
      const twoCol = v === "two-column";
      return `<section class="sec ${base}"><div class="wrap" style="${twoCol ? "" : "max-width:720px"}">
        ${secHead(p)}
        <div style="display:${twoCol ? "grid;grid-template-columns:1fr 1fr;gap:16px" : "flex;flex-direction:column;gap:12px"}">
        ${(p.items || []).map((it, i) => `<div class="card" style="padding:18px 22px">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:12px">
          <strong data-ir-path="props.items.${i}.question">${esc(it.question)}</strong><span style="color:var(--c-muted)">+</span></div>
          <p class="muted" data-ir-path="props.items.${i}.answer" style="margin-top:10px;font-size:calc(14px*var(--fs))">${esc(it.answer)}</p></div>`).join("")}</div></div></section>`;
    }

    if (t === "cta") {
      const bold = v === "banner-bold";
      const inner = `${p.heading ? `<h2 data-ir-path="props.heading" style="margin-bottom:12px">${esc(p.heading)}</h2>` : ""}
        ${p.subheading ? `<p class="muted" data-ir-path="props.subheading" style="margin-bottom:24px;max-width:520px;${v === "split" ? "" : "margin-left:auto;margin-right:auto"}">${esc(p.subheading)}</p>` : ""}
        <div style="display:flex;gap:12px;flex-wrap:wrap;${v === "split" ? "" : "justify-content:center"}">${btnHtml(p.ctaPrimary, "primary", "props.ctaPrimary.text")}${btnHtml(p.ctaSecondary, "outline", "props.ctaSecondary.text")}</div>`;
      if (v === "split") return `<section class="sec ${base}"><div class="wrap" style="display:grid;grid-template-columns:1fr 1fr;gap:32px;align-items:center">${inner}</div></section>`;
      return `<section class="sec ${base}" style="${bold ? "background:var(--c-primary);" : "background:var(--c-surface);"}text-align:center"><div class="wrap">${inner}</div></section>`;
    }

    if (t === "newsletter") {
      const form = `<div style="display:flex;gap:10px;${v === "minimal" ? "" : "justify-content:center;"}max-width:440px;margin:0 auto">
        <input class="input" placeholder="${esc(p.placeholder || "Email")}" data-ir-path="props.placeholder" style="flex:1">
        <a class="btn btn-primary"><span data-ir-path="props.submitText">${esc(p.submitText || "Подписаться")}</span></a></div>`;
      return `<section class="sec ${base}" style="${v === "boxed" ? "" : ""}"><div class="wrap" style="${v === "boxed" ? "background:var(--c-surface);border:1px solid var(--c-border);border-radius:var(--r-card);padding:48px;box-shadow:var(--shadow);" : ""}text-align:center">
        <h2 data-ir-path="props.heading" style="margin-bottom:10px">${esc(p.heading || "")}</h2>
        ${p.subheading ? `<p class="muted" data-ir-path="props.subheading" style="margin-bottom:24px">${esc(p.subheading)}</p>` : '<div style="margin-bottom:24px"></div>'}
        ${form}</div></section>`;
    }

    if (t === "contact-form") {
      const form = `<div class="card" style="display:flex;flex-direction:column;gap:14px">
        ${(p.fields || []).map((f, i) => `<label style="display:flex;flex-direction:column;gap:6px;font-size:calc(13px*var(--fs));font-weight:600">
          <span data-ir-path="props.fields.${i}.label">${esc(f.label)}${f.required ? " *" : ""}</span>
          ${f.inputType === "textarea" ? `<textarea class="input" rows="3" placeholder="${esc(f.placeholder || "")}"></textarea>`
            : f.inputType === "checkbox" ? `<span style="display:flex;gap:8px;align-items:center;font-weight:400"><input type="checkbox"> <span data-ir-path="props.fields.${i}.placeholder">${esc(f.placeholder || "")}</span></span>`
            : `<input class="input" placeholder="${esc(f.placeholder || "")}">`}</label>`).join("")}
        <a class="btn btn-primary" style="justify-content:center"><span data-ir-path="props.submitText">${esc(p.submitText || "Отправить")}</span></a></div>`;
      const info = `<div style="display:flex;flex-direction:column;justify-content:center;gap:12px">
        <h2 data-ir-path="props.heading">${esc(p.heading || "")}</h2>
        ${p.subheading ? `<p class="muted" data-ir-path="props.subheading">${esc(p.subheading)}</p>` : ""}</div>`;
      if (v === "split-info" || v === "map") {
        return `<section class="sec ${base}"><div class="wrap" style="display:grid;grid-template-columns:1fr 1fr;gap:48px;align-items:start">${info}${form}</div></section>`;
      }
      return `<section class="sec ${base}"><div class="wrap" style="max-width:560px">
        <h2 data-ir-path="props.heading" style="text-align:center;margin-bottom:10px">${esc(p.heading || "")}</h2>
        ${p.subheading ? `<p class="muted" data-ir-path="props.subheading" style="text-align:center;margin-bottom:24px">${esc(p.subheading)}</p>` : ""}
        ${form}</div></section>`;
    }

    if (t === "footer") {
      const cols = (p.columns || []).map(col => `<div>
        <h4 style="margin-bottom:14px">${esc(col.title)}</h4>
        <div style="display:flex;flex-direction:column;gap:10px">${(col.links || []).map(l =>
          `<a href="#" onclick="return false" style="color:var(--c-muted);text-decoration:none;font-size:calc(14px*var(--fs))">${esc(l.label)}</a>`).join("")}</div></div>`).join("");
      if (v === "simple") {
        return `<footer class="sec ${base}" style="padding-top:28px;padding-bottom:28px;border-top:1px solid var(--c-border)"><div class="wrap" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:16px">
          <strong style="font-family:var(--font-display)"><span data-ir-path="props.logoText">${esc(p.logoText || "")}</span></strong>
          <span class="muted" style="font-size:calc(13px*var(--fs))" data-ir-path="props.copyright">${esc(p.copyright || "")}</span></div></footer>`;
      }
      return `<footer class="sec ${base}" style="border-top:1px solid var(--c-border)"><div class="wrap">
        <div style="display:grid;grid-template-columns:1.4fr repeat(${Math.max(1, (p.columns || []).length)},1fr);gap:32px;margin-bottom:40px">
          <div><strong style="font-family:var(--font-display);font-size:calc(19px*var(--fs))"><span data-ir-path="props.logoText">${esc(p.logoText || "")}</span></strong>
          ${p.tagline ? `<p class="muted" data-ir-path="props.tagline" style="margin-top:12px;font-size:calc(14px*var(--fs));max-width:260px">${esc(p.tagline)}</p>` : ""}</div>
          ${cols}</div>
        <div class="divider"></div>
        <p class="muted" data-ir-path="props.copyright" style="font-size:calc(13px*var(--fs));text-align:center">${esc(p.copyright || "")}</p></div></footer>`;
    }

    /* fallback: comparison, team, blog-grid, banner и любые новые типы */
    if (t === "banner") {
      return `<section class="sec ${base}" style="padding-top:14px;padding-bottom:14px;background:var(--c-surface)"><div class="wrap" style="display:flex;gap:16px;align-items:center;justify-content:center;flex-wrap:wrap">
        <span data-ir-path="props.text">${esc(p.text || "")}</span>${btnHtml(p.cta, "outline", "props.cta.text")}</div></section>`;
    }
    return `<section class="sec ${base}"><div class="wrap">${secHead(p)}
      ${renderChildren(sec.children, uid, Math.min(3, (sec.children || []).length || 0), sec.frame) ||
      `<div class="card muted">Секция «${esc(t)}» (${esc(v)}): нет children для предпросмотра</div>`}</div></section>`;
  }

  function secHead(p) {
    if (!p.heading && !p.subheading) return "";
    return `<div class="sec-head">${p.heading ? `<h2 data-ir-path="props.heading">${esc(p.heading)}</h2>` : ""}
      ${p.subheading ? `<p class="muted" data-ir-path="props.subheading">${esc(p.subheading)}</p>` : ""}</div>`;
  }

  /* ---------- публичное API ---------- */

  let uidCounter = 0;

  /** Рендерит IR в container (внутри .preview-clip). Масштабирует под ширину контейнера. */
  function renderIR(container, ir) {
    const uid = ++uidCounter;
    const tokens = (ir.tokens = mergeDefaults(ir.tokens));
    const tree = ir.tree || [];

    let styleEl = document.getElementById("ir-fonts");
    if (!styleEl) {
      styleEl = document.createElement("link");
      styleEl.id = "ir-fonts";
      styleEl.rel = "stylesheet";
      document.head.appendChild(styleEl);
    }
    if (tokens.font) styleEl.href = fontsUrl(tokens);

    // артборд: корневой frame задаёт ширину холста и (опционально) free-позиционирование секций
    const rootFrame = ir.frame && typeof ir.frame === "object" ? ir.frame : null;
    const rootFree = !!(rootFrame && rootFrame.layout === "free");
    const artW = rootFrame && typeof rootFrame.width === "number" ? rootFrame.width : DESIGN_WIDTH;
    const artStyle = [`width:${artW}px`];
    if (rootFrame) {
      if (typeof rootFrame.height === "number") artStyle.push(`height:${rootFrame.height}px`);
      if (typeof rootFrame.padding === "number") artStyle.push(`padding:${rootFrame.padding}px`);
      else if (Array.isArray(rootFrame.padding) && rootFrame.padding.length === 4) artStyle.push(`padding:${rootFrame.padding.map(n => n + "px").join(" ")}`);
      if (rootFree) artStyle.push("position:relative");
    }

    const css = `.ir-${uid}{${cssVars(tokens)}}` + baseCss(uid);
    const body = tree.map((sec, i) => {
      annotatePaths(sec);
      // помечаем корневой тег секции её индексом — нужно редактору для точной записи в IR
      return renderSection(sec, uid, rootFree).replace(/^<(\w+)/, `<$1 data-ir-sec="${i}"`);
    }).join("");

    container.innerHTML = `<style>${css}</style><div class="ir-${uid}" data-design-width="${artW}" style="${artStyle.join(";")}">${body}</div>`;
    const inner = container.firstElementChild ? container.querySelector(".ir-" + uid) : null;
    applyFrameOverrides(container, tree);
    requestAnimationFrame(() => fitPreview(container, inner));
  }

  /** Применяет sec._frames (frame-оверрайды props-элементов) как inline-стили.
   *  Раньше это делал только полноэкранный редактор — теперь и нода Edit, и превью. */
  function applyFrameOverrides(container, tree) {
    (tree || []).forEach((sec, si) => {
      if (!sec._frames || !Object.keys(sec._frames).length) return;
      const secEl = container.querySelector(`[data-ir-sec="${si}"]`);
      if (!secEl) return;
      for (const [path, frame] of Object.entries(sec._frames)) {
        const el = secEl.querySelector(`[data-ir-path^="${path}"]`);
        if (!el) continue;
        const css = frameCss(frame, true, false);
        if (css) el.style.cssText = (el.style.cssText || "") + ";" + css;
      }
    });
  }

  function fitPreview(container, inner) {
    if (!inner) inner = container.querySelector('[class^="ir-"]');
    if (!inner) return;
    const designW = Number(inner.dataset && inner.dataset.designWidth) || DESIGN_WIDTH;
    const w = container.clientWidth || 300;
    const scale = Math.min(1, w / designW);
    inner.style.transform = `scale(${scale})`;
    container.style.height = (inner.offsetHeight * scale) + "px";
  }

  /** Проставляет __path элементам children для редактирования. */
  function annotatePaths(sec, prefix) {
    prefix = prefix || "";
    (sec.children || []).forEach((el, i) => {
      el.__path = `${prefix}children.${i}`;
      annotatePathsEl(el, el.__path);
    });
  }
  function annotatePathsEl(el, path) {
    (el.children || []).forEach((c, i) => {
      c.__path = `${path}.children.${i}`;
      annotatePathsEl(c, c.__path);
    });
  }

  global.IRRenderer = { renderIR, fitPreview, DESIGN_WIDTH };
})(window);
