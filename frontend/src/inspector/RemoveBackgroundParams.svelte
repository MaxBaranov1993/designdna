<script lang="ts">
  import { captureNodeUpload } from "../flow/store";
  import { flow, flowBusy } from "../flow/state";
  import { commitNodeText, flushNodeText } from "../flow/textcommit";
  import { toast } from "../flow/toast";
  import type { RemoveBackgroundNodeData } from "../flow/types";
  let { id, data }: { id: number; data: RemoveBackgroundNodeData } = $props();
  let busy = $derived(!!$flowBusy[id]);
  function upload(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    if (file.size > 20 * 1024 * 1024) { toast("Choose an image up to 20 MB", "error"); return; }
    const applyUpload = captureNodeUpload(id);
    const reader = new FileReader();
    reader.onload = () => applyUpload({ image: String(reader.result), fileName: file.name });
    reader.readAsDataURL(file);
    input.value = "";
  }
</script>

<div class="dna-insp-fields">
  <label class="dna-field">
    <span class="dna-field-cap">Removal method</span>
    <select disabled={busy} value={data.method || 'ai'} onchange={(e) => $flow.setNodeData(id, { method: e.currentTarget.value })}>
      <option value="ai">Codex · any background</option>
      <option value="chroma">Local · solid background</option>
    </select>
  </label>
  <div class="dna-field">
    <div class="dna-field-cap">Source image</div>
    <label class="dna-btn-ghost" style="cursor:pointer">
      {data.image ? "Replace image" : "Upload image"}
      <input type="file" accept="image/png,image/jpeg,image/webp" hidden disabled={busy} onchange={upload} />
    </label>
    {#if data.fileName}<div class="dna-field-hint">{data.fileName}</div>{/if}
    <div class="dna-field-hint">A connected image takes priority over the uploaded file.</div>
    {#if data.image}<button class="dna-btn-ghost" disabled={busy} onclick={() => $flow.setNodeData(id, { image: null, fileName: "" })}>Remove file</button>{/if}
  </div>
  {#if data.method === 'chroma'}
    <label class="dna-field"><span class="dna-field-cap">Background color</span>
      <input aria-label="Background color" type="color" disabled={busy} value={data.keyColor || '#00ff00'} onchange={(e) => $flow.setNodeData(id, { keyColor: e.currentTarget.value })} />
    </label>
    <label class="dna-field"><span class="dna-field-cap">Tolerance · {data.tolerance ?? 32}</span>
      <input aria-label="Tolerance" type="range" min="0" max="160" disabled={busy} value={data.tolerance ?? 32} onchange={(e) => $flow.setNodeData(id, { tolerance: +e.currentTarget.value })} />
    </label>
    <label class="dna-field"><span class="dna-field-cap">Edge softness · {data.softness ?? 24}</span>
      <input aria-label="Edge softness" type="range" min="1" max="100" disabled={busy} value={data.softness ?? 24} onchange={(e) => $flow.setNodeData(id, { softness: +e.currentTarget.value })} />
    </label>
    <label><input type="checkbox" disabled={busy} checked={data.despill !== false} onchange={(e) => $flow.setNodeData(id, { despill: e.currentTarget.checked })} /> Remove color fringe</label>
    <div class="dna-field-hint">No AI call. Removes the selected color from the canvas edges; suitable for a prepared solid background. Up to 4 megapixels.</div>
  {:else}
  <div class="dna-field">
    <div class="dna-field-cap">What to preserve</div>
    <textarea rows="3" disabled={busy} value={data.prompt} placeholder="Optional: for example, preserve the sofa and its cushions"
      oninput={(e) => { const value = e.currentTarget.value; commitNodeText(`removebackground:${id}:prompt`, () => $flow.setNodeData(id, { prompt: value })); }}
      onblur={() => flushNodeText(`removebackground:${id}:prompt`)}></textarea>
    <div class="dna-field-hint">GPT Image · Codex account. Output is a transparent PNG. Check fine details after processing.</div>
  </div>
  {/if}
  {#if data.variants.length}<button class="dna-btn-ghost" disabled={busy} onclick={() => { $flow.setNodeData(id, { variants: [], active: 0 }); $flow.propagate(id); }}>Clear results</button>{/if}
</div>
