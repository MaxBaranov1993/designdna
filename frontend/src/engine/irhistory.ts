// @ts-nocheck
/* irhistory.js — общая snapshot-история IR (undo/redo) для ноды Edit и DNA-редактора.
 *
 * IRHistory.createHistory({ limit, coalesceMs }) → {
 *   push(snapshotFn, selKey) — снапшотFn вызывается СРАЗУ (паттерн snapshot-before-mutation:
 *     владелец зовёт push до мутации IR); быстрые повторные push (< coalesceMs) с тем же
 *     selKey сливаются в одну запись — иначе серия nudge стрелками вымыла бы весь стек;
 *   undo(currentFn) / redo(currentFn) — текущее состояние кладётся в противоположный стек,
 *     возвращается снапшот для восстановления (или null);
 *   canUndo(), canRedo(), clear()
 * }
 * Хранение — JSON-снапшоты (глубокая копия), лимит по умолчанию 50.
 */

  const DEFAULT_LIMIT = 50;
  const DEFAULT_COALESCE_MS = 500;

  function clone(v) { return JSON.parse(JSON.stringify(v)); }

  function createHistory(opts) {
    const limit = (opts && opts.limit) || DEFAULT_LIMIT;
    const coalesceMs = (opts && opts.coalesceMs != null) ? opts.coalesceMs : DEFAULT_COALESCE_MS;
    let undoStack = [];
    let redoStack = [];
    let lastPushTime = 0;
    let lastSelKey = null; // null — следующий push не коалесцируем

    /** Снапшот до мутации. Возвращает false, если push слился с предыдущим. */
    function push(snapshotFn, selKey) {
      const now = Date.now();
      const key = (selKey === undefined) ? null : selKey;
      const coalesce = undoStack.length > 0
        && key != null && key === lastSelKey
        && (now - lastPushTime) < coalesceMs;
      lastPushTime = now;
      lastSelKey = key;
      redoStack.length = 0; // новое действие инвалидирует redo-ветку
      if (coalesce) return false;
      undoStack.push(clone(snapshotFn()));
      if (undoStack.length > limit) undoStack.shift();
      return true;
    }

    function undo(currentFn) {
      if (!undoStack.length) return null;
      redoStack.push(clone(currentFn()));
      lastSelKey = null; // после undo серия считается разорванной
      return undoStack.pop();
    }

    function redo(currentFn) {
      if (!redoStack.length) return null;
      undoStack.push(clone(currentFn()));
      lastSelKey = null;
      return redoStack.pop();
    }

    function canUndo() { return undoStack.length > 0; }
    function canRedo() { return redoStack.length > 0; }
    function clear() { undoStack.length = 0; redoStack.length = 0; lastSelKey = null; }

    return { push, undo, redo, canUndo, canRedo, clear };
  }

export const IRHistory = { createHistory };
