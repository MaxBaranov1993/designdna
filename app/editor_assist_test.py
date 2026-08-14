"""Самопроверка AI-first Edit Node: preview, patch guard и атомарность контракта.

Сервер не запускается и внешний LLM не вызывается:
    .venv/Scripts/python app/editor_assist_test.py
"""
from __future__ import annotations

import copy
import pathlib
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from test_qualitygate import BASE_IR  # noqa: E402


FAILS: list[str] = []


def check(name: str, condition: bool, extra: str = "") -> None:
    tag = "OK " if condition else "FAIL"
    print(f"[{tag}] {name}" + (f" — {extra}" if extra and not condition else ""))
    if not condition:
        FAILS.append(name)


def status_of(result) -> int:
    return int(getattr(result, "status_code", 200))


def main() -> None:
    source = copy.deepcopy(BASE_IR)

    # Детерминированный adapt должен вернуть preview и не менять входной IR.
    before = copy.deepcopy(source)
    result = server.editor_assist(server.EditorAssistReq(
        ir=source,
        prompt="сделай макет адаптивным",
        action="adapt",
    ))
    check("adapt: HTTP success", status_of(result) == 200, str(status_of(result)))
    check("adapt: schema validation", isinstance(result, dict) and result["validation"]["schema"] is True)
    check("preview не мутирует входной IR", source == before)
    check("preview содержит IR", isinstance(result, dict) and isinstance(result.get("previewIr"), dict))

    selected_adapt = server.editor_assist(server.EditorAssistReq(
        ir=source,
        prompt="сделай выбранную карточку адаптивной",
        action="adapt",
        scope=server.EditorAssistScope(
            sourceKeys=["editor:/tree/2/children/1"],
            viewport="desktop",
        ),
    ))
    selected_card = selected_adapt["previewIr"]["tree"][2]["children"][1]
    check("adapt: selected card gets mobile fill", selected_card["responsive"]["mobile"]["frame"]["width"] == "fill")
    check("adapt: selected card reports mobile change", "mobile" in selected_adapt["changedViewports"])

    original_chat = server.llm.chat
    try:
        server.llm.chat = lambda *_args, **_kwargs: (
            '{"summary":"gap preview","ops":[{"op":"replace",'
            '"path":"/tree/0/frame/gap","before":24,"after":32,'
            '"reason":"Более ровный ритм"}]}'
        )
        custom = server.editor_assist(server.EditorAssistReq(
            ir=source,
            prompt="увеличь gap",
            action="custom",
        ))
        check("custom: patch preview", status_of(custom) == 200)
        check("custom: diff нормализован", isinstance(custom, dict) and custom["ops"][0]["after"] == 32)
        check("custom: изменённый IR только в preview", source["tree"][0]["frame"]["gap"] == 24)

        # A nested node path necessarily traverses `children`; that traversal is not
        # itself a structural mutation and must remain editable.
        nested_path = "/tree/2/children/1/frame/width"
        nested_candidate, _ = server._editor_validate_and_apply(
            source,
            [{"op": "replace", "path": nested_path, "after": 320, "reason": "nested frame"}],
            server.EditorAssistConstraints(),
        )
        check("nested frame path is allowed", nested_candidate["tree"][2]["children"][1]["frame"]["width"] == 320)

        # Pen-like semantic commands resolve sourceKey + viewport into safe IR ops,
        # including creation of missing responsive containers.
        command_base = server._editor_ensure_source_keys(server.ensure_current_ir(source, source="assist-test"))
        target = command_base["tree"][2]["children"][1]["sourceKey"]
        command_ops = server._editor_commands_to_ops(
            command_base,
            [{
                "command": "update",
                "targetSourceKey": target,
                "viewport": "mobile",
                "changes": {"frame": {"width": "fill", "minWidth": 0}},
                "reason": "mobile fill",
            }],
            server.EditorAssistScope(sourceKeys=[target], viewport="mobile"),
        )
        command_candidate, _ = server._editor_validate_and_apply(
            command_base, command_ops, server.EditorAssistConstraints()
        )
        mobile_frame = command_candidate["tree"][2]["children"][1]["responsive"]["mobile"]["frame"]
        check("semantic command creates mobile override", mobile_frame == {"width": "fill", "minWidth": 0})

        other_target = command_base["tree"][0]["sourceKey"]
        try:
            server._editor_commands_to_ops(
                command_base,
                [{"command": "update", "targetSourceKey": other_target, "changes": {"frame": {"gap": 8}}}],
                server.EditorAssistScope(sourceKeys=[target], viewport="mobile"),
            )
            outside_scope_blocked = False
        except ValueError:
            outside_scope_blocked = True
        check("semantic command cannot escape selection", outside_scope_blocked)

        server.llm.chat = lambda *_args, **_kwargs: (
            '{"summary":"unsafe","ops":[{"op":"replace",'
            '"path":"/tree/0/type","before":"navbar","after":"card",'
            '"reason":"Нельзя менять тип"}]}'
        )
        blocked = server.editor_assist(server.EditorAssistReq(
            ir=source,
            prompt="измени тип",
            action="custom",
        ))
        check("structure guard: type change rejected", status_of(blocked) == 422)
    finally:
        server.llm.chat = original_chat

    if FAILS:
        print("FAILURES:", len(FAILS))
        for failure in FAILS:
            print(" -", failure)
        raise SystemExit(1)
    print("ALL EDITOR ASSIST CHECKS PASSED")


if __name__ == "__main__":
    main()
