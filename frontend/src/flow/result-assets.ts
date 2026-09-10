import { api } from './api';
import { assetRunPatch, executeAssetPlan, type AssetRun, type AssetPlan } from './generator-assets';
import { captureNodeScope, beginRunAbort, endRunAbort, bindPageState, useFlowStore } from './store';
import { pullInput } from './dataflow';
import { portsOfNode } from './ports';
import { compositionParts } from '../engine/composition-parts';
import { isImageSource } from './image-assets';
import { inputFingerprint } from './fingerprint';
import type { IRObject } from './types';

export type AssetVersion = { runId: string; before: IRObject[]; after: IRObject[] };
export function resultVariants(node: { type?: string; data: any }): IRObject[] {
  return node.type === 'derive' ? node.data.variants : node.type === 'mix'
    ? node.data.mixVariants?.length ? node.data.mixVariants : node.data.ir ? [node.data.ir] : []
    : node.data.ir ? [node.data.ir] : [];
}
export function resultAssetsAreCurrent(node: { type?: string; data: any }): boolean {
  const version = (node.data.assetVersions as AssetVersion[] | undefined)?.at(-1);
  return !!version && version.runId === node.data.assetRuns?.at(-1)?.id
    && JSON.stringify(resultVariants(node)) === JSON.stringify(version.after);
}
function resultPatch(node: any, variants: IRObject[]) {
  return node.type === 'derive' ? { variants } : node.type === 'mix'
    ? { mixVariants: variants, ir: variants[node.data.mixActive || 0] || variants[0] } : { ir: variants[0] };
}

/** Explicit per-node image operation, using the same guarded executor as Generator. */
export async function fillResultAssets(id: number, replaceImages = false, onlySlot?: string) {
  const get = bindPageState(), state = get(), node = state.nodes.find(n => Number(n.id) === id);
  if (!node || !['derive', 'reskin', 'mix'].includes(node.type || '') || state.busy[id]) return;
  if (node.type === 'reskin' && !(node.data as any).mask?.images) return;
  const variants = resultVariants(node);
  if (!variants.length) return;
  const scope = captureNodeScope(get, id), signal = beginRunAbort(id, state.activePageId);
  const fingerprint = () => {
    const current = get(), target = current.nodes.find(n => n.id === node.id);
    if (!target) return '';
    const { assetRuns, assetVersions, ...data } = target.data as any;
    return inputFingerprint({ data, designSystems: current.designSystemPicker, inputs: portsOfNode(target).in.map(port =>
      [port.name, current.edges.filter(e => e.target === node.id && e.targetHandle === port.name), pullInput(current.nodes, current.edges, target, port.name)]) });
  };
  let expected = fingerprint();
  scope.watchInputs(() => fingerprint() === expected);
  const set = (patch: Record<string, unknown>) => { scope.check(); get().setNodeData(id, patch); expected = fingerprint(); };
  const data = node.data as any;
  const reference = portsOfNode(node).in.map(port => ({ port: port.name, value: pullInput(state.nodes, state.edges, node, port.name) }))
    .map(input => ({ ...input, part: compositionParts(input.value as IRObject).parts.find(part => isImageSource(part.image)) }))
    .find(input => input.part);
  const referenceEdge = reference && state.edges.find(edge => edge.target === node.id && edge.targetHandle === reference.port);
  get().setBusy(id, true);
  let run: AssetRun | undefined;
  const before = structuredClone(variants);
  try {
    const plan = await scope.wait(api<AssetPlan>('/api/generate/assets/prepare', { variants, context: {
      brief: data.prompt || '', coherentSeries: true, replaceImages,
      ...(reference ? { referenceImage: reference.part!.image, referenceSource: { port: reference.port, path: reference.part!.path,
        nodeId: referenceEdge?.source, sourcePort: referenceEdge?.sourceHandle } } : {}),
    } }, { signal }));
    if (onlySlot) {
      const prior = (data.assetRuns as AssetRun[] | undefined)?.at(-1);
      plan.slots = plan.slots.filter(slot => {
        const previous = prior?.plan.slots.find(item => item.id === slot.id && item.status !== 'complete');
        return previous && previous.targetHash === slot.targetHash && (onlySlot === '*' || slot.id === onlySlot);
      });
    }
    if (!plan.slots.length) { get().setStatus(id, 'Нет доступных мест для изображений', 'ok'); return; }
    run = { id: crypto.randomUUID(), inputKey: expected, pageId: state.activePageId, startedAt: Date.now(),
      status: 'running', provider: 'codex', events: [], plan };
    await executeAssetPlan(variants, run, { signal, scope,
      onStage: label => get().setStatus(id, label),
      onChange: (output, snapshot) => {
        run = snapshot;
        const current = get().nodes.find(n => n.id === node.id)!;
        const history = ((current.data as any).assetVersions || []) as AssetVersion[];
        set({ ...resultPatch(current, output), assetRuns: assetRunPatch((current.data as any).assetRuns, snapshot),
          assetVersions: [...history.filter(item => item.runId !== snapshot.id), { runId: snapshot.id, before, after: output }].slice(-4) });
        get().propagate(id);
      } });
    get().setStatus(id, run.status === 'complete' ? 'Изображения готовы' : 'Часть изображений требует повтора', run.status === 'complete' ? 'ok' : 'err');
  } catch (error) {
    if (scope.owns()) get().setStatus(id, error instanceof Error ? error.message : String(error), 'err');
  } finally {
    if (scope.owns()) {
      const current = get().nodes.find(n => n.id === node.id)!;
      const history = (current.data as any).assetRuns as AssetRun[] | undefined;
      if (history?.at(-1)?.status === 'running') {
        const last = structuredClone(history.at(-1)!);
        last.status = 'cancelled'; last.finishedAt = Date.now();
        last.plan.slots.forEach(slot => { if (slot.status === 'running') slot.status = 'failed'; });
        get().setNodeData(id, { assetRuns: assetRunPatch(history, last) });
      }
      get().setBusy(id, false);
    }
    endRunAbort(id, signal, state.activePageId);
  }
}

export function undoResultAssets(id: number) {
  const state = useFlowStore.getState(), node = state.nodes.find(n => Number(n.id) === id);
  if (!node || state.busy[id]) return;
  const history = ((node.data as any).assetVersions || []) as AssetVersion[], last = history.at(-1);
  if (!last || JSON.stringify(resultVariants(node)) !== JSON.stringify(last.after)) {
    state.setStatus(id, 'Результат изменён после обработки изображений; отмена его не перезапишет', 'err'); return;
  }
  state.setNodeData(id, { ...resultPatch(node, structuredClone(last.before)), assetVersions: history.slice(0, -1) });
  state.propagate(id);
  state.setStatus(id, 'Изображения восстановлены', 'ok');
}
