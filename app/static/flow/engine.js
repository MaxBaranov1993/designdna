var DesignAIEngine = function(exports) {
  "use strict";var __defProp = Object.defineProperty;
var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: true, configurable: true, writable: true, value }) : obj[key] = value;
var __publicField = (obj, key, value) => __defNormalProp(obj, typeof key !== "symbol" ? key + "" : key, value);

  function scenesOf(data) {
    var _a;
    const scenes = Array.isArray((_a = data.motion) == null ? void 0 : _a.scenes) ? data.motion.scenes : [];
    let start = 0;
    return scenes.map((scene) => {
      var _a2;
      const settings = ((_a2 = data.sceneSettings) == null ? void 0 : _a2[scene.interactionSceneId]) || {};
      const duration = Math.max(250, Math.min(3e4, Number(settings.duration || scene.duration)));
      const type = settings.transition || scene.transition.type;
      const transition = {
        type,
        easing: settings.easing || scene.transition.easing,
        duration: type === "cut" ? 0 : Math.max(100, Math.min(duration, Number(settings.transitionDuration || scene.transition.duration || 300)))
      };
      const next = { ...scene, start, duration, transition };
      start += duration;
      return next;
    });
  }
  function smoothstepU(u) {
    return u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2;
  }
  function interpProp(keys, lt, dims, mode = "linear") {
    if (!keys.length) return dims === 2 ? [960, 540] : 0;
    if (lt <= keys[0].t) return keys[0].v;
    if (lt >= keys[keys.length - 1].t) return keys[keys.length - 1].v;
    let i = 0;
    for (let j = 0; j < keys.length - 1; j++) if (lt >= keys[j].t && lt < keys[j + 1].t) i = j;
    const a = keys[i];
    const b = keys[i + 1];
    let u = (lt - a.t) / Math.max(1, b.t - a.t);
    if (mode !== "linear") u = smoothstepU(u);
    if (dims === 2) {
      const av = a.v;
      const bv = b.v;
      return [av[0] + (bv[0] - av[0]) * u, av[1] + (bv[1] - av[1]) * u];
    }
    return a.v + (b.v - a.v) * u;
  }
  function layerVals(layer, lt, mode = "linear") {
    return {
      p: interpProp(layer.props.p.keys, lt, 2, mode),
      s: layer.props.s.keys.length ? interpProp(layer.props.s.keys, lt, 1, mode) : 1,
      r: interpProp(layer.props.r.keys, lt, 1, mode),
      o: layer.props.o.keys.length ? interpProp(layer.props.o.keys, lt, 1, mode) : 1
    };
  }
  const COMP_CARD_STYLE = "display:inline-block;max-width:100%;padding:0.55em 1.4em;border-radius:0.5em;background:#222;border:1px solid #444;color:#eee;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;box-shadow:0 10px 30px rgba(0,0,0,0.28)";
  function compositionFrame(data, layers, time) {
    var _a, _b, _c, _d, _e, _f;
    const scenes = scenesOf(data);
    const index = scenes.findIndex((s, i) => time >= s.start && (time < s.start + s.duration || i === scenes.length - 1));
    const scene = scenes[index];
    if (!scene) return [];
    const local = Math.max(0, Math.min(time - scene.start, scene.duration));
    const transition = scene.transition;
    let progress = index > 0 && transition.duration > 0 ? Math.min(1, local / transition.duration) : 1;
    if (transition.easing === "ease-in") progress *= progress;
    else if (transition.easing === "ease-out") progress = 1 - (1 - progress) ** 2;
    else if (["ease", "ease-in-out"].includes(transition.easing)) progress = progress * progress * (3 - 2 * progress);
    const visible = progress < 1 && transition.type !== "cut" ? [scenes[index - 1], scene] : [scene];
    const width = Number(((_a = data.composition) == null ? void 0 : _a.width) || ((_c = (_b = data.motion) == null ? void 0 : _b.composition) == null ? void 0 : _c.width) || 1920);
    const height = Number(((_d = data.composition) == null ? void 0 : _d.height) || ((_f = (_e = data.motion) == null ? void 0 : _e.composition) == null ? void 0 : _f.height) || 1080);
    return visible.flatMap((current) => {
      const isCurrent = current.id === scene.id;
      const local2 = Math.max(0, Math.min(time - current.start, current.duration));
      const easing = current.transition.easing;
      return layers.filter((layer) => {
        var _a2;
        return (layer.sceneId ?? ((_a2 = scenes[0]) == null ? void 0 : _a2.id)) === current.id;
      }).map((layer) => {
        const values = layerVals(layer, local2, easing === "linear" ? "linear" : "smoothstep");
        if (progress < 1) {
          if (transition.type === "fade" || transition.type === "zoom") values.o *= isCurrent ? progress : 1 - progress;
          if (transition.type === "slide-left") values.p = [values.p[0] + width * (isCurrent ? 1 - progress : -progress), values.p[1]];
          if (transition.type === "slide-up") values.p = [values.p[0], values.p[1] + height * (isCurrent ? 1 - progress : -progress)];
          if (transition.type === "zoom") {
            const scale = isCurrent ? 0.92 + 0.08 * progress : 1 + 0.04 * progress;
            values.p = [(values.p[0] - width / 2) * scale + width / 2, (values.p[1] - height / 2) * scale + height / 2];
            values.s *= scale;
          }
        }
        return { layer, values };
      });
    });
  }
  async function mountComposition(host, data, layers) {
    host.style.background = "#fff";
    host.style.fontFamily = 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
    const elements = /* @__PURE__ */ new Map();
    const images = [];
    for (const layer of layers) {
      const el = document.createElement("div");
      el.style.cssText = "position:absolute;text-align:center;line-height:1.08;letter-spacing:-0.02em;display:none";
      if (layer.type === "image") {
        const img = document.createElement("img");
        img.style.cssText = "display:block;width:100%;aspect-ratio:3/2;border-radius:18px;object-fit:contain";
        img.src = layer.src || "";
        images.push(img.decode());
        el.appendChild(img);
      } else {
        if (layer.type === "comp") {
          const card = document.createElement("span");
          card.style.cssText = COMP_CARD_STYLE;
          card.textContent = layer.name;
          el.appendChild(card);
        } else el.textContent = layer.text || "";
      }
      host.appendChild(el);
      elements.set(layer.id, el);
    }
    await Promise.all(images);
    return (time) => {
      for (const el of elements.values()) el.style.display = "none";
      let zIndex = 0;
      for (const { layer, values: v } of compositionFrame(data, layers, time)) {
        const el = elements.get(layer.id);
        Object.assign(el.style, {
          zIndex: String(zIndex++),
          display: "block",
          left: `${v.p[0]}px`,
          top: `${v.p[1]}px`,
          width: `${layer.w}px`,
          transform: `translate(-50%,-50%) scale(${v.s}) rotate(${v.r}deg)`,
          opacity: String(v.o),
          fontSize: `${layer.size}px`,
          fontWeight: String(layer.weight),
          color: layer.color
        });
      }
    };
  }
  const MotionComposition = /* @__PURE__ */ Object.freeze(/* @__PURE__ */ Object.defineProperty({
    __proto__: null,
    COMP_CARD_STYLE,
    compositionFrame,
    mountComposition
  }, Symbol.toStringTag, { value: "Module" }));
  const groups = [
    { label: "Sans", fonts: [
      "Inter",
      "Roboto",
      "Open Sans",
      "Lato",
      "Montserrat",
      "Poppins",
      "Nunito",
      "Raleway",
      "Source Sans 3",
      "Work Sans",
      "DM Sans",
      "Manrope",
      "Sora",
      "Space Grotesk",
      "Plus Jakarta Sans",
      "Urbanist",
      "Outfit",
      "Rubik",
      "Mulish",
      "Noto Sans",
      "Noto Sans Display",
      "Noto Sans JP",
      "Noto Sans KR",
      "Noto Sans SC",
      "Noto Sans Thai",
      "PT Sans",
      "Ubuntu",
      "Fira Sans",
      "Barlow",
      "Karla",
      "Cabin",
      "Hind",
      "Heebo",
      "IBM Plex Sans",
      "Alegreya Sans",
      "Exo 2",
      "Josefin Sans",
      "Quicksand",
      "Titillium Web",
      // пары typography.py (кириллица): без записи в каталоге семейство не грузится
      "Golos Text",
      "Tenor Sans",
      "Commissioner",
      "Poiret One"
    ] },
    { label: "Serif", fonts: [
      "Merriweather",
      "Playfair Display",
      "Lora",
      "Libre Baskerville",
      "Cormorant Garamond",
      "EB Garamond",
      "Crimson Text",
      "Bitter",
      "Source Serif 4",
      "Noto Serif",
      "Noto Serif Display",
      "PT Serif",
      "Alegreya",
      "Spectral",
      "Fraunces",
      "Prata",
      "Libre Bodoni",
      "DM Serif Display",
      "Vollkorn",
      "Cardo",
      "IBM Plex Serif",
      "Roboto Slab",
      "Literata",
      "Yeseva One",
      "Newsreader"
    ] },
    { label: "Mono", fonts: [
      "Roboto Mono",
      "Source Code Pro",
      "IBM Plex Mono",
      "JetBrains Mono",
      "Fira Code",
      "Fira Mono",
      "Space Mono",
      "DM Mono",
      "Inconsolata",
      "Ubuntu Mono",
      "Noto Sans Mono",
      "Red Hat Mono",
      "Azeret Mono"
    ] },
    { label: "Display", fonts: [
      "Bebas Neue",
      "Oswald",
      "Anton",
      "Archivo Black",
      "League Spartan",
      "Bungee",
      "Righteous",
      "Cinzel",
      "Abril Fatface",
      "Alfa Slab One",
      "Bodoni Moda",
      "Unbounded",
      "Russo One",
      "Teko",
      "Chakra Petch",
      "Orbitron",
      "Michroma",
      "Syne",
      "Clash Display",
      "Cormorant Infant"
    ] },
    { label: "Handwriting", fonts: [
      "Pacifico",
      "Caveat",
      "Dancing Script",
      "Lobster",
      "Comforter",
      "Marck Script",
      "Bad Script",
      "Shadows Into Light",
      "Permanent Marker",
      "Indie Flower",
      "Amatic SC",
      "Neucha"
    ] },
    { label: "System", provider: "system", fonts: [
      "Arial",
      "Helvetica",
      "Verdana",
      "Tahoma",
      "Trebuchet MS",
      "Georgia",
      "Times New Roman",
      "Courier New",
      "Segoe UI",
      "SF Pro Display",
      "SF Pro Text"
    ] }
  ];
  const googleFamilies = new Set(groups.filter((g) => g.provider !== "system").flatMap((g) => g.fonts));
  const systemFamilies = new Set(groups.filter((g) => g.provider === "system").flatMap((g) => g.fonts));
  const families = groups.flatMap((g) => g.fonts);
  const DesignAIFontCatalog = {
    groups,
    families,
    googleFamilies,
    systemFamilies,
    isGoogleFamily(name) {
      return googleFamilies.has(String(name || "").trim());
    },
    isSystemFamily(name) {
      return systemFamilies.has(String(name || "").trim());
    }
  };
  function isLockedNode(node) {
    return !!node && typeof node === "object" && node.editable === false;
  }
  function lockedReason(node) {
    if (!isLockedNode(node)) return "";
    return String(node.lockedReason || "intrinsically non-editable surface");
  }
  const DESIGN_WIDTH = 960;
  const DEFAULT_TOKENS = {
    mode: "light",
    color: { primary: "#5B5BD6", background: "#ffffff", surface: "#f5f5f7", text: "#1a1a1a", textMuted: "#666666", border: "#e0e0e0" },
    font: { display: { family: "Inter", weight: 700 }, body: { family: "Inter", weight: 400 }, scale: "default" },
    radius: { card: "md", button: "md", input: "md" },
    spacing: { section: "md", container: "default" },
    shadow: "sm"
  };
  function mergeDefaults(tokens) {
    const out = JSON.parse(JSON.stringify(DEFAULT_TOKENS));
    if (!tokens || typeof tokens !== "object") return out;
    for (const k of Object.keys(tokens)) {
      if (tokens[k] && typeof tokens[k] === "object" && !Array.isArray(tokens[k]) && out[k] && typeof out[k] === "object") {
        Object.assign(out[k], tokens[k]);
        if (k === "font") {
          for (const f of ["display", "body"]) if (tokens.font[f]) Object.assign(out.font[f], tokens.font[f]);
        }
        if (k === "color") {
          for (const c of Object.keys(tokens.color)) if (tokens.color[c]) out.color[c] = tokens.color[c];
        }
      } else if (tokens[k] !== void 0) {
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
    lg: "0 18px 50px rgba(0,0,0,.24)"
  };
  const TYPE_SCALE = { compact: 0.9, default: 1, spacious: 1.1 };
  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function safeColor(v) {
    const s = String(v == null ? "" : v).trim();
    if (/^#[0-9a-fA-F]{3,8}$/.test(s)) return s;
    if (/^rgba?\(\s*[\d.]+\s*,\s*[\d.]+%?\s*,\s*[\d.]+%?\s*(?:,\s*[\d.]+\s*)?\)$/.test(s)) return s;
    if (/^hsla?\(\s*[\d.]+\s*,\s*[\d.]+%\s*,\s*[\d.]+%\s*(?:,\s*[\d.]+\s*)?\)$/.test(s)) return s;
    return null;
  }
  function safeFontStack(v) {
    const GENERIC = /* @__PURE__ */ new Set([
      "serif",
      "sans-serif",
      "monospace",
      "cursive",
      "fantasy",
      "system-ui",
      "ui-serif",
      "ui-sans-serif",
      "ui-monospace",
      "ui-rounded",
      "math",
      "emoji",
      "fangsong"
    ]);
    const parts = String(v == null ? "" : v).split(",").map((p) => p.replace(/["']/g, "").trim()).filter(Boolean);
    const out = [];
    for (const p of parts.slice(0, 8)) {
      if (!p || p.length > 60 || !/^[\p{L}\p{N}\s._-]+$/u.test(p)) continue;
      out.push(GENERIC.has(p) ? p : `'${p}'`);
    }
    if (!out.length) return "";
    if (!out.some((name) => GENERIC.has(name.replace(/'/g, "")))) out.push("sans-serif");
    return out.join(",");
  }
  function safeFontFamily(v) {
    return safeFontStack(v).split(",")[0].replace(/'/g, "") || "Inter";
  }
  function safeAlign(v) {
    return ["left", "center", "right", "justify", "start", "end"].includes(v) ? v : null;
  }
  function visualCss(style) {
    if (!style || typeof style !== "object") return "";
    const s = [];
    const color = safeColor(style.color);
    if (color) s.push(`color:${color}`);
    const bg = safeColor(style.background);
    if (bg) s.push(`background:${bg}`);
    const border = safeColor(style.borderColor);
    if (border) s.push(`border-color:${border}`);
    const bw = Number(style.borderWidth);
    if (Number.isFinite(bw) && bw >= 0 && bw <= 64) s.push(`border-style:solid`, `border-width:${bw}px`);
    const family = style.fontFamily ? safeFontStack(style.fontFamily) : "";
    if (family) s.push(`font-family:${family}`);
    const fs = Number(style.fontSize);
    if (Number.isFinite(fs) && fs >= 1 && fs <= 512) s.push(`font-size:${fs}px`);
    const fw = Number(style.fontWeight);
    if (Number.isFinite(fw) && fw >= 100 && fw <= 900) s.push(`font-weight:${fw}`);
    const lh = Number(style.lineHeight);
    if (Number.isFinite(lh) && lh >= 0.5 && lh <= 10) s.push(`line-height:${lh}`);
    const ls = Number(style.letterSpacing);
    if (Number.isFinite(ls) && ls >= -20 && ls <= 100) s.push(`letter-spacing:${ls}px`);
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
    const radius = Number(style.borderRadius);
    if (Number.isFinite(radius) && radius >= 0 && radius <= 1e3) s.push(`border-radius:${radius}px`);
    if (typeof style.boxShadow === "string" && style.boxShadow.length <= 300 && !/[;{}<>"'\\\r\n]/.test(style.boxShadow)) s.push(`box-shadow:${style.boxShadow}`);
    if (["none", "underline", "line-through", "overline"].includes(style.textDecoration)) s.push(`text-decoration:${style.textDecoration}`);
    if (["normal", "nowrap", "pre", "pre-wrap", "pre-line", "break-spaces"].includes(style.whiteSpace)) s.push(`white-space:${style.whiteSpace}`);
    if (["auto", "antialiased", "subpixel-antialiased"].includes(style.fontSmoothing)) s.push(`-webkit-font-smoothing:${style.fontSmoothing}`);
    if (["visible", "hidden", "clip", "scroll", "auto"].includes(style.overflow)) s.push(`overflow:${style.overflow}`);
    if (Number(style.flexShrink) === 0) s.push("flex-shrink:0");
    if (["none", "uppercase", "lowercase", "capitalize"].includes(style.textTransform)) s.push(`text-transform:${style.textTransform}`);
    const op = Number(style.opacity);
    if (Number.isFinite(op) && op >= 0 && op <= 1) s.push(`opacity:${op}`);
    if (["contain", "cover", "fill", "none", "scale-down"].includes(style.objectFit)) s.push(`object-fit:${style.objectFit}`);
    if (typeof style.objectPosition === "string" && style.objectPosition.length <= 40 && /^[\d.%\s-]|^(left|center|right|top|bottom)/.test(style.objectPosition)) s.push(`object-position:${style.objectPosition}`);
    if (typeof style.filter === "string" && style.filter.length <= 300 && !/[;{}<>"'\\\r\n]/.test(style.filter) && !/url\s*\(/i.test(style.filter)) s.push(`filter:${style.filter}`);
    if (typeof style.backdropFilter === "string" && style.backdropFilter.length <= 300 && !/[;{}<>"'\\\r\n]/.test(style.backdropFilter) && !/url\s*\(/i.test(style.backdropFilter)) s.push(`backdrop-filter:${style.backdropFilter}`);
    if (typeof style.mixBlendMode === "string" && /^[a-z-]+$/.test(style.mixBlendMode)) s.push(`mix-blend-mode:${style.mixBlendMode}`);
    if (style.direction === "rtl") s.push("direction:rtl");
    if (typeof style.writingMode === "string" && /^(vertical|sideways)-/.test(style.writingMode)) s.push(`writing-mode:${style.writingMode}`);
    const ow = Number(style.outline);
    if (Number.isFinite(ow) && ow > 0 && ow <= 64) s.push(`outline:${ow}px solid ${safeColor(style.outlineColor) || "#808080"}`);
    const bgImg = style.backgroundImage;
    if (typeof bgImg === "string" && bgImg.length <= 800 && !/[;{}<>"'\\\r\n]/.test(bgImg) && !/url\s*\(/i.test(bgImg)) s.push(`background-image:${bgImg}`);
    const mask = style.maskImage;
    if (typeof mask === "string" && mask.length <= 800 && !/[;{}<>"'\\\r\n]/.test(mask) && !/url\s*\(/i.test(mask)) s.push(`mask-image:${mask}`, `-webkit-mask-image:${mask}`);
    const cp = style.clipPath;
    if (typeof cp === "string" && cp.length <= 300 && /^[a-zA-Z0-9\s(),.%#-]+$/.test(cp)) s.push(`clip-path:${cp}`);
    const ts = style.textShadow;
    if (typeof ts === "string" && ts.length <= 300 && !/[;{}<>"'\\\r\n]/.test(ts) && !/url\s*\(/i.test(ts)) s.push(`text-shadow:${ts}`);
    if (style.backgroundClip === "text" && typeof bgImg === "string") {
      s.push("-webkit-background-clip:text", "background-clip:text", "color:transparent");
    }
    return s.join(";");
  }
  function accentChildren(el) {
    const kids = Array.isArray(el.children) ? el.children : [];
    const placed = kids.filter((c) => c && c.type === "text" && c.frame && typeof c.frame.x === "number" && typeof c.frame.y === "number");
    if (!placed.length) return "";
    return placed.map((c) => {
      const css = [
        "position:absolute",
        `left:${c.frame.x}px`,
        `top:${c.frame.y}px`,
        typeof c.frame.width === "number" ? `width:${c.frame.width}px` : "",
        visualCss(c.style)
      ].filter(Boolean).join(";");
      return `<span style="${css}">${esc(c.text || "")}</span>`;
    }).join("");
  }
  function visualTextCss(style) {
    if (!style || typeof style !== "object") return "";
    const s = [];
    const color = safeColor(style.color);
    if (color) s.push(`color:${color}`);
    const family = style.fontFamily ? safeFontStack(style.fontFamily) : "";
    if (family) s.push(`font-family:${family}`);
    const fs = Number(style.fontSize);
    if (Number.isFinite(fs) && fs >= 1 && fs <= 512) s.push(`font-size:${fs}px`);
    const fw = Number(style.fontWeight);
    if (Number.isFinite(fw) && fw >= 100 && fw <= 900) s.push(`font-weight:${fw}`);
    const lh = Number(style.lineHeight);
    if (Number.isFinite(lh) && lh >= 0.5 && lh <= 10) s.push(`line-height:${lh}`);
    const ls = Number(style.letterSpacing);
    if (Number.isFinite(ls) && ls >= -20 && ls <= 100) s.push(`letter-spacing:${ls}px`);
    if (style.fontStyle === "italic" || style.fontStyle === "oblique") s.push(`font-style:${style.fontStyle}`);
    if (style.fontVariantNumeric === "tabular-nums") s.push(`font-variant-numeric:tabular-nums`);
    if (["none", "underline", "line-through", "overline"].includes(style.textDecoration)) s.push(`text-decoration:${style.textDecoration}`);
    if (["none", "uppercase", "lowercase", "capitalize"].includes(style.textTransform)) s.push(`text-transform:${style.textTransform}`);
    const ts = style.textShadow;
    if (typeof ts === "string" && ts.length <= 300 && /^[a-zA-Z0-9\s(),.%#-]+$/.test(ts)) s.push(`text-shadow:${ts}`);
    const bgImage = style.backgroundImage;
    if (style.backgroundClip === "text" && typeof bgImage === "string" && bgImage.length <= 800 && !/url\s*\(|expression/i.test(bgImage)) {
      s.push(
        `background-image:${bgImage}`,
        "-webkit-background-clip:text",
        "background-clip:text",
        "color:transparent"
      );
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
    return true;
  }
  function addFontFamily(fams, family, weight) {
    const name = safeFontFamily(family);
    if (!shouldLoadGoogleFont(name)) return;
    const w = Math.min(900, Math.max(100, Math.round(Number(weight) || 400)));
    fams.add(name.replace(/ /g, "+") + ":wght@" + w);
  }
  function collectStyleFonts(node, fams) {
    if (!node || typeof node !== "object") return;
    if (node.style && node.style.fontFamily) addFontFamily(fams, node.style.fontFamily, node.style.fontWeight);
    if (Array.isArray(node.children)) node.children.forEach((child) => collectStyleFonts(child, fams));
    if (Array.isArray(node.tree)) node.tree.forEach((sec) => collectStyleFonts(sec, fams));
  }
  function fontsUrl(tokens, ir) {
    var _a;
    const fams = /* @__PURE__ */ new Set();
    for (const key of ["display", "body"]) {
      const f = tokens.font && tokens.font[key];
      if (f && f.family) {
        addFontFamily(fams, f.family, f.weight);
      }
    }
    collectStyleFonts(ir, fams);
    const capturedFamilies = new Set((((_a = ir == null ? void 0 : ir.meta) == null ? void 0 : _a.fontFaces) || []).filter((face) => face && typeof face.url === "string" && face.url.startsWith("/fonts/")).map((face) => safeFontFamily(face.family).toLowerCase()));
    for (const spec of fams) {
      const family = String(spec).split(":")[0].replace(/\+/g, " ").toLowerCase();
      if (capturedFamilies.has(family)) fams.delete(spec);
    }
    if (!fams.size) return "";
    return "https://fonts.googleapis.com/css2?" + [...fams].map((f) => "family=" + f).join("&") + "&display=swap";
  }
  const TYPE_ROLES = ["display", "h1", "h2", "h3", "lead", "body", "small", "eyebrow"];
  function typeRoleOf(el) {
    const role = el && typeof el.typeRole === "string" ? el.typeRole : "";
    return TYPE_ROLES.includes(role) ? role : "";
  }
  function styleWithoutTypeOverrides(style) {
    if (!style || typeof style !== "object") return style;
    const { fontSize, fontWeight, lineHeight, letterSpacing, ...rest } = style;
    return rest;
  }
  const MOBILE_TYPE_FACTOR = { display: 0.7, h1: 0.74, h2: 0.87, h3: 0.92 };
  function safeCssValue(v, max) {
    const s = String(v == null ? "" : v).trim();
    if (!s || s.length > (max || 160) || /[;{}<>"'\\\r\n]/.test(s)) return null;
    return s;
  }
  function num(v, min, max) {
    const n = Number(v);
    return Number.isFinite(n) && n >= min && n <= max ? n : null;
  }
  function typeRoleVars(type) {
    const roles = type && type.roles;
    if (!roles || typeof roles !== "object") return "";
    const out = [];
    for (const role of TYPE_ROLES) {
      const r = roles[role];
      if (!r || typeof r !== "object") continue;
      const size = num(r.size, 8, 200);
      if (size == null) continue;
      out.push(`--t-${role}-size:${size}px`);
      const mobile = MOBILE_TYPE_FACTOR[role];
      if (mobile) out.push(`--t-${role}-size-m:${Math.round(size * mobile)}px`);
      const lh = num(r.lineHeight, 0.8, 3);
      if (lh != null) out.push(`--t-${role}-lh:${lh}`);
      const tracking = num(r.tracking, -0.2, 0.5);
      if (tracking != null) out.push(`--t-${role}-tracking:${tracking}em`);
      const weight = num(r.weight, 100, 900);
      if (weight != null) out.push(`--t-${role}-weight:${Math.round(weight)}`);
    }
    return out.join(";");
  }
  function tokensV2Vars(v2) {
    if (!v2 || typeof v2 !== "object") return "";
    const out = [];
    const c = v2.color;
    if (c && typeof c === "object") {
      for (const [role, name] of [
        ["bg2", "bg2"],
        ["surface2", "surface2"],
        ["ink", "ink"],
        ["ink2", "ink2"],
        ["inkMuted", "ink-muted"],
        ["line", "line"],
        ["accentInk", "accent-ink"],
        ["accent2", "accent2"]
      ]) {
        const value = safeColor(c[role]);
        if (value) out.push(`--c-${name}:${value}`);
      }
    }
    out.push(typeRoleVars(v2.type));
    const families2 = v2.type && v2.type.families;
    if (families2 && typeof families2 === "object") {
      for (const [role, name] of [["display", "display"], ["body", "body"]]) {
        const face = families2[role];
        const stack = face && safeFontStack(face.stack || face.family);
        if (stack) out.push(`--font-${name}:${stack}`);
      }
    }
    if (Array.isArray(v2.space)) {
      v2.space.slice(0, 20).forEach((step, i) => {
        const value = num(step, 0, 400);
        if (value != null) out.push(`--space-${i + 1}:${value}px`);
      });
    }
    const radius = v2.radius;
    if (radius && typeof radius === "object") {
      for (const key of ["sm", "md", "lg", "pill"]) {
        const value = num(radius[key], 0, 999);
        if (value != null) out.push(`--r-${key}:${value}px`);
      }
    }
    const shadow = v2.shadow;
    if (shadow && typeof shadow === "object") {
      for (const key of ["sm", "md", "lg"]) {
        const value = safeCssValue(shadow[key], 160);
        if (value) out.push(`--shadow-${key}:${value}`);
      }
    }
    const motion = v2.motion;
    if (motion && typeof motion === "object") {
      const duration = num(motion.durationMs, 0, 2e3);
      const easing = safeCssValue(motion.easing, 60);
      if (duration != null) out.push(`--motion-duration:${Math.round(duration)}ms`);
      if (easing) out.push(`--motion-easing:${easing}`);
    }
    return out.filter(Boolean).join(";");
  }
  function cssVars(tokens) {
    const c = tokens.color, scale = TYPE_SCALE[tokens.font.scale] || 1;
    const d = DEFAULT_TOKENS.color;
    const v2 = tokens.v2 && typeof tokens.v2 === "object" ? tokens.v2 : null;
    const v2c = v2 && v2.color || {};
    const col = (k, fb) => safeColor(c[k]) || fb;
    const role = (k, v1Key, fb) => safeColor(v2c[k]) || col(v1Key, fb);
    const primary = role("accent", "primary", d.primary);
    const fw = (f, fb) => Math.min(900, Math.max(100, Math.round(Number(f && f.weight) || fb)));
    return `
      --c-primary:${primary};--c-secondary:${col("secondary", safeColor(v2c.accent2) || primary)};--c-accent:${col("accent", safeColor(v2c.accent2) || primary)};
      --c-bg:${role("bg", "background", d.background)};--c-surface:${role("surface", "surface", d.surface)};--c-text:${role("ink", "text", d.text)};--c-muted:${role("inkMuted", "textMuted", d.textMuted)};--c-border:${role("line", "border", d.border)};
      --font-display:${safeFontStack(tokens.font.display.family) || "'Inter'"},sans-serif;--font-body:${safeFontStack(tokens.font.body.family) || "'Inter'"},sans-serif;
      --fw-display:${fw(tokens.font.display, 700)};--fw-body:${fw(tokens.font.body, 400)};
      --fs:${scale};
      --r-card:${RADIUS_PX[tokens.radius.card]};--r-btn:${RADIUS_PX[tokens.radius.button]};--r-input:${RADIUS_PX[tokens.radius.input]};
      --sec-py:${SECTION_PY[tokens.spacing.section]};--container:${CONTAINER_W[tokens.spacing.container]};
      --shadow:${SHADOWS[tokens.shadow]};
      ${tokensV2Vars(v2)};
    `;
  }
  function baseCss(uid) {
    return `
      /* Кегли берутся из ролей tokens.v2 (--t-<role>-*); fallback внутри var()
         оставляет прежнюю фиксированную шкалу документам без v2. */
      .ir-${uid} { background:var(--c-bg); color:var(--c-text); font-family:var(--font-body); font-weight:var(--t-body-weight,var(--fw-body));
        font-size:var(--t-body-size, calc(15px * var(--fs))); line-height:var(--t-body-lh,1.6);
        letter-spacing:var(--t-body-tracking,normal); width:${DESIGN_WIDTH}px; transform-origin:top left; }
      .ir-${uid} * { margin:0; padding:0; box-sizing:border-box; }
      .ir-${uid} h1,.ir-${uid} h2,.ir-${uid} h3,.ir-${uid} h4 { font-family:var(--font-display); font-weight:var(--fw-display); line-height:1.15; }
      .ir-${uid} h1 { font-size:var(--t-h1-size, calc(46px * var(--fs))); line-height:var(--t-h1-lh,1.15);
        letter-spacing:var(--t-h1-tracking,-.02em); font-weight:var(--t-h1-weight,var(--fw-display)); }
      .ir-${uid} h2 { font-size:var(--t-h2-size, calc(30px * var(--fs))); line-height:var(--t-h2-lh,1.15);
        letter-spacing:var(--t-h2-tracking,-.01em); font-weight:var(--t-h2-weight,var(--fw-display)); }
      .ir-${uid} h3 { font-size:var(--t-h3-size, calc(20px * var(--fs))); line-height:var(--t-h3-lh,1.15);
        letter-spacing:var(--t-h3-tracking,normal); font-weight:var(--t-h3-weight,var(--fw-display)); }
      .ir-${uid} h4 { font-size:var(--t-lead-size, calc(16px * var(--fs))); }
      /* Роли без своего тега — для свободной композиции и блоков T3. */
      .ir-${uid} .t-display { font-family:var(--font-display); font-size:var(--t-display-size, calc(60px * var(--fs)));
        line-height:var(--t-display-lh,1.02); letter-spacing:var(--t-display-tracking,-.03em); font-weight:var(--t-display-weight,var(--fw-display)); }
      .ir-${uid} .t-lead { font-size:var(--t-lead-size, calc(19px * var(--fs))); line-height:var(--t-lead-lh,1.5);
        letter-spacing:var(--t-lead-tracking,normal); font-weight:var(--t-lead-weight,var(--fw-body)); }
      .ir-${uid} .t-small { font-size:var(--t-small-size, calc(13px * var(--fs))); line-height:var(--t-small-lh,1.5);
        font-weight:var(--t-small-weight,var(--fw-body)); }
      .ir-${uid} .t-eyebrow { font-size:var(--t-eyebrow-size, calc(12px * var(--fs))); line-height:var(--t-eyebrow-lh,1.2);
        letter-spacing:var(--t-eyebrow-tracking,.12em); font-weight:var(--t-eyebrow-weight,600); text-transform:uppercase; }
      /* Текстовые стили (typeRole) на любом теге: роль важнее тега, поэтому
         селекторы идут после h1–h4 и перебивают их по порядку каскада. */
      .ir-${uid} .t-h1 { font-family:var(--font-display); font-size:var(--t-h1-size, calc(46px * var(--fs))); line-height:var(--t-h1-lh,1.15);
        letter-spacing:var(--t-h1-tracking,-.02em); font-weight:var(--t-h1-weight,var(--fw-display)); }
      .ir-${uid} .t-h2 { font-family:var(--font-display); font-size:var(--t-h2-size, calc(30px * var(--fs))); line-height:var(--t-h2-lh,1.15);
        letter-spacing:var(--t-h2-tracking,-.01em); font-weight:var(--t-h2-weight,var(--fw-display)); }
      .ir-${uid} .t-h3 { font-family:var(--font-display); font-size:var(--t-h3-size, calc(20px * var(--fs))); line-height:var(--t-h3-lh,1.15);
        letter-spacing:var(--t-h3-tracking,normal); font-weight:var(--t-h3-weight,var(--fw-display)); }
      .ir-${uid} .t-body { font-family:var(--font-body); font-size:var(--t-body-size, calc(15px * var(--fs))); line-height:var(--t-body-lh,1.6);
        letter-spacing:var(--t-body-tracking,normal); font-weight:var(--t-body-weight,var(--fw-body)); text-transform:none; }
      .ir-${uid} h1.t-display, .ir-${uid} h2.t-display, .ir-${uid} h3.t-display, .ir-${uid} h4.t-display { font-size:var(--t-display-size, calc(60px * var(--fs)));
        line-height:var(--t-display-lh,1.02); letter-spacing:var(--t-display-tracking,-.03em); font-weight:var(--t-display-weight,var(--fw-display)); }
      .ir-${uid} h1.t-lead, .ir-${uid} h2.t-lead, .ir-${uid} h3.t-lead, .ir-${uid} h4.t-lead { font-family:var(--font-body); font-size:var(--t-lead-size, calc(19px * var(--fs)));
        line-height:var(--t-lead-lh,1.5); letter-spacing:var(--t-lead-tracking,normal); font-weight:var(--t-lead-weight,var(--fw-body)); }
      .ir-${uid} h1.t-small, .ir-${uid} h2.t-small, .ir-${uid} h3.t-small, .ir-${uid} h4.t-small { font-family:var(--font-body); font-size:var(--t-small-size, calc(13px * var(--fs)));
        line-height:var(--t-small-lh,1.5); font-weight:var(--t-small-weight,var(--fw-body)); }
      .ir-${uid} h1.t-eyebrow, .ir-${uid} h2.t-eyebrow, .ir-${uid} h3.t-eyebrow, .ir-${uid} h4.t-eyebrow { font-family:var(--font-body); font-size:var(--t-eyebrow-size, calc(12px * var(--fs)));
        line-height:var(--t-eyebrow-lh,1.2); letter-spacing:var(--t-eyebrow-tracking,.12em); font-weight:var(--t-eyebrow-weight,600); text-transform:uppercase; }
      .ir-${uid} .sec, .ir-${uid} .sec-free { padding:var(--sec-py) 32px; position:relative; }
      .ir-${uid} .sec-source { padding:0; position:relative; margin:0; }
      /* Источник объявляет лишние веса поверх одного файла (JetBrains Mono 400/500/600
         → один woff2), браузер там не синтезирует жирность. Захват хранит только
         реальные файлы, поэтому без запрета синтеза 500-й вес рисовался faux-bold
         и каждая подпись расходилась с оригиналом на 1–2px по ширине. */
      .ir-${uid} .sec-source, .ir-${uid} .sec-source * { font-synthesis:none; }
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
        display:flex; align-items:center; justify-content:center; color:var(--c-muted); font-size:13px; line-height:1.5; min-height:180px; padding:16px; text-align:center; }
      .ir-${uid} .img-ph > span { max-width:720px; }
      .ir-${uid} .sec-head { text-align:center; max-width:640px; margin:0 auto 40px; }
      .ir-${uid} .sec-head h2 { margin-bottom:12px; }
      .ir-${uid} .divider { height:1px; background:var(--c-border); margin:16px 0; }
      .ir-${uid} .avatar { width:44px; height:44px; border-radius:50%; background:var(--c-primary); color:#fff;
        display:inline-flex; align-items:center; justify-content:center; font-weight:700; flex:none; }
      .ir-${uid} .stars { color:var(--c-accent); letter-spacing:2px; }
      .ir-${uid} [data-ir-path].editing { outline:2px dashed var(--c-primary); outline-offset:2px; cursor:text; }
      .ir-${uid} [data-ir-locked] { cursor:default; }
      .ir-${uid}.ir-mobile { font-size:var(--t-body-size, calc(16px * var(--fs))); line-height:1.55; }
      .ir-${uid}.ir-mobile h1 { font-size:var(--t-h1-size-m, calc(34px * var(--fs))); line-height:1.08; letter-spacing:-.025em; }
      .ir-${uid}.ir-mobile h2 { font-size:var(--t-h2-size-m, calc(26px * var(--fs))); line-height:1.12; }
      .ir-${uid}.ir-mobile h3 { font-size:var(--t-h3-size-m, calc(20px * var(--fs))); }
      .ir-${uid}.ir-mobile .t-display { font-size:var(--t-display-size-m, calc(42px * var(--fs))); }
      .ir-${uid}.ir-mobile .t-h1 { font-size:var(--t-h1-size-m, calc(34px * var(--fs))); }
      .ir-${uid}.ir-mobile .t-h2 { font-size:var(--t-h2-size-m, calc(26px * var(--fs))); }
      .ir-${uid}.ir-mobile .t-h3 { font-size:var(--t-h3-size-m, calc(20px * var(--fs))); }
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
  const FLEX_JUSTIFY = { start: "flex-start", center: "center", end: "flex-end", "space-between": "space-between", "space-around": "space-around" };
  const FLEX_ALIGN = { start: "flex-start", center: "center", end: "flex-end", stretch: "stretch", baseline: "baseline" };
  function frameCss(f, parentFree, container, parentFrame) {
    if (!f || typeof f !== "object") return "";
    const s = [];
    const pDir = parentFrame && parentFrame.direction === "row" ? "row" : "column";
    const wrappingFill = f.width === "fill" && pDir === "row" && parentFrame && parentFrame.wrap;
    if (typeof f.width === "number") s.push(`width:${f.width}px`);
    else if (f.width === "fill") {
      if (parentFree) s.push("width:100%");
      else if (wrappingFill) {
        const basis = typeof f.minWidth === "number" ? f.minWidth : 220;
        s.push("width:auto", `flex:1 1 ${basis}px`, `min-width:min(100%,${basis}px)`);
      } else if (pDir === "row") s.push("width:100%", "flex:1 1 auto", "min-width:0");
      else s.push("width:100%", "min-width:0");
    } else if (f.width === "hug") s.push("width:fit-content");
    if (typeof f.height === "number") s.push(`height:${f.height}px`);
    else if (f.height === "fill") {
      if (parentFree) s.push("height:100%");
      else if (pDir === "column") s.push("align-self:stretch", "flex-grow:1", "min-height:0");
      else s.push("align-self:stretch", "min-height:0");
    } else if (f.height === "hug") s.push("height:fit-content");
    if (typeof f.minWidth === "number" && !wrappingFill) s.push(`min-width:${f.minWidth}px`);
    if (typeof f.maxWidth === "number") s.push(`max-width:${f.maxWidth}px`);
    if (typeof f.minHeight === "number") s.push(`min-height:${f.minHeight}px`);
    if (typeof f.maxHeight === "number") s.push(`max-height:${f.maxHeight}px`);
    if (f.clip) s.push("overflow:hidden");
    if (typeof f.transform === "string" && f.transform.length <= 300 && !/[;{}<>"'\\\r\n]/.test(f.transform)) s.push(`transform:${f.transform}`);
    else if (typeof f.rotation === "number" && f.rotation) s.push(`transform:rotate(${f.rotation}deg)`);
    const z = Number(f.z);
    if (Number.isInteger(z) && z >= -1e3 && z <= 1e3) s.push(`z-index:${z}`);
    const placed = (parentFree || f.absolute) && (typeof f.x === "number" || typeof f.y === "number");
    if (placed) {
      s.push("position:absolute", `left:${typeof f.x === "number" ? f.x : 0}px`, `top:${typeof f.y === "number" ? f.y : 0}px`);
    }
    if (typeof f.padding === "number") s.push(`padding:${f.padding}px`);
    else if (Array.isArray(f.padding) && f.padding.length === 4) s.push(`padding:${f.padding.map((n) => n + "px").join(" ")}`);
    else if (Array.isArray(f.padding) && f.padding.length === 2) s.push(`padding:${f.padding[0]}px ${f.padding[1]}px`);
    if (container) {
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
  function withFrame(html, frame, parentFree, container, irPath, cls, parentFrame, extraCss) {
    const css = [frameCss(frame, parentFree, container, parentFrame), extraCss || ""].filter(Boolean).join(";");
    if (!css && !cls) return html;
    const pathAttr = irPath ? ` data-ir-path="${esc(irPath)}"` : "";
    const trAttr = frame && typeof frame.transform === "string" && frame.transform ? " data-ir-transform" : "";
    const clsAttr = cls ? ` class="${cls}"` : "";
    return `<div data-ir-frame${pathAttr}${trAttr}${clsAttr} style="${css}">${html}</div>`;
  }
  function transformAttr(frame) {
    return frame && typeof frame.transform === "string" && frame.transform ? " data-ir-transform" : "";
  }
  const ASPECT_RATIO = { "1:1": "1/1", "4:3": "4/3", "16:9": "16/9", "3:4": "3/4", "9:16": "9/16" };
  function renderElement(el, uid, parentFree, parentFrame) {
    if (el && el.__responsiveHidden) return "";
    const irPath = el.__path || null;
    const html = renderElementInner(el, uid, parentFree, parentFrame);
    let out;
    if (el.type === "card" || el.type === "frame" || (el.type === "button" || el.type === "input") && el.children && el.children.length) {
      out = html;
    } else {
      const clipText = (el.type === "text" || el.type === "heading") && el.frame && typeof el.frame.height === "number" ? "overflow:hidden" : "";
      const flexShare = (el.type === "image" || el.type === "heading" || el.type === "text") && !parentFree && parentFrame && parentFrame.layout === "auto" && parentFrame.direction === "row" && !(el.frame && (typeof el.frame.width === "number" || el.frame.width === "hug" || el.frame.width === "fill"));
      const flexImage = flexShare ? el.type === "image" ? "flex:1 1 0;min-width:0" : "flex:1 1 0;min-width:min-content" : "";
      const extra = [clipText, flexImage].filter(Boolean).join(";");
      const wrapped = withFrame(html, el.frame, parentFree, false, irPath, "", parentFrame, extra);
      out = wrapped === html && irPath ? flexImage ? `<div data-ir-path="${esc(irPath)}" style="${flexImage}">${html}</div>` : `<span data-ir-path="${esc(irPath)}" style="display:inline-block">${html}</span>` : wrapped;
    }
    if (isLockedNode(el)) {
      const lock = ` data-ir-locked="${esc(String(el.lockedReason || "locked"))}"`;
      out = out.replace(/^<([a-zA-Z][a-zA-Z0-9]*)/, "<$1" + lock);
    }
    return out;
  }
  function renderElementInner(el, uid, parentFree, parentFrame) {
    switch (el.type) {
      case "heading": {
        const lvl = Math.min(4, Math.max(1, el.level || 2));
        const a = safeAlign(el.align);
        const alignCss = a ? `text-align:${a}` : "";
        const placed = accentChildren(el);
        const role = typeRoleOf(el);
        const style = role ? styleWithoutTypeOverrides(el.style) : el.style;
        const css = [
          visualCss(style),
          alignCss,
          placed ? "position:relative" : "",
          (style == null ? void 0 : style.fontSmoothing) === "antialiased" ? "will-change:opacity" : ""
        ].filter(Boolean).join(";");
        const sa = css ? ` style="${css}"` : "";
        const rc = role ? ` class="t-${role}" data-type-role="${role}"` : "";
        const childText = Array.isArray(el.children) ? el.children.map((c) => c && (c.text || c.title || "")).filter(Boolean).join(" ") : "";
        const own = esc(el.text || el.title || (placed ? "" : childText) || "");
        return `<h${lvl}${rc}${sa}>${own}${placed || ""}</h${lvl}>`;
      }
      case "text": {
        const a = safeAlign(el.align);
        const alignCss = a ? `text-align:${a}` : "";
        const placed = accentChildren(el);
        const role = typeRoleOf(el);
        const style = role ? styleWithoutTypeOverrides(el.style) : el.style;
        const css = [
          visualCss(style),
          alignCss,
          placed ? "position:relative" : "",
          (style == null ? void 0 : style.fontSmoothing) === "antialiased" ? "will-change:opacity" : ""
        ].filter(Boolean).join(";");
        const sa = css ? ` style="${css}"` : "";
        const classes = [];
        if (el.size === "sm" || el.size === "xs") classes.push("muted");
        if (role) classes.push(`t-${role}`);
        const cls = classes.length ? ` class="${classes.join(" ")}"` : "";
        const rd = role ? ` data-type-role="${role}"` : "";
        return `<p${cls}${rd}${sa}>${esc(el.text || "")}${placed || ""}</p>`;
      }
      case "button": {
        const free = el.frame && el.frame.layout === "free";
        const kids = (el.children || []).map((c) => renderElement(c, uid, free, el.frame)).join("");
        if (kids) {
          const fcss = frameCss(el.frame, parentFree, true, parentFrame);
          const css = [fcss, "padding:0", visualCss(el.style)].filter(Boolean).join(";");
          const path2 = el.__path ? ` data-ir-path="${esc(el.__path)}"` : "";
          return `<button type="button" class="source-control"${path2}${transformAttr(el.frame)}${css ? ` style="${css}"` : ""}>${kids}</button>`;
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
          const ratio = ASPECT_RATIO[el.aspect];
          const css = ratio ? ` style="aspect-ratio:${ratio};min-height:0"` : "";
          return `<div class="img-ph"${css}><span>${esc(el.imagePrompt || el.alt || "изображение")}</span></div>`;
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
        return `<ul style="list-style:none;display:flex;flex-direction:column;gap:8px">${(el.items || []).map((i) => `<li style="display:flex;gap:8px;align-items:flex-start"><span style="color:var(--c-primary)">✓</span><span>${esc(i)}</span></li>`).join("")}</ul>`;
      case "input":
        if (el.children && el.children.length) {
          const free = el.frame && el.frame.layout === "free";
          const kids = el.children.map((c) => renderElement(c, uid, free, el.frame)).join("");
          const fcss = frameCss(el.frame, parentFree, true, parentFrame);
          const css = [fcss, "padding:0", visualCss(el.style)].filter(Boolean).join(";");
          const path = el.__path ? ` data-ir-path="${esc(el.__path)}"` : "";
          return `<div class="source-input"${path}${transformAttr(el.frame)}${css ? ` style="${css}"` : ""}>${kids}</div>`;
        }
        if (el.inputType === "textarea") {
          return `<textarea class="input" placeholder="${esc(el.placeholder || el.label || "")}">${esc(el.value ?? "")}</textarea>`;
        }
        if (el.inputType === "select") {
          return `<select class="input" aria-label="${esc(el.label || el.placeholder || "")}">${(el.items || []).map((item) => `<option${String(item) === String(el.value) ? " selected" : ""}>${esc(item)}</option>`).join("")}</select>`;
        }
        return `<input class="input" type="${["text", "search", "email", "tel", "url", "password", "number", "checkbox"].includes(el.inputType) ? el.inputType : "text"}" placeholder="${esc(el.placeholder || el.label || "")}" value="${esc(el.value ?? "")}">`;
      case "frame": {
        const free = el.frame && el.frame.layout === "free";
        const inner = (el.children || []).map((c) => renderElement(c, uid, free, el.frame)).join("");
        const fcss = frameCss(el.frame, parentFree, true, parentFrame);
        const path = el.__path ? ` data-ir-path="${esc(el.__path)}"` : "";
        const css = [fcss, visualCss(el.style)].filter(Boolean).join(";");
        return `<div class="ir-frame"${path}${transformAttr(el.frame)}${css ? ` style="${css}"` : ""}>${inner}</div>`;
      }
      case "card": {
        const free = el.frame && el.frame.layout === "free";
        const inner = (el.children || []).map((c) => renderElement(c, uid, free, el.frame)).join("");
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
    return (name || "?").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  }
  function renderChildren(children, uid, cols, parentFrame) {
    if (!children || !children.length) return "";
    const free = parentFrame && parentFrame.layout === "free";
    const hasAbs = children.some((c) => c.frame && c.frame.absolute);
    const style = free || hasAbs ? ' style="position:relative"' : cols ? ` style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:20px"` : "";
    return `<div${style}>${children.map((c) => renderElement(c, uid, free, parentFrame)).join("")}</div>`;
  }
  function btnHtml(btn, defVariant, path) {
    if (!btn) return "";
    const btnPath = path ? ` data-ir-path="${esc(path.replace(/\.text$/, ""))}"` : "";
    return `<a class="btn btn-${btn.variant || defVariant}"${btnPath}><span>${esc(btn.text || "")}</span></a>`;
  }
  function renderSection(sec, uid, parentFree) {
    const isFree = !!(sec.frame && sec.frame.layout === "free");
    const hasChildren = sec.children && sec.children.length > 0;
    const isMeasuredSource = sec.type === "source-block" || sec.variant === "dom-capture";
    isMeasuredSource && (sec.preview || sec.sourcePreview || sec.props && sec.props.sourcePreview);
    const isStructuredSource = isMeasuredSource && hasChildren;
    const reproduction = isStructuredSource || isFree && hasChildren;
    let absChildren = null;
    if (!reproduction && hasChildren) {
      const abs = sec.children.filter((c) => c && c.frame && c.frame.absolute && (typeof c.frame.x === "number" || typeof c.frame.y === "number"));
      if (abs.length) absChildren = abs;
    }
    const innerSec = absChildren ? Object.assign({}, sec, { children: sec.children.filter((c) => absChildren.indexOf(c) < 0) }) : sec;
    const html = reproduction ? "" : renderSectionInner(innerSec, uid);
    let childrenHtml = "";
    if (reproduction) {
      childrenHtml = sec.children.map((c) => renderElement(c, uid, isFree, sec.frame)).join("");
    } else if (absChildren) {
      childrenHtml = absChildren.map((c) => renderElement(c, uid, false, sec.frame)).join("");
    }
    const underlay = "";
    const combined = underlay + html + childrenHtml;
    const secStyle = visualCss(sec.style);
    const railCss = sec.frame && typeof sec.frame.contentMaxWidth === "number" ? `--content-max-width:${sec.frame.contentMaxWidth}px;--content-gutter:${typeof sec.frame.contentGutter === "number" ? sec.frame.contentGutter : 0}px` : "";
    const extraCss = [secStyle, railCss, absChildren ? "position:relative" : ""].filter(Boolean).join(";");
    return withFrame(
      combined,
      sec.frame,
      parentFree,
      isStructuredSource || isFree,
      null,
      isStructuredSource ? "sec-source" : isFree && hasChildren ? "sec-free" : "",
      null,
      extraCss
    );
  }
  const INVERTED_ROLES = "color:#fff;--c-text:#fff;--c-muted:rgba(255,255,255,.78);--c-border:rgba(255,255,255,.24)";
  const COMPOSITION_SURFACE = {
    background: "background:var(--c-bg)",
    surface: "background:var(--c-surface)",
    primary: `background:var(--c-primary);${INVERTED_ROLES}`,
    accent: `background:var(--c-accent);${INVERTED_ROLES}`,
    none: ""
  };
  const COMPOSITION_PADDING = {
    tight: "padding-top:calc(var(--sec-py) * .55);padding-bottom:calc(var(--sec-py) * .55)",
    normal: "",
    // 1.6× давало 224px пустоты над hero — vision-судья снимал за это на каждой странице
    airy: "padding-top:calc(var(--sec-py) * 1.15);padding-bottom:calc(var(--sec-py) * 1.15)"
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
      const links = (p.links || []).map((l, i) => `<a style="color:var(--c-muted);text-decoration:none;font-size:calc(14px * var(--fs));font-weight:500" href="#" onclick="return false">
          <span data-ir-path="props.links.${i}.label">${esc(l.label)}</span></a>`).join("");
      const logo = `<a style="font-family:var(--font-display);font-weight:var(--fw-display);font-size:calc(19px * var(--fs));color:var(--c-text);text-decoration:none" href="#" onclick="return false">
          <span data-ir-path="props.logoText">${esc(p.logoText || "")}</span></a>`;
      const cta = v === "minimal" ? p.cta && p.cta.text ? btnHtml(p.cta, "outline", "props.cta.text") : "" : btnHtml(p.cta, "primary", "props.cta.text");
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
    if (t === "composition") {
      const free = !!(sec.frame && sec.frame.layout === "free");
      const kids = (sec.children || []).map((c) => renderElement(c, uid, free, sec.frame)).join("");
      const style = [compositionSurface(p.background), compositionPadding(p.density)].filter(Boolean).join(";");
      const head = p.heading ? `<h2 data-ir-path="props.heading" style="margin-bottom:${p.subheading ? 12 : 32}px;max-width:14ch">${esc(p.heading)}</h2>` : "";
      const sub = p.subheading ? `<p class="muted" data-ir-path="props.subheading" style="margin-bottom:32px;max-width:62ch">${esc(p.subheading)}</p>` : "";
      return `<section class="sec sec-composition ${base}"${style ? ` style="${style}"` : ""}>
        <div class="wrap">${head}${sub}${kids}</div></section>`;
    }
    if (t === "hero") {
      const badge = p.badge ? `<span class="badge tone-primary" style="margin-bottom:16px"><span data-ir-path="props.badge">${esc(p.badge)}</span></span>` : "";
      const head = `<h1 data-ir-path="props.heading" style="margin-bottom:16px">${esc(p.heading || "")}</h1>`;
      const sub = p.subheading ? `<p class="muted" data-ir-path="props.subheading" style="font-size:calc(17px*var(--fs));margin-bottom:28px;max-width:560px">${esc(p.subheading)}</p>` : "";
      const btns = `<div style="display:flex;gap:12px;flex-wrap:wrap">${btnHtml(p.ctaPrimary, "primary", "props.ctaPrimary.text")}${btnHtml(p.ctaSecondary, "outline", "props.ctaSecondary.text")}</div>`;
      const heroMedia = (minHeight, extra) => p.media ? p.media.src ? `<div class="img-ph" style="min-height:${minHeight}px;overflow:hidden;padding:0;${extra || ""}"><img src="${esc(p.media.src)}" alt="${esc(p.media.alt || "")}" style="display:block;width:100%;height:${minHeight}px;object-fit:cover" decoding="sync"></div>` : `<div class="img-ph" style="min-height:${minHeight}px;${extra || ""}">${esc(p.media.imagePrompt || p.media.alt || "")}</div>` : "";
      if (v === "editorial-stack") {
        const eyebrow = p.badge ? `<p class="muted" data-ir-path="props.badge" style="font-size:calc(12px*var(--fs));letter-spacing:.14em;text-transform:uppercase;margin-bottom:28px">${esc(p.badge)}</p>` : "";
        return `<section class="sec ${base}"><div class="wrap">
          ${eyebrow}
          <h1 data-ir-path="props.heading" style="font-size:calc(76px*var(--fs));line-height:1.02;letter-spacing:-.03em;margin-bottom:40px;max-width:16ch">${esc(p.heading || "")}</h1>
          <div style="border-top:1px solid var(--c-border);padding-top:28px;display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:40px;align-items:start">
            ${p.subheading ? `<p data-ir-path="props.subheading" style="font-size:calc(19px*var(--fs));max-width:52ch">${esc(p.subheading)}</p>` : "<div></div>"}
            <div style="display:flex;gap:12px;flex-wrap:wrap;justify-content:flex-start">${btnHtml(p.ctaPrimary, "primary", "props.ctaPrimary.text")}${btnHtml(p.ctaSecondary, "ghost", "props.ctaSecondary.text")}</div>
          </div>
          ${heroMedia(360, "margin-top:48px")}</div></section>`;
      }
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
      if (v === "split-offset") {
        const media = heroMedia(420, "margin-top:-64px;border-top-right-radius:0;border-bottom-right-radius:0") || `<div class="img-ph" style="min-height:420px;margin-top:-64px">${esc("медиа")}</div>`;
        return `<section class="sec ${base}" style="overflow:hidden"><div class="wrap" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:56px;align-items:start">
          <div style="display:flex;flex-direction:column;padding-top:24px">${badge}${head}${sub}${btns}</div>
          <div style="position:relative;left:72px">${media}</div></div></section>`;
      }
      if (v === "numbered") {
        const items = (sec.children || []).map((c, i) => `<div style="display:grid;grid-template-columns:56px 1fr;gap:20px;align-items:start;padding:20px 0;border-top:1px solid var(--c-border)">
          <span style="font-family:var(--font-display);font-weight:var(--fw-display);font-size:calc(22px*var(--fs));color:var(--c-primary);line-height:1.2">${String(i + 1).padStart(2, "0")}</span>
          <div>${renderElement(c, uid, false, sec.frame)}</div></div>`).join("");
        return `<section class="sec ${base}"><div class="wrap" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:64px;align-items:start">
          <div style="display:flex;flex-direction:column">${badge}${head}${sub}${btns}</div>
          <div>${items}</div></div></section>`;
      }
      if (v === "split" || v === "split-reverse") {
        const media = p.media ? p.media.src ? `<div class="img-ph" style="min-height:320px;overflow:hidden;padding:0"><img src="${esc(p.media.src)}" alt="${esc(p.media.alt || "")}" style="display:block;width:100%;height:320px;object-fit:cover" decoding="sync"></div>` : `<div class="img-ph" style="min-height:320px">${esc(p.media.imagePrompt || p.media.alt || "")}</div>` : `<div class="img-ph" style="min-height:320px">медиа</div>`;
        const txt = `<div style="display:flex;flex-direction:column;justify-content:center">${badge}${head}${sub}${btns}</div>`;
        return `<section class="sec ${base}"><div class="wrap" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:48px;align-items:center">
          ${v === "split" ? txt + media : media + txt}</div></section>`;
      }
      if (v === "media-bg" || v === "gradient") {
        const bg = v === "gradient" ? "background:linear-gradient(135deg,var(--c-primary) 0%,var(--c-bg) 90%);" : "background:linear-gradient(rgba(0,0,0,.45),rgba(0,0,0,.45)),linear-gradient(135deg,var(--c-surface),var(--c-border));";
        return `<section class="sec ${base}" style="${bg}text-align:center"><div class="wrap" style="display:flex;flex-direction:column;align-items:center">
          ${badge}${head}${sub.replace("max-width:560px", "max-width:640px;margin-left:auto;margin-right:auto")}<div style="display:flex;gap:12px">${btnHtml(p.ctaPrimary, "primary", "props.ctaPrimary.text")}${btnHtml(p.ctaSecondary, "outline", "props.ctaSecondary.text")}</div></div></section>`;
      }
      const align = p.align === "left" ? "left" : "center";
      return `<section class="sec ${base}" style="text-align:${align}"><div class="wrap" style="display:flex;flex-direction:column;${align === "center" ? "align-items:center" : ""}">
        ${badge}${head}${sub}${btns}</div></section>`;
    }
    if (t === "logo-cloud") {
      const logos = (sec.children && sec.children.length ? sec.children : [{ type: "text", text: "Партнёр" }, { type: "text", text: "Бренд" }, { type: "text", text: "Компания" }, { type: "text", text: "Сервис" }]).map((c) => `<span class="muted" style="font-family:var(--font-display);font-weight:700;font-size:calc(18px*var(--fs));opacity:.7">${esc(c.text || c.title || c.alt || "logo")}</span>`).join("");
      const marquee = v === "marquee" ? ";overflow:hidden;white-space:nowrap" : "";
      return `<section class="sec ${base}" style="padding-top:32px;padding-bottom:32px${marquee}"><div class="wrap" style="text-align:center">
        ${p.heading ? `<p class="muted" data-ir-path="props.heading" style="margin-bottom:20px;font-size:calc(13px*var(--fs));text-transform:uppercase;letter-spacing:.08em">${esc(p.heading)}</p>` : ""}
        <div style="display:flex;gap:48px;justify-content:center;align-items:center;flex-wrap:wrap">${logos}</div></div></section>`;
    }
    if (t === "feature-grid") {
      const kids = sec.children || [];
      const kid = (c) => renderElement(c, uid, false, sec.frame);
      if (v === "list-rail") {
        const rows = kids.map((c, i) => `<div style="display:grid;grid-template-columns:72px 1fr;gap:28px;align-items:start;padding:26px 0;border-top:1px solid var(--c-border)">
          <span style="font-family:var(--font-display);font-weight:var(--fw-display);font-size:calc(26px*var(--fs));color:var(--c-primary);line-height:1.1">${String(i + 1).padStart(2, "0")}</span>
          <div>${kid(c)}</div></div>`).join("");
        return `<section class="sec ${base}"><div class="wrap" style="max-width:900px">
          ${secHeadLeft(p)}<div>${rows}</div></div></section>`;
      }
      if (v === "bento-asym") {
        const spans = [4, 2, 3, 3, 2, 4];
        const tiles = kids.map((c, i) => `<div style="grid-column:span ${spans[i % spans.length]};${i === 0 ? "min-height:280px;" : ""}display:grid">${kid(c)}</div>`).join("");
        return `<section class="sec ${base}"><div class="wrap">
          ${secHead(p)}
          <div style="display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:20px">${tiles}</div></div></section>`;
      }
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
          ${(c.children || []).map((ch) => renderElement(ch, uid, !!(c.frame && c.frame.layout === "free"), c.frame)).join("")}</div>`;
        return `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:48px;align-items:center;margin-bottom:48px">${i % 2 ? txt + media : media + txt}</div>`;
      }).join("");
      return `<section class="sec ${base}"><div class="wrap">${secHead(p)}${rows}</div></section>`;
    }
    if (t === "stats") {
      const items = (p.items || []).map((it, i) => `<div style="text-align:center"><div data-ir-path="props.items.${i}.value" style="font-family:var(--font-display);font-weight:var(--fw-display);font-size:calc(38px*var(--fs));color:var(--c-primary)">${esc(it.value)}</div>
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
        ${(sec.children || []).map((c, i) => `<div class="img-ph" style="min-height:${v === "masonry" ? 140 + i * 67 % 120 : 200}px">${esc(c.imagePrompt || c.alt || "фото")}</div>`).join("")}</div></div></section>`;
    }
    if (t === "testimonials") {
      return `<section class="sec ${base}"><div class="wrap">${secHead(p)}
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:20px">
        ${(sec.children || []).map((c) => `<div class="card">
          ${c.children && c.children.some((x) => x.type === "rating") ? "" : '<span class="stars">★★★★★</span>'}
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
            ${inputType === "textarea" ? `<textarea data-ir-path="${controlPath}" data-form-part="control" class="input" rows="3" placeholder="${esc(placeholder)}"${controlStyle}></textarea>` : inputType === "checkbox" ? `<span data-ir-path="${controlPath}" data-form-part="control" style="display:flex;gap:8px;align-items:center;font-weight:400;${controlCss}"><input type="checkbox"> <span>${esc(placeholder)}</span></span>` : `<input data-ir-path="${controlPath}" data-form-part="control" class="input" placeholder="${esc(placeholder)}"${controlStyle}>`}</div>`;
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
      const cols = (p.columns || []).map((col) => `<div>
        <h4 style="margin-bottom:14px">${esc(col.title)}</h4>
        <div style="display:flex;flex-direction:column;gap:10px">${(col.links || []).map((l) => `<a href="#" onclick="return false" style="color:var(--c-muted);text-decoration:none;font-size:calc(14px*var(--fs))">${esc(l.label)}</a>`).join("")}</div></div>`).join("");
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
    if (t === "banner") {
      return `<section class="sec ${base}" style="padding-top:14px;padding-bottom:14px;background:var(--c-surface)"><div class="wrap" style="display:flex;gap:16px;align-items:center;justify-content:center;flex-wrap:wrap">
        <span data-ir-path="props.text">${esc(p.text || "")}</span>${btnHtml(p.cta, "outline", "props.cta.text")}</div></section>`;
    }
    return `<section class="sec ${base}"><div class="wrap">${secHead(p)}
      ${renderChildren(sec.children, uid, Math.min(3, (sec.children || []).length || 0), sec.frame) || `<div class="card muted">Секция «${esc(t)}» (${esc(v)}): нет children для предпросмотра</div>`}</div></section>`;
  }
  function secHead(p) {
    if (!p.heading && !p.subheading) return "";
    return `<div class="sec-head">${p.heading ? `<h2 data-ir-path="props.heading">${esc(p.heading)}</h2>` : ""}
      ${p.subheading ? `<p class="muted" data-ir-path="props.subheading">${esc(p.subheading)}</p>` : ""}</div>`;
  }
  function secHeadLeft(p) {
    if (!p.heading && !p.subheading) return "";
    return `<div class="sec-head" style="text-align:left;max-width:none;margin:0 0 32px">
      ${p.heading ? `<h2 data-ir-path="props.heading">${esc(p.heading)}</h2>` : ""}
      ${p.subheading ? `<p class="muted" data-ir-path="props.subheading">${esc(p.subheading)}</p>` : ""}</div>`;
  }
  let uidCounter = 0;
  const renderStates = /* @__PURE__ */ new WeakMap();
  function nowMs() {
    return typeof performance !== "undefined" && typeof performance.now === "function" ? performance.now() : Date.now();
  }
  function cachedRenderIsLive(container, cached) {
    return !!cached && cached.styleEl && cached.rootEl && cached.styleEl.parentElement === container && cached.rootEl.parentElement === container;
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
      if (key === "children" || omitFrames && key === "_frames") continue;
      local[key] = value[key];
    }
    return JSON.stringify(local);
  }
  function snapshotSection(section) {
    const nodes = /* @__PURE__ */ new Map();
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
        depth
      });
      const childParentFree = !!(node.frame && node.frame.layout === "free");
      children.forEach((child) => visit(child, childParentFree, node.frame, depth + 1));
    }
    roots.forEach((node) => visit(node, sectionFree, section && section.frame, 0));
    return {
      fingerprint: localFingerprint(section, true),
      frameFingerprint: JSON.stringify(section && section._frames || null),
      childPaths: roots.map((child) => child && child.__path || ""),
      nodes
    };
  }
  function planNodePatches(before, after) {
    if (!before || !after || before.fingerprint !== after.fingerprint || before.frameFingerprint !== after.frameFingerprint || after.frameFingerprint !== "null") return null;
    const patches = [];
    function walk(beforePaths, afterPaths, parentPath) {
      if (beforePaths.length !== afterPaths.length || beforePaths.some((path, index) => path !== afterPaths[index])) {
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
  const cloneIr = (value) => JSON.parse(JSON.stringify(value));
  const confirmedFontSpecs = /* @__PURE__ */ new Set();
  const registeredFontFaces = /* @__PURE__ */ new Map();
  let lastFontFacesCss = "";
  function materializeResponsiveIR(source, viewport) {
    if (!source || !source.responsive || !source.responsive.viewports) return source;
    (source.tree || []).forEach((sec) => annotatePaths(sec, "", false));
    return materializeResponsiveInPlace(cloneIr(source), viewport);
  }
  function materializeResponsiveInPlace(ir, viewport) {
    const meta = ir.responsive.viewports[viewport] || ir.responsive.viewports.desktop;
    if (meta) {
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
      if (override && typeof override.text === "string") node.text = override.text;
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
  function renderIR(container, ir, options) {
    const startedAt = nowMs();
    if (ir) ir = cloneIr(ir);
    const responsiveSource = !!(ir && ir.responsive && ir.responsive.viewports);
    if (responsiveSource) {
      (ir.tree || []).forEach((sec) => annotatePaths(sec, "", false));
      ir = materializeResponsiveInPlace(ir, options && options.viewport ? options.viewport : "desktop");
    }
    const cached = renderStates.get(container);
    const incremental = !!(options && options.incremental);
    const reuseCachedRoot = incremental && cachedRenderIsLive(container, cached);
    const uid = reuseCachedRoot ? cached.uid : ++uidCounter;
    const tokens = ir.tokens = mergeDefaults(ir.tokens);
    const tree = ir.tree || [];
    let styleEl = document.getElementById("ir-fonts");
    if (!styleEl) {
      styleEl = document.createElement("link");
      styleEl.id = "ir-fonts";
      styleEl.rel = "stylesheet";
      document.head.appendChild(styleEl);
    }
    const offline = !!(options && options.offline);
    const href = tokens.font && !offline ? fontsUrl(tokens, ir) : "";
    if (href && styleEl.getAttribute("href") !== href) styleEl.setAttribute("href", href);
    else if (!href && styleEl.hasAttribute("href")) styleEl.removeAttribute("href");
    const requestedFaces = Array.isArray(ir.meta && ir.meta.fontFaces) ? ir.meta.fontFaces : [];
    const customFaces = requestedFaces.filter((face) => {
      if (!face || typeof face !== "object") return false;
      const family = String(face.family || "");
      const weight = String(face.weight || "");
      const style = String(face.style || "");
      const url = String(face.url || "");
      const unicodeRange = String(face.unicodeRange || "");
      return /^[A-Za-z0-9 ._-]{1,80}$/.test(family) && /^(?:[1-9]00(?: [1-9]00)?|normal|bold)$/.test(weight) && /^(?:normal|italic|oblique)$/.test(style) && /^\/fonts\/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(url) && (!unicodeRange || /^[Uu+0-9A-Fa-f? ,\-]{1,2048}$/.test(unicodeRange));
    });
    let ffEl = document.getElementById("ir-fontfaces");
    if (!ffEl) {
      ffEl = document.createElement("style");
      ffEl.id = "ir-fontfaces";
      document.head.appendChild(ffEl);
    }
    for (const f of customFaces) {
      const key = [f.family, f.style, f.weight, f.url, f.unicodeRange || ""].join("|");
      if (!registeredFontFaces.has(key)) registeredFontFaces.set(key, f);
    }
    const fontFacesCss = Array.from(registeredFontFaces.values()).map((f) => {
      const rawUrl = String(f.url);
      const format = /\.woff2$/i.test(rawUrl) ? "woff2" : /\.woff$/i.test(rawUrl) ? "woff" : "truetype";
      const unicode = f.unicodeRange ? "unicode-range:" + String(f.unicodeRange) + ";" : "";
      const isDesktop = typeof window !== "undefined" && !!window.designDNA;
      const url = isDesktop && rawUrl.startsWith("/fonts/") ? "ddna://" + rawUrl.slice(1) : rawUrl;
      return "@font-face{font-family:'" + String(f.family) + "';font-style:" + String(f.style) + ";font-weight:" + String(f.weight) + ";" + unicode + "src:url('" + url + "') format('" + format + "');font-display:swap;}";
    }).join("\n");
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
        const pending = unconfirmedFaces.map((f) => {
          const w = parseInt(String(f.weight), 10) || 400;
          const spec = w + ' 16px "' + f.family + '"';
          return document.fonts.load(spec).then((faces) => ({ spec, ok: faces.length > 0 })).catch((error) => ({ spec, ok: false, error: String(error && error.message || error) }));
        });
        void Promise.all(pending).then((results) => {
          for (const r of results) if (r.ok) confirmedFontSpecs.add(r.spec);
          const failed = results.filter((r) => !r.ok);
          if (failed.length) {
            console.error("[ir] source fonts failed to load: " + failed.map((r) => r.spec + (r.error ? " — " + r.error : "")).join("; "));
          }
        });
      } catch (_) {
      }
    }
    if (requestedFaces.length && !customFaces.length) {
      console.error("[ir] every captured font face was rejected by validation: " + JSON.stringify(requestedFaces.slice(0, 3)));
    }
    const legacySourceFrame = tree.length === 1 && tree[0] && (tree[0].type === "source-block" || tree[0].variant === "dom-capture") && tree[0].frame && typeof tree[0].frame === "object" ? tree[0].frame : null;
    const rootFrame = ir.frame && typeof ir.frame === "object" ? ir.frame : legacySourceFrame;
    const rootFree = !!(rootFrame && rootFrame.layout === "free");
    const artW = rootFrame && typeof rootFrame.width === "number" ? rootFrame.width : DESIGN_WIDTH;
    const artStyle = [`width:${artW}px`];
    if (rootFrame) {
      if (typeof rootFrame.height === "number") artStyle.push(`height:${rootFrame.height}px`);
      if (typeof rootFrame.padding === "number") artStyle.push(`padding:${rootFrame.padding}px`);
      else if (Array.isArray(rootFrame.padding) && rootFrame.padding.length === 4) artStyle.push(`padding:${rootFrame.padding.map((n) => n + "px").join(" ")}`);
      if (rootFree) artStyle.push("position:relative");
    }
    const css = `.ir-${uid}{${cssVars(tokens)}}` + baseCss(uid);
    const rootSourcePreview = ir.sourcePreview || ir.meta && ir.meta.sourcePreview;
    const sections = tree.map((sec, i) => {
      if (rootSourcePreview && sec && (sec.type === "source-block" || sec.variant === "dom-capture") && !sec.preview && !sec.sourcePreview && !(sec.props && sec.props.sourcePreview)) {
        sec.props = Object.assign({}, sec.props || {}, { sourcePreview: rootSourcePreview });
      }
      annotatePaths(sec, "", responsiveSource);
      return renderSection(sec, uid, rootFree).replace(/^<(\w+)/, `<$1 data-ir-sec="${i}"`);
    });
    const body = sections.join("");
    const sectionFingerprints = sections.map((html, index) => html + "\0" + JSON.stringify(tree[index] && tree[index]._frames || null));
    const sectionSnapshots = tree.map(snapshotSection);
    const vpName = options && options.viewport || (artW <= 639 ? "mobile" : artW <= 1023 ? "tablet" : "desktop");
    const viewportClass = "ir-" + vpName;
    const rootStyle = artStyle.join(";");
    let inner = null;
    let mode = "full";
    let patchedSections = sections.length;
    let patchedNodes = 0;
    const canPatch = reuseCachedRoot && cached.sectionFingerprints && cached.sectionSnapshots && cached.sections.length === sections.length && cached.rootEl.children.length === sections.length;
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
      durationMs: nowMs() - startedAt
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
      stats
    });
    if (!options || options.fit !== false) requestAnimationFrame(() => fitPreview(container, inner));
    return stats;
  }
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
    container.style.height = inner.offsetHeight * scale + "px";
  }
  function annotatePaths(sec, prefix, preserve) {
    prefix = prefix || "";
    const sourceSec = !!sec && (sec.type === "source-block" || sec.variant === "dom-capture");
    (sec.children || []).forEach((el, i) => {
      if (!preserve || !el.__path) el.__path = sourceSec && el.sourceKey || `${prefix}children.${i}`;
      annotatePathsEl(el, el.__path, preserve, sourceSec);
    });
  }
  function annotatePathsEl(el, path, preserve, sourceSec) {
    (el.children || []).forEach((c, i) => {
      if (!preserve || !c.__path) c.__path = sourceSec && c.sourceKey || `${path}.children.${i}`;
      annotatePathsEl(c, c.__path, preserve, sourceSec);
    });
  }
  const IRRenderer = { renderIR, materializeResponsiveIR, fitPreview, getRenderStats, DESIGN_WIDTH };
  function isSourceKeyPath(path) {
    return !!path && !path.startsWith("children.") && !path.startsWith("props.");
  }
  function findByKey(sec, key) {
    let found = null;
    const walk = (n) => {
      if (!n || typeof n !== "object" || found) return;
      if (n.sourceKey === key || n.__path === key) {
        found = n;
        return;
      }
      (n.children || []).forEach(walk);
    };
    walk(sec);
    return found;
  }
  function sourceParentPath(path) {
    if (!path || path.startsWith("children.") || path.startsWith("props.")) return void 0;
    let p = path;
    const syn = p.indexOf("::");
    if (syn >= 0) p = p.slice(0, syn);
    else {
      const i = p.lastIndexOf("/");
      p = i >= 0 ? p.slice(0, i) : "";
    }
    if (!p || p === "root" || p.endsWith(":root")) return null;
    return p;
  }
  function locateByKey(sec, key) {
    if (!sec || !key) return null;
    let found = null;
    const walk = (node, parentNode, arr) => {
      if (found || !node || typeof node !== "object") return;
      if (node.sourceKey === key || node.__path === key) {
        found = { node, parentNode, siblings: arr, index: arr.indexOf(node) };
        return;
      }
      (node.children || []).forEach((c) => walk(c, node, node.children));
    };
    (sec.children || []).forEach((c) => walk(c, sec, sec.children));
    return found;
  }
  function parentKeyByKey(sec, key) {
    const located = locateByKey(sec, key);
    if (!located) return void 0;
    const parentNode = located.parentNode;
    if (parentNode === sec) return null;
    const k = parentNode.sourceKey || parentNode.__path;
    return k != null ? String(k) : void 0;
  }
  function rekeyCloneKeys(root, uidFn) {
    if (!root || typeof root !== "object" || root.sourceKey == null) return root;
    const origRoot = String(root.sourceKey);
    const newRoot = origRoot + "~" + uidFn();
    let extra = 0;
    const walk = (n, isRootNode) => {
      if (!n || typeof n !== "object") return;
      if (n.sourceKey != null) {
        const k = String(n.sourceKey);
        if (isRootNode || k === origRoot) n.sourceKey = newRoot;
        else if (k.startsWith(origRoot) && (k.charAt(origRoot.length) === "/" || k.charAt(origRoot.length) === ":")) {
          n.sourceKey = newRoot + k.slice(origRoot.length);
        } else {
          n.sourceKey = newRoot + "::dup" + extra++;
        }
      }
      delete n.__path;
      (n.children || []).forEach((c) => walk(c, false));
    };
    walk(root, true);
    root.sourceMeta = Object.assign({ kind: "dom" }, root.sourceMeta, { derivedFromKey: origRoot });
    return root;
  }
  const GEO_CSS = `
  /* Оверлей живёт ВНУТРИ трансформированного контейнера (canvas-координаты).
     --geo-inv = 1/zoom: ручки, чипы и линии держат постоянный экранный размер. */
  .geo-overlay { position:absolute; left:0; top:0; width:100%; height:100%; pointer-events:auto; z-index:50; overflow:visible; cursor:default; }
  .geo-overlay[data-tool="rect"], .geo-overlay[data-tool="frame"], .geo-overlay[data-tool="text"],
  .geo-overlay[data-tool="ellipse"], .geo-overlay[data-tool="line"], .geo-overlay[data-tool="image"] { cursor:crosshair; }
  .geo-overlay[data-tool="hand"] { cursor:grab; }
  .geo-overlay.geo-handling { cursor:grabbing; }
  .geo-overlay * { pointer-events:none; }
  .geo-overlay .geo-h, .geo-overlay .geo-pad { pointer-events:auto; }
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
  .geo-pad-guide { position:absolute; pointer-events:none; z-index:1; background:rgba(151,71,255,.72); }
  .geo-pad-guide.pad-top, .geo-pad-guide.pad-bottom { height:calc(1px * var(--geo-inv,1)); }
  .geo-pad-guide.pad-left, .geo-pad-guide.pad-right { width:calc(1px * var(--geo-inv,1)); }
  .geo-pad { position:absolute; z-index:4; box-sizing:border-box; pointer-events:auto;
    background:#9747ff; border:calc(1px * var(--geo-inv,1)) solid #fff;
    box-shadow:0 0 0 calc(1px * var(--geo-inv,1)) rgba(151,71,255,.45); }
  .geo-pad.pad-top, .geo-pad.pad-bottom { width:calc(34px * var(--geo-inv,1)); height:calc(7px * var(--geo-inv,1));
    margin-left:calc(-17px * var(--geo-inv,1)); margin-top:calc(-3.5px * var(--geo-inv,1));
    border-radius:calc(4px * var(--geo-inv,1)); cursor:ns-resize; }
  .geo-pad.pad-left, .geo-pad.pad-right { width:calc(7px * var(--geo-inv,1)); height:calc(34px * var(--geo-inv,1));
    margin-left:calc(-3.5px * var(--geo-inv,1)); margin-top:calc(-17px * var(--geo-inv,1));
    border-radius:calc(4px * var(--geo-inv,1)); cursor:ew-resize; }
  .geo-pad::after { content:attr(data-value); position:absolute; opacity:0; pointer-events:none; transition:opacity 80ms linear;
    min-width:calc(22px * var(--geo-inv,1)); padding:calc(2px * var(--geo-inv,1)) calc(5px * var(--geo-inv,1));
    border-radius:calc(4px * var(--geo-inv,1)); background:#9747ff; color:#fff;
    font:600 calc(10px * var(--geo-inv,1))/1.2 'Inter',system-ui,sans-serif; text-align:center; white-space:nowrap; }
  .geo-pad:hover::after, .geo-pad.active::after { opacity:1; }
  .geo-pad.pad-top::after, .geo-pad.pad-bottom::after { left:50%; transform:translateX(-50%); top:calc(9px * var(--geo-inv,1)); }
  .geo-pad.pad-bottom::after { top:auto; bottom:calc(9px * var(--geo-inv,1)); }
  .geo-pad.pad-left::after, .geo-pad.pad-right::after { top:50%; transform:translateY(-50%); left:calc(9px * var(--geo-inv,1)); }
  .geo-pad.pad-right::after { left:auto; right:calc(9px * var(--geo-inv,1)); }
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
  let geoClipboard = [];
  let geoUidCounter = 0;
  function nextUid() {
    return "geo-" + Date.now().toString(36) + "-" + ++geoUidCounter;
  }
  function getByPath(obj, path) {
    return path.split(".").reduce((o, k) => o == null ? o : o[k], obj);
  }
  function setByPath(obj, path, value) {
    const keys = path.split(".");
    const last = keys.pop();
    const target = keys.reduce((o, k) => o == null ? o : o[k], obj);
    if (target != null) target[last] = value;
  }
  function editableTextPath(path) {
    if (!path || !path.startsWith("props.")) return path;
    const base = path.replace(/\.text$/, "");
    const textProps = ["cta", "ctaPrimary", "ctaSecondary", "badge", "heading", "subheading", "text", "logoText"];
    const key = base.slice("props.".length);
    if (textProps.includes(key)) return base + ".text";
    return path;
  }
  function finiteNum(v) {
    const n = typeof v === "number" ? v : parseFloat(v);
    return Number.isFinite(n) ? n : 0;
  }
  const NEW_SHAPE_FILL = "#8B5CF6";
  function attach(opts) {
    const { previewEl, getIR, getScale, onCommit, onSelect } = opts;
    const cancelCommit = opts.cancelCommit || null;
    const scrollEl = opts.scrollEl || null;
    const onToolChange = opts.onToolChange || null;
    const notice = opts.onNotice || function() {
    };
    const toolsEnabled = !!opts.tools;
    const escapeViaHandle = !!opts.escapeViaHandle;
    const isLocked = opts.isLocked || null;
    function skipLocked(ref) {
      return !!isLocked && isLocked(ref);
    }
    let _onMutated = opts.onMutated || function() {
    };
    function blockContentEarly() {
      const irEl = previewEl.querySelector('[class^="ir-"]');
      if (irEl) irEl.classList.add("geo-content-block");
    }
    function onMutated() {
      _onMutated();
      requestAnimationFrame(blockContentEarly);
      scheduleBoxSync();
    }
    injectCSS();
    const prevStyle = previewEl.style;
    if (!prevStyle.position || prevStyle.position === "static") {
      prevStyle.position = "relative";
    }
    let selections = [];
    let drag = null;
    let lastDragSmartSnapped = false;
    let marquee = null;
    let tool = "select";
    let hand = null;
    let create = null;
    let destroyed = false;
    let rafId = null;
    let boxSyncRaf = null;
    let pendingPointer = null;
    let containerCtx = null;
    let nudgeSessionUntil = 0;
    let styleSessionUntil = 0;
    function scale() {
      const s = getScale();
      return s > 0 ? s : 1;
    }
    function overlayScale() {
      const ow = previewEl.offsetWidth;
      return ow > 0 ? previewEl.getBoundingClientRect().width / ow : 1;
    }
    function canvasK() {
      const os = overlayScale();
      return os > 0 ? scale() / os : 1;
    }
    function scheduleBoxSync() {
      if (boxSyncRaf || destroyed) return;
      boxSyncRaf = requestAnimationFrame(() => {
        boxSyncRaf = null;
        if (!destroyed && selections.length) renderSelectionBoxes();
      });
    }
    function artboardEl() {
      return previewEl.querySelector('[class^="ir-"]');
    }
    function irNodeAt(ref) {
      const ir = getIR();
      if (ref.secIdx == null) return ir;
      if (ref.path == null) return ir.tree[ref.secIdx];
      const sec = ir.tree[ref.secIdx];
      if (!sec) return null;
      const direct = getByPath(sec, ref.path);
      if (direct || ref.path.startsWith("props.")) return direct;
      return findByKey(sec, ref.path);
    }
    function lockedNodeFor(ref) {
      if (!ref || ref.secIdx == null || !ref.path || ref.path.startsWith("props.")) return null;
      const node = irNodeAt(ref);
      return isLockedNode(node) ? node : null;
    }
    function refuseLocked(ref) {
      const node = lockedNodeFor(ref);
      if (!node) return false;
      hint("Слой заблокирован: " + lockedReason(node));
      return true;
    }
    function getFrame(ref) {
      if (ref.secIdx == null) return getIR().frame || {};
      if (ref.path == null) return getIR().tree[ref.secIdx].frame || {};
      if (ref.path.startsWith("props.")) {
        const sec = getIR().tree[ref.secIdx];
        return sec._frames && sec._frames[ref.path] || {};
      }
      const node = irNodeAt(ref);
      return node && node.frame || {};
    }
    function setFrameData(ref, frame) {
      if (refuseLocked(ref)) return;
      if (ref.secIdx == null) {
        getIR().frame = frame;
        return;
      }
      if (ref.path == null) {
        getIR().tree[ref.secIdx].frame = frame;
        return;
      }
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
      if (/^props\.fields\.\d+$/.test(ref.path)) return "поле формы · " + String(node && (node.label || node.placeholder) || "без названия");
      if (/^props\.fields\.\d+\.parts\.label$/.test(ref.path)) return "подпись поля";
      if (/^props\.fields\.\d+\.parts\.control$/.test(ref.path)) return "поле ввода";
      if (ref.path === "props.submit") return "кнопка формы · " + String(node && node.text || "Отправить");
      if (ref.path && ref.path.startsWith("props.")) return ref.path.replace("props.", "");
      return node && node.type ? node.type : "узел";
    }
    function screenToCanvas(clientX, clientY) {
      const base = previewEl.getBoundingClientRect();
      const s = scale();
      return {
        x: (clientX - base.left) / s,
        y: (clientY - base.top) / s
      };
    }
    function collectHitTargets() {
      const ir = getIR();
      if (!ir || !ir.tree) return [];
      const targets = [];
      const base = previewEl.getBoundingClientRect();
      const s = scale();
      ir.tree.forEach((sec, si) => {
        const secEl = previewEl.querySelector(`[data-ir-sec="${si}"]`);
        if (!secEl) return;
        const sr = secEl.getBoundingClientRect();
        targets.push({
          ref: { secIdx: si, path: null },
          depth: 0,
          x: (sr.left - base.left) / s,
          y: (sr.top - base.top) / s,
          w: sr.width / s,
          h: sr.height / s
        });
        secEl.querySelectorAll("[data-ir-path]").forEach((el) => {
          const rawPath = el.getAttribute("data-ir-path");
          if (!rawPath) return;
          const r = el.getBoundingClientRect();
          if (r.width < 2 || r.height < 2) return;
          targets.push({
            ref: { secIdx: si, path: normalizePropsPath(rawPath) },
            depth: rawPath.startsWith("children.") ? rawPath.split(".children.").length : 1,
            x: (r.left - base.left) / s,
            y: (r.top - base.top) / s,
            w: r.width / s,
            h: r.height / s
          });
        });
      });
      return targets;
    }
    function parentRef(ref) {
      if (!ref || ref.secIdx == null || !ref.path) return null;
      if (ref.path.startsWith("children.")) {
        const parts = ref.path.split(".");
        if (parts.length <= 2) return { secIdx: ref.secIdx, path: null };
        parts.pop();
        parts.pop();
        return { secIdx: ref.secIdx, path: parts.join(".") };
      }
      const pk = parentKeyByKey(getIR().tree[ref.secIdx], ref.path);
      if (pk === void 0) return null;
      return { secIdx: ref.secIdx, path: pk };
    }
    function nearestSelectableContainer(ref, hitKeys) {
      const hitNode = irNodeAt(ref);
      if (hitNode && ["button", "input"].includes(hitNode.type)) return ref;
      let parent = parentRef(ref);
      while (parent) {
        const node = irNodeAt(parent);
        if (parent.path && node && node.children && node.children.length && hitKeys.has(refKey(parent)) && !skipLocked(parent)) {
          if (["button", "input"].includes(node.type)) return parent;
          const layout = node && node.frame && node.frame.layout;
          if (layout !== "free") return parent;
        }
        parent = parentRef(parent);
      }
      return null;
    }
    function hitTest(clientX, clientY, deep) {
      const pt = screenToCanvas(clientX, clientY);
      const targets = collectHitTargets();
      const hits = [];
      for (let i = targets.length - 1; i >= 0; i--) {
        const t = targets[i];
        if (pt.x >= t.x && pt.x <= t.x + t.w && pt.y >= t.y && pt.y <= t.y + t.h) {
          if (skipLocked(t.ref)) continue;
          hits.push(t);
          if (deep && t.ref.path === null) continue;
          if (containerCtx && t.ref.path === null) continue;
          if (!deep) {
            const hitKeys = new Set(hits.map((h) => refKey(h.ref)).concat(targets.filter((q) => pt.x >= q.x && pt.x <= q.x + q.w && pt.y >= q.y && pt.y <= q.y + q.h).map((q) => refKey(q.ref))));
            const container = nearestSelectableContainer(t.ref, hitKeys);
            if (container) return container;
          }
          return t.ref;
        }
      }
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
    function hitTestHandle(clientX, clientY) {
      if (!selections.length) return null;
      const s = scale();
      const base = previewEl.getBoundingClientRect();
      let hx, hy, hw, hh;
      if (selections.length > 1) {
        const rects = selectedRects();
        if (rects.length < 2) return null;
        hx = Math.min(...rects.map((r) => r.x));
        hy = Math.min(...rects.map((r) => r.y));
        hw = Math.max(...rects.map((r) => r.x + r.w)) - hx;
        hh = Math.max(...rects.map((r) => r.y + r.h)) - hy;
      } else {
        const primary = selections[selections.length - 1];
        const el = domAt(primary.ref);
        if (!el) return null;
        const r = el.getBoundingClientRect();
        hx = (r.left - base.left) / s;
        hy = (r.top - base.top) / s;
        hw = r.width / s;
        hh = r.height / s;
      }
      const pt = screenToCanvas(clientX, clientY);
      const handles = [
        { dir: "nw", cx: hx, cy: hy },
        { dir: "n", cx: hx + hw / 2, cy: hy },
        { dir: "ne", cx: hx + hw, cy: hy },
        { dir: "e", cx: hx + hw, cy: hy + hh / 2 },
        { dir: "se", cx: hx + hw, cy: hy + hh },
        { dir: "s", cx: hx + hw / 2, cy: hy + hh },
        { dir: "sw", cx: hx, cy: hy + hh },
        { dir: "w", cx: hx, cy: hy + hh / 2 }
      ];
      const HS = Math.max(4, 6 / scale());
      for (const h of handles) {
        if (Math.abs(pt.x - h.cx) <= HS && Math.abs(pt.y - h.cy) <= HS) {
          return h.dir;
        }
      }
      return null;
    }
    const SNAP_THRESHOLD = 4;
    function computeGuides(movingRef, movingRect) {
      const snapThr = SNAP_THRESHOLD / scale();
      const targets = collectHitTargets().filter((t) => refKey(t.ref) !== refKey(movingRef));
      const guides = [];
      const distances = [];
      let snapDx = 0, snapDy = 0;
      let bestDx = Infinity, bestDy = Infinity;
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
        if (mCy > tT && mCy < tB) {
          if (mL > tR) {
            const gap = mL - tR;
            if (gap > 0 && gap < 200) distances.push({ type: "h", from: tR, to: mL, y: mCy, val: gap });
          } else if (mR < tL) {
            const gap = tL - mR;
            if (gap > 0 && gap < 200) distances.push({ type: "h", from: mR, to: tL, y: mCy, val: gap });
          }
        }
        if (mCx > tL && mCx < tR) {
          if (mT > tB) {
            const gap = mT - tB;
            if (gap > 0 && gap < 200) distances.push({ type: "v", from: tB, to: mT, x: mCx, val: gap });
          } else if (mB < tT) {
            const gap = tT - mB;
            if (gap > 0 && gap < 200) distances.push({ type: "v", from: mB, to: tT, x: mCx, val: gap });
          }
        }
      }
      const seen = /* @__PURE__ */ new Set();
      const uniqueGuides = guides.filter((g) => {
        const k = g.axis + ":" + Math.round(g.pos);
        if (seen.has(k)) return false;
        seen.add(k);
        return true;
      });
      const closestDist = {};
      distances.forEach((d) => {
        const k = d.type + ":" + (d.type === "h" ? "y" + Math.round(d.y) : "x" + Math.round(d.x));
        if (!closestDist[k] || d.val < closestDist[k].val) closestDist[k] = d;
      });
      const eq = [];
      const eqSeen = /* @__PURE__ */ new Set();
      const eqPar = parentOf(movingRef);
      const sibKeys = /* @__PURE__ */ new Set();
      if (eqPar) {
        eqPar.siblings.forEach((sib, j) => {
          const r = eqPar.isRoot ? { secIdx: j, path: null } : { secIdx: eqPar.secIdx, path: siblingPath(eqPar, j) };
          sibKeys.add(refKey(r));
        });
      }
      function eqMembers(axis) {
        const mates = targets.filter((t) => {
          if (!sibKeys.has(refKey(t.ref))) return false;
          const overlap = axis === "h" ? Math.min(mB, t.y + t.h) - Math.max(mT, t.y) : Math.min(mR, t.x + t.w) - Math.max(mL, t.x);
          return overlap > 0;
        });
        const self = { x: movingRect.x, y: movingRect.y, w: movingRect.w, h: movingRect.h, _moving: true };
        const list = mates.concat([self]);
        list.sort((a, b) => axis === "h" ? a.x - b.x : a.y - b.y);
        return list;
      }
      function pushEqRegion(type, a, b, gap) {
        let from, to, c0, c1;
        if (type === "h") {
          from = a.x + a.w;
          to = b.x;
          c0 = Math.max(a.y, b.y);
          c1 = Math.min(a.y + a.h, b.y + b.h);
          if (c1 - c0 < 2) {
            c0 = mT;
            c1 = mB;
          }
        } else {
          from = a.y + a.h;
          to = b.y;
          c0 = Math.max(a.x, b.x);
          c1 = Math.min(a.x + a.w, b.x + b.w);
          if (c1 - c0 < 2) {
            c0 = mL;
            c1 = mR;
          }
        }
        const key = type + ":" + Math.round(from) + ":" + Math.round(to);
        if (eqSeen.has(key)) return;
        eqSeen.add(key);
        eq.push({ type, from, to, cross0: c0, cross1: c1, val: gap });
      }
      ["h", "v"].forEach((axis) => {
        const members = eqMembers(axis);
        if (members.length < 3) return;
        const gaps = [];
        for (let j = 0; j + 1 < members.length; j++) {
          gaps.push(axis === "h" ? members[j + 1].x - (members[j].x + members[j].w) : members[j + 1].y - (members[j].y + members[j].h));
        }
        const mi = members.findIndex((m) => m._moving);
        for (let j = 0; j + 1 < gaps.length; j++) {
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
      overlay().querySelectorAll(".geo-guide, .geo-dist, .geo-dist-line, .geo-eq, .geo-eq-label").forEach((el) => el.remove());
      if (!guidesData) return;
      const k = canvasK();
      const inv = 1 / overlayScale();
      guidesData.guides.forEach((g) => {
        const el = document.createElement("div");
        el.className = "geo-guide " + (g.axis === "h" ? "geo-guide-h" : "geo-guide-v");
        if (g.axis === "h") el.style.top = g.pos * k + "px";
        else el.style.left = g.pos * k + "px";
        overlay().appendChild(el);
      });
      guidesData.distances.forEach((d) => {
        const line = document.createElement("div");
        line.className = "geo-dist-line " + (d.type === "h" ? "geo-dist-line-h" : "geo-dist-line-v");
        if (d.type === "h") {
          line.style.left = d.from * k + "px";
          line.style.width = (d.to - d.from) * k + "px";
          line.style.top = d.y * k + "px";
        } else {
          line.style.top = d.from * k + "px";
          line.style.height = (d.to - d.from) * k + "px";
          line.style.left = d.x * k + "px";
        }
        overlay().appendChild(line);
        const label = document.createElement("div");
        label.className = "geo-dist";
        label.textContent = Math.round(d.val) + "px";
        if (d.type === "h") {
          label.style.left = (d.from + d.to) / 2 * k - 12 * inv + "px";
          label.style.top = d.y * k - 12 * inv + "px";
        } else {
          label.style.left = d.x * k + 4 * inv + "px";
          label.style.top = (d.from + d.to) / 2 * k - 6 * inv + "px";
        }
        overlay().appendChild(label);
      });
      (guidesData.eq || []).forEach((d) => {
        const region = document.createElement("div");
        region.className = "geo-eq";
        if (d.type === "h") {
          region.style.left = d.from * k + "px";
          region.style.width = Math.max(1, d.to - d.from) * k + "px";
          region.style.top = d.cross0 * k + "px";
          region.style.height = Math.max(2, d.cross1 - d.cross0) * k + "px";
        } else {
          region.style.top = d.from * k + "px";
          region.style.height = Math.max(1, d.to - d.from) * k + "px";
          region.style.left = d.cross0 * k + "px";
          region.style.width = Math.max(2, d.cross1 - d.cross0) * k + "px";
        }
        overlay().appendChild(region);
        const label = document.createElement("div");
        label.className = "geo-eq-label";
        label.textContent = Math.round(d.val) + "px";
        if (d.type === "h") {
          label.style.left = (d.from + d.to) / 2 * k - 12 * inv + "px";
          label.style.top = d.cross0 * k - 12 * inv + "px";
        } else {
          label.style.left = d.cross0 * k + 4 * inv + "px";
          label.style.top = (d.from + d.to) / 2 * k - 6 * inv + "px";
        }
        overlay().appendChild(label);
      });
    }
    function clearGuides() {
      overlay().querySelectorAll(".geo-guide, .geo-dist, .geo-dist-line, .geo-eq, .geo-eq-label").forEach((el) => el.remove());
    }
    function parentOf(ref) {
      const ir = getIR();
      if (ref.secIdx == null) return null;
      if (ref.path == null) {
        return { node: ir, siblings: ir.tree, dom: artboardEl(), isRoot: true, index: ref.secIdx };
      }
      const sec = ir.tree[ref.secIdx];
      if (!sec) return null;
      if (isSourceKeyPath(ref.path)) {
        const located = locateByKey(sec, ref.path);
        if (!located || located.index < 0) return null;
        const parentNode2 = located.parentNode;
        const parentPath2 = parentNode2 === sec ? null : String(parentNode2.sourceKey || parentNode2.__path || sourceParentPath(ref.path) || "");
        return {
          node: parentNode2,
          siblings: located.siblings,
          dom: domAt({ secIdx: ref.secIdx, path: parentPath2 }),
          parentPath: parentPath2,
          secIdx: ref.secIdx,
          index: located.index,
          sourceMode: true
        };
      }
      const keys = ref.path.split(".");
      keys.pop();
      keys.pop();
      const parentPath = keys.join(".");
      const parentNode = parentPath ? getByPath(sec, parentPath) : sec;
      const parentDom = domAt(parentPath ? { secIdx: ref.secIdx, path: parentPath } : { secIdx: ref.secIdx, path: null });
      return {
        node: parentNode,
        siblings: parentNode && parentNode.children || [],
        dom: parentDom,
        parentPath,
        secIdx: ref.secIdx,
        index: parseInt(ref.path.split(".").pop(), 10)
      };
    }
    function siblingDom(parent, j) {
      if (parent.isRoot) return previewEl.querySelector(`[data-ir-sec="${j}"]`);
      return domAt({ secIdx: parent.secIdx, path: siblingPath(parent, j) });
    }
    function siblingPath(parent, j) {
      if (parent.isRoot) return null;
      if (parent.sourceMode || parent.parentPath && !String(parent.parentPath).startsWith("children.")) {
        const sib = parent.siblings[j];
        if (sib && sib.sourceKey) return String(sib.sourceKey);
      }
      return parent.parentPath ? parent.parentPath + ".children." + j : "children." + j;
    }
    function refKey(ref) {
      return ref.secIdx + ":" + (ref.path || "");
    }
    function overlay() {
      let ov = previewEl.querySelector(":scope > .geo-overlay");
      if (!ov) {
        ov = document.createElement("div");
        ov.className = "geo-overlay";
        ov.innerHTML = '<div class="geo-box hover" hidden></div><div class="geo-sel-container"></div>';
        previewEl.appendChild(ov);
      }
      ov.style.width = Math.max(previewEl.scrollWidth, previewEl.offsetWidth) + "px";
      ov.style.height = Math.max(previewEl.scrollHeight, previewEl.offsetHeight) + "px";
      ov.dataset.tool = tool;
      syncZoom(ov);
      return ov;
    }
    function hint(text) {
      const el = document.createElement("div");
      el.className = "geo-hint";
      el.textContent = text;
      overlay().appendChild(el);
      setTimeout(() => el.remove(), 2500);
    }
    function syncZoom(ov) {
      (ov || overlay()).style.setProperty("--geo-inv", String(1 / overlayScale()));
    }
    function selContainer() {
      return overlay().querySelector(".geo-sel-container");
    }
    function boxRect(el) {
      const base = previewEl.getBoundingClientRect();
      const r = el.getBoundingClientRect();
      const ow = previewEl.offsetWidth;
      const s = ow > 0 ? previewEl.getBoundingClientRect().width / ow : 1;
      return {
        left: (r.left - base.left) / s,
        top: (r.top - base.top) / s,
        width: r.width / s,
        height: r.height / s
      };
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
      ["nw", "n", "ne", "e", "se", "s", "sw", "w"].forEach((d) => {
        const h = document.createElement("span");
        h.className = "geo-h h-" + d;
        h.dataset.dir = d;
        box.appendChild(h);
      });
    }
    function canEditPadding(ref) {
      if (ref.path && ref.path.startsWith("props.")) return false;
      if (ref.secIdx == null || ref.path == null) return true;
      const node = irNodeAt(ref);
      return !!(node && (node.type === "card" || node.type === "frame" || Array.isArray(node.children) && node.children.length));
    }
    function padding4(ref, el) {
      const p = getFrame(ref).padding;
      if (typeof p === "number") {
        const v = Math.max(0, finiteNum(p));
        return [v, v, v, v];
      }
      if (Array.isArray(p)) {
        if (p.length >= 4) return p.slice(0, 4).map((v) => Math.max(0, finiteNum(v)));
        if (p.length >= 2) {
          const v = Math.max(0, finiteNum(p[0])), h = Math.max(0, finiteNum(p[1]));
          return [v, h, v, h];
        }
        if (p.length === 1) {
          const v = Math.max(0, finiteNum(p[0]));
          return [v, v, v, v];
        }
      }
      const cs = el ? getComputedStyle(el) : null;
      return cs ? [cs.paddingTop, cs.paddingRight, cs.paddingBottom, cs.paddingLeft].map((v) => Math.max(0, finiteNum(v))) : [0, 0, 0, 0];
    }
    function positionPaddingHandles(box, pads) {
      const [top, right, bottom, left] = pads;
      const values = { top, right, bottom, left };
      const insetPx = 10 / overlayScale();
      const insetY = Math.min(insetPx, Math.max(2, (box.offsetHeight || 40) * 0.2));
      const insetX = Math.min(insetPx, Math.max(2, (box.offsetWidth || 40) * 0.2));
      ["top", "right", "bottom", "left"].forEach((side) => {
        const guide = box.querySelector(`.geo-pad-guide.pad-${side}`);
        const handle = box.querySelector(`.geo-pad.pad-${side}`);
        const value = Math.max(0, values[side]);
        if (!guide || !handle) return;
        handle.dataset.value = `${Math.round(value)} px`;
        if (side === "top") {
          guide.style.cssText = `top:${value}px;left:${left}px;right:${right}px`;
          handle.style.top = value + insetY + "px";
          handle.style.left = "50%";
        } else if (side === "bottom") {
          guide.style.cssText = `bottom:${value}px;left:${left}px;right:${right}px`;
          handle.style.bottom = value + insetY + "px";
          handle.style.left = "50%";
        } else if (side === "left") {
          guide.style.cssText = `left:${value}px;top:${top}px;bottom:${bottom}px`;
          handle.style.left = value + insetX + "px";
          handle.style.top = "50%";
        } else {
          guide.style.cssText = `right:${value}px;top:${top}px;bottom:${bottom}px`;
          handle.style.right = value + insetX + "px";
          handle.style.top = "50%";
        }
      });
    }
    function addPaddingHandles(box, ref, el) {
      if (!canEditPadding(ref)) return;
      ["top", "right", "bottom", "left"].forEach((side) => {
        const guide = document.createElement("span");
        guide.className = `geo-pad-guide pad-${side}`;
        box.appendChild(guide);
        const handle = document.createElement("span");
        handle.className = `geo-pad pad-${side}`;
        handle.dataset.side = side;
        handle.title = "Drag to change padding";
        box.appendChild(handle);
      });
      positionPaddingHandles(box, padding4(ref, el));
    }
    function selectionUnionBox() {
      let u = null;
      selections.forEach((sel) => {
        const el = domAt(sel.ref);
        if (!el) return;
        const r = boxRect(el);
        if (!u) {
          u = { left: r.left, top: r.top, right: r.left + r.width, bottom: r.top + r.height };
          return;
        }
        u.left = Math.min(u.left, r.left);
        u.top = Math.min(u.top, r.top);
        u.right = Math.max(u.right, r.left + r.width);
        u.bottom = Math.max(u.bottom, r.top + r.height);
      });
      return u && { left: u.left, top: u.top, width: u.right - u.left, height: u.bottom - u.top };
    }
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
        if (!multi && i === selections.length - 1) {
          addHandles(box);
          addPaddingHandles(box, sel.ref, el);
        }
        placeBox(box, boxRect(el));
        cont.appendChild(box);
      });
      if (multi) {
        const u = selectionUnionBox();
        if (u) {
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
      const ref = hitTest(e.clientX, e.clientY);
      if (!ref || selections.some((s) => refKey(s.ref) === refKey(ref))) {
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
      const seen = /* @__PURE__ */ new Set();
      refs.forEach((ref) => {
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
      const idx = selections.findIndex((s) => refKey(s.ref) === k);
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
    function startMarquee(e) {
      const base = previewEl.getBoundingClientRect();
      const s = scale();
      marquee = {
        startX: (e.clientX - base.left) / s,
        startY: (e.clientY - base.top) / s,
        shiftKey: e.shiftKey,
        prevSelections: e.shiftKey ? selections.slice() : []
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
      const k = canvasK();
      el.style.left = x * k + "px";
      el.style.top = y * k + "px";
      el.style.width = w * k + "px";
      el.style.height = h * k + "px";
    }
    function onMarqueeUp(e) {
      overlay().removeEventListener("pointermove", onMarqueeMove);
      try {
        overlay().releasePointerCapture(e.pointerId);
      } catch (_) {
      }
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
      collectHitTargets().forEach((t) => {
        if (skipLocked(t.ref)) return;
        const shallow = t.ref.path === null || /^children\.\d+$/.test(t.ref.path);
        const inside = t.x >= mx && t.y >= my && t.x + t.w <= mx + mw && t.y + t.h <= my + mh;
        if (!inside && !shallow) return;
        const intersects = t.x < mx + mw && t.x + t.w > mx && t.y < my + mh && t.y + t.h > my;
        if (inside || shallow && intersects) hits.push(t.ref);
      });
      if (marquee.shiftKey) {
        const merged = marquee.prevSelections.slice();
        const seen = new Set(merged.map((s2) => refKey(s2.ref)));
        hits.forEach((ref) => {
          const k = refKey(ref);
          if (!seen.has(k)) {
            seen.add(k);
            merged.push(ref);
          }
        });
        selectMulti(merged.map((s2) => s2.ref || s2));
      } else {
        selectMulti(hits);
      }
      marquee = null;
    }
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
      try {
        overlay().releasePointerCapture(e.pointerId);
      } catch (_) {
      }
      overlay().classList.remove("geo-handling");
      hand = null;
    }
    function containerAt(pt) {
      const targets = collectHitTargets();
      for (let i = targets.length - 1; i >= 0; i--) {
        const t = targets[i];
        if (!(pt.x >= t.x && pt.x <= t.x + t.w && pt.y >= t.y && pt.y <= t.y + t.h)) continue;
        if (t.ref.secIdx == null) continue;
        const node = irNodeAt(t.ref);
        if (node && (t.ref.path == null || node.type === "card" || node.type === "frame")) {
          return t;
        }
      }
      return null;
    }
    function rootSectionFallback(pt) {
      const ir = getIR();
      if (!ir || !ir.tree || !ir.tree.length) return null;
      const secEl = previewEl.querySelector('[data-ir-sec="0"]');
      if (!secEl) return null;
      const base = previewEl.getBoundingClientRect();
      const s = scale();
      const r = secEl.getBoundingClientRect();
      return {
        ref: { secIdx: 0, path: null },
        x: (r.left - base.left) / s,
        y: (r.top - base.top) / s,
        w: r.width / s,
        h: r.height / s
      };
    }
    function startCreate(e) {
      const pt = screenToCanvas(e.clientX, e.clientY);
      const cont = containerAt(pt) || rootSectionFallback();
      if (!cont) {
        notice("Рисовать можно внутри артборда — начните перетаскивание на макете.");
        return;
      }
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
      const k = canvasK();
      create.el.style.left = x * k + "px";
      create.el.style.top = y * k + "px";
      create.el.style.width = w * k + "px";
      create.el.style.height = h * k + "px";
    }
    function onCreateUp(e) {
      overlay().removeEventListener("pointermove", onCreateMove);
      try {
        overlay().releasePointerCapture(e.pointerId);
      } catch (_) {
      }
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
      const contEl = domAt(cont.ref);
      const contCs = contEl ? getComputedStyle(contEl) : null;
      const cbl = contCs ? parseFloat(contCs.borderLeftWidth) || 0 : 0;
      const cbt = contCs ? parseFloat(contCs.borderTopWidth) || 0 : 0;
      const fr = { x: Math.round(rx - cont.x - cbl), y: Math.round(ry - cont.y - cbt) };
      if (!parentFree) fr.absolute = true;
      let child;
      if (tool === "rect") {
        fr.width = Math.round(clicked ? 120 : Math.max(16, rw));
        fr.height = Math.round(clicked ? 90 : Math.max(16, rh));
        child = { type: "rect", sourceKey: nextUid(), fill: NEW_SHAPE_FILL, radius: 8, frame: fr };
      } else if (tool === "ellipse") {
        fr.width = Math.round(clicked ? 120 : Math.max(16, rw));
        fr.height = Math.round(clicked ? 90 : Math.max(16, rh));
        child = { type: "rect", sourceKey: nextUid(), fill: NEW_SHAPE_FILL, radius: 9999, frame: fr };
      } else if (tool === "line") {
        const horizontal = clicked || rw >= rh;
        if (horizontal) {
          fr.width = Math.round(clicked ? 120 : Math.max(8, rw));
          fr.height = 2;
        } else {
          fr.width = 2;
          fr.height = Math.round(Math.max(8, rh));
        }
        child = { type: "rect", sourceKey: nextUid(), fill: NEW_SHAPE_FILL, frame: fr };
      } else if (tool === "image") {
        fr.width = Math.round(clicked ? 240 : Math.max(40, rw));
        fr.height = Math.round(clicked ? 160 : Math.max(40, rh));
        child = { type: "image", sourceKey: nextUid(), alt: "изображение", frame: fr };
      } else if (tool === "text") {
        child = { type: "text", sourceKey: nextUid(), text: "Новый текст", frame: fr };
      } else {
        fr.width = Math.round(clicked ? 240 : Math.max(40, rw));
        fr.height = Math.round(clicked ? 160 : Math.max(40, rh));
        child = {
          type: "card",
          sourceKey: nextUid(),
          children: [],
          frame: fr,
          style: { background: "#00000000", borderColor: NEW_SHAPE_FILL, borderWidth: 1 }
        };
      }
      contNode.children = contNode.children || [];
      contNode.children.push(child);
      const newPath = !cont.ref.path || String(cont.ref.path).startsWith("children.") ? (cont.ref.path ? cont.ref.path + "." : "") + "children." + (contNode.children.length - 1) : String(child.sourceKey);
      selections = [];
      const createdRef = { secIdx: cont.ref.secIdx, path: newPath };
      select(createdRef);
      onMutated();
      if (tool === "text") {
        setTool("select");
        let waits = 40;
        const enter = () => {
          if (domAt(createdRef)) {
            beginTextEdit(createdRef);
            return;
          }
          if (--waits > 0) setTimeout(enter, 25);
        };
        setTimeout(enter, 0);
      }
    }
    function relPos(el, baseEl) {
      const s = scale();
      const base = baseEl.getBoundingClientRect();
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(baseEl);
      const bl = parseFloat(cs.borderLeftWidth) || 0, bt = parseFloat(cs.borderTopWidth) || 0;
      return {
        x: Math.round((r.left - base.left) / s - bl),
        y: Math.round((r.top - base.top) / s - bt)
      };
    }
    function makeParentFree(parent) {
      const s = scale();
      const cs = getComputedStyle(parent.dom);
      const bl = parseFloat(cs.borderLeftWidth) || 0, bt = parseFloat(cs.borderTopWidth) || 0;
      const base = parent.dom.getBoundingClientRect();
      const measured = parent.siblings.map((sib, j) => {
        const sibEl = siblingDom(parent, j);
        if (!sibEl) return null;
        const r = sibEl.getBoundingClientRect();
        return {
          x: Math.round((r.left - base.left) / s - bl),
          y: Math.round((r.top - base.top) / s - bt),
          w: Math.round(r.width / s),
          h: Math.round(r.height / s)
        };
      });
      parent.siblings.forEach((sib, j) => {
        const m = measured[j];
        if (!m) return;
        const sibRef = parent.isRoot ? { secIdx: j, path: null } : { secIdx: parent.secIdx, path: siblingPath(parent, j) };
        const sf = Object.assign({}, getFrame(sibRef));
        if (typeof sf.x !== "number") sf.x = m.x;
        if (typeof sf.y !== "number") sf.y = m.y;
        if (sf.width === "fill") sf.width = m.w;
        if (sf.height === "fill") sf.height = m.h;
        setFrameData(sibRef, sf);
      });
      parent.node.frame = Object.assign({}, parent.node.frame, {
        layout: "free",
        // frame у родителя может отсутствовать (свежий IR от LLM) — берём измеренную высоту
        height: parent.node.frame && parent.node.frame.height || Math.round(parent.dom.getBoundingClientRect().height / s)
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
        const f2 = Object.assign({}, getFrame(d.ref));
        f2.x = Math.round((typeof f2.x === "number" ? f2.x : 0) + dx);
        f2.y = Math.round((typeof f2.y === "number" ? f2.y : 0) + dy);
        setFrameData(d.ref, f2);
        return;
      }
      if (parent.isRoot) {
        const measured = makeParentFree(parent);
        const mr = measured[parent.siblings.indexOf(irNodeAt(d.ref))] || null;
        const fr = Object.assign({}, getFrame(d.ref));
        fr.x = Math.round((mr ? mr.x : typeof fr.x === "number" ? fr.x : 0) + dx);
        fr.y = Math.round((mr ? mr.y : typeof fr.y === "number" ? fr.y : 0) + dy);
        setFrameData(d.ref, fr);
        return;
      }
      const childDom = domAt(d.ref);
      const m = childDom ? relPos(childDom, parent.dom) : null;
      const f = Object.assign({}, getFrame(d.ref));
      const bx = m ? m.x : typeof f.x === "number" ? f.x : 0;
      const by = m ? m.y : typeof f.y === "number" ? f.y : 0;
      if (childDom) {
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
      const movedRefs = selections.filter((s) => s.ref.secIdx != null);
      movedRefs.forEach((sel) => {
        commitMoveFor({ ref: sel.ref }, dx, dy);
      });
      onMutated();
    }
    function liveResize(d, dx, dy) {
      const dir = d.dir;
      let w = d.w0, h = d.h0, tx = 0, ty = 0;
      if (dir.includes("e")) w = d.w0 + dx;
      if (dir.includes("s")) h = d.h0 + dy;
      if (dir.includes("w")) {
        w = d.w0 - dx;
        tx = dx;
      }
      if (dir.includes("n")) {
        h = d.h0 - dy;
        ty = dy;
      }
      w = Math.max(8, w);
      h = Math.max(8, h);
      const parent = parentOf(d.ref);
      if (!parent || !parent.node.frame || parent.node.frame.layout !== "free") {
        tx = 0;
        ty = 0;
      }
      d.wLive = w;
      d.hLive = h;
      d.txLive = tx;
      d.tyLive = ty;
      if (dir.includes("e") || dir.includes("w")) {
        d.el.style.minWidth = "0px";
        d.el.style.maxWidth = "none";
      }
      if (dir.includes("n") || dir.includes("s")) {
        d.el.style.minHeight = "0px";
        d.el.style.maxHeight = "none";
      }
      d.el.style.width = w + "px";
      d.el.style.height = h + "px";
      const node = irNodeAt(d.ref);
      const hasKids = node && Array.isArray(node.children) && node.children.length;
      if (d.dir.length === 2 && hasKids && d.w0 > 0 && d.h0 > 0) {
        const ksx = Math.max(0.1, w / d.w0), ksy = Math.max(0.1, h / d.h0);
        const origin = { se: "0 0", sw: "100% 0", ne: "0 100%", nw: "100% 100%" }[d.dir] || "0 0";
        d.el.style.transformOrigin = origin;
        d.el.style.transform = `translate(${tx}px, ${ty}px) scale(${ksx}, ${ksy})`;
      } else {
        d.el.style.transform = tx || ty ? `translate(${tx}px, ${ty}px)` : "";
      }
      const chip = overlay().querySelector(".geo-box.selected:last-child .geo-chip");
      if (chip) chip.textContent = `${Math.round(w)}×${Math.round(h)}`;
    }
    function livePadding(d, dx, dy, e) {
      const pads = d.padding0.slice();
      const index = { top: 0, right: 1, bottom: 2, left: 3 }[d.side];
      const opposite = [2, 3, 0, 1][index];
      const axisDelta = index === 0 ? dy : index === 1 ? -dx : index === 2 ? -dy : dx;
      let value = d.padding0[index] + axisDelta;
      if (e && e.shiftKey) value = Math.round(value / 4) * 4;
      const dimension = index === 0 || index === 2 ? d.h0 : d.w0;
      value = Math.max(0, Math.min(value, Math.max(0, dimension - pads[opposite] - 8)));
      pads[index] = Math.round(value);
      d.paddingLive = pads;
      d.el.style.padding = `${pads[0]}px ${pads[1]}px ${pads[2]}px ${pads[3]}px`;
      if (d.box) {
        positionPaddingHandles(d.box, pads);
        const active = d.box.querySelector(`.geo-pad.pad-${d.side}`);
        if (active) active.classList.add("active");
      }
      const chip = d.box && d.box.querySelector(".geo-chip");
      if (chip) chip.textContent = `Padding ${pads.map((v) => Math.round(v)).join(" · ")}`;
    }
    function restoreInlinePadding(d) {
      if (!d.el || !d.inlinePadding) return;
      ["padding", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft"].forEach((key) => {
        d.el.style[key] = d.inlinePadding[key];
      });
    }
    function commitPadding(d) {
      restoreInlinePadding(d);
      if (!d.paddingLive) {
        renderSelectionBoxes();
        return;
      }
      const p = d.paddingLive.map((v) => Math.max(0, Math.round(v)));
      onCommit();
      const frame = Object.assign({}, getFrame(d.ref));
      frame.padding = p.every((v) => v === p[0]) ? p[0] : p;
      setFrameData(d.ref, frame);
      onMutated();
    }
    function commitResize(d) {
      const node = irNodeAt(d.ref);
      if (!node || d.wLive == null) {
        onMutated();
        return;
      }
      onCommit();
      const f = Object.assign({}, getFrame(d.ref));
      const oldW = typeof f.width === "number" ? f.width : d.w0;
      const oldH = typeof f.height === "number" ? f.height : d.h0;
      f.width = Math.round(d.wLive);
      f.height = Math.round(d.hLive);
      if ((d.dir.includes("e") || d.dir.includes("w")) && (typeof f.minWidth === "number" && f.minWidth > f.width || typeof f.maxWidth === "number" && f.maxWidth < f.width)) {
        delete f.minWidth;
        delete f.maxWidth;
      }
      if ((d.dir.includes("n") || d.dir.includes("s")) && (typeof f.minHeight === "number" && f.minHeight > f.height || typeof f.maxHeight === "number" && f.maxHeight < f.height)) {
        delete f.minHeight;
        delete f.maxHeight;
      }
      const parent = parentOf(d.ref);
      if (parent && parent.node.frame && parent.node.frame.layout === "free" && (d.txLive || d.tyLive)) {
        f.x = Math.round((typeof f.x === "number" ? f.x : 0) + d.txLive);
        f.y = Math.round((typeof f.y === "number" ? f.y : 0) + d.tyLive);
      }
      setFrameData(d.ref, f);
      applyConstraints(d.ref, oldW, oldH, f.width, f.height);
      const isCorner = d.dir.length === 2;
      if (isCorner) scaleDescendants(d.ref, f.width / (oldW || f.width), f.height / (oldH || f.height), "full");
      else if (d.dir === "e" || d.dir === "w") scaleDescendants(d.ref, f.width / (oldW || f.width), 1, "x");
      else if (d.dir === "n" || d.dir === "s") scaleDescendants(d.ref, 1, f.height / (oldH || f.height), "y");
      onMutated();
    }
    function liveResizeMulti(d, dx, dy) {
      const dir = d.dir, u0 = d.union0;
      let w = u0.w, h = u0.h, tx = 0, ty = 0;
      if (dir.includes("e")) w = u0.w + dx;
      if (dir.includes("s")) h = u0.h + dy;
      if (dir.includes("w")) {
        w = u0.w - dx;
        tx = dx;
      }
      if (dir.includes("n")) {
        h = u0.h - dy;
        ty = dy;
      }
      w = Math.max(8, w);
      h = Math.max(8, h);
      d.wLive = w;
      d.hLive = h;
      d.txLive = tx;
      d.tyLive = ty;
      const k = canvasK();
      d.el.style.width = w * k + "px";
      d.el.style.height = h * k + "px";
      d.el.style.transform = tx || ty ? `translate(${tx * k}px, ${ty * k}px)` : "";
    }
    function commitResizeMulti(d) {
      if (d.wLive == null) {
        onMutated();
        return;
      }
      onCommit();
      const u0 = d.union0;
      const sx = u0.w > 0 ? d.wLive / u0.w : 1;
      const sy = u0.h > 0 ? d.hLive / u0.h : 1;
      const nx = u0.x + (d.txLive || 0), ny = u0.y + (d.tyLive || 0);
      d.items.forEach((it) => {
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
      const multiCorner = d.dir.length === 2;
      d.items.forEach((it) => {
        if (multiCorner) scaleDescendants(it.ref, sx, sy, "full");
        else if (d.dir === "e" || d.dir === "w") scaleDescendants(it.ref, sx, 1, "x");
        else if (d.dir === "n" || d.dir === "s") scaleDescendants(it.ref, 1, sy, "y");
      });
      onMutated();
    }
    function scaleDescendants(ref, sx, sy, mode) {
      if (!Number.isFinite(sx) || !Number.isFinite(sy) || Math.abs(sx - 1) < 1e-3 && Math.abs(sy - 1) < 1e-3) return;
      const root = irNodeAt(ref);
      if (!root || !Array.isArray(root.children) || !root.children.length) return;
      sx = Math.max(0.1, Math.min(8, sx));
      sy = Math.max(0.1, Math.min(8, sy));
      const fontK = mode === "full" ? Math.min(sx, sy) : 1;
      const scaleFrame = (frame) => {
        const f = Object.assign({}, frame);
        if (mode !== "y") {
          if (typeof f.x === "number") f.x = Math.round(f.x * sx);
          if (typeof f.width === "number") f.width = Math.max(4, Math.round(f.width * sx));
        }
        if (mode !== "x") {
          if (typeof f.y === "number") f.y = Math.round(f.y * sy);
          if (typeof f.height === "number") f.height = Math.max(4, Math.round(f.height * sy));
        }
        if (typeof f.padding === "number" && mode === "full") f.padding = Math.max(0, Math.round(f.padding * fontK));
        else if (Array.isArray(f.padding) && mode === "full") f.padding = f.padding.map((v) => Math.max(0, Math.round(v * fontK)));
        if (typeof f.gap === "number") f.gap = Math.max(0, Math.round(f.gap * (mode === "y" ? sy : sx)));
        if (typeof f.borderRadius === "number" && mode === "full") f.borderRadius = Math.max(0, Math.round(f.borderRadius * fontK));
        return f;
      };
      const scaleStyle = (style) => {
        if (!style || typeof style !== "object") return style;
        const out = Object.assign({}, style);
        if (fontK !== 1 && typeof out.fontSize === "number") out.fontSize = Math.max(8, Math.round(out.fontSize * fontK));
        if (mode === "full" && typeof out.borderRadius === "number") out.borderRadius = Math.max(0, Math.round(out.borderRadius * fontK));
        return out;
      };
      const freeParent = root.frame && root.frame.layout === "free";
      const walk = (node, depth) => {
        if (!node || typeof node !== "object" || node.editable === false) return;
        const positioned = depth === 0 && freeParent && node.frame && (typeof node.frame.x === "number" || typeof node.frame.y === "number");
        if (positioned) return;
        if (node.frame && !node.frame.constraints) node.frame = scaleFrame(node.frame);
        if (fontK !== 1 && node.style) node.style = scaleStyle(node.style);
        (node.children || []).forEach((child) => walk(child, depth + 1));
      };
      root.children.forEach((child) => walk(child, 0));
    }
    function applyConstraints(ref, oldW, oldH, newW, newH) {
      const node = irNodeAt(ref);
      if (!node || !node.children) return;
      const dw = newW - oldW, dh = newH - oldH;
      if (!dw && !dh) return;
      node.children.forEach((c) => {
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
    function onPointerDown(e) {
      if (ctxMenuEl && e.target instanceof Node && ctxMenuEl.contains(e.target)) return;
      if (e.button !== 0) return;
      e.preventDefault();
      e.stopPropagation();
      if (tool === "hand") {
        startHand(e);
        return;
      }
      if (["rect", "text", "frame", "ellipse", "line", "image"].includes(tool)) {
        startCreate(e);
        return;
      }
      const paddingHandle = e.target instanceof Element ? e.target.closest(".geo-pad") : null;
      if (paddingHandle && overlay().contains(paddingHandle)) {
        const padBox = paddingHandle.closest(".geo-box");
        const side = paddingHandle.dataset.side;
        const br = padBox && padBox.getBoundingClientRect();
        let edgeDist = Infinity;
        if (br && side) {
          if (side === "top") edgeDist = e.clientY - br.top;
          else if (side === "bottom") edgeDist = br.bottom - e.clientY;
          else if (side === "left") edgeDist = e.clientX - br.left;
          else if (side === "right") edgeDist = br.right - e.clientX;
        }
        if (br && Number.isFinite(edgeDist) && edgeDist <= Math.max(22, 0.35 * (side === "top" || side === "bottom" ? br.height : br.width))) {
          startPadding(side, e, padBox);
          return;
        }
      }
      const handleDir = hitTestHandle(e.clientX, e.clientY);
      if (handleDir) {
        startResize(handleDir, e);
        return;
      }
      const deep = !!(e.ctrlKey || e.metaKey);
      const hitRef = hitTest(e.clientX, e.clientY, deep);
      let ref = hitRef;
      let clickRef = null;
      if (!deep && !e.shiftKey && selections.length) {
        const owns = selections.some((sel) => {
          const sr = sel.ref;
          if (sr.secIdx == null) return false;
          const sNode = irNodeAt(sr);
          if (sr.path != null) {
            const isFreeGroup = sNode && (sNode.type === "card" || sNode.type === "frame" || sNode.type === "button") && sNode.frame && sNode.frame.layout === "free";
            if (!isFreeGroup) return false;
          }
          const el = domAt(sr);
          if (!el) return false;
          const r = el.getBoundingClientRect();
          if (!r || e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) return false;
          if (!hitRef) return true;
          if (refKey(hitRef) === refKey(sr)) return true;
          if (hitRef.secIdx !== sr.secIdx) return false;
          if (sr.path == null) return true;
          return String(hitRef.path || "").startsWith(String(sr.path) + ".");
        });
        if (owns) {
          if (selections.length === 1) {
            ref = selections[0].ref;
            if (hitRef && refKey(hitRef) !== refKey(ref)) clickRef = hitRef;
          } else {
            ref = null;
            ref = selections[0].ref;
            if (hitRef) clickRef = hitRef;
          }
        }
      }
      if (!ref) {
        if (!e.shiftKey) clear();
        startMarquee(e);
        return;
      }
      if (e.shiftKey) {
        toggleSelect(ref);
        return;
      }
      if (deep) {
        const k = refKey(ref);
        const already = selections.some((s) => refKey(s.ref) === k);
        if (already && selections.length === 1) {
          clear();
          return;
        }
        if (!already) select(ref);
      } else {
        const alreadySelected = selections.some((s) => refKey(s.ref) === refKey(ref));
        if (!alreadySelected) {
          select(ref);
        }
      }
      drag = {
        startX: e.clientX,
        startY: e.clientY,
        moved: false,
        type: "move",
        els: [],
        altKey: e.altKey,
        clickRef
      };
      overlay().setPointerCapture(e.pointerId);
      overlay().addEventListener("pointermove", onDragMove);
      overlay().addEventListener("pointerup", onDragUp, { once: true });
    }
    function startResize(dir, e) {
      if (!selections.length) return;
      e.preventDefault();
      if (selections.length > 1) {
        const rects = selectedRects().filter((r2) => r2.ref.path == null || r2.ref.path.startsWith("children."));
        if (rects.length < 2) return;
        const ux = Math.min(...rects.map((r2) => r2.x));
        const uy = Math.min(...rects.map((r2) => r2.y));
        drag = {
          type: "resize-multi",
          dir,
          startX: e.clientX,
          startY: e.clientY,
          moved: true,
          union0: {
            x: ux,
            y: uy,
            w: Math.max(...rects.map((r2) => r2.x + r2.w)) - ux,
            h: Math.max(...rects.map((r2) => r2.y + r2.h)) - uy
          },
          items: rects,
          el: overlay().querySelector(".geo-box.geo-union")
        };
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
      drag = {
        ref: primary.ref,
        type: "resize",
        dir,
        startX: e.clientX,
        startY: e.clientY,
        moved: true,
        el,
        w0: r.width / s,
        h0: r.height / s
      };
      overlay().setPointerCapture(e.pointerId);
      overlay().addEventListener("pointermove", onDragMove);
      overlay().addEventListener("pointerup", onDragUp, { once: true });
    }
    function startPadding(side, e, box) {
      if (selections.length !== 1 || !side) return;
      const primary = selections[0];
      if (!canEditPadding(primary.ref)) return;
      const el = domAt(primary.ref);
      if (!el) return;
      const rect = boxRect(el);
      drag = {
        ref: primary.ref,
        type: "padding",
        side,
        startX: e.clientX,
        startY: e.clientY,
        moved: false,
        el,
        box,
        w0: rect.width,
        h0: rect.height,
        padding0: padding4(primary.ref, el),
        inlinePadding: {
          padding: el.style.padding,
          paddingTop: el.style.paddingTop,
          paddingRight: el.style.paddingRight,
          paddingBottom: el.style.paddingBottom,
          paddingLeft: el.style.paddingLeft
        }
      };
      const active = box && box.querySelector(`.geo-pad.pad-${side}`);
      if (active) active.classList.add("active");
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
          drag.els = selections.filter((s2) => s2.ref.secIdx != null).map((s2) => ({ ref: s2.ref, el: domAt(s2.ref) })).filter((d) => d.el);
          if (drag.els.length === 1) {
            const t = collectHitTargets().find((tt) => refKey(tt.ref) === refKey(drag.els[0].ref));
            if (t) drag.originRect = { x: t.x, y: t.y, w: t.w, h: t.h };
          }
        }
      }
      const s = scale();
      if (drag.type === "move") {
        let tx = dx / s, ty = dy / s;
        let constrain = null;
        if (e.shiftKey) {
          constrain = Math.abs(dx) >= Math.abs(dy) ? "y" : "x";
          if (constrain === "y") ty = 0;
          else tx = 0;
        }
        if (drag.els.length === 1) {
          const d0 = drag.els[0];
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
          drag.smartSnapped = !!(guidesData.snaps.dx || guidesData.snaps.dy || guidesData.eq && guidesData.eq.length);
          if (constrain === "y") ty = 0;
          else if (constrain === "x") tx = 0;
          renderGuides(guidesData);
        } else {
          clearGuides();
        }
        drag.els.forEach((d) => {
          d.el.style.transform = `translate(${tx}px, ${ty}px)`;
        });
        const chip = overlay().querySelector(".geo-box.selected:last-child .geo-chip");
        if (chip) chip.textContent = `Δ ${Math.round(tx)} · ${Math.round(ty)}`;
      } else if (drag.type === "padding") {
        livePadding(drag, dx / s, dy / s, e);
      } else if (drag.type === "resize-multi") {
        if (drag.el) liveResizeMulti(drag, dx / s, dy / s);
      } else {
        if (!drag.el) drag.el = domAt(drag.ref);
        if (drag.el) liveResize(drag, dx / s, dy / s);
      }
    }
    function onDragUp(e) {
      overlay().removeEventListener("pointermove", onDragMove);
      try {
        overlay().releasePointerCapture(e.pointerId);
      } catch (_) {
      }
      if (rafId) {
        cancelAnimationFrame(rafId);
        rafId = null;
      }
      pendingPointer = e;
      applyDragFrame();
      const d = drag;
      lastDragSmartSnapped = !!(d && d.smartSnapped);
      drag = null;
      pendingPointer = null;
      if (!d) return;
      const s = scale();
      let dx = (e.clientX - d.startX) / s, dy = (e.clientY - d.startY) / s;
      if (d.type === "padding" && Math.hypot(dx, dy) >= 3) {
        d.moved = true;
        livePadding(d, dx, dy, e);
      }
      if (e.shiftKey && d.type === "move") {
        if (Math.abs(dx) >= Math.abs(dy)) dy = 0;
        else dx = 0;
      }
      if (!d.moved) {
        clearGuides();
        if (d.type === "padding") renderSelectionBoxes();
        else if (d.type === "move" && d.clickRef) select(d.clickRef);
        return;
      }
      if (d.type === "move") {
        d.els && d.els.forEach((de) => {
          if (de.el) de.el.style.transform = "";
        });
        clearGuides();
        if (d.altKey) commitDuplicateMove(dx, dy);
        else commitMoveAll(dx, dy);
      } else if (d.type === "padding") commitPadding(d);
      else if (d.type === "resize-multi") {
        if (d.el) d.el.style.transform = "";
        commitResizeMulti(d);
      } else {
        d.el.style.transform = "";
        commitResize(d);
      }
    }
    function collectDuplicateTargets() {
      const targets = [];
      selections.forEach((sel) => {
        if (sel.ref.secIdx == null) return;
        if (sel.ref.path != null && sel.ref.path.startsWith("props.")) return;
        if (lockedNodeFor(sel.ref)) return;
        const parent = parentOf(sel.ref);
        if (!parent) return;
        const idx = sel.ref.path == null ? sel.ref.secIdx : parent.index;
        if (!Number.isInteger(idx) || idx < 0 || idx >= parent.siblings.length) return;
        targets.push({
          ref: sel.ref,
          arr: parent.siblings,
          idx,
          source: isSourceKeyPath(sel.ref.path)
        });
      });
      return targets;
    }
    function duplicateSelections() {
      const targets = collectDuplicateTargets();
      targets.sort((a, b) => a.arr === b.arr ? a.idx - b.idx : 0);
      const shifts = /* @__PURE__ */ new Map();
      const newRefs = [];
      targets.forEach((t) => {
        const at = t.idx + (shifts.get(t.arr) || 0);
        const node = t.arr[at];
        if (!node) return;
        const clone2 = JSON.parse(JSON.stringify(node));
        const sec = getIR().tree[t.ref.secIdx];
        const keyed = clone2.sourceKey != null && (t.source || sec && (sec.type === "source-block" || sec.variant === "dom-capture"));
        if (keyed) rekeyCloneKeys(clone2, nextUid);
        t.arr.splice(at + 1, 0, clone2);
        shifts.set(t.arr, (shifts.get(t.arr) || 0) + 1);
        if (t.ref.path == null) newRefs.push({ secIdx: at + 1, path: null });
        else if (keyed) {
          newRefs.push({ secIdx: t.ref.secIdx, path: String(clone2.sourceKey) });
        } else {
          const segs = t.ref.path.split(".");
          segs[segs.length - 1] = String(at + 1);
          newRefs.push({ secIdx: t.ref.secIdx, path: segs.join(".") });
        }
      });
      return newRefs;
    }
    function zOrder(dir) {
      if (selections.length !== 1) return;
      const ref = selections[0].ref;
      if (ref.secIdx == null) return;
      if (refuseLocked(ref)) return;
      const parent = parentOf(ref);
      if (!parent) return;
      const idx = ref.path == null ? ref.secIdx : parent.index;
      const to = idx + dir;
      if (!Number.isInteger(idx) || to < 0 || to >= parent.siblings.length) return;
      onCommit();
      const [node] = parent.siblings.splice(idx, 1);
      parent.siblings.splice(to, 0, node);
      const newRef = ref.path == null ? { secIdx: to, path: null } : isSourceKeyPath(ref.path) ? ref : Object.assign({}, ref, {
        path: ref.path.split(".").slice(0, -1).concat(String(to)).join(".")
      });
      select(newRef);
      onMutated();
    }
    function bringForward() {
      zOrder(1);
    }
    function sendBackward() {
      zOrder(-1);
    }
    function reparent(ref, targetRef, index) {
      if (!ref || !targetRef || ref.secIdx == null) return false;
      if (refuseLocked(ref) || refuseLocked(targetRef)) return false;
      const node = irNodeAt(ref);
      const targetNode = irNodeAt(targetRef);
      if (!node || !targetNode || node === targetNode) return false;
      let cycle = false;
      (function scan(n) {
        if (cycle || !n || typeof n !== "object") return;
        if (n === targetNode) {
          cycle = true;
          return;
        }
        (n.children || []).forEach(scan);
      })(node);
      if (cycle) return false;
      const parent = parentOf(ref);
      if (!parent || !Array.isArray(parent.siblings)) return false;
      if (parent.node === targetNode) return false;
      const from = parent.index;
      if (!Number.isInteger(from) || parent.siblings[from] !== node) return false;
      const beforeEl = domAt(ref);
      const targetDom = domAt(targetRef);
      const keepPos = beforeEl && targetDom ? relPos(beforeEl, targetDom) : null;
      onCommit();
      parent.siblings.splice(from, 1);
      const kids = targetNode.children || (targetNode.children = []);
      const at = Number.isInteger(index) && index >= 0 && index <= kids.length ? index : kids.length;
      kids.splice(at, 0, node);
      const targetFrame = targetNode.frame || {};
      if (keepPos && node.frame && targetFrame.layout === "free") {
        node.frame.x = keepPos.x;
        node.frame.y = keepPos.y;
        node.frame.absolute = true;
      }
      selections = [];
      onMutated();
      return true;
    }
    function moveSibling(ref, newIndex) {
      if (ref.secIdx == null) return;
      if (refuseLocked(ref)) return;
      const parent = parentOf(ref);
      if (!parent) return;
      const idx = ref.path == null ? ref.secIdx : parent.index;
      if (!Number.isInteger(idx) || !Number.isInteger(newIndex) || newIndex < 0 || newIndex >= parent.siblings.length || idx === newIndex) return;
      onCommit();
      const [node] = parent.siblings.splice(idx, 1);
      parent.siblings.splice(newIndex, 0, node);
      const shift = (j) => j === idx ? newIndex : idx < newIndex ? j > idx && j <= newIndex ? j - 1 : j : j >= newIndex && j < idx ? j + 1 : j;
      const prefixSegs = ref.path == null ? null : ref.path.split(".").slice(0, -1);
      selections = selections.map((s) => {
        const r = s.ref;
        if (prefixSegs == null) {
          if (r.secIdx == null) return s;
          const j2 = shift(r.secIdx);
          return j2 === r.secIdx ? s : Object.assign({}, s, { ref: Object.assign({}, r, { secIdx: j2 }) });
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
    function groupSelection() {
      if (selections.some((s2) => s2.ref.secIdx != null && s2.ref.path == null)) {
        hint("Группировка недоступна для секций верхнего уровня");
        return;
      }
      const refs = selections.map((s2) => s2.ref).filter((r) => r.secIdx != null && r.path != null && !r.path.startsWith("props.") && !lockedNodeFor(r));
      if (refs.length < 2) return;
      const secIdx = refs[0].secIdx;
      const parents = refs.map((r) => r.secIdx === secIdx ? parentOf(r) : null);
      const parent = parents[0];
      if (!parent || !parent.dom || parents.some((p) => !p || p.siblings !== parent.siblings)) {
        hint("Группировка возможна только для сиблингов одного контейнера");
        return;
      }
      const s = scale();
      const cs = getComputedStyle(parent.dom);
      const bl = parseFloat(cs.borderLeftWidth) || 0, bt = parseFloat(cs.borderTopWidth) || 0;
      const base = parent.dom.getBoundingClientRect();
      const idxs = refs.map((r, i) => parents[i].index).filter(Number.isInteger).sort((a, b) => a - b);
      if (idxs.length !== refs.length) return;
      const meas = [];
      for (const i of idxs) {
        const el = siblingDom(parent, i);
        if (!el) return;
        const r = el.getBoundingClientRect();
        meas.push({
          x: (r.left - base.left) / s - bl,
          y: (r.top - base.top) / s - bt,
          w: r.width / s,
          h: r.height / s
        });
      }
      const gx = Math.min(...meas.map((m) => m.x)), gy = Math.min(...meas.map((m) => m.y));
      const gw = Math.max(...meas.map((m) => m.x + m.w)) - gx;
      const gh = Math.max(...meas.map((m) => m.y + m.h)) - gy;
      const groupSec = getIR().tree[secIdx];
      const sourceMode = !!(groupSec && (groupSec.type === "source-block" || groupSec.variant === "dom-capture"));
      onCommit();
      const taken = idxs.map((i) => parent.siblings[i]);
      const group = {
        type: "card",
        frame: {
          layout: "free",
          x: Math.round(gx),
          y: Math.round(gy),
          width: Math.round(gw),
          height: Math.round(gh)
        },
        children: taken.map((n, k) => {
          const c = JSON.parse(JSON.stringify(n));
          delete c.__path;
          c.frame = Object.assign({}, c.frame, {
            x: Math.round(meas[k].x - gx),
            y: Math.round(meas[k].y - gy)
          });
          if (c.frame.width === "fill" || c.frame.width === "hug") c.frame.width = Math.round(meas[k].w);
          if (c.frame.height === "fill" || c.frame.height === "hug") c.frame.height = Math.round(meas[k].h);
          return c;
        })
      };
      if (sourceMode) {
        const pk = parent.parentPath ? String(parent.parentPath) : parent.node && parent.node.sourceKey ? String(parent.node.sourceKey) : "";
        group.sourceKey = (pk ? pk + "/group~" : "group~") + nextUid();
      }
      for (let k = idxs.length - 1; k >= 0; k--) parent.siblings.splice(idxs[k], 1);
      parent.siblings.splice(idxs[0], 0, group);
      select({ secIdx, path: sourceMode ? group.sourceKey : (parent.parentPath ? parent.parentPath + ".children." : "children.") + idxs[0] });
      onMutated();
    }
    function ungroupSelection() {
      if (selections.length !== 1) return;
      const ref = selections[0].ref;
      if (ref.secIdx == null || ref.path == null) return;
      const node = irNodeAt(ref);
      if (isLockedNode(node)) return;
      if (!node || !node.children || !node.children.length || !node.frame || node.frame.layout !== "free") return;
      const parent = parentOf(ref);
      if (!parent) return;
      const idx = parent.index;
      if (!Number.isInteger(idx) || idx < 0) return;
      onCommit();
      const gx = finiteNum(node.frame.x), gy = finiteNum(node.frame.y);
      const parentFree = !!(parent.node.frame && parent.node.frame.layout === "free");
      const kids = node.children.map((c) => {
        const k = JSON.parse(JSON.stringify(c));
        k.frame = Object.assign({}, k.frame);
        ["width", "height"].forEach((d) => {
          if (typeof k.frame[d] === "string") {
            const n = parseFloat(k.frame[d]);
            if (Number.isFinite(n)) k.frame[d] = n;
          }
        });
        if (parentFree) {
          k.frame.x = Math.round(finiteNum(k.frame.x) + gx);
          k.frame.y = Math.round(finiteNum(k.frame.y) + gy);
        }
        return k;
      });
      parent.siblings.splice(idx, 1, ...kids);
      selectMulti(kids.map((_, k) => ({
        secIdx: ref.secIdx,
        path: siblingPath(parent, idx + k)
      })));
      onMutated();
    }
    function commitDuplicateMove(dx, dy) {
      if (!collectDuplicateTargets().length) return;
      onCommit();
      const newRefs = duplicateSelections();
      newRefs.forEach((r) => {
        const node = irNodeAt(r);
        if (node && node.frame && (typeof node.frame.x === "number" || typeof node.frame.y === "number")) {
          node.frame = Object.assign({}, node.frame, {
            x: Math.round((node.frame.x || 0) + dx),
            y: Math.round((node.frame.y || 0) + dy)
          });
        }
      });
      if (newRefs.length) selectMulti(newRefs);
      onMutated();
    }
    function selectedRects() {
      const targets = collectHitTargets();
      return selections.filter((s) => s.ref.secIdx != null).map((s) => {
        const t = targets.find((tt) => refKey(tt.ref) === refKey(s.ref));
        if (!t) return null;
        return { ref: s.ref, x: t.x, y: t.y, w: t.w, h: t.h };
      }).filter(Boolean);
    }
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
        const pc = parentBox(rects[0].ref);
        if (pc) {
          ensureParentFree(rects[0].ref);
          const f = Object.assign({}, getFrame(rects[0].ref));
          single(f, rects[0], pc);
          setFrameData(rects[0].ref, f);
        }
      } else {
        rects.forEach((r) => {
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
        const minX = Math.min(...rects.map((q) => q.x));
        f.x = Math.round(minX);
      }, (f) => {
        f.x = 0;
      });
    }
    function alignCenterH() {
      applyAlign((f, r, rects) => {
        const minX = Math.min(...rects.map((q) => q.x));
        const maxX = Math.max(...rects.map((q) => q.x + q.w));
        const center = (minX + maxX) / 2;
        f.x = Math.round(center - r.w / 2);
      }, (f, r, pc) => {
        f.x = Math.round((pc.w - r.w) / 2);
      });
    }
    function alignRight() {
      applyAlign((f, r, rects) => {
        const maxX = Math.max(...rects.map((q) => q.x + q.w));
        f.x = Math.round(maxX - r.w);
      }, (f, r, pc) => {
        f.x = Math.round(pc.w - r.w);
      });
    }
    function stretchWidth() {
      if (!selections.length) return;
      onCommit();
      selections.forEach((sel) => {
        const parent = parentOf(sel.ref);
        const pc = parentBox(sel.ref);
        if (!parent || !pc) return;
        const f = Object.assign({}, getFrame(sel.ref));
        if (parent.node && parent.node.frame && parent.node.frame.layout === "free") {
          f.x = 0;
          f.width = Math.max(8, Math.round(pc.w));
        } else {
          delete f.x;
          f.width = "fill";
        }
        setFrameData(sel.ref, f);
      });
      onMutated();
    }
    function alignTop() {
      applyAlign((f, r, rects) => {
        const minY = Math.min(...rects.map((q) => q.y));
        f.y = Math.round(minY);
      }, (f) => {
        f.y = 0;
      });
    }
    function alignCenterV() {
      applyAlign((f, r, rects) => {
        const minY = Math.min(...rects.map((q) => q.y));
        const maxY = Math.max(...rects.map((q) => q.y + q.h));
        const center = (minY + maxY) / 2;
        f.y = Math.round(center - r.h / 2);
      }, (f, r, pc) => {
        f.y = Math.round((pc.h - r.h) / 2);
      });
    }
    function alignBottom() {
      applyAlign((f, r, rects) => {
        const maxY = Math.max(...rects.map((q) => q.y + q.h));
        f.y = Math.round(maxY - r.h);
      }, (f, r, pc) => {
        f.y = Math.round(pc.h - r.h);
      });
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
      rects.forEach((r) => {
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
      rects.forEach((r) => {
        const f = Object.assign({}, getFrame(r.ref));
        ensureParentFree(r.ref);
        f.y = Math.round(cy);
        setFrameData(r.ref, f);
        cy += r.h + gap;
      });
      onMutated();
    }
    function setFrame(partial) {
      if (!selections.length) return;
      onCommit();
      selections.forEach((sel) => {
        var _a;
        const node = irNodeAt(sel.ref);
        if (!node && !((_a = sel.ref.path) == null ? void 0 : _a.startsWith("props."))) return;
        const f = Object.assign({}, getFrame(sel.ref));
        for (const k of ["x", "y", "width", "height"]) {
          const val = partial[k];
          if (val === void 0) continue;
          if (val === null) delete f[k];
          else if (!Number.isNaN(Number(val))) f[k] = Math.round(Number(val));
        }
        if (!Object.keys(f).length) setFrameData(sel.ref, null);
        else setFrameData(sel.ref, f);
        if (sel.ref.secIdx != null && (partial.x !== void 0 || partial.y !== void 0) && !f.absolute) {
          ensureParentFree(sel.ref);
        }
      });
      onMutated();
    }
    function setFrameProps(partial) {
      if (!selections.length) return;
      onCommit();
      selections.forEach((sel) => {
        const f = Object.assign({}, getFrame(sel.ref));
        for (const [k, v] of Object.entries(partial)) {
          if (v === void 0) continue;
          if (v === null) delete f[k];
          else f[k] = v;
        }
        if (!Object.keys(f).length) setFrameData(sel.ref, null);
        else setFrameData(sel.ref, f);
        if (sel.ref.secIdx != null && ((partial.x !== void 0 || partial.y !== void 0) && !f.absolute || partial.layout === "free")) {
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
      selections.forEach((sel) => {
        if (refuseLocked(sel.ref)) return;
        const node = irNodeAt(sel.ref);
        if (!node) return;
        const style = Object.assign({}, node.style || {});
        for (const [k, v] of Object.entries(partial)) {
          if (v === void 0) continue;
          if (v === null || v === "") delete style[k];
          else style[k] = v;
        }
        if (node.type === "rect") {
          if (partial.background !== void 0) {
            if (partial.background === null || partial.background === "") delete node.fill;
            else node.fill = partial.background;
          }
          if (partial.borderRadius !== void 0) {
            if (partial.borderRadius === null || partial.borderRadius === "") delete node.radius;
            else node.radius = Math.max(0, Math.round(Number(partial.borderRadius) || 0));
          }
        }
        if (Object.keys(style).length) node.style = style;
        else delete node.style;
      });
      onMutated();
    }
    function posOf(ref) {
      const el = domAt(ref);
      const parent = parentOf(ref);
      if (!el || !parent || !parent.dom) return null;
      return relPos(el, parent.dom);
    }
    function frameOf(ref) {
      return getFrame(ref);
    }
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
      selections.forEach((sel) => {
        const f = getFrame(sel.ref);
        if (f && Object.keys(f).length) setFrameData(sel.ref, null);
      });
      onMutated();
    }
    function selectAllInContext() {
      const ir = getIR();
      if (!ir || !ir.tree) return;
      const refs = [];
      if (containerCtx) {
        const node = irNodeAt(containerCtx);
        (node && node.children || []).forEach((_, j) => {
          refs.push({
            secIdx: containerCtx.secIdx,
            path: (containerCtx.path ? containerCtx.path + "." : "") + "children." + j
          });
        });
      } else {
        ir.tree.forEach((sec, si) => {
          (sec && sec.children || []).forEach((_, j) => refs.push({ secIdx: si, path: "children." + j }));
        });
      }
      const visible = refs.filter((r) => !skipLocked(r));
      if (visible.length) selectMulti(visible);
    }
    function copySelection() {
      const lockedSel = selections.find((s) => lockedNodeFor(s.ref));
      if (lockedSel) {
        refuseLocked(lockedSel.ref);
        return 0;
      }
      const items = collectSelectionItems();
      if (items.length) geoClipboard = items;
      return items.length;
    }
    function collectSelectionItems() {
      const items = [];
      selections.forEach((sel) => {
        if (sel.ref.secIdx == null) return;
        if (sel.ref.path != null && sel.ref.path.startsWith("props.")) return;
        const node = irNodeAt(sel.ref);
        if (!node) return;
        if (sel.ref.path == null) {
          items.push({ node: JSON.parse(JSON.stringify(node)), intoTree: true });
          return;
        }
        const parent = parentOf(sel.ref);
        if (!parent) return;
        items.push({
          node: JSON.parse(JSON.stringify(node)),
          parentRef: { secIdx: sel.ref.secIdx, path: parent.parentPath || null }
        });
      });
      return items;
    }
    function deleteSelections() {
      if (!selections.length) return;
      const targets = [];
      selections.forEach((sel) => {
        if (sel.ref.secIdx == null) return;
        if (sel.ref.path != null && sel.ref.path.startsWith("props.")) return;
        if (lockedNodeFor(sel.ref)) return;
        const parent = parentOf(sel.ref);
        if (!parent) return;
        const idx = sel.ref.path == null ? sel.ref.secIdx : parent.index;
        if (!Number.isInteger(idx) || idx < 0 || idx >= parent.siblings.length) return;
        targets.push({ arr: parent.siblings, idx });
      });
      if (!targets.length) return;
      onCommit();
      targets.sort((a, b) => a.arr === b.arr ? b.idx - a.idx : 0);
      targets.forEach((t) => t.arr.splice(t.idx, 1));
      clear();
      onMutated();
    }
    function cutSelection() {
      if (!copySelection()) return;
      deleteSelections();
    }
    function insertItems(items) {
      const ir = getIR();
      if (!ir || !ir.tree || !ir.tree.length) return [];
      const rekey = (n, isSection) => {
        if (!n || typeof n !== "object") return;
        if (!isSection && n.sourceKey != null) {
          rekeyCloneKeys(n, nextUid);
          return;
        }
        if (isSection) {
          if ("id" in n) n.id = nextUid();
        } else {
          delete n.id;
          n.sourceKey = nextUid();
        }
        delete n.__path;
        (n.children || []).forEach((c) => rekey(c, false));
      };
      const newRefs = [];
      items.forEach((item) => {
        const node = JSON.parse(JSON.stringify(item.node));
        if (isLockedNode(node)) return;
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
        if (isLockedNode(contNode)) return;
        contNode.children = contNode.children || [];
        const contSec = ir.tree[contRef.secIdx];
        const sourceSec = !!(contSec && (contSec.type === "source-block" || contSec.variant === "dom-capture"));
        const childPath = sourceSec ? String(node.sourceKey || "") : !contRef.path || String(contRef.path).startsWith("children.") ? (contRef.path ? contRef.path + "." : "") + "children." + contNode.children.length : String(node.sourceKey || "");
        if (!childPath) return;
        contNode.children.push(node);
        newRefs.push({ secIdx: contRef.secIdx, path: childPath });
      });
      return newRefs;
    }
    function pasteClipboard() {
      if (!geoClipboard.length) return;
      const ir = getIR();
      if (!ir || !ir.tree || !ir.tree.length) return;
      onCommit();
      const newRefs = insertItems(geoClipboard);
      if (!newRefs.length) {
        if (cancelCommit) cancelCommit();
        return;
      }
      selectMulti(newRefs);
      onMutated();
    }
    function duplicateSelection() {
      const lockedSel = selections.find((s) => lockedNodeFor(s.ref));
      if (lockedSel) {
        refuseLocked(lockedSel.ref);
        return;
      }
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
    let ctxMenuEl = null;
    function closeContextMenu() {
      if (ctxMenuEl) {
        ctxMenuEl.remove();
        ctxMenuEl = null;
      }
      document.removeEventListener("pointerdown", onDocDownCloseCtx, true);
    }
    function onDocDownCloseCtx(ev) {
      if (ctxMenuEl && ev.target instanceof Node && ctxMenuEl.contains(ev.target)) return;
      closeContextMenu();
    }
    function openContextMenu(clientX, clientY, items) {
      closeContextMenu();
      const m = document.createElement("div");
      m.className = "geo-ctx-menu";
      items.forEach((it) => {
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
          b.addEventListener("click", (ev) => {
            ev.stopPropagation();
            closeContextMenu();
            it.run();
          });
        }
        m.appendChild(b);
      });
      overlay().appendChild(m);
      const pt = screenToCanvas(clientX, clientY);
      const W = previewEl.clientWidth, H = previewEl.clientHeight;
      m.style.left = Math.max(0, Math.min(Math.round(pt.x), Math.max(0, W - m.offsetWidth))) + "px";
      m.style.top = Math.max(0, Math.min(Math.round(pt.y), Math.max(0, H - m.offsetHeight))) + "px";
      ctxMenuEl = m;
      document.addEventListener("pointerdown", onDocDownCloseCtx, true);
    }
    function buildCtxItems() {
      const hasSel = selections.length > 0;
      const multiSel = selections.length > 1;
      const last = hasSel ? selections[selections.length - 1] : null;
      const lastNode = last ? irNodeAt(last.ref) : null;
      const canUngroup = hasSel && !multiSel && lastNode && Array.isArray(lastNode.children) && lastNode.children.length > 0 && lastNode.frame && lastNode.frame.layout === "free";
      const groupable = !selections.some((s) => s.ref.secIdx != null && s.ref.path == null) && selections.filter((s) => s.ref.secIdx != null && s.ref.path != null && !s.ref.path.startsWith("props.") && !lockedNodeFor(s.ref)).length >= 2;
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
        { label: "Удалить", hint: "Del", disabled: !hasSel, run: deleteSelections }
      ];
      if (hasSel && !multiSel && last) {
        const pathLabel = last.ref.path == null ? `tree[${last.ref.secIdx}]` : `tree[${last.ref.secIdx}].${last.ref.path}`;
        items.push({ sep: true });
        items.push({
          label: "Копировать IR-путь",
          hint: pathLabel,
          run: () => {
            if (navigator.clipboard) navigator.clipboard.writeText(pathLabel);
            hint("IR-путь скопирован");
          }
        });
      }
      return items;
    }
    function onContextMenu(e) {
      if (destroyed) return;
      e.preventDefault();
      e.stopPropagation();
      const ref = hitTest(e.clientX, e.clientY, false);
      if (ref) {
        const already = selections.some((s) => refKey(s.ref) === refKey(ref));
        if (!already) select(ref);
      }
      openContextMenu(e.clientX, e.clientY, buildCtxItems());
    }
    function consumeEscape() {
      if (containerCtx) {
        containerCtx = null;
        clear();
        renderContainerBadge();
        return true;
      }
      if (selections.length) {
        clear();
        return true;
      }
      return false;
    }
    function onKeydown(e) {
      const ae = document.activeElement;
      if (ae && (ae.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName))) return;
      if (toolsEnabled) {
        const toolKeys = {
          v: "select",
          r: "rect",
          o: "ellipse",
          l: "line",
          i: "image",
          t: "text",
          f: "frame",
          h: "hand"
        };
        const tk = toolKeys[e.key.toLowerCase()];
        if (tk && !e.ctrlKey && !e.metaKey && !e.altKey) {
          setTool(tk);
          return;
        }
      }
      if (e.ctrlKey || e.metaKey) {
        const ck = e.key.toLowerCase();
        if (ck === "a" && !e.altKey) {
          e.preventDefault();
          e.stopPropagation();
          selectAllInContext();
          return;
        }
        if (!e.shiftKey && !e.altKey) {
          if (ck === "c" && selections.length) {
            copySelection();
            return;
          }
          if (ck === "x" && selections.length) {
            e.preventDefault();
            e.stopPropagation();
            cutSelection();
            return;
          }
          if (ck === "v" && geoClipboard.length) {
            e.preventDefault();
            e.stopPropagation();
            pasteClipboard();
            return;
          }
          if (ck === "d" && selections.length) {
            e.preventDefault();
            e.stopPropagation();
            duplicateSelection();
            return;
          }
        }
      }
      if (e.key === "Escape") {
        if (ctxMenuEl) {
          e.preventDefault();
          e.stopPropagation();
          closeContextMenu();
          return;
        }
        if (!escapeViaHandle) consumeEscape();
        return;
      }
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
        selections.forEach((sel) => {
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
      if ((e.key === "Delete" || e.key === "Backspace") && selections.length) {
        e.preventDefault();
        e.stopPropagation();
        deleteSelections();
        return;
      }
      if ((e.key === "g" || e.key === "G" || e.key === "п" || e.key === "П") && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        if (e.shiftKey) ungroupSelection();
        else groupSelection();
        return;
      }
      if ((e.key === "d" || e.key === "D") && (e.ctrlKey || e.metaKey) && selections.length) {
        e.preventDefault();
        e.stopPropagation();
        onCommit();
        const newRefs = duplicateSelections();
        newRefs.forEach((r) => {
          const node = irNodeAt(r);
          const parent = parentOf(r);
          const parentFree = !!(parent && parent.node.frame && parent.node.frame.layout === "free");
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
    function onDblClick(e) {
      const ref = hitTest(e.clientX, e.clientY, true);
      if (!ref) return;
      e.preventDefault();
      const node = irNodeAt(ref);
      if (refuseLocked(ref)) return;
      if (ref.path === null && node && node.type) {
        containerCtx = ref;
        clear();
        renderContainerBadge();
        return;
      }
      if (node && node.type === "image" && opts.onImageUpload) {
        select(ref);
        opts.onImageUpload(ref);
        return;
      }
      beginTextEdit(ref);
    }
    function beginTextEdit(ref) {
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
            if (n.text !== void 0) n.text = newText;
            else if (n.title !== void 0) n.title = newText;
          }
        } else if (path.startsWith("props.")) {
          setByPath(sec, editableTextPath(path), newText);
        } else {
          const n = irNodeAt({ secIdx, path });
          if (n) {
            if (n.text !== void 0) n.text = newText;
            else if (n.title !== void 0) n.title = newText;
          }
        }
        onMutated();
      };
      textEl.addEventListener("blur", commit, { once: true });
      textEl.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" && !ev.shiftKey) {
          ev.preventDefault();
          textEl.blur();
        }
        if (ev.key === "Escape") {
          textEl.textContent = textEl.dataset.origText || textEl.textContent;
          textEl.blur();
        }
      });
      textEl.dataset.origText = textEl.textContent;
    }
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
    blockContentEarly();
    overlay().addEventListener("pointerdown", onPointerDown);
    overlay().addEventListener("pointermove", onHover);
    overlay().addEventListener("pointerleave", hideHover);
    overlay().addEventListener("dblclick", onDblClick);
    overlay().addEventListener("contextmenu", onContextMenu);
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
      lastDragSmartSnapped: () => lastDragSmartSnapped,
      syncZoom: () => syncZoom(),
      resetFrame,
      stretchWidth,
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
      reparent,
      groupSelection,
      ungroupSelection,
      selectAll: selectAllInContext,
      copySelection,
      cutSelection,
      pasteClipboard,
      duplicateSelection,
      destroy,
      get selection() {
        return selections[0] || null;
      },
      get selections() {
        return selections;
      }
    };
  }
  const GeoEdit = { attach };
  const DEFAULT_LIMIT = 50;
  const DEFAULT_COALESCE_MS = 500;
  function clone(v) {
    return JSON.parse(JSON.stringify(v));
  }
  function createHistory(opts) {
    const limit = opts && opts.limit || DEFAULT_LIMIT;
    const coalesceMs = opts && opts.coalesceMs != null ? opts.coalesceMs : DEFAULT_COALESCE_MS;
    let undoStack = [];
    let redoStack = [];
    let lastPushTime = 0;
    let lastSelKey = null;
    let cancelledRedo = null;
    let lastPushedSnapshot = null;
    function push(snapshotFn, selKey) {
      const now = Date.now();
      const key = selKey === void 0 ? null : selKey;
      const coalesce = undoStack.length > 0 && key != null && key === lastSelKey && now - lastPushTime < coalesceMs;
      lastPushTime = now;
      lastSelKey = key;
      cancelledRedo = redoStack.slice();
      redoStack.length = 0;
      if (coalesce) {
        lastPushedSnapshot = null;
        return false;
      }
      const snapshot = clone(snapshotFn());
      undoStack.push(snapshot);
      if (undoStack.length > limit) undoStack.shift();
      lastPushedSnapshot = snapshot;
      return true;
    }
    function cancelLast() {
      if (lastPushedSnapshot && undoStack.length && undoStack[undoStack.length - 1] === lastPushedSnapshot) {
        undoStack.pop();
      }
      if (cancelledRedo) redoStack = cancelledRedo;
      cancelledRedo = null;
      lastPushedSnapshot = null;
      lastSelKey = null;
    }
    function undo(currentFn) {
      cancelledRedo = null;
      lastPushedSnapshot = null;
      if (!undoStack.length) return null;
      redoStack.push(clone(currentFn()));
      lastSelKey = null;
      return undoStack.pop();
    }
    function redo(currentFn) {
      cancelledRedo = null;
      lastPushedSnapshot = null;
      if (!redoStack.length) return null;
      undoStack.push(clone(currentFn()));
      lastSelKey = null;
      return redoStack.pop();
    }
    function canUndo() {
      return undoStack.length > 0;
    }
    function canRedo() {
      return redoStack.length > 0;
    }
    function clear() {
      cancelledRedo = null;
      lastPushedSnapshot = null;
      undoStack.length = 0;
      redoStack.length = 0;
      lastSelKey = null;
    }
    return { push, undo, redo, canUndo, canRedo, clear, cancelLast };
  }
  const IRHistory = { createHistory };
  const TIMELINE_PROPERTY_DEFAULTS = {
    x: 0,
    y: 0,
    scale: 1,
    rotation: 0,
    opacity: 1
  };
  const EASING_BEZIERS = {
    linear: [0, 0, 1, 1],
    ease: [0.25, 0.1, 0.25, 1],
    "ease-in": [0.42, 0, 1, 1],
    "ease-out": [0, 0, 0.58, 1],
    "ease-in-out": [0.42, 0, 0.58, 1]
  };
  function cubicBezierY(x1, y1, x2, y2, progress) {
    if (progress <= 0) return 0;
    if (progress >= 1) return 1;
    const cx = 3 * x1;
    const bx = 3 * (x2 - x1) - cx;
    const ax = 1 - cx - bx;
    const cy = 3 * y1;
    const by = 3 * (y2 - y1) - cy;
    const ay = 1 - cy - by;
    const sampleX = (u2) => ((ax * u2 + bx) * u2 + cx) * u2;
    const sampleY = (u2) => ((ay * u2 + by) * u2 + cy) * u2;
    const sampleDX = (u2) => (3 * ax * u2 + 2 * bx) * u2 + cx;
    let u = progress;
    for (let i = 0; i < 8; i++) {
      const x = sampleX(u) - progress;
      if (Math.abs(x) < 1e-6) return sampleY(u);
      const d = sampleDX(u);
      if (Math.abs(d) < 1e-6) break;
      u -= x / d;
      if (u < 0) u = 0;
      if (u > 1) u = 1;
    }
    let lo = 0;
    let hi = 1;
    u = progress;
    while (hi - lo > 1e-6) {
      if (sampleX(u) < progress) lo = u;
      else hi = u;
      u = (lo + hi) / 2;
    }
    return sampleY(u);
  }
  function easingProgress(easing, bezier, progress) {
    if (progress <= 0) return 0;
    if (progress >= 1) return 1;
    const name = easing || "linear";
    if (name === "linear") return progress;
    let points;
    if (name === "cubic-bezier") {
      points = bezier && bezier.length === 4 ? [bezier[0], bezier[1], bezier[2], bezier[3]] : EASING_BEZIERS["ease-in-out"];
    } else {
      points = EASING_BEZIERS[name];
    }
    return cubicBezierY(points[0], points[1], points[2], points[3], progress);
  }
  function solveTrack(track, t, fallback) {
    const kfs = track && track.keyframes;
    if (!kfs || kfs.length === 0) return fallback;
    if (t <= kfs[0].t) return kfs[0].value;
    const last = kfs[kfs.length - 1];
    if (t >= last.t) return last.value;
    for (let i = 0; i < kfs.length - 1; i++) {
      const a = kfs[i];
      const b = kfs[i + 1];
      if (t >= a.t && t <= b.t) {
        if (b.t === a.t) return b.value;
        const progress = (t - a.t) / (b.t - a.t);
        const eased = easingProgress(a.easing, a.bezier, progress);
        return a.value + (b.value - a.value) * eased;
      }
    }
    return last.value;
  }
  function solveLayer(layer, t) {
    const props = layer.transform && layer.transform.properties || {};
    return {
      x: solveTrack(props.x, t, TIMELINE_PROPERTY_DEFAULTS.x),
      y: solveTrack(props.y, t, TIMELINE_PROPERTY_DEFAULTS.y),
      scale: Math.max(0, solveTrack(props.scale, t, TIMELINE_PROPERTY_DEFAULTS.scale)),
      rotation: solveTrack(props.rotation, t, TIMELINE_PROPERTY_DEFAULTS.rotation),
      opacity: Math.min(1, Math.max(0, solveTrack(props.opacity, t, TIMELINE_PROPERTY_DEFAULTS.opacity))),
      visible: t >= layer.in && t <= layer.out
    };
  }
  class TimelineEngine {
    constructor(document2) {
      __publicField(this, "document");
      __publicField(this, "layersById");
      this.document = document2;
      this.layersById = /* @__PURE__ */ new Map();
      for (const layer of document2.layers || []) {
        this.layersById.set(layer.id, layer);
      }
    }
    get duration() {
      return this.document.composition.duration;
    }
    get fps() {
      return this.document.composition.fps;
    }
    get width() {
      return this.document.composition.width;
    }
    get height() {
      return this.document.composition.height;
    }
    layer(id) {
      return this.layersById.get(id);
    }
    layerIds() {
      return (this.document.layers || []).map((layer) => layer.id);
    }
    frameIndex(t) {
      return Math.round(Math.max(0, Math.min(this.duration, t)) / 1e3 * this.fps);
    }
    timeOfFrame(index) {
      return Math.min(this.duration, index / this.fps * 1e3);
    }
    totalFrames() {
      return this.frameIndex(this.duration) + 1;
    }
    /** Детерминированное состояние всех слоёв в момент времени. */
    seek(t) {
      const clamped = Math.max(0, Math.min(this.duration, t));
      const out = {};
      for (const layer of this.document.layers || []) {
        out[layer.id] = solveLayer(layer, clamped);
      }
      return out;
    }
  }
  function applySolvedToDom(root, solved) {
    const nodes = root.querySelectorAll("[data-timeline-layer]");
    nodes.forEach((node) => {
      const el = node;
      const id = el.getAttribute("data-timeline-layer") || "";
      const state = solved[id];
      if (!state) {
        el.style.visibility = "hidden";
        return;
      }
      el.style.visibility = state.visible ? "visible" : "hidden";
      el.style.opacity = state.opacity.toFixed(4);
      el.style.transform = `translate3d(${state.x.toFixed(3)}px, ${state.y.toFixed(3)}px, 0) rotate(${state.rotation.toFixed(4)}deg) scale(${state.scale.toFixed(6)})`;
    });
  }
  const Timeline = {
    easingProgress,
    solveTrack,
    solveLayer,
    applySolvedToDom,
    propertyDefaults: TIMELINE_PROPERTY_DEFAULTS
  };
  function motionEase(value, easing = "soft") {
    const p = Math.max(0, Math.min(1, value));
    if (easing === "linear") return p;
    if (easing === "ease-in") return p * p * p;
    if (easing === "ease-out") return 1 - (1 - p) ** 3;
    return p * p * p * (p * (p * 6 - 15) + 10);
  }
  function renderStoryOverlays(root, ir, overlays, find) {
    var _a;
    root.style.position = "relative";
    const panels = [];
    for (const overlay of overlays) {
      const anchor = find(root, overlay.anchorTarget);
      if (!anchor) throw new Error(`Не найден элемент для окна: ${overlay.anchorTarget}`);
      const style = getComputedStyle(anchor), color = ((_a = ir.tokens) == null ? void 0 : _a.color) || {};
      const panel = document.createElement("div");
      panel.dataset.storyTarget = `overlay.${overlay.id}`;
      panel.dataset.storyOverlay = overlay.id;
      Object.assign(panel.style, {
        position: "absolute",
        zIndex: "100",
        boxSizing: "border-box",
        width: `${overlay.width || 240}px`,
        padding: "8px",
        borderRadius: `${overlay.radius ?? 12}px`,
        background: overlay.background || color.surface || "#ffffff",
        color: overlay.color || color.text || "#171717",
        boxShadow: "0 12px 36px #00000024, 0 2px 8px #00000012",
        border: `1px solid ${color.border || "#dddddd"}`,
        fontFamily: style.fontFamily,
        fontSize: `${Math.max(13, Math.min(18, parseFloat(style.fontSize) || 14))}px`,
        fontWeight: "400",
        lineHeight: "1.5",
        transformOrigin: "top right"
      });
      if (overlay.title) {
        const title = document.createElement("div");
        title.textContent = overlay.title;
        Object.assign(title.style, { padding: "8px 12px", fontWeight: "600", opacity: ".65", fontSize: "12px" });
        panel.append(title);
      }
      for (const item of overlay.items) {
        const button = document.createElement("div");
        button.dataset.storyTarget = `overlay.${overlay.id}.${item.id}`;
        button.textContent = item.text;
        Object.assign(button.style, {
          padding: "10px 12px",
          borderRadius: "7px",
          margin: "2px 0",
          whiteSpace: "pre-wrap",
          background: item.selected ? overlay.accent || color.primary || "#7018e6" : "transparent",
          color: item.selected ? "#ffffff" : "inherit"
        });
        panel.append(button);
      }
      root.append(panel);
      const artWidth = root.offsetWidth, ratio = root.getBoundingClientRect().width / artWidth || 1;
      const a = anchor.getBoundingClientRect(), origin = root.getBoundingClientRect();
      const panelWidth = Math.min(overlay.width || 240, artWidth - 24);
      panel.style.width = panelWidth + "px";
      panel.style.left = Math.max(12, Math.min(artWidth - panelWidth - 12, (a.right - origin.left) / ratio - panelWidth)) + "px";
      panel.style.top = (a.bottom - origin.top) / ratio + 10 + "px";
      panels.push(panel);
    }
    return panels;
  }
  function storySchedule(story) {
    let time = 0;
    return story.actions.map((action) => {
      const start = time;
      time += action.duration;
      return { ...action, start, end: time };
    });
  }
  function storyTarget(root, target) {
    const bound = Array.from(root.querySelectorAll("[data-story-target]")).find((el) => el.dataset.storyTarget === target);
    if (bound || target.startsWith("overlay.")) return bound || null;
    const match = /^s(\d+)(?:\.(.+))?$/.exec(target);
    if (!match) return null;
    const section = root.querySelector(`[data-ir-sec="${Number(match[1])}"]`);
    if (!section || !match[2]) return section;
    return Array.from(section.querySelectorAll("[data-ir-path]")).find((el) => el.dataset.irPath === match[2]) || null;
  }
  function bindStoryTargets(root, ir) {
    (ir.tree || []).forEach((section, index) => {
      const host = root.querySelector(`[data-ir-sec="${index}"]`);
      if (!host) return;
      const imported = section.type === "source-block" || section.variant === "dom-capture";
      const elements = Array.from(host.querySelectorAll("[data-ir-path]"));
      const walk = (children, treePath, renderPath) => (children || []).forEach((child, i) => {
        const canonical = `${treePath}.children.${i}`;
        const actual = imported && child.sourceKey || `${renderPath ? renderPath + "." : ""}children.${i}`;
        const element = elements.find((el) => el.dataset.irPath === actual);
        if (element) element.dataset.storyTarget = canonical;
        walk(child.children, canonical, actual);
      });
      walk(section.children, `s${index}`, "");
    });
  }
  function actionTarget(root, id) {
    const target = storyTarget(root, id);
    if (!target.dataset.irPath || target.matches("input,textarea,button,a,[role=button]")) return target;
    return Array.from(target.querySelectorAll("input,textarea,button,a,[role=button]")).find((el) => el.dataset.irPath === target.dataset.irPath || el.closest("[data-ir-path]") === target) || target;
  }
  class VideoStoryPlayer {
    constructor(host, document2, offline = false) {
      __publicField(this, "roots", /* @__PURE__ */ new Map());
      __publicField(this, "fields", /* @__PURE__ */ new Map());
      __publicField(this, "mapped", []);
      __publicField(this, "cursor");
      __publicField(this, "pulse");
      __publicField(this, "engine");
      __publicField(this, "story");
      var _a, _b, _c, _d;
      this.host = host;
      this.document = document2;
      this.story = document2.story;
      this.engine = new TimelineEngine(document2);
      host.replaceChildren();
      Object.assign(host.style, { width: `${document2.composition.width}px`, height: `${document2.composition.height}px`, position: "relative", overflow: "hidden", pointerEvents: "none", background: document2.composition.background });
      for (const page of this.story.pages) {
        const outer = window.document.createElement("div");
        outer.dataset.storyPage = page.id;
        Object.assign(outer.style, { position: "absolute", inset: "0", overflow: "hidden", background: document2.composition.background });
        const inner = window.document.createElement("div");
        outer.append(inner);
        host.append(outer);
        IRRenderer.renderIR(inner, page.ir, { viewport: "desktop", fit: false, offline });
        bindStoryTargets(inner, page.ir);
        const artWidth = Number((_a = inner.querySelector("[data-design-width]")) == null ? void 0 : _a.dataset.designWidth) || Number((_b = page.ir.frame) == null ? void 0 : _b.width) || 1440;
        const scale = document2.composition.width / artWidth;
        Object.assign(inner.style, { width: artWidth + "px", transformOrigin: "top left" });
        const panels = renderStoryOverlays(inner, page.ir, page.overlays || [], storyTarget);
        this.roots.set(page.id, { outer, inner, scale, panels });
        for (const layer of document2.layers || []) {
          if (layer.type !== "component" || (layer.pageId || this.story.pages[0].id) !== page.id) continue;
          let target = layer.storyTarget;
          if (!target) {
            const visit = (node, path) => {
              if ((node.sourceKey || node.id) === layer.ref) target = path;
              (node.children || []).forEach((child, i) => visit(child, `${path}.children.${i}`));
            };
            (page.ir.tree || []).forEach((section, i) => visit(section, `s${i}`));
          }
          const el = target ? storyTarget(inner, target) : null;
          if (el) {
            el.dataset.timelineLayer = layer.id;
            const base = getComputedStyle(el);
            this.mapped.push({ el, id: layer.id, transform: base.transform === "none" ? "" : base.transform, opacity: Number(base.opacity), visibility: base.visibility });
          }
        }
      }
      for (const action of this.story.actions.filter((a) => a.type === "type")) {
        const key = `${action.pageId}/${action.target}`;
        if (this.fields.has(key)) continue;
        const root = (_c = this.roots.get(action.pageId)) == null ? void 0 : _c.inner;
        const target = root && storyTarget(root, action.target || "");
        if (!target) throw new Error(`Не найдено поле ${action.target} на странице ${action.pageId}`);
        const input = target.matches("input,textarea") ? target : target.querySelector("input,textarea");
        if (input) {
          this.fields.set(key, { el: input, initial: input.value });
        } else {
          const overlay = window.document.createElement("span");
          overlay.dataset.storyTyped = "true";
          Object.assign(overlay.style, { position: "absolute", inset: "0", padding: "8px 12px", display: "none", alignItems: "center", whiteSpace: "pre-wrap", font: "inherit", color: "inherit", overflow: "hidden" });
          if (getComputedStyle(target).position === "static") target.style.position = "relative";
          target.append(overlay);
          this.fields.set(key, { el: target, initial: "", overlay });
        }
      }
      for (const action of this.story.actions.filter((a) => a.target)) {
        const root = (_d = this.roots.get(action.pageId)) == null ? void 0 : _d.inner;
        if (!root || !storyTarget(root, action.target)) throw new Error(`Не найден элемент ${action.target} на странице ${action.pageId}`);
      }
      this.cursor = window.document.createElement("div");
      this.cursor.dataset.storyCursor = "true";
      this.cursor.innerHTML = '<svg width="30" height="38" viewBox="0 0 30 38"><path d="M3 2L25 23L15 24L11 34L3 2Z" fill="white" stroke="#101218" stroke-width="2" stroke-linejoin="round"/></svg>';
      Object.assign(this.cursor.style, { position: "absolute", left: "0", top: "0", zIndex: "9999", filter: "drop-shadow(0 2px 3px #0005)" });
      this.pulse = window.document.createElement("div");
      this.pulse.dataset.storyClick = "true";
      Object.assign(this.pulse.style, { position: "absolute", width: "48px", height: "48px", left: "0", top: "0", margin: "-24px", border: "3px solid #ff691d", borderRadius: "50%", zIndex: "9998" });
      host.append(this.pulse, this.cursor);
      this.seek(0);
    }
    writeField(key, text) {
      const field = this.fields.get(key);
      if (!field) return;
      if (!field.overlay) field.el.value = text ?? field.initial;
      else {
        for (const child of Array.from(field.el.children)) if (child !== field.overlay) child.style.visibility = text === null ? "" : "hidden";
        field.overlay.style.display = text === null ? "none" : "flex";
        field.overlay.textContent = text || "";
      }
    }
    seek(time) {
      const t = Math.max(0, Math.min(this.document.composition.duration, time));
      const solved = this.engine.seek(t);
      for (const base of this.mapped) {
        const state = solved[base.id];
        base.el.style.visibility = state.visible ? base.visibility : "hidden";
        base.el.style.opacity = String(state.visible ? state.opacity * base.opacity : 0);
        base.el.style.transform = `translate3d(${state.x}px,${state.y}px,0) rotate(${state.rotation}deg) scale(${state.scale}) ${base.transform}`;
      }
      for (const key of this.fields.keys()) this.writeField(key, null);
      const scrolls = {};
      const typed = {};
      let pageId = this.story.initialPageId;
      let x = this.document.composition.width / 2, y = this.document.composition.height / 2, visible = false, pulse = 0, cursorOpacity = 0, cursorScale = 1;
      let fade = null;
      const applyScroll = () => {
        for (const [id, root] of this.roots) root.inner.style.transform = `scale(${root.scale}) translateY(${-(scrolls[id] || 0)}px)`;
      };
      for (const root of this.roots.values()) {
        root.outer.style.transform = "none";
        for (const panel of root.panels) panel.style.translate = "0px 0px";
      }
      applyScroll();
      for (const action of storySchedule(this.story)) {
        if (t < action.start) break;
        const p = Math.min(1, (t - action.start) / action.duration);
        const ease = (v) => motionEase(v, action.easing);
        if (action.type === "navigate") {
          const to = action.toPageId;
          const samePageState = action.transition === "state";
          fade = action.transition !== "cut" && p < 1 ? { from: pageId, to, progress: ease(p), motion: action.transition === "motion", state: samePageState } : null;
          if (samePageState) {
            scrolls[to] = scrolls[pageId] || 0;
            applyScroll();
          } else cursorOpacity *= fade ? 1 - motionEase(Math.min(1, p * 2)) : 0;
          pageId = to;
          visible = visible && cursorOpacity > 0;
        } else if (action.type === "scroll") {
          const root = this.roots.get(pageId);
          const max = Math.max(0, root.inner.scrollHeight - this.document.composition.height / root.scale);
          let destination = action.y || 0;
          if (action.target) {
            const target = actionTarget(root.inner, action.target);
            const box = target.getBoundingClientRect(), origin = root.inner.getBoundingClientRect();
            const viewScale = this.host.getBoundingClientRect().width / this.document.composition.width || 1;
            destination = (box.top + box.height / 2 - origin.top) / (root.scale * viewScale) - this.document.composition.height / (2 * root.scale);
          }
          const end = Math.min(max, Math.max(0, destination));
          scrolls[pageId] = (scrolls[pageId] || 0) + (end - (scrolls[pageId] || 0)) * ease(p);
          applyScroll();
        } else if (action.target) {
          const root = this.roots.get(pageId);
          const target = actionTarget(root.inner, action.target);
          const box = target.getBoundingClientRect(), hostBox = this.host.getBoundingClientRect();
          const viewScale = hostBox.width / this.document.composition.width || 1;
          const endX = (box.left + box.width / 2 - hostBox.left) / viewScale;
          const endY = (box.top + box.height / 2 - hostBox.top) / viewScale;
          const movement = action.type === "move" ? p : Math.min(1, p / (action.type === "type" ? 0.35 : 0.5));
          const q = ease(movement), dx = endX - x, dy = endY - y, distance = Math.hypot(dx, dy);
          const arc = action.easing === "linear" ? 0 : Math.min(24, distance * 0.07) * Math.sin(Math.PI * q);
          x += dx * q - (distance ? dy / distance : 0) * arc;
          y += dy * q + (distance ? dx / distance : 0) * arc;
          if (!visible) cursorOpacity = motionEase((t - action.start) / 240);
          visible = true;
          if (action.type === "click" && p > 0.6 && p < 1) {
            pulse = (p - 0.6) / 0.4;
            cursorScale = 1 - 0.12 * Math.sin(Math.PI * pulse) ** 2;
          }
          if (action.type === "type") {
            const progress = Math.max(0, (p - 0.35) / 0.65);
            const value = Array.from(action.text || "").slice(0, Math.floor(Array.from(action.text || "").length * progress)).join("");
            typed[`${pageId}/${action.target}`] = value;
            this.writeField(`${pageId}/${action.target}`, value);
          }
        }
        if (p < 1) break;
      }
      for (const [id, root] of this.roots) {
        const opacity = fade ? id === fade.from ? 1 : id === fade.to ? fade.progress : 0 : id === pageId ? 1 : 0;
        if (fade == null ? void 0 : fade.motion) {
          const q = fade.progress;
          root.outer.style.transformOrigin = "center center";
          root.outer.style.transform = id === fade.to ? `translateY(${Math.min(10, this.document.composition.height * 0.012) * (1 - q)}px) scale(${1 + 0.035 * (1 - q)})` : "none";
        }
        root.outer.style.zIndex = fade ? id === fade.to ? "2" : id === fade.from ? "1" : "0" : "0";
        root.outer.style.opacity = String(opacity);
        root.outer.style.visibility = opacity > 0 ? "visible" : "hidden";
        if ((fade == null ? void 0 : fade.state) && id === fade.to) for (const panel of root.panels) panel.style.translate = `0px ${-8 * (1 - fade.progress)}px`;
      }
      this.cursor.style.visibility = visible ? "visible" : "hidden";
      this.cursor.style.opacity = String(cursorOpacity);
      this.cursor.style.transformOrigin = "3px 2px";
      this.cursor.style.transform = `translate(${x}px,${y}px) scale(${cursorScale})`;
      this.pulse.style.opacity = pulse ? String(0.75 * Math.sin(Math.PI * pulse) ** 2) : "0";
      this.pulse.style.transform = `translate(${x}px,${y}px) scale(${0.35 + 0.9 * motionEase(pulse, "ease-out")})`;
      return { pageId, cursor: { x, y, visible, opacity: cursorOpacity, scale: cursorScale }, typed, scrolls, time: t };
    }
    destroy() {
      this.host.replaceChildren();
    }
  }
  if (typeof window !== "undefined") {
    window.MotionComposition = MotionComposition;
    window.IRRenderer = IRRenderer;
    window.GeoEdit = GeoEdit;
    window.IRHistory = IRHistory;
    window.DesignAIFontCatalog = DesignAIFontCatalog;
    window.TimelineEngine = TimelineEngine;
    window.Timeline = Timeline;
    window.VideoStoryPlayer = VideoStoryPlayer;
  }
  exports.DesignAIFontCatalog = DesignAIFontCatalog;
  exports.GeoEdit = GeoEdit;
  exports.IRHistory = IRHistory;
  exports.IRRenderer = IRRenderer;
  exports.Timeline = Timeline;
  exports.TimelineEngine = TimelineEngine;
  Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
  return exports;
}({});
