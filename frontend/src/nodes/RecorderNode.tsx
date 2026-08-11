import { useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
import type { NodeProps } from "@xyflow/react";
import { IrPreview } from "../components/IrPreview";
import { useFlowStore } from "../flow/store";
import type {
  InteractionDraftEvent,
  InteractionDraftScene,
  IRObject,
  RecorderFlowNode,
} from "../flow/types";
import { NodeShell, NodeStatus } from "./NodeShell";
import { InPorts, OutPorts } from "./PortHandles";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PHONE_RE = /^\+?[\d\s().-]{7,}$/;
const TOKEN_RE = /^(?:bearer\s+)?[a-z0-9_-]{24,}(?:\.[a-z0-9_-]{10,}){0,2}$/i;

function sanitizeTypedValue(value: string): string {
  const trimmed = value.trim();
  if (EMAIL_RE.test(trimmed)) return "[EMAIL]";
  if (PHONE_RE.test(trimmed)) return "[PHONE]";
  if (TOKEN_RE.test(trimmed)) return "[TOKEN]";
  return value;
}

function escapePointer(value: string): string {
  return value.replace(/~/g, "~0").replace(/\//g, "~1");
}

function valueAtPath(root: unknown, path: string): unknown {
  return path.split(".").filter(Boolean).reduce<unknown>((value, part) => {
    if (!value || typeof value !== "object") return undefined;
    return (value as Record<string, unknown>)[part];
  }, root);
}

function valueAtPointer(root: unknown, pointer: string): unknown {
  return pointer.split("/").slice(1).reduce<unknown>((value, part) => {
    if (!value || typeof value !== "object") return undefined;
    const key = part.replace(/~1/g, "/").replace(/~0/g, "~");
    return (value as Record<string, unknown>)[key];
  }, root);
}

function findSourceKey(value: unknown): string {
  if (!value || typeof value !== "object") return "";
  const record = value as Record<string, unknown>;
  if (typeof record.sourceKey === "string") return record.sourceKey;
  return "";
}

function hasOwn(value: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function targetFromPreview(ir: IRObject, target: HTMLElement): { sourceKey: string; path: string } | null {
  const sectionElement = target.closest<HTMLElement>("[data-ir-sec]");
  if (!sectionElement) return null;
  const sectionIndex = Number(sectionElement.dataset.irSec);
  const tree = Array.isArray(ir.tree) ? ir.tree : [];
  const section = tree[sectionIndex] as Record<string, unknown> | undefined;
  if (!section) return null;

  const pathElement = target.closest<HTMLElement>("[data-ir-path]");
  const dotPath = pathElement?.dataset.irPath || "";
  const selected = dotPath ? valueAtPath(section, dotPath) : section;
  const parentPath = dotPath.includes(".") ? dotPath.slice(0, dotPath.lastIndexOf(".")) : "";
  const sourceKey = findSourceKey(selected) || findSourceKey(valueAtPath(section, parentPath)) || findSourceKey(section);
  if (!sourceKey) return null;
  const pointer = ["tree", String(sectionIndex), ...dotPath.split(".").filter(Boolean)]
    .map(escapePointer)
    .join("/");
  return { sourceKey, path: `/${pointer}` };
}

function nextTime(events: InteractionDraftEvent[]): number {
  return events.length ? events[events.length - 1].time + 500 : 0;
}

function upsertPatch(
  patch: InteractionDraftScene["patch"],
  next: InteractionDraftScene["patch"][number],
): InteractionDraftScene["patch"] {
  return [...patch.filter((item) => item.path !== next.path), next];
}

export function RecorderNode({ id, data, selected }: NodeProps<RecorderFlowNode>) {
  const nodeId = Number(id);
  const setNodeData = useFlowStore((state) => state.setNodeData);
  const runNode = useFlowStore((state) => state.runNode);
  const busy = useFlowStore((state) => Boolean(state.busy[nodeId]));
  const [typedValue, setTypedValue] = useState("");
  const [scrollY, setScrollY] = useState("640");
  const currentSceneId = data.draftScenes.at(-1)?.id || "scene-0";

  const appendEvent = (event: Omit<InteractionDraftEvent, "id" | "time">) => {
    const draftEvents = [
      ...data.draftEvents,
      { ...event, id: `event-${data.draftEvents.length + 1}`, time: nextTime(data.draftEvents) },
    ];
    setNodeData(nodeId, { draftEvents, interaction: null });
  };

  const selectTarget = (event: ReactMouseEvent<HTMLDivElement>) => {
    if (!data.ir) return;
    const element = event.target as HTMLElement;
    const target = targetFromPreview(data.ir, element);
    if (!target) return;
    setNodeData(nodeId, { selectedTarget: target.sourceKey, selectedPath: target.path });
    if (data.recording) {
      appendEvent({ type: "click", targetSourceKey: target.sourceKey, payload: {}, resultingSceneId: currentSceneId });
    }
  };

  const addTypeEvent = () => {
    if (!data.selectedTarget || !data.selectedPath || !typedValue) return;
    const safeValue = sanitizeTypedValue(typedValue);
    const nextSceneId = `scene-${data.draftScenes.length}`;
    const previousPatch = data.draftScenes.at(-1)?.patch || [];
    const selectedValue = valueAtPointer(data.ir, data.selectedPath);
    const selectedRecord = selectedValue && typeof selectedValue === "object"
      ? selectedValue as Record<string, unknown>
      : null;
    const property = selectedRecord
      ? (hasOwn(selectedRecord, "value") ? "value" : hasOwn(selectedRecord, "text") ? "text" : "value")
      : "";
    const valuePath = property ? `${data.selectedPath}/${property}` : data.selectedPath;
    const op = selectedRecord && !hasOwn(selectedRecord, property) ? "add" : "replace";
    const scene: InteractionDraftScene = {
      id: nextSceneId,
      viewport: "desktop",
      patch: upsertPatch(previousPatch, { op, path: valuePath, value: safeValue }),
    };
    setNodeData(nodeId, {
      draftScenes: [...data.draftScenes, scene],
      draftEvents: [
        ...data.draftEvents,
        {
          id: `event-${data.draftEvents.length + 1}`,
          time: nextTime(data.draftEvents),
          type: "type",
          targetSourceKey: data.selectedTarget,
          payload: { value: safeValue },
          resultingSceneId: nextSceneId,
        },
      ],
      interaction: null,
    });
    setTypedValue("");
  };

  const addScrollEvent = () => {
    const y = Number(scrollY);
    if (!Number.isFinite(y)) return;
    appendEvent({
      type: "scroll",
      targetSourceKey: data.selectedTarget || "document-root",
      payload: { y },
      resultingSceneId: currentSceneId,
    });
  };

  const reset = () => {
    setTypedValue("");
    setNodeData(nodeId, {
      interaction: null,
      recording: false,
      selectedTarget: "",
      selectedPath: "",
      draftEvents: [],
      draftScenes: [{ id: "scene-0", viewport: "desktop", patch: [] }],
    });
  };

  const privacyReport = data.interaction?.privacyReport as Record<string, unknown> | undefined;
  return (
    <NodeShell id={id} type="recorder" selected={selected}>
      <InPorts type="recorder" />
      <div className="recorder-preview nodrag">
        <IrPreview
          ir={data.ir}
          height={210}
          fitHeight
          interactive
          onClickCapture={selectTarget}
          empty="Connect Design IR to record interactions"
        />
        <div className="recorder-preview-bar">
          <span>{data.selectedTarget || "Click a preview element"}</span>
          <button
            className={`btn-node small ${data.recording ? "recording" : ""}`}
            onClick={() => setNodeData(nodeId, { recording: !data.recording })}
            disabled={!data.ir}
          >
            {data.recording ? "Pause" : "Record"}
          </button>
        </div>
      </div>
      <div className="recorder-tools nodrag">
        <div className="recorder-input-row">
          <input
            type="text"
            value={typedValue}
            placeholder="Type value (PII is redacted)"
            onChange={(event) => setTypedValue(event.target.value)}
          />
          <button className="btn-node small" onClick={addTypeEvent} disabled={!data.selectedTarget || !typedValue}>Type</button>
        </div>
        <div className="recorder-input-row">
          <input type="number" value={scrollY} onChange={(event) => setScrollY(event.target.value)} aria-label="Scroll Y" />
          <button className="btn-node small" onClick={addScrollEvent}>Scroll</button>
        </div>
      </div>
      <div className="recorder-summary">
        <span>{data.draftEvents.length} events</span>
        <span>{data.draftScenes.length} scenes</span>
        {privacyReport ? <span>{Number(privacyReport.sanitizedCount || 0)} redacted</span> : null}
      </div>
      {data.draftEvents.length ? (
        <div className="recorder-events nodrag">
          {data.draftEvents.slice(-4).map((event) => (
            <div key={event.id}><strong>{event.type}</strong><span>{event.targetSourceKey}</span></div>
          ))}
        </div>
      ) : null}
      <div className="ctl-row">
        <button className="btn-node primary small nodrag" disabled={busy || !data.ir} onClick={() => runNode(nodeId)}>
          {busy ? <span className="spinner" /> : null} Build Interaction IR
        </button>
        <button className="btn-node small nodrag" onClick={reset}>Reset</button>
      </div>
      <NodeStatus id={id} />
      <OutPorts type="recorder" data={data} />
    </NodeShell>
  );
}
