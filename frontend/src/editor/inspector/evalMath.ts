/* Числовые поля инспектора: math-выражения («100*2+40», «960/3») и применение
 * значений через GeoEdit. Порт evalMath/readNumInput/applyNum из inspector.js —
 * поведение 1:1 (ui_p1_insp_test вбивает выражения и ждёт схлопывания в число). */
import type { GeoHandle } from "../globals";

/** Безопасный калькулятор для числовых полей (W: 100*2): цифры и + - * / ( ) .
 *  Без eval — ручной рекурсивный парсер; возвращает null если не выражение. */
export function evalMath(expr: string): number | null {
  const s = String(expr).replace(/\s+/g, "");
  if (!s || !/^[0-9+\-*/().]+$/.test(s)) return null;
  if (!/[+\-*/]/.test(s)) return null; // обычное число парсит Number
  let i = 0;
  function factor(): number | null {
    if (s[i] === "(") { i++; const v = expr2(); if (s[i] !== ")") return null; i++; return v; }
    if (s[i] === "-" || s[i] === "+") { const op = s[i++]; const v = factor(); return v == null ? null : op === "-" ? -v : v; }
    const m = /^[0-9.]+/.exec(s.slice(i));
    if (!m) return null;
    i += m[0].length;
    const n = Number(m[0]);
    return Number.isFinite(n) ? n : null;
  }
  function term(): number | null {
    let v = factor();
    while (v != null && (s[i] === "*" || s[i] === "/")) {
      const op = s[i++]; const r = factor();
      if (r == null) return null;
      if (op === "*") v *= r;
      else { if (r === 0) return null; v /= r; }
    }
    return v;
  }
  function expr2(): number | null {
    let v = term();
    while (v != null && (s[i] === "+" || s[i] === "-")) {
      const op = s[i++]; const r = term();
      if (r == null) return null;
      v = op === "+" ? v + r : v - r;
    }
    return v;
  }
  const v = expr2();
  return v != null && i === s.length ? v : null;
}

/** Значение числового инпута: выражение → число; пусто → null; мусор → undefined. */
export function readNumInput(inp: HTMLInputElement): number | null | undefined {
  const raw = String(inp.value).trim();
  if (raw === "") return null;
  const m = evalMath(raw);
  if (m != null) return Math.round(m);
  const n = Number(raw);
  return Number.isFinite(n) ? Math.round(n) : undefined;
}

export function applyNum(geo: GeoHandle, key: string, v: number | null) {
  if (key === "x" || key === "y" || key === "width" || key === "height") {
    geo.setFrame({ [key]: v });
  } else if (key === "rotation") {
    geo.setFrameProps({ rotation: v == null || v === 0 ? null : v });
  } else if (key === "gap") {
    geo.setFrameProps({ gap: v == null ? null : Math.max(0, v) });
  }
}
