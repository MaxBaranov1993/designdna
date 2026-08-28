<script lang="ts">
  import type { SourceArtifact } from "../flow/types";
  import ComponentCatalogPreview from "./ComponentCatalogPreview.svelte";

  type CatalogPool = "components" | "review" | "suggestions";
  type CatalogEntry = { key: string; pool: CatalogPool; component: Record<string, any> };

  let {
    artifact,
    catalogEntries = [],
    catalog = {},
    acceptedMasters = 0,
    acceptedVariants = 0,
    onOpen,
  }: {
    artifact: SourceArtifact | null;
    catalogEntries?: CatalogEntry[];
    catalog?: Record<string, any>;
    acceptedMasters?: number;
    acceptedVariants?: number;
    onOpen?: (key: string, pool: CatalogPool) => void;
  } = $props();

  /* Одно семейство — одна карточка. Fidelity-гейт раскладывает провалившиеся
   * вхождения в ключи "family-review", "-review-2", ... — раньше каждый такой
   * ключ становился отдельной карточкой с тем же названием, и каталог выглядел
   * как свалка дублей. Здесь review-вхождения сворачиваются под свой мастер. */
  type FamilyCard = { baseKey: string; primary: CatalogEntry; review: CatalogEntry[] };

  const baseKeyOf = (key: string) => key.replace(/-review(?:-\d+)?$/, "");

  function mergeFamilies(entries: CatalogEntry[]): FamilyCard[] {
    const families = new Map<string, FamilyCard>();
    const order: string[] = [];
    for (const entry of entries) {
      const baseKey = baseKeyOf(entry.key);
      let family = families.get(baseKey);
      if (!family) {
        family = { baseKey, primary: entry, review: [] };
        families.set(baseKey, family);
        order.push(baseKey);
        continue;
      }
      // Мастером карточки становится verified-вхождение из основного пула;
      // остальные показываются внутри как экземпляры на ревью.
      const better = entry.pool === "components" && family.primary.pool !== "components";
      if (better) {
        family.review.push(family.primary);
        family.primary = entry;
      } else {
        family.review.push(entry);
      }
    }
    return order.map((key) => families.get(key)!);
  }

  let screens = $derived(artifact?.screens || []);
  let foundationGroups = $derived(artifact?.foundations.groups || []);
  let catalogGroups = $derived.by((): Array<[string, FamilyCard[]]> => {
    const byKey = new Map(catalogEntries.map((entry) => [entry.key, entry]));
    const groups: Array<[string, CatalogEntry[]]> = [];
    const seen = new Set<string>();
    for (const section of catalog.sections || []) {
      const entries = (section.componentKeys || [])
        .map((key: string) => byKey.get(key))
        .filter((entry: CatalogEntry | undefined): entry is CatalogEntry => !!entry);
      for (const entry of entries) seen.add(entry.key);
      if (entries.length) groups.push([String(section.label || section.key), entries]);
    }
    const fallback = new Map<string, CatalogEntry[]>();
    for (const entry of catalogEntries) {
      if (seen.has(entry.key)) continue;
      const category = String(entry.component.category || "Other");
      fallback.set(category, [...(fallback.get(category) || []), entry]);
    }
    return [...groups, ...Array.from(fallback.entries())]
      .map(([label, entries]) => [label, mergeFamilies(entries)]);
  });
  let detectedComponents = $derived(catalogEntries.length
    || artifact?.summary.componentSetCount || artifact?.summary.componentCount || 0);
  let detectedVariants = $derived(catalogEntries.length
    ? catalogEntries.reduce((total, entry) => total + Math.max(1, Object.keys(entry.component.variants || {}).length), 0)
    : artifact?.summary.variantCount ?? artifact?.summary.observedStateCount ?? 0);

  const percent = (value: unknown) => {
    const score = Number(value);
    return Number.isFinite(score) ? `${Math.round(score * 100)}%` : "—";
  };
  const dimension = (value: unknown) => {
    const size = Number(value);
    return Number.isFinite(size) ? Math.round(size).toLocaleString() : "—";
  };
</script>

{#if artifact}
  <div class="source-workbench">
    <header class="source-intro">
      <div>
        <span class="source-eyebrow">Measured Source Artifact</span>
        <h2>Observed UI → accepted system</h2>
        <p>Every exact Source master stays visible. Quality decides publishability, not whether a component exists.</p>
      </div>
      <code>{artifact.source.pipelineVersion}</code>
    </header>

    <section class="source-funnel" aria-label="Detected Source content and accepted Design System content">
      <div class="source-observed">
        <span>Detected in Source</span>
        <strong>{detectedComponents}</strong>
        <small>components · {detectedVariants} variants</small>
      </div>
      <div class="source-transfer" aria-hidden="true"><i></i><b>review</b><em>→</em></div>
      <div class="source-accepted">
        <span>Accepted in System</span>
        <strong>{acceptedMasters}</strong>
        <small>masters · {acceptedVariants} variants</small>
      </div>
    </section>

    <section class="source-section">
      <div class="source-section-head">
        <div><span>01</span><h3>Foundations</h3></div>
        <small>{artifact.summary.tokenCount ?? 0} measured tokens</small>
      </div>
      <div class="foundation-strip">
        {#each foundationGroups as group (group.key)}
          <span title={group.key}>{group.name}<strong>{group.tokenCount}</strong></span>
        {:else}
          <span>Raw groups<strong>{Object.keys(artifact.foundations.tokens || {}).length}</strong></span>
        {/each}
      </div>
    </section>

    <section class="source-section">
      <div class="source-section-head">
        <div><span>02</span><h3>Screens</h3></div>
        <small>{screens.length} viewport compositions</small>
      </div>
      <div class="screen-grid">
        {#each screens as screen (screen.screenKey)}
          <article>
            <header><div><strong>{screen.name}</strong><span>{screen.viewport}{screen.theme ? ` · ${screen.theme}` : ""}</span></div><code>{dimension(screen.size.width)} × {dimension(screen.size.height)}</code></header>
            <div class="screen-metrics">
              <span>{screen.componentKeys.length} instances</span>
              <span>{screen.metrics.editableLayers ?? screen.metrics.layers ?? 0} layers</span>
              <span>mean {percent(screen.metrics.fidelityMean)}</span>
              <span>min {percent(screen.metrics.fidelityMin)}</span>
            </div>
            <p title={screen.hierarchy.map((item) => item.name).join(" → ")}>
              {screen.hierarchy.slice(0, 5).map((item) => item.name).join(" → ")}{screen.hierarchy.length > 5 ? " …" : ""}
            </p>
          </article>
        {:else}
          <div class="source-empty">Run Source again to assemble the screen registry.</div>
        {/each}
      </div>
    </section>

    <section class="source-section">
      <div class="source-section-head">
        <div><span>03</span><h3>Component Library</h3></div>
        <small>{detectedComponents} exact masters · quality status never hides a component</small>
      </div>
      <div class="component-sheet" data-source-component-catalog>
        {#each catalogGroups as [category, families] (category)}
          <section class="catalog-group">
            <header><h4>{category}</h4><span>{families.length} families</span></header>
            <div class="catalog-grid">
              {#each families as family (family.baseKey)}
                {@const entry = family.primary}
                {@const comp = entry.component}
                {@const variants = Object.entries(comp.variants || {}) as Array<[string, any]>}
                {@const allVerified = comp.status === "verified" && family.review.every((item) => item.component.status === "verified")}
                <article class:needs-review={!allVerified} data-catalog-component={entry.key}>
                  <header class="catalog-card-head">
                    <div><strong>{comp.name || entry.key}</strong><small>{comp.canonicalRole || family.baseKey}</small></div>
                    <span class:verified={allVerified}>
                      {allVerified ? "verified" : family.review.length ? `review ×${family.review.length}` : "needs review"}
                    </span>
                  </header>
                  <div class="catalog-variants">
                    {#each (variants.length ? variants : [["default", {}] as [string, any]]) as [variantKey, variant] (variantKey)}
                      <div class="catalog-variant">
                        <ComponentCatalogPreview component={comp} {variantKey} />
                        <div><span>{variant.label || variantKey}</span><small>×{variant.observedCount || comp.provenance?.occurrenceCount || 1}</small></div>
                      </div>
                    {/each}
                  </div>
                  {#if family.review.length}
                    <div class="catalog-review-strip">
                      <span>Экземпляры на ревью</span>
                      <div>
                        {#each family.review as instance (instance.pool + ":" + instance.key)}
                          <button type="button" title="Открыть экземпляр {instance.key}"
                                  onclick={() => onOpen?.(instance.key, instance.pool)}>
                            <ComponentCatalogPreview component={instance.component} variantKey="default" />
                          </button>
                        {/each}
                      </div>
                    </div>
                  {/if}
                  <footer>
                    <span>{comp.provenance?.occurrenceCount || 1} source instances{family.review.length ? ` · +${family.review.length} review` : ""}</span>
                    <button type="button" onclick={() => onOpen?.(entry.key, entry.pool)}>Inspect component</button>
                  </footer>
                </article>
              {/each}
            </div>
          </section>
        {:else}
          <div class="source-empty">Sync Source to build the exact component catalog from measured DOM boundaries.</div>
        {/each}
      </div>
    </section>
  </div>
{:else}
  <div class="source-empty large"><strong>No Source Artifact</strong><span>Connect or Sync a completed Source import to inspect screens and measured components.</span></div>
{/if}

<style>
  .source-workbench { display: grid; gap: 20px; padding: 22px; color: #dfe4ee; }
  .source-intro { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }
  .source-eyebrow { color: #58d1bc; font-size: 10px; font-weight: 750; letter-spacing: .12em; text-transform: uppercase; }
  .source-intro h2 { margin: 5px 0 4px; font-size: 20px; letter-spacing: -.02em; }
  .source-intro p { margin: 0; color: #8f97a8; font-size: 11px; }
  code { color: #65cbb9; font-family: "SFMono-Regular", Consolas, monospace; font-size: 9px; }
  .source-funnel { display: grid; grid-template-columns: 1fr 150px 1fr; min-height: 98px; overflow: hidden; border: 1px solid #2a303b; border-radius: 13px; background: #11151d; }
  .source-funnel > div:not(.source-transfer) { padding: 16px 18px; }
  .source-funnel span, .source-funnel small { display: block; }
  .source-funnel span { color: #969eae; font-size: 10px; font-weight: 700; }
  .source-funnel strong { display: block; margin: 4px 0 3px; font-size: 30px; line-height: 1; }
  .source-funnel small { color: #737b8b; font-size: 10px; }
  .source-observed { box-shadow: inset 3px 0 #32b6a0; }
  .source-observed strong { color: #58d1bc; }
  .source-accepted { box-shadow: inset -3px 0 #8b7cf6; text-align: right; }
  .source-accepted strong { color: #a99cff; }
  .source-transfer { position: relative; display: grid; grid-template-columns: 1fr auto 1fr; place-items: center; color: #798193; }
  .source-transfer i { position: absolute; width: 100%; height: 1px; background: linear-gradient(90deg, #32b6a0, #8b7cf6); opacity: .7; }
  .source-transfer b { z-index: 1; grid-column: 2; border: 1px solid #303746; border-radius: 999px; background: #161b24; padding: 4px 8px; font-size: 8px; letter-spacing: .08em; text-transform: uppercase; }
  .source-transfer em { z-index: 1; grid-column: 3; margin-left: auto; background: #11151d; font-style: normal; }
  .source-section { min-width: 0; }
  .source-section-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 9px; }
  .source-section-head > div { display: flex; align-items: baseline; gap: 8px; }
  .source-section-head span { color: #50596b; font-family: Consolas, monospace; font-size: 9px; }
  .source-section-head h3 { margin: 0; font-size: 12px; letter-spacing: .02em; }
  .source-section-head small { color: #747d8e; font-size: 9px; }
  .foundation-strip, .screen-metrics { display: flex; flex-wrap: wrap; gap: 6px; }
  .foundation-strip > span { border: 1px solid #2c3340; border-radius: 999px; background: #151a23; padding: 5px 8px; color: #aeb5c4; font-size: 9px; }
  .foundation-strip strong { margin-left: 6px; color: #58d1bc; }
  .screen-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
  .screen-grid article { min-width: 0; border: 1px solid #2a303b; border-radius: 10px; background: #121720; padding: 10px; }
  .screen-grid header { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
  .screen-grid header strong, .screen-grid header span { display: block; }
  .screen-grid header strong { font-size: 10px; }
  .screen-grid header span { margin-top: 2px; color: #737c8d; font-size: 8px; }
  .screen-metrics { margin-top: 8px; }
  .screen-metrics span { border-radius: 999px; background: #18242a; padding: 3px 5px; color: #82b8ae; font-size: 8px; }
  .screen-grid p { overflow: hidden; margin: 8px 0 0; color: #777f90; font-size: 8px; text-overflow: ellipsis; white-space: nowrap; }
  .component-sheet { display: grid; gap: 16px; }
  .catalog-group { min-width: 0; }
  .catalog-group > header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 7px; border-bottom: 1px solid #252b35; padding-bottom: 6px; }
  .catalog-group > header h4 { margin: 0; color: #bec5d2; font-size: 10px; text-transform: capitalize; }
  .catalog-group > header span { color: #687184; font-size: 8px; }
  .catalog-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 9px; }
  .catalog-grid article { min-width: 0; overflow: hidden; border: 1px solid #303744; border-radius: 12px; background: #121720; box-shadow: inset 0 2px #43bda8; }
  .catalog-grid article.needs-review { box-shadow: inset 0 2px #d79a53; }
  .catalog-card-head, .catalog-grid article > footer { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px; }
  .catalog-card-head > div, .catalog-card-head strong, .catalog-card-head small { display: block; min-width: 0; }
  .catalog-card-head strong { overflow: hidden; color: #eef1f7; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
  .catalog-card-head small { margin-top: 2px; color: #687184; font-size: 8px; }
  .catalog-card-head > span { flex: none; border-radius: 999px; background: #35291c; padding: 3px 6px; color: #d8a465; font-size: 7px; font-weight: 750; text-transform: uppercase; }
  .catalog-card-head > span.verified { background: #173129; color: #62d4ad; }
  .catalog-variants { display: grid; grid-template-columns: repeat(auto-fit, minmax(116px, 1fr)); gap: 7px; padding: 0 9px; }
  .catalog-variant { min-width: 0; }
  .catalog-variant > div:last-child { display: flex; align-items: center; justify-content: space-between; gap: 5px; padding: 5px 2px 2px; color: #9ba4b5; font-size: 8px; }
  .catalog-variant small { color: #687184; }
  .catalog-review-strip { margin-top: 8px; padding: 0 9px; }
  .catalog-review-strip > span { display: block; margin-bottom: 5px; color: #b9925e; font-size: 8px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; }
  .catalog-review-strip > div { display: grid; grid-template-columns: repeat(auto-fill, minmax(72px, 1fr)); gap: 5px; }
  .catalog-review-strip button { overflow: hidden; border: 1px dashed #4a4133; border-radius: 8px; background: #171512; padding: 3px; cursor: pointer; }
  .catalog-review-strip button:hover { border-color: #6d5f45; }
  .catalog-grid article > footer { border-top: 1px solid #272e39; margin-top: 7px; color: #6f788a; font-size: 8px; }
  .catalog-grid article > footer button { border: 1px solid #394252; border-radius: 7px; background: #1b222d; padding: 5px 7px; color: #cbd1dc; font-size: 8px; cursor: pointer; }
  .catalog-grid article > footer button:hover { border-color: #5e6a7f; background: #232b38; }
  .catalog-grid article > footer button:focus-visible { outline: 2px solid #8b7cf6; outline-offset: 2px; }
  .source-empty { border: 1px dashed #343b47; border-radius: 9px; padding: 12px; color: #7c8595; font-size: 10px; }
  .source-empty.large { display: grid; place-items: center; gap: 6px; min-height: 320px; margin: 22px; text-align: center; }
  .source-empty.large strong { color: #d5dae4; font-size: 13px; }
  @media (max-width: 980px) {
    .source-funnel { grid-template-columns: 1fr 90px 1fr; }
    .screen-grid { grid-template-columns: 1fr; }
    .catalog-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
  @media (max-width: 720px) { .catalog-grid { grid-template-columns: 1fr; } }
</style>
