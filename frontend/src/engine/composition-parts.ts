import type { IRObject } from '../flow/types';

export type PartGroup = 'background' | 'image' | 'text' | 'decoration' | 'container';
export type CompositionPart = {
  path: string; group: PartGroup; label: string; sourceKey?: string;
  image?: string; protected: boolean; kind: 'text' | 'pixels' | 'structure';
};
export const PART_GROUPS: Array<[PartGroup, string]> = [
  ['background', 'Подложки'], ['image', 'Изображения'], ['text', 'Тексты'],
  ['decoration', 'Декор'], ['container', 'Контейнеры'],
];

/** Inventory only: no normalization, flattening, or mutation of canonical masters. */
export function compositionParts(ir: IRObject | null | undefined, protectedRoot = false) {
  const parts: CompositionPart[] = [];
  let visited = 0, truncated = false;
  function walk(node: any, path: string, inherited: boolean) {
    if (!node || typeof node !== 'object') return;
    if (++visited > 5000) { truncated = true; return; }
    const protectedPart = inherited || node.editable === false || !!node.componentRef
      || !!node._dsMaster || !!node.sourceMeta?.componentRef || node.type === 'source-block';
    const props = node.props || {}, style = node.style || {};
    const add = (group: PartGroup, label: string, kind: CompositionPart['kind'], image?: string) => {
      parts.push({ path, group, label, kind, image, sourceKey: node.sourceKey, protected: protectedPart });
    };
    const background = style.backgroundImage;
    const backgroundUrl = typeof background === 'string' ? /^url\(["']?(.*?)["']?\)$/.exec(background)?.[1] : '';
    if (backgroundUrl) add('background', 'Фоновое изображение', 'pixels', backgroundUrl);
    else if (background || style.background || style.backgroundColor || node.fill) add('background', 'Заливка', 'structure');
    const image = node.src || props.src || props.media?.src;
    if (typeof image === 'string' && image) add('image', String(node.alt || props.alt || props.media?.alt || 'Изображение'), 'pixels', image);
    else if (node.type === 'image' || node.imagePrompt || props.imagePrompt) add('image', 'Изображение отсутствует', 'pixels');
    const texts = [node.text, ...['text', 'heading', 'title', 'subheading', 'label', 'caption', 'description'].map(key => props[key])]
      .filter((value): value is string => typeof value === 'string' && !!value.trim());
    for (const value of [...new Set(texts)]) add('text', value, 'text');
    if (['icon', 'svg', 'path', 'shape', 'line', 'divider', 'rect', 'ellipse'].includes(node.type)) {
      add('decoration', String(node.name || props.name || node.type), 'structure');
    } else if (node.children?.length || (!image && !texts.length && node.type !== 'image')) {
      add('container', String(node.name || node.type || 'Группа'), 'structure');
    }
    for (const [index, child] of (node.children || []).entries()) walk(child, `${path}.children.${index}`, protectedPart);
  }
  (Array.isArray(ir?.tree) ? ir.tree : []).forEach((node: any, index: number) => walk(node, `tree.${index}`, protectedRoot));
  return { parts, truncated };
}
