import type { IRObject, TimelineNodeData, VideoRevision, VideoRevisionChange } from "./types";

const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value));
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** Append-only branches. Checkpoint manual work before AI or restoration. */
export function videoHistoryPatch(
  data: TimelineNodeData, next: IRObject, change?: VideoRevisionChange,
): Pick<TimelineNodeData, "revisions" | "activeRevisionId"> {
  if (!change) return {};
  const revisions = [...(data.revisions || [])];
  let parentId = data.activeRevisionId || null;
  const current = revisions.find((item) => item.id === parentId);
  const append = (timeline: IRObject, details: VideoRevisionChange) => {
    const entry: VideoRevision = {
      ...details, id: crypto.randomUUID(), parentId, createdAt: new Date().toISOString(),
      sourceIr: copy(data.ir), timeline: copy(timeline),
    };
    revisions.push(entry);
    parentId = entry.id;
  };
  if (data.timeline && (!current || !same(current.timeline, data.timeline) || !same(current.sourceIr, data.ir))) {
    append(data.timeline, { kind: current ? "manual" : "initial", label: current ? "Ручные правки" : "Исходный монтаж" });
  }
  if (change.restoredFrom) {
    const target = revisions.find((item) => item.id === change.restoredFrom);
    const sourcePages = (data.sourcePages || []).map(({ id, ir }) => ({ id, ir }));
    const targetPages = ((target?.timeline as any)?.story?.pages || []).map(({ id, ir }: any) => ({ id, ir }));
    if (!target || !same(target.sourceIr, data.ir) || !same(target.timeline, next) || (targetPages.length > 0 && !same(targetPages, sourcePages))) {
      throw new Error("Версия относится к другой исходной странице. Подключите прежнюю страницу перед восстановлением.");
    }
    parentId = target.id;
  }
  append(next, change);
  return { revisions, activeRevisionId: parentId };
}


/** Preserve the current montage before replacing any connected source page. */
export function videoSourceCheckpoint(data: TimelineNodeData): Pick<TimelineNodeData, "revisions" | "activeRevisionId"> {
  if (!data.timeline) return {};
  const revisions = data.revisions || [];
  const current = revisions.find((entry) => entry.id === data.activeRevisionId);
  if (current && same(current.timeline, data.timeline) && same(current.sourceIr, data.ir)) return {};
  const entry: VideoRevision = {
    id: crypto.randomUUID(), parentId: data.activeRevisionId || null, createdAt: new Date().toISOString(),
    kind: "manual", label: "Монтаж перед изменением страниц", sourceIr: copy(data.ir), timeline: copy(data.timeline),
  };
  return { revisions: [...revisions, entry], activeRevisionId: entry.id };
}
