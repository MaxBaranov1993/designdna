<script lang="ts">
  import { onMount } from "svelte";
  import Button from "../components/ui/Button.svelte";
  import "./project-map.css";

  type Snapshot = Awaited<ReturnType<NonNullable<Window["designDNA"]>["repoCanvas"]["snapshot"]>>;

  const desktop = window.designDNA;
  let snapshot = $state<Snapshot | null>(null);
  let error = $state("");
  let busy = $state(false);

  const load = async () => {
    if (!desktop) return;
    busy = true;
    error = "";
    try {
      snapshot = await desktop.repoCanvas.snapshot();
    } catch (reason) {
      error = reason instanceof Error ? reason.message : String(reason);
    } finally {
      busy = false;
    }
  };

  onMount(() => {
    void load();
  });

  let entitiesByArea = $derived.by(() => {
    const groups = new Map<string, NonNullable<Snapshot>["entities"]>();
    for (const entity of snapshot?.entities || []) {
      const group = groups.get(entity.areaId || "unassigned") || [];
      group.push(entity);
      groups.set(entity.areaId || "unassigned", group);
    }
    return groups;
  });

  const refreshArchitecture = async () => {
    if (!desktop || !window.confirm("Перестроить семантическую карту проекта через Codex?")) return;
    busy = true;
    error = "";
    try {
      await desktop.repoCanvas.refresh({ effort: "medium" });
      await load();
    } catch (reason) {
      error = reason instanceof Error ? reason.message : String(reason);
      busy = false;
    }
  };
</script>

{#if !desktop}
  <div class="project-map-empty">Project Map доступен в desktop-приложении DesignDNA.</div>
{:else}
  <section class="project-map-shell">
    <header class="project-map-header">
      <div>
        <span class="project-map-eyebrow">Live semantic workspace</span>
        <h1>Project Map</h1>
        <p>Архитектура репозитория и активная работа агентов в одном локальном runtime.</p>
      </div>
      <div class="project-map-actions">
        <Button variant="outline" onclick={() => void load()} disabled={busy}>Обновить</Button>
        <Button onclick={() => void refreshArchitecture()} disabled={busy}>Architect refresh</Button>
      </div>
    </header>

    {#if error}<div class="project-map-error">{error}</div>{/if}
    <div class="project-map-stats">
      {@render metric("Areas", snapshot?.summary.areaCount ?? 0)}
      {@render metric("Entities", snapshot?.summary.entityCount ?? 0)}
      {@render metric("Active work", snapshot?.summary.activeWork ?? 0)}
      {@render metric("Revision", snapshot?.revision ?? 0)}
    </div>

    <div class="project-map-grid">
      {#each snapshot?.areas || [] as area (area.id)}
        <article class="project-area">
          <div class="project-area-title"><h2>{area.title || area.id}</h2><span>{entitiesByArea.get(area.id)?.length || 0}</span></div>
          {#if area.note}<p>{area.note}</p>{/if}
          <div class="project-entities">
            {#each entitiesByArea.get(area.id) || [] as entity (entity.id)}
              <div class="project-entity">
                <div><strong>{entity.label || entity.id}</strong>{#if entity.status}<small>{entity.status}</small>{/if}</div>
                {#if entity.purpose}<p>{entity.purpose}</p>{/if}
                {#if entity.path}<code>{entity.path}</code>{/if}
              </div>
            {/each}
          </div>
        </article>
      {/each}
    </div>

    {#if snapshot?.work?.length}
      <section class="project-work">
        <h2>Agent work</h2>
        <div>
          {#each snapshot.work as item (item.id)}
            <span>{item.title || item.task || item.id} · {item.status || "unknown"}</span>
          {/each}
        </div>
      </section>
    {/if}
  </section>
{/if}

{#snippet metric(label: string, value: number)}
  <div class="project-map-metric"><strong>{value}</strong><span>{label}</span></div>
{/snippet}
