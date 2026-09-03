<script lang="ts" module>
  /* ---------- цветовая математика ---------- */

  function hexToRgb(hex: string): [number, number, number] | null {
    let s = String(hex || "").trim().replace(/^#/, "");
    if (/^[0-9a-f]{3}$/i.test(s)) s = s.split("").map((c) => c + c).join("");
    if (!/^[0-9a-f]{6}$/i.test(s)) return null;
    return [parseInt(s.slice(0, 2), 16), parseInt(s.slice(2, 4), 16), parseInt(s.slice(4, 6), 16)];
  }

  function rgbToHex(r: number, g: number, b: number): string {
    const h = (v: number) =>
      Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0");
    return ("#" + h(r) + h(g) + h(b)).toLowerCase();
  }

  function rgbToHsv(r: number, g: number, b: number): [number, number, number] {
    const rn = r / 255, gn = g / 255, bn = b / 255;
    const max = Math.max(rn, gn, bn), min = Math.min(rn, gn, bn);
    const d = max - min;
    let h = 0;
    if (d > 0) {
      if (max === rn) h = ((gn - bn) / d) % 6;
      else if (max === gn) h = (bn - rn) / d + 2;
      else h = (rn - gn) / d + 4;
      h *= 60;
      if (h < 0) h += 360;
    }
    return [h, max === 0 ? 0 : d / max, max];
  }

  function hsvToRgb(h: number, s: number, v: number): [number, number, number] {
    const hh = ((h % 360) + 360) % 360;
    const c = v * s;
    const x = c * (1 - Math.abs(((hh / 60) % 2) - 1));
    const m = v - c;
    let rp = 0, gp = 0, bp = 0;
    if (hh < 60) [rp, gp, bp] = [c, x, 0];
    else if (hh < 120) [rp, gp, bp] = [x, c, 0];
    else if (hh < 180) [rp, gp, bp] = [0, c, x];
    else if (hh < 240) [rp, gp, bp] = [0, x, c];
    else if (hh < 300) [rp, gp, bp] = [x, 0, c];
    else [rp, gp, bp] = [c, 0, x];
    return [(rp + m) * 255, (gp + m) * 255, (bp + m) * 255];
  }

  function normalizeHex(v: string): string | null {
    const rgb = hexToRgb(v);
    return rgb ? rgbToHex(rgb[0], rgb[1], rgb[2]) : null;
  }
</script>

<script lang="ts">
  /* Color picker инспектора (по мотивам OpenPencil color-picker-panel, MIT):
   * SV-поле + hue-слайдер + HEX + быстрые свотчи design-токенов IR.
   * Запись идёт через скрытый нативный input[data-style-color] — wiring уже в
   * wireInspector.ts, контракт с legacy 1:1 (включая синхронизацию text-поля). */
  import * as ctl from "../controller";
  import { COLOR_ROLE_ORDER } from "../../engine/tokensV2";

  /* ---------- компонент ---------- */

  let {
    styleKey,
    label,
    hex,
    raw,
    transparent,
  }: {
    styleKey: string;
    label: string;
    hex: string;
    raw: string;
    transparent: boolean;
  } = $props();

  const PICKER_W = 232;
  const PICKER_H = 316;

  let open = $state(false);
  let pos = $state({ x: 0, y: 0 });
  let hsv: [number, number, number] = $state([0, 0, 1]);

  let fieldEl: HTMLDivElement | null = $state(null);
  let swatchEl: HTMLButtonElement | null = $state(null);
  let popEl: HTMLDivElement | null = $state(null);
  let svEl: HTMLDivElement | null = $state(null);
  let hueEl: HTMLInputElement | null = $state(null);

  /** Запись через скрытый нативный input: wireInspector сам применит стиль
   *  и синхронизирует text-поле (контракт legacy). */
  function writeHex(value: string) {
    const root = fieldEl;
    if (!root) return;
    const native = root.querySelector<HTMLInputElement>(`input[data-style-color="${styleKey}"]`);
    if (!native) return;
    native.value = value;
    native.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function openPicker() {
    const rgb = hexToRgb(fieldEl
      ?.querySelector<HTMLInputElement>(`input[data-style-text="${styleKey}"]`)?.value || "") || hexToRgb(hex) || [255, 255, 255];
    hsv = rgbToHsv(rgb[0], rgb[1], rgb[2]);
    const r = swatchEl?.getBoundingClientRect();
    if (r) {
      pos = {
        x: Math.max(8, Math.min(r.right - PICKER_W, window.innerWidth - PICKER_W - 8)),
        y: Math.max(8, Math.min(r.bottom + 4, window.innerHeight - PICKER_H - 8)),
      };
    }
    open = true;
  }

  /* Пока пикер открыт, инспектор не перестраивается (inspScrubbing — тот же
   * механизм, что для scrub-drag): иначе tick-ремаунт убьёт DOM пикера при
   * каждой записи стиля. Закрытие возвращает перестройку. */
  $effect(() => {
    if (!open) return;
    ctl.setInspScrubbing(true);
    return () => ctl.setInspScrubbing(false);
  });

  /* Escape — закрыть только пикер (window capture раньше document-capture
   * geoedit, иначе Esc снимет выделение/закроет редактор);
   * клик вне пикера закрывает его, само действие клика не гасится. */
  $effect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        open = false;
      }
    };
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node | null;
      if (t && popEl && popEl.contains(t)) return;
      if (t && swatchEl && swatchEl.contains(t)) return;
      open = false;
    };
    window.addEventListener("keydown", onKey, true);
    document.addEventListener("pointerdown", onDown, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      document.removeEventListener("pointerdown", onDown, true);
    };
  });

  function applyHsv(h: number, s: number, v: number) {
    const hh = Math.max(0, Math.min(360, h));
    const ss = Math.max(0, Math.min(1, s));
    const vv = Math.max(0, Math.min(1, v));
    hsv = [hh, ss, vv];
    const rgb = hsvToRgb(hh, ss, vv);
    writeHex(rgbToHex(rgb[0], rgb[1], rgb[2]));
  }

  /* Hue-слайдер: нативный input-слушатель вместо bind:value —
   * контролируемый range не стабильно реагирует на программную запись value. */
  $effect(() => {
    if (!open) return;
    const el = hueEl;
    if (!el) return;
    const current = hsv;
    const onInput = () => applyHsv(Number(el.value), current[1], current[2]);
    el.addEventListener("input", onInput);
    return () => el.removeEventListener("input", onInput);
  });

  function svFromEvent(e: PointerEvent) {
    const el = svEl;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const s = (e.clientX - r.left) / Math.max(1, r.width);
    const v = 1 - (e.clientY - r.top) / Math.max(1, r.height);
    applyHsv(hsv[0], s, v);
  }

  function svDown(e: PointerEvent) {
    e.preventDefault();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    svFromEvent(e);
    const move = (ev: PointerEvent) => svFromEvent(ev);
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  function commitHexText(el: HTMLInputElement) {
    const norm = normalizeHex(el.value);
    if (!norm) return;
    const rgb = hexToRgb(norm)!;
    hsv = rgbToHsv(rgb[0], rgb[1], rgb[2]);
    writeHex(norm);
  }

  function beginInlineEdit() {
    ctl.setInspScrubbing(true);
  }

  function updateInlineHex(el: HTMLInputElement) {
    const norm = normalizeHex(el.value);
    if (norm) writeHex(norm);
  }

  function endInlineEdit(el: HTMLInputElement) {
    updateInlineHex(el);
    ctl.setInspScrubbing(false);
  }

  const tokens = ((): [string, string][] => {
    const s = ctl.getSession();
    const t = s && s.ir && s.ir.tokens;
    if (!t || typeof t !== "object") return [];
    // Роли v2 — те же цвета, но в порядке ролей страницы; для документов без
    // v2 остаются плоские v1-токены.
    const v2 = t.v2 && typeof t.v2 === "object" ? t.v2.color : null;
    if (v2 && typeof v2 === "object") {
      return COLOR_ROLE_ORDER
        .filter((role) => typeof v2[role] === "string")
        .map((role) => [role, v2[role]]) as [string, string][];
    }
    const c = t.color;
    if (!c || typeof c !== "object") return [];
    return Object.entries(c).filter(([, v]) => typeof v === "string") as [string, string][];
  })();
</script>

<!-- svelte-ignore a11y_label_has_associated_control -->
<div class="pi-field" bind:this={fieldEl}>
  <label>{label}</label>
  <input type="color" data-style-color={styleKey} value={hex} class="pi-cp-native" />
  <button
    type="button"
    bind:this={swatchEl}
    class={`pi-cp-swatch ${transparent ? "pi-empty" : ""}`}
    title="Открыть пикер цвета"
    onclick={openPicker}
  >
    <span class="pi-cp-fill" style="background: {transparent ? 'transparent' : hex}"></span>
  </button>
  <button
    class={`pi-ibtn pi-clear-color ${transparent ? "pi-active" : ""}`}
    data-clear-style={styleKey}
    title="Transparent"
  >×</button>
  <input
    type="text"
    data-style-text={styleKey}
    value={raw}
    placeholder="transparent"
    onfocus={beginInlineEdit}
    oninput={(e) => updateInlineHex(e.currentTarget)}
    onblur={(e) => endInlineEdit(e.currentTarget)}
    onkeydown={(e) => {
      if (e.key === "Enter") {
        updateInlineHex(e.currentTarget);
        e.currentTarget.blur();
      }
    }}
  />

  {#if open}
    <div class="pi-cp-pop" bind:this={popEl} style="left: {pos.x}px; top: {pos.y}px">
      <div
        class="pi-cp-sv"
        role="group"
        aria-label={label}
        bind:this={svEl}
        style="background: linear-gradient(to top,#000,rgba(0,0,0,0)),linear-gradient(to right,#fff,hsl({Math.round(hsv[0])},100%,50%))"
        onpointerdown={svDown}
      >
        <div
          class="pi-cp-thumb"
          style="left: {hsv[1] * 100}%; top: {(1 - hsv[2]) * 100}%"
        ></div>
      </div>
      <input
        class="pi-cp-hue"
        type="range"
        min={0}
        max={360}
        aria-label="Hue"
        bind:this={hueEl}
        value={Math.round(hsv[0])}
      />
      <div class="pi-cp-hexrow">
        <span>HEX</span>
        {#key hex}
          <input
            class="pi-cp-hex"
            type="text"
            spellcheck="false"
            value={hex.replace(/^#/, "")}
            onblur={(e) => commitHexText(e.currentTarget)}
            onkeydown={(e) => {
              if (e.key === "Enter") {
                commitHexText(e.currentTarget);
                e.currentTarget.blur();
              }
            }}
          />
        {/key}
      </div>
      {#if tokens.length > 0}
        <div class="pi-cp-tokens">
          {#each tokens as [name, val] (name)}
            <button
              type="button"
              class="pi-cp-token"
              title={`${name} ${val}`}
              style="background: {val}"
              onclick={() => {
                const norm = normalizeHex(val);
                if (!norm) return;
                const rgb = hexToRgb(norm)!;
                hsv = rgbToHsv(rgb[0], rgb[1], rgb[2]);
                writeHex(norm);
              }}
            ></button>
          {/each}
        </div>
      {/if}
    </div>
  {/if}
</div>
