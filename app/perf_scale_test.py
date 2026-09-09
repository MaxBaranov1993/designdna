"""Production-shaped масштабное профилирование (1000 и 5000 нод).

Замеряет p95 критических путей на синтетических графах production-формы:
  - autosave: save_project с единичным изменением между сейвами
    (сериализация + SHA-256 + SQLite-запись + taste-profile);
  - CAS-коммит: commit_project по актуальной ревизии (http /api/project/save
    с expectedRevision);
  - load: inspect_project с миграцией payload;
  - AI-payload: editor_assist._messages на большом IR с узким выделением
    (обрезка до выбранного поддерева).

Бюджеты — сознально мягкие (ловят порядок деградации, не шумят в CI);
фактические числа печатаются строками PROFILE. Жёсткие гейты из
архитектурного решения (autosave p95 ≤ 250 мс, propagation/render p95
≤ 100 мс) оцениваются по выведенным числам, а не ассертами.
"""
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

import project_store
from editor_assist import AssistRequest, _messages

FIXTURE = Path(__file__).parent / "fixtures" / "frame-example.json"


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, round(0.95 * (len(ordered) - 1))))
    return ordered[index]


def _build_project(node_count: int) -> dict:
    """Граф production-формы: цепочки prompt → generator → edit; каждый
    десятый узел несёт полноценный IR (типично для страницы с миксами и
    правками), остальные — лёгкие данные параметров."""
    sections = json.loads(FIXTURE.read_text(encoding="utf-8"))["tree"]
    nodes: list[dict] = []
    edges: list[dict] = []
    for i in range(1, node_count + 1):
        kind = i % 10
        if kind == 0:
            nodes.append({
                "id": i, "type": "edit", "x": (i % 40) * 60, "y": (i // 40) * 140,
                "data": {"ir": {"tree": json.loads(json.dumps(sections)), "tokens": {}},
                         "prompt": f"правка {i}"},
            })
            edges.append({"from": i - 1, "to": i, "port": "ir"})
        elif kind == 5:
            nodes.append({
                "id": i, "type": "generator", "x": (i % 40) * 60, "y": (i // 40) * 140,
                "data": {"brief": f"сгенерируй секцию {i}", "variants": []},
            })
            edges.append({"from": i - 1, "to": i, "port": "ir"})
        else:
            nodes.append({
                "id": i, "type": "prompt", "x": (i % 40) * 60, "y": (i // 40) * 140,
                "data": {"text": f"бриф {i} " + "x" * 80},
            })
            if i > 1:
                edges.append({"from": i - 1, "to": i, "port": "ir"})
    return {
        "version": "designai-pages-v1",
        "activePageId": "page-1",
        "pages": [{
            "id": "page-1", "name": "Scale",
            "graph": {"nodes": nodes, "edges": edges, "view": {"x": 0, "y": 0, "zoom": 1}, "nextId": node_count + 1},
        }],
        "channels": {},
    }


def _build_large_ir(section_count: int) -> tuple[dict, list[str]]:
    """Большой IR с sourceKey на каждом узле — форма DNA-редактора.
    Возвращает IR и три валидных ключа выделения (секция, вложенный узел,
    последняя секция)."""
    sections = json.loads(FIXTURE.read_text(encoding="utf-8"))["tree"]
    tree = []
    index = 0
    sample_keys: list[str] = []
    for copy_number in range(section_count):
        for section in json.loads(json.dumps(sections)):
            index += 1
            section["sourceKey"] = f"sec:{index}"
            if not sample_keys:
                sample_keys.append(section["sourceKey"])
            def visit(node):
                nonlocal index
                index += 1
                node["sourceKey"] = f"n:{index}"
                if len(sample_keys) == 1 and (node.get("children") or []):
                    sample_keys.append(node["sourceKey"])
                for child in node.get("children") or []:
                    visit(child)
            for child in section.get("children") or []:
                visit(child)
            tree.append(section)
    sample_keys.append(tree[-1]["sourceKey"])
    return {"version": "1.0", "tokens": {"color": {"bg": {"value": "#101014"}}}, "tree": tree}, sample_keys


def _profile_backend(node_count: int, samples: int) -> dict[str, float]:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        old_db = project_store.DB_PATH
        project_store.DB_PATH = Path(td) / "projects.db"
        payload = _build_project(node_count)
        try:
            project_store.save_project(payload)

            save_times: list[float] = []
            for sample in range(samples):
                payload["pages"][0]["graph"]["nodes"][sample % node_count]["data"]["text"] = f"бриг {sample}"
                t0 = time.perf_counter()
                project_store.save_project(payload)
                save_times.append(time.perf_counter() - t0)

            revision = project_store.inspect_project()["revision"]
            cas_times: list[float] = []
            for sample in range(samples):
                payload["pages"][0]["graph"]["nodes"][sample % node_count]["data"]["text"] = f"cas {sample}"
                t0 = time.perf_counter()
                result = project_store.commit_project(payload, revision)
                cas_times.append(time.perf_counter() - t0)
                assert result.get("ok"), result
                revision = str(result.get("revision") or revision)

            load_times: list[float] = []
            for _ in range(max(3, samples // 2)):
                t0 = time.perf_counter()
                project_store.inspect_project()
                load_times.append(time.perf_counter() - t0)

            return {
                "autosave_p95": _p95(save_times),
                "cas_p95": _p95(cas_times),
                "load_p95": _p95(load_times),
                "autosave_median": statistics.median(save_times),
            }
        finally:
            project_store.DB_PATH = old_db


def _profile_prompt(section_count: int, samples: int) -> dict[str, float]:
    base, keys = _build_large_ir(section_count)
    req = AssistRequest(ir=base, prompt="перепиши тексты выделения", action="custom",
                        scope={"sourceKeys": keys, "viewport": "desktop"})
    times: list[float] = []
    sizes: list[int] = []
    for _ in range(samples):
        t0 = time.perf_counter()
        messages = _messages(base, req)
        times.append(time.perf_counter() - t0)
        sizes.append(len(messages[1]["content"]))
    full_size = len(json.dumps(base, ensure_ascii=False))
    return {"prompt_build_p95": _p95(times), "prompt_bytes": max(sizes), "full_ir_bytes": full_size}


def test_scale_profile_1000_and_5000_nodes() -> None:
    for node_count, samples in ((1000, 12), (5000, 6)):
        backend = _profile_backend(node_count, samples)
        print(f"PROFILE nodes={node_count} autosave_p95={backend['autosave_p95']*1000:.0f}ms "
              f"autosave_median={backend['autosave_median']*1000:.0f}ms "
              f"cas_p95={backend['cas_p95']*1000:.0f}ms load_p95={backend['load_p95']*1000:.0f}ms")
        # мягкие CI-потолки: ловим порядок деградации, не джиттер
        ceiling = 3.0 if node_count == 5000 else 1.0
        assert backend["autosave_p95"] < ceiling, f"autosave p95 {backend['autosave_p95']:.2f}s @ {node_count}"
        assert backend["cas_p95"] < ceiling, f"CAS p95 {backend['cas_p95']:.2f}s @ {node_count}"

    prompt = _profile_prompt(section_count=120, samples=10)
    print(f"PROFILE prompt sections=120 build_p95={prompt['prompt_build_p95']*1000:.0f}ms "
          f"payload={prompt['prompt_bytes']//1024}KB full_ir={prompt['full_ir_bytes']//1024}KB")
    assert prompt["prompt_build_p95"] < 1.0
    # обрезка обязана давать кратный выигрыш против полного IR
    assert prompt["prompt_bytes"] * 4 < prompt["full_ir_bytes"], (
        f"payload {prompt['prompt_bytes']}B почти не меньше полного IR {prompt['full_ir_bytes']}B")


if __name__ == "__main__":
    test_scale_profile_1000_and_5000_nodes()
    print("ALL SCALE PROFILE CHECKS PASSED")
