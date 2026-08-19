<script lang="ts">
  import * as ctl from "../controller";
  import { editorUi } from "../state";
  import type { AssistAction, AssistScopeMode } from "../aiTypes";
  import type { GeoRef, GeoSel } from "../globals";
  import ColorPicker from "./ColorPicker.svelte";
  import FontOptions from "./FontOptions.svelte";

  const QUICK: { action: AssistAction; label: string; prompt: string }[] = [
    { action: "adapt", label: "Адаптив", prompt: "Сделай выделение адаптивным для tablet и mobile, сохрани дизайн и структуру." },
    { action: "content-fit", label: "Подогнать", prompt: "Подгони размеры и внутренние отступы под содержимое без изменения структуры." },
    { action: "align", label: "Выровнять", prompt: "Аккуратно выровняй выделенные элементы внутри ближайшего контейнера." },
  ];
  function getByPath(obj: any, path: string) { return path.split(".").reduce((o, k) => o == null ? o : o[k], obj); }
  function nodeOf(ir: any, ref: GeoRef) {
    if (ref.secIdx == null) return ir;
    if (ref.path == null) return ir.tree?.[ref.secIdx];
    return getByPath(ir.tree?.[ref.secIdx], ref.path);
  }
  function hex(value: any, fallback: string) {
    const text = String(value || "").trim();
    if (/^#[0-9a-f]{3}$/i.test(text)) return "#" + text.slice(1).split("").map((c) => c + c).join("").toLowerCase();
    return /^#[0-9a-f]{6}$/i.test(text) ? text.toLowerCase() : fallback;
  }
  function paddingOf(value: unknown): number[] {
    if (Array.isArray(value)) {
      const p = value.map((item) => Number(item) || 0);
      return p.length >= 4 ? p.slice(0, 4) : [p[0] || 0, p[1] ?? p[0] ?? 0, p[2] ?? p[0] ?? 0, p[3] ?? p[1] ?? p[0] ?? 0];
    }
    const n = Number(value) || 0;
    return [n, n, n, n];
  }
  function setPadding(index: number, event: Event) {
    const value = Math.max(0, Number((event.currentTarget as HTMLInputElement).value) || 0);
    const next = [...padding]; next[index] = value;
    geo?.setFrameProps({ padding: next });
  }
  function run(action: AssistAction, text: string) { void ctl.requestAiAssist({ action, prompt: text, scopeMode }); }

  const sess = ctl.getSession();
  const sels: GeoSel[] = sess?.sel || [];
  const geo = sess?.geo || null;
  const first = sels[0];
  const node = first ? nodeOf(sess?.ir, first.ref) || {} : {};
  const isFormField = !!first?.ref.path && /^props\.fields\.\d+$/.test(first.ref.path);
  const isFormLabel = !!first?.ref.path && /^props\.fields\.\d+\.parts\.label$/.test(first.ref.path);
  const isFormControl = !!first?.ref.path && /^props\.fields\.\d+\.parts\.control$/.test(first.ref.path);
  const isFormSubmit = first?.ref.path === "props.submit" && node.role === "form-submit";
  const formFieldPath = first?.ref.path?.match(/^(props\.fields\.\d+)/)?.[1];
  const formField = formFieldPath && first?.ref.secIdx != null ? getByPath(sess?.ir?.tree?.[first.ref.secIdx], formFieldPath) || {} : {};
  const frame = first && geo ? geo.frameOf(first.ref) || {} : {};
  const style = node.style || {};
  const canUngroup = sels.length === 1 && Array.isArray(node.children) && node.children.length > 0 && frame.layout === "free";
  const padding = paddingOf(frame.padding);
  const fill = hex(style.background || node.fill, "#ffffff");
  const textColor = hex(style.color, "#111111");
  let scopeMode = $state<AssistScopeMode>(sels.length > 1 ? "selection" : "single");
  let prompt = $state("");
  const busy = $derived($editorUi.aiBusy);
  const error = $derived($editorUi.aiError);
  const preview = $derived($editorUi.aiPreview);
</script>

<div class="ai-inspector" data-ai-inspector>
  <section class="ai-scope" aria-label="Область изменения">
    <div class="ai-scope-copy"><span class="ai-scope-kicker">AI изменит</span><strong>{scopeMode === "selection" ? `группу · ${sels.length}` : first?.label}</strong></div>
    {#if sels.length > 1}
      <div class="ai-scope-switch"><button class:active={scopeMode === "single"} onclick={() => scopeMode = "single"}>Один</button><button class:active={scopeMode === "selection"} onclick={() => scopeMode = "selection"}>Группа</button></div>
    {:else}<span class="ai-scope-lock">1 объект</span>{/if}
  </section>

  <section class="ai-command-card">
    <div class="ai-command-title"><span class="ai-spark">✦</span><div><strong>Что изменить?</strong><small>Сначала покажу результат. Вы решаете, применять ли его.</small></div></div>
    <textarea bind:value={prompt} disabled={busy || !!preview} placeholder="Например: сделай карточку компактнее и легче" aria-label="Задача для AI"></textarea>
    <div class="ai-quick-row">{#each QUICK as item (item.action)}<button disabled={busy || !!preview} onclick={() => run(item.action, item.prompt)}>{item.label}</button>{/each}</div>
    <button class="ai-run" disabled={busy || !!preview || !prompt.trim()} onclick={() => run("custom", prompt)}>{busy ? "Готовлю результат…" : "Показать результат"}</button>
    {#if error}<div class="ai-error" role="alert">{error}</div>{/if}
    {#if preview}
      <div class="ai-preview" data-ai-preview="ready">
        <div class="ai-preview-head"><span>Предпросмотр</span><b>{preview.ops.length} изм.</b></div><p>{preview.summary}</p>
        <small>{preview.ops.length ? "Изменения видны на холсте, исходник ещё не изменён." : "Макет уже соответствует запросу."}</small>
        <div class="ai-preview-actions"><button data-ai-cancel onclick={ctl.cancelAiAssist}>Отменить</button><button class="primary" data-ai-apply disabled={!preview.ops.length} onclick={ctl.applyAiAssist}>Применить</button></div>
      </div>
    {/if}
  </section>

  {#if !preview}
    <details class="manual-controls"><summary><span>Точно вручную</span><small>{isFormField ? "группа · цвета · padding · align" : isFormLabel ? "подпись · шрифт · цвет · padding" : isFormControl ? "поле ввода · шрифт · цвета · padding" : isFormSubmit ? "кнопка · текст · шрифт · цвета · padding" : "шрифт · цвета · padding · merge · align"}</small></summary>
      <div class="manual-body pi">
        {#if isFormField}<div class="manual-group field-content"><span class="manual-label">Группа поля</span><p>Выберите вложенную подпись или поле ввода на холсте либо в слоях.</p></div>{/if}
        {#if isFormLabel}<div class="manual-group field-content"><span class="manual-label">Подпись</span><label><span>Текст</span><input data-el-prop="text" value={node.text ?? formField.label ?? ""} /></label></div>{/if}
        {#if isFormControl}<div class="manual-group field-content"><span class="manual-label">Поле ввода</span><label><span>Подсказка</span><input data-el-prop="placeholder" value={node.placeholder ?? formField.placeholder ?? ""} /></label></div>{/if}
        {#if isFormSubmit}<div class="manual-group field-content"><span class="manual-label">Кнопка формы</span><label><span>Текст</span><input data-el-prop="text" value={node.text ?? sess?.ir?.tree?.[first.ref.secIdx!]?.props?.submitText ?? "Отправить"} /></label></div>{/if}
        <div class="manual-group"><span class="manual-label">Align</span><div class="align-grid">
          <button data-act="align-left" title="По левому краю">⇤</button><button data-act="align-center-h" title="По центру горизонтали">↔</button><button data-act="align-right" title="По правому краю">⇥</button>
          <button data-act="align-top" title="По верхнему краю">↥</button><button data-act="align-center-v" title="По центру вертикали">↕</button><button data-act="align-bottom" title="По нижнему краю">↧</button>
        </div></div>
        <div class="manual-group"><span class="manual-label">Merge</span><div class="merge-row"><button data-act="group" disabled={sels.length < 2}>Объединить</button><button data-act="ungroup" disabled={!canUngroup}>Разъединить</button></div></div>
        <div class="manual-group"><span class="manual-label">Padding</span><div class="padding-grid">{#each ["T", "R", "B", "L"] as label, index}<label><span>{label}</span><input data-padding={label.toLowerCase()} type="number" min="0" value={padding[index]} onchange={(event) => setPadding(index, event)} /></label>{/each}</div></div>
        <div class="manual-group"><span class="manual-label">Цвета</span><div class="manual-color"><ColorPicker styleKey="background" label="Заливка" hex={fill} raw={style.background || node.fill || ""} transparent={!style.background && !node.fill} /></div><div class="manual-color"><ColorPicker styleKey="color" label="Текст" hex={textColor} raw={style.color || ""} transparent={!style.color} /></div></div>
        <div class="manual-group"><span class="manual-label">Шрифт</span><label class="font-family"><span>Семейство</span><select data-style-select="fontFamily" value={style.fontFamily || ""}><FontOptions autoLabel="Как в теме" /></select></label><div class="font-pair"><label><span>Размер</span><input type="number" min="1" data-style-num="fontSize" value={typeof style.fontSize === "number" ? style.fontSize : ""} placeholder="auto" /></label><label><span>Вес</span><input type="number" min="100" max="900" step="100" data-style-num="fontWeight" value={typeof style.fontWeight === "number" ? style.fontWeight : ""} placeholder="auto" /></label></div></div>
      </div>
    </details>
  {/if}
</div>
