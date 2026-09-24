<script lang="ts">
  import { captureNodeUpload } from "../flow/store";
  import { flow } from "../flow/state";
  import { commitNodeText, flushNodeText } from "../flow/textcommit";
  import type { ReferenceNodeData } from "../flow/types";

  let { id, data }: { id: number; data: ReferenceNodeData } = $props();

  const onFile = (e: Event) => {
    const input = e.currentTarget as HTMLInputElement;
    const f = input.files && input.files[0];
    if (!f) return;
    const applyUpload = captureNodeUpload(id);
    const rd = new FileReader();
    rd.onload = () => applyUpload({ image: String(rd.result), fileName: f.name });
    rd.readAsDataURL(f);
    input.value = "";
  };
</script>

<div class="dna-insp-fields">
  <div class="dna-field">
    <div class="dna-field-cap">Image role</div>
    <select value={data.role || "style"} onchange={(e) => $flow.setNodeData(id, { role: e.currentTarget.value as NonNullable<ReferenceNodeData["role"]> })}>
      <option value="style">Style: palette and character</option>
      <option value="composition">Composition: layout and hierarchy</option>
      <option value="reproduce">Reproduce the original</option>
    </select>
    <div class="dna-field-hint">Connect the image output to Generator Reference. Exact design system components retain priority.</div>
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Style description</div>
    <textarea
      rows="5"
      value={data.brief}
      placeholder="What to take from the reference: density, tone, button style…"
      oninput={(e) => {
        const value = e.currentTarget.value;
        commitNodeText(`reference:${id}:brief`, () => {
          $flow.setNodeData(id, { brief: value });
          $flow.propagate(id);
        });
      }}
      onblur={() => flushNodeText(`reference:${id}:brief`)}
    ></textarea>
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Image</div>
    <label class="dna-btn-ghost" style="cursor: pointer">
      {data.fileName ? `Replace · ${data.fileName}` : "Choose screenshot"}
      <input type="file" accept="image/*" hidden onchange={onFile} />
    </label>
    {#if data.image}
      <button class="dna-btn-ghost" onclick={() => $flow.setNodeData(id, { image: null, fileName: "" })}>Remove image</button>
    {/if}
  </div>
</div>
