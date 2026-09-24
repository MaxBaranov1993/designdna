<script lang="ts">
  import * as ctl from "./controller";
  import { editorUi } from "./state";

  const proposal = $derived($editorUi.qualityProposal);
  const fixCount = $derived(proposal ? proposal.journal.length : 0);

  function issueText(issue: { rule?: string; path?: string; message?: string }) {
    return issue.message || issue.rule || issue.path || "Design constraint violation";
  }
</script>

{#if proposal}
  <div
    class="fe-quality-backdrop"
    role="presentation"
    onmousedown={(event) => {
      if (event.target === event.currentTarget && proposal.status !== "loading") ctl.dismissQualityProposal();
    }}
  >
    <div class="fe-quality-card" role="dialog" aria-modal="true" aria-labelledby="quality-title">
      <div class="fe-quality-kicker">AI Quality Copilot · pre-export checks</div>
      <h2 id="quality-title">{proposal.status === "loading" ? "Checking layout…" : proposal.passed ? "No critical issues" : `Issues found: ${proposal.violations.length}`}</h2>
      {#if proposal.status === "loading"}
        <div class="fe-quality-loader"><i></i><span>Grid, overflow, constraints, and structure</span></div>
      {/if}
      {#if proposal.status === "error"}
        <div class="fe-quality-error">Could not complete verification: {proposal.error}</div>
      {/if}
      {#if proposal.status === "ready"}
        <div class="fe-quality-score"><b>{Math.max(0, 100 - proposal.violations.length * 8)}</b><span>technical quality<br/><small>{fixCount} fixes prepared</small></span></div>
        <div class="fe-quality-issues">
          {#each proposal.violations.slice(0, 7) as issue, index (`${issue.rule || "issue"}-${index}`)}
            <div><b>{issue.severity || "check"}</b><span>{issueText(issue)}<small>{issue.path || issue.rule || "document"}</small></span></div>
          {/each}
          {#if !proposal.violations.length}
            <div class="fe-quality-pass">✓ Layout passes deterministic rules</div>
          {/if}
        </div>
        <p>AI previews the result before changing it. Automatic fixes preserve content and support Undo.</p>
      {/if}
      <div class="fe-quality-actions">
        <button class="fe-btn" data-act="dismiss-quality-gate" onclick={() => ctl.dismissQualityProposal()}>Close</button>
        {#if proposal.status === "ready" && fixCount > 0}
          <button class="fe-btn primary" data-act="apply-quality-fixes" onclick={() => ctl.applyQualityProposal(proposal)}>Fix {fixCount}</button>
        {/if}
      </div>
    </div>
  </div>
{/if}
