<script lang="ts">
  import ProviderPicker from "../components/ProviderPicker.svelte";
  import { flow, flowBusy } from "../flow/state";
  import { useFlowStore } from "../flow/store";
  import type { SourceImportNodeData, SourceViewport } from "../flow/types";

  let { id, data }: { id: number; data: SourceImportNodeData } = $props();
  const VIEWPORTS: SourceViewport[] = ["desktop", "tablet", "mobile"];
  const PREVIEW_MODES = ["reference", "ir", "compare"] as const;
  let busy = $derived(!!$flowBusy[id]);
  let captured = $derived(new Set(Object.keys(((data.blocks?.find((block) => block.ir)?.ir as { responsive?: { viewports?: Record<string, unknown> } } | undefined)?.responsive?.viewports) || { desktop: {} })));
  const captureViewport = (viewport: SourceViewport) => {
    if (viewport === "desktop") return;
    const current = (data.captureViewports || (data.importProfile === "precise" ? ["tablet", "mobile"] : [])) as ("tablet" | "mobile")[];
    $flow.setNodeData(id, { captureViewports: [...new Set([...current, viewport])], importedUrl: null, activeViewport: viewport });
    void $flow.runNode(id);
  };
  let desktopAuth = $derived(typeof window !== "undefined" ? window.designDNA?.sourceAuth : undefined);

  const openAuthenticatedSession = async () => {
    const rawUrl = (data.url || "").trim();
    if (!rawUrl || !desktopAuth) return;
    const url = /^[a-z][a-z\d+.-]*:\/\//i.test(rawUrl) ? rawUrl : `https://${rawUrl}`;
    await desktopAuth.open(url);
  };
  const setViewport = (viewport: SourceViewport) => {
    $flow.setNodeData(id, { activeViewport: viewport });
    queueMicrotask(() => $flow.propagate(id));
  };
</script>

<div class="dna-insp-fields">
  <div class="dna-field">
    <div class="dna-field-cap">Source</div>
    <div class="dna-insp-seg">
      <button class:active={data.mode === "url"} onclick={() => $flow.setNodeData(id, { mode: "url" })}>URL</button>
      <button class:active={data.mode === "screenshot"} onclick={() => $flow.setNodeData(id, { mode: "screenshot" })}>Screenshot</button>
    </div>
  </div>
  {#if data.mode === "url"}
    <label class="dna-insp-check" title="Only import pages you own or have permission to use">
      <input type="checkbox" checked={data.mine} onchange={(e) => $flow.setNodeData(id, { mine: e.currentTarget.checked })} />
      <span>I own this site / have permission</span>
    </label>
    {#if desktopAuth}
      <label class="dna-insp-check" title="Cookies stay in isolated desktop app memory">
        <input type="checkbox" checked={data.authenticatedSession} onchange={(e) => $flow.setNodeData(id, { authenticatedSession: e.currentTarget.checked })} />
        <span>Authenticated session</span>
      </label>
      {#if data.authenticatedSession}
        <button class="dna-btn-ghost" onclick={openAuthenticatedSession}>Open browser sign-in</button>
      {/if}
    {/if}
  {/if}
  {#if desktopAuth}
    <div class="dna-field">
      <div class="dna-field-cap">AI refinement · account</div>
      <ProviderPicker
        provider={data.aiProvider || "openai"}
        effort={data.aiEffort || "high"}
        onChange={(next) => $flow.setNodeData(id, { aiProvider: next.provider, aiEffort: next.effort as "medium" | "high" | "max" })}
      />
    </div>
  {/if}
  <div class="dna-field">
    <div class="dna-field-cap">Preview viewport</div>
    <div class="dna-insp-seg">
      {#each VIEWPORTS as viewport (viewport)}
        {#if captured.has(viewport) || !data.blocks?.length}
          <button class:active={data.activeViewport === viewport} onclick={() => setViewport(viewport)}>{viewport === "desktop" ? "Desktop" : viewport === "tablet" ? "Tablet" : "Mobile"}</button>
        {:else}
          <button class="capture-viewport" disabled={busy} title={`Not captured yet · capture the ${viewport} layout now`}
            onclick={() => captureViewport(viewport)}>+ {viewport === "tablet" ? "Tablet" : "Mobile"}</button>
        {/if}
      {/each}
    </div>
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Block preview mode</div>
    <div class="dna-insp-seg">
      {#each PREVIEW_MODES as mode (mode)}
        <button class:active={(data.previewMode || "reference") === mode} onclick={() => $flow.setNodeData(id, { previewMode: mode })}>{mode === "reference" ? "Reference" : mode === "ir" ? "IR" : "Compare"}</button>
      {/each}
    </div>
  </div>
  {#if data.importedUrl && data.blocks.length}
    <div class="dna-insp-row">
      <button class="dna-btn-ghost" disabled={busy} title="Reload page" onclick={() => { $flow.setNodeData(id, { importedUrl: null }); queueMicrotask(() => $flow.runNode(id)); }}>Refresh import</button>
      <button class="dna-btn-ghost" disabled={busy} title="Build UI Kit and design system from this Source" onclick={() => void useFlowStore.getState().createDesignSystemFromSource(id)}>◈ UI Kit &amp; DS</button>
    </div>
  {/if}
  {#if data.lastRun}
    <div class="dna-field">
      <div class="dna-field-cap">Last import</div>
      <div class="dna-field-value"><span>{data.lastRun.cached ? "from cache" : "measured"}</span><span class="dna-out-kind">{(data.lastRun.totalMs / 1000).toFixed(1)}s</span></div>
    </div>
  {/if}
</div>
