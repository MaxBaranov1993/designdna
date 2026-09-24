<script lang="ts">
  import * as ctl from "./controller";
  import { editorUi } from "./state";

  const OPTIONS: Array<{ id: ctl.IntentLock; label: string; hint: string }> = [
    { id: "brand", label: "Brand", hint: "tokens, logo, and brand choices" },
    { id: "content", label: "Content", hint: "text, images, and data" },
    { id: "geometry", label: "Geometry", hint: "dimensions, positions, and axes" },
    { id: "appearance", label: "Appearance", hint: "colors, fonts, radii, and shadows" },
    { id: "responsive", label: "Responsive", hint: "tablet/mobile overrides" },
    { id: "source-link", label: "Source link", hint: "provenance and sourceKey" },
  ];

  const open = $derived($editorUi.intentLocksOpen);
  let locks: ctl.IntentLock[] = $state([]);
  const view = $derived(open ? ctl.getIntentLockView() : { scope: "", locks: [] as ctl.IntentLock[] });

  $effect(() => {
    if (open) locks = view.locks;
  });

  function toggle(id: ctl.IntentLock) {
    locks = locks.includes(id) ? locks.filter((lock) => lock !== id) : [...locks, id];
  }
</script>

{#if open}
  <div
    class="fe-locks-backdrop"
    role="presentation"
    onmousedown={(event) => {
      if (event.target === event.currentTarget) ctl.closeIntentLocks();
    }}
  >
    <div class="fe-locks-card" role="dialog" aria-modal="true" aria-labelledby="locks-title">
      <div class="fe-locks-kicker">Intent Locks · {view.scope}</div>
      <h2 id="locks-title">What should AI preserve?</h2>
      <p>Smart Axis, Harmonizer, Responsive Autopilot, and Quality fixes respect these locks.</p>
      <div class="fe-locks-list">
        {#each OPTIONS as option (option.id)}
          <label class={locks.includes(option.id) ? "active" : ""}>
            <input type="checkbox" checked={locks.includes(option.id)} onchange={() => toggle(option.id)} />
            <span><b>{option.label}</b><small>{option.hint}</small></span>
          </label>
        {/each}
      </div>
      <div class="fe-locks-actions">
        <button class="fe-btn" data-act="dismiss-intent-locks" onclick={() => ctl.closeIntentLocks()}>Cancel</button>
        <button class="fe-btn primary" data-act="apply-intent-locks" onclick={() => ctl.setIntentLocks(locks)}>Save locks</button>
      </div>
    </div>
  </div>
{/if}
