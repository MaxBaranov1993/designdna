<script lang="ts">
  /* Панель «Правила»: чем руководствуются генератор и судья — не чёрный ящик.
   * Встроенные правила (DESIGN.md / BLOCKS.md / RUBRIC.md) показываются как есть,
   * правила проекта редактируются здесь и уходят в промпт генерации и в рубрику
   * судьи (GET/POST /api/rules). data-act — контракт тестов. */
  import * as ctl from "./controller";
  import { editorUi } from "./state";
  import { toast } from "../flow/toast";

  type BuiltinRule = { id: string; title: string; file: string; text: string };
  const open = $derived($editorUi.rulesOpen);
  let tab = $state("project");
  let builtin: BuiltinRule[] = $state([]);
  let project = $state("");
  let draft = $state("");
  let maxChars = $state(20000);
  let loading = $state(false);
  let saving = $state(false);
  let error = $state("");

  async function load() {
    loading = true;
    error = "";
    try {
      const res = await fetch("/api/rules");
      const body = await res.json();
      if (!res.ok || body.error) throw new Error(body.error || body.detail || `HTTP ${res.status}`);
      builtin = Array.isArray(body.builtin) ? body.builtin : [];
      project = String(body.project || "");
      draft = project;
      maxChars = Number(body.maxProjectChars) || 20000;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  async function save() {
    saving = true;
    error = "";
    try {
      const res = await fetch("/api/rules/project", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: draft }),
      });
      const body = await res.json();
      if (!res.ok || body.error) throw new Error(body.error || body.detail || `HTTP ${res.status}`);
      project = String(body.project || "");
      draft = project;
      toast("Project rules saved. The next generation and review will use them", "ok");
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      saving = false;
    }
  }

  $effect(() => {
    if (open) void load();
  });

  const dirty = $derived(draft !== project);
  const active = $derived(builtin.find((r) => r.id === tab) || null);
</script>

{#if open}
  <div
    class="fe-locks-backdrop"
    role="presentation"
    onmousedown={(event) => {
      if (event.target === event.currentTarget) ctl.handleAct("close-rules");
    }}
  >
    <div class="fe-locks-card fe-rules-card" role="dialog" aria-modal="true" aria-labelledby="rules-title" data-rules-panel>
      <div class="fe-locks-kicker">Rules · Generator and judge</div>
      <h2 id="rules-title">Rules used by the agent</h2>
      <p>Built-in rules are versioned with the app. Your project rules are included in the generation prompt and the visual judge rubric so they can be checked.</p>
      <div class="fe-rules-tabs" role="tablist">
        <button class="fe-btn" class:primary={tab === "project"} role="tab" aria-selected={tab === "project"} data-rules-tab="project" onclick={() => (tab = "project")}>Project rules{dirty ? " •" : ""}</button>
        {#each builtin as rule (rule.id)}
          <button class="fe-btn" class:primary={tab === rule.id} role="tab" aria-selected={tab === rule.id} data-rules-tab={rule.id} onclick={() => (tab = rule.id)}>{rule.title}</button>
        {/each}
      </div>
      {#if loading}
        <div class="fe-rules-empty">Loading rules…</div>
      {:else if tab === "project"}
        <textarea
          class="fe-rules-editor"
          data-rules-project
          placeholder="For example: cards without shadows; one CTA per screen; no gradients; buttons from button/primary only; clear English copy."
          bind:value={draft}
          maxlength={maxChars}
          spellcheck="false"
        ></textarea>
        <div class="fe-rules-meta">{draft.length} / {maxChars}</div>
      {:else if active}
        <div class="fe-rules-meta">{active.file} · read-only</div>
        <pre class="fe-rules-view" data-rules-view={active.id}>{active.text || "(empty)"}</pre>
      {/if}
      {#if error}<div class="fe-rules-error" role="alert">{error}</div>{/if}
      <div class="fe-locks-actions">
        <button class="fe-btn" data-act="close-rules" onclick={() => ctl.handleAct("close-rules")}>Close</button>
        {#if tab === "project"}
          <button class="fe-btn primary" data-act="save-rules" disabled={saving || !dirty} onclick={() => void save()}>{saving ? "Saving…" : "Save rules"}</button>
        {/if}
      </div>
    </div>
  </div>
{/if}
