<script lang="ts">
  import * as ctl from "./controller";
  import { diagramSection } from "./diagram";
  import { toast } from "../flow/toast";
  let { disabled = false }: {disabled?: boolean} = $props();
  let open = $state(false), title = $state("Process diagram"), steps = $state("Input data\nProcessing\nResult"), error = $state("");
  let panelTop = $state(50), panelLeft = $state(12);
  function toggle(event: MouseEvent) {
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    panelTop = rect.bottom + 8;
    panelLeft = Math.max(12, Math.min(rect.right - 330, window.innerWidth - 342));
    open = !open; error = "";
  }
  function insert() {
    const ir = ctl.currentIrSnapshot();
    if (!ir || disabled) return;
    try {
      const section = diagramSection(ir, title, steps.split("\n"));
      if (ctl.insertDiagramSection(section)) { open = false; error = ""; toast("Diagram added. Edit labels, steps, and arrows in the editor", "ok"); }
    } catch (e) { error = e instanceof Error ? e.message : String(e); }
  }
</script>

<div class="diagram-insert">
  <button class="fe-btn" data-act="insert-diagram" {disabled} aria-haspopup="dialog" aria-expanded={open} onclick={toggle}>+ Diagram</button>
  {#if open}
    <div class="diagram-panel" style:top={panelTop + "px"} style:left={panelLeft + "px"} role="dialog" aria-label="Add process diagram">
      <label>Title<input maxlength="160" bind:value={title} /></label>
      <label>Steps, one per line<textarea rows="6" bind:value={steps}></textarea></label>
      <p>2 to 6 steps. Labels and arrows are separate elements; move connectors manually.</p>
      {#if error}<p role="alert">{error}</p>{/if}
      <div><button class="fe-btn" onclick={() => open = false}>Cancel</button> <button class="fe-btn primary" data-act="apply-diagram" onclick={insert}>Add</button></div>
    </div>
  {/if}
</div>

<style>
  .diagram-insert { position: relative; }
  .diagram-panel { position: fixed; z-index: 45; width: min(330px, calc(100vw - 24px)); max-height: 75vh; overflow: auto; background: hsl(var(--secondary)); color: hsl(var(--foreground)); border: 1px solid hsl(var(--border)); border-radius: 10px; padding: 14px; box-shadow: 0 8px 32px #0005; font-size: 12px; }
  label { display: grid; gap: 5px; margin-bottom: 10px; }
  input,textarea { width: 100%; box-sizing: border-box; border: 1px solid hsl(var(--border)); border-radius: 6px; padding: 7px; font: inherit; background: hsl(var(--background)); color: hsl(var(--foreground)); }
  p { color: hsl(var(--muted-foreground)); line-height: 1.5; }
</style>
