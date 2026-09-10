/** A reversible timeline preset. It never writes into a page's canonical Design IR. */
export function assembleLayers(document: Record<string, any>): number {
  const page = document.story?.pages?.find((p: any) => p.id === document.story.initialPageId);
  if (!page) throw new Error('Подключите страницу к Видео');
  const groups = new Map<string, any>((document.groups || []).map((group: any) => [group.id, group]));
  const locked = (layer: any) => {
    if (layer.locked) return true;
    let parent = layer.parent;
    const seen = new Set();
    while (parent && !seen.has(parent)) {
      seen.add(parent); const group = groups.get(parent);
      if (group?.locked) return true;
      parent = group?.parent;
    }
    return false;
  };
  const candidates = (document.layers || []).filter((layer: any) => layer.type === 'component'
    && layer.storyTarget && (!layer.pageId || layer.pageId === page.id));
  const layers = candidates.filter((layer: any) => !locked(layer) && layer.in === 0 && layer.out >= 100
    && !Object.keys(layer.transform?.properties || {}).length
    && !candidates.some((other: any) => other !== layer && other.storyTarget.startsWith(layer.storyTarget + '.children.')));
  if (!layers.length) throw new Error('Нет свободных слоёв: существующая анимация и блокировки сохраняются');
  const kind = (layer: any) => {
    const path = String(layer.storyTarget).replace(/^s(\d+)/, 'tree.$1').split('.');
    const node = path.reduce((value: any, key: string) => value?.[key], page.ir);
    return node?.type === 'image' ? 2 : ['text', 'heading', 'button'].includes(node?.type) ? 1 : 0;
  };
  layers.sort((a: any, b: any) => kind(a) - kind(b));
  const duration = Math.min(2000, document.composition.duration, ...layers.map((layer: any) => layer.out));
  layers.forEach((layer: any, index: number) => {
    const start = Math.floor(index / layers.length * duration * .65), end = Math.floor(start + duration * .3);
    const keys = (from: number, to: number) => ({ keyframes: [
      { t: 0, value: from, easing: 'linear' },
      ...(start ? [{ t: start, value: from, easing: 'ease-out' }] : []),
      { t: end, value: to, easing: 'ease-out' },
    ] });
    layer.transform = { ...layer.transform, properties: { opacity: keys(0, 1), y: keys(24, 0) } };
  });
  return layers.length;
}
