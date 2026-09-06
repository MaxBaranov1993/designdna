<script lang="ts">
  import { actionLabel, storySchedule, storyTargets } from "../engine/video-story";
  import { motionDurations, softenStory, type StoryEasing } from "../engine/story-motion";
  import type { StoryAction, VideoStory } from "../engine/video-story";
  let { story, disabled = false, onChange, onSeek, onPolish }: { story: VideoStory; disabled?: boolean; onChange: (story: VideoStory) => void; onSeek: (time: number) => void; onPolish: (story: VideoStory) => void } = $props();
  let selected = $state("");
  let kind = $state<StoryAction["type"]>("wait");
  const rows = $derived(storySchedule(story));
  const action = $derived(story.actions.find((a) => a.id === selected));
  const page = $derived(story.pages.find((p) => p.id === action?.pageId));
  const targets = $derived(page ? storyTargets(page.ir).filter((t) => action?.type !== "type" || t.kind === "input") : []);
  const pageName = (id: string) => story.pages.find((p) => p.id === id)?.name || id;
  const targetName = (a: StoryAction) => storyTargets(story.pages.find((p) => p.id === a.pageId)?.ir || {}).find((t) => t.id === a.target)?.label || "";
  function change(patch: Partial<StoryAction>) {
    onChange({ ...story, actions: story.actions.map((a) => a.id === selected ? { ...a, ...patch } : a) });
  }
  function move(offset: number) {
    const actions = [...story.actions], index = actions.findIndex((a) => a.id === selected), next = index + offset;
    if (index < 0 || next < 0 || next >= actions.length) return;
    [actions[index], actions[next]] = [actions[next], actions[index]];
    onChange({ ...story, actions });
  }
  function add() {
    const last = story.actions.at(-1);
    const pageId = last?.type === "navigate" ? last.toPageId! : last?.pageId || story.initialPageId;
    const page = story.pages.find((p) => p.id === pageId)!;
    const target = storyTargets(page.ir).find((t) => kind === "type" ? t.kind === "input" : t.kind === "button") || storyTargets(page.ir)[0];
    const next: StoryAction = { id: "action-" + crypto.randomUUID(), type: kind, pageId, duration: motionDurations[kind], easing: "soft" };
    if (["move", "click", "type"].includes(kind)) next.target = target?.id;
    if (kind === "type") next.text = "";
    if (kind === "scroll") next.y = 400;
    if (kind === "navigate") { next.toPageId = story.pages.find((p) => p.id !== pageId)?.id; next.transition = "motion"; }
    selected = next.id;
    onChange({ ...story, actions: [...story.actions, next] });
  }
</script>

<div class="story-panel" inert={disabled}>
  <div class="story-title">Сценарий <span>{story.actions.length} действий</span></div>
  {#if !rows.length}<p class="story-empty">Опишите действия в промпте или добавьте их вручную.</p>{/if}
  {#if rows.length}<button data-act="story-soften" title="Плавные движения, спокойный темп и 60 fps. Можно отменить." onclick={() => onPolish(softenStory(story))}>Смягчить весь сценарий</button>{/if}
  <div class="story-rows">
    {#each rows as row, i (row.id)}
      <button class:active={selected === row.id} class="story-row" data-act="story-action" onclick={() => { selected = row.id; onSeek(row.start); }}>
        <span class="story-number">{i + 1}</span>
        <span><strong>{actionLabel[row.type]}</strong><small>{pageName(row.pageId)}{row.type === "navigate" ? " → " + pageName(row.toPageId!) : targetName(row) ? " · " + targetName(row) : ""}</small></span>
        <span class="story-time">{(row.start / 1000).toFixed(1)}s</span>
      </button>
    {/each}
  </div>
  <div class="story-add"><select aria-label="Новое действие" bind:value={kind}>{#each Object.entries(actionLabel) as [value, label]}<option {value}>{label}</option>{/each}</select>
    <button data-act="story-add" disabled={rows.length >= 100 || (kind === "navigate" && story.pages.length < 2)} onclick={add}>+</button></div>
  {#if action}
    <div class="story-fields">
      <strong>{actionLabel[action.type]}</strong>
      <label>На странице<select aria-label="Страница действия" value={action.pageId} onchange={(e) => change({ pageId: e.currentTarget.value })}>{#each story.pages as p}<option value={p.id}>{p.name}</option>{/each}</select></label>
      {#if ["move", "click", "type"].includes(action.type)}<label>Элемент<select aria-label="Элемент действия" value={action.target || ""} onchange={(e) => change({ target: e.currentTarget.value })}>{#each targets as t}<option value={t.id}>{t.label}</option>{/each}</select></label>{/if}
      {#if action.type === "type"}<label>Текст<textarea aria-label="Текст для ввода" value={action.text || ""} onchange={(e) => change({ text: e.currentTarget.value })}></textarea></label>{/if}
      {#if action.type === "scroll"}<label>Прокрутить к<select aria-label="Цель прокрутки" value={action.target || ""} onchange={(e) => change({ target: e.currentTarget.value || undefined, y: action.y || 0 })}><option value="">Позиция в пикселях</option>{#each targets as t}<option value={t.id}>{t.label}</option>{/each}</select></label>{#if !action.target}<label>Прокрутить до, px<input aria-label="Позиция прокрутки" type="number" min="0" max="100000" value={action.y} onchange={(e) => change({ y: Number(e.currentTarget.value) })} /></label>{/if}{/if}
      {#if action.type === "navigate"}<label>Перейти на<select aria-label="Страница назначения" value={action.toPageId || ""} onchange={(e) => change({ toPageId: e.currentTarget.value })}>{#each story.pages.filter((p) => p.id !== action.pageId) as p}<option value={p.id}>{p.name}</option>{/each}</select></label>
        <label>Переход<select aria-label="Эффект перехода" value={action.transition || "fade"} onchange={(e) => change({ transition: e.currentTarget.value as "cut" | "fade" | "motion" })}><option value="cut">Смена кадра</option><option value="fade">Растворение</option><option value="motion">Motion · плавное появление</option></select></label>{/if}
      {#if action.type !== "wait"}<label>Плавность<select aria-label="Плавность движения" value={action.easing || "soft"} onchange={(e) => change({ easing: e.currentTarget.value as StoryEasing })}><option value="soft">Ease in-out · мягко</option><option value="ease-in">Ease in · разгон</option><option value="ease-out">Ease out · торможение</option><option value="linear">Равномерно</option></select></label>{/if}
      <label>Длительность, с<input aria-label="Длительность действия" type="number" step="0.1" min="0.1" max="60" value={action.duration / 1000} onchange={(e) => change({ duration: Math.round(Number(e.currentTarget.value) * 1000) })} /></label>
      <div class="story-order"><button title="Раньше" onclick={() => move(-1)}>↑</button><button title="Позже" onclick={() => move(1)}>↓</button><button onclick={() => onChange({ ...story, actions: story.actions.filter((a) => a.id !== selected) })}>Удалить</button></div>
    </div>
  {/if}
</div>

<style>
  .story-panel { font-size: 12px; margin-bottom: 16px; }
  .story-title { font-weight: 700; display: flex; justify-content: space-between; margin-bottom: 8px; }
  .story-title span, .story-empty, .story-time { color: var(--dna-dim); font-size: 10px; }
  .story-rows { max-height: 250px; overflow: auto; }
  .story-row { display: grid; grid-template-columns: 16px minmax(0,1fr) 30px; width: 100%; gap: 4px; text-align: left; background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 7px 3px; color: var(--dna-text); }
  .story-row.active { background: var(--dna-elevated); border-color: var(--dna-action); }
  .story-row strong { display: block; font-size: 11px; }
  .story-row small { display: block; overflow-wrap: anywhere; font-size: 10px; color: var(--dna-dim); margin-top: 2px; }
  .story-number { color: var(--dna-action); font-variant-numeric: tabular-nums; }
  .story-add, .story-order { display: flex; gap: 6px; margin-top: 8px; }
  .story-fields { display: grid; gap: 7px; margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--dna-border); }
  label { display: grid; gap: 4px; font-size: 11px; color: var(--dna-dim); }
  input, select, textarea { width: 100%; min-width: 0; box-sizing: border-box; background: var(--dna-sunken); color: var(--dna-text); border: 1px solid var(--dna-border); border-radius: 5px; padding: 5px; font: inherit; }
  button { cursor: pointer; background: var(--dna-elevated); color: var(--dna-text); border: 1px solid var(--dna-border); border-radius: 5px; padding: 4px 9px; }
  button:focus-visible { outline: 2px solid var(--dna-action); }
</style>
