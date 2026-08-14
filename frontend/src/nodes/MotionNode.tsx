import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { CSSProperties } from "react";
import type { NodeProps } from "@xyflow/react";
import { IrPreview } from "../components/IrPreview";
import { api, apiGet } from "../flow/api";
import { applyCompPreview, type CompKeyframe, type CompLayer } from "../flow/motionComp";
import { useFlowStore } from "../flow/store";
import type { MotionFlowNode, MotionNodeData, MotionRenderJob, MotionSceneSettings, SourceViewport } from "../flow/types";
import { NodeShell, NodeStatus } from "./NodeShell";
import { InPorts, OutPorts } from "./PortHandles";

type MotionScene = {
  id: string;
  interactionSceneId: string;
  start: number;
  duration: number;
  viewport: SourceViewport;
  transition: {
    type: MotionSceneSettings["transition"];
    duration: number;
    easing: MotionSceneSettings["easing"];
  };
};

function scenesOf(data: MotionNodeData): MotionScene[] {
  return Array.isArray(data.motion?.scenes) ? data.motion.scenes as MotionScene[] : [];
}

function durationOf(data: MotionNodeData): number {
  const composition = data.motion?.composition as Record<string, unknown> | undefined;
  return Number(composition?.duration || 0);
}

function previewFor(data: MotionNodeData, scene: MotionScene | undefined) {
  if (!scene) return null;
  return data.sceneIrs.find((item) => item.sceneId === scene.id)?.ir || null;
}

function formatTime(milliseconds: number): string {
  const seconds = Math.max(0, milliseconds) / 1000;
  return `${Math.floor(seconds / 60)}:${(seconds % 60).toFixed(1).padStart(4, "0")}`;
}

function formatBytes(bytes = 0): string {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`;
}

function layersOf(data: MotionNodeData): CompLayer[] {
  return Array.isArray(data.motion?.layers) ? data.motion.layers as CompLayer[] : [];
}

function MotionWorkspace({ nodeId, data, onClose }: { nodeId: number; data: MotionNodeData; onClose: () => void }) {
  const setNodeData = useFlowStore((state) => state.setNodeData);
  const runNode = useFlowStore((state) => state.runNode);
  const busy = useFlowStore((state) => Boolean(state.busy[nodeId]));
  const scenes = useMemo(() => scenesOf(data), [data.motion]);
  const layers = useMemo(() => layersOf(data), [data.motion]);
  const isComp = layers.length > 0;
  const total = durationOf(data);
  const [playing, setPlaying] = useState(false);
  const [playhead, setPlayhead] = useState(() => scenes[data.selectedScene]?.start || 0);
  const [inspectorOpen, setInspectorOpen] = useState(() => window.innerWidth > 760);
  const [prompt, setPrompt] = useState(data.prompt || "");
  const previewHost = useRef<HTMLDivElement>(null);
  const activeIndex = Math.max(0, scenes.findIndex((scene, index) => playhead >= scene.start && (playhead < scene.start + scene.duration || index === scenes.length - 1)));
  const activeScene = scenes[activeIndex];
  const activeSourceId = activeScene?.interactionSceneId || "";
  const preview = isComp ? data.ir : previewFor(data, activeScene);
  const selectedLayer = layers[Math.min(data.selectedLayer || 0, Math.max(0, layers.length - 1))] || null;
  const renderSettings = data.renderSettings || { format: "mp4" as const, quality: "high" as const };
  const renderJob = data.renderJob;
  const rendering = renderJob?.status === "queued" || renderJob?.status === "rendering";

  useEffect(() => {
    applyCompPreview(previewHost.current, isComp ? data.motion : null, playhead);
  }, [data.motion, isComp, playhead, preview]);

  useEffect(() => {
    if (!playing || total <= 0) return;
    let previous = performance.now();
    const timer = window.setInterval(() => {
      const now = performance.now();
      const delta = now - previous;
      previous = now;
      setPlayhead((current) => {
        const next = current + delta;
        if (next >= total) {
          setPlaying(false);
          return total;
        }
        return next;
      });
    }, 40);
    return () => window.clearInterval(timer);
  }, [playing, total]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.code === "Space" && !event.repeat) {
        event.preventDefault();
        if (playhead >= total) setPlayhead(0);
        setPlaying((current) => !current);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, playhead, total]);

  const selectScene = (index: number) => {
    const scene = scenes[index];
    if (!scene) return;
    setPlaying(false);
    setPlayhead(scene.start);
    setNodeData(nodeId, { selectedScene: index });
  };

  const updateScene = (patch: Partial<MotionSceneSettings>) => {
    if (!activeScene) return;
    const current = data.sceneSettings[activeScene.interactionSceneId] || {};
    setNodeData(nodeId, {
      sceneSettings: {
        ...data.sceneSettings,
        [activeScene.interactionSceneId]: { ...current, ...patch },
      },
    });
  };

  const patchLayer = (layerId: string, keyframes: CompKeyframe[]) => {
    if (!data.motion) return;
    const nextLayers = layers.map((layer) => layer.id === layerId ? { ...layer, keyframes } : layer);
    const duration = Math.max(800, ...nextLayers.flatMap((layer) => layer.keyframes.map((frame) => frame.t)), 0) + 400;
    const motion = {
      ...data.motion,
      layers: nextLayers,
      composition: { ...(data.motion.composition as object), duration },
      scenes: (data.motion.scenes as MotionScene[]).map((scene, index) => index === 0 ? { ...scene, duration } : scene),
    };
    setNodeData(nodeId, { motion });
  };

  const startRender = async () => {
    if (!data.ir || !data.motion || rendering) return;
    if (!isComp && !data.interaction) return;
    try {
      let job = await api<MotionRenderJob>("/api/motion/render", {
        base_ir: data.ir,
        interaction: isComp ? null : data.interaction,
        motion: data.motion,
      });
      setNodeData(nodeId, { renderJob: job });
      while (job.status === "queued" || job.status === "rendering") {
        await new Promise((resolve) => window.setTimeout(resolve, 400));
        job = await apiGet<MotionRenderJob>(`/api/motion/render/${job.id}`);
        setNodeData(nodeId, { renderJob: job });
      }
    } catch (error) {
      setNodeData(nodeId, {
        renderJob: {
          id: renderJob?.id || "failed",
          status: "error",
          progress: 0,
          error: error instanceof Error ? error.message : String(error),
        },
      });
    }
  };

  const transition = activeScene?.transition || { type: "cut", duration: 0, easing: "linear" };
  const animationStyle = {
    "--motion-duration": `${transition.duration}ms`,
    "--motion-easing": transition.easing,
  } as CSSProperties;

  return createPortal(
    <div className="motion-workspace" role="dialog" aria-modal="true" aria-label="Motion Editor">
      <header className="motion-topbar">
        <div><strong>Ролик</strong><span>{data.composition.width} x {data.composition.height} · {data.composition.fps} fps</span></div>
        <div className="motion-transport">
          <button title="Jump to start" onClick={() => { setPlaying(false); setPlayhead(0); }}>|&lt;</button>
          <button className="primary" onClick={() => { if (playhead >= total) setPlayhead(0); setPlaying((current) => !current); }}>{playing ? "Pause" : "Play"}</button>
          <span>{formatTime(playhead)} / {formatTime(total)}</span>
        </div>
        <div className="motion-actions">
          {rendering ? <span className="motion-render-progress">Rendering {renderJob?.progress || 0}%</span> : null}
          {renderJob?.status === "complete" && renderJob.downloadUrl ? <a className="motion-download" href={renderJob.downloadUrl} download={renderJob.filename}><span className="motion-desktop-label">Download {renderJob.result?.bytes ? formatBytes(renderJob.result.bytes) : "video"}</span><span className="motion-mobile-label">Save</span></a> : null}
          <button className="motion-export" disabled={busy || rendering || !data.motion} onClick={startRender}>{rendering ? "Exporting..." : `Export ${renderSettings.format.toUpperCase()}`}</button>
          <button className="motion-inspector-toggle" onClick={() => setInspectorOpen((current) => !current)}>{inspectorOpen ? "Canvas" : "Inspector"}</button>
          <button className="motion-close" title="Close Motion Editor" onClick={onClose}>x</button>
        </div>
      </header>
      <main className="motion-main">
        <section className="motion-stage">
          <div className={`motion-player motion-transition-${transition.type}`} key={isComp ? "comp" : activeScene?.id} style={animationStyle} ref={previewHost}>
            <IrPreview ir={preview} height={540} fitHeight={false} viewport={activeScene?.viewport} empty="Соберите композицию из страницы" />
          </div>
        </section>
        <aside className={`motion-inspector ${inspectorOpen ? "open" : ""}`}>
          {isComp ? (
            <>
              <div className="motion-panel-title">Нейросеть</div>
              <textarea
                className="motion-prompt"
                value={prompt}
                placeholder="Например: продуктовый ролик 9:16, hero выезжает снизу, карточки появляются по очереди, камера медленно едет вниз"
                onChange={(event) => setPrompt(event.target.value)}
              />
              <button
                className="btn-node primary"
                disabled={busy || !data.ir}
                onClick={() => { setNodeData(nodeId, { prompt }); runNode(nodeId); }}
              >
                {busy ? "Собираю..." : prompt.trim() ? "Собрать с AI" : "Собрать из секций"}
              </button>
              <div className="motion-panel-title">Слои</div>
              <div className="motion-layer-list">
                {layers.map((layer, index) => (
                  <button
                    key={layer.id}
                    className={layer.id === selectedLayer?.id ? "active" : ""}
                    onClick={() => setNodeData(nodeId, { selectedLayer: index })}
                  >
                    {layer.name}
                  </button>
                ))}
              </div>
              {selectedLayer ? (
                <>
                  <div className="motion-panel-title">Кейфреймы · {selectedLayer.name}</div>
                  {selectedLayer.keyframes.map((frame, index) => (
                    <div className="motion-kf" key={`${selectedLayer.id}-${index}`}>
                      <label>t ms<input type="number" value={frame.t} onChange={(event) => {
                        const next = selectedLayer.keyframes.map((item, itemIndex) => itemIndex === index ? { ...item, t: Number(event.target.value) } : item);
                        patchLayer(selectedLayer.id, next);
                      }} /></label>
                      <label>Y<input type="number" value={frame.y ?? 0} onChange={(event) => {
                        const next = selectedLayer.keyframes.map((item, itemIndex) => itemIndex === index ? { ...item, y: Number(event.target.value) } : item);
                        patchLayer(selectedLayer.id, next);
                      }} /></label>
                      <label>Opacity<input type="number" min="0" max="1" step="0.05" value={frame.opacity ?? 1} onChange={(event) => {
                        const next = selectedLayer.keyframes.map((item, itemIndex) => itemIndex === index ? { ...item, opacity: Number(event.target.value) } : item);
                        patchLayer(selectedLayer.id, next);
                      }} /></label>
                      <label>Scale<input type="number" min="0.1" max="3" step="0.02" value={frame.scale ?? 1} onChange={(event) => {
                        const next = selectedLayer.keyframes.map((item, itemIndex) => itemIndex === index ? { ...item, scale: Number(event.target.value) } : item);
                        patchLayer(selectedLayer.id, next);
                      }} /></label>
                    </div>
                  ))}
                  <button className="btn-node small" onClick={() => patchLayer(selectedLayer.id, [...selectedLayer.keyframes, { t: Math.round(playhead), opacity: 1, x: 0, y: 0, scale: 1, rotate: 0 }])}>+ кадр на playhead</button>
                </>
              ) : null}
            </>
          ) : null}
          <div className="motion-panel-title">Composition</div>
          <div className="motion-ratios">
            <button className={data.composition.width > data.composition.height ? "active" : ""} onClick={() => setNodeData(nodeId, { composition: { ...data.composition, width: 1920, height: 1080 } })}>16:9</button>
            <button className={data.composition.height > data.composition.width ? "active" : ""} onClick={() => setNodeData(nodeId, { composition: { ...data.composition, width: 1080, height: 1920 } })}>9:16</button>
            <button className={data.composition.height === data.composition.width ? "active" : ""} onClick={() => setNodeData(nodeId, { composition: { ...data.composition, width: 1080, height: 1080 } })}>1:1</button>
          </div>
          <label>Frame rate<select value={data.composition.fps} onChange={(event) => setNodeData(nodeId, { composition: { ...data.composition, fps: Number(event.target.value) } })}><option value="24">24 fps</option><option value="30">30 fps</option><option value="60">60 fps</option></select></label>
          <label>Format<select value={renderSettings.format} onChange={(event) => setNodeData(nodeId, { renderSettings: { ...renderSettings, format: event.target.value as "mp4" | "webm" }, renderJob: null })}><option value="mp4">MP4 / H.264</option><option value="webm">WebM / VP9</option></select></label>
          <label>Quality<select value={renderSettings.quality} onChange={(event) => setNodeData(nodeId, { renderSettings: { ...renderSettings, quality: event.target.value as "draft" | "high" | "lossless" }, renderJob: null })}><option value="draft">Draft</option><option value="high">High</option><option value="lossless">Lossless</option></select></label>
          {renderJob?.status === "error" ? <div className="motion-render-error">{renderJob.error || "Render failed"}</div> : null}
          <div className="motion-panel-title">Scene {activeIndex + 1}</div>
          <label>Duration, ms<input type="number" min="250" max="30000" value={data.sceneSettings[activeSourceId]?.duration ?? activeScene?.duration ?? 1200} onChange={(event) => updateScene({ duration: Number(event.target.value) })} /></label>
          <label>Transition<select value={data.sceneSettings[activeSourceId]?.transition ?? transition.type} onChange={(event) => updateScene({ transition: event.target.value as MotionSceneSettings["transition"] })}><option value="cut">Cut</option><option value="fade">Fade</option><option value="slide-left">Slide left</option><option value="slide-up">Slide up</option><option value="zoom">Zoom</option></select></label>
          <label>Transition, ms<input type="number" min="0" max="30000" value={data.sceneSettings[activeSourceId]?.transitionDuration ?? transition.duration} onChange={(event) => updateScene({ transitionDuration: Number(event.target.value) })} /></label>
          <label>Easing<select value={data.sceneSettings[activeSourceId]?.easing ?? transition.easing} onChange={(event) => updateScene({ easing: event.target.value as MotionSceneSettings["easing"] })}><option value="linear">Linear</option><option value="ease">Ease</option><option value="ease-in">Ease in</option><option value="ease-out">Ease out</option><option value="ease-in-out">Ease in/out</option></select></label>
          {isComp ? null : <button className="btn-node primary" disabled={busy} onClick={() => runNode(nodeId)}>{busy ? "Applying..." : "Apply timeline"}</button>}
        </aside>
      </main>
      <footer className="motion-timeline">
        <div className="motion-timebar"><input aria-label="Motion playhead" type="range" min="0" max={Math.max(1, total)} step="10" value={Math.min(playhead, total)} onChange={(event) => { setPlaying(false); setPlayhead(Number(event.target.value)); }} /></div>
        <div className="motion-track-row">
          <div className="motion-track-name"><strong>Scenes</strong><span>{scenes.length} clips</span></div>
          <div className="motion-clips">
            {scenes.map((scene, index) => <button key={scene.id} className={index === activeIndex ? "active" : ""} style={{ flexGrow: scene.duration }} onClick={() => selectScene(index)}><strong>{index + 1}</strong><span>{(scene.duration / 1000).toFixed(1)}s</span></button>)}
            <i className="motion-playhead" style={{ left: `${total ? (playhead / total) * 100 : 0}%` }} />
          </div>
        </div>
      </footer>
    </div>,
    document.body,
  );
}

export function MotionNode({ id, data, selected }: NodeProps<MotionFlowNode>) {
  const nodeId = Number(id);
  const runNode = useFlowStore((state) => state.runNode);
  const setNodeData = useFlowStore((state) => state.setNodeData);
  const busy = useFlowStore((state) => Boolean(state.busy[nodeId]));
  const [open, setOpen] = useState(false);
  const scenes = scenesOf(data);
  const scene = scenes[data.selectedScene || 0];
  const preview = previewFor(data, scene);
  return (
    <NodeShell id={id} type="motion" selected={selected}>
      <InPorts type="motion" />
      <div className="motion-node-preview nodrag">
        <IrPreview ir={preview || data.ir} height={180} fitHeight empty="Подключите страницу — соберём композицию из блоков" />
        <div><span>{layersOf(data).length ? `${layersOf(data).length} слоёв` : `${scenes.length} scenes`}</span><span>{(durationOf(data) / 1000).toFixed(1)}s · {data.composition.fps} fps</span></div>
      </div>
      <div className="ctl-row">
        <button className="btn-node primary small nodrag" disabled={busy || !data.ir} onClick={() => runNode(nodeId)}>{busy ? <span className="spinner" /> : null} Собрать</button>
        <button className="btn-node small nodrag" disabled={!data.motion} onClick={() => setOpen(true)} aria-label="Open editor">Открыть</button>
      </div>
      {scenes.length > 1 ? <div className="motion-node-scenes nodrag">{scenes.map((item, index) => <button key={item.id} className={index === data.selectedScene ? "active" : ""} onClick={() => setNodeData(nodeId, { selectedScene: index })}>{index + 1}</button>)}</div> : null}
      <NodeStatus id={id} />
      <OutPorts type="motion" data={data} />
      {open ? <MotionWorkspace nodeId={nodeId} data={data} onClose={() => setOpen(false)} /> : null}
    </NodeShell>
  );
}
