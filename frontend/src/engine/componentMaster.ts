import type { IRObject } from '../flow/types';

/** Resolve the requested master without substituting a different variant. */
export function selectedComponentMaster(component: Record<string, any> | null | undefined, variantKey = 'default'): IRObject | null {
  if (!component) return null;
  const variant = component.variants?.[variantKey];
  if (!variant && variantKey !== 'default') return null;
  if (variant?.masterRef === 'self') return component.masterIr || null;
  if (variant?.masterIr) return variant.masterIr;
  if (variant?.masterRef) return null;
  return component.masterIr || (component.origin === 'observed' ? null : component.templateIr) || null;
}

/** Display/working-copy coordinates only. Canonical Source masters stay unchanged. */
export function componentMasterPreview(master: IRObject): IRObject {
  const clone = JSON.parse(JSON.stringify(master)) as Record<string, any>;
  const root = clone.tree?.[0];
  if (!root || root.type === 'source-block') return clone as IRObject;
  const frame = root.frame || {};
  root.frame = { ...frame, x: 0, y: 0 };
  const overrides: Record<string, any> = {};
  for (const [name, override] of Object.entries(root.responsive || {}) as Array<[string, any]>) {
    if (!override?.frame) continue;
    override.frame = { ...override.frame, x: 0, y: 0 };
    overrides[name] = { frame: { width: override.frame.width ?? frame.width,
      height: override.frame.height ?? frame.height, layout: 'free' } };
  }
  const width = Number(frame.width) || 320, height = Number(frame.height) || 120;
  const hasResponsive = (node: any): boolean => !!node?.responsive && Object.keys(node.responsive).length > 0
    || (node?.children || []).some(hasResponsive);
  const viewports = Object.fromEntries((hasResponsive(root) || clone.responsive?.viewports ? ['desktop', 'tablet', 'mobile'] : [])
    .map(name => [name, { width: overrides[name]?.frame.width || width, height: overrides[name]?.frame.height || height }]));
  return {
    ...clone,
    ...(Object.keys(viewports).length ? { responsive: { ...clone.responsive, viewports } } : {}),
    frame: { width, height, layout: 'free' },
    tree: [{ id: 'ds-master-preview', type: 'source-block', variant: 'component-master',
      frame: { width, height, layout: 'free' }, responsive: overrides, props: {}, children: [root] }],
  } as IRObject;
}
