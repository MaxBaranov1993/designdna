/* Color picker инспектора (по мотивам OpenPencil color-picker-panel, MIT):
 * SV-поле + hue-слайдер + HEX + быстрые свотчи design-токенов IR.
 * Запись идёт через скрытый нативный input[data-style-color] — wiring уже в
 * wireInspector.ts, контракт с legacy 1:1 (включая синхронизацию text-поля). */
import { useEffect, useRef, useState } from "react";
import * as ctl from "../controller";

/* ---------- цветовая математика ---------- */

export function hexToRgb(hex: string): [number, number, number] | null {
  let s = String(hex || "").trim().replace(/^#/, "");
  if (/^[0-9a-f]{3}$/i.test(s)) s = s.split("").map((c) => c + c).join("");
  if (!/^[0-9a-f]{6}$/i.test(s)) return null;
  return [parseInt(s.slice(0, 2), 16), parseInt(s.slice(2, 4), 16), parseInt(s.slice(4, 6), 16)];
}

export function rgbToHex(r: number, g: number, b: number): string {
  const h = (v: number) =>
    Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0");
  return ("#" + h(r) + h(g) + h(b)).toLowerCase();
}

export function rgbToHsv(r: number, g: number, b: number): [number, number, number] {
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

export function hsvToRgb(h: number, s: number, v: number): [number, number, number] {
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

/* ---------- компонент ---------- */

interface ColorFieldProps {
  styleKey: string;    // background | color | borderColor
  label: string;
  hex: string;         // полный hex для свотча (fallback уже применён)
  raw: string;         // как записано в IR (для text-инпута)
  transparent: boolean;
}

const PICKER_W = 232;
const PICKER_H = 316;

export function ColorField({ styleKey, label, hex, raw, transparent }: ColorFieldProps) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [hsv, setHsv] = useState<[number, number, number]>(() => {
    const rgb = hexToRgb(hex) || [255, 255, 255];
    return rgbToHsv(rgb[0], rgb[1], rgb[2]);
  });
  const fieldRef = useRef<HTMLDivElement | null>(null);
  const swatchRef = useRef<HTMLButtonElement | null>(null);
  const popRef = useRef<HTMLDivElement | null>(null);
  const svRef = useRef<HTMLDivElement | null>(null);
  const hueRef = useRef<HTMLInputElement | null>(null);

  /** Запись через скрытый нативный input: wireInspector сам применит стиль
   *  и синхронизирует text-поле (контракт legacy). */
  const writeHex = (value: string) => {
    const root = fieldRef.current;
    if (!root) return;
    const native = root.querySelector<HTMLInputElement>(
      `input[data-style-color="${styleKey}"]`);
    if (!native) return;
    native.value = value;
    native.dispatchEvent(new Event("input", { bubbles: true }));
  };

  const openPicker = () => {
    // переинициализация hsv из текущего значения при каждом открытии
    const rgb = hexToRgb(fieldRef.current
      ?.querySelector<HTMLInputElement>(`input[data-style-text="${styleKey}"]`)?.value || "") || hexToRgb(hex) || [255, 255, 255];
    setHsv(rgbToHsv(rgb[0], rgb[1], rgb[2]));
    const r = swatchRef.current?.getBoundingClientRect();
    if (r) {
      setPos({
        x: Math.max(8, Math.min(r.right - PICKER_W, window.innerWidth - PICKER_W - 8)),
        y: Math.max(8, Math.min(r.bottom + 4, window.innerHeight - PICKER_H - 8)),
      });
    }
    setOpen(true);
  };

  /* Пока пикер открыт, инспектор не перестраивается (inspScrubbing — тот же
   * механизм, что для scrub-drag): иначе tick-ремаунт убьёт DOM пикера при
   * каждой записи стиля. Закрытие возвращает перестройку. */
  useEffect(() => {
    if (!open) return;
    ctl.setInspScrubbing(true);
    return () => ctl.setInspScrubbing(false);
  }, [open]);

  /* Escape — закрыть только пикер (window capture раньше document-capture
   * geoedit, иначе Esc снимет выделение/закроет редактор);
   * клик вне пикера закрывает его, само действие клика не гасится. */
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        setOpen(false);
      }
    };
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node | null;
      if (t && popRef.current && popRef.current.contains(t)) return;
      if (t && swatchRef.current && swatchRef.current.contains(t)) return;
      setOpen(false);
    };
    window.addEventListener("keydown", onKey, true);
    document.addEventListener("pointerdown", onDown, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      document.removeEventListener("pointerdown", onDown, true);
    };
  }, [open]);

  const applyHsv = (h: number, s: number, v: number) => {
    const hh = Math.max(0, Math.min(360, h));
    const ss = Math.max(0, Math.min(1, s));
    const vv = Math.max(0, Math.min(1, v));
    setHsv([hh, ss, vv]);
    const rgb = hsvToRgb(hh, ss, vv);
    writeHex(rgbToHex(rgb[0], rgb[1], rgb[2]));
  };

  /* Hue-слайдер: нативный input-слушатель вместо React onChange —
   * контролируемый range не стабильно реагирует на программную запись value. */
  useEffect(() => {
    if (!open) return;
    const el = hueRef.current;
    if (!el) return;
    const onInput = () => applyHsv(Number(el.value), hsv[1], hsv[2]);
    el.addEventListener("input", onInput);
    return () => el.removeEventListener("input", onInput);
  }, [open, hsv]);

  const svFromEvent = (e: PointerEvent) => {
    const el = svRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const s = (e.clientX - r.left) / Math.max(1, r.width);
    const v = 1 - (e.clientY - r.top) / Math.max(1, r.height);
    applyHsv(hsv[0], s, v);
  };

  const svDown = (e: React.PointerEvent) => {
    e.preventDefault();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    svFromEvent(e.nativeEvent);
    const move = (ev: PointerEvent) => svFromEvent(ev);
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const commitHexText = (el: HTMLInputElement) => {
    const norm = normalizeHex(el.value);
    if (!norm) return;
    const rgb = hexToRgb(norm)!;
    setHsv(rgbToHsv(rgb[0], rgb[1], rgb[2]));
    writeHex(norm);
  };

  const tokens = ((): [string, string][] => {
    const s = ctl.getSession();
    const c = s && s.ir && s.ir.tokens && s.ir.tokens.color;
    if (!c || typeof c !== "object") return [];
    return Object.entries(c).filter(([, v]) => typeof v === "string") as [string, string][];
  })();

  return (
    <div className="pi-field" ref={fieldRef}>
      <label>{label}</label>
      <input type="color" data-style-color={styleKey} defaultValue={hex} className="pi-cp-native" />
      <button
        type="button"
        ref={swatchRef}
        className={`pi-cp-swatch ${transparent ? "pi-empty" : ""}`}
        title="Открыть пикер цвета"
        onClick={openPicker}
      >
        <span className="pi-cp-fill" style={{ background: transparent ? "transparent" : hex }} />
      </button>
      <button
        className={`pi-ibtn pi-clear-color ${transparent ? "pi-active" : ""}`}
        data-clear-style={styleKey}
        title="Transparent"
      >×</button>
      <input type="text" data-style-text={styleKey} defaultValue={raw} placeholder="transparent" />

      {open && (
        <div className="pi-cp-pop" ref={popRef} style={{ left: pos.x, top: pos.y }}>
          <div
            className="pi-cp-sv"
            ref={svRef}
            style={{
              background:
                `linear-gradient(to top,#000,rgba(0,0,0,0)),` +
                `linear-gradient(to right,#fff,hsl(${Math.round(hsv[0])},100%,50%))`,
            }}
            onPointerDown={svDown}
          >
            <div
              className="pi-cp-thumb"
              style={{ left: `${hsv[1] * 100}%`, top: `${(1 - hsv[2]) * 100}%` }}
            />
          </div>
          <input
            className="pi-cp-hue"
            type="range"
            min={0}
            max={360}
            ref={hueRef}
            value={Math.round(hsv[0])}
            onChange={() => {/* нативный слушатель в useEffect */}}
          />
          <div className="pi-cp-hexrow">
            <span>HEX</span>
            <input
              className="pi-cp-hex"
              type="text"
              spellCheck={false}
              defaultValue={hex.replace(/^#/, "")}
              key={hex}
              onBlur={(e) => commitHexText(e.currentTarget)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  commitHexText(e.currentTarget);
                  (e.currentTarget as HTMLInputElement).blur();
                }
              }}
            />
          </div>
          {tokens.length > 0 && (
            <div className="pi-cp-tokens">
              {tokens.map(([name, val]) => (
                <button
                  key={name}
                  type="button"
                  className="pi-cp-token"
                  title={`${name} ${val}`}
                  style={{ background: val }}
                  onClick={() => {
                    const norm = normalizeHex(val);
                    if (!norm) return;
                    const rgb = hexToRgb(norm)!;
                    setHsv(rgbToHsv(rgb[0], rgb[1], rgb[2]));
                    writeHex(norm);
                  }}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
