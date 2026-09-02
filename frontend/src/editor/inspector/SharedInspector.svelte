<script lang="ts">
  import * as ctl from "../controller";
  import { editorUi } from "../state";
  import type { AssistAction, AssistScopeMode } from "../aiTypes";
  import type { GeoRef, GeoSel } from "../globals";
  import DesignSystemPicker from "../../components/DesignSystemPicker.svelte";
import ColorPicker from "./ColorPicker.svelte";
  import FontOptions from "./FontOptions.svelte";
  import { findByKey, isSourceKeyPath } from "../../engine/sourcepath";

  const QUICK: { action: AssistAction; label: string; prompt: string }[] = [
    { action: "adapt", label: "Адаптив", prompt: "Сделай выделение адаптивным для tablet и mobile, сохрани дизайн и структуру." },
    { action: "content-fit", label: "Подогнать", prompt: "Подгони размеры и внутренние отступы под содержимое без изменения структуры." },
    { action: "align", label: "Выровнять", prompt: "Аккуратно выровняй выделенные элементы внутри ближайшего контейнера." },
  ];
  function getByPath(obj: any, path: string) { return path.split(".").reduce((o, k) => o == null ? o : o[k], obj); }
  function nodeOf(ir: any, ref: GeoRef) {
    if (ref.secIdx == null) return ir;
    if (ref.path == null) return ir.tree?.[ref.secIdx];
    const section = ir.tree?.[ref.secIdx];
    return isSourceKeyPath(ref.path) ? findByKey(section, ref.path) : getByPath(section, ref.path);
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
  function valueLabel(value: unknown) {
    if (value === undefined) return "—";
    if (value === null) return "пусто";
    const text = typeof value === "string" ? value : JSON.stringify(value);
    return text.length > 48 ? text.slice(0, 45) + "…" : text;
  }
  function propertyLabel(path: string) {
    const key = path.split("/").filter(Boolean).at(-1) || path;
    const names: Record<string, string> = {
      background: "Заливка", color: "Цвет текста", fontSize: "Размер шрифта", fontWeight: "Вес шрифта",
      fontFamily: "Шрифт", padding: "Внутренние отступы", gap: "Расстояние", width: "Ширина", height: "Высота",
      x: "Позиция X", y: "Позиция Y", align: "Выравнивание", justify: "Распределение", direction: "Направление",
      text: "Текст", title: "Заголовок", placeholder: "Подсказка", opacity: "Прозрачность", radius: "Скругление",
    };
    return names[key] || key;
  }
  function run(action: AssistAction, text: string) {
    confirmed = false;
    ctl.setAiAssistFormState({ prompt: text, action, scopeMode, provider, effort, designSystemSelection: dsSelection, constraints: { allowContent, allowStyle, allowFrame, allowColor } });
    void ctl.requestAiAssist({
      action, prompt: text, scopeMode, provider, effort,
      constraints: { allowContent, allowStyle, allowFrame, allowColor },
    });
  }

  const sess = ctl.getSession();
  const sels: GeoSel[] = sess?.sel || [];
  const geo = sess?.geo || null;
  const first = sels[0];
  const selectedValue = first ? nodeOf(sess?.ir, first.ref) : undefined;
  const node = selectedValue ?? {};
  const isScalarProp = first?.ref.path?.startsWith("props.") && (selectedValue == null || typeof selectedValue !== "object");
  const isFormField = !!first?.ref.path && /^props\.fields\.\d+$/.test(first.ref.path);
  const isFormLabel = !!first?.ref.path && /^props\.fields\.\d+\.parts\.label$/.test(first.ref.path);
  const isFormControl = !!first?.ref.path && /^props\.fields\.\d+\.parts\.control$/.test(first.ref.path);
  const isFormSubmit = first?.ref.path === "props.submit" && node.role === "form-submit";
  const isImage = sels.length === 1 && node.type === "image";
  let imageBusy = $state(false);
  async function onImageFile(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0] ?? null;
    input.value = "";
    if (!file) return;
    imageBusy = true;
    try {
      await ctl.uploadImageForSelection(file);
    } finally {
      imageBusy = false;
    }
  }
  const formFieldPath = first?.ref.path?.match(/^(props\.fields\.\d+)/)?.[1];
  const formField = formFieldPath && first?.ref.secIdx != null ? getByPath(sess?.ir?.tree?.[first.ref.secIdx], formFieldPath) || {} : {};
  const frame = first && geo ? geo.frameOf(first.ref) || {} : {};
  const style = node.style || {};
  const canUngroup = sels.length === 1 && Array.isArray(node.children) && node.children.length > 0 && frame.layout === "free";
  // Ручная геометрия (data-pi — контракт wireInspector/тестов): у секций
  // x/y/rotation неприменимы, у контейнеров показываем раскладку
  const isRootSel = first?.ref.path == null;
  const isContainer = Array.isArray(node.children) && node.children.length > 0;
  const dir = frame.layout === "free" ? "free" : String(frame.direction || "row");
  const radioName = "pi-just-" + (first?.ref.secIdx ?? "x") + "-" + (first?.ref.path ?? "root");
  const padding = paddingOf(frame.padding);
  const fill = hex(style.background || node.fill, "#ffffff");
  const textColor = hex(style.color, "#111111");
  const savedAiForm = ctl.getAiAssistFormState();
  let scopeMode = $state<AssistScopeMode>(sels.length > 1 ? (ctl.hasExplicitAiAssistScopeMode() ? savedAiForm.scopeMode : "selection") : "single");
  let effort = $state<"medium" | "high" | "max">(["medium", "high", "max"].includes(String(savedAiForm.effort)) ? savedAiForm.effort as "medium" | "high" | "max" : "medium");
  /* Модель и усилие — один селект: пара значений «провайдер:усилие». Claude
   * доступен только там, где есть desktop-мост (запрос исполняет локальный
   * CLI); в браузере остаётся Sol, потому что там отвечает сервер. */
  const MODEL_LABELS: Record<string, string> = { openai: "GPT-5.6 Sol", claude: "Claude Opus", codex: "Codex" };
  const modelOptions = ctl.ASSIST_PROVIDERS
    .filter((item) => ctl.assistProviderAvailable(item))
    .flatMap((item) => (item === "codex"
      // Codex — текстовый транспорт без reasoning: один пункт без усилий
      ? [{ value: "codex:medium", label: MODEL_LABELS[item] }]
      : (["medium", "high", "max"] as const).map((level) => ({
          value: `${item}:${level}`,
          label: `${MODEL_LABELS[item]} · ${level[0].toUpperCase()}${level.slice(1)}`,
        }))));
  let provider = $state<"openai" | "claude" | "codex">(
    ctl.assistProviderAvailable(String(savedAiForm.provider)) ? savedAiForm.provider as "openai" | "claude" | "codex" : "openai",
  );
  // bind:value, а не value={...}: атрибут выставляется до монтирования <option>,
  // и селект оставался визуально пустым, хотя значение в состоянии было.
  let modelChoice = $state(
    `${ctl.assistProviderAvailable(String(savedAiForm.provider)) ? savedAiForm.provider : "openai"}`
    + `:${["medium", "high", "max"].includes(String(savedAiForm.effort)) ? savedAiForm.effort : "medium"}`,
  );
  function applyModelChoice() {
    const [nextProvider, nextEffort] = modelChoice.split(":");
    provider = nextProvider as "openai" | "claude" | "codex";
    effort = nextEffort as "medium" | "high" | "max";
    ctl.setAiAssistFormState({ provider, effort });
  }
  let dsSelection = $state<string>((savedAiForm as any).designSystemSelection || "inherit");
  let prompt = $state(savedAiForm.prompt);
  let allowContent = $state(savedAiForm.constraints.allowContent);
  let allowStyle = $state(isScalarProp ? false : savedAiForm.constraints.allowStyle);
  let allowFrame = $state(isScalarProp ? false : savedAiForm.constraints.allowFrame);
  let allowColor = $state(isScalarProp ? false : savedAiForm.constraints.allowColor);
  let confirmed = $state(false);
  const busy = $derived($editorUi.aiBusy);
  const error = $derived($editorUi.aiError);
  const preview = $derived($editorUi.aiPreview);
  const progress = $derived($editorUi.aiProgress);
  const scope = $derived(ctl.getAiScopeView(scopeMode));
  const highImpact = $derived(!!preview && (preview.ops.length > 8 || preview.warnings.some((warning) => warning.code === "high_impact")));
  let elapsedSeconds = $state(0);
  $effect(() => {
    const startedAt = progress?.startedAt;
    if (!busy || !startedAt) { elapsedSeconds = 0; return; }
    const update = () => { elapsedSeconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000)); };
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  });
  function elapsedLabel(seconds: number) {
    const minutes = Math.floor(seconds / 60);
    const rest = String(seconds % 60).padStart(2, "0");
    return minutes ? `${minutes}:${rest}` : `${seconds} сек`;
  }
</script>

<div class="ai-inspector" data-ai-inspector>
  <section class="ai-scope" aria-label="Область изменения">
    <div class="ai-scope-copy"><span class="ai-scope-kicker">AI изменит</span><strong>{scopeMode === "document" ? `весь артборд · ${scope.items.length} секц.` : scopeMode === "selection" ? `выбранные объекты · ${scope.items.length}` : scope.items[0]?.label}</strong></div>
    <div class="ai-scope-switch">
      {#if sels.length > 1 && scopeMode !== "document"}
        <button aria-pressed={scopeMode === "single"} class:active={scopeMode === "single"} onclick={() => { scopeMode = "single"; ctl.setAiAssistScopeMode(scopeMode); }}>Один</button>
        <button aria-pressed={scopeMode === "selection"} class:active={scopeMode === "selection"} onclick={() => { scopeMode = "selection"; ctl.setAiAssistScopeMode(scopeMode); }}>Группа</button>
      {/if}
      <button aria-pressed={scopeMode === "document"} class:active={scopeMode === "document"} title="AI изменит все секции артборда в одном согласованном проходе" onclick={() => { scopeMode = scopeMode === "document" ? (sels.length > 1 ? "selection" : "single") : "document"; ctl.setAiAssistScopeMode(scopeMode); }}>Вся страница</button>
    </div>
  </section>
  <div class="ai-provider-row" aria-label="Модель">
    <span class="ai-scope-kicker">Модель</span>
    <select bind:value={modelChoice} onchange={applyModelChoice} disabled={busy || !!preview}>
      {#each modelOptions as option (option.value)}
        <option value={option.value}>{option.label}</option>
      {/each}
    </select>
  </div>
  <div class="ai-scope-list" aria-label="Элементы для AI">
    {#if scopeMode === "document"}<span class="ai-scope-chip">все секции · согласованно</span>{/if}
    {#each scopeMode === "document" ? [] : scope.items as item (item.sourceKey)}
      <span class="ai-scope-chip">{item.label}{#if scopeMode === "selection" && scope.items.length > 1}<button title="Убрать из группы" aria-label={`Убрать ${item.label} из группы`} onclick={() => ctl.removeFromAiSelection(item.ref)}>×</button>{/if}</span>
    {/each}
  </div>
  {#if scope.excluded.length}
    <div class="ai-scope-warning">Контейнер «{scope.excluded.map((item) => item.label).join(", ")}» исключён: выбрана вложенная часть.</div>
  {/if}

  <div class="ai-ds-row"><DesignSystemPicker selection={dsSelection} usageMode={((savedAiForm as any).designSystemUsageMode || "strict")} onChange={(v, meta) => { dsSelection = v; ctl.setAiAssistFormState({ designSystemSelection: v, designSystemUsageMode: meta?.usageMode } as any); }} /></div>
  <section class="ai-command-card">
    <div class="ai-command-title"><span class="ai-spark">✦</span><div><strong>Что изменить?</strong><small>Сначала покажу результат. Вы решаете, применять ли его.</small></div></div>
    <textarea bind:value={prompt} oninput={() => ctl.setAiAssistFormState({ prompt })} disabled={busy || !!preview} placeholder="Например: сделай карточку компактнее и легче" aria-label="Задача для AI"></textarea>
    <fieldset class="ai-constraints" disabled={busy || !!preview}>
      <legend>Можно менять</legend>
      <label><input type="checkbox" bind:checked={allowContent} onchange={() => ctl.setAiAssistFormState({ constraints: { allowContent } as any })} /> Текст</label>
      <label><input type="checkbox" bind:checked={allowStyle} disabled={isScalarProp} onchange={() => ctl.setAiAssistFormState({ constraints: { allowStyle } as any })} /> Стиль</label>
      <label><input type="checkbox" bind:checked={allowFrame} disabled={isScalarProp} onchange={() => ctl.setAiAssistFormState({ constraints: { allowFrame } as any })} /> Размеры</label>
      <label><input type="checkbox" bind:checked={allowColor} disabled={isScalarProp} onchange={() => ctl.setAiAssistFormState({ constraints: { allowColor } as any })} /> Цвета</label>
    </fieldset>
    {#if isScalarProp}<small>Для этого текстового свойства AI меняет только текст.</small>{:else}<div class="ai-quick-row">{#each QUICK as item (item.action)}<button disabled={busy || !!preview || (scopeMode !== "document" && !scope.items.length)} onclick={() => run(item.action, item.prompt)}>{item.label}</button>{/each}</div>{/if}
    <button class="ai-run" data-ai-run aria-busy={busy} disabled={busy || !!preview || !prompt.trim() || (scopeMode !== "document" && !scope.items.length)} onclick={() => run("custom", prompt)}>{busy ? `AI работает · ${elapsedLabel(elapsedSeconds)}` : "Показать вариант"}</button>
    {#if busy && progress}
      <div class="ai-progress" data-ai-progress={progress.stage} role="status" aria-live="polite">
        <span class="ai-progress-spinner" aria-hidden="true"></span>
        <div><strong>{progress.label}</strong><small>{elapsedSeconds >= 90 ? "Ответ занимает дольше обычного, но запрос ещё активен" : "Запрос активен · обычно 20–120 секунд"}</small></div>
        <button type="button" class="ai-progress-cancel" data-ai-cancel aria-label="Отменить запрос AI" onclick={ctl.cancelAiAssist}>Отменить</button>
      </div>
    {/if}
    {#if error}<div class="ai-error" role="alert">{error}</div>{/if}
    {#if preview}
      <div class="ai-preview" data-ai-preview="ready" aria-live="polite">
        <div class="ai-preview-head"><span>Предпросмотр</span><b>{preview.ops.length} изм.</b></div><p>{preview.summary}</p>
        <small>{preview.ops.length ? "Изменения видны на холсте, исходник ещё не изменён." : "Макет уже соответствует запросу."}</small>
        {#if preview.ops.length}
          <details class="ai-diff" open>
            <summary>Что изменится</summary>
            <ol>{#each preview.ops.slice(0, 8) as op}<li><strong>{propertyLabel(op.path)}</strong><span>{valueLabel(op.before)} → {valueLabel(op.after)}</span>{#if op.reason}<small>{op.reason}</small>{/if}</li>{/each}</ol>
            {#if preview.ops.length > 8}<div class="ai-diff-more">Ещё {preview.ops.length - 8} изменений</div>{/if}
          </details>
        {/if}
        {#if highImpact}
          <div class="ai-impact" role="alert"><strong>Много изменений</strong><span>Проверьте подсвеченные объекты и список перед применением.</span><label><input type="checkbox" bind:checked={confirmed} /> Я проверил изменения</label></div>
        {/if}
        <div class="ai-preview-actions"><button data-ai-cancel aria-label="Отменить предпросмотр AI" onclick={ctl.cancelAiAssist}>Отменить</button><button class="primary" data-ai-apply aria-label="Применить правки AI" disabled={!preview.ops.length || (highImpact && !confirmed)} onclick={ctl.applyAiAssist}>Применить</button></div>
      </div>
    {/if}
  </section>

  {#if !preview}
    {#if sels.length}
    <details class="manual-controls"><summary><span>Точно вручную</span><small>{isFormField ? "группа · цвета · padding · align" : isFormLabel ? "подпись · шрифт · цвет · padding" : isFormControl ? "поле ввода · шрифт · цвета · padding" : isFormSubmit ? "кнопка · текст · шрифт · цвета · padding" : "position · flex · шрифт · цвета · padding · merge · align"}</small></summary>
      <div class="manual-body pi">
        {#if isFormField}<div class="manual-group field-content"><span class="manual-label">Группа поля</span><p>Выберите вложенную подпись или поле ввода на холсте либо в слоях.</p></div>{/if}
        <div class="manual-group"><span class="manual-label">Position</span>
          <div class="pi-row">
            <div class="pi-field"><label for="pi-frame-x" title="Тяни горизонтально — scrub; можно выражения: 100*2">X</label><input id="pi-frame-x" type="text" inputMode="decimal" data-pi="x" value={frame.x ?? ""} disabled={isRootSel} /></div>
            <div class="pi-field"><label for="pi-frame-y" title="Тяни горизонтально — scrub; можно выражения: 100*2">Y</label><input id="pi-frame-y" type="text" inputMode="decimal" data-pi="y" value={frame.y ?? ""} disabled={isRootSel} /></div>
          </div>
          <div class="pi-row">
            <div class="pi-field"><label for="pi-frame-width" title="Ширина. Можно выражения: 960/3">Ш</label><input id="pi-frame-width" type="text" inputMode="decimal" data-pi="width" value={frame.width ?? ""} /></div>
            <div class="pi-field"><label for="pi-frame-height" title="Высота. Можно выражения: 960/3">В</label><input id="pi-frame-height" type="text" inputMode="decimal" data-pi="height" value={frame.height ?? ""} /></div>
          </div>
          <div class="pi-row">
            <div class="pi-field"><label for="pi-frame-rotation">R</label><input id="pi-frame-rotation" type="text" inputMode="decimal" data-pi="rotation" value={frame.rotation ?? ""} disabled={isRootSel} /></div>
            <div class="pi-field"><label for="pi-frame-gap">Gap</label><input id="pi-frame-gap" type="text" inputMode="decimal" data-pi="gap" value={typeof frame.gap === "number" ? frame.gap : ""} /></div>
          </div>
          {#if !isRootSel}
            <div class="pi-row"><label class="pi-check"><input type="checkbox" data-pi="absolute" checked={!!frame.absolute} /> Absolute</label></div>
          {/if}
        </div>
        {#if isContainer}
          <div class="manual-group"><span class="manual-label">Flex Layout</span>
            <div class="pi-btnrow">
              <button class={"pi-ibtn" + (dir === "free" ? " active" : "")} data-pi-dir="free" title="Без раскладки: дети по x/y">⊞</button>
              <button class={"pi-ibtn" + (dir === "column" ? " active" : "")} data-pi-dir="column" title="Колонка (vertical)">↓</button>
              <button class={"pi-ibtn" + (dir === "row" ? " active" : "")} data-pi-dir="row" title="Ряд (horizontal)">→</button>
            </div>
            <div class="pi-grid3">
              {#each ["start", "center", "end"] as a}
                {#each ["start", "center", "end"] as j}
                  <button class={"pi-ibtn" + (frame.justify === j && frame.align === a ? " active" : "")} data-pi-ja={j + "|" + a} title={"justify:" + j + " align:" + a}><span class="dot"></span></button>
                {/each}
              {/each}
            </div>
            <div class="pi-row"><label class="pi-radio"><input type="radio" name={radioName} data-pi-justify="space-between" checked={frame.justify === "space-between"} /> Space Between</label></div>
            <div class="pi-row"><label class="pi-radio"><input type="radio" name={radioName} data-pi-justify="space-around" checked={frame.justify === "space-around"} /> Space Around</label></div>
          </div>
        {/if}
        {#if isFormLabel}<div class="manual-group field-content"><span class="manual-label">Подпись</span><label><span>Текст</span><input data-el-prop="text" value={node.text ?? formField.label ?? ""} /></label></div>{/if}
        {#if isFormControl}<div class="manual-group field-content"><span class="manual-label">Поле ввода</span><label><span>Подсказка</span><input data-el-prop="placeholder" value={node.placeholder ?? formField.placeholder ?? ""} /></label></div>{/if}
        {#if isFormSubmit}<div class="manual-group field-content"><span class="manual-label">Кнопка формы</span><label><span>Текст</span><input data-el-prop="text" value={node.text ?? sess?.ir?.tree?.[first.ref.secIdx!]?.props?.submitText ?? "Отправить"} /></label></div>{/if}
        {#if isImage}
          <div class="manual-group field-content pi-image" data-pi-image>
            <span class="manual-label">Изображение</span>
            {#if node.src}
              <img class="pi-image-preview" src={node.src} alt={node.alt || ""} />
            {:else}
              <div class="pi-image-empty">Заглушка{node.imagePrompt ? `: ${String(node.imagePrompt).slice(0, 80)}` : ""}. Загрузите свою картинку — или двойной клик по заглушке на холсте.</div>
            {/if}
            <div class="pi-image-actions">
              <label class="fe-btn primary pi-image-upload">
                {imageBusy ? "Загружаю…" : node.src ? "Заменить…" : "Загрузить…"}
                <input type="file" accept="image/*" data-act="upload-image" hidden disabled={imageBusy} onchange={onImageFile} />
              </label>
              {#if node.src}<button class="fe-btn" type="button" data-act="clear-image" onclick={() => ctl.clearImageForSelection()}>Убрать</button>{/if}
            </div>
            <label><span>Alt</span><input data-el-prop="alt" value={node.alt ?? ""} placeholder={node.imagePrompt ?? ""} /></label>
          </div>
        {/if}
        <div class="manual-group"><span class="manual-label">Align</span><div class="align-grid">
          <button data-act="align-left" title="По левому краю" aria-label="По левому краю">⇤</button><button data-act="align-center-h" title="По центру горизонтали" aria-label="По центру горизонтали">↔</button><button data-act="align-right" title="По правому краю" aria-label="По правому краю">⇥</button>
          <button data-act="align-top" title="По верхнему краю" aria-label="По верхнему краю">↥</button><button data-act="align-center-v" title="По центру вертикали" aria-label="По центру вертикали">↕</button><button data-act="align-bottom" title="По нижнему краю" aria-label="По нижнему краю">↧</button>
          <button data-act="distribute-h" title="Распределить по горизонтали" aria-label="Распределить по горизонтали" disabled={sels.length < 3}>↹</button><button data-act="distribute-v" title="Распределить по вертикали" aria-label="Распределить по вертикали" disabled={sels.length < 3}>⇕</button>
        </div></div>
        <div class="manual-group"><span class="manual-label">Merge</span><div class="merge-row"><button data-act="group" disabled={sels.length < 2} aria-label="Объединить">Объединить</button><button data-act="ungroup" disabled={!canUngroup} aria-label="Разъединить">Разъединить</button></div></div>
        <div class="manual-group"><span class="manual-label">Padding</span><div class="padding-grid">{#each ["T", "R", "B", "L"] as label, index}<label><span>{label}</span><input data-padding={label.toLowerCase()} type="number" min="0" value={padding[index]} onchange={(event) => setPadding(index, event)} /></label>{/each}</div></div>
        <div class="manual-group"><span class="manual-label">Цвета</span><div class="manual-color"><ColorPicker styleKey="background" label="Заливка" hex={fill} raw={style.background || node.fill || ""} transparent={!style.background && !node.fill} /></div><div class="manual-color"><ColorPicker styleKey="color" label="Текст" hex={textColor} raw={style.color || ""} transparent={!style.color} /></div></div>
        <div class="manual-group"><span class="manual-label">Шрифт</span><label class="font-family"><span>Семейство</span><select data-style-select="fontFamily" value={style.fontFamily || ""}><FontOptions autoLabel="Как в теме" /></select></label><div class="font-pair"><label><span>Размер</span><input type="number" min="1" data-style-num="fontSize" value={typeof style.fontSize === "number" ? style.fontSize : ""} placeholder="auto" /></label><label><span>Вес</span><input type="number" min="100" max="900" step="100" data-style-num="fontWeight" value={typeof style.fontWeight === "number" ? style.fontWeight : ""} placeholder="auto" /></label></div></div>
      </div>
    </details>
    {/if}
  {/if}

  <!-- Привязка к сетке: тумблер + шаг; состояние в editor/store (зеркало controller) -->
  <div class="fe-snap">
    <div class="fe-snap-head">
      <div class="fe-snap-copy"><strong>Привязка к сетке</strong><small>Шаг {$editorUi.snapStep}px · Alt — отключить</small></div>
      <button
        class={"fe-snap-toggle" + ($editorUi.snap ? " on" : "")}
        role="switch"
        aria-checked={$editorUi.snap}
        aria-label="Привязка к сетке"
        onclick={() => ctl.setSnap(!$editorUi.snap)}
      ><i></i></button>
    </div>
    <div class="fe-snap-steps" role="group" aria-label="Шаг сетки">
      {#each [4, 8, 12, 16] as s (s)}
        <button
          class:active={$editorUi.snapStep === s}
          aria-pressed={$editorUi.snapStep === s}
          disabled={!$editorUi.snap}
          onclick={() => ctl.setSnapStep(s)}
        >{s}px</button>
      {/each}
    </div>
  </div>
</div>
