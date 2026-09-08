<script lang="ts">
  import ProviderPicker from "../components/ProviderPicker.svelte";
  import { flow, flowBusy, flowDesignSystemPicker, flowDesignSystems } from "../flow/state";
  import { pinnedDesignSystemRef } from "../flow/store";
  import { commitNodeText, flushNodeText } from "../flow/textcommit";
  import type { GeneratorNodeData } from "../flow/types";

  /* Параметры Генератора, переехавшие из тела ноды: свой промпт, задача,
   * визуальное направление, дизайн-система, действия с активным вариантом. */
  let { id, data }: { id: number; data: GeneratorNodeData & Record<string, any> } = $props();

  let busy = $derived(!!$flowBusy[id]);
  let effort = $derived(["medium", "high", "max"].includes(data.effort) ? data.effort : "medium");
  let count = $derived(Math.max(1, Math.min(2, Number(data.count) || 1)));
  let activeIr = $derived(data.variants?.length ? data.variants[data.active] || null : null);
  let pinnedRef = $derived(pinnedDesignSystemRef(data as Record<string, unknown>, $flowDesignSystems, $flowDesignSystemPicker));
  let usageMode = $derived(String(data.designSystemUsageMode || $flowDesignSystemPicker?.usageMode || "strict"));
  let dsOptedOut = $derived(String(data.designSystemSelection || "") === "none");
  let dsName = $derived(pinnedRef ? ($flowDesignSystems.systems?.find((s) => s.systemId === pinnedRef!.systemId)?.name || String(pinnedRef.systemId)) : "");

  const surfaceOptions = [
    ["auto", "Определить по задаче"], ["landing", "Лендинг"], ["catalog", "Поиск и каталог"],
    ["detail", "Карточка объекта"], ["checkout", "Запись и оформление"], ["dashboard", "Кабинет и аналитика"],
    ["form", "Форма и настройки"], ["editor", "Редактор"], ["ai-workspace", "AI-интерфейс"],
    ["article", "Статья и журнал"], ["feed", "Лента"], ["component", "Один компонент"],
  ];
  const styleOptions = [
    ["auto", "По задаче и дизайн-системе"], ["minimal", "Спокойный минимализм"], ["enterprise", "Информационный"],
    ["marketplace", "Поиск на первом месте"], ["editorial", "Редакционный"], ["swiss", "Строгая сетка"],
    ["product-led", "Демонстрация продукта"], ["luxury", "Сдержанный предметный"], ["organic", "Материальный"],
    ["playful", "Иллюстративный"], ["brutal", "Плакатный"], ["industrial", "Технический"],
    ["soft-pastel", "Мягкая палитра"], ["bento", "Модульный"], ["glass", "Многослойный"],
    ["immersive", "Иммерсивный"], ["retro", "Ретро"],
  ];
</script>

<div class="dna-insp-fields">
  <div class="dna-field">
    <div class="dna-field-cap">Свой промпт</div>
    <textarea
      rows="4"
      placeholder="Используется, если к входу «Промт» ничего не подключено"
      value={data.ownPrompt}
      oninput={(e) => {
        const value = e.currentTarget.value;
        commitNodeText(`generator:${id}:ownPrompt`, () => $flow.setNodeData(id, { ownPrompt: value }));
      }}
      onblur={() => flushNodeText(`generator:${id}:ownPrompt`)}
    ></textarea>
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Модель и усилие</div>
    <ProviderPicker provider={data.provider || "openai"} {effort} onChange={(next) => $flow.setNodeData(id, next)} />
  </div>
  <div class="dna-insp-row">
    <div class="dna-field">
      <div class="dna-field-cap">Вариантов</div>
      <select value={String(count)} onchange={(e) => $flow.setNodeData(id, { count: Number(e.currentTarget.value) })}>
        <option value="1">1</option>
        <option value="2">2</option>
      </select>
    </div>
    <div class="dna-field">
      <div class="dna-field-cap">Тип экрана</div>
      <select disabled={busy} value={data.surface || "auto"} onchange={(e) => $flow.setNodeData(id, { surface: e.currentTarget.value, selectedDirection: "all", directions: [] })}>
        {#each surfaceOptions as option}<option value={option[0]}>{option[1]}</option>{/each}
      </select>
    </div>
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Визуальное направление</div>
    <select disabled={busy || !!pinnedRef} value={data.designStyle || "auto"} onchange={(e) => $flow.setNodeData(id, { designStyle: e.currentTarget.value, selectedDirection: "all" })}>
      {#each styleOptions as option}<option value={option[0]}>{option[1]}</option>{/each}
    </select>
    <div class="dna-field-hint">{pinnedRef ? "Внешний вид задаёт выбранная дизайн-система." : "Без дизайн-системы генератор создаст согласованные основы под задачу."}</div>
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Дизайн-система</div>
    {#if pinnedRef && !dsOptedOut}
      <div class="dna-field-value"><span>◈ {dsName}</span><span class="dna-out-kind">проект</span></div>
      <select value={usageMode} onchange={(e) => $flow.setNodeData(id, { designSystemUsageMode: e.currentTarget.value })}>
        <option value="strict">strict — только мастера и токены</option>
        <option value="extend">extend — мастера + новое в токенах</option>
        <option value="style-only">style-only — токены и характер</option>
      </select>
      <button class="dna-btn-ghost" onclick={() => $flow.setNodeData(id, { designSystemSelection: "none" })}>Генерировать без ДС</button>
    {:else if dsOptedOut}
      <div class="dna-field-value"><span>ДС отключена для этой ноды</span></div>
      <button class="dna-btn-ghost" onclick={() => $flow.setNodeData(id, { designSystemSelection: "inherit" })}>Вернуть ДС проекта</button>
    {:else}
      <div class="dna-field-hint">Подключите ноду «Дизайн-система» ко входу или выберите систему проекта.</div>
    {/if}
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Активный вариант</div>
    <div class="dna-insp-row">
      <button class="dna-btn-ghost" disabled={!activeIr} onclick={() => $flow.sendToNode(id, "edit")}>→ Редактор</button>
      <button class="dna-btn-ghost" disabled={!activeIr} onclick={() => $flow.sendToNode(id, "reference")}>→ Референс</button>
      <button class="dna-btn-ghost" disabled={busy || !activeIr} title="Запомнить как удачный" onclick={() => void $flow.recordVariantTaste(id, "accepted")}>✓ Принять</button>
      <button class="dna-btn-ghost" disabled={busy || !activeIr} title="Запомнить как неудачный" onclick={() => void $flow.recordVariantTaste(id, "rejected")}>× Отклонить</button>
    </div>
    <button class="dna-btn-ghost" disabled={busy || !activeIr} title="Сделать этот вариант дизайн-системой" onclick={() => void $flow.promoteVariantToDesignSystem(id)}>◈ Закрепить стиль как ДС</button>
  </div>
</div>
