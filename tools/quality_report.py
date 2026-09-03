#!/usr/bin/env python3
"""Reproducible T6 visual-quality benchmark and exemplar audit.

Dry-run renders the ten curated exemplars and performs every local check without
network access.  The default live mode additionally generates a controlled
before/after pair for five fixed briefs and asks the pixel vision judge to score
the pairs and every exemplar.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
sys.path.insert(0, str(APP))

import llm_client as llm  # noqa: E402
import qualitygate  # noqa: E402
from ir import format_errors, sanitize_generated_ir, validate_ir  # noqa: E402
from ir_render import render_png  # noqa: E402


DEFAULT_REPORT = ROOT / "results" / "quality-report.md"
DEFAULT_ASSETS = ROOT / "results" / "quality-report-assets"
MAX_PNG_BYTES = 400 * 1024
MIN_EXEMPLAR_SCORE = 90


@dataclass(frozen=True)
class Brief:
    slug: str
    product: str
    text: str
    exemplars: tuple[str, ...]


BRIEFS = (
    Brief("saas", "SaaS", "Лендинг SaaS-платформы для сменного планирования на производстве: показать платёжный продукт через рабочий график, правила и внедрение.", ("saas-landing", "fintech")),
    Brief("marketplace", "Маркетплейс", "Маркетплейс проверенного промышленного оборудования: покупателю нужны состояние станка, порядок торгов, логистика и ответственность площадки.", ("marketplace", "saas-landing")),
    Brief("restaurant", "Ресторан", "Небольшой винный бар с сезонной кухней: меню на сегодня, характер погреба, честные правила брони и один ясный путь к столу.", ("restaurant", "ecommerce")),
    Brief("portfolio", "Портфолио", "Портфолио предметного дизайнера: один сильный кейс, процесс от наблюдения до серии и спокойный контакт для нового проекта.", ("portfolio", "real-estate")),
    Brief("fintech", "Финтех", "B2B-финтех для платёжного календаря группы компаний: кассовые разрывы, согласование, интеграции и измеримый план внедрения.", ("fintech", "saas-landing")),
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _all_exemplars() -> list[Path]:
    return sorted((APP / "exemplars").glob("*.json"))


def _walk(nodes: list[dict[str, Any]]):
    for node in nodes:
        yield node
        children = node.get("children")
        if isinstance(children, list):
            yield from _walk(children)


def _slop_check(ir: dict[str, Any]) -> list[str]:
    """Mechanical half of the RUBRIC checklist; visual items stay human-reviewed."""
    problems: list[str] = []
    nodes = list(_walk(ir.get("tree") or []))
    empty_images = [n for n in nodes if n.get("type") == "image" and not n.get("imagePrompt")]
    if empty_images:
        problems.append(f"{len(empty_images)} image placeholders without art direction")
    pills = [n for n in nodes if n.get("variant") == "pill"]
    if len(pills) > 3:
        problems.append(f"pill repetition ({len(pills)})")
    cards = [n for n in nodes if n.get("type") == "card"]
    if len(cards) > 6:
        problems.append(f"uniform card scatter ({len(cards)})")
    labels = [str(n.get("text") or n.get("title") or "").strip() for n in nodes]
    repeated = {label for label in labels if label and labels.count(label) > 2}
    if repeated:
        problems.append("repeated copy: " + ", ".join(sorted(repeated)[:3]))
    return problems


def _save_png(data: bytes, path: Path) -> int:
    """Keep report images bounded while retaining PNG and a 1440px render."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if len(data) <= MAX_PNG_BYTES:
        path.write_bytes(data)
        return len(data)
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        compact = image.convert("RGB").quantize(colors=128)
        compact.save(path, format="PNG", optimize=True)
    return path.stat().st_size


def _deterministic_record(path: Path, assets_dir: Path) -> dict[str, Any]:
    ir = _load(path)
    schema = format_errors(validate_ir(ir))
    unchanged = sanitize_generated_ir(ir) == ir
    gate = qualitygate.check(ir)
    slop = _slop_check(ir)
    png_path = assets_dir / "exemplars" / f"{path.stem}.png"
    png_size = _save_png(render_png(ir, width=1440), png_path)
    return {
        "name": path.stem,
        "ir": ir,
        "schema": schema,
        "sanitize_unchanged": unchanged,
        "qualitygate": gate,
        "slop": slop,
        "png": png_path,
        "png_size": png_size,
    }


def _exemplar_block(names: tuple[str, ...]) -> str:
    chunks: list[str] = []
    for name in names:
        document = _load(APP / "exemplars" / f"{name}.json")
        body, dropped = llm.fit_exemplar(document)
        direction = (document.get("meta") or {}).get("direction") or {}
        note = f"; tail sections omitted: {dropped}" if dropped else ""
        chunks.append(
            f"### exemplar: {name} · направление «{direction.get('name', name)}»{note}\n"
            f"```json\n{body}\n```"
        )
    return "\n\n".join(chunks)


def _generate(brief: Brief, *, with_exemplars: bool) -> dict[str, Any]:
    examples = _exemplar_block(brief.exemplars) if with_exemplars else ""
    system = llm.build_system_prompt("generate", exemplars=examples)
    phase = "after: use the supplied product exemplars as craft anchors" if with_exemplars else "before: no exemplar context"
    raw = llm.chat(
        "auto",
        [
            {"role": "system", "content": system},
            {"role": "user", "content": f"## Fixed benchmark brief\n{brief.text}\n\n## Controlled condition\n{phase}\n\nReturn one complete Design IR JSON document."},
        ],
        0.6,
        role="generator",
        reasoning_effort="high",
    )
    parsed = json.loads(llm.extract_json(raw))
    parsed = sanitize_generated_ir(parsed)
    parsed, _ = qualitygate.autofix(parsed)
    errors = format_errors(validate_ir(parsed))
    if errors:
        raise ValueError("generated IR does not pass schema: " + "; ".join(errors[:5]))
    return parsed


def _judge(ir: dict[str, Any], brief: str) -> dict[str, Any]:
    # Importing server is delayed so --dry-run never depends on provider config.
    import server

    return server._quality_scorecard(ir, brief)


def _live_pairs(assets_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for brief in BRIEFS:
        row: dict[str, Any] = {"brief": brief}
        for condition, with_exemplars in (("before", False), ("after", True)):
            # Провал одного условия (невалидный IR, таймаут CLI) — строка отчёта,
            # а не обрыв всего прогона: остальные брифы и эталоны важнее.
            try:
                ir = _generate(brief, with_exemplars=with_exemplars)
                png = assets_dir / "briefs" / f"{brief.slug}-{condition}.png"
                size = _save_png(render_png(ir, width=1440), png)
                row[condition] = {"ir": ir, "png": png, "png_size": size, "scorecard": _judge(ir, brief.text)}
            except Exception as exc:  # noqa: BLE001 — отчёт должен пережить любой сбой условия
                row[condition] = {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}
                print(f"[{brief.slug}/{condition}] failed: {row[condition]['error']}", file=sys.stderr)
        rows.append(row)
    return rows


def _relative(path: Path, report: Path) -> str:
    return Path(os.path.relpath(path, report.parent)).as_posix()


def _render_report(report: Path, deterministic: list[dict[str, Any]], live: list[dict[str, Any]] | None, live_error: str | None) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Design Studio v3 — quality report",
        "",
        f"Generated: {stamp}. Render width: 1440 px. Exemplar target: vision score ≥{MIN_EXEMPLAR_SCORE}.",
        "",
        "## Fixed five-brief benchmark",
        "",
        "`before` is a controlled ablation of exemplar context; `after` uses the same current prompt and the two named product exemplars. This is not presented as a historical score.",
        "",
        "| Product | Before PNG | Before score | After PNG | After score | Delta |",
        "|---|---|---:|---|---:|---:|",
    ]
    if live:
        def cell(item):
            if "error" in item:
                return f"failed: {item['error']}", None
            return f"[PNG]({_relative(item['png'], report)})", int(item["scorecard"]["score"])
        for row in live:
            b_png, bs = cell(row["before"]); a_png, after_score = cell(row["after"])
            delta = f"{after_score - bs:+d}" if bs is not None and after_score is not None else "—"
            lines.append(f"| {row['brief'].product} | {b_png} | {bs if bs is not None else '—'} | {a_png} | {after_score if after_score is not None else '—'} | {delta} |")
        before_scores = [int(row["before"]["scorecard"]["score"]) for row in live if "scorecard" in row["before"]]
        after_scores = [int(row["after"]["scorecard"]["score"]) for row in live if "scorecard" in row["after"]]
        if before_scores and after_scores:
            lines += ["", f"Median: **{statistics.median(before_scores):g} → {statistics.median(after_scores):g}** (пар с оценкой: {min(len(before_scores), len(after_scores))} из {len(live)})."]
        else:
            lines += ["", "Median: — (ни одной полной пары до/после)."]
    else:
        for brief in BRIEFS:
            lines.append(f"| {brief.product} | not run | not run | not run | not run | not run |")
        lines += ["", "Live generation and vision scoring: **not run / ожидает ключей**."]
        if live_error:
            lines.append(f"Reason: `{live_error}`")

    lines += [
        "",
        "## Exemplar library",
        "",
        f"Count: **{len(deterministic)}**. Live score cells remain `not run` until a configured vision provider executes the default mode.",
        "",
        "| Exemplar | PNG | Schema | Sanitize stable | Quality gate | Slop checklist | Vision score |",
        "|---|---|---|---|---|---|---:|",
    ]
    for item in deterministic:
        schema = "pass" if not item["schema"] else "fail"
        stable = "pass" if item["sanitize_unchanged"] else "fail"
        gate = "pass" if not item["qualitygate"] else "fail"
        slop = "pass" if not item["slop"] else "fail"
        score = item.get("scorecard", {}).get("score", "not run")
        lines.append(f"| {item['name']} | [PNG]({_relative(item['png'], report)}) | {schema} | {stable} | {gate} | {slop} | {score} |")

    lines += [
        "",
        "## Verification contract",
        "",
        "Dry-run guarantees valid Design IR, byte-stable sanitize, an empty deterministic quality gate, bounded PNG evidence, and a mechanical check for the RUBRIC slop tropes (empty imagery, excessive pills/cards, repeated copy). Visual hierarchy, rhythm, density, typography and brief fit remain the vision judge's responsibility.",
        "",
        "Operator command with credentials:",
        "",
        "```powershell",
        ".venv\\Scripts\\python tools/quality_report.py",
        "```",
        "",
        f"The live command exits non-zero if an exemplar scores below {MIN_EXEMPLAR_SCORE}, a local check fails, or a report PNG exceeds {MAX_PNG_BYTES // 1024} KiB.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="render exemplars and run local checks without LLM/vision calls")
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--assets-dir", type=Path, default=DEFAULT_ASSETS)
    args = parser.parse_args()
    report = args.output.resolve()
    assets = args.assets_dir.resolve()

    exemplars = [_deterministic_record(path, assets) for path in _all_exemplars()]
    local_failures = [item["name"] for item in exemplars if item["schema"] or not item["sanitize_unchanged"] or item["qualitygate"] or item["slop"] or item["png_size"] > MAX_PNG_BYTES]

    live: list[dict[str, Any]] | None = None
    live_error: str | None = None
    if not args.dry_run:
        # Живой режим: API-ключ OpenAI ИЛИ консольный аккаунт Codex/Claude (cli_llm)
        import cli_llm  # noqa: WPS433 — app/ уже в sys.path
        cli_provider = cli_llm.default_provider()
        if not os.getenv("OPENAI_API_KEY") and not cli_provider:
            live_error = "no provider: set OPENAI_API_KEY or sign in to Codex CLI / Claude Code"
        else:
            print(f"live provider: {'openai api' if os.getenv('OPENAI_API_KEY') else cli_provider}")
            try:
                live = _live_pairs(assets)
                for item in exemplars:
                    item["scorecard"] = _judge(item["ir"], str((item["ir"].get("meta") or {}).get("description") or item["name"]))
            except Exception as exc:  # report partial provider failure without hiding it
                live = None
                live_error = f"{type(exc).__name__}: {exc}"

    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(_render_report(report, exemplars, live, live_error), encoding="utf-8")
    print(f"report: {report}")
    print(f"exemplars: {len(exemplars)}; local failures: {len(local_failures)}")
    if local_failures:
        print("failed: " + ", ".join(local_failures), file=sys.stderr)
        return 1
    if not args.dry_run and live is None:
        print("live benchmark not run: " + str(live_error), file=sys.stderr)
        return 2
    if live is not None:
        low = [item["name"] for item in exemplars if int(item["scorecard"]["score"]) < MIN_EXEMPLAR_SCORE]
        if low:
            print(f"exemplar vision score below {MIN_EXEMPLAR_SCORE}: " + ", ".join(low), file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
