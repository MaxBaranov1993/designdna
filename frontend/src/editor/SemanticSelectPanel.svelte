<script lang="ts">
  import * as ctl from "./controller";
  import { editorUi } from "./state";

  const EXAMPLES = ["all buttons", "headings", "all cards", "images", "elements from source B"];

  const open = $derived($editorUi.semanticSelectOpen);
  let query = $state("");
  let count: number | null = $state(null);

  function run() {
    count = ctl.semanticSelect(query);
  }
</script>

{#if open}
  <div
    class="fe-semantic-backdrop"
    role="presentation"
    onmousedown={(event) => {
      if (event.target === event.currentTarget) ctl.closeSemanticSelect();
    }}
  >
    <div class="fe-semantic-card" role="dialog" aria-modal="true" aria-labelledby="semantic-title">
      <div class="fe-semantic-kicker">Semantic Selection · AI understands meaning and source</div>
      <h2 id="semantic-title">What should be selected?</h2>
      <div class="fe-semantic-input">
        <input
          value={query}
          oninput={(event) => { query = event.currentTarget.value; count = null; }}
          onkeydown={(event) => { if (event.key === "Enter") run(); }}
          placeholder="For example: all CTAs from Header"
          aria-label="Smart selection request"
        />
        <button class="fe-btn primary" data-act="run-semantic-select" disabled={!query.trim()} onclick={run}>Select</button>
      </div>
      <div class="fe-semantic-examples">
        {#each EXAMPLES as example (example)}
          <button onclick={() => { query = example; count = null; }}>{example}</button>
        {/each}
      </div>
      {#if count !== null}
        <div class={"fe-semantic-result " + (count ? "found" : "empty")}>{count ? `Elements selected: ${count}` : "No matches. Refine the type or source name"}</div>
      {/if}
      <p>The request combines element meaning and provenance. For example, buttons from Imported header will not select CTAs from other sources.</p>
      <div class="fe-semantic-actions"><button class="fe-btn" data-act="dismiss-semantic-select" onclick={() => ctl.closeSemanticSelect()}>Done</button></div>
    </div>
  </div>
{/if}
