/* Навешивание событий инспектора — порт inspector.js (wireActs/wireSingle) и
 * editor.js (wireInspectorEvents/wireResponsiveInspector) на React-разметку.
 * Инпуты неконтролируемые, поэтому слушатели — нативные: поведение «change после
 * fill + dispatchEvent(new Event('change'))» из тестов сохраняется 1:1.
 * Scrub-drag по label держит флаг ctl.setInspScrubbing: пока он поднят, контроллер
 * не бампит inspectorTick, и React не перемонтирует панель (pointer capture жив). */
import * as ctl from "../controller";
import type { GeoHandle } from "../globals";
import { applyNum, readNumInput } from "./evalMath";
import { isLockedNode } from "../../engine/locked";
import { applyTypeScale, fontStack, readFloatInput } from "../../engine/tokensV2";

function sess() {
  return ctl.getSession();
}

function geo() {
  const s = sess();
  return s ? s.geo : null;
}

/** Color controls can commit as soon as Svelte mounts them, independently of
 * InspectorPanel's deferred DOM wiring. Always resolve the current GeoEdit. */
export function applyInspectorColor(key: string, raw: string): string | undefined {
  const value = String(raw || "").trim();
  const clear = !value || value.toLowerCase() === "transparent";
  const digits = value.replace(/^#/, "");
  const normalized = clear ? ""
    : /^[0-9a-f]{3}$/i.test(digits) ? "#" + digits.split("").map((char) => char + char).join("").toLowerCase()
    : /^[0-9a-f]{6}$/i.test(digits) ? "#" + digits.toLowerCase() : undefined;
  const g = geo();
  if (normalized === undefined || !g) return undefined;
  g.setNodeStyle({ [key]: normalized || null });
  return normalized;
}

/* ---------- общие data-act (align/distribute/reset-frame) ---------- */

function wireActs(root: HTMLElement) {
  root.querySelectorAll("[data-act]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const g = geo();
      if (!g) return;
      const map: Record<string, keyof GeoHandle> = {
        "align-left": "alignLeft", "align-center-h": "alignCenterH", "align-right": "alignRight",
        "align-top": "alignTop", "align-center-v": "alignCenterV", "align-bottom": "alignBottom",
        "distribute-h": "distributeH", "distribute-v": "distributeV", "reset-frame": "resetFrame",
        "stretch-width": "stretchWidth", "group": "groupSelection", "ungroup": "ungroupSelection",
      };
      const fn = map[(btn as HTMLElement).dataset.act!];
      if (fn && typeof g[fn] === "function") (g[fn] as () => void)();
    });
  });
}

/* ---------- одиночное выделение: data-pi / data-style-* / scrub ---------- */

function wireSingle(root: HTMLElement) {
  const s = sess();
  const g = geo();
  if (!s || !g || !s.sel.length) return;
  const ref = s.sel[0].ref;
  const f = () => (geo() ? geo()!.frameOf(ref) : {}) || {};

  root.querySelectorAll<HTMLInputElement | HTMLSelectElement>("[data-pi]").forEach((inp) => {
    if (inp.hasAttribute("data-direct-change")) return;
    inp.addEventListener("change", () => {
      const g2 = geo();
      if (!g2) return;
      const key = inp.dataset.pi;
      const cur = f();
      if (key === "x" || key === "y" || key === "width" || key === "height" ||
          key === "rotation" || key === "gap") {
        // numeric math: «100*2», «960/3» и т.п. схлопываются в число
        const v = readNumInput(inp as HTMLInputElement);
        if (v === undefined) return; // не распознано — не применяем
        if (v !== null) inp.value = String(v);
        applyNum(g2, key!, v);
      } else if (key === "constr-h" || key === "constr-v") {
        const constraints = cur.constraints || {};
        const axis = key === "constr-h" ? "h" : "v";
        g2.setFrameProps({ constraints: Object.assign({}, constraints, { [axis]: inp.value }) });
      } else if (key === "absolute") {
        if ((inp as HTMLInputElement).checked) {
          const extra: Record<string, number> = {};
          if (typeof cur.x !== "number" || typeof cur.y !== "number") {
            const p = g2.posOf(ref);
            if (p) { extra.x = p.x; extra.y = p.y; }
          }
          g2.setFrameProps(Object.assign({ absolute: true }, extra));
        } else {
          g2.setFrameProps({ absolute: null });
        }
      } else if (key === "clip") {
        g2.setFrameProps({ clip: (inp as HTMLInputElement).checked ? true : null });
      } else if (key === "fillw") {
        g2.setFrameProps({ width: (inp as HTMLInputElement).checked ? "fill" : null });
      } else if (key === "hugw") {
        g2.setFrameProps({ width: (inp as HTMLInputElement).checked ? "hug" : null });
      } else if (key === "fillh") {
        g2.setFrameProps({ height: (inp as HTMLInputElement).checked ? "fill" : null });
      } else if (key === "hugh") {
        g2.setFrameProps({ height: (inp as HTMLInputElement).checked ? "hug" : null });
      }
    });
  });

  root.querySelectorAll<HTMLInputElement>("[data-style-color]").forEach((inp) => {
    if (inp.hasAttribute("data-direct-change")) return;
    inp.addEventListener("input", () => {
      const g2 = geo();
      if (!g2) return;
      const key = inp.dataset.styleColor!;
      const text = root.querySelector<HTMLInputElement>(`[data-style-text="${key}"]`);
      if (text) text.value = inp.value;
      g2.setNodeStyle({ [key]: inp.value });
    });
  });
  root.querySelectorAll<HTMLInputElement>("[data-style-text]").forEach((inp) => {
    if (inp.hasAttribute("data-direct-change")) return;
    inp.addEventListener("change", () => {
      const g2 = geo();
      if (!g2) return;
      const key = inp.dataset.styleText!;
      const value = String(inp.value || "").trim();
      if (!value || value.toLowerCase() === "transparent") {
        g2.setNodeStyle({ [key]: null });
        return;
      }
      const short = value.match(/^#([0-9a-f]{3})$/i);
      const normalized = short
        ? "#" + short[1].split("").map((char) => char + char).join("").toLowerCase()
        : /^#[0-9a-f]{6}$/i.test(value) ? value.toLowerCase() : null;
      if (!normalized) return;
      inp.value = normalized;
      g2.setNodeStyle({ [key]: normalized });
    });
  });
  root.querySelectorAll<HTMLElement>("[data-clear-style]").forEach((btn) => {
    if (btn.hasAttribute("data-direct-change")) return;
    btn.addEventListener("click", () => {
      const g2 = geo();
      if (!g2) return;
      const key = btn.dataset.clearStyle!;
      const text = root.querySelector<HTMLInputElement>(`[data-style-text="${key}"]`);
      const color = root.querySelector<HTMLInputElement>(`[data-style-color="${key}"]`);
      if (text) { text.value = ""; text.dispatchEvent(new Event("change")); }
      if (color) color.value = "#ffffff";
      g2.setNodeStyle({ [key]: null });
    });
  });
  root.querySelectorAll<HTMLInputElement>("[data-style-num]").forEach((inp) => {
    inp.addEventListener("change", () => {
      const g2 = geo();
      if (!g2) return;
      const key = inp.dataset.styleNum!;
      const v = readNumInput(inp);
      if (v === undefined) return;
      if (v !== null) inp.value = String(Math.max(0, v));
      g2.setNodeStyle({ [key]: v == null ? null : Math.max(0, v) });
    });
  });
  root.querySelectorAll<HTMLInputElement>("[data-style-range]").forEach((inp) => {
    inp.addEventListener("input", () => {
      const g2 = geo();
      if (!g2) return;
      const key = inp.dataset.styleRange!;
      const pct = Math.max(0, Math.min(100, Number(inp.value) || 0));
      const label = inp.parentElement && inp.parentElement.querySelector("[data-opacity-label]");
      if (label) label.textContent = pct + "%";
      g2.setNodeStyle({ [key]: pct === 100 ? null : Math.round(pct) / 100 });
    });
  });
  root.querySelectorAll<HTMLSelectElement>("[data-style-select]").forEach((sel) => {
    sel.addEventListener("change", () => {
      const g2 = geo();
      if (!g2) return;
      g2.setNodeStyle({ [sel.dataset.styleSelect!]: sel.value || null });
    });
  });

  // drag-scrub: тянуть лейбл горизонтально = менять значение (Shift — шаг 10)
  root.querySelectorAll<HTMLElement>(".pi-field").forEach((field) => {
    const inp = field.querySelector<HTMLInputElement>("input[data-pi]");
    const lab = field.querySelector("label");
    if (!inp || !lab || inp.disabled) return;
    const key = inp.dataset.pi!;
    if (!["x", "y", "width", "height", "rotation", "gap"].includes(key)) return;
    lab.style.cursor = "ew-resize";
    lab.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      const base = readNumInput(inp);
      const start = typeof base === "number" ? base : 0;
      const sx = e.clientX;
      lab.setPointerCapture(e.pointerId);
      // пока scrub жив, контроллер не бампит tick — панель не перемонтируется
      ctl.setInspScrubbing(true);
      const move = (ev: PointerEvent) => {
        const step = ev.shiftKey ? 10 : 1;
        const v = start + Math.round(ev.clientX - sx) * step;
        inp.value = String(v);
        // geo() — живой геттер: после ре-аттача geoedit ручка обновится сама
        const g3 = geo();
        if (g3) applyNum(g3, key, v);
      };
      const up = () => {
        lab.removeEventListener("pointermove", move);
        ctl.setInspScrubbing(false);
      };
      lab.addEventListener("pointermove", move);
      lab.addEventListener("pointerup", up, { once: true });
    });
  });

  root.querySelectorAll<HTMLElement>("[data-pi-dir]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const g2 = geo();
      if (!g2) return;
      const d = btn.dataset.piDir;
      if (d === "free") g2.setFrameProps({ layout: "free" });
      else g2.setFrameProps({ layout: "auto", direction: d });
    });
  });

  root.querySelectorAll<HTMLElement>("[data-pi-ja]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const g2 = geo();
      if (!g2) return;
      const [j, a] = btn.dataset.piJa!.split("|");
      g2.setFrameProps({ justify: j, align: a });
    });
  });

  root.querySelectorAll<HTMLInputElement>("[data-pi-justify]").forEach((radio) => {
    radio.addEventListener("change", () => {
      const g2 = geo();
      if (g2 && radio.checked) g2.setFrameProps({ justify: radio.dataset.piJustify });
    });
  });
}

/* ---------- type-specific группы (порт wireInspectorEvents из editor.js) ---------- */

function wireTypeGroups(root: HTMLElement) {
  // element props (text/size/align/level/variant)
  root.querySelectorAll<HTMLInputElement | HTMLSelectElement>("[data-el-prop]").forEach((inp) => {
    inp.addEventListener("change", () => {
      const s = sess();
      if (!s || !s.sel.length) return;
      const node = s.sel[0].node;
      if (!node) return;
      if (isLockedNode(node)) return; // editable:false (raster fallback): правка запрещена
      ctl.pushHistory();
      const key = inp.dataset.elProp!;
      let val: any = inp.value;
      if (key === "level") val = Number(val);
      // typeRole "" = Auto: поле снимается, роль снова берётся по тегу
      if (key === "typeRole" && !val) delete node[key];
      else node[key] = val;
      ctl.commitActiveIrEdits();
      ctl.rerenderEditorCanvas();
    });
  });
  // текстовый стиль «всем таким»: та же роль всем heading того же уровня / всем text
  root.querySelectorAll<HTMLButtonElement>("[data-type-role-apply-all]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const s = sess();
      if (!s || !s.sel.length) return;
      const node = s.sel[0].node;
      const role = node && typeof node.typeRole === "string" ? node.typeRole : "";
      if (!role) return;
      const same = (el: any) => el && el.type === node.type
        && (node.type !== "heading" || (el.level || 2) === (node.level || 2))
        && !isLockedNode(el) && !(el.sourceMeta && el.sourceMeta.componentRef);
      let touched = 0;
      const walk = (children: any) => {
        if (!Array.isArray(children)) return;
        for (const el of children) {
          if (!el || typeof el !== "object") continue;
          if (el.sourceMeta && el.sourceMeta.componentRef) continue; // пиннутый мастер ДС
          if (same(el) && el.typeRole !== role) { el.typeRole = role; touched++; }
          walk(el.children);
        }
      };
      const tree = Array.isArray(s.ir.tree) ? s.ir.tree : [];
      ctl.pushHistory();
      for (const sec of tree) {
        if (!sec || sec.type === "source-block") continue;
        walk(sec.children);
      }
      if (!touched) { s.history.cancelLast(); return; }
      ctl.commitActiveIrEdits();
      ctl.rerenderEditorCanvas();
    });
  });
  // text content
  root.querySelectorAll<HTMLTextAreaElement>("[data-textprop]").forEach((ta) => {
    ta.addEventListener("change", () => {
      const s = sess();
      if (!s || !s.sel.length) return;
      if (isLockedNode(s.sel[0].node)) return; // editable:false (raster fallback): текст запрещён
      ctl.pushHistory();
      s.sel[0].node[ta.dataset.textprop!] = ta.value;
      ctl.commitActiveIrEdits();
      ctl.rerenderEditorCanvas();
    });
  });
  // token colors: снапшот ДО мутации (по первому input серии) —
  // pushHistory на change снимал бы уже изменённый цвет, и undo его не возвращал
  root.querySelectorAll<HTMLInputElement>("[data-color]").forEach((inp) => {
    let armed = false;
    inp.addEventListener("focus", () => { armed = true; });
    inp.addEventListener("input", () => {
      const s = sess();
      if (!s) return;
      if (armed) { ctl.pushHistory(); armed = false; }
      s.ir.tokens.color[inp.dataset.color!] = inp.value;
      (inp.nextElementSibling as HTMLElement).textContent = inp.value;
      ctl.rerenderEditorCanvas();
    });
  });
  // font family
  root.querySelectorAll<HTMLSelectElement>("[data-font]").forEach((sel) => {
    sel.addEventListener("change", () => {
      const s = sess();
      if (!s) return;
      ctl.pushHistory();
      s.ir.tokens.font[sel.dataset.font!].family = sel.value;
      ctl.rerenderEditorCanvas();
    });
  });
  // роли цвета tokens.v2 — тот же контракт «снапшот до мутации», что у data-color
  root.querySelectorAll<HTMLInputElement>("[data-color-v2]").forEach((inp) => {
    let armed = false;
    inp.addEventListener("focus", () => { armed = true; });
    inp.addEventListener("input", () => {
      const s = sess();
      if (!s || !s.ir.tokens.v2 || !s.ir.tokens.v2.color) return;
      if (armed) { ctl.pushHistory(); armed = false; }
      s.ir.tokens.v2.color[inp.dataset.colorV2!] = inp.value;
      (inp.nextElementSibling as HTMLElement).textContent = inp.value;
      ctl.rerenderEditorCanvas();
    });
  });
  // семейства tokens.v2: пишем и family, и stack — рендерер берёт готовый стек
  root.querySelectorAll<HTMLSelectElement>("[data-font-v2]").forEach((sel) => {
    sel.addEventListener("change", () => {
      const s = sess();
      const families = s && s.ir.tokens.v2 && s.ir.tokens.v2.type && s.ir.tokens.v2.type.families;
      if (!families || !families[sel.dataset.fontV2!]) return;
      ctl.pushHistory();
      const face = families[sel.dataset.fontV2!];
      face.family = sel.value;
      face.stack = fontStack(sel.value);
      ctl.rerenderEditorCanvas();
    });
  });
  // base/ratio шкалы: кегли ролей пересчитываются тем же правилом, что в миграции
  root.querySelectorAll<HTMLInputElement>("[data-token-num]").forEach((inp) => {
    inp.addEventListener("change", () => {
      const s = sess();
      if (!s) return;
      const path = inp.dataset.tokenNum!.split(".");
      let obj: any = s.ir.tokens;
      for (let i = 0; i < path.length - 1; i++) {
        if (!obj || typeof obj !== "object") return;
        obj = obj[path[i]];
      }
      if (!obj || typeof obj !== "object") return;
      // ratio — дробное, readNumInput округляет до целого и схлопнул бы 1.45 в 1
      const value = readFloatInput(inp.value);
      if (value == null) return;
      ctl.pushHistory();
      obj[path[path.length - 1]] = value;
      applyTypeScale(s.ir.tokens.v2 && s.ir.tokens.v2.type);
      ctl.rerenderEditorCanvas();
    });
  });
  // точечная правка роли (кегль/вес) поверх посчитанной шкалы
  root.querySelectorAll<HTMLInputElement>("[data-type-role]").forEach((inp) => {
    inp.addEventListener("change", () => {
      const s = sess();
      const roles = s && s.ir.tokens.v2 && s.ir.tokens.v2.type && s.ir.tokens.v2.type.roles;
      const target = roles && roles[inp.dataset.typeRole!];
      if (!target) return;
      const value = readFloatInput(inp.value);
      if (value == null) return;
      ctl.pushHistory();
      target[inp.dataset.typeField!] = inp.dataset.typeField === "weight"
        ? Math.max(100, Math.min(900, Math.round(value / 100) * 100))
        : value;
      ctl.rerenderEditorCanvas();
    });
  });
  // token-level props (font.scale, radius.card, spacing.section, shadow)
  root.querySelectorAll<HTMLSelectElement>("[data-token]").forEach((sel) => {
    sel.addEventListener("change", () => {
      const s = sess();
      if (!s) return;
      ctl.pushHistory();
      const path = sel.dataset.token!.split(".");
      let obj = s.ir.tokens;
      for (let i = 0; i < path.length - 1; i++) obj = obj[path[i]];
      obj[path[path.length - 1]] = sel.value;
      ctl.rerenderEditorCanvas();
    });
  });
  root.querySelectorAll<HTMLInputElement>("[data-node-style-color]").forEach((inp) => {
    inp.addEventListener("input", () => {
      const g2 = geo();
      if (!g2 || !g2.setNodeStyle) return;
      g2.setNodeStyle({ [inp.dataset.nodeStyleColor!]: inp.value });
    });
  });
  root.querySelectorAll<HTMLInputElement>("[data-node-style-num]").forEach((inp) => {
    inp.addEventListener("change", () => {
      const g2 = geo();
      if (!g2 || !g2.setNodeStyle) return;
      const raw = String(inp.value || "").trim();
      const value = raw === "" ? null : Number(raw);
      if (raw !== "" && !Number.isFinite(value)) return;
      g2.setNodeStyle({ [inp.dataset.nodeStyleNum!]: value == null ? null : Math.max(0, value) });
    });
  });
  root.querySelectorAll<HTMLSelectElement>("[data-node-style-select]").forEach((sel) => {
    sel.addEventListener("change", () => {
      const g2 = geo();
      if (!g2 || !g2.setNodeStyle) return;
      g2.setNodeStyle({ [sel.dataset.nodeStyleSelect!]: sel.value || null });
    });
  });
}

/* ---------- responsive-блок (порт wireResponsiveInspector из editor.js) ---------- */

function wireResponsive(root: HTMLElement) {
  const s = sess();
  if (!s || !s.sel.length) return;
  const liveSel = () => sess()?.sel[0] || null;
  const reset = root.querySelector('[data-responsive-act="reset"]');
  if (reset) reset.addEventListener("click", () => {
    const sel = liveSel();
    if (sel) ctl.resetResponsiveOverride(sel);
  });
  const all = root.querySelector('[data-responsive-act="all"]');
  if (all) all.addEventListener("click", () => {
    const sel = liveSel();
    if (sel) ctl.applyResponsiveToAll(sel);
  });
  root.querySelectorAll("[data-responsive-copy]").forEach((button) => {
    button.addEventListener("click", () => {
      const sel = liveSel();
      if (sel) ctl.copyResponsiveTo(sel, (button as HTMLElement).dataset.responsiveCopy!);
    });
  });
}

/** Точка входа: зовётся из InspectorPanel после монтирования свежего дерева. */
export function wireInspector(root: HTMLElement) {
  wireActs(root);
  wireSingle(root);
  wireTypeGroups(root);
  wireResponsive(root);
}
