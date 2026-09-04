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
      toast("Правила проекта сохранены: следующая генерация и судья их применят", "ok");
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
      <div class="fe-locks-kicker">Правила · генератор и судья</div>
      <h2 id="rules-title">По каким правилам работает агент</h2>
      <p>Встроенные правила версионируются с приложением. Правила проекта пишете вы: они уходят в промпт генерации и в рубрику vision-судьи, то есть проверяются.</p>
      <div class="fe-rules-tabs" role="tablist">
        <button class="fe-btn" class:primary={tab === "project"} role="tab" aria-selected={tab === "project"} data-rules-tab="project" onclick={() => (tab = "project")}>Правила проекта{dirty ? " •" : ""}</button>
        {#each builtin as rule (rule.id)}
          <button class="fe-btn" class:primary={tab === rule.id} role="tab" aria-selected={tab === rule.id} data-rules-tab={rule.id} onclick={() => (tab = rule.id)}>{rule.title}</button>
        {/each}
      </div>
      {#if loading}
        <div class="fe-rules-empty">Загрузка правил…</div>
      {:else if tab === "project"}
        <textarea
          class="fe-rules-editor"
          data-rules-project
          placeholder="Например: карточки без теней; один CTA на экран; никаких градиентов; кнопки только из мастера button/primary; тексты на русском без англицизмов."
          bind:value={draft}
          maxlength={maxChars}
          spellcheck="false"
        ></textarea>
        <div class="fe-rules-meta">{draft.length} / {maxChars}</div>
      {:else if active}
        <div class="fe-rules-meta">{active.file} · только чтение</div>
        <pre class="fe-rules-view" data-rules-view={active.id}>{active.text || "(пусто)"}</pre>
      {/if}
      {#if error}<div class="fe-rules-error" role="alert">{error}</div>{/if}
      <div class="fe-locks-actions">
        <button class="fe-btn" data-act="close-rules" onclick={() => ctl.handleAct("close-rules")}>Закрыть</button>
        {#if tab === "project"}
          <button class="fe-btn primary" data-act="save-rules" disabled={saving || !dirty} onclick={() => void save()}>{saving ? "Сохраняю…" : "Сохранить правила"}</button>
        {/if}
      </div>
    </div>
  </div>
{/if}
