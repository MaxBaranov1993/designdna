<script lang="ts">
  /* Опции шрифтов для селектов инспектора — порт fontOptionsHtml:
   * каталог engine/fontCatalog с группами или плоский fallback-список.
   * Выбранное значение задаёт селект через value. */
  import { DesignAIFontCatalog } from "../../engine/fontCatalog";

  let { autoLabel }: { autoLabel?: string } = $props();

  const FALLBACK_FONTS = ["Inter", "Sora", "Manrope", "Playfair Display", "Space Grotesk", "DM Sans", "IBM Plex Mono", "Montserrat"];
  const catalog = DesignAIFontCatalog;
</script>

{#if autoLabel != null}
  <option value="">{autoLabel}</option>
{/if}
{#if catalog && catalog.groups}
  {#each catalog.groups as group (group.label)}
    <optgroup label={group.label}>
      {#each group.fonts as f (f)}
        <option value={f}>{f}</option>
      {/each}
    </optgroup>
  {/each}
{:else}
  {#each (catalog ? catalog.families : FALLBACK_FONTS) as f (f)}
    <option value={f}>{f}</option>
  {/each}
{/if}
