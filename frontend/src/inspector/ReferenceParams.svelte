<script lang="ts">
  import { captureNodeUpload } from "../flow/store";
  import { flow } from "../flow/state";
  import { commitNodeText, flushNodeText } from "../flow/textcommit";
  import { toast } from "../flow/toast";
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
    <div class="dna-field-cap">Описание стиля</div>
    <textarea
      rows="5"
      value={data.brief}
      placeholder="Что взять из референса: плотность, тон, характер кнопок…"
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
    <div class="dna-field-cap">Изображение</div>
    <label class="dna-btn-ghost" style="cursor: pointer">
      {data.fileName ? `Заменить · ${data.fileName}` : "Выбрать скриншот"}
      <input type="file" accept="image/*" hidden onchange={onFile} />
    </label>
    {#if data.image}
      <button class="dna-btn-ghost" onclick={() => $flow.setNodeData(id, { image: null, fileName: "" })}>Убрать изображение</button>
    {/if}
  </div>
  <label class="dna-insp-check">
    <input type="checkbox" checked={!!data.decomposed} onchange={(e) => {
      if (e.currentTarget.checked) { toast("Разбор референса на компоненты появится в Фазе B2"); e.currentTarget.checked = false; return; }
      $flow.setNodeData(id, { decomposed: false });
    }} />
    <span>Разбить на компоненты</span>
  </label>
</div>
