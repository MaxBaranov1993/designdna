import type { DesignSystemNodeData } from '../flow/types';

/** Persisted pipeline state outranks a transient 'ready' badge after reload. */
export function designSystemIdleStatus(data: Partial<DesignSystemNodeData>) {
  const stages = Object.values(data.pipelineStatus || {});
  if (stages.some(s => s.status === 'failed')) return {text:'Validation error', kind:'err'};
  if (stages.some(s => s.status === 'cancelled')) return {text:'Incomplete', kind:'err'};
  if (stages.some(s => s.status === 'warning'))
    return {text:'Needs review', kind:'err'};
  if (data.lastError) return {text:'Error', kind:'err'};
  if (data.sourceUpdate) return {text:'Source changed', kind:'err'};
  if (!data.systemId) return undefined;
  if (Number(data.summary?.reviewMasters || 0) > 0)
    return {text:`UI Kit built · ${data.summary?.reviewMasters} need review`, kind:null};
  return {text:data.status === 'published' ? 'Published' : 'Draft', kind:null};
}
