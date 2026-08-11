import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import type { CSSProperties } from "react";
import type { NodeProps } from "@xyflow/react";
import { IrPreview } from "../components/IrPreview";
import { useFlowStore } from "../flow/store";
import type { MotionFlowNode, MotionNodeData, MotionSceneSettings, SourceViewport } from "../flow/types";
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

function MotionWorkspace({ nodeId, data, onClose }: { nodeId: number; data: MotionNodeData; onClose: () => void }) {
  const setNodeData = useFlowStore((state) => state.setNodeData);
  const runNode = useFlowStore((state) => state.runNode);
  const busy = useFlowStore((state) => Boolean(state.busy[nodeId]));
  const scenes = useMemo(() => scenesOf(data), [data.motion]);
  const total = durationOf(data);
  const [playing, setPlaying] = useState(false);
  const [playhead, setPlayhead] = useState(() => scenes[data.selectedScene]?.start || 0);
  const activeIndex = Math.max(0, scenes.findIndex((scene, index) => playhead >= scene.start && (playhead < scene.start + scene.duration || index === scenes.length - 1)));
  const activeScene = scenes[activeIndex];
  const activeSourceId = activeScene?.interactionSceneId || "";
  const preview = previewFor(data, activeScene);

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

  const transition = activeScene?.transition || { type: "cut", duration: 0, easing: "linear" };
  const animationStyle = {
    "--motion-duration": `${transition.duration}ms`,
    "--motion-easing": transition.easing,
  } as CSSProperties;

  return createPortal(
    <div className="motion-workspace" role="dialog" aria-modal="true" aria-label="Motion Editor">
      <header className="motion-topbar">
        <div><strong>Motion Editor</strong><span>{data.composition.width} x {data.composition.height} · {data.composition.fps} fps</span></div>
        <div className="motion-transport">
          <button title="Jump to start" onClick={() => { setPlaying(false); setPlayhead(0); }}>|&lt;</button>
          <button className="primary" onClick={() => { if (playhead >= total) setPlayhead(0); setPlaying((current) => !current); }}>{playing ? "Pause" : "Play"}</button>
          <span>{formatTime(playhead)} / {formatTime(total)}</span>
        </div>
        <button className="motion-close" title="Close Motion Editor" onClick={onClose}>x</button>
      </header>
      <main className="motion-main">
        <section className="motion-stage">
          <div className={`motion-player motion-transition-${transition.type}`} key={activeScene?.id} style={animationStyle}>
            <IrPreview ir={preview} height={540} fitHeight={false} viewport={activeScene?.viewport} empty="Build Motion IR to preview scenes" />
          </div>
        </section>
        <aside className="motion-inspector">
          <div className="motion-panel-title">Composition</div>
          <div className="motion-ratios">
            <button className={data.composition.width > data.composition.height ? "active" : ""} onClick={() => setNodeData(nodeId, { composition: { ...data.composition, width: 1920, height: 1080 } })}>16:9</button>
            <button className={data.composition.height > data.composition.width ? "active" : ""} onClick={() => setNodeData(nodeId, { composition: { ...data.composition, width: 1080, height: 1920 } })}>9:16</button>
            <button className={data.composition.height === data.composition.width ? "active" : ""} onClick={() => setNodeData(nodeId, { composition: { ...data.composition, width: 1080, height: 1080 } })}>1:1</button>
          </div>
          <label>Frame rate<select value={data.composition.fps} onChange={(event) => setNodeData(nodeId, { composition: { ...data.composition, fps: Number(event.target.value) } })}><option value="24">24 fps</option><option value="30">30 fps</option><option value="60">60 fps</option></select></label>
          <div className="motion-panel-title">Scene {activeIndex + 1}</div>
          <label>Duration, ms<input type="number" min="250" max="30000" value={data.sceneSettings[activeSourceId]?.duration ?? activeScene?.duration ?? 1200} onChange={(event) => updateScene({ duration: Number(event.target.value) })} /></label>
          <label>Transition<select value={data.sceneSettings[activeSourceId]?.transition ?? transition.type} onChange={(event) => updateScene({ transition: event.target.value as MotionSceneSettings["transition"] })}><option value="cut">Cut</option><option value="fade">Fade</option><option value="slide-left">Slide left</option><option value="slide-up">Slide up</option><option value="zoom">Zoom</option></select></label>
          <label>Transition, ms<input type="number" min="0" max="30000" value={data.sceneSettings[activeSourceId]?.transitionDuration ?? transition.duration} onChange={(event) => updateScene({ transitionDuration: Number(event.target.value) })} /></label>
          <label>Easing<select value={data.sceneSettings[activeSourceId]?.easing ?? transition.easing} onChange={(event) => updateScene({ easing: event.target.value as MotionSceneSettings["easing"] })}><option value="linear">Linear</option><option value="ease">Ease</option><option value="ease-in">Ease in</option><option value="ease-out">Ease out</option><option value="ease-in-out">Ease in/out</option></select></label>
          <button className="btn-node primary" disabled={busy} onClick={() => runNode(nodeId)}>{busy ? "Applying..." : "Apply timeline"}</button>
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
        <IrPreview ir={preview} height={180} fitHeight empty="Build Motion IR to materialize scenes" />
        <div><span>{scenes.length} scenes</span><span>{(durationOf(data) / 1000).toFixed(1)}s · {data.composition.fps} fps</span></div>
      </div>
      <div className="ctl-row">
        <button className="btn-node primary small nodrag" disabled={busy || !data.ir || !data.interaction} onClick={() => runNode(nodeId)}>{busy ? <span className="spinner" /> : null} Build timeline</button>
        <button className="btn-node small nodrag" disabled={!data.motion} onClick={() => setOpen(true)}>Open editor</button>
      </div>
      {scenes.length > 1 ? <div className="motion-node-scenes nodrag">{scenes.map((item, index) => <button key={item.id} className={index === data.selectedScene ? "active" : ""} onClick={() => setNodeData(nodeId, { selectedScene: index })}>{index + 1}</button>)}</div> : null}
      <NodeStatus id={id} />
      <OutPorts type="motion" data={data} />
      {open ? <MotionWorkspace nodeId={nodeId} data={data} onClose={() => setOpen(false)} /> : null}
    </NodeShell>
  );
}
