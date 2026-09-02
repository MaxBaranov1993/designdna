import { writable } from "svelte/store";

/* Фирменный confirm вместо window.confirm: запросы копятся в очереди,
 * ConfirmHost показывает первый и резолвит промис ответом пользователя.
 * Если хост не смонтирован (нет DOM/тестовая среда) — запрос всё равно
 * висит в очереди и будет показан, как только хост появится. */
export type ConfirmOptions = {
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel?: string;
  /* Красная кнопка подтверждения — для необратимых действий (удаление) */
  danger?: boolean;
};

export type ConfirmRequest = Required<ConfirmOptions> & {
  id: number;
  resolve: (value: boolean) => void;
};

let seq = 0;

export const confirmQueue = writable<ConfirmRequest[]>([]);

export function confirmDialog(options: ConfirmOptions): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    const request: ConfirmRequest = {
      id: ++seq,
      title: options.title,
      message: options.message,
      confirmLabel: options.confirmLabel,
      cancelLabel: options.cancelLabel ?? "Отмена",
      danger: options.danger ?? false,
      resolve,
    };
    confirmQueue.update((queue) => [...queue, request]);
  });
}

/* Завершить запрос: снять его из очереди и отдать ответ ожидающему промису. */
export function settleConfirm(id: number, value: boolean) {
  confirmQueue.update((queue) => {
    const request = queue.find((item) => item.id === id);
    if (!request) return queue;
    request.resolve(value);
    return queue.filter((item) => item.id !== id);
  });
}
