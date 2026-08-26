<script lang="ts">
  import IrPreview from "../components/IrPreview.svelte";
  import { api, apiGet } from "../flow/api";
  import { flow, flowBusy } from "../flow/state";
  import { bodyPortal } from "../lib/bodyPortal";
  import type { MotionNodeData, MotionRenderJob, MotionSceneSettings } from "../flow/types";
  import { durationOf, previewFor, scenesOf } from "./motion-utils";

  function formatTime(milliseconds: number): string {
    const seconds = Math.max(0, milliseconds) / 1000;
    return `${Math.floor(seconds / 60)}:${(seconds % 60).toFixed(1).padStart(4, "0")}`;
  }

  function formatBytes(bytes = 0): string {
    return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`;
  }

  let { nodeId, data, onClose }: { nodeId: number; data: MotionNodeData; onClose: () => void } = $props();

  let busy = $derived(Boolean($flowBusy[nodeId]));
  let scenes = $derived(scenesOf(data));
  let total = $derived(durationOf(data));
  let playing = $state(false);
  let playhead = $state(0);
  let playheadInitialized = false;
  let inspectorOpen = $state(window.innerWidth > 760);
  let activeIndex = $derived(
    Math.max(0, scenes.findIndex((scene, index) => playhead >= scene.start && (playhead < scene.start + scene.duration || index === scenes.length - 1))),
  );
  let activeScene = $derived(scenes[activeIndex]);
  let activeSourceId = $derived(activeScene?.interactionSceneId || "");
  let preview = $derived(previewFor(data, activeScene));
  let renderSettings = $derived(data.renderSettings || { format: "mp4" as const, quality: "high" as const });
  let renderJob = $derived(data.renderJob);
  let rendering = $derived(renderJob?.status === "queued" || renderJob?.status === "rendering");
  // Desktop: якорь href="/api/.../download" под file:// не работает (нет HTTP и
  // навигация закрыта политикой) — качаем через IPC и системный диалог сохранения.
  const desktopFiles = typeof window !== "undefined" ? window.designDNA?.files : undefined;
  const downloadVideo = async () => {
    if (!renderJob?.downloadUrl || !desktopFiles) return;
    const resp = await fetch(renderJob.downloadUrl);
    if (!resp.ok) return;
    const buf = new Uint8Array(await resp.arrayBuffer());
    let binary = "";
    for (let i = 0; i < buf.length; i += 32_768) binary += String.fromCharCode(...buf.subarray(i, i + 32_768));
    await desktopFiles.save(renderJob.filename || "motion.mp4", btoa(binary));
  };
  let transition = $derived(activeScene?.transition || { type: "cut" as const, duration: 0, easing: "linear" as const });

  $effect(() => {
    if (playheadInitialized) return;
    playhead = scenes[data.selectedScene]?.start || 0;
    playheadInitialized = true;
  });

  $effect(() => {
    if (!playing || total <= 0) return;
    let previous = performance.now();
    const timer = window.setInterval(() => {
      const now = performance.now();
      const delta = now - previous;
      previous = now;
      const next = playhead + delta;
      if (next >= total) {
        playing = false;
        playhead = total;
      } else {
        playhead = next;
      }
    }, 40);
    return () => window.clearInterval(timer);
  });

  $effect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.code === "Space" && !event.repeat) {
        event.preventDefault();
        if (playhead >= total) playhead = 0;
        playing = !playing;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const selectScene = (index: number) => {
    const scene = scenes[index];
    if (!scene) return;
    playing = false;
    playhead = scene.start;
    $flow.setNodeData(nodeId, { selectedScene: index });
  };

  const updateScene = (patch: Partial<MotionSceneSettings>) => {
    if (!activeScene) return;
    const current = data.sceneSettings[activeScene.interactionSceneId] || {};
    $flow.setNodeData(nodeId, {
      sceneSettings: {
        ...data.sceneSettings,
        [activeScene.interactionSceneId]: { ...current, ...patch },
      },
    });
  };

  const startRender = async () => {
    if (!data.ir || !data.interaction || !data.motion || rendering) return;
    try {
      let job = await api<MotionRenderJob>("/api/motion/render", {
        base_ir: data.ir,
        interaction: data.interaction,
        motion: data.motion,
      });
      $flow.setNodeData(nodeId, { renderJob: job });
      while (job.status === "queued" || job.status === "rendering") {
        await new Promise((resolve) => window.setTimeout(resolve, 400));
        job = await apiGet<MotionRenderJob>(`/api/motion/render/${job.id}`);
        $flow.setNodeData(nodeId, { renderJob: job });
      }
    } catch (error) {
      $flow.setNodeData(nodeId, {
        renderJob: {
          id: renderJob?.id || "failed",
          status: "error",
          progress: 0,
          error: error instanceof Error ? error.message : String(error),
        },
      });
    }
  };
</script>

<div class="motion-workspace" role="dialog" aria-modal="true" aria-label="Motion Editor" use:bodyPortal>
  <header class="motion-topbar">
    <div><strong>Motion Editor</strong><span>{data.composition.width} x {data.composition.height} · {data.composition.fps} fps</span></div>
    <div class="motion-transport">
      <button title="Jump to start" onclick={() => { playing = false; playhead = 0; }}>|&lt;</button>
      <button class="primary" onclick={() => { if (playhead >= total) playhead = 0; playing = !playing; }}>{playing ? "Pause" : "Play"}</button>
      <span>{formatTime(playhead)} / {formatTime(total)}</span>
    </div>
    <div class="motion-actions">
      {#if rendering}<span class="motion-render-progress">Rendering {renderJob?.progress || 0}%</span>{/if}
      {#if renderJob?.status === "complete" && renderJob.downloadUrl}
        {#if desktopFiles}
          <button class="motion-download" onclick={downloadVideo}><span class="motion-desktop-label">Download {renderJob.result?.bytes ? formatBytes(renderJob.result.bytes) : "video"}</span><span class="motion-mobile-label">Save</span></button>
        {:else}
          <a class="motion-download" href={renderJob.downloadUrl} download={renderJob.filename}><span class="motion-desktop-label">Download {renderJob.result?.bytes ? formatBytes(renderJob.result.bytes) : "video"}</span><span class="motion-mobile-label">Save</span></a>
        {/if}
      {/if}
      <button class="motion-export" disabled={busy || rendering || !data.motion} onclick={startRender}>{rendering ? "Exporting..." : `Export ${renderSettings.format.toUpperCase()}`}</button>
      <button class="motion-inspector-toggle" onclick={() => (inspectorOpen = !inspectorOpen)}>{inspectorOpen ? "Canvas" : "Inspector"}</button>
      <button class="motion-close" title="Close Motion Editor" onclick={onClose}>x</button>
    </div>
  </header>
  <main class="motion-main">
    <section class="motion-stage">
      {#key activeScene?.id}
        <div
          class={`motion-player motion-transition-${transition.type}`}
          style="--motion-duration: {transition.duration}ms; --motion-easing: {transition.easing};"
        >
          <IrPreview ir={preview} height={540} fitHeight={false} viewport={activeScene?.viewport} empty="Build Motion IR to preview scenes" />
        </div>
      {/key}
    </section>
    <aside class={`motion-inspector ${inspectorOpen ? "open" : ""}`}>
      <div class="motion-panel-title">Composition</div>
      <div class="motion-ratios">
        <button class={data.composition.width > data.composition.height ? "active" : ""} onclick={() => $flow.setNodeData(nodeId, { composition: { ...data.composition, width: 1920, height: 1080 } })}>16:9</button>
        <button class={data.composition.height > data.composition.width ? "active" : ""} onclick={() => $flow.setNodeData(nodeId, { composition: { ...data.composition, width: 1080, height: 1920 } })}>9:16</button>
        <button class={data.composition.height === data.composition.width ? "active" : ""} onclick={() => $flow.setNodeData(nodeId, { composition: { ...data.composition, width: 1080, height: 1080 } })}>1:1</button>
      </div>
      <label>Frame rate<select value={data.composition.fps} onchange={(event) => $flow.setNodeData(nodeId, { composition: { ...data.composition, fps: Number(event.currentTarget.value) } })}><option value="24">24 fps</option><option value="30">30 fps</option><option value="60">60 fps</option></select></label>
      <label>Format<select value={renderSettings.format} onchange={(event) => $flow.setNodeData(nodeId, { renderSettings: { ...renderSettings, format: event.currentTarget.value as "mp4" | "webm" }, renderJob: null })}><option value="mp4">MP4 / H.264</option><option value="webm">WebM / VP9</option></select></label>
      <label>Quality<select value={renderSettings.quality} onchange={(event) => $flow.setNodeData(nodeId, { renderSettings: { ...renderSettings, quality: event.currentTarget.value as "draft" | "high" | "lossless" }, renderJob: null })}><option value="draft">Draft</option><option value="high">High</option><option value="lossless">Lossless</option></select></label>
      {#if renderJob?.status === "error"}<div class="motion-render-error">{renderJob.error || "Render failed"}</div>{/if}
      <div class="motion-panel-title">Scene {activeIndex + 1}</div>
      <label>Duration, ms<input type="number" min="250" max="30000" value={data.sceneSettings[activeSourceId]?.duration ?? activeScene?.duration ?? 1200} oninput={(event) => updateScene({ duration: Number(event.currentTarget.value) })} /></label>
      <label>Transition<select value={data.sceneSettings[activeSourceId]?.transition ?? transition.type} onchange={(event) => updateScene({ transition: event.currentTarget.value as MotionSceneSettings["transition"] })}><option value="cut">Cut</option><option value="fade">Fade</option><option value="slide-left">Slide left</option><option value="slide-up">Slide up</option><option value="zoom">Zoom</option></select></label>
      <label>Transition, ms<input type="number" min="0" max="30000" value={data.sceneSettings[activeSourceId]?.transitionDuration ?? transition.duration} oninput={(event) => updateScene({ transitionDuration: Number(event.currentTarget.value) })} /></label>
      <label>Easing<select value={data.sceneSettings[activeSourceId]?.easing ?? transition.easing} onchange={(event) => updateScene({ easing: event.currentTarget.value as MotionSceneSettings["easing"] })}><option value="linear">Linear</option><option value="ease">Ease</option><option value="ease-in">Ease in</option><option value="ease-out">Ease out</option><option value="ease-in-out">Ease in/out</option></select></label>
      <button class="btn-node primary" disabled={busy} onclick={() => $flow.runNode(nodeId)}>{busy ? "Applying..." : "Apply timeline"}</button>
    </aside>
  </main>
  <footer class="motion-timeline">
    <div class="motion-timebar"><input aria-label="Motion playhead" type="range" min="0" max={Math.max(1, total)} step="10" value={Math.min(playhead, total)} oninput={(event) => { playing = false; playhead = Number(event.currentTarget.value); }} /></div>
    <div class="motion-track-row">
      <div class="motion-track-name"><strong>Scenes</strong><span>{scenes.length} clips</span></div>
      <div class="motion-clips">
        {#each scenes as scene, index (scene.id)}
          <button class={index === activeIndex ? "active" : ""} style="flex-grow: {scene.duration}" onclick={() => selectScene(index)}><strong>{index + 1}</strong><span>{(scene.duration / 1000).toFixed(1)}s</span></button>
        {/each}
        <i class="motion-playhead" style="left: {total ? (playhead / total) * 100 : 0}%"></i>
      </div>
    </div>
  </footer>
</div>
