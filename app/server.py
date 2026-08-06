#!/usr/bin/env python3
"""DesignAI Web — локальный dev-сервер генерации веб-дизайна (Design IR).

Запуск:  .venv/Scripts/python app/server.py   (порт 8420)
"""
import concurrent.futures
import copy
import json
import mimetypes
import re
import sys
import traceback
import urllib.request
import urllib.error
import webbrowser
from pathlib import Path

# Windows: реестр может не знать MIME для .js/.css/woff — без корректного
# content-type браузер отказывается выполнять module-скрипты сборки /flow
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import llm_client as llm  # chat, chat_vision, build_system_prompt, extract_json
from colorutils import mix_hex_colors
from scraper import prepare_image_b64, analyze_url, extract_structure, parse_design_tokens
from reproduce import run_pipeline as reproduce_pipeline
from urlguard import validate_public_url
import cache_store
import blockparse
import mergeback
import qualitygate

import jsonschema

SCHEMA = json.loads((ROOT / "schema" / "design-ir.schema.json").read_text(encoding="utf-8"))
VALIDATOR = jsonschema.Draft7Validator(SCHEMA)
ANALYSIS_PATH = ROOT / "test-targets" / "rsale-site" / "analysis.json"

EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4)

app = FastAPI(title="DesignAI Web", docs_url=None, redoc_url=None)

COLOR_TOKEN_KEYS = ["primary", "secondary", "accent", "background", "surface", "text", "textMuted", "border"]
PROVIDERS = ["qwen", "kimi", "groq", "gemini", "xai", "glm", "openrouter"]
VISION_PROVIDERS = ["xai", "gemini", "groq", "qwen", "glm", "openrouter"]  # приоритет для vision

# роли вызовов для роутинга OpenRouter — см. таблицу llm_client.ROUTING
# (generate/edit/repair/clone/reference/...)


# ---------- helpers ----------

def validate_ir(ir: dict) -> list:
    """Список ошибок валидации IR по схеме (пустой = ок)."""
    return sorted(
        (f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
         for e in VALIDATOR.iter_errors(ir)),
        key=str,
    )


def parse_ir_response(raw: str):
    """extract_json + json.loads -> (ir, error)."""
    try:
        return json.loads(llm.extract_json(raw)), None
    except (json.JSONDecodeError, ValueError) as e:
        return None, f"невалидный JSON от модели: {e}"


def call_llm_ir(provider: str, user_content: str, temperature: float = 0.8, mode: str = "generate"):
    """Вызов LLM с системным промптом генератора -> (ir, error)."""
    try:
        raw = llm.chat(provider, [
            {"role": "system", "content": llm.build_system_prompt(mode)},
            {"role": "user", "content": user_content},
        ], temperature, role="generator" if mode == "generate" else "edit")
    except Exception as e:
        return None, str(e)
    return parse_ir_response(raw)


def err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=status)


def normalize_provider(provider: str | None) -> str:
    return provider if provider in PROVIDERS else "qwen"


# ---------- models ----------

class GenerateReq(BaseModel):
    brief: str = ""
    count: int = 3
    provider: str = "qwen"
    styleHint: str | None = None
    seedTag: str | None = None


class AnalyzeReq(BaseModel):
    force: bool = False
    provider: str = "qwen"


class MixReq(BaseModel):
    irs: list
    weights: list


class RefineReq(BaseModel):
    ir: dict
    instruction: str = ""
    provider: str = "qwen"


class ValidateReq(BaseModel):
    ir: dict


class CloneReq(BaseModel):
    url: str = ""
    component: str = ""
    provider: str = "qwen"


class BlockParseReq(BaseModel):
    url: str = ""
    blocks: list | None = None  # опционально: [{name, selector}] — клонировать только их


class ReskinReq(BaseModel):
    ir: dict
    prompt: str = ""
    tokens: dict | None = None  # источник нового стиля (design-токены)
    mask: dict = {}             # чекбоксы: colors/fonts/radii/shadows/texts/images


class VisionDecomposeReq(BaseModel):
    image: str = ""  # base64 data URL
    brief: str = ""
    provider: str = "qwen"


class QualityGateReq(BaseModel):
    ir: dict
    fix: bool = True  # авто-доводка solver'ом (без LLM) того, что чинится


class ConstraintsCheckReq(BaseModel):
    ir: dict
    constraints: list  # [{path, lock?, min?, max?, enum?, max_len?}]


class ScrapeReq(BaseModel):
    url: str = ""
    use_playwright: bool = True


class ReproduceReq(BaseModel):
    image: str = ""  # base64 data URL
    url: str = ""  # или URL сайта: скриншот снимем сами, результат кэшируется
    provider: str = "qwen"  # любой провайдер для VLM-анализа структуры
    regions: list | None = None  # опциональные регионы для diff: [["name", x1, y1, x2, y2], ...]


# ---------- endpoints ----------

@app.post("/api/generate")
def generate(req: GenerateReq):
    provider = normalize_provider(req.provider)
    brief = req.brief.strip()
    if not brief:
        return err(422, "Пустой бриф: опишите, что нужно сгенерировать.")
    count = max(1, min(int(req.count or 1), 5))
    has_style = bool(req.styleHint and req.styleHint.strip())
    style = f"\n\n## Reference / style context\n{req.styleHint.strip()}" if has_style else ""
    mode = "edit" if has_style else "generate"

    def gen_one(n: int):
        if mode == "edit":
            user = (
                f"## Reference context\n{req.styleHint.strip()}\n\n"
                f"## Modification instruction\n{brief}\n\n"
                f"REPRODUCE the reference structure and content EXACTLY. "
                f"Apply ONLY the modification above. Do NOT add or remove sections/elements. "
                f"Do NOT invent content not present in the reference."
            )
        else:
            user = (
                f"## Brief\n{brief}\n\n"
                f"Вариант {n} из {count}: сделай визуально отличное решение №{n} — "
                f"своя палитра, типографика, настроение и композиция, не повторяй другие варианты."
            )
        if req.seedTag:
            user += f"\nseedTag: {req.seedTag}"
        return call_llm_ir(provider, user, 0.8 if mode == "generate" else 0.3, mode)

    futures = [EXECUTOR.submit(gen_one, i + 1) for i in range(count)]
    variants, errors = [], []
    for i, f in enumerate(futures):
        ir, error = f.result()
        if ir is not None:
            variants.append(ir)
        else:
            errors.append({"index": i + 1, "error": error})
    if not variants:
        return err(502, f"Ни один вариант не сгенерирован. {errors[0]['error'] if errors else ''}")
    return {"variants": variants, "errors": errors}


@app.post("/api/analyze-header")
def analyze_header(req: AnalyzeReq):
    if ANALYSIS_PATH.exists() and not req.force:
        try:
            return json.loads(ANALYSIS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass  # битый кэш — перегенерируем

    provider = normalize_provider(req.provider)
    header_html = (ROOT / "test-targets" / "rsale-site" / "header-extracted.html").read_text(encoding="utf-8")
    page_html = (ROOT / "test-targets" / "rsale-site" / "page-ru.html").read_text(encoding="utf-8")
    # из страницы берём куски со стилями и начало body, чтобы уложиться в контекст
    styles = " ".join(re.findall(r"<style[^>]*>(.*?)</style>", page_html, re.S))[:6000]
    body_start = re.sub(r"\s+", " ", page_html)[:6000]

    user = (
        "Ты — senior веб-дизайнер. Проанализируй HTML шапки реального сайта "
        "(маркетплейс объявлений Rsale, Сербия) и верни ОДИН JSON-объект с полями:\n"
        '- "structureSummary": markdown-строка (на русском): структура шапки, элементы, их порядок, паттерны.\n'
        '- "suggestedTokens": объект design-токенов по схеме Design IR (mode/color/font/radius/spacing/shadow), '
        "подобранные по визуальному стилю этого сайта.\n"
        '- "headerBrief": строка (на русском) — бриф для генерации НОВЫХ шапок (одна секция navbar) '
        "в стиле и нише этого сайта: что за продукт, какие элементы шапки нужны, настроение.\n"
        "Никакого markdown вокруг, только JSON.\n\n"
        f"## HTML шапки\n{header_html}\n\n## CSS стилей страницы (фрагмент)\n{styles}\n\n## Начало страницы (фрагмент)\n{body_start}"
    )
    try:
        raw = llm.chat(provider, [
            {"role": "system", "content": "Ты — senior веб-дизайнер и аналитик дизайн-систем. Отвечаешь строго одним JSON-объектом."},
            {"role": "user", "content": user},
        ], 0.4, role="clone")
    except Exception as e:
        return err(502, str(e))
    data, error = parse_ir_response(raw)
    if data is None:
        return err(502, error)
    if not isinstance(data, dict) or "structureSummary" not in data or "headerBrief" not in data:
        return err(502, "Модель вернула JSON без обязательных полей structureSummary/headerBrief")
    ANALYSIS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


@app.post("/api/mix")
def mix(req: MixReq):
    irs, weights = req.irs, [float(w) for w in req.weights]
    if not irs:
        return err(422, "Нужен хотя бы один IR для микса.")
    if len(irs) != len(weights):
        return err(422, "Количество IR и весов не совпадает.")
    if any(w < 0 for w in weights):
        return err(422, "Веса должны быть >= 0.")

    dom = max(range(len(irs)), key=lambda i: weights[i])  # при всех нулях -> 0
    result = copy.deepcopy(irs[dom])
    if not isinstance(result, dict):
        return err(422, f"IR #{dom + 1} не является объектом.")
    result_colors = result.setdefault("tokens", {}).setdefault("color", {})

    # цвета — взвешенный микс в OKLCH
    for key in COLOR_TOKEN_KEYS:
        pairs = [(ir["tokens"]["color"][key], weights[i])
                 for i, ir in enumerate(irs)
                 if isinstance(ir, dict) and key in ir.get("tokens", {}).get("color", {})]
        if pairs:
            result_colors[key] = mix_hex_colors(pairs)

    meta = result.setdefault("meta", {})
    if "name" in meta:
        meta["name"] = f"{meta['name']} (mix)"
    meta["mixOf"] = [{"index": i, "weight": weights[i]} for i in range(len(irs))]
    return {"ir": result}


@app.post("/api/refine")
def refine(req: RefineReq):
    provider = normalize_provider(req.provider)
    instruction = req.instruction.strip()
    if not instruction:
        return err(422, "Пустая инструкция правки.")
    ir_json = json.dumps(req.ir, ensure_ascii=False)

    def ask(content: str):
        return llm.chat(provider, [
            {"role": "system", "content": llm.build_system_prompt()},
            {"role": "user", "content": content},
        ], 0.3, role="edit")

    user = (
        "Вот текущий Design IR (JSON):\n" + ir_json +
        "\n\nПравка пользователя (часть могла быть уже применена вручную — учитывай оба источника): "
        + instruction +
        "\n\nВерни обновлённый ПОЛНЫЙ валидный Design IR по схеме. Только JSON."
    )
    try:
        raw = ask(user)
    except Exception as e:
        return err(502, str(e))
    ir, error = parse_ir_response(raw)
    errors = validate_ir(ir) if ir is not None else [error]

    if errors:
        # один repair-вызов
        repair = (
            "Следующий JSON не прошёл валидацию по схеме. Ошибки:\n- " + "\n- ".join(errors[:10]) +
            "\n\nИсправь минимально и верни только исправленный JSON:\n\n" +
            (ir_json if ir is None else json.dumps(ir, ensure_ascii=False))
        )
        try:
            raw2 = ask(repair)
        except Exception as e:
            return err(502, str(e))
        ir2, error2 = parse_ir_response(raw2)
        if ir2 is None:
            return err(502, f"repair не помог: {error2}")
        errors2 = validate_ir(ir2)
        if errors2:
            return err(502, "refine не прошёл валидацию после repair: " + "; ".join(errors2[:5]))
        ir = ir2
    return {"ir": ir}


@app.post("/api/validate")
def validate(req: ValidateReq):
    errors = validate_ir(req.ir)
    return {"ok": not errors, "errors": errors}


@app.post("/api/clone")
def clone(req: CloneReq):
    """Клонирование компонента с внешнего сайта: fetch HTML → LLM → IR."""
    url = req.url.strip()
    component = req.component.strip()
    if not url:
        return err(422, "Укажите URL сайта.")
    if not component:
        return err(422, "Опишите, какой компонент клонировать.")
    provider = normalize_provider(req.provider)

    # SSRF-гард: только публичные http/https URL
    try:
        validate_public_url(url)
    except ValueError as e:
        return err(422, str(e))

    # кэш: тот же сайт повторно — без траты токенов
    hit = cache_store.get("clone_url", cache_store.key_url(url))
    if hit:
        return {**hit, "cached": True}

    # fetch страницы
    try:
        req_obj = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ru,en;q=0.9",
        })
        with urllib.request.urlopen(req_obj, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return err(502, f"Не удалось загрузить {url}: {e}")

    # извлекаем стили и body (обрезаем до 12000 символов чтобы уложиться в контекст)
    styles = " ".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S))[:6000]
    body = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)  # убираем скрипты
    body = re.sub(r"\s+", " ", body)[:12000]

    user = (
        "Ты — senior фронтенд-разработчик и дизайн-инженер. Тебе дали HTML+CSS реальной страницы.\n"
        f"Задача: выделить компонент «{component}» из этой страницы и представить его как Design IR (JSON).\n\n"
        "ПРАВИЛА:\n"
        "- Воспроизведи структуру компонента ТОЧНО: те же элементы, тот же порядок, тот же текст.\n"
        "- НЕ добавляй элементы, которых нет в HTML.\n"
        "- НЕ убирай элементы из HTML.\n"
        "- Тексты — verbatim из HTML (не перефразируй).\n"
        "- Цвета/шрифты/радиусы — извлеки из CSS и запиши в tokens.\n"
        "- Раскладку (flex/grid/позиции) — передай через frame (layout/direction/gap/padding).\n"
        "- Верни ОДИН JSON-объект по схеме Design IR. Без markdown.\n\n"
        f"## CSS стили\n{styles}\n\n## HTML страницы\n{body}"
    )
    try:
        raw = llm.chat(provider, [
            {"role": "system", "content": llm.build_system_prompt("edit")},
            {"role": "user", "content": user},
        ], 0.2, role="clone")
    except Exception as e:
        return err(502, str(e))
    ir, error = parse_ir_response(raw)
    if ir is None:
        return err(502, error)
    errors = validate_ir(ir)
    if errors:
        # repair
        repair = (
            "Следующий JSON не прошёл валидацию. Ошибки:\n- " + "\n- ".join(errors[:8]) +
            "\n\nИсправь минимально и верни только JSON:\n\n" + json.dumps(ir, ensure_ascii=False)
        )
        try:
            raw2 = llm.chat(provider, [
                {"role": "system", "content": llm.build_system_prompt("edit")},
                {"role": "user", "content": repair},
            ], 0.2, role="repair")
            ir2, _ = parse_ir_response(raw2)
            if ir2 and not validate_ir(ir2):
                ir = ir2
        except Exception:
            pass
    cache_store.put("clone_url", cache_store.key_url(url), {"ir": ir})
    return {"ir": ir, "cached": False}


# ---------- BlockParse / Reskin (решение владельца 11, docs/NODES-HOUDINI.md §7) ----------

# человекочитаемые категории маски для промпта Reskin
_MASK_LABELS = {
    "colors": "цвета (tokens.color, tokens.mode) и fill элементов",
    "fonts": "шрифты (tokens.font: family/weight/scale)",
    "radii": "радиусы (tokens.radius)",
    "shadows": "тени (tokens.shadow)",
    "texts": "тексты в props (заголовки, подписи, кнопки)",
    "images": "изображения (src/imagePrompt/alt/aspect)",
}


@app.post("/api/block-parse")
def block_parse(req: BlockParseReq):
    """BlockParse: детекция блоков страницы + параллельный clone каждого в IR."""
    url = req.url.strip()
    if not url:
        return err(422, "Укажите URL сайта.")
    try:
        validate_public_url(url)  # SSRF-гард (422, а не 502)
    except ValueError as e:
        return err(422, str(e))
    try:
        return blockparse.parse_blocks(url, blocks=req.blocks)
    except ValueError as e:  # кривой список блоков
        return err(422, str(e))
    except Exception as e:
        traceback.print_exc()
        return err(502, f"Ошибка block-parse: {e}")


@app.post("/api/reskin")
def reskin(req: ReskinReq):
    """Reskin: AI-рестайл блока с локом структуры.

    LLM (только qwen, решение владельца 7) → детерминированный merge-back
    (залоченные поля принудительно из входного IR) → валидация по схеме →
    один repair-вызов по существующему паттерну. Дрейф структуры невозможен.
    """
    errors = validate_ir(req.ir)
    if errors:
        return err(422, "Входной IR невалиден: " + "; ".join(errors[:5]))

    mask = mergeback.normalize_mask(req.mask)
    if not any(mask.values()):
        return {"ir": req.ir,
                "log": ["пустая маска: возвращён входной IR без LLM-вызова"]}

    allowed = "\n".join(f"- {label}" for key, label in _MASK_LABELS.items() if mask[key])
    user = (
        "Ты — дизайн-инженер. Ниже — Design IR блока и источник нового стиля.\n"
        "Верни ПОЛНЫЙ Design IR того же блока в новом стиле: один JSON по схеме, без markdown.\n\n"
        "ЖЁСТКИЕ ОГРАНИЧЕНИЯ (проверяются программой, нарушения будут отброшены):\n"
        "- структура дерева НЕ меняется: те же секции и элементы, id, типы, порядок, вложенность;\n"
        "- frame (геометрия и раскладка) НЕ меняется;\n"
        "- props-разметка (состав ключей, варианты, ссылки, иконки) НЕ меняется;\n"
        f"- менять разрешено ТОЛЬКО:\n{allowed}\n\n"
        f"## Входной Design IR\n{json.dumps(req.ir, ensure_ascii=False)}"
    )
    if req.tokens:
        user += f"\n\n## Design-токены нового стиля (источник)\n{json.dumps(req.tokens, ensure_ascii=False)}"
    if req.prompt.strip():
        user += f"\n\n## Пожелания по новому стилю\n{req.prompt.strip()}"

    provider = "qwen"  # решение владельца 7: только qwencloud
    try:
        raw = llm.chat(provider, [
            {"role": "system", "content": llm.build_system_prompt("edit")},
            {"role": "user", "content": user},
        ], 0.7, role="edit")
    except Exception as e:
        return err(502, str(e))
    model_ir, parse_error = parse_ir_response(raw)
    if model_ir is None:
        return err(502, parse_error)

    # детерминированный merge-back: залоченные поля — из входа, попытки в журнал
    merged, journal = mergeback.merge_back(req.ir, model_ir, mask)
    errors = validate_ir(merged)
    if errors:
        # один repair-вызов (паттерн /api/refine); после repair — повторный merge-back
        repair = (
            "Следующий JSON не прошёл валидацию по схеме. Ошибки:\n- " + "\n- ".join(errors[:10]) +
            "\n\nИсправь минимально и верни только исправленный JSON:\n\n" +
            json.dumps(merged, ensure_ascii=False)
        )
        try:
            raw2 = llm.chat(provider, [
                {"role": "system", "content": llm.build_system_prompt("edit")},
                {"role": "user", "content": repair},
            ], 0.2, role="repair")
            ir2, _ = parse_ir_response(raw2)
            if ir2 is not None:
                merged2, journal2 = mergeback.merge_back(req.ir, ir2, mask)
                if not validate_ir(merged2):
                    merged, journal, errors = merged2, journal + journal2, []
        except Exception:
            pass
    if errors:
        return err(502, "reskin не прошёл валидацию после repair: " + "; ".join(errors[:5]))
    return {"ir": merged, "log": journal}


# ---------- Quality Gate / Constraints (решение владельца 12.2, бэклог §8) ----------

@app.post("/api/quality-gate")
def quality_gate(req: QualityGateReq):
    """Детерминированный Quality Gate: правила v1 + авто-доводка без LLM.

    passed/violations — по входному IR; fixed_ir/journal — результат solver'а
    (починено только то, что чинится детерминированно: сетка 8px, overflow).
    """
    violations = qualitygate.check(req.ir)
    if req.fix:
        fixed_ir, journal = qualitygate.autofix(req.ir)
    else:
        fixed_ir, journal = copy.deepcopy(req.ir), []
    return {"passed": not violations, "violations": violations,
            "fixed_ir": fixed_ir, "journal": journal}


@app.post("/api/constraints/check")
def constraints_check(req: ConstraintsCheckReq):
    """Проверка декларативных ограничений (локи полей по путям + диапазоны)."""
    try:
        violations = qualitygate.check_constraints(req.ir, req.constraints)
    except ValueError as e:
        return err(422, str(e))
    return {"ok": not violations, "violations": violations}


VISION_SYSTEM_PROMPT = """Ты — pixel-perfect дизайн-инженер. Тебе дают скриншот веб-страницы.
Твоя задача — воспроизвести ТОЧНО то, что видишь, как Design IR (JSON по схеме).

ПРАВИЛА:
1. НЕ ПРИДУМЫВАЙ контент. Используй ТОЛЬКО тексты, кнопки, логотипы видимые на скриншоте.
2. Воспроизведи ТОЧНУЮ структуру: navbar, hero, секции, footer — в том же порядке.
3. Извлеки ЦВЕТА пиксель-точно: фон, текст, кнопки, бордеры — запиши в tokens.color.
4. Извлеки ШРИФТЫ: определи family (Inter/Sora/Manrope/etc), weight, размеры заголовков/текста.
5. Извлеки ОТСТУПЫ: padding секций, gap между элементами, margin — запиши в frame (padding/gap).
6. Извлеки РАДИУСЫ кнопок/карточек — запиши в tokens.radius.
7. Вложенность: если видишь карточку с иконкой+заголовком+текстом — это children внутри card.
8. Кнопки: текст verbatim, variant (primary/secondary/outline/ghost) по визуальному стилю.
9. Позиции: если элементы расположены горизонтально — frame.direction="row", вертикально — "column".
10. Верни ОДИН валидный JSON по схеме Design IR. Без markdown, без пояснений."""


@app.post("/api/vision-decompose")
def vision_decompose(req: VisionDecomposeReq):
    """Vision-анализ скриншота → pixel-perfect Design IR.
    Автоматически перебирает провайдеров (gemini → groq → qwen)."""
    if not req.image:
        return err(422, "Нужно изображение (base64 data URL).")

    # подготавливаем изображение (resize для vision API)
    img_url = prepare_image_b64(req.image)

    brief_hint = f"\n\nДополнительный контекст: {req.brief}" if req.brief.strip() else ""
    user_prompt = (
        "Проанализируй этот скриншот и верни Design IR (JSON), который ТОЧНО воспроизводит "
        "всё видимое: структуру, тексты, цвета, шрифты, отступы, радиусы, вложенность. "
        "Каждый видимый элемент должен быть в IR. Не добавляй ничего от себя."
        + brief_hint
    )

    # перебираем провайдеров vision
    providers_to_try = VISION_PROVIDERS if req.provider not in VISION_PROVIDERS else [req.provider] + [p for p in VISION_PROVIDERS if p != req.provider]

    all_errors = []
    for provider in providers_to_try:
        try:
            raw = llm.chat_vision(provider, img_url, user_prompt, VISION_SYSTEM_PROMPT, 0.1,
                                  role="vision")
        except Exception as e:
            all_errors.append(f"{provider}: {e}")
            continue

        ir, error = parse_ir_response(raw)
        if ir is None:
            all_errors.append(f"{provider}: {error}")
            continue

        errors = validate_ir(ir)
        if errors:
            # repair attempt
            repair_prompt = (
                "Следующий JSON не прошёл валидацию по схеме Design IR. Ошибки:\n- "
                + "\n- ".join(errors[:8])
                + "\n\nИсправь минимально и верни только исправленный JSON:\n\n"
                + json.dumps(ir, ensure_ascii=False)
            )
            try:
                raw2 = llm.chat_vision(provider, img_url, repair_prompt, VISION_SYSTEM_PROMPT, 0.1,
                                       role="vision")
                ir2, _ = parse_ir_response(raw2)
                if ir2 and not validate_ir(ir2):
                    ir = ir2
            except Exception:
                pass

        return {"ir": ir, "provider_used": provider}

    return err(502, f"Все vision-провайдеры недоступны. Ошибки: {' | '.join(all_errors)}. Установите GROQ_API_KEY (console.groq.com) или GEMINI_API_KEY (aistudio.google.com) — оба бесплатны.")


@app.post("/api/scrape")
def scrape(req: ScrapeReq):
    """Полный анализ реального сайта: контент + стили + структура + скриншот."""
    url = req.url.strip()
    if not url:
        return err(422, "Укажите URL сайта.")
    try:
        validate_public_url(url)  # SSRF-гард (422, а не 502)
    except ValueError as e:
        return err(422, str(e))
    try:
        data = analyze_url(url, use_playwright=req.use_playwright)
    except Exception as e:
        return err(502, f"Ошибка анализа: {e}")

    return {
        "url": data.url,
        "title": data.title,
        "text_content": data.text_content[:4000],
        "structure": data.structure,
        "tokens": data.tokens,
        "screenshot": f"data:image/png;base64,{data.screenshot_b64}" if data.screenshot_b64 else "",
        "viewport": data.viewport,
    }


@app.post("/api/reproduce")
def reproduce(req: ReproduceReq):
    """Pixel-perfect reproduction: скриншот → VLM-структура → Python-измерения → HTML → diff.

    Работает с любым провайдером для VLM-анализа. Все измерения — из пикселей.
    Повторный запрос того же скриншота/сайта — из кэша, без траты токенов.
    """
    url = req.url.strip()
    image = req.image
    url_key = None
    if url:
        try:
            validate_public_url(url)
        except ValueError as e:
            return err(422, str(e))
        url_key = cache_store.key_url(url)
        hit = cache_store.get("reproduce_url", url_key)
        if hit:
            return {**hit, "cached": True}
        # скриншот сайта снимаем один раз — дальше он же и кэшируется
        try:
            page = analyze_url(url, use_playwright=True)
        except Exception as e:
            return err(502, f"Не удалось снять скриншот {url}: {e}")
        if not page.screenshot_b64:
            return err(502, "Пустой скриншот сайта.")
        image = f"data:image/png;base64,{page.screenshot_b64}"
    if not image:
        return err(422, "Нужно изображение (base64 data URL) или URL сайта.")

    # кэш по хэшу изображения: тот же скриншот от любого пользователя — бесплатно
    img_key = cache_store.key_image(image)
    hit = cache_store.get("reproduce_img", img_key)
    if hit:
        return {**hit, "cached": True}

    provider = normalize_provider(req.provider)

    regions = None
    if req.regions:
        regions = [tuple(r) for r in req.regions]

    try:
        result = reproduce_pipeline(
            image_b64=image,
            provider=provider,
            llm_module=llm,
            regions=regions,
        )
    except Exception as e:
        traceback.print_exc()
        return err(502, f"Ошибка пайплайна: {e}")

    payload = {
        "structure": result.get("structure", {}),
        "colors": result.get("colors", {}),
        "measurements": result.get("measurements", {}),
        "icons_count": len(result.get("icons", [])),
        "contents_count": len(result.get("contents", [])),
        "html": result.get("html", ""),
        "diff": result.get("diff", {}),
        "ir": result.get("ir", {}),
        "repro_png": f"data:image/png;base64,{result['repro_png_b64']}" if result.get("repro_png_b64") else "",
        "provider_used": provider,
    }
    cache_store.put("reproduce_img", img_key, payload)
    if url_key:
        cache_store.put("reproduce_url", url_key, payload)
    return {**payload, "cached": False}


@app.get("/api/cache/stats")
def cache_stats():
    """Наблюдаемость кэша: сколько LLM-вызовов сэкономлено повторами."""
    return cache_store.stats()


@app.get("/nodes")
def nodes_page():
    # Legacy-граф снят (Спринт 5 завершён, Фазы A/B1/B2/B3/C в main): старый
    # адрес перенаправляет на новый React Flow UI
    return RedirectResponse(url="/", status_code=307)


@app.get("/")
@app.get("/flow")
@app.get("/flow/{rest:path}")
def flow_page():
    # Главный маршрут и /flow — новый нодовый редактор (React Flow, сборка из
    # frontend/): SPA-фолбэк — любой подпуть отдаём index.html, ассеты приходят
    # через /static/flow/
    return FileResponse(Path(__file__).resolve().parent / "static" / "flow" / "index.html")


app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")


@app.exception_handler(Exception)
async def unhandled(request, exc):
    traceback.print_exc()
    return JSONResponse({"detail": f"Внутренняя ошибка: {exc}"}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    url = "http://127.0.0.1:8420"
    print(f"DesignAI Web: {url}")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    uvicorn.run(app, host="127.0.0.1", port=8420, log_level="warning")
