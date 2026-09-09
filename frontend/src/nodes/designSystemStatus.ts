import type { DesignSystemNodeData } from '../flow/types';

/** Persisted pipeline state outranks a transient 'ready' badge after reload. */
export function designSystemIdleStatus(data: Partial<DesignSystemNodeData>) {
  const stages = Object.values(data.pipelineStatus || {});
  if (stages.some(s => s.status === 'failed')) return {text:'Ошибка проверки', kind:'err'};
  if (stages.some(s => s.status === 'cancelled')) return {text:'Не завершено', kind:'err'};
  if (stages.some(s => s.status === 'warning'))
    return {text:'Нужно ревью', kind:'err'};
  if (data.lastError) return {text:'Ошибка', kind:'err'};
  if (data.sourceUpdate) return {text:'Source изменён', kind:'err'};
  if (!data.systemId) return undefined;
  if (Number(data.summary?.reviewMasters || 0) > 0)
    return {text:`UI Kit собран · ${data.summary?.reviewMasters} требуют проверки`, kind:null};
  return {text:data.status === 'published' ? 'Опубликовано' : 'Черновик', kind:null};
}
