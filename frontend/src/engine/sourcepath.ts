// @ts-nocheck
/* DesignAI Web — Source Import адресация: стабильный sourceKey вместо numeric path.
 * Чистые функции без DOM: используются geoedit (структурные мутации) и
 * headless regression-тестами (frontend/tests/engine.regression.test.mjs).
 *
 * sourceKey — иерархический ключ захвата ("block:root/div:1"; синтетические
 * слои: "block:root/div:1::text0"). Навигация (parentRef/hoisting) и
 * структурные мутации (delete/duplicate/group/reorder) обязаны опираться на
 * locateByKey/parentKeyByKey — фактический parentNode: строковый разбор ключа
 * (sourceParentPath) после groupSelection возвращает старого родителя. */

/** true, если path — sourceKey Source Import (не children.* и не props.*). */
export function isSourceKeyPath(path) {
  return !!path && !path.startsWith("children.") && !path.startsWith("props.");
}

/** Поиск узла по sourceKey/__path внутри секции (Source Import identity). */
export function findByKey(sec, key) {
  let found = null;
  const walk = (n) => {
    if (!n || typeof n !== "object" || found) return;
    if (n.sourceKey === key || n.__path === key) { found = n; return; }
    (n.children || []).forEach(walk);
  };
  walk(sec);
  return found;
}

/** Родитель sourceKey-пути: "b:root/div:1/div:2" → "b:root/div:1";
 *  синтетический слой ("b:root/div:1::bg0") принадлежит своему элементу;
 *  "b:root" → сама секция (path null). undefined — не sourceKey-путь. */
export function sourceParentPath(path) {
  if (!path || path.startsWith("children.") || path.startsWith("props.")) return undefined;
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

/** Структурный lookup: фактический массив children родителя, узел и его
 *  точный индекс. null — ключ структурно не представлен в дереве (stale ref,
 *  синтетический ключ вне children): структурные мутации обязаны отказать,
 *  а не гадать по формату ключа. Синтетические слои (::text0/::bg0/::value)
 *  валидны, пока они реально лежат в children своего элемента. */
export function locateByKey(sec, key) {
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

/** Фактический родитель sourceKey-узла: sourceKey родителя, null — родитель
 *  сама секция (ref.path === null), undefined — ключ структурно не представлен
 *  (stale ref, неадресуемый родитель): навигация обязана отказать, а не гадать
 *  по формату ключа. В отличие от sourceParentPath идёт через locateByKey —
 *  реальный parentNode: после groupSelection дети лежат в группе
 *  "<prefix>/group~<uid>", а их sourceKey НЕ меняется, поэтому строковый разбор
 *  ключа вернул бы старого родителя. */
export function parentKeyByKey(sec, key) {
  const located = locateByKey(sec, key);
  if (!located) return undefined;
  const parentNode = located.parentNode;
  if (parentNode === sec) return null;
  const k = parentNode.sourceKey || parentNode.__path;
  return k != null ? String(k) : undefined;
}

/** Свежие sourceKey всему поддереву дубликата. Иерархия ключа сохраняется
 *  (родительский префикс + маркер "~<uid>"), поэтому строковая навигация
 *  (sourceParentPath) и DOM-адресация (annotatePaths: __path = sourceKey)
 *  остаются валидными, а ключи не пересекаются с захваченными: компилятор
 *  генерирует только tag:idx / root / "::suffix" — "~" в них не встречается.
 *  uidFn() обязан давать уникальное значение на каждый вызов.
 *  __path — рантайм-аннотация рендерера: сбрасываем, чтобы клон не делил
 *  DOM-identity с оригиналом до следующего annotatePaths. */
export function rekeyCloneKeys(root, uidFn) {
  if (!root || typeof root !== "object" || root.sourceKey == null) return root;
  const origRoot = String(root.sourceKey);
  const newRoot = origRoot + "~" + uidFn();
  let extra = 0;
  const walk = (n, isRootNode) => {
    if (!n || typeof n !== "object") return;
    if (n.sourceKey != null) {
      const k = String(n.sourceKey);
      if (isRootNode || k === origRoot) n.sourceKey = newRoot;
      else if (k.startsWith(origRoot) &&
               (k.charAt(origRoot.length) === "/" || k.charAt(origRoot.length) === ":")) {
        n.sourceKey = newRoot + k.slice(origRoot.length);
      } else {
        // ключ вне иерархии корня (дефект захвата) — привязываем к клону явно
        n.sourceKey = newRoot + "::dup" + (extra++);
      }
    }
    delete n.__path;
    (n.children || []).forEach((c) => walk(c, false));
  };
  walk(root, true);
  return root;
}
