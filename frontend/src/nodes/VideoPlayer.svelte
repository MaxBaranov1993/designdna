<script lang="ts">

  /* Встроенный плеер ноды (Weavy: кадр + тайм-код, ⏮ ▶ ⏭, loop). В десктопе
   * ссылка /api/… не играет напрямую (нет HTTP под file://) — тянем через
   * fetch-мост и отдаём blob: URL; в браузере relative URL играет как есть. */
  let { src, label = "видео" }: { src: string; label?: string } = $props();

  let video: HTMLVideoElement | null = $state(null);
  let resolved = $state<string | null>(null);
  let error = $state("");
  let playing = $state(false);
  let loop = $state(false);
  let time = $state(0);
  let duration = $state(0);
  const isDesktop = typeof window !== "undefined" && !!window.designDNA;
  $effect(() => {
    const source = src;
    let alive = true;
    let objectUrl: string | null = null;
    const controller = new AbortController();
    resolved = null; error = ""; playing = false; time = 0; duration = 0;
    (async () => {
      try {
        if (!isDesktop || /^(blob|data):/i.test(source)) { resolved = source; return; }
        const response = await fetch(source, { signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const blob = await response.blob();
        if (!alive) return;
        objectUrl = URL.createObjectURL(blob);
        resolved = objectUrl;
      } catch (reason) {
        if (alive) error = reason instanceof Error ? reason.message : String(reason);
      }
    })();
    return () => {
      alive = false;
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  });

  const fmt = (seconds: number) => {
    const total = Math.max(0, seconds);
    const m = Math.floor(total / 60);
    const s = Math.floor(total % 60);
    const cs = Math.floor((total - Math.floor(total)) * 100);
    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}.${String(cs).padStart(2, "0")}`;
  };
  const toggle = () => {
    if (!video) return;
    if (video.paused) void video.play().catch(reason => { error = String(reason?.message || reason); }); else video.pause();
  };
  const seek = (value: number) => {
    if (video) video.currentTime = value;
  };
</script>

<div class="n-hero n-player">
  {#if error}
    <div class="n-hero-empty">Видео не загрузилось: {error}</div>
  {:else if resolved}
    <!-- svelte-ignore a11y_media_has_caption -->
    <video
      bind:this={video}
      src={resolved}
      playsinline
      preload="metadata"
      {loop}
      aria-label={label}
      onerror={() => { error = video?.error?.message || "Не удалось декодировать видео"; }}
      onplay={() => (playing = true)}
      onpause={() => (playing = false)}
      ontimeupdate={() => (time = video?.currentTime || 0)}
      onloadedmetadata={() => (duration = video?.duration || 0)}
      onclick={toggle}
    ></video>
    <span class="n-hero-tag">{fmt(time)}</span>
  {:else}
    <div class="n-hero-empty">Загрузка видео…</div>
  {/if}
</div>
<div class="n-transport nodrag" role="group" aria-label="Транспорт">
  <button title="В начало" aria-label="В начало" onclick={() => seek(0)}>⏮</button>
  <button class="play" title={playing ? "Пауза (Space)" : "Играть (Space)"} aria-label={playing ? "Пауза" : "Играть"} onclick={toggle}>{playing ? "❚❚" : "▶"}</button>
  <button title="В конец" aria-label="В конец" onclick={() => seek(duration)}>⏭</button>
  <input class="scrub" type="range" min="0" max={duration || 0} step="0.01" value={time} aria-label="Позиция" oninput={(e) => seek(Number(e.currentTarget.value))} />
  <span class="tcode">{fmt(duration)}</span>
  <button class:on={loop} title="Повтор" aria-label="Повтор" aria-pressed={loop} onclick={() => (loop = !loop)}>↻</button>
</div>

<style>
  .n-player video { display: block; width: 100%; max-height: 240px; background: #0d0d0f; cursor: pointer; }
  .n-transport { display: flex; align-items: center; gap: 4px; padding: 4px 6px; border-radius: var(--r-ctl); background: var(--dna-sunken); border: 1px solid var(--dna-border); }
  .n-transport button { width: 22px; height: 22px; flex: none; border: 0; border-radius: 6px; background: transparent; color: var(--dna-text-2); font-size: 10px; cursor: pointer; display: grid; place-items: center; }
  .n-transport button:hover { background: var(--dna-hover); color: var(--dna-text); }
  .n-transport button.play { background: var(--dna-active-bg); color: var(--dna-active-fg); }
  .n-transport button.on { color: var(--dna-text); background: var(--dna-hover); }
  .n-transport .scrub { flex: 1; min-width: 0; height: 3px; accent-color: var(--dna-text); cursor: pointer; }
  .n-transport .tcode { font-size: 10px; font-weight: 600; color: var(--dna-muted); font-variant-numeric: tabular-nums; padding: 0 2px; white-space: nowrap; }
</style>
