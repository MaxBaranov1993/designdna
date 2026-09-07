<script lang="ts">
  /* Шпаргалка горячих клавиш графового экрана: открывается по «?»
   * (Shift+/ в латинице, Shift+«,» в русской раскладке), закрывается по Esc,
   * ✕ и клику по фону. Не перехватывает ввод в полях и не всплывает поверх
   * уже открытого модального оверлея (диалоги, DNA-редактор). */
  let open = $state(false);
  let closeBtn: HTMLButtonElement | null = $state(null);
  let restoreFocus: HTMLElement | null = null;

  type Row = { keys: string[]; label: string };
  type Section = { title: string; rows: Row[] };

  const sections: Section[] = [
    {
      title: "Канвас графа",
      rows: [
        { keys: ["ПКМ"], label: "Создать ноду (меню с поиском)" },
        { keys: ["ПКМ по ноде"], label: "Меню ноды: разорвать связи" },
        { keys: ["Ctrl", "Колесо"], label: "Зум к курсору" },
        { keys: ["V"], label: "Выбор и выделение рамкой" },
        { keys: ["H"], label: "Рука" },
        { keys: ["Shift", "1"], label: "Вписать весь граф" },
        { keys: ["Shift", "2"], label: "Вписать выделенное" },
        { keys: ["Пробел + drag", "СКМ", "Колесо"], label: "Перемещение канваса" },
        { keys: ["Del", "Backspace"], label: "Удалить выбранную ноду или связь" },
        { keys: ["Ctrl", "Z"], label: "Отменить изменение графа" },
        { keys: ["Ctrl", "Y"], label: "Повторить изменение графа" },
        { keys: ["Esc"], label: "Закрыть меню или диалог" },
        { keys: ["?"], label: "Эта шпаргалка" },
      ],
    },
    {
      title: "DNA-редактор",
      rows: [
        { keys: ["V", "М"], label: "Выделение" },
        { keys: ["H", "Р"], label: "Рука (панорама)" },
        { keys: ["R", "К"], label: "Прямоугольник" },
        { keys: ["T", "Е"], label: "Текст" },
        { keys: ["F", "А"], label: "Фрейм" },
        { keys: ["O", "Щ"], label: "Эллипс" },
        { keys: ["L", "Д"], label: "Линия" },
        { keys: ["I", "Ш"], label: "Изображение" },
        { keys: ["]", "["], label: "Слой выше / ниже" },
        { keys: ["Ctrl", "S"], label: "Сохранить" },
        { keys: ["Ctrl", "Z"], label: "Отменить" },
        { keys: ["Ctrl", "Shift", "Z"], label: "Повторить (или Ctrl+Y)" },
        { keys: ["Esc"], label: "Закрыть редактор" },
      ],
    },
  ];

  const isTyping = (target: EventTarget | null) => {
    const el = target as HTMLElement | null;
    return !!el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
  };

  const modalOpen = () =>
    !!document.querySelector('[role="dialog"][aria-modal="true"], .dna-editor[data-editor-open="true"]');

  const close = () => {
    if (!open) return;
    open = false;
    restoreFocus?.focus?.();
    restoreFocus = null;
  };

  const onKeydown = (event: KeyboardEvent) => {
    if (open && event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close();
      return;
    }
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const isHelp =
      event.key === "?" || (event.shiftKey && (event.key === "," || event.code === "Slash"));
    if (!isHelp) return;
    if (open) {
      event.preventDefault();
      close();
      return;
    }
    if (isTyping(event.target) || modalOpen()) return;
    event.preventDefault();
    restoreFocus = document.activeElement as HTMLElement | null;
    open = true;
  };

  $effect(() => {
    if (open) closeBtn?.focus();
  });
</script>

<svelte:window onkeydown={onKeydown} />

{#if open}
  <div
    class="hk-backdrop"
    role="presentation"
    onclick={(event) => {
      if (event.target === event.currentTarget) close();
    }}
  >
    <div class="hk-card" role="dialog" aria-modal="true" aria-labelledby="hk-title" data-hotkey-cheatsheet>
      <div class="hk-head">
        <div>
          <div class="hk-kicker">Горячие клавиши</div>
          <h2 id="hk-title">Шпаргалка</h2>
        </div>
        <button bind:this={closeBtn} class="hk-close" type="button" aria-label="Закрыть шпаргалку" onclick={close}>✕</button>
      </div>
      <div class="hk-grid">
        {#each sections as section (section.title)}
          <section class="hk-section">
            <h3>{section.title}</h3>
            <dl>
              {#each section.rows as row (row.label)}
                <div class="hk-row">
                  <dt>
                    {#each row.keys as key, index (key)}
                      {#if index > 0}<span class="hk-sep">{row.keys.length > 2 || row.keys[0] === "Ctrl" ? "+" : "/"}</span>{/if}
                      <kbd>{key}</kbd>
                    {/each}
                  </dt>
                  <dd>{row.label}</dd>
                </div>
              {/each}
            </dl>
          </section>
        {/each}
      </div>
      <div class="hk-foot">Esc — закрыть · Русские буквы в редакторе работают как латинские</div>
    </div>
  </div>
{/if}

<style>
  .hk-backdrop {
    position: fixed;
    inset: 0;
    z-index: 188;
    display: grid;
    place-items: center;
    padding: 24px;
    background: rgba(7, 7, 10, 0.66);
    backdrop-filter: blur(5px);
  }
  .hk-card {
    width: min(760px, calc(100vw - 48px));
    max-height: calc(100vh - 48px);
    overflow: auto;
    padding: 22px;
    border: 1px solid var(--dna-border-strong);
    border-radius: 16px;
    background: var(--dna-elevated);
    color: var(--dna-text);
    box-shadow: 0 24px 80px rgba(0, 0, 0, 0.7);
  }
  .hk-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 16px;
  }
  .hk-kicker {
    margin-bottom: 6px;
    color: var(--dna-violet-text);
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }
  .hk-card h2 {
    margin: 0;
    font-size: 19px;
  }
  .hk-close {
    width: 30px;
    height: 30px;
    border: 1px solid var(--dna-border);
    border-radius: 9px;
    background: var(--dna-panel);
    color: var(--dna-muted);
    font-size: 12px;
    cursor: pointer;
  }
  .hk-close:hover {
    background: var(--dna-hover);
    color: var(--dna-text);
  }
  .hk-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 20px;
  }
  .hk-section h3 {
    margin: 0 0 8px;
    color: var(--dna-muted);
    font-size: 10.5px;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }
  .hk-section dl {
    margin: 0;
  }
  .hk-row {
    display: grid;
    grid-template-columns: minmax(118px, auto) 1fr;
    align-items: center;
    gap: 10px;
    padding: 5px 0;
    border-bottom: 1px solid var(--dna-border-soft);
  }
  .hk-row:last-child {
    border-bottom: none;
  }
  .hk-row dt {
    display: flex;
    align-items: center;
    gap: 4px;
    flex-wrap: wrap;
  }
  .hk-row dd {
    margin: 0;
    color: var(--dna-text-2);
    font-size: 12.5px;
  }
  .hk-sep {
    color: var(--dna-faint);
    font-size: 11px;
  }
  kbd {
    display: inline-block;
    min-width: 22px;
    padding: 2px 6px;
    border: 1px solid var(--dna-border-strong);
    border-bottom-width: 2px;
    border-radius: 6px;
    background: var(--dna-panel);
    color: var(--dna-text);
    font-family: inherit;
    font-size: 11px;
    font-weight: 700;
    text-align: center;
    line-height: 1.4;
  }
  .hk-foot {
    margin-top: 16px;
    color: var(--dna-faint);
    font-size: 11px;
  }
  .hk-close:focus-visible {
    outline: 2px solid var(--dna-violet-l);
    outline-offset: 2px;
  }
</style>
