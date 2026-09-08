<script lang="ts">
  /* Пустое состояние канваса: страница без нод.
   *
   * Карточка переносится (portal) ВНУТРЬ `.svelte-flow__pane`: для Playwright
   * и hit-testing любая точка карточки считается пейном, а ПКМ/клик по
   * карточке переотправляются пейну синтетическим событием — обработчики
   * Svelte Flow принимают только события с target === pane. Кнопки
   * сценариев ловят события сами (`nopan` — d3-zoom их не тянет). */
  import { useFlowStore } from "./store";
  import { toast } from "./toast";

  let { onfit }: { onfit?: () => void } = $props();

  type Scenario = {
    id: string;
    icon: string;
    title: string;
    note: string;
    build: () => void;
  };

  const fitSoon = () => {
    if (!onfit) return;
    setTimeout(onfit, 80);
    setTimeout(onfit, 450);
  };

  const scenarios: Scenario[] = [
    {
      id: "import-uikit",
      icon: "⌁",
      title: "Импорт сайта → UI Kit",
      note: "Source Import по URL, из него — Design System",
      build: () => {
        const st = useFlowStore.getState();
        const source = st.addNode("sourceimport", 120, 160);
        const system = st.addNode("designsystem", 560, 160);
        st.connect({ node: source.id, port: "artifact" }, { node: system.id, port: "artifact" });
      },
    },
    {
      id: "landing",
      icon: "◈",
      title: "Генерация лендинга",
      note: "Промпт и референс → Генератор вариантов",
      build: () => {
        const st = useFlowStore.getState();
        const prompt = st.addNode("prompt", 120, 120);
        const reference = st.addNode("reference", 120, 380);
        const generator = st.addNode("generator", 560, 180);
        st.connect({ node: prompt.id, port: "out" }, { node: generator.id, port: "prompt" });
        st.connect({ node: reference.id, port: "out" }, { node: generator.id, port: "reference" });
      },
    },
    {
      id: "video",
      icon: "▶",
      title: "Видео из страницы",
      note: "Источник → Генератор → Recorder → Motion → ролик",
      build: () => {
        useFlowStore.getState().addVideoChainPage();
      },
    },
  ];

  const run = (scenario: Scenario) => {
    try {
      scenario.build();
      fitSoon();
    } catch (error) {
      console.error("empty-state scenario failed", error);
      toast(`Не удалось собрать сценарий: ${(error as Error)?.message || error}`, "error");
    }
  };

  /* Переносит узел в пейн Svelte Flow. Пейн может смонтироваться позже
   * (store.initialized), поэтому ждём его по кадрам; на размонтировании
   * узел снимается с пейна вручную — Svelte удаляет его по исходному месту. */
  const portalToPane = (node: HTMLElement) => {
    let frame = 0;
    const host = node.parentElement;
    const attach = () => {
      const pane = host?.querySelector<HTMLElement>(".svelte-flow__pane");
      if (pane) {
        if (node.parentElement !== pane) pane.appendChild(node);
        return;
      }
      frame = requestAnimationFrame(attach);
    };
    attach();
    return {
      destroy() {
        cancelAnimationFrame(frame);
        node.remove();
      },
    };
  };

  /* ПКМ и клик по карточке (кроме клика по кнопке) — это ПКМ/клик по пейну:
   * меню создания ноды и закрытие меню работают так же, как на пустом месте. */
  const forwardToPane = (event: MouseEvent) => {
    const target = event.target as HTMLElement | null;
    if (event.type === "click" && target?.closest("button")) return;
    const pane = (event.currentTarget as HTMLElement).closest<HTMLElement>(".svelte-flow__pane");
    if (!pane) return;
    event.preventDefault();
    event.stopPropagation();
    pane.dispatchEvent(
      new MouseEvent(event.type, {
        bubbles: true,
        cancelable: true,
        clientX: event.clientX,
        clientY: event.clientY,
        screenX: event.screenX,
        screenY: event.screenY,
        button: event.button,
        buttons: event.buttons,
        ctrlKey: event.ctrlKey,
        shiftKey: event.shiftKey,
        altKey: event.altKey,
        metaKey: event.metaKey,
      }),
    );
  };
</script>

<div class="empty-state" use:portalToPane>
  <div
    class="empty-card"
    role="presentation"
    data-empty-state
    oncontextmenu={forwardToPane}
    onclick={forwardToPane}
  >
    <div class="empty-kicker">Пустая страница</div>
    <h2>С чего начать</h2>
    <p>
      <kbd>ПКМ</kbd> или двойной клик по канвасу создаёт ноду, <kbd>Ctrl</kbd>+<kbd>K</kbd> — поиск, <kbd>?</kbd> — горячие клавиши.
      Или соберите стартовый граф одной кнопкой:
    </p>
    <div class="empty-actions">
      {#each scenarios as scenario (scenario.id)}
        <button
          type="button"
          class="empty-btn nopan"
          data-scenario={scenario.id}
          onclick={(event) => {
            event.stopPropagation();
            run(scenario);
          }}
        >
          <span class="empty-ic" aria-hidden="true">{scenario.icon}</span>
          <span class="empty-txt">
            <strong>{scenario.title}</strong>
            <small>{scenario.note}</small>
          </span>
        </button>
      {/each}
    </div>
  </div>
</div>

<style>
  .empty-state {
    position: absolute;
    inset: 0;
    z-index: 4;
    display: grid;
    place-items: center;
    padding: 16px;
    pointer-events: none;
  }
  .empty-card {
    width: min(560px, 100%);
    padding: 18px 20px;
    border: 1px solid var(--dna-border);
    border-radius: 16px;
    background: var(--dna-panel);
    color: var(--dna-text);
    box-shadow: var(--shadow-panel);
    pointer-events: auto;
    user-select: none;
  }
  .empty-kicker {
    margin-bottom: 6px;
    color: var(--dna-dim);
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }
  .empty-card h2 {
    margin: 0 0 6px;
    font-size: 17px;
  }
  .empty-card p {
    margin: 0 0 14px;
    color: var(--dna-text-2);
    font-size: 12.5px;
    line-height: 1.5;
  }
  .empty-card kbd {
    display: inline-block;
    padding: 1px 6px;
    border: 1px solid var(--dna-border-strong);
    border-bottom-width: 2px;
    border-radius: 6px;
    background: var(--dna-panel);
    color: var(--dna-text);
    font-family: inherit;
    font-size: 11px;
    font-weight: 700;
  }
  .empty-actions {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
  }
  .empty-btn {
    display: flex;
    align-items: flex-start;
    gap: 9px;
    padding: 10px;
    border: 1px solid var(--dna-border);
    border-radius: 11px;
    background: var(--dna-panel);
    color: var(--dna-text);
    text-align: left;
    cursor: pointer;
    transition: background 0.15s ease, border-color 0.15s ease;
  }
  .empty-btn:hover {
    background: var(--dna-hover);
    border-color: var(--dna-border-strong);
  }
  .empty-btn:focus-visible {
    outline: 2px solid var(--dna-text);
    outline-offset: 2px;
  }
  .empty-ic {
    flex: none;
    width: 24px;
    height: 24px;
    display: grid;
    place-items: center;
    border-radius: 7px;
    background: var(--dna-sunken);
    border: 1px solid var(--dna-border);
    color: var(--dna-text-2);
    font-size: 13px;
  }
  .empty-txt {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }
  .empty-txt strong {
    font-size: 12px;
    font-weight: 700;
    line-height: 1.3;
  }
  .empty-txt small {
    color: var(--dna-muted);
    font-size: 10.5px;
    line-height: 1.35;
  }
  @media (max-width: 900px) {
    .empty-actions {
      grid-template-columns: 1fr;
    }
  }
</style>
