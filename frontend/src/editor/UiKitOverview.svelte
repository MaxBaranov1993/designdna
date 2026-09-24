<script lang="ts">
  import ComponentCatalogPreview from './ComponentCatalogPreview.svelte';
  import { capturedFontUrl, kitColors, kitConcept, kitFonts, type KitEntry, type KitSection } from './ui-kit-model';
  let { document: doc, entries, section, onSection, onComponents, onOpen, onAnalyze, busy = false }:
    { document: Record<string, any>; entries: KitEntry[]; section: KitSection;
      onSection: (section: KitSection) => void; onComponents: () => void;
      onOpen: (key: string, pool: KitEntry['pool']) => void; onAnalyze: () => void; busy?: boolean } = $props();
  const colors = $derived(kitColors(doc));
  const fonts = $derived(kitFonts(doc, entries));
  const concept = $derived(kitConcept(doc));
  const brief = $derived(doc.siteBrief || {});
  const foundations = $derived(doc.foundations || {});
  const previewEntries = $derived(entries.filter(e => !!e.component.masterIr).slice(0, 6));
  const verified = $derived(entries.filter(e => e.pool === 'components' && e.component.status === 'verified').length);
  const sourceUrl = $derived(String(doc.sourceRefs?.[0]?.url || ''));
  let sample = $state('The quick brown fox · Design begins with details');
  let fontState = $state<Record<string, { alias: string; loaded: boolean; missing: number }>>({});
  let notice = $state('');

  // Unique aliases prevent a site's @font-face from changing the application UI.
  $effect(() => {
    const current = fonts;
    let alive = true;
    const registered: FontFace[] = [];
    fontState = {};
    void Promise.all(current.map(async (font, index) => {
      const alias = `kit-${crypto.randomUUID()}-${index}`;
      let loaded = 0, missing = 0;
      await Promise.all(font.faces.map(async face => {
        const url = capturedFontUrl(face.url, !!window.designDNA);
        if (!url) { missing++; return; }
        try {
          const candidate = new FontFace(alias, `url(${JSON.stringify(url)})`, {
            weight: String(face.weight || '400'), style: String(face.style || 'normal'),
            ...(face.unicodeRange ? { unicodeRange: face.unicodeRange } : {}),
          });
          await candidate.load();
          if (alive) { window.document.fonts.add(candidate); registered.push(candidate); loaded++; }
        } catch { missing++; }
      }));
      if (alive) fontState = { ...fontState, [font.family]: { alias, loaded: loaded > 0, missing } };
    }));
    return () => { alive = false; registered.forEach(face => window.document.fonts.delete(face)); };
  });
  async function copy(value: string) {
    try { await navigator.clipboard.writeText(value); notice = `Copied: ${value}`; }
    catch { notice = `Could not copy. Value: ${value}`; }
  }
  const fontStyle = (family: string) => fontState[family]?.loaded ? `"${fontState[family].alias}", sans-serif` : 'sans-serif';
</script>

<div class="kit-workspace" data-kit-section={section}>
  {#if section === 'overview'}
    <header class="kit-intro">
      <div><p class="eyebrow">YOUR SITE LIBRARY</p><h1>Site components and style</h1>
        <p>Components for building pages, colors and fonts for new ideas.</p>
        {#if sourceUrl}<span class="source-address">{sourceUrl}</span>{/if}
      </div>
      <div class="kit-readiness"><strong>{entries.length} components in the library</strong>
        <span>{verified} verified · {entries.length - verified} need review</span>
        <small>Components are available for manual editing. Validation determines readiness for strict generation.</small>
      </div>
    </header>
    <div class="identity-board">
      <section class="concept-summary"><p class="eyebrow">CONCEPT AND CHARACTER</p>
        <h2>{brief.summary || concept.summary || 'Meet the site style'}</h2>
        <p>{concept.hasAnalysis ? 'AI has enriched the style description. Source components are preserved separately.' : 'A brief interpretation of measurements. AI can add rules and a concept description.'}</p>
        <button class="text-button" onclick={() => onSection('concept')}>About the site concept <span>↗</span></button>
      </section>
      <section class="type-poster"><p class="eyebrow">TYPOGRAPHY</p>
        <div class="type-specimen" style:font-family={fontStyle(fonts.find(f => f.role === 'Headings')?.family || fonts[0]?.family || '')}>Aa Bb</div>
        <p>{fonts.map(f => f.family).join(' · ') || 'No font information found'}</p>
        <button class="text-button" onclick={() => onSection('fonts')}>View fonts <span>↗</span></button>
      </section>
    </div>
    <section class="palette-section"><div class="section-head"><div><h2>Site palette</h2><p>Color roles and their values, side by side.</p></div><button class="text-button" onclick={() => onSection('colors')}>All colors and tokens →</button></div>
      <div class="palette-ribbon">{#each colors.slice(0, 8) as color}<button title={`Copy ${color.value}`} onclick={() => copy(color.value)}><i style:background={color.value}></i><span>{color.label}</span><code>{color.value}</code></button>{:else}<p class="empty">Colors will appear after building from Source.</p>{/each}</div>
    </section>
    <section><div class="section-head"><div><h2>Source components</h2><p>Open a component to explore variants and compare with the original.</p></div><button class="text-button" onclick={onComponents}>All components →</button></div>
      <div class="preview-grid">{#each previewEntries as entry}<button class="component-tile" onclick={() => onOpen(entry.key, entry.pool)}><ComponentCatalogPreview component={entry.component} /><span>{doc.catalog?.componentMeta?.[entry.key]?.label || entry.component.name || entry.key}</span><small>{entry.pool === 'components' ? 'In the library' : 'Needs review'} · {Object.keys(entry.component.variants || {}).length || 1} variant(s)</small></button>{:else}<p class="empty">No extracted components in this document yet. Build a UI Kit from Source.</p>{/each}</div>
    </section>
  {:else if section === 'colors'}
    <header class="page-heading"><p class="eyebrow">DESIGN SYSTEM FOUNDATIONS</p><h1>Colors and tokens</h1><p>Tokens are reusable saved style values. Role names are detected automatically.</p></header>
    <section><h2>Color roles</h2><div class="color-grid">{#each colors as color}<button class="color-tile" onclick={() => copy(color.value)} title="Copy value"><i style:background={color.value}></i><span>{color.label}</span><code>{color.value}</code><small>{color.key}</small></button>{:else}<p class="empty">No color roles found in the document.</p>{/each}</div></section>
    {#if Object.keys(foundations.colors?.primitives || {}).length}<details class="token-details"><summary>All measured shades</summary><div class="primitive-list">{#each Object.entries(foundations.colors.primitives) as [name, value]}<button onclick={() => copy(String(value))}><i style:background={String(value)}></i><code>{String(value)}</code><small>{name}</small></button>{/each}</div></details>{/if}
    <div class="token-columns">
      <section><h2>Spacing</h2><p>Spacing between elements in pixels.</p><div class="spacing-list">{#each Object.entries(foundations.spacing || {}) as [name, value]}<div><code>{name}</code><i style:width={`${Math.min(180, Math.max(0, Number(value) || 0))}px`}></i><span>{String(value)} px</span></div>{:else}<p class="empty">No measurements available.</p>{/each}</div></section>
      <section><h2>Corner radii</h2><p>Corner shapes for cards and elements.</p><div class="radius-list">{#each foundations.radii || [] as radius}<div><i style:border-radius={`${Number(radius) || 0}px`}></i><span>{radius} px</span></div>{:else}<p class="empty">No measurements available.</p>{/each}</div>
        <h2 class="subheading">Screen sizes</h2><div class="breakpoints">{#each Object.entries(foundations.breakpoints || {}) as [name, size]}<span>{name}<strong>{String(size)} px</strong></span>{/each}</div>
        {#if foundations.shadows?.length}<h2 class="subheading">Shadows</h2><div class="shadow-list">{#each foundations.shadows as shadow}<button onclick={() => copy(String(shadow))}><i style:box-shadow={String(shadow)}></i><code>{shadow}</code></button>{/each}</div>{/if}
      </section>
    </div>
  {:else if section === 'fonts'}
    <header class="page-heading"><p class="eyebrow">SITE TYPOGRAPHY</p><h1>Live font samples</h1><p>The sample uses the captured font when its file is available. Try your own text below.</p></header>
    <label class="sample-input">Sample text<input bind:value={sample} maxlength="240" placeholder="Enter text" /></label>
    <div class="font-list">{#each fonts as font}<section class="font-card" data-kit-font={font.family}><header><div><span class="eyebrow">{font.role}</span><h2>{font.family}</h2></div><span class="font-status">{!fontState[font.family] ? 'Loading sample…' : fontState[font.family].loaded ? fontState[font.family].missing ? 'Some font weights are unavailable' : 'Source file loaded' : 'File unavailable · showing a system font'}</span></header>
      <p class="font-sample" style:font-family={fontStyle(font.family)}>{sample || 'Aa Bb 0123456789'}</p>
      <footer><span>Weights: {[...new Set(font.faces.map(f => String(f.weight || '400')))].join(' · ') || 'not detected'}</span><button class="text-button" onclick={() => copy(font.family)}>Copy name</button></footer></section>{:else}<p class="empty">This source has no font information. A screenshot alone cannot identify the exact font name.</p>{/each}</div>
    {#if Object.keys(foundations.typography?.scale || {}).length}<details class="token-details"><summary>Measured text sizes</summary><div class="breakpoints">{#each Object.entries(foundations.typography.scale) as [name, size]}<span>{name}<strong>{String(size)} px</strong></span>{/each}</div></details>{/if}
  {:else}
    <header class="page-heading"><p class="eyebrow">SITE CONCEPT</p><h1>What makes this style recognizable</h1><p>The description helps create new pages with the same character. AI interpretation does not replace measurements or source components.</p></header>
    {#if brief.summary || brief.audience || brief.offer}
      <section class="site-brief"><p class="eyebrow">ABOUT THE SITE · {brief.origin === 'ai' ? 'AI ANALYSIS' : 'DESCRIPTION'}</p>
        {#if brief.summary}<h2>{brief.summary}</h2>{/if}
        <div class="trait-grid">{#if brief.audience}<div><h3>Audience</h3><p>{brief.audience}</p></div>{/if}{#if brief.offer}<div><h3>Offering</h3><p>{brief.offer}</p></div>{/if}</div>
      </section>
    {:else if brief.headings?.length}
      <section class="site-brief"><p class="eyebrow">HEADINGS FROM THE SOURCE SITE</p><ul>{#each brief.headings.slice(0, 4) as heading}<li>{heading}</li>{/each}</ul><p>These are the original texts. AI analysis will add a description of the site purpose and audience.</p></section>
    {/if}
    <section class="concept-lead"><span class="eyebrow">BRIEF DESCRIPTION · INTERPRETATION</span><h2>{concept.summary || 'Description not prepared yet'}</h2><p>{concept.hasAnalysis ? 'Analysis from the selected model and usage recommendations appear below.' : 'The basic UI Kit is already available. Run AI analysis to get a concept description and styling rules.'}</p><button class="analyze-button" onclick={onAnalyze} disabled={busy}>{busy ? 'Running…' : concept.hasAnalysis ? 'Refresh AI analysis' : 'Describe style with AI'}</button></section>
    {#if concept.traits.length}<div class="trait-grid">{#each concept.traits as trait}<section><h2>{trait.label}</h2><p>{trait.text}</p></section>{/each}</div>{/if}
    {#if concept.doRules.length || concept.dontRules.length}<div class="token-columns"><section><h2>Preserve in new pages</h2><ul>{#each concept.doRules as rule}<li>{rule}</li>{/each}</ul></section><section><h2>Avoid</h2><ul>{#each concept.dontRules as rule}<li>{rule}</li>{/each}</ul></section></div>{/if}
  {/if}
  <p class="copy-notice" role="status">{notice}</p>
</div>

<style>
  .kit-workspace { --kit-line: var(--dna-border, #34343c); --kit-muted: var(--dna-muted, #a7a7b5); --kit-panel: var(--dna-panel, #232328); max-width: 1280px; margin: auto; padding: 32px 36px 48px; color: var(--dna-text, #ededf3); font-size: 14px; line-height: 1.55; }
  h1, h2, p { margin: 0; } h1 { font-size: clamp(26px, 3vw, 36px); line-height: 1.2; letter-spacing: -.03em; font-weight: 650; } h2 { font-size: 18px; line-height: 1.4; font-weight: 600; } p { color: var(--kit-muted); } button { font: inherit; cursor: pointer; } button:disabled { opacity: .55; cursor: wait; } button:focus-visible, input:focus-visible, summary:focus-visible { outline: 2px solid var(--dna-violet, #9b84ff); outline-offset: 4px; }
  .eyebrow { color: var(--kit-muted); font-size: 10px; letter-spacing: .1em; font-weight: 600; } .kit-intro { display: flex; justify-content: space-between; align-items: center; gap: 32px; margin-bottom: 28px; } .kit-intro h1, .page-heading h1 { margin: 8px 0 10px; } .source-address { display: block; margin-top: 8px; font-size: 12px; color: var(--kit-muted); overflow-wrap: anywhere; }
  .kit-readiness { max-width: 310px; padding-left: 20px; border-left: 2px solid var(--dna-artifact, #41baaa); display: grid; gap: 5px; flex-shrink: 0; } .kit-readiness span { font-size: 12px; } .kit-readiness small { font-size: 11px; color: var(--kit-muted); }
  .identity-board { display: grid; grid-template-columns: 1.3fr 1fr; border: 1px solid var(--kit-line); border-radius: 14px; overflow: hidden; background: var(--kit-panel); } .identity-board section { padding: 24px; } .concept-summary h2 { margin: 14px 0; font-size: 21px; line-height: 1.35; letter-spacing: -.015em; } .concept-summary p:not(.eyebrow) { font-size: 12px; } .concept-summary button { margin-top: 18px; }
  .type-poster { border-left: 1px solid var(--kit-line); background: #f0eff5; color: #242132; } .type-poster p { color: #666073; font-size: 12px; } .type-specimen { font-size: 72px; line-height: 1.3; letter-spacing: -.035em; padding-block: 8px; } .type-poster button { color: #433069; margin-top: 18px; }
  .text-button { display: inline-flex; align-items: center; justify-content: space-between; gap: 16px; padding: 0; border: 0; background: none; color: var(--dna-text, #ededf3); font-size: 12px; font-weight: 600; } .text-button:hover { text-decoration: underline; }
  .section-head { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin: 30px 0 16px; } .section-head p { margin-top: 4px; font-size: 12px; }
  .palette-ribbon { display: grid; grid-template-columns: repeat(8, minmax(0, 1fr)); gap: 10px; } .palette-ribbon button { display: grid; gap: 5px; text-align: left; min-width: 0; background: none; border: 0; padding: 0; color: inherit; } .palette-ribbon i { height: 56px; border-radius: 7px; border: 1px solid #8884; } .palette-ribbon span { font-size: 11px; } code { font: 11px ui-monospace, Consolas, monospace; overflow-wrap: anywhere; } .palette-ribbon code { color: var(--kit-muted); }
  .preview-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; } .component-tile { min-width: 0; border: 1px solid var(--kit-line); background: var(--kit-panel); color: inherit; border-radius: 10px; padding: 10px; text-align: left; } .component-tile:hover { border-color: var(--dna-violet, #9b84ff); } .component-tile > span { display: block; font-size: 13px; font-weight: 600; margin: 12px 4px 3px; } .component-tile > small { display: block; color: var(--kit-muted); margin-inline: 4px; font-size: 11px; }
  .page-heading { max-width: 790px; margin-bottom: 30px; } .color-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin-top: 18px; } .color-tile { background: var(--kit-panel); border: 1px solid var(--kit-line); border-radius: 12px; padding: 12px; color: inherit; display: grid; text-align: left; gap: 5px; } .color-tile i { height: 90px; border: 1px solid #8884; border-radius: 6px; margin-bottom: 8px; } .color-tile small { color: var(--kit-muted); }
  .site-brief { padding: 24px; border: 1px solid var(--kit-line); border-radius: 12px; background: var(--kit-panel); margin-bottom: 28px; } .site-brief h2 { margin-top: 12px; } .site-brief h3 { font-size: 14px; margin: 0 0 6px; } .site-brief .trait-grid { margin-top: 20px; }
  .token-details { margin-top: 26px; border-top: 1px solid var(--kit-line); padding-top: 16px; } summary { cursor: pointer; } .primitive-list { display: flex; flex-wrap: wrap; gap: 10px; padding-top: 18px; } .primitive-list button { color: inherit; background: var(--kit-panel); border: 1px solid var(--kit-line); border-radius: 7px; padding: 8px; display: flex; align-items: center; gap: 8px; } .primitive-list i { width: 22px; height: 22px; border-radius: 4px; } .primitive-list small { font-size: 10px; color: var(--kit-muted); }
  .token-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 36px; margin-top: 32px; } .token-columns section > p { margin: 5px 0 20px; font-size: 12px; } .spacing-list { display: grid; gap: 7px; } .spacing-list > div { display: grid; grid-template-columns: 70px 1fr 60px; align-items: center; gap: 10px; font-size: 11px; } .spacing-list i { height: 8px; background: var(--dna-artifact, #41baaa); max-width: 100%; } .spacing-list code { color: var(--kit-muted); }
  .radius-list, .breakpoints { display: flex; flex-wrap: wrap; gap: 18px; } .radius-list > div { display: grid; gap: 7px; text-align: center; font-size: 11px; } .radius-list i { display: block; width: 48px; height: 48px; border: 2px solid var(--kit-muted); } .subheading { margin-top: 28px; margin-bottom: 16px; } .breakpoints { margin-top: 18px; } .breakpoints span { min-width: 80px; color: var(--kit-muted); font-size: 11px; } .breakpoints strong { display: block; color: var(--dna-text, #ededf3); font-size: 14px; } .shadow-list { display: grid; gap: 14px; } .shadow-list button { background: var(--kit-panel); border: 1px solid var(--kit-line); color: inherit; border-radius: 8px; padding: 18px; text-align: left; display: flex; gap: 18px; align-items: center; } .shadow-list i { width: 42px; height: 34px; flex-shrink: 0; border-radius: 6px; background: #b9b7c6; }
  .sample-input { display: grid; gap: 8px; font-size: 12px; margin-bottom: 24px; } input { width: 100%; box-sizing: border-box; padding: 12px 14px; border: 1px solid var(--kit-line); border-radius: 8px; color: inherit; background: var(--kit-panel); font: inherit; }
  .font-list { display: grid; gap: 22px; } .font-card { padding: 24px; border: 1px solid var(--kit-line); border-radius: 14px; background: var(--kit-panel); } .font-card header, .font-card footer { display: flex; align-items: center; justify-content: space-between; gap: 20px; } .font-card h2 { margin-top: 6px; } .font-status, .font-card footer { font-size: 11px; color: var(--kit-muted); } .font-sample { color: var(--dna-text, #ededf3); font-size: clamp(25px, 3vw, 42px); line-height: 1.45; padding: 30px 0; overflow-wrap: anywhere; } .font-card footer { border-top: 1px solid var(--kit-line); padding-top: 16px; }
  .concept-lead { border-left: 3px solid var(--dna-violet, #9b84ff); padding: 8px 24px; max-width: 850px; } .concept-lead h2 { font-size: 24px; margin: 12px 0; } .analyze-button { margin-top: 18px; border: 1px solid var(--dna-violet, #9b84ff); background: var(--dna-violet, #7656d4); color: white; border-radius: 7px; padding: 9px 16px; font-size: 13px; } .trait-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-top: 32px; } .trait-grid section { padding: 22px; background: var(--kit-panel); border: 1px solid var(--kit-line); border-radius: 10px; } .trait-grid p { margin-top: 10px; } ul { padding-left: 20px; color: var(--kit-muted); } li { padding-bottom: 8px; }
  .copy-notice { position: sticky; bottom: 8px; width: fit-content; max-width: 100%; margin-top: 14px; background: var(--kit-panel); border-radius: 5px; font-size: 12px; overflow-wrap: anywhere; } .copy-notice:not(:empty) { padding: 8px 12px; border: 1px solid var(--kit-line); } .empty { padding: 20px 0; font-size: 13px; }
  @media (max-width: 900px) { .kit-workspace { padding: 24px 20px; } .kit-intro { align-items: flex-start; } .kit-readiness { max-width: 240px; } .palette-ribbon { grid-template-columns: repeat(4, 1fr); } .preview-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .type-specimen { font-size: 68px; } }
  @media (max-width: 600px) { .kit-intro { flex-direction: column; } .kit-readiness { max-width: none; } .identity-board, .token-columns, .trait-grid { grid-template-columns: 1fr; } .type-poster { border-left: 0; border-top: 1px solid var(--kit-line); } .color-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .section-head { align-items: flex-start; flex-direction: column; gap: 8px; } .font-card header, .font-card footer { align-items: flex-start; flex-direction: column; gap: 8px; } .preview-grid { grid-template-columns: 1fr; } }
</style>
