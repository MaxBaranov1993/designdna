<script lang="ts">
  import { storySchedule, type VideoStory } from "../engine/video-story";
  let { story, disabled = false, onChange, onSeek }: {story: VideoStory; disabled?: boolean; onChange: (story: VideoStory) => void; onSeek: (time: number) => void} = $props();
  let selected = $state("");
  let selectedField = $state("");
  const states = $derived(story.pages.filter(page => page.generatedFrom));
  const page = $derived(states.find(page => page.id === selected) || states[0]);
  const fields = $derived.by(() => {
    const result: Array<{path: string; text: string}> = [];
    const keys = new Set(["text", "heading", "subheading", "title", "label", "placeholder", "description", "subtitle", "caption", "body", "value", "alt", "imagePrompt", "ctaPrimary", "ctaSecondary"]);
    const walk = (value: any, path: string) => {
      if (Array.isArray(value)) value.forEach((child, i) => walk(child, `${path}.${i}`));
      else if (value && typeof value === "object") for (const [key, child] of Object.entries(value)) {
        if (["style", "frame", "tokens", "meta", "provenance", "componentRef"].includes(key)) continue;
        if (keys.has(key) && typeof child === "string") result.push({path: `${path}.${key}`, text: child});
        else if (child && typeof child === "object") walk(child, `${path}.${key}`);
      }
    };
    if (page) { walk(page.overlays, "overlays"); walk(page.ir.tree, "ir.tree"); }
    return result;
  });
  const field = $derived(fields.find(field => field.path === selectedField) || fields[0]);
  const entry = $derived(storySchedule(story).find(action => action.type === "navigate" && action.toPageId === page?.id));
  function editText(text: string) {
    if (!page || !field || disabled) return;
    const next: VideoStory = JSON.parse(JSON.stringify(story));
    let node: any = next.pages.find(item => item.id === page.id);
    const parts = field.path.split(".");
    for (const part of parts.slice(0, -1)) node = node[part];
    node[parts[parts.length - 1]] = text;
    onChange(next);
  }
</script>

{#if states.length}
  <section class="video-states" aria-label="Созданные состояния" data-act="video-states">
    <strong>Созданные состояния · {states.length}</strong>
    <p>Копии для ролика. Исходная страница сохранена.</p>
    <label>Состояние<select aria-label="Состояние страницы" value={page?.id} onchange={(event) => { selected = event.currentTarget.value; selectedField = ""; }}>
      {#each states as state}<option value={state.id}>{state.name}</option>{/each}
    </select></label>
    <button disabled={!entry} onclick={() => entry && onSeek(entry.end + 1)}>Показать в ролике</button>
    {#if fields.length}
      <label>Текст<select aria-label="Текст состояния" value={field?.path} onchange={(event) => selectedField = event.currentTarget.value}>
        {#each fields as item}<option value={item.path}>{item.text.slice(0, 70) || "Пустой текст"}</option>{/each}
      </select></label>
      <textarea aria-label="Изменить текст состояния" disabled={disabled} maxlength="8000" rows="3" value={field?.text || ""} onchange={(event) => editText(event.currentTarget.value)}></textarea>
    {/if}
  </section>
{/if}

<style>
  .video-states { display: grid; gap: 9px; padding: 12px 0; border-top: 1px solid var(--dna-border); margin-bottom: 16px; font-size: 11px; }
  strong { font-size: 12px; color: var(--dna-text); }
  p { color: var(--dna-dim); line-height: 1.5; margin: 0; }
  label { display: grid; gap: 5px; color: var(--dna-dim); }
  select, textarea, button { box-sizing: border-box; min-width: 0; width: 100%; font: inherit; color: var(--dna-text); background: var(--dna-elevated); border: 1px solid var(--dna-border); border-radius: 6px; padding: 7px; }
  textarea { resize: vertical; line-height: 1.5; }
  button { cursor: pointer; }
  :disabled { opacity: .5; }
</style>
