import { useMemo, useState } from "react";
import * as ctl from "./controller";
import { useEditorStore } from "./store";
import type { AssistAction, AssistRequest, AssistViewport } from "./aiTypes";

const QUICK_ACTIONS: { action: AssistAction; label: string; prompt: string }[] = [
  { action: "adapt", label: "Сделать адаптивным", prompt: "Сделай layout адаптивным для tablet и mobile, не меняя структуру." },
  { action: "overflow", label: "Убрать переполнение", prompt: "Убери переполнение за границы viewport, сохранив визуальную иерархию." },
  { action: "content-fit", label: "Подогнать под контент", prompt: "Подгони размеры и отступы под содержимое без изменения структуры." },
  { action: "align", label: "Выровнять", prompt: "Выровняй выделенные элементы по ближайшему контейнеру." },
  { action: "accessibility", label: "Улучшить доступность", prompt: "Улучши доступность визуальных элементов, не меняя структуру." },
  { action: "rename-layers", label: "Переименовать слои", prompt: "Дай слоям короткие семантические имена по их роли." },
  { action: "style", label: "Изменить стиль", prompt: "Сделай стиль более цельным и сохрани существующую композицию." },
];

const PROPERTY_LABELS: Record<string, string> = {
  width: "Ширина",
  height: "Высота",
  gap: "Расстояние",
  padding: "Внутренние отступы",
  direction: "Направление layout",
  wrap: "Перенос элементов",
  align: "Выравнивание",
  justify: "Распределение",
  text: "Текст",
  name: "Название слоя",
  style: "Стиль",
  frame: "Размер и layout",
};

function describeOp(path: string, reason?: string) {
  if (reason) return reason;
  const leaf = path.split("/").filter(Boolean).at(-1) || "property";
  return PROPERTY_LABELS[leaf] || "Настройка элемента";
}

export function AiAssistPanel() {
  const aiOpen = useEditorStore((s) => s.aiOpen);
  const busy = useEditorStore((s) => s.aiBusy);
  const error = useEditorStore((s) => s.aiError);
  const preview = useEditorStore((s) => s.aiPreview);
  const tick = useEditorStore((s) => s.inspectorTick);
  const [prompt, setPrompt] = useState("");
  const [viewport, setViewport] = useState<AssistViewport>("current");
  const selectionCount = useMemo(() => ctl.getSession()?.sel.length || 0, [tick, aiOpen]);

  const run = (request: AssistRequest) => { void ctl.requestAiAssist(request); };

  return (
    <aside className={`fe-ai-panel${aiOpen ? " open" : ""}`} id="feAiPanel" aria-hidden={!aiOpen}>
      <div className="fe-ai-head">
        <div>
          <h3>AI‑ассистент</h3>
          <span className="fe-ai-subtitle">Preview → Apply</span>
        </div>
        <button className="fe-tbtn" data-act="close-ai" title="Закрыть" onClick={ctl.closeAiPanel}>×</button>
      </div>

      <div className="fe-ai-body">
        <div className="fe-ai-context">
          <span>{selectionCount ? `Выделено: ${selectionCount}` : "Весь экран"}</span>
          <label>
            <span>Viewport</span>
            <select value={viewport} onChange={(e) => setViewport(e.target.value as AssistViewport)} disabled={busy}>
              <option value="current">Текущий</option>
              <option value="all">Все breakpoint</option>
              <option value="desktop">Desktop</option>
              <option value="tablet">Tablet</option>
              <option value="mobile">Mobile</option>
            </select>
          </label>
        </div>

        <div className="fe-ai-section-label">Быстрые действия</div>
        <div className="fe-ai-actions-grid">
          {QUICK_ACTIONS.map((item) => (
            <button
              key={item.action}
              className="fe-ai-action"
              data-ai-action={item.action}
              disabled={busy}
              onClick={() => run({ action: item.action, prompt: item.prompt, viewport })}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="fe-ai-section-label">Свой запрос</div>
        <textarea
          className="fe-ai-prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Например: сделай hero компактнее на mobile"
          disabled={busy}
        />
        <button
          className="fe-btn primary fe-ai-run"
          data-ai-action="custom"
          disabled={busy || !prompt.trim()}
          onClick={() => run({ action: "custom", prompt, viewport })}
        >
          {busy ? "Анализирую…" : "Подготовить preview"}
        </button>

        {error && <div className="fe-ai-error" role="alert">{error}</div>}

        {preview && (
          <div className="fe-ai-preview" data-ai-preview="ready">
            <div className="fe-ai-preview-summary">{preview.summary}</div>
            <div className="fe-ai-preview-meta">
              {preview.ops.length} изменений
            </div>
            {preview.changedViewports.length > 0 && (
              <div className="fe-ai-viewports" aria-label="Затронутые viewport">
                {preview.changedViewports.map((item) => (
                  <button key={item} type="button" onClick={() => ctl.setViewport(item)}>{item}</button>
                ))}
              </div>
            )}
            <div className="fe-ai-preview-meta">
              {preview.ops.length
                ? "Результат показан на холсте. Проверьте отмеченные viewport, затем примените или отмените."
                : "Макет уже соответствует запросу — применять нечего."}
            </div>
            <div className="fe-ai-diff-list">
              {preview.ops.slice(0, 12).map((op, index) => (
                <div className="fe-ai-diff" key={`${op.path}-${index}`}>
                  <span title={op.path}>{describeOp(op.path, op.reason)}</span>
                </div>
              ))}
              {preview.ops.length > 12 && <div className="fe-ai-more">+ ещё {preview.ops.length - 12}</div>}
            </div>
            {preview.warnings.length > 0 && (
              <div className="fe-ai-warnings">
                {preview.warnings.map((warning, index) => <div key={`${warning.code}-${index}`}>⚠ {warning.message}</div>)}
              </div>
            )}
            <div className="fe-ai-preview-actions">
              <button className="fe-btn" data-ai-cancel onClick={ctl.cancelAiAssist}>Отмена</button>
              <button
                className="fe-btn primary"
                data-ai-apply
                disabled={busy || preview.ops.length === 0}
                onClick={ctl.applyAiAssist}
              >
                {preview.ops.length ? "Применить" : "Нет изменений"}
              </button>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
