<script lang="ts">
  /* Единый DesignSystemPicker (ТЗ §15): выбор системы + режим + mock для всех
   * AI-поверхностей. Badge интерфейса, не canvas-нода. */
  import { flow, flowDesignSystems } from "../flow/state";
  import type { DesignSystemPickerChange, DesignSystemUsageMode } from "../flow/types";

  let {
    selection = "inherit",
    usageMode = "strict",
    fixtureProfile = "typical",
    onChange,
    compact = false,
  } = $props<{
    selection?: "inherit" | "none" | string;
    usageMode?: DesignSystemUsageMode;
    fixtureProfile?: string;
    onChange?: (value: "inherit" | "none" | string, meta?: DesignSystemPickerChange) => void;
    compact?: boolean;
  }>();

  const registry = $derived($flowDesignSystems || { systems: [], defaultSystemRef: null });
  const defaultSystem = $derived(
    registry.systems.find((s: any) => s.systemId === registry.defaultSystemRef?.systemId && s.status === "published"),
  );
  const published = $derived((registry.systems || []).filter((s: any) => s.status === "published"));

  const emit = (nextSelection = selection, nextMode = usageMode, nextFixture = fixtureProfile) => {
    const meta: DesignSystemPickerChange = {
      selection: nextSelection,
      usageMode: nextMode,
      fixtureProfile: nextFixture,
    };
    $flow.setDesignSystemPicker(meta);
    onChange?.(nextSelection, meta);
  };

  export function resolvedRef(): Record<string, unknown> | null {
    const st = $flow;
    const picker = st.designSystemPicker;
    const currentSelection = selection || picker?.selection || "inherit";
    const currentMode = usageMode || picker?.usageMode || "strict";
    const currentFixture = fixtureProfile || picker?.fixtureProfile || "typical";
    if (currentSelection === "none") return null;
    if (currentSelection === "inherit") {
      const ref = (st.designSystems as any)?.defaultSystemRef;
      if (!ref) return null;
      const system = ((st.designSystems as any).systems || []).find((s: any) => s.systemId === ref.systemId);
      if (!system || system.status !== "published") return null;
      return { systemId: ref.systemId, revision: ref.revision ?? system.revision, contentHash: system.contentHash || ref.contentHash || "", usageMode: currentMode, mockFixtureProfile: currentFixture };
    }
    const system = ((st.designSystems as any).systems || []).find((s: any) => s.systemId === currentSelection);
    if (!system || system.status !== "published") return null;
    return { systemId: currentSelection, revision: system.revision, contentHash: system.contentHash || "", usageMode: currentMode, mockFixtureProfile: currentFixture };
  }

  const set = (value: "inherit" | "none" | string) => {
    selection = value;
    emit(value, usageMode, fixtureProfile);
  };
</script>

{#if compact}
  <span class="ds-badge" title="Дизайн-система" data-ds-picker="compact">
    DS · {selection === "inherit" ? (defaultSystem ? `${defaultSystem.name} v${defaultSystem.revision}` : "нет") : selection === "none" ? "нет" : "reference"} · {usageMode}
  </span>
{:else}
  <div class="ds-picker" data-ds-picker>
    <label class="ds-field">
      <span>Design System</span>
      <select
        data-ds-field="selection"
        aria-label="Выбор дизайн-системы: inherit, конкретная reference-система или none"
        value={selection}
        onchange={(e) => set(e.currentTarget.value as any)}
      >
        <option value="inherit">Project default — {defaultSystem ? `${defaultSystem.name} · v${defaultSystem.revision}` : "не задана"}</option>
        {#each published as system (system.systemId)}
          <option value={system.systemId}>
            {system.name} · v{system.revision} (reference)
          </option>
        {/each}
        {#each (registry.systems || []).filter((s: any) => s.status !== "published") as system (system.systemId)}
          <option value={system.systemId} disabled>
            {system.name} · v{system.revision} ({system.status})
          </option>
        {/each}
        <option value="none">None</option>
      </select>
    </label>
    {#if selection !== "none" && (selection !== "inherit" || defaultSystem)}
      <label class="ds-field">
        <span>Режим</span>
        <select
          data-ds-field="usage"
          aria-label="Режим использования: strict или свободнее"
          value={usageMode}
          onchange={(e) => emit(selection, e.currentTarget.value as DesignSystemUsageMode, fixtureProfile)}
        >
          <option value="strict">Strict — только компоненты системы</option>
          <option value="extend">Extend — новые компоненты локально</option>
          <option value="style-only">Style only — только foundations</option>
        </select>
      </label>
      <label class="ds-field">
        <span>Mock data</span>
        <select
          data-ds-field="fixture"
          aria-label="Профиль mock-данных"
          value={fixtureProfile}
          onchange={(e) => emit(selection, usageMode, e.currentTarget.value)}
        >
          <option value="typical">typical</option>
          <option value="short">short</option>
          <option value="long">long</option>
          <option value="empty">empty</option>
          <option value="loading">loading</option>
          <option value="error">error</option>
          <option value="edge-case">edge-case</option>
        </select>
      </label>
    {/if}
    {#if !published.length}
      <small class="ds-hint">Нет опубликованных систем — создайте из Source-ноды: «UI Kit & Design System»</small>
    {/if}
  </div>
{/if}

<style>
  .ds-picker { display: flex; flex-direction: column; gap: 6px; padding: 6px 0; }
  .ds-field { display: flex; flex-direction: column; gap: 2px; font-size: 10.5px; color: #8b8fa3; }
  .ds-field select { font-size: 11.5px; padding: 3px 6px; border-radius: 6px; border: 1px solid #2a2e3d; background: #171923; color: #e2e5ee; }
  .ds-hint { font-size: 10px; color: #6b7080; }
  .ds-badge { font-size: 10px; color: #8b8fa3; border: 1px solid #2a2e3d; padding: 2px 6px; border-radius: 4px; }
</style>
