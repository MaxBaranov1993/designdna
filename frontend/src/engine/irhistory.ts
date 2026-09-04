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
    let cancelledRedo = null;
    let lastPushedSnapshot = null; // для cancelLast: только реально запушенная запись

    /** Снапшот до мутации. Возвращает false, если push слился с предыдущим. */
    function push(snapshotFn, selKey) {
      const now = Date.now();
      const key = (selKey === undefined) ? null : selKey;
      const coalesce = undoStack.length > 0
        && key != null && key === lastSelKey
        && (now - lastPushTime) < coalesceMs;
      lastPushTime = now;
      lastSelKey = key;
      cancelledRedo = redoStack.slice();
      redoStack.length = 0; // новое действие инвалидирует redo-ветку
      if (coalesce) { lastPushedSnapshot = null; return false; }
      const snapshot = clone(snapshotFn());
      undoStack.push(snapshot);
      if (undoStack.length > limit) undoStack.shift();
      lastPushedSnapshot = snapshot;
      return true;
    }

    /** Отменяет последний push, если мутация после него не применилась —
     *  отказ операции не должен оставлять фантомный undo-шаг. Безопасно
     *  сразу после push; слиявшиеся (coalesced) push не отменяет. */
    function cancelLast() {
      if (lastPushedSnapshot && undoStack.length
          && undoStack[undoStack.length - 1] === lastPushedSnapshot) {
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
      lastSelKey = null; // после undo серия считается разорванной
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

    function canUndo() { return undoStack.length > 0; }
    function canRedo() { return redoStack.length > 0; }
    function clear() { cancelledRedo = null; lastPushedSnapshot = null; undoStack.length = 0; redoStack.length = 0; lastSelKey = null; }

    return { push, undo, redo, canUndo, canRedo, clear, cancelLast };
  }

export const IRHistory = { createHistory };
