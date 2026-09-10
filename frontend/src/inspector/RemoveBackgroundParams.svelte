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
    if (file.size > 20 * 1024 * 1024) { toast("Выберите изображение до 20 МБ", "error"); return; }
    const applyUpload = captureNodeUpload(id);
    const reader = new FileReader();
    reader.onload = () => applyUpload({ image: String(reader.result), fileName: file.name });
    reader.readAsDataURL(file);
    input.value = "";
  }
</script>

<div class="dna-insp-fields">
  <label class="dna-field">
    <span class="dna-field-cap">Способ удаления</span>
    <select disabled={busy} value={data.method || 'ai'} onchange={(e) => $flow.setNodeData(id, { method: e.currentTarget.value })}>
      <option value="ai">Codex · произвольный фон</option>
      <option value="chroma">Локально · однородный фон</option>
    </select>
  </label>
  <div class="dna-field">
    <div class="dna-field-cap">Исходное изображение</div>
    <label class="dna-btn-ghost" style="cursor:pointer">
      {data.image ? "Заменить изображение" : "Загрузить изображение"}
      <input type="file" accept="image/png,image/jpeg,image/webp" hidden disabled={busy} onchange={upload} />
    </label>
    {#if data.fileName}<div class="dna-field-hint">{data.fileName}</div>{/if}
    <div class="dna-field-hint">Подключённая картинка имеет приоритет перед загруженным файлом.</div>
    {#if data.image}<button class="dna-btn-ghost" disabled={busy} onclick={() => $flow.setNodeData(id, { image: null, fileName: "" })}>Убрать файл</button>{/if}
  </div>
  {#if data.method === 'chroma'}
    <label class="dna-field"><span class="dna-field-cap">Цвет фона</span>
      <input aria-label="Цвет фона" type="color" disabled={busy} value={data.keyColor || '#00ff00'} onchange={(e) => $flow.setNodeData(id, { keyColor: e.currentTarget.value })} />
    </label>
    <label class="dna-field"><span class="dna-field-cap">Допуск · {data.tolerance ?? 32}</span>
      <input aria-label="Допуск" type="range" min="0" max="160" disabled={busy} value={data.tolerance ?? 32} onchange={(e) => $flow.setNodeData(id, { tolerance: +e.currentTarget.value })} />
    </label>
    <label class="dna-field"><span class="dna-field-cap">Мягкость края · {data.softness ?? 24}</span>
      <input aria-label="Мягкость края" type="range" min="1" max="100" disabled={busy} value={data.softness ?? 24} onchange={(e) => $flow.setNodeData(id, { softness: +e.currentTarget.value })} />
    </label>
    <label><input type="checkbox" disabled={busy} checked={data.despill !== false} onchange={(e) => $flow.setNodeData(id, { despill: e.currentTarget.checked })} /> Убрать цветную кайму</label>
    <div class="dna-field-hint">Без AI-вызова. Удаляет выбранный цвет от края холста; подходит для подготовленного однородного фона. До 4 мегапикселей.</div>
  {:else}
  <div class="dna-field">
    <div class="dna-field-cap">Что сохранить</div>
    <textarea rows="3" disabled={busy} value={data.prompt} placeholder="Необязательно: например, сохранить диван вместе с подушками"
      oninput={(e) => { const value = e.currentTarget.value; commitNodeText(`removebackground:${id}:prompt`, () => $flow.setNodeData(id, { prompt: value })); }}
      onblur={() => flushNodeText(`removebackground:${id}:prompt`)}></textarea>
    <div class="dna-field-hint">GPT Image · аккаунт Codex. Результат — PNG с прозрачностью. Проверьте мелкие детали объекта после обработки.</div>
  </div>
  {/if}
  {#if data.variants.length}<button class="dna-btn-ghost" disabled={busy} onclick={() => { $flow.setNodeData(id, { variants: [], active: 0 }); $flow.propagate(id); }}>Очистить результаты</button>{/if}
</div>
