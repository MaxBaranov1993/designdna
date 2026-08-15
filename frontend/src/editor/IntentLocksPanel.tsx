import { useEffect, useState } from "react";
import * as ctl from "./controller";
import { useEditorStore } from "./store";

const OPTIONS: Array<{ id: ctl.IntentLock; label: string; hint: string }> = [
  { id: "brand", label: "Бренд", hint: "токены, логотип и фирменные решения" },
  { id: "content", label: "Контент", hint: "тексты, изображения и данные" },
  { id: "geometry", label: "Геометрия", hint: "размеры, позиции и оси" },
  { id: "appearance", label: "Внешний вид", hint: "цвета, шрифты, радиусы и тени" },
  { id: "responsive", label: "Адаптив", hint: "tablet/mobile overrides" },
  { id: "source-link", label: "Связь с источником", hint: "provenance и sourceKey" },
];

export function IntentLocksPanel() {
  const open = useEditorStore((state) => state.intentLocksOpen);
  const [locks, setLocks] = useState<ctl.IntentLock[]>([]);
  const view = open ? ctl.getIntentLockView() : { scope: "", locks: [] as ctl.IntentLock[] };
  useEffect(() => { if (open) setLocks(view.locks); }, [open]);
  if (!open) return null;
  const toggle = (id: ctl.IntentLock) => setLocks((current) => current.includes(id) ? current.filter((lock) => lock !== id) : [...current, id]);
  return (
    <div className="fe-locks-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) ctl.closeIntentLocks(); }}>
      <section className="fe-locks-card" role="dialog" aria-modal="true" aria-labelledby="locks-title">
        <div className="fe-locks-kicker">Intent Locks · {view.scope}</div>
        <h2 id="locks-title">Что AI не должен менять?</h2>
        <p>Блокировки соблюдают Smart Axis, Harmonizer, Responsive Autopilot и Quality fixes.</p>
        <div className="fe-locks-list">{OPTIONS.map((option) => (
          <label key={option.id} className={locks.includes(option.id) ? "active" : ""}>
            <input type="checkbox" checked={locks.includes(option.id)} onChange={() => toggle(option.id)} />
            <span><b>{option.label}</b><small>{option.hint}</small></span>
          </label>
        ))}</div>
        <div className="fe-locks-actions">
          <button className="fe-btn" onClick={() => ctl.closeIntentLocks()}>Отмена</button>
          <button className="fe-btn primary" data-act="apply-intent-locks" onClick={() => ctl.setIntentLocks(locks)}>Сохранить блокировки</button>
        </div>
      </section>
    </div>
  );
}
