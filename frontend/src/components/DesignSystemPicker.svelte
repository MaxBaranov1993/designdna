<script lang="ts">
  /* Единый DesignSystemPicker (ТЗ §15): выбор системы + режим + mock для всех
   * AI-поверхностей. Badge интерфейса, не canvas-нода. */
  import { flow } from "../flow/state";

  let { selection = "inherit", onChange, compact = false } = $props<{
    selection?: "inherit" | "none" | string;
    onChange?: (value: "inherit" | "none" | string) => void;
    compact?: boolean;
  }>();

  let usageMode = $state<"strict" | "extend" | "style-only">("strict");
  let fixtureProfile = $state("typical");

  const registry = $derived($flow.designSystems || { systems: [], defaultSystemRef: null });
  const defaultSystem = $derived(
    registry.systems.find((s: any) => s.systemId === registry.defaultSystemRef?.systemId && s.status === "published"),
  );

  export function resolvedRef(): Record<string, unknown> | null {
    const st = $flow;
    if (selection === "none") return null;
    if (selection === "inherit") {
      const ref = (st.designSystems as any)?.defaultSystemRef;
      if (!ref) return null;
      const system = ((st.designSystems as any).systems || []).find((s: any) => s.systemId === ref.systemId);
      if (!system || system.status !== "published") return null;
      return { systemId: ref.systemId, revision: ref.revision ?? system.revision, contentHash: system.contentHash || "", usageMode, mockFixtureProfile: fixtureProfile };
    }
    const system = ((st.designSystems as any).systems || []).find((s: any) => s.systemId === selection);
    if (!system || system.status !== "published") return null;
    return { systemId: selection, revision: system.revision, contentHash: system.contentHash || "", usageMode, mockFixtureProfile: fixtureProfile };
  }

  const set = (value: "inherit" | "none" | string) => { selection = value; onChange?.(value); };
</script>

{#if compact}
  <span class="ds-badge" title="Дизайн-система">DS · {selection === "inherit" ? (defaultSystem ? `${defaultSystem.name} v${defaultSystem.revision}` : "нет") : selection === "none" ? "нет" : selection} · {usageMode}</span>
{:else}
  <div class="ds-picker">
    <label class="ds-field">
      <span>Design System</span>
      <select value={selection} onchange={(e) => set(e.currentTarget.value as any)} disabled={!registry.systems?.length}>
        <option value="inherit">Project default — {defaultSystem ? `${defaultSystem.name} · v${defaultSystem.revision}` : "не задана"}</option>
        {#each registry.systems as system (system.systemId)}
          <option value={system.systemId} disabled={system.status !== "published"}>
            {system.name} · v{system.revision}{system.status !== "published" ? ` (${system.status})` : ""}
          </option>
        {/each}
        <option value="none">None</option>
      </select>
    </label>
    {#if selection !== "none" && (selection !== "inherit" || defaultSystem)}
      <label class="ds-field">
        <span>Режим</span>
        <select bind:value={usageMode}>
          <option value="strict">Strict — только компоненты системы</option>
          <option value="extend">Extend — новые компоненты локально</option>
          <option value="style-only">Style only — только foundations</option>
        </select>
      </label>
      <label class="ds-field">
        <span>Mock data</span>
        <select bind:value={fixtureProfile}>
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
    {#if !registry.systems?.length}
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
