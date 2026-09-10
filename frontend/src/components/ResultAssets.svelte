<script lang="ts">
  import { fillResultAssets, undoResultAssets, resultVariants, resultAssetsAreCurrent, type AssetVersion } from '../flow/result-assets';
  import { flowBusy } from '../flow/state';
  import type { AssetRun } from '../flow/generator-assets';
  import AssetRunDetails from './AssetRunDetails.svelte';
  let { id, type, data }: { id: string; type: string; data: any } = $props();
  let replace = $state(false);
  let busy = $derived(!!$flowBusy[Number(id)]);
  const allowed = $derived(type !== 'reskin' || data.mask?.images);
  const runs = $derived(data.assetRuns as AssetRun[] | undefined);
  const versions = $derived((data.assetVersions || []) as AssetVersion[]);
</script>

{#if resultVariants({ type, data }).length}
  <details class="result-assets nodrag nowheel">
    <summary>Изображения результата · Codex</summary>
    {#if allowed}
      <p>Общий стиль серии берётся из входного компонента. Обрабатываются места с описанием изображения.</p>
      <label><input type="checkbox" bind:checked={replace} disabled={busy} /> Обновить уже готовые изображения</label>
      <button class="btn-node small" disabled={busy} onclick={() => void fillResultAssets(Number(id), replace)}>Создать изображения через Codex</button>
    {:else}<p>Для изображений включите соответствующее поле маски Reskin.</p>{/if}
    {#if versions.length}<button class="btn-node small" disabled={busy} onclick={() => undoResultAssets(Number(id))}>Отменить обработку изображений</button>{/if}
    <AssetRunDetails {runs} {busy} currentResult={resultAssetsAreCurrent({ type, data })} onRetry={allowed ? (slotId) => void fillResultAssets(Number(id), runs?.at(-1)?.plan.context.replaceImages === true, slotId || '*') : undefined} />
  </details>
{/if}

<style>
  .result-assets { margin:8px 12px; font-size:11px; }
  summary { cursor:pointer; padding:6px 0; }
  p { line-height:1.5; opacity:.75; }
  label { display:block; margin:8px 0; }
  button { margin:4px 0; }
</style>
