#!/usr/bin/env python3
"""Пакетный прогон спайка: 7 брифов × 3 температуры.

Идемпотентен: существующие файлы results/*.json пропускаются — можно
перезапускать после сбоев, догонит недостающее.

    python spike/run_all.py
"""
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_test as rt

OUT = Path(__file__).resolve().parent.parent / "results"
OUT.mkdir(exist_ok=True)

BRIEFS = {
    "b1": "Лендинг для SaaS-платформы аналитики маркетинга. Аудитория — CMO среднего бизнеса. "
          "Тон: уверенный, минималистичный, светлая тема, много воздуха. Нужны: hero с продуктовым "
          "скриншотом, фичи, метрики клиентов, тарифы, FAQ, CTA.",
    "b2": "Сайт спешелти-кофейни в Москве. Тёплая палитра (кремовый, коричневый, терракота), уютно, "
          "серифная типографика. Секции: hero с фото интерьера, меню (карточки), о нас, отзывы, "
          "контакты с формой бронирования столика.",
    "b3": "Лендинг финтех-приложения для инвестиций. Тёмная тема, неоновый акцент, доверие + "
          "технологичность. Hero, как это работает (шаги), цифры, сравнение с банками, отзывы, "
          "тарифы, форма заявки на ранний доступ.",
    "b4": "Портфолио-лендинг независимой дизайн-студии. Брутализм: крупная типографика, ч/б + один "
          "кислотный акцент, видимая сетка. Hero-манифест, избранные проекты (галерея), услуги, "
          "команда, контакты.",
    "b5": "Лендинг онлайн-школы программирования для подростков. Ярко, дружелюбно, скруглённые "
          "формы, иллюстрации. Hero, курсы (карточки), как проходит обучение, отзывы родителей, "
          "тарифы, форма записи на пробный урок.",
    "b6": "Сгенерируй ТОЛЬКО секцию pricing: 3 тарифа для облачного хранилища, средний выделен, "
          "переключатель месяц/год. Светлая тема, корпоративный стиль.",
    "b7": "Сделай лендинг с анимированным 3D-фоном, параллаксом и видеоплеером. Тема — игровая "
          "студия, тёмная тема, неон.",
}

# Три температуры авто-маршрута (OpenAI/Kimi по подключённому аккаунту) для оценки разброса.
RUNS = {
    "auto": [("t07", 0.7), ("t09", 0.9), ("t10", 1.0)],
}


def main() -> int:
    system = rt.build_system_prompt()
    total = sum(len(BRIEFS) * len(v) for v in RUNS.values())
    done = failed = 0
    for bid, brief in BRIEFS.items():
        for provider, runs in RUNS.items():
            for tag, temp in runs:
                out = OUT / f"{bid}-{provider}-{tag}.json"
                if out.exists():
                    done += 1
                    continue
                messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"## Brief\n{brief}"},
                ]
                try:
                    raw = rt.chat(provider, messages, temp)
                    out.write_text(rt.extract_json(raw), encoding="utf-8")
                    done += 1
                    print(f"[done {done}/{total}] {out.name}", flush=True)
                except Exception as e:
                    failed += 1
                    print(f"[fail] {out.name}: {e}", flush=True)
                    traceback.print_exc(limit=1)
                time.sleep(2)
    print(f"Готово: {done}/{total}, ошибок: {failed}", flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
