<script lang="ts">
  import * as ctl from "./controller";
  import { editorUi } from "./state";

  const proposal = $derived($editorUi.harmonizerProposal);

  function colors(tokens: any): string[] {
    const source = tokens?.semantic?.color || tokens?.color || {};
    return [...new Set(Object.values(source).filter((value): value is string => typeof value === "string" && /^#[0-9a-f]{3,8}$/i.test(value)))].slice(0, 8);
  }

  const palette = $derived(proposal ? colors(proposal.tokens) : []);
  const displayFont = $derived(proposal?.tokens?.font?.display?.family || proposal?.tokens?.semantic?.font?.display || "from tokens");
  const bodyFont = $derived(proposal?.tokens?.font?.body?.family || proposal?.tokens?.semantic?.font?.body || "from tokens");
</script>

{#if proposal}
  <div
    class="fe-harmonize-backdrop"
    role="presentation"
    onmousedown={(event) => {
      if (event.target === event.currentTarget && proposal.status !== "loading") ctl.dismissHarmonizerProposal();
    }}
  >
    <div class="fe-harmonize-card" role="dialog" aria-modal="true" aria-labelledby="harmonize-title">
      <div class="fe-harmonize-kicker">AI Harmonizer · {proposal.sourceCount} sources</div>
      <h2 id="harmonize-title">{proposal.status === "loading" ? "Preparing shared tokens…" : "Make the page visually consistent"}</h2>
      {#if proposal.status === "loading"}
        <div class="fe-harmonize-loader"><i></i><span>Finding recurring colors, fonts, radii, shadows, and semantic roles</span></div>
      {/if}
      {#if proposal.status === "error"}
        <div class="fe-harmonize-error">Harmonizer unavailable: {proposal.error}</div>
      {/if}
      {#if proposal.status === "ready"}
        <p>Structure, text, and images will be preserved. Only style properties linked to the shared system will change.</p>
        <div class="fe-harmonize-preview">
          <div><small>Palette</small><span class="fe-harmonize-palette">{#each palette as color (color)}<i style="background: {color}" title={color}></i>{/each}</span></div>
          <div><small>Typography</small><b>{displayFont}</b><span>{bodyFont}</span></div>
          <div><small>Normalization</small><b>color · type · radius · shadow</b><span>through semantic bindings</span></div>
        </div>
        <div class="fe-harmonize-note">The preview has not changed IR. Standard Undo is available after Apply.</div>
      {/if}
      <div class="fe-harmonize-actions">
        <button class="fe-btn" data-act="dismiss-harmonizer" onclick={() => ctl.dismissHarmonizerProposal()}>Cancel</button>
        {#if proposal.status === "ready"}
          <button class="fe-btn primary" data-act="apply-harmonizer" onclick={() => ctl.applyHarmonizerProposal(proposal)}>Apply shared style</button>
        {/if}
      </div>
    </div>
  </div>
{/if}
