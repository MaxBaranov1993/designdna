// @ts-nocheck
/* DesignAI Web — renderer: Design IR -> DOM. TS-модуль ядра (без window-глобалов). */
import { DesignAIFontCatalog } from "./fontCatalog";
import { isLockedNode } from "./locked";

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

  /* ---------- санация значений из IR (контент от LLM — недоверенный) ---------- */

  /** Цвет — #rgb/#rrggbb/#rrggbbaa, rgba(...), hsla(...); иначе null. */
  function safeColor(v) {
    const s = String(v == null ? "" : v).trim();
    if (/^#[0-9a-fA-F]{3,8}$/.test(s)) return s;
    if (/^rgba?\(\s*[\d.]+\s*,\s*[\d.]+%?\s*,\s*[\d.]+%?\s*(?:,\s*[\d.]+\s*)?\)$/.test(s)) return s;
    if (/^hsla?\(\s*[\d.]+\s*,\s*[\d.]+%\s*,\s*[\d.]+%\s*(?:,\s*[\d.]+\s*)?\)$/.test(s)) return s;
    return null;
  }

  /** Полный font-stack из недоверенной строки: имена в кавычках, generic —
   *  без. Запятые и fallback сохраняются: раньше всё вне букв/цифр/дефисов
   *  вырезалось, и стек "Space Grotesk", sans-serif превращался в
   *  несуществующее семейство 'Space Grotesk sans-serif' — текст рендерился
   *  неправильным шрифтом на любом реальном сайте. */
  function safeFontStack(v) {
    const GENERIC = new Set(["serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui",
      "ui-serif", "ui-sans-serif", "ui-monospace", "ui-rounded", "math", "emoji", "fangsong"]);
    const parts = String(v == null ? "" : v).split(",")
      .map((p) => p.replace(/["']/g, "").trim())
      .filter(Boolean);
    const out = [];
    for (const p of parts.slice(0, 8)) {
      if (!p || p.length > 60 || !/^[\p{L}\p{N}\s._-]+$/u.test(p)) continue;
      out.push(GENERIC.has(p) ? p : `'${p}'`);
    }
    if (!out.length) return "";
    // Без явного generic-фолбэка недостающий веб-шрифт откатывался к дефолту
    // документа — а он serif. Сайт на гротеске превращался в антикву.
    if (!out.some((name) => GENERIC.has(name.replace(/'/g, "")))) out.push("sans-serif");
    return out.join(",");
  }

  /** Первый family стека — для каталога шрифтов и URL Google Fonts. */
  function safeFontFamily(v) {
    return safeFontStack(v).split(",")[0].replace(/'/g, "") || "Inter";
  }

  /** text-align — whitelist, иначе null (инъекции в style-атрибут через el.align). */
  function safeAlign(v) {
    return ["left", "center", "right", "justify", "start", "end"].includes(v) ? v : null;
  }

  /** Локальные стили импортированного DOM-слоя. Набор сознательно мал и
   * санитизируется: BlockParse должен переносить измеренный вид, не открывая
   * путь для CSS-инъекций из внешней страницы. */
  function visualCss(style) {
    if (!style || typeof style !== "object") return "";
    const s = [];
    const color = safeColor(style.color); if (color) s.push(`color:${color}`);
    const bg = safeColor(style.background); if (bg) s.push(`background:${bg}`);
    const border = safeColor(style.borderColor); if (border) s.push(`border-color:${border}`);
    const bw = Number(style.borderWidth); if (Number.isFinite(bw) && bw >= 0 && bw <= 64) s.push(`border-style:solid`, `border-width:${bw}px`);
    const family = style.fontFamily ? safeFontStack(style.fontFamily) : ""; if (family) s.push(`font-family:${family}`);
    const fs = Number(style.fontSize); if (Number.isFinite(fs) && fs >= 1 && fs <= 512) s.push(`font-size:${fs}px`);
    const fw = Number(style.fontWeight); if (Number.isFinite(fw) && fw >= 100 && fw <= 900) s.push(`font-weight:${fw}`);
    const lh = Number(style.lineHeight); if (Number.isFinite(lh) && lh >= .5 && lh <= 10) s.push(`line-height:${lh}`);
    const ls = Number(style.letterSpacing); if (Number.isFinite(ls) && ls >= -20 && ls <= 100) s.push(`letter-spacing:${ls}px`);
    // per-side borders (когда стороны различаются — напр. border-bottom у шапки)
    if (Array.isArray(style.borderSides) && style.borderSides.length === 4) {
      const sides = ["top", "right", "bottom", "left"];
      style.borderSides.forEach((side, i) => {
        const w = Number(side && side.width);
        if (!Number.isFinite(w) || w <= 0) return;
        const c = safeColor(side && side.color) || "#e0e0e0";
        s.push(`border-${sides[i]}:${Math.min(64, w)}px solid ${c}`);
      });
    }
    if (style.fontStyle === "italic" || style.fontStyle === "oblique") s.push(`font-style:${style.fontStyle}`);
    if (style.fontVariantNumeric === "tabular-nums") s.push(`font-variant-numeric:tabular-nums`);
    if (["left", "center", "right", "justify", "start", "end"].includes(style.textAlign)) s.push(`text-align:${style.textAlign}`);
    const radius = Number(style.borderRadius); if (Number.isFinite(radius) && radius >= 0 && radius <= 1000) s.push(`border-radius:${radius}px`);
    if (typeof style.boxShadow === "string" && style.boxShadow.length <= 300 && !/[;{}<>"'\\\r\n]/.test(style.boxShadow)) s.push(`box-shadow:${style.boxShadow}`);
    if (["none", "underline", "line-through", "overline"].includes(style.textDecoration)) s.push(`text-decoration:${style.textDecoration}`);
    if (["normal", "nowrap", "pre", "pre-wrap", "pre-line", "break-spaces"].includes(style.whiteSpace)) s.push(`white-space:${style.whiteSpace}`);
    if (["visible", "hidden", "clip", "scroll", "auto"].includes(style.overflow)) s.push(`overflow:${style.overflow}`);
    // Source Import: flex-shrink:0 у карточек горизонтальных scroll-shelf —
    // без этого переполненная строка сжимается в ширину контейнера
    if (Number(style.flexShrink) === 0) s.push("flex-shrink:0");
    if (["none", "uppercase", "lowercase", "capitalize"].includes(style.textTransform)) s.push(`text-transform:${style.textTransform}`);
    const op = Number(style.opacity); if (Number.isFinite(op) && op >= 0 && op <= 1) s.push(`opacity:${op}`);
    if (["contain", "cover", "fill", "none", "scale-down"].includes(style.objectFit)) s.push(`object-fit:${style.objectFit}`);
    // Source Import: точный crop картинок и фильтры/блендинг (безопасный charset
    // как у boxShadow — url()-фильтры компилятор отправляет в raster fallback)
    if (typeof style.objectPosition === "string" && style.objectPosition.length <= 40 && /^[\d.%\s-]|^(left|center|right|top|bottom)/.test(style.objectPosition)) s.push(`object-position:${style.objectPosition}`);
    if (typeof style.filter === "string" && style.filter.length <= 300 && !/[;{}<>"'\\\r\n]/.test(style.filter) && !/url\s*\(/i.test(style.filter)) s.push(`filter:${style.filter}`);
    if (typeof style.backdropFilter === "string" && style.backdropFilter.length <= 300 && !/[;{}<>"'\\\r\n]/.test(style.backdropFilter) && !/url\s*\(/i.test(style.backdropFilter)) s.push(`backdrop-filter:${style.backdropFilter}`);
    if (typeof style.mixBlendMode === "string" && /^[a-z-]+$/.test(style.mixBlendMode)) s.push(`mix-blend-mode:${style.mixBlendMode}`);
    if (style.direction === "rtl") s.push("direction:rtl");
    if (typeof style.writingMode === "string" && /^(vertical|sideways)-/.test(style.writingMode)) s.push(`writing-mode:${style.writingMode}`);
    const ow = Number(style.outline); if (Number.isFinite(ow) && ow > 0 && ow <= 64) s.push(`outline:${ow}px solid ${safeColor(style.outlineColor) || "#808080"}`);
    // Source Import visual channels: gradient background/mask и clip-path.
    // Только безопасный charset (как boxShadow), url() запрещён — внешние
    // ресурсы переносятся через image-слои, а не через CSS.
    const bgImg = style.backgroundImage;
    if (typeof bgImg === "string" && bgImg.length <= 800 && !/[;{}<>"'\\\r\n]/.test(bgImg) && !/url\s*\(/i.test(bgImg)) s.push(`background-image:${bgImg}`);
    const mask = style.maskImage;
    if (typeof mask === "string" && mask.length <= 800 && !/[;{}<>"'\\\r\n]/.test(mask) && !/url\s*\(/i.test(mask)) s.push(`mask-image:${mask}`, `-webkit-mask-image:${mask}`);
    const cp = style.clipPath;
    if (typeof cp === "string" && cp.length <= 300 && /^[a-zA-Z0-9\s(),.%#-]+$/.test(cp)) s.push(`clip-path:${cp}`);
    // Свечение текста. Узлы text/heading рендерятся именно этой функцией, а не
    // visualTextCss (она обслуживает только подписи кнопок), поэтому канал
    // обязан быть здесь — иначе подсветка акцентного слова не доезжает.
    const ts = style.textShadow;
    if (typeof ts === "string" && ts.length <= 300 && !/[;{}<>"'\\\r\n]/.test(ts) && !/url\s*\(/i.test(ts)) s.push(`text-shadow:${ts}`);
    // Градиентная заливка глифов: идёт ПОСЛЕ background-image и color выше —
    // последнее правило побеждает, поэтому цвет становится прозрачным, а
    // градиент обрезается по буквам, а не красит прямоугольник.
    if (style.backgroundClip === "text" && typeof bgImg === "string") {
      s.push("-webkit-background-clip:text", "background-clip:text", "color:transparent");
    }
    return s.join(";");
  }
  /** Inline-акценты внутри text/heading: свой стиль, свой измеренный кадр.
   *  Возвращает готовый HTML или "" — узлы без кадра сюда не попадают, их
   *  текст уже поглощён родителем (компилятор помечает такие merged-into-text). */
  function accentChildren(el) {
    const kids = Array.isArray(el.children) ? el.children : [];
    const placed = kids.filter((c) => c && c.type === "text" && c.frame
      && typeof c.frame.x === "number" && typeof c.frame.y === "number");
    if (!placed.length) return "";
    return placed.map((c) => {
      const css = [
        "position:absolute",
        `left:${c.frame.x}px`,
        `top:${c.frame.y}px`,
        typeof c.frame.width === "number" ? `width:${c.frame.width}px` : "",
        visualCss(c.style),
      ].filter(Boolean).join(";");
      return `<span style="${css}">${esc(c.text || "")}</span>`;
    }).join("");
  }
  function visualTextCss(style) {
    if (!style || typeof style !== "object") return "";
    const s = [];
    const color = safeColor(style.color); if (color) s.push(`color:${color}`);
    const family = style.fontFamily ? safeFontStack(style.fontFamily) : ""; if (family) s.push(`font-family:${family}`);
    const fs = Number(style.fontSize); if (Number.isFinite(fs) && fs >= 1 && fs <= 512) s.push(`font-size:${fs}px`);
    const fw = Number(style.fontWeight); if (Number.isFinite(fw) && fw >= 100 && fw <= 900) s.push(`font-weight:${fw}`);
    const lh = Number(style.lineHeight); if (Number.isFinite(lh) && lh >= .5 && lh <= 10) s.push(`line-height:${lh}`);
    const ls = Number(style.letterSpacing); if (Number.isFinite(ls) && ls >= -20 && ls <= 100) s.push(`letter-spacing:${ls}px`);
    if (style.fontStyle === "italic" || style.fontStyle === "oblique") s.push(`font-style:${style.fontStyle}`);
    if (style.fontVariantNumeric === "tabular-nums") s.push(`font-variant-numeric:tabular-nums`);
    if (["none", "underline", "line-through", "overline"].includes(style.textDecoration)) s.push(`text-decoration:${style.textDecoration}`);
    if (["none", "uppercase", "lowercase", "capitalize"].includes(style.textTransform)) s.push(`text-transform:${style.textTransform}`);
    // Свечение акцентного слова. Charset тот же, что у boxShadow: только
    // числа, единицы, цвета и запятые — без url()/expression().
    const ts = style.textShadow;
    if (typeof ts === "string" && ts.length <= 300 && /^[a-zA-Z0-9\s(),.%#-]+$/.test(ts)) s.push(`text-shadow:${ts}`);
    // Градиентная заливка текста: цвет глифов задаёт background-clip, поэтому
    // color обязан стать прозрачным — иначе градиент не виден.
    const bgImage = style.backgroundImage;
    if (style.backgroundClip === "text" && typeof bgImage === "string"
      && bgImage.length <= 800 && !/url\s*\(|expression/i.test(bgImage)) {
      s.push(`background-image:${bgImage}`, "-webkit-background-clip:text",
        "background-clip:text", "color:transparent");
    }
    return s.join(";");
  }
  function styleAttr(style, extra) {
    const css = [extra || "", visualCss(style)].filter(Boolean).join(";");
    return css ? ` style="${css}"` : "";
  }

  function shouldLoadGoogleFont(family) {
    const name = safeFontFamily(family);
    const catalog = DesignAIFontCatalog;
    if (catalog && catalog.isSystemFamily && catalog.isSystemFamily(name)) return false;
    if (catalog && catalog.isGoogleFamily) return catalog.isGoogleFamily(name);
    return !!name;
  }

  function addFontFamily(fams, family, weight) {
    const name = safeFontFamily(family);
    if (!name || !shouldLoadGoogleFont(name)) return;
    const w = Math.min(900, Math.max(100, Math.round(Number(weight) || 400)));
    fams.add(name.replace(/ /g, "+") + ":wght@" + w);
  }

  function collectStyleFonts(node, fams) {
    if (!node || typeof node !== "object") return;
    if (node.style && node.style.fontFamily) addFontFamily(fams, node.style.fontFamily, node.style.fontWeight);
    if (Array.isArray(node.children)) node.children.forEach(child => collectStyleFonts(child, fams));
    if (Array.isArray(node.tree)) node.tree.forEach(sec => collectStyleFonts(sec, fams));
  }

  function fontsUrl(tokens, ir) {
    const fams = new Set();
    for (const key of ["display", "body"]) {
      const f = tokens.font && tokens.font[key];
      if (f && f.family) {
        addFontFamily(fams, f.family, f.weight);
      }
    }
    collectStyleFonts(ir, fams);
    if (!fams.size) return "";
    return "https://fonts.googleapis.com/css2?" + [...fams].map(f => "family=" + f).join("&") + "&display=swap";
  }

  function cssVars(tokens) {
    const c = tokens.color, scale = TYPE_SCALE[tokens.font.scale] || 1;
    // цвета/шрифты/веса приходят из IR (контент недоверенный) — только санация
    const d = DEFAULT_TOKENS.color;
    const primary = safeColor(c.primary) || d.primary;
    const col = (k, fb) => safeColor(c[k]) || fb;
    const fw = (f, fb) => Math.min(900, Math.max(100, Math.round(Number(f && f.weight) || fb)));
    return `
      --c-primary:${primary};--c-secondary:${col("secondary", primary)};--c-accent:${col("accent", primary)};
      --c-bg:${col("background", d.background)};--c-surface:${col("surface", d.surface)};--c-text:${col("text", d.text)};--c-muted:${col("textMuted", d.textMuted)};--c-border:${col("border", d.border)};
      --font-display:${safeFontStack(tokens.font.display.family) || "'Inter'"},sans-serif;--font-body:${safeFontStack(tokens.font.body.family) || "'Inter'"},sans-serif;
      --fw-display:${fw(tokens.font.display, 700)};--fw-body:${fw(tokens.font.body, 400)};
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
      .ir-${uid} .sec-source { padding:0; position:relative; margin:0; }
      .ir-${uid} .source-underlay { position:absolute; inset:0; width:100%; height:100%; object-fit:fill; pointer-events:none; user-select:none; }
      .ir-${uid} .sec-source.with-underlay > [data-ir-frame] > * { opacity:0 !important; }
      .ir-${uid} .sec-source.with-underlay > [data-ir-frame].editing > * { opacity:.92 !important; }
      .dna-editor .ir-${uid} .sec-source.with-underlay .source-underlay { opacity:0 !important; }
      .dna-editor .ir-${uid} .sec-source.with-underlay > [data-ir-frame] > * { opacity:1 !important; }
      .ir-${uid} .wrap { max-width:var(--content-max-width,var(--container)) !important; width:calc(100% - (var(--content-gutter,0px) * 2)); margin-left:auto; margin-right:auto; }
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
      .ir-${uid} .source-control, .ir-${uid} .source-input { appearance:none; background:transparent; border:0;
        color:inherit; font:inherit; text-decoration:none; }
      .ir-${uid} .icon-dot { width:34px; height:34px; border-radius:var(--r-btn); background:var(--c-primary);
        color:#fff; display:inline-flex; align-items:center; justify-content:center; font-size:15px; flex:none; }
      /* Заглушка изображения — тон из палитры (surface + разбавленные accent/primary),
         а не универсальный серый градиент: пустая картинка должна читаться как часть
         макета, а не как дырка в вёрстке. background объявлен дважды: вторая строка
         работает там, где есть color-mix, первая остаётся фолбэком. */
      .ir-${uid} .img-ph { background:var(--c-surface); border-radius:var(--r-card); border:1px solid var(--c-border);
        background-image:linear-gradient(150deg, color-mix(in srgb, var(--c-accent) 16%, transparent) 0%, color-mix(in srgb, var(--c-primary) 9%, transparent) 100%);
        display:flex; align-items:center; justify-content:center; color:var(--c-muted); font-size:12px; min-height:180px; padding:16px; text-align:center; }
      .ir-${uid} .sec-head { text-align:center; max-width:640px; margin:0 auto 40px; }
      .ir-${uid} .sec-head h2 { margin-bottom:12px; }
      .ir-${uid} .divider { height:1px; background:var(--c-border); margin:16px 0; }
      .ir-${uid} .avatar { width:44px; height:44px; border-radius:50%; background:var(--c-primary); color:#fff;
        display:inline-flex; align-items:center; justify-content:center; font-weight:700; flex:none; }
      .ir-${uid} .stars { color:var(--c-accent); letter-spacing:2px; }
      .ir-${uid} [data-ir-path].editing { outline:2px dashed var(--c-primary); outline-offset:2px; cursor:text; }
      .ir-${uid} [data-ir-locked] { cursor:default; }
      .ir-${uid}.ir-mobile { font-size:calc(16px * var(--fs)); line-height:1.55; }
      .ir-${uid}.ir-mobile h1 { font-size:calc(34px * var(--fs)); line-height:1.08; letter-spacing:-.025em; }
      .ir-${uid}.ir-mobile h2 { font-size:calc(26px * var(--fs)); line-height:1.12; }
      .ir-${uid}.ir-mobile .sec:not(.sec-source), .ir-${uid}.ir-mobile .sec-free { padding-left:16px; padding-right:16px; }
      .ir-${uid}.ir-mobile .sec-free { display:flex !important; flex-direction:column; gap:20px; height:auto !important; }
      .ir-${uid}.ir-mobile .sec-free > [data-ir-path]:not([data-ir-transform]) { position:relative !important; inset:auto !important; transform:none !important; }
      .ir-${uid}.ir-mobile .sec:not(.sec-source) .wrap { width:100%; }
      .ir-${uid}.ir-mobile .sec:not(.sec-source) [data-ir-path],
      .ir-${uid}.ir-mobile .sec-free [data-ir-path] { max-width:100%; overflow-wrap:anywhere; }
      .ir-${uid}.ir-mobile .btn { min-height:44px; padding:11px 18px; justify-content:center; }
      .ir-${uid}.ir-tablet .sec:not(.sec-source), .ir-${uid}.ir-tablet .sec-free { padding-left:24px; padding-right:24px; }
      .ir-${uid}.ir-tablet .sec-free { display:flex !important; flex-direction:column; gap:28px; height:auto !important; }
      .ir-${uid}.ir-tablet .sec-free > [data-ir-path]:not([data-ir-transform]) { position:relative !important; inset:auto !important; transform:none !important; }
    `;
  }

  /* ---------- геометрия: frame (модель Figma) ---------- */

  const FLEX_JUSTIFY = { start: "flex-start", center: "center", end: "flex-end", "space-between": "space-between", "space-around": "space-around" };
  const FLEX_ALIGN = { start: "flex-start", center: "center", end: "flex-end", stretch: "stretch", baseline: "baseline" };

  /** frame -> CSS. container=true добавляет раскладку детей (auto-layout/free);
   *  parentFree=true — родитель имеет layout:"free", значит x/y работают (absolute). */
  function frameCss(f, parentFree, container, parentFrame) {
    if (!f || typeof f !== "object") return "";
    const s = [];
    // fill/hug зависят от раскладки родителя: flex-grow растягивает по ГЛАВНОЙ оси,
    // поэтому в column-родителе fill-width не должен иметь flex-grow (и наоборот) —
    // иначе «fill» ломает геометрию и после drag-конверсии элементы разъезжаются
    const pDir = parentFrame && parentFrame.direction === "row" ? "row" : "column";
    const wrappingFill = f.width === "fill" && pDir === "row" && parentFrame && parentFrame.wrap;
    if (typeof f.width === "number") s.push(`width:${f.width}px`);
    else if (f.width === "fill") {
      if (parentFree) s.push("width:100%");
      else if (wrappingFill) {
        const basis = typeof f.minWidth === "number" ? f.minWidth : 220;
        s.push("width:auto", `flex:1 1 ${basis}px`, `min-width:min(100%,${basis}px)`);
      }
      else if (pDir === "row") s.push("width:100%", "flex:1 1 auto", "min-width:0");
      else s.push("width:100%", "min-width:0");
    }
    else if (f.width === "hug") s.push("width:fit-content");
    if (typeof f.height === "number") s.push(`height:${f.height}px`);
    else if (f.height === "fill") {
      if (parentFree) s.push("height:100%");
      else if (pDir === "column") s.push("align-self:stretch", "flex-grow:1", "min-height:0");
      else s.push("align-self:stretch", "min-height:0");
    }
    else if (f.height === "hug") s.push("height:fit-content");
    if (typeof f.minWidth === "number" && !wrappingFill) s.push(`min-width:${f.minWidth}px`);
    if (typeof f.maxWidth === "number") s.push(`max-width:${f.maxWidth}px`);
    if (typeof f.minHeight === "number") s.push(`min-height:${f.minHeight}px`);
    if (typeof f.maxHeight === "number") s.push(`max-height:${f.maxHeight}px`);
    if (f.clip) s.push("overflow:hidden");
    // Полный CSS transform источника имеет приоритет над простым rotation;
    // charset-санитизация как у boxShadow (без инъекционных символов).
    if (typeof f.transform === "string" && f.transform.length <= 300 && !/[;{}<>"'\\\r\n]/.test(f.transform)) s.push(`transform:${f.transform}`);
    else if (typeof f.rotation === "number" && f.rotation) s.push(`transform:rotate(${f.rotation}deg)`);
    const z = Number(f.z); if (Number.isInteger(z) && z >= -1000 && z <= 1000) s.push(`z-index:${z}`);
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
 *  cls — опциональный класс обёртки (например sec-free для дефолтного padding).
 *  data-ir-transform помечает захваченный CSS transform источника: responsive
 *  reflow-правила (.ir-mobile/.ir-tablet .sec-free) не сбрасывают его — linked
 *  viewports Source Import хранят измеренный transform каждого viewport. */
  function withFrame(html, frame, parentFree, container, irPath, cls, parentFrame, extraCss) {
    const css = [frameCss(frame, parentFree, container, parentFrame), extraCss || ""].filter(Boolean).join(";");
    if (!css && !cls) return html;
    const pathAttr = irPath ? ` data-ir-path="${esc(irPath)}"` : "";
    const trAttr = frame && typeof frame.transform === "string" && frame.transform ? " data-ir-transform" : "";
    const clsAttr = cls ? ` class="${cls}"` : "";
    return `<div data-ir-frame${pathAttr}${trAttr}${clsAttr} style="${css}">${html}</div>`;
  }

  /** data-ir-transform для корневых тегов контейнеров (card/button/input),
   *  которые несут data-ir-path без withFrame-обёртки (см. withFrame). */
  function transformAttr(frame) {
    return frame && typeof frame.transform === "string" && frame.transform ? " data-ir-transform" : "";
  }

  /* ---------- элементы (children) ---------- */

  const ASPECT_RATIO = { "1:1": "1/1", "4:3": "4/3", "16:9": "16/9", "3:4": "3/4", "9:16": "9/16" };

  function renderElement(el, uid, parentFree, parentFrame) {
    if (el && el.__responsiveHidden) return "";
    const irPath = el.__path || null;
    const html = renderElementInner(el, uid, parentFree, parentFrame);
    let out;
    if (el.type === "card" || el.type === "frame" || ((el.type === "button" || el.type === "input") && el.children && el.children.length)) {
      out = html;
    } else {
      // текст с захваченной высотой: страховка от визуального наезда на соседей,
      // если метрики шрифта всё же разойдутся (клип вместо overflow поверх)
      const clipText = (el.type === "text" || el.type === "heading") &&
        el.frame && typeof el.frame.height === "number" ? "overflow:hidden" : "";
      const wrapped = withFrame(html, el.frame, parentFree, false, irPath, "", parentFrame, clipText);
      // если frame пустой и withFrame не обернул — добавляем span-обёртку с path
      out = (wrapped === html && irPath)
        ? `<span data-ir-path="${esc(irPath)}" style="display:inline-block">${html}</span>`
        : wrapped;
    }
    // editable:false (raster fallback источника): слой остаётся selectable и
    // inspectable (data-ir-path не трогаем), но помечается data-ir-locked —
    // geoedit/inspector/AI mutation paths обязаны отказать в правках.
    if (isLockedNode(el)) {
      const lock = ` data-ir-locked="${esc(String(el.lockedReason || "locked"))}"`;
      out = out.replace(/^<([a-zA-Z][a-zA-Z0-9]*)/, "<$1" + lock);
    }
    return out;
  }

  function renderElementInner(el, uid, parentFree, parentFrame) {
    // data-ir-path НЕ ставится здесь — он добавляется на withFrame-обёртку в renderElement
    // или на card-корень. Исключение: props-элементы секций ставят path сами.
    switch (el.type) {
      /* Акцентные inline-дети (подсвеченное слово, градиентная заливка) —
       * самостоятельные слои со своим стилем и измеренным кадром. Раньше они
       * схлопывались в голый текст: компилятор их отдавал, а рендер терял,
       * поэтому подсветка не доезжала до картинки. */
      case "heading": {
        const lvl = Math.min(4, Math.max(1, el.level || 2));
        const a = safeAlign(el.align);
        const alignCss = a ? `text-align:${a}` : "";
        const placed = accentChildren(el);
        const css = [visualCss(el.style), alignCss, placed ? "position:relative" : ""].filter(Boolean).join(";");
        const sa = css ? ` style="${css}"` : "";
        const childText = Array.isArray(el.children)
          ? el.children.map((c) => c && (c.text || c.title || "")).filter(Boolean).join(" ")
          : "";
        const own = esc(el.text || el.title || (placed ? "" : childText) || "");
        return `<h${lvl}${sa}>${own}${placed || ""}</h${lvl}>`;
      }
      case "text": {
        const a = safeAlign(el.align);
        const alignCss = a ? `text-align:${a}` : "";
        const placed = accentChildren(el);
        const css = [visualCss(el.style), alignCss, placed ? "position:relative" : ""].filter(Boolean).join(";");
        const sa = css ? ` style="${css}"` : "";
        const cls = el.size === "sm" || el.size === "xs" ? ' class="muted"' : "";
        return `<p${cls}${sa}>${esc(el.text || "")}${placed || ""}</p>`;
      }
      case "button": {
        const free = el.frame && el.frame.layout === "free";
        const kids = (el.children || []).map(c => renderElement(c, uid, free, el.frame)).join("");
        if (kids) {
          const fcss = frameCss(el.frame, parentFree, true, parentFrame);
          const css = [fcss, "padding:0", visualCss(el.style)].filter(Boolean).join(";");
          const path = el.__path ? ` data-ir-path="${esc(el.__path)}"` : "";
          return `<button type="button" class="source-control"${path}${transformAttr(el.frame)}${css ? ` style="${css}"` : ""}>${kids}</button>`;
        }
        const textCss = visualTextCss(el.style);
        const path = el.__path ? ` data-ir-path="${esc(el.__path)}"` : "";
        return `<a class="btn btn-${el.variant || "primary"}"${path}${styleAttr(el.style)}><span${textCss ? ` style="${textCss}"` : ""}>${esc(el.text || "")}</span></a>`;
      }
      case "badge":
        return `<span class="badge${el.tone && el.tone !== "default" ? " tone-" + el.tone : ""}">${esc(el.text || el.label || "")}</span>`;
      case "icon":
        return `<span class="icon-dot">${esc((el.icon || "✦").slice(0, 2))}</span>`;
      case "image":
        if (el.src) {
          return `<img src="${esc(el.src)}" alt="${esc(el.alt || "")}"${styleAttr(el.style, "display:block;width:100%;height:100%;object-fit:contain")} decoding="sync">`;
        }
        {
          // без aspect заглушка была одинаковой полосой в 180px: в композиции
          // это ломало ритм колонки, где картинка задаёт пропорцию блока
          const ratio = ASPECT_RATIO[el.aspect];
          const css = ratio ? ` style="aspect-ratio:${ratio};min-height:0"` : "";
          return `<div class="img-ph"${css}>${esc(el.imagePrompt || el.alt || "изображение")}</div>`;
        }
      case "divider":
        return `<div class="divider"></div>`;
      case "rect": {
        const bg = /^#[0-9a-fA-F]{3,8}$/.test(el.fill || "") ? el.fill : "#8B5CF6";
        const rad = typeof el.radius === "number" ? el.radius : 8;
        return `<div${styleAttr(el.style, `background:${bg};border-radius:${rad}px;min-height:1px;width:100%;height:100%`)}></div>`;
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
        if (el.children && el.children.length) {
          const free = el.frame && el.frame.layout === "free";
          const kids = el.children.map(c => renderElement(c, uid, free, el.frame)).join("");
          const fcss = frameCss(el.frame, parentFree, true, parentFrame);
          const css = [fcss, "padding:0", visualCss(el.style)].filter(Boolean).join(";");
          const path = el.__path ? ` data-ir-path="${esc(el.__path)}"` : "";
          return `<div class="source-input"${path}${transformAttr(el.frame)}${css ? ` style="${css}"` : ""}>${kids}</div>`;
        }
        return `<input class="input" placeholder="${esc(el.placeholder || el.label || "")}" value="${esc(el.value || "")}">`;
      /* Голый контейнер композиции: без карточной обводки/фона — только собственная
       * геометрия (auto-layout или free) и дети. Рендерится как card с role, но это
       * явный тип, чтобы модель не путала «фрейм» с «карточкой». */
      case "frame": {
        const free = el.frame && el.frame.layout === "free";
        const inner = (el.children || []).map(c => renderElement(c, uid, free, el.frame)).join("");
        const fcss = frameCss(el.frame, parentFree, true, parentFrame);
        const path = el.__path ? ` data-ir-path="${esc(el.__path)}"` : "";
        const css = [fcss, visualCss(el.style)].filter(Boolean).join(";");
        return `<div class="ir-frame"${path}${transformAttr(el.frame)}${css ? ` style="${css}"` : ""}>${inner}</div>`;
      }
      case "card": {
        const free = el.frame && el.frame.layout === "free";
        const inner = (el.children || []).map(c => renderElement(c, uid, free, el.frame)).join("");
        const fcss = frameCss(el.frame, parentFree, true, parentFrame);
        const cardPath = el.__path ? ` data-ir-path="${esc(el.__path)}"` : "";
        const cardTr = transformAttr(el.frame);
        if (el.role) {
          const sourceCss = [fcss, visualCss(el.style)].filter(Boolean).join(";");
          return `<div${cardPath}${cardTr}${sourceCss ? ` style="${sourceCss}"` : ""}>${inner}</div>`;
        }
        const css = [fcss, visualCss(el.style)].filter(Boolean).join(";");
        return `<div class="card"${cardPath}${cardTr}${css ? ` style="${css}"` : ""}>
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
      : cols ? ` style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:20px"` : "";
    return `<div${style}>${children.map(c => renderElement(c, uid, free, parentFrame)).join("")}</div>`;
  }

  /* ---------- секции ---------- */

  function btnHtml(btn, defVariant, path) {
    if (!btn) return "";
    const btnPath = path ? ` data-ir-path="${esc(path.replace(/\.text$/, ""))}"` : "";
    return `<a class="btn btn-${btn.variant || defVariant}"${btnPath}><span>${esc(btn.text || "")}</span></a>`;
  }

  function renderSection(sec, uid, parentFree) {
    const isFree = !!(sec.frame && sec.frame.layout === "free");
    const hasChildren = sec.children && sec.children.length > 0;
    // Browser-captured layers already contain exact x/y values relative to the
    // source block. Generic section padding would shift every layer and can
    // force a 73px header to a 128px minimum box.
    const isMeasuredSource = sec.type === "source-block" || sec.variant === "dom-capture";
    const sourcePreview = isMeasuredSource && (sec.preview || sec.sourcePreview || (sec.props && sec.props.sourcePreview));
    const isStructuredSource = isMeasuredSource && hasChildren;
    // free-секция с children — тоже reproduction-режим (как source-block):
    // рендерим ТОЛЬКО children прямо в обёртку [data-ir-sec]. Иначе generic-inner
    // (<section class="sec"> с дефолтным padding + .wrap) давал двойной отступ и
    // перехватывал absolute-якорь детей — контракт frame.x/y от padding-box секции
    // ломался (элементы съезжали на 64/32 + margin .wrap).
    const reproduction = isStructuredSource || (isFree && hasChildren);
    // absolute-дети auto-секции поднимаем на уровень обёртки [data-ir-sec]: их x/y —
    // от padding-box секции (контракт geoedit relPos/posOf), а generic-inner
    // (<section class="sec"> с дефолтным padding + .wrap) сместил бы якорь на 64/32+.
    // Flow-дети остаются внутри generic-структуры и не сдвигаются.
    let absChildren = null;
    if (!reproduction && hasChildren) {
      const abs = sec.children.filter(c => c && c.frame && c.frame.absolute &&
        (typeof c.frame.x === "number" || typeof c.frame.y === "number"));
      if (abs.length) absChildren = abs;
    }
    const innerSec = absChildren
      ? Object.assign({}, sec, { children: sec.children.filter(c => absChildren.indexOf(c) < 0) })
      : sec;
    const html = reproduction ? "" : renderSectionInner(innerSec, uid);
    let childrenHtml = "";
    if (reproduction) {
      childrenHtml = sec.children.map(c => renderElement(c, uid, isFree, sec.frame)).join("");
    } else if (absChildren) {
      childrenHtml = absChildren.map(c => renderElement(c, uid, false, sec.frame)).join("");
    }
    // Source screenshots are comparison evidence, never the editable canvas.
    const underlay = "";
    const combined = underlay + html + childrenHtml;
    const secStyle = visualCss(sec.style);
    // обёртка — якорь hoisted absolute-детей: position:relative без flex-раскладки
    // (extraCss гарантирует и саму обёртку, даже если у секции пустой frame)
    const railCss = sec.frame && typeof sec.frame.contentMaxWidth === "number"
      ? `--content-max-width:${sec.frame.contentMaxWidth}px;--content-gutter:${typeof sec.frame.contentGutter === "number" ? sec.frame.contentGutter : 0}px`
      : "";
    const extraCss = [secStyle, railCss, absChildren ? "position:relative" : ""].filter(Boolean).join(";");
    // free-секция рендерится без .sec-внутренностей — класс sec-free сохраняет
    // дефолтный padding секции, иначе при конверсии в free дети «уплывают»
    return withFrame(combined, sec.frame, parentFree, isStructuredSource || isFree, null,
      isStructuredSource ? "sec-source" : ((isFree && hasChildren) ? "sec-free" : ""), null, extraCss);
  }

  /* Фон и плотность секции-композиции: только токены, никаких сырых hex из props.
   * На инвертированных плитах переопределяем muted/border локально: иначе приглушённый
   * текст остаётся тёмно-серым на цветном фоне и проваливается по контрасту. */
  const INVERTED_ROLES = "color:#fff;--c-text:#fff;--c-muted:rgba(255,255,255,.78);--c-border:rgba(255,255,255,.24)";
  const COMPOSITION_SURFACE = {
    background: "background:var(--c-bg)",
    surface: "background:var(--c-surface)",
    primary: `background:var(--c-primary);${INVERTED_ROLES}`,
    accent: `background:var(--c-accent);${INVERTED_ROLES}`,
    none: "",
  };
  const COMPOSITION_PADDING = {
    tight: "padding-top:calc(var(--sec-py) * .55);padding-bottom:calc(var(--sec-py) * .55)",
    normal: "",
    airy: "padding-top:calc(var(--sec-py) * 1.6);padding-bottom:calc(var(--sec-py) * 1.6)",
  };

  function compositionSurface(value) {
    return COMPOSITION_SURFACE[value] || "";
  }

  function compositionPadding(value) {
    return COMPOSITION_PADDING[value] || "";
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

    /* Свободная композиция: содержимое целиком в children (frame + примитивы).
     * Семантических props нет, кроме рамки секции — фон из токенов и плотность. */
    if (t === "composition") {
      const free = !!(sec.frame && sec.frame.layout === "free");
      const kids = (sec.children || []).map(c => renderElement(c, uid, free, sec.frame)).join("");
      const style = [compositionSurface(p.background), compositionPadding(p.density)]
        .filter(Boolean).join(";");
      const head = p.heading
        ? `<h2 data-ir-path="props.heading" style="margin-bottom:${p.subheading ? 12 : 32}px;max-width:14ch">${esc(p.heading)}</h2>`
        : "";
      const sub = p.subheading
        ? `<p class="muted" data-ir-path="props.subheading" style="margin-bottom:32px;max-width:62ch">${esc(p.subheading)}</p>`
        : "";
      return `<section class="sec sec-composition ${base}"${style ? ` style="${style}"` : ""}>
        <div class="wrap">${head}${sub}${kids}</div></section>`;
    }

    if (t === "hero") {
      const badge = p.badge ? `<span class="badge tone-primary" style="margin-bottom:16px"><span data-ir-path="props.badge">${esc(p.badge)}</span></span>` : "";
      const head = `<h1 data-ir-path="props.heading" style="margin-bottom:16px">${esc(p.heading || "")}</h1>`;
      const sub = p.subheading ? `<p class="muted" data-ir-path="props.subheading" style="font-size:calc(17px*var(--fs));margin-bottom:28px;max-width:560px">${esc(p.subheading)}</p>` : "";
      const btns = `<div style="display:flex;gap:12px;flex-wrap:wrap">${btnHtml(p.ctaPrimary, "primary", "props.ctaPrimary.text")}${btnHtml(p.ctaSecondary, "outline", "props.ctaSecondary.text")}</div>`;
      const heroMedia = (minHeight, extra) => p.media
        ? p.media.src
          ? `<div class="img-ph" style="min-height:${minHeight}px;overflow:hidden;padding:0;${extra || ""}"><img src="${esc(p.media.src)}" alt="${esc(p.media.alt || "")}" style="display:block;width:100%;height:${minHeight}px;object-fit:cover" decoding="sync"></div>`
          : `<div class="img-ph" style="min-height:${minHeight}px;${extra || ""}">${esc(p.media.imagePrompt || p.media.alt || "")}</div>`
        : "";

      /* Редакционная колонка: надзаголовок без плашки, display-заголовок во всю
       * ширину, под ним полоса «лид + действие» — как разворот журнала. */
      if (v === "editorial-stack") {
        const eyebrow = p.badge
          ? `<p class="muted" data-ir-path="props.badge" style="font-size:calc(12px*var(--fs));letter-spacing:.14em;text-transform:uppercase;margin-bottom:28px">${esc(p.badge)}</p>`
          : "";
        return `<section class="sec ${base}"><div class="wrap">
          ${eyebrow}
          <h1 data-ir-path="props.heading" style="font-size:calc(76px*var(--fs));line-height:1.02;letter-spacing:-.03em;margin-bottom:40px;max-width:16ch">${esc(p.heading || "")}</h1>
          <div style="border-top:1px solid var(--c-border);padding-top:28px;display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:40px;align-items:start">
            ${p.subheading ? `<p data-ir-path="props.subheading" style="font-size:calc(19px*var(--fs));max-width:52ch">${esc(p.subheading)}</p>` : "<div></div>"}
            <div style="display:flex;gap:12px;flex-wrap:wrap;justify-content:flex-start">${btnHtml(p.ctaPrimary, "primary", "props.ctaPrimary.text")}${btnHtml(p.ctaSecondary, "ghost", "props.ctaSecondary.text")}</div>
          </div>
          ${heroMedia(360, "margin-top:48px")}</div></section>`;
      }

      /* Плакат: плита surface с рамкой, заголовок занимает почти всю плиту,
       * подпись и действие прижаты к её низу. Одна вертикаль, никакой сетки карточек. */
      if (v === "poster") {
        return `<section class="sec ${base}" style="background:var(--c-surface)"><div class="wrap">
          <div style="border:1px solid var(--c-border);border-radius:var(--r-card);padding:56px 48px;display:flex;flex-direction:column;gap:48px;min-height:520px;justify-content:space-between;background:var(--c-bg)">
            <div>${badge}
              <h1 data-ir-path="props.heading" style="font-size:calc(64px*var(--fs));line-height:1.05;letter-spacing:-.03em;max-width:14ch">${esc(p.heading || "")}</h1></div>
            ${heroMedia(300)}
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr));gap:32px;align-items:end">
              ${p.subheading ? `<p class="muted" data-ir-path="props.subheading" style="font-size:calc(17px*var(--fs));max-width:48ch">${esc(p.subheading)}</p>` : "<div></div>"}
              <div style="display:flex;gap:12px;flex-wrap:wrap">${btnHtml(p.ctaPrimary, "primary", "props.ctaPrimary.text")}${btnHtml(p.ctaSecondary, "outline", "props.ctaSecondary.text")}</div>
            </div></div></div></section>`;
      }

      /* Сдвинутый сплит: узкая текстовая колонка и медиа, поднятое над базовой
       * линией и уходящее за правый край — асимметрия вместо двух равных половин. */
      if (v === "split-offset") {
        const media = heroMedia(420, "margin-top:-64px;border-top-right-radius:0;border-bottom-right-radius:0") ||
          `<div class="img-ph" style="min-height:420px;margin-top:-64px">${esc("медиа")}</div>`;
        return `<section class="sec ${base}" style="overflow:hidden"><div class="wrap" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:56px;align-items:start">
          <div style="display:flex;flex-direction:column;padding-top:24px">${badge}${head}${sub}${btns}</div>
          <div style="position:relative;left:72px">${media}</div></div></section>`;
      }

      /* Нумерованный вход: тезис слева, справа — пронумерованные доказательства
       * из children. Нумерация здесь несёт информацию (порядок шагов), а не декор. */
      if (v === "numbered") {
        const items = (sec.children || []).map((c, i) => `<div style="display:grid;grid-template-columns:56px 1fr;gap:20px;align-items:start;padding:20px 0;border-top:1px solid var(--c-border)">
          <span style="font-family:var(--font-display);font-weight:var(--fw-display);font-size:calc(22px*var(--fs));color:var(--c-primary);line-height:1.2">${String(i + 1).padStart(2, "0")}</span>
          <div>${renderElement(c, uid, false, sec.frame)}</div></div>`).join("");
        return `<section class="sec ${base}"><div class="wrap" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:64px;align-items:start">
          <div style="display:flex;flex-direction:column">${badge}${head}${sub}${btns}</div>
          <div>${items}</div></div></section>`;
      }

      if (v === "split" || v === "split-reverse") {
        const media = p.media
          ? p.media.src
            ? `<div class="img-ph" style="min-height:320px;overflow:hidden;padding:0"><img src="${esc(p.media.src)}" alt="${esc(p.media.alt || "")}" style="display:block;width:100%;height:320px;object-fit:cover" decoding="sync"></div>`
            : `<div class="img-ph" style="min-height:320px">${esc(p.media.imagePrompt || p.media.alt || "")}</div>`
          : `<div class="img-ph" style="min-height:320px">медиа</div>`;
        const txt = `<div style="display:flex;flex-direction:column;justify-content:center">${badge}${head}${sub}${btns}</div>`;
        return `<section class="sec ${base}"><div class="wrap" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:48px;align-items:center">
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
      const kids = sec.children || [];
      const kid = (c) => renderElement(c, uid, false, sec.frame);

      /* Рейка-список: возможности идут строками с крупным индексом, разделённые
       * линией. Плотный ритм без карточной сетки — контрапункт к grid-3. */
      if (v === "list-rail") {
        const rows = kids.map((c, i) => `<div style="display:grid;grid-template-columns:72px 1fr;gap:28px;align-items:start;padding:26px 0;border-top:1px solid var(--c-border)">
          <span style="font-family:var(--font-display);font-weight:var(--fw-display);font-size:calc(26px*var(--fs));color:var(--c-primary);line-height:1.1">${String(i + 1).padStart(2, "0")}</span>
          <div>${kid(c)}</div></div>`).join("");
        return `<section class="sec ${base}"><div class="wrap" style="max-width:900px">
          ${secHeadLeft(p)}<div>${rows}</div></div></section>`;
      }

      /* Асимметричное бенто: ширины плиток чередуются 4/2 → 3/3 → 2/4 по шестиколоночной
       * сетке, первая плитка выше остальных. Ряды остаются заполненными без дыр. */
      if (v === "bento-asym") {
        const spans = [4, 2, 3, 3, 2, 4];
        // display:grid у плитки — чтобы содержимое растягивалось на всю ячейку:
        // соседи в одном ряду обязаны быть одной высоты
        const tiles = kids.map((c, i) => `<div style="grid-column:span ${spans[i % spans.length]};${i === 0 ? "min-height:280px;" : ""}display:grid">${kid(c)}</div>`).join("");
        return `<section class="sec ${base}"><div class="wrap">
          ${secHead(p)}
          <div style="display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:20px">${tiles}</div></div></section>`;
      }

      /* Манифест в две колонки: заголовок остаётся слева и залипает, тезисы
       * читаются как сплошной текст справа, а не как карточки. */
      if (v === "two-col-manifest") {
        const rows = kids.map((c, i) => `<div style="${i ? "border-top:1px solid var(--c-border);padding-top:28px;" : ""}margin-bottom:28px">${kid(c)}</div>`).join("");
        return `<section class="sec ${base}"><div class="wrap" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:72px;align-items:start">
          <div style="position:sticky;top:32px">${secHeadLeft(p)}</div>
          <div>${rows}</div></div></section>`;
      }

      const cols = v === "grid-2" ? 2 : v === "grid-4" ? 4 : 3;
      return `<section class="sec ${base}"><div class="wrap">
        ${secHead(p)}
        ${renderChildren(sec.children, uid, v === "bento" ? 3 : cols, sec.frame)}
        </div></section>`;
    }

    if (t === "feature-alternating") {
      const rows = (sec.children || []).map((c, i) => {
        const media = `<div class="img-ph" style="min-height:240px">${esc(c.imagePrompt || c.alt || "изображение")}</div>`;
        const txt = `<div style="display:flex;flex-direction:column;justify-content:center;gap:12px">
          ${c.title || c.text ? `<h3>${esc(c.title || "")}</h3><p class="muted">${esc(c.text || "")}</p>` : renderElement(c, uid, false, sec.frame)}
          ${(c.children || []).map(ch => renderElement(ch, uid, !!(c.frame && c.frame.layout === "free"), c.frame)).join("")}</div>`;
        return `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:48px;align-items:center;margin-bottom:48px">${i % 2 ? txt + media : media + txt}</div>`;
      }).join("");
      return `<section class="sec ${base}"><div class="wrap">${secHead(p)}${rows}</div></section>`;
    }

    if (t === "stats") {
      const items = (p.items || []).map((it, i) =>
        `<div style="text-align:center"><div data-ir-path="props.items.${i}.value" style="font-family:var(--font-display);font-weight:var(--fw-display);font-size:calc(38px*var(--fs));color:var(--c-primary)">${esc(it.value)}</div>
        <div class="muted" data-ir-path="props.items.${i}.label">${esc(it.label)}</div></div>`).join("");
      return `<section class="sec ${base}"><div class="wrap">
        ${p.heading ? `<h2 data-ir-path="props.heading" style="text-align:center;margin-bottom:40px">${esc(p.heading)}</h2>` : ""}
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,200px),1fr));gap:24px">${items}</div></div></section>`;
    }

    if (t === "steps") {
      return `<section class="sec ${base}"><div class="wrap">${secHead(p)}
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,240px),1fr));gap:20px">
        ${(sec.children || []).map((c, i) => `<div class="card"><div class="icon-dot" style="margin-bottom:12px">${i + 1}</div>
          <h3 style="margin-bottom:8px">${esc(c.title || c.text || "Шаг " + (i + 1))}</h3><p class="muted">${esc(c.text || "")}</p></div>`).join("")}</div></div></section>`;
    }

    if (t === "gallery") {
      return `<section class="sec ${base}"><div class="wrap">${secHead(p)}
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,160px),1fr));gap:16px">
        ${(sec.children || []).map((c, i) => `<div class="img-ph" style="min-height:${v === "masonry" ? 140 + ((i * 67) % 120) : 200}px">${esc(c.imagePrompt || c.alt || "фото")}</div>`).join("")}</div></div></section>`;
    }

    if (t === "testimonials") {
      const cols = v === "grid-2" ? 2 : v === "single-featured" ? 1 : 3;
      return `<section class="sec ${base}"><div class="wrap">${secHead(p)}
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:20px">
        ${(sec.children || []).map(c => `<div class="card">
          ${c.children && c.children.some(x => x.type === "rating") ? "" : '<span class="stars">★★★★★</span>'}
          <p style="margin:12px 0 16px">${esc(c.text || "")}</p>
          <span style="display:flex;align-items:center;gap:12px"><span class="avatar">${esc(initials(c.name || c.title))}</span>
          <span><strong>${esc(c.name || c.title || "")}</strong><br><span class="muted" style="font-size:13px">${esc(c.role || "")}</span></span></span></div>`).join("")}</div></div></section>`;
    }

    if (t === "pricing") {
      return `<section class="sec ${base}"><div class="wrap">${secHead(p)}
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,240px),1fr));gap:20px;align-items:stretch">
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
        <div style="display:${twoCol ? "grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr));gap:16px" : "flex;flex-direction:column;gap:12px"}">
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
      if (v === "split") return `<section class="sec ${base}"><div class="wrap" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:32px;align-items:center">${inner}</div></section>`;
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
      const submit = p.submit || {};
      const submitFrame = sec._frames && sec._frames["props.submit"] || {};
      const submitCss = ["justify-content:center", frameCss(submitFrame, false, false), visualCss(submit.style)].filter(Boolean).join(";");
      const submitText = submit.text ?? p.submitText ?? "Отправить";
      const form = `<div class="card" style="display:flex;flex-direction:column;gap:14px">
        ${(p.fields || []).map((f, i) => {
          const path = `props.fields.${i}`;
          const frame = sec._frames && sec._frames[path] || {};
          const labelPart = f.parts && f.parts.label || {};
          const controlPart = f.parts && f.parts.control || {};
          const labelPath = `${path}.parts.label`;
          const controlPath = `${path}.parts.control`;
          const labelFrame = sec._frames && sec._frames[labelPath] || {};
          const controlFrame = sec._frames && sec._frames[controlPath] || {};
          const groupCss = ["display:flex", "flex-direction:column", "gap:6px", frameCss(frame, false, false), visualCss(f.style)].filter(Boolean).join(";");
          const labelCss = ["font-size:calc(13px*var(--fs))", "font-weight:600", frameCss(labelFrame, false, false), visualTextCss(labelPart.style)].filter(Boolean).join(";");
          const controlCss = [frameCss(controlFrame, false, false), visualCss(controlPart.style)].filter(Boolean).join(";");
          const controlStyle = controlCss ? ` style="${controlCss}"` : "";
          const labelText = labelPart.text ?? f.label ?? "";
          const placeholder = controlPart.placeholder ?? f.placeholder ?? "";
          const inputType = controlPart.inputType ?? f.inputType;
          return `<div data-ir-path="${path}" data-form-field="${i}" style="${groupCss}">
            <span data-ir-path="${labelPath}" data-form-part="label" style="${labelCss}">${esc(labelText)}${f.required ? " *" : ""}</span>
            ${inputType === "textarea" ? `<textarea data-ir-path="${controlPath}" data-form-part="control" class="input" rows="3" placeholder="${esc(placeholder)}"${controlStyle}></textarea>`
              : inputType === "checkbox" ? `<span data-ir-path="${controlPath}" data-form-part="control" style="display:flex;gap:8px;align-items:center;font-weight:400;${controlCss}"><input type="checkbox"> <span>${esc(placeholder)}</span></span>`
              : `<input data-ir-path="${controlPath}" data-form-part="control" class="input" placeholder="${esc(placeholder)}"${controlStyle}>`}</div>`;
        }).join("")}
        <a class="btn btn-primary" data-ir-path="props.submit" data-form-submit style="${submitCss}">${esc(submitText)}</a></div>`;
      const info = `<div style="display:flex;flex-direction:column;justify-content:center;gap:12px">
        <h2 data-ir-path="props.heading">${esc(p.heading || "")}</h2>
        ${p.subheading ? `<p class="muted" data-ir-path="props.subheading">${esc(p.subheading)}</p>` : ""}</div>`;
      if (v === "split-info" || v === "map") {
        return `<section class="sec ${base}"><div class="wrap" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:48px;align-items:start">${info}${form}</div></section>`;
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
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,180px),1fr));gap:32px;margin-bottom:40px">
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

  /** Заголовок секции без центрирования и без ограничения в 640px — для вариантов,
   *  где шапка стоит в левой колонке (list-rail, two-col-manifest). */
  function secHeadLeft(p) {
    if (!p.heading && !p.subheading) return "";
    return `<div class="sec-head" style="text-align:left;max-width:none;margin:0 0 32px">
      ${p.heading ? `<h2 data-ir-path="props.heading">${esc(p.heading)}</h2>` : ""}
      ${p.subheading ? `<p class="muted" data-ir-path="props.subheading">${esc(p.subheading)}</p>` : ""}</div>`;
  }

  /* ---------- публичное API ---------- */

  let uidCounter = 0;
  const renderStates = new WeakMap();

  function nowMs() {
    return typeof performance !== "undefined" && typeof performance.now === "function"
      ? performance.now()
      : Date.now();
  }

  function cachedRenderIsLive(container, cached) {
    return !!cached && cached.styleEl && cached.rootEl &&
      cached.styleEl.parentElement === container && cached.rootEl.parentElement === container;
  }

  function replaceRenderedSection(root, index, html) {
    const current = root.children[index];
    if (!current) return false;
    const template = document.createElement("template");
    template.innerHTML = html.trim();
    const next = template.content.firstElementChild;
    if (!next) return false;
    current.replaceWith(next);
    return true;
  }

  function localFingerprint(value, omitFrames) {
    const local = {};
    for (const key of Object.keys(value || {})) {
      if (key === "children" || (omitFrames && key === "_frames")) continue;
      local[key] = value[key];
    }
    return JSON.stringify(local);
  }

  function snapshotSection(section) {
    const nodes = new Map();
    const sectionFree = !!(section && section.frame && section.frame.layout === "free");
    const roots = Array.isArray(section && section.children) ? section.children : [];
    function visit(node, parentFree, parentFrame, depth) {
      if (!node || typeof node !== "object" || !node.__path) return;
      const children = Array.isArray(node.children) ? node.children : [];
      const childPaths = children.map((child) => child && child.__path || "");
      nodes.set(node.__path, {
        fingerprint: localFingerprint(node, false),
        childPaths,
        node,
        parentFree,
        parentFrame,
        depth,
      });
      const childParentFree = !!(node.frame && node.frame.layout === "free");
      children.forEach((child) => visit(child, childParentFree, node.frame, depth + 1));
    }
    roots.forEach((node) => visit(node, sectionFree, section && section.frame, 0));
    return {
      fingerprint: localFingerprint(section, true),
      frameFingerprint: JSON.stringify(section && section._frames || null),
      childPaths: roots.map((child) => child && child.__path || ""),
      nodes,
    };
  }

  function planNodePatches(before, after) {
    if (!before || !after || before.fingerprint !== after.fingerprint ||
      before.frameFingerprint !== after.frameFingerprint || after.frameFingerprint !== "null") return null;
    const patches = [];
    function walk(beforePaths, afterPaths, parentPath) {
      if (beforePaths.length !== afterPaths.length ||
        beforePaths.some((path, index) => path !== afterPaths[index])) {
        if (!parentPath || !after.nodes.has(parentPath)) return false;
        patches.push(after.nodes.get(parentPath));
        return true;
      }
      for (let index = 0; index < afterPaths.length; index += 1) {
        const path = afterPaths[index];
        const oldNode = before.nodes.get(path);
        const nextNode = after.nodes.get(path);
        if (!path || !oldNode || !nextNode) {
          if (!parentPath || !after.nodes.has(parentPath)) return false;
          patches.push(after.nodes.get(parentPath));
          return true;
        }
        if (oldNode.fingerprint !== nextNode.fingerprint) {
          patches.push(nextNode);
          continue;
        }
        if (!walk(oldNode.childPaths, nextNode.childPaths, path)) return false;
      }
      return true;
    }
    return walk(before.childPaths, after.childPaths, null) ? patches : null;
  }

  function renderedNodeAt(sectionElement, path) {
    for (const element of sectionElement.querySelectorAll("[data-ir-path]")) {
      if (element.dataset.irPath === path) return element;
    }
    return null;
  }

  function replaceRenderedNode(sectionElement, entry, uid) {
    const current = renderedNodeAt(sectionElement, entry.node.__path);
    if (!current) return false;
    const template = document.createElement("template");
    template.innerHTML = renderElement(entry.node, uid, entry.parentFree, entry.parentFrame).trim();
    const next = template.content.firstElementChild;
    if (!next) return false;
    current.replaceWith(next);
    return true;
  }

  /* Глубокий клон IR на каждый рендер. Именно JSON-раундтрип, не structuredClone:
   * JSON выбрасывает ключи со значением undefined, а геометрия (constraints,
   * z-order, группы) различает «ключа нет» и «ключ есть, но undefined» —
   * structuredClone ломал эти проверки (ui_p2_test). */
  const cloneIr = (value) => JSON.parse(JSON.stringify(value));

  /* Шрифты источника, чью загрузку document.fonts уже подтвердил: повторный
   * load на каждый ререндер — лишние промисы и шум в консоли. */
  const confirmedFontSpecs = new Set<string>();
  let lastFontFacesCss = "";

  function materializeResponsiveIR(source, viewport) {
    if (!source || !source.responsive || !source.responsive.viewports) return source;
    (source.tree || []).forEach(sec => annotatePaths(sec, "", false));
    return materializeResponsiveInPlace(cloneIr(source), viewport);
  }

  /* Вариант для IR, уже принадлежащего рендереру (клон из renderIR):
   * viewport-мутации применяются на месте, без повторного глубокого клона. */
  function materializeResponsiveInPlace(ir, viewport) {
    const meta = ir.responsive.viewports[viewport] || ir.responsive.viewports.desktop;
    if (meta) {
      // Page compositions use height:"hug" so the common artboard follows all
      // rendered sections. Viewport metadata still carries a numeric export
      // height, but must not turn the editable auto-height artboard back into a
      // fixed 900/1024/844px crop.
      const autoHeight = ir.frame && ir.frame.height === "hug";
      const viewportFrame = { width: meta.width };
      if (!autoHeight && Number.isFinite(meta.height)) viewportFrame.height = meta.height;
      ir.frame = Object.assign({}, ir.frame || {}, viewportFrame);
    }
    function resolveNode(node) {
      if (!node || typeof node !== "object") return node;
      const override = node.responsive && node.responsive[viewport];
      if (override && override.visible === false) node.__responsiveHidden = true;
      if (override && override.frame) node.frame = Object.assign({}, node.frame || {}, override.frame);
      if (override && override.style) node.style = Object.assign({}, node.style || {}, override.style);
      if (override && typeof override.src === "string") node.src = override.src;
      if (Array.isArray(node.children)) node.children = node.children.map(resolveNode);
      return node;
    }
    ir.tree = (ir.tree || []).map(resolveNode);
    if (meta && meta.preview && ir.tree[0]) {
      ir.sourcePreview = meta.preview;
      ir.tree[0].preview = meta.preview;
    }
    return ir;
  }

  /** Рендерит IR в container (внутри .preview-clip). Масштабирует под ширину контейнера. */
  function renderIR(container, ir, options) {
    const startedAt = nowMs();
    // работаем на глубокой копии: mergeDefaults/__path/sourcePreview — рантайм-данные,
    // они не должны протекать в канонический IR вызывающего (editor.buildActiveIR
    // передаёт state.ir напрямую)
    if (ir) ir = cloneIr(ir);
    const responsiveSource = !!(ir && ir.responsive && ir.responsive.viewports);
    // приватная копия принадлежит рендереру: annotate + viewport-мутации на месте,
    // второй deep clone не нужен (внешние клиенты materializeResponsiveIR
    // по-прежнему получают защитный клон)
    if (responsiveSource) {
      (ir.tree || []).forEach((sec) => annotatePaths(sec, "", false));
      ir = materializeResponsiveInPlace(ir, options && options.viewport ? options.viewport : "desktop");
    }
    const cached = renderStates.get(container);
    const incremental = !!(options && options.incremental);
    const reuseCachedRoot = incremental && cachedRenderIsLive(container, cached);
    const uid = reuseCachedRoot ? cached.uid : ++uidCounter;
    const tokens = (ir.tokens = mergeDefaults(ir.tokens));
    const tree = ir.tree || [];

    let styleEl = document.getElementById("ir-fonts");
    if (!styleEl) {
      styleEl = document.createElement("link");
      styleEl.id = "ir-fonts";
      styleEl.rel = "stylesheet";
      document.head.appendChild(styleEl);
    }
    // offline-рендер (timeline_render.py) детерминирован: шрифты берутся только
    // из локальных @font-face ниже, внешний каталог не запрашивается вовсе
    const offline = !!(options && options.offline);
    const href = tokens.font && !offline ? fontsUrl(tokens, ir) : "";
    if (href && styleEl.getAttribute("href") !== href) styleEl.setAttribute("href", href);
    else if (!href && styleEl.hasAttribute("href")) styleEl.removeAttribute("href");

    // кастомные шрифты источника (база /fonts из Source Import): инжект
    // @font-face + preload, чтобы метрики текста совпали с исходным сайтом
    const requestedFaces = Array.isArray(ir.meta && ir.meta.fontFaces) ? ir.meta.fontFaces : [];
    const customFaces = requestedFaces.filter((face) => {
      if (!face || typeof face !== "object") return false;
      const family = String(face.family || "");
      const weight = String(face.weight || "");
      const style = String(face.style || "");
      const url = String(face.url || "");
      const unicodeRange = String(face.unicodeRange || "");
      return /^[A-Za-z0-9 ._-]{1,80}$/.test(family) &&
        /^(?:[1-9]00(?: [1-9]00)?|normal|bold)$/.test(weight) &&
        /^(?:normal|italic|oblique)$/.test(style) &&
        /^\/fonts\/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(url) &&
        (!unicodeRange || /^[Uu+0-9A-Fa-f? ,\-]{1,2048}$/.test(unicodeRange));
    });
    let ffEl = document.getElementById("ir-fontfaces");
    if (!ffEl) {
      ffEl = document.createElement("style");
      ffEl.id = "ir-fontfaces";
      document.head.appendChild(ffEl);
    }
    const fontFacesCss = customFaces.map((f) => {
      const rawUrl = String(f.url);
      const format = /\.woff2$/i.test(rawUrl) ? "woff2" : /\.woff$/i.test(rawUrl) ? "woff" : "truetype";
      const unicode = f.unicodeRange ? "unicode-range:" + String(f.unicodeRange) + ";" : "";
      // Desktop: рендерер живёт на file://, корневой '/fonts/...' резолвится в
      // корень файловой системы. Привилегированная схема ddna://fonts отдаёт
      // захваченные шрифты из userData/main-процесса с CORS-заголовком.
      const isDesktop = typeof window !== "undefined" && !!(window as any).designDNA;
      const url = isDesktop && rawUrl.startsWith("/fonts/") ? "ddna://" + rawUrl.slice(1) : rawUrl;
      return "@font-face{font-family:'" + String(f.family) + "';" +
        "font-style:" + String(f.style) + ";font-weight:" + String(f.weight) + ";" +
        unicode + "src:url('" + url + "') format('" + format + "');font-display:swap;}";
    }).join("\n");
    // Перезапись <style> при том же тексте заставляет браузер перечитать все
    // @font-face — на каждую правку в редакторе. Меняем только при отличии.
    if (fontFacesCss !== lastFontFacesCss) {
      ffEl.textContent = fontFacesCss;
      lastFontFacesCss = fontFacesCss;
    }
    const unconfirmedFaces = customFaces.filter((f) => {
      const w = parseInt(String(f.weight), 10) || 400;
      return !confirmedFontSpecs.has(w + ' 16px "' + f.family + '"');
    });
    if (unconfirmedFaces.length) {
      try {
        // Загрузку подтверждаем, а не выстреливаем вслепую: молчаливый отказ
        // (404 протокола, битый файл) раньше выглядел как «шрифт не применился»
        // без единого следа в логах.
        const pending = unconfirmedFaces.map((f) => {
          const w = parseInt(String(f.weight), 10) || 400;
          const spec = w + ' 16px "' + f.family + '"';
          return document.fonts.load(spec).then((faces) => ({ spec, ok: faces.length > 0 }))
            .catch((error) => ({ spec, ok: false, error: String(error && error.message || error) }));
        });
        void Promise.all(pending).then((results) => {
          for (const r of results) if (r.ok) confirmedFontSpecs.add(r.spec);
          const failed = results.filter((r) => !r.ok);
          if (failed.length) {
            console.error("[ir] source fonts failed to load: " +
              failed.map((r) => r.spec + (r.error ? " — " + r.error : "")).join("; "));
          }
        });
      } catch (_) { /* preload — best effort */ }
    }
    if (requestedFaces.length && !customFaces.length) {
      console.error("[ir] every captured font face was rejected by validation: " +
        JSON.stringify(requestedFaces.slice(0, 3)));
    }

    // артборд: корневой frame задаёт ширину холста и (опционально) free-позиционирование секций
    // Source Import IR created before the root-frame contract may still live in
    // saved graphs/localStorage. Infer its artboard from the only measured
    // source section so old nodes render correctly without re-importing.
    const legacySourceFrame = tree.length === 1 && tree[0] &&
      (tree[0].type === "source-block" || tree[0].variant === "dom-capture") &&
      tree[0].frame && typeof tree[0].frame === "object" ? tree[0].frame : null;
    const rootFrame = ir.frame && typeof ir.frame === "object" ? ir.frame : legacySourceFrame;
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
    const rootSourcePreview = ir.sourcePreview || (ir.meta && ir.meta.sourcePreview);
    const sections = tree.map((sec, i) => {
      if (rootSourcePreview && sec &&
        (sec.type === "source-block" || sec.variant === "dom-capture") &&
        !sec.preview && !sec.sourcePreview && !(sec.props && sec.props.sourcePreview)) {
        sec.props = Object.assign({}, sec.props || {}, { sourcePreview: rootSourcePreview });
      }
      annotatePaths(sec, "", responsiveSource);
      // помечаем корневой тег секции её индексом — нужно редактору для точной записи в IR
      return renderSection(sec, uid, rootFree).replace(/^<(\w+)/, `<$1 data-ir-sec="${i}"`);
    });
    const body = sections.join("");
    // _frames are applied after HTML generation, so include them explicitly in
    // the diff. Replacing that section also clears obsolete inline overrides.
    const sectionFingerprints = sections.map((html, index) =>
      html + "\u0000" + JSON.stringify(tree[index] && tree[index]._frames || null));
    const sectionSnapshots = tree.map(snapshotSection);

    // Класс вьюпорта — из ЯВНО запрошенного режима (редактор передаёт
    // options.viewport). Вывод из ширины артборда ломал редактор: дефолтный
    // холст 960px (DESIGN_WIDTH) всегда получал ir-tablet и tablet-рефлоу
    // (sec-free -> column gap:28, absolute -> flow) — геометрия, eq-метки и
    // marquee расходились с IR. Ширина остаётся fallback'ом для превью-миниатюр
    // без явного viewport.
    const vpName = (options && options.viewport) ||
      (artW <= 639 ? "mobile" : artW <= 1023 ? "tablet" : "desktop");
    const viewportClass = "ir-" + vpName;
    const rootStyle = artStyle.join(";");
    let inner = null;
    let mode = "full";
    let patchedSections = sections.length;
    let patchedNodes = 0;
    const canPatch = reuseCachedRoot && cached.sectionFingerprints && cached.sectionSnapshots &&
      cached.sections.length === sections.length &&
      cached.rootEl.children.length === sections.length;

    if (canPatch) {
      const changed = [];
      let replaceFailed = false;
      if (cached.css !== css) cached.styleEl.textContent = css;
      cached.rootEl.className = `ir-${uid} ${viewportClass}`;
      cached.rootEl.dataset.designWidth = String(artW);
      if (cached.rootStyle !== rootStyle) cached.rootEl.style.cssText = rootStyle;
      for (let i = 0; i < sections.length; i += 1) {
        if (cached.sectionFingerprints[i] === sectionFingerprints[i]) continue;
        const nodePatches = planNodePatches(cached.sectionSnapshots[i], sectionSnapshots[i]);
        if (nodePatches && nodePatches.length) {
          const sectionElement = cached.rootEl.children[i];
          let nodePatchFailed = false;
          for (const entry of nodePatches) {
            if (!replaceRenderedNode(sectionElement, entry, uid)) {
              nodePatchFailed = true;
              break;
            }
          }
          if (!nodePatchFailed) {
            patchedNodes += nodePatches.length;
            continue;
          }
        }
        if (!replaceRenderedSection(cached.rootEl, i, sections[i])) {
          replaceFailed = true;
          break;
        }
        changed.push(i);
      }
      if (!replaceFailed) {
        inner = cached.rootEl;
        mode = "incremental";
        patchedSections = changed.length;
        if (changed.length) applyFrameOverrides(container, tree, new Set(changed));
      }
    }

    if (!inner) {
      patchedNodes = 0;
      container.innerHTML = `<style>${css}</style><div class="ir-${uid} ${viewportClass}" data-design-width="${artW}" style="${rootStyle}">${body}</div>`;
      inner = container.firstElementChild ? container.querySelector(".ir-" + uid) : null;
      applyFrameOverrides(container, tree);
    }

    const containerStyle = container.firstElementChild;
    const stats = {
      mode,
      patchedSections,
      patchedNodes,
      totalSections: sections.length,
      durationMs: nowMs() - startedAt,
    };
    renderStates.set(container, {
      uid,
      styleEl: containerStyle,
      rootEl: inner,
      css,
      rootStyle,
      sections,
      sectionFingerprints,
      sectionSnapshots,
      stats,
    });
    // fitPreview сжимает артборд под ширину контейнера — нужно только в превью нод;
    // DNA-редактор управляет масштабом сам (zoom/pan), двойной scale ломал геометрию
    if (!options || options.fit !== false) requestAnimationFrame(() => fitPreview(container, inner));
    return stats;
  }

  /** Применяет sec._frames (frame-оверрайды props-элементов) как inline-стили.
   *  Раньше это делал только полноэкранный редактор — теперь и нода Edit, и превью. */
  function applyFrameOverrides(container, tree, sectionIndexes) {
    (tree || []).forEach((sec, si) => {
      if (sectionIndexes && !sectionIndexes.has(si)) return;
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

  function getRenderStats(container) {
    const cached = renderStates.get(container);
    return cached && cached.stats ? Object.assign({}, cached.stats) : null;
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

  /** Проставляет __path элементам children для редактирования.
   *  Source Import sections (source-block/dom-capture) carry stable sourceKeys,
   *  so their layers use the sourceKey as the editable identity; generated/AI
   *  sections fall back to the tree index path — even for nodes that gained a
   *  sourceKey later (editor-created "geo-"/"manual:" keys), because the editor
   *  structural machinery (numeric sibling addressing) is built on index paths. */
  function annotatePaths(sec, prefix, preserve) {
    prefix = prefix || "";
    const sourceSec = !!sec && (sec.type === "source-block" || sec.variant === "dom-capture");
    (sec.children || []).forEach((el, i) => {
      if (!preserve || !el.__path) el.__path = (sourceSec && el.sourceKey) || `${prefix}children.${i}`;
      annotatePathsEl(el, el.__path, preserve, sourceSec);
    });
  }
  function annotatePathsEl(el, path, preserve, sourceSec) {
    (el.children || []).forEach((c, i) => {
      if (!preserve || !c.__path) c.__path = (sourceSec && c.sourceKey) || `${path}.children.${i}`;
      annotatePathsEl(c, c.__path, preserve, sourceSec);
    });
  }

export const IRRenderer = { renderIR, materializeResponsiveIR, fitPreview, getRenderStats, DESIGN_WIDTH };

/** Чистые строковые инструменты рендерера для headless regression-тестов
 *  (frontend/tests/engine.regression.test.mjs) — без DOM. */
export const IRRendererTest = { baseCss, frameCss, withFrame, renderElement, visualCss };
