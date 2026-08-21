// @ts-nocheck
/* DesignAI Web — editable:false contract (Source Import raster fallback).
 * Слой с editable:false — intrinsically non-editable surface (canvas/webgl/
 * iframe/shadow/url-mask): он остаётся видимым, selectable и inspectable,
 * но content/geometry/style мутации (ручные и AI) обязаны отказывать.
 * Общий предикат используют renderer (маркировка data-ir-locked), geoedit,
 * inspector и editor controller — единая точка истины для контракта. */

/** true, если IR-узел помечен как intrinsically non-editable (raster fallback). */
export function isLockedNode(node) {
  return !!node && typeof node === "object" && node.editable === false;
}

/** Человекочитаемая причина блокировки (lockedReason из Source Import). */
export function lockedReason(node) {
  if (!isLockedNode(node)) return "";
  return String(node.lockedReason || "intrinsically non-editable surface");
}
