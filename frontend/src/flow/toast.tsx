import { useEffect, useState } from "react";

export type ToastKind = "ok" | "error";

type ToastItem = { id: number; msg: string; kind?: ToastKind };

let items: ToastItem[] = [];
let seq = 1;
const listeners = new Set<(list: ToastItem[]) => void>();

function emit() {
  for (const fn of listeners) fn(items);
}

/* Зеркало toast() (nodes.js:53-59): error висит 7 с, остальные 3.5 с */
export function toast(msg: string, kind?: ToastKind) {
  const id = seq++;
  items = [...items, { id, msg, kind }];
  emit();
  setTimeout(() => {
    items = items.filter((t) => t.id !== id);
    emit();
  }, kind === "error" ? 7000 : 3500);
}

/* Контейнер тостов — зеркало #toasts в nodes.html */
export function ToastViewport() {
  const [list, setList] = useState<ToastItem[]>(items);
  useEffect(() => {
    listeners.add(setList);
    setList(items);
    return () => {
      listeners.delete(setList);
    };
  }, []);
  return (
    <div id="toasts">
      {list.map((t) => (
        <div key={t.id} className={"toast" + (t.kind ? " " + t.kind : "")}>
          {t.msg}
        </div>
      ))}
    </div>
  );
}
