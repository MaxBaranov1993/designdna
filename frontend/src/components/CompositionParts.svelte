<script lang="ts">
  import type { IRObject } from '../flow/types';
  import { compositionParts, PART_GROUPS } from '../engine/composition-parts';
  let { ir, protectedRoot = false }: { ir: IRObject | null; protectedRoot?: boolean } = $props();
  const inventory = $derived(compositionParts(ir, protectedRoot));
</script>

<details class="composition-parts nodrag nowheel">
  <summary>Состав компонента · {inventory.parts.filter(part => part.kind === 'text').length} текстов · {inventory.parts.filter(part => part.kind === 'pixels').length} изображений</summary>
  <p>Тексты хранятся в IR; внутренние детали изображений — в пикселях. Защищённые части редактируются через рабочую копию.</p>
  {#each PART_GROUPS as [key, title]}
    {@const group = inventory.parts.filter(part => part.group === key)}
    {#if group.length}
      <details class="part-group">
        <summary>{title} · {group.length}</summary>
        <ul>
          {#each group as part}
            <li title={`${part.path}${part.sourceKey ? ` · ${part.sourceKey}` : ''}`}>
              {#if part.image}<img src={part.image} alt={part.label} loading="lazy" />{/if}
              <span class="part-label">{part.label}</span>
              <small>{part.protected ? 'Защищено' : part.kind === 'pixels' ? 'Ресурс' : 'IR'}</small>
            </li>
          {/each}
        </ul>
      </details>
    {/if}
  {/each}
  {#if inventory.truncated}<p>Показаны первые 5000 узлов.</p>{/if}
</details>

<style>
  .composition-parts { padding:10px; color:var(--text-muted, #aaa); font-size:11px; border-top:1px solid var(--border, #333); }
  summary { cursor:pointer; line-height:1.5; }
  p { margin:8px 0; line-height:1.5; }
  .part-group { margin:6px 0; }
  ul { list-style:none; padding:0; margin:5px 0; max-height:260px; overflow:auto; }
  li { display:flex; align-items:center; gap:8px; padding:6px 0; border-bottom:1px solid var(--border, #333); }
  img { width:48px; height:40px; object-fit:contain; background:repeating-conic-gradient(#252529 0 25%, #38383c 0 50%) 0 0 / 12px 12px; }
  .part-label { overflow-wrap:anywhere; min-width:0; flex:1; max-height:72px; overflow:auto; }
  small { flex-shrink:0; opacity:.7; }
</style>
