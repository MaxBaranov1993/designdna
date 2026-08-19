"""Selection-scoped, preview-only AI editing for the DNA editor."""
from __future__ import annotations

import copy
import json

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import ir
import llm_client as llm

router = APIRouter()


class AssistScope(BaseModel):
    sourceKeys: list[str] = Field(default_factory=list)
    viewport: str = "desktop"


class AssistConstraints(BaseModel):
    allowStructure: bool = False
    allowContent: bool = True
    allowStyle: bool = True
    allowFrame: bool = True


class AssistRequest(BaseModel):
    ir: dict
    prompt: str = ""
    action: str = "custom"
    scope: AssistScope = Field(default_factory=AssistScope)
    constraints: AssistConstraints = Field(default_factory=AssistConstraints)
    prepareOnly: bool = False
    rawOutput: str | None = None


ALLOWED_ACTIONS = {"adapt", "overflow", "content-fit", "align", "style", "custom"}
ALLOWED_VIEWPORTS = {"desktop", "tablet", "mobile", "all", "current"}
FORBIDDEN_FIELDS = {"id", "type", "sourceKey", "children", "tree"}
ALLOWED_GROUPS = {"frame", "style", "styleBindings", "props"}
CONTENT_FIELDS = {"text", "title", "placeholder", "value", "label", "name", "alt", "ariaLabel"}


def _error(status: int, message: str):
    return JSONResponse({"detail": message}, status_code=status)


def _parts(path: str) -> list[str]:
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("patch path должен быть JSON Pointer")
    return [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/") if part]


def _get(doc, path: str):
    value = doc
    for part in _parts(path):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def _exists(doc, path: str) -> bool:
    try:
        _get(doc, path)
        return True
    except (KeyError, IndexError, TypeError, ValueError):
        return False


def _apply(doc, operation: dict) -> None:
    parts = _parts(operation["path"])
    if not parts:
        raise ValueError("изменение корневого IR запрещено")
    parent = doc
    for part in parts[:-1]:
        parent = parent[int(part)] if isinstance(parent, list) else parent[part]
    last = parts[-1]
    if operation["op"] in {"add", "replace"}:
        if isinstance(parent, list):
            if operation["op"] == "add": parent.insert(int(last), copy.deepcopy(operation.get("after")))
            else: parent[int(last)] = copy.deepcopy(operation.get("after"))
        else: parent[last] = copy.deepcopy(operation.get("after"))
    elif operation["op"] == "remove":
        if isinstance(parent, list): parent.pop(int(last))
        else: parent.pop(last, None)
    else:
        raise ValueError("поддерживаются только add, replace и remove")


def _source_paths(doc: dict) -> dict[str, str]:
    result: dict[str, str] = {}
    def visit(node, path: str):
        if not isinstance(node, dict): return
        key = str(node.get("sourceKey") or f"editor:{path}")
        result[key] = path
        for index, child in enumerate(node.get("children") or []):
            visit(child, f"{path}/children/{index}")
    for index, section in enumerate(doc.get("tree") or []):
        visit(section, f"/tree/{index}")
    return result


def _scope_paths(doc: dict, keys: list[str]) -> list[str]:
    paths = _source_paths(doc)
    selected = [paths[key] for key in keys if key in paths]
    if keys and not selected:
        raise ValueError("выделенные элементы больше не найдены в документе")
    return selected


def _inside(path: str, prefixes: list[str]) -> bool:
    return not prefixes or any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes)


def _ensure_object(shadow: dict, path: str, ops: list[dict], reason: str) -> None:
    parts = _parts(path)
    for end in range(1, len(parts) + 1):
        current = "/" + "/".join(part.replace("~", "~0").replace("/", "~1") for part in parts[:end])
        if _exists(shadow, current): continue
        op = {"op": "add", "path": current, "after": {}, "reason": reason}
        _apply(shadow, op); ops.append(op)


def _commands_to_ops(base: dict, commands: list, scope: AssistScope) -> list[dict]:
    if not isinstance(commands, list) or len(commands) > 60:
        raise ValueError("AI должен вернуть список до 60 команд")
    paths = _source_paths(base)
    allowed = _scope_paths(base, scope.sourceKeys)
    shadow = copy.deepcopy(base)
    ops: list[dict] = []
    for command in commands:
        if not isinstance(command, dict) or command.get("command") != "update":
            raise ValueError("поддерживается только команда update")
        target = paths.get(str(command.get("targetSourceKey") or ""))
        if not target: raise ValueError("AI указал неизвестный элемент")
        if not _inside(target, allowed): raise ValueError("AI попытался изменить элемент вне текущего выделения")
        viewport = str(command.get("viewport") or scope.viewport).lower()
        if viewport in {"current", "desktop", "all"}: viewport = "shared"
        if viewport not in {"shared", "tablet", "mobile"}: raise ValueError("неизвестный viewport команды")
        changes = command.get("changes")
        if not isinstance(changes, dict) or not changes: raise ValueError("команда update не содержит changes")
        reason = str(command.get("reason") or "").strip()
        for group, values in changes.items():
            if group in ALLOWED_GROUPS:
                if not isinstance(values, dict): raise ValueError(f"{group} должен быть объектом")
                group_path = f"{target}/{group}" if viewport == "shared" else f"{target}/responsive/{viewport}/{group}"
                _ensure_object(shadow, group_path, ops, reason)
                for key, value in values.items():
                    key = str(key).replace("~", "~0").replace("/", "~1")
                    path = f"{group_path}/{key}"
                    op = {"op": "replace" if _exists(shadow, path) else "add", "path": path, "after": copy.deepcopy(value), "reason": reason}
                    _apply(shadow, op); ops.append(op)
            elif group in CONTENT_FIELDS and viewport == "shared":
                path = f"{target}/{group}"
                op = {"op": "replace" if _exists(shadow, path) else "add", "path": path, "after": copy.deepcopy(values), "reason": reason}
                _apply(shadow, op); ops.append(op)
            else: raise ValueError(f"недопустимая группа изменения: {group}")
    return ops


def _structure(doc: dict) -> list[tuple]:
    result = []
    def visit(node, path):
        if not isinstance(node, dict): return
        result.append((path, node.get("id"), node.get("type"), node.get("sourceKey")))
        for index, child in enumerate(node.get("children") or []): visit(child, f"{path}/children/{index}")
    for index, section in enumerate(doc.get("tree") or []): visit(section, f"/tree/{index}")
    return result


def _validate_apply(base: dict, ops: list[dict], req: AssistRequest) -> tuple[dict, list[dict]]:
    if len(ops) > 100: raise ValueError("слишком много изменений")
    allowed = _scope_paths(base, req.scope.sourceKeys)
    candidate = copy.deepcopy(base)
    normalized = []
    for raw in ops:
        op, path = str(raw.get("op")), str(raw.get("path"))
        parts = _parts(path)
        if op not in {"add", "remove", "replace"} or not parts or parts[0] != "tree": raise ValueError(f"недопустимая операция: {path}")
        if not _inside(path, allowed): raise ValueError("AI попытался изменить элемент вне текущего выделения")
        if parts[-1] in FORBIDDEN_FIELDS or (len(parts) > 1 and parts[-2] in {"children", "tree"}):
            raise ValueError(f"структурное изменение запрещено: {path}")
        if "frame" in parts and not req.constraints.allowFrame: raise ValueError("изменение layout запрещено")
        if any(part in {"style", "styleBindings"} for part in parts) and not req.constraints.allowStyle: raise ValueError("изменение стиля запрещено")
        operation = {"op": op, "path": path, "before": copy.deepcopy(_get(base, path)) if op != "add" and _exists(base, path) else None, "after": copy.deepcopy(raw.get("after")), "reason": str(raw.get("reason") or "")}
        _apply(candidate, operation); normalized.append(operation)
    if _structure(base) != _structure(candidate): raise ValueError("AI изменил структуру дерева")
    errors = ir.format_errors(ir.validate_ir(candidate))
    if errors: raise ValueError("AI создал невалидный IR: " + "; ".join(errors[:4]))
    return candidate, normalized


def _diff(before, after, path="") -> list[dict]:
    if isinstance(before, dict) and isinstance(after, dict):
        result = []
        for key in dict.fromkeys([*before.keys(), *after.keys()]):
            child = f"{path}/{str(key).replace('~', '~0').replace('/', '~1')}"
            if key not in after: result.append({"op": "remove", "path": child, "before": copy.deepcopy(before[key])})
            elif key not in before: result.append({"op": "add", "path": child, "after": copy.deepcopy(after[key])})
            else: result.extend(_diff(before[key], after[key], child))
        return result
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        result = []
        for index, (left, right) in enumerate(zip(before, after)):
            result.extend(_diff(left, right, f"{path}/{index}"))
        return result
    if before != after: return [{"op": "replace", "path": path, "before": copy.deepcopy(before), "after": copy.deepcopy(after)}]
    return []


def _adapt(base: dict, scope: AssistScope) -> tuple[dict, list[dict], str]:
    candidate = copy.deepcopy(base)
    paths = _scope_paths(candidate, scope.sourceKeys)
    for path in paths:
        node = _get(candidate, path)
        frame = node.get("frame") if isinstance(node.get("frame"), dict) else {}
        responsive = node.setdefault("responsive", {})
        mobile = responsive.setdefault("mobile", {}).setdefault("frame", {})
        mobile.setdefault("width", "fill"); mobile.setdefault("minWidth", 0)
        if frame.get("layout") == "auto" and frame.get("direction") == "row":
            mobile.setdefault("direction", "column"); mobile.setdefault("align", "stretch")
        tablet = responsive.setdefault("tablet", {}).setdefault("frame", {})
        if isinstance(frame.get("width"), (int, float)) and frame["width"] > 720:
            tablet.setdefault("width", "fill"); tablet.setdefault("minWidth", 0)
    ops = [op for op in _diff(base, candidate) if _inside(op["path"], paths)][:100]
    return candidate, ops, "Адаптивные настройки выделения подготовлены"


def _messages(base: dict, req: AssistRequest) -> list[dict]:
    system = (
        "You are an AI visual editor. Return JSON only: {summary, commands}. Each command is "
        "{command:'update', targetSourceKey, viewport:'shared|tablet|mobile', changes, reason}. "
        "changes may contain frame, style, styleBindings, props, text, title, placeholder, value, label, name, alt, ariaLabel. "
        "Use only selected sourceKeys. Never change hierarchy, ids, types, sourceKeys, children, or array order. "
        "Preserve the current design and make the smallest coherent change."
    )
    scope = req.scope.model_dump() if hasattr(req.scope, "model_dump") else req.scope.dict()
    return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps({"action": req.action, "prompt": req.prompt, "scope": scope, "ir": base}, ensure_ascii=False)}]


def _parse_result(raw: str, base: dict, req: AssistRequest):
    parsed = json.loads(llm.extract_json(raw))
    if not isinstance(parsed, dict): raise ValueError("AI вернул не объект")
    ops = _commands_to_ops(base, parsed.get("commands", []), req.scope)
    candidate, ops = _validate_apply(base, ops, req)
    return candidate, ops, str(parsed.get("summary") or "Изменения готовы")


@router.post("/api/editor/assist")
def editor_assist(req: AssistRequest):
    if req.action not in ALLOWED_ACTIONS: return _error(422, "Неизвестное AI-действие")
    if req.scope.viewport not in ALLOWED_VIEWPORTS: return _error(422, "Неизвестный viewport")
    if not req.prompt.strip(): return _error(422, "Опишите, что нужно изменить")
    errors = ir.format_errors(ir.validate_ir(req.ir))
    if errors: return _error(422, "IR не проходит schema: " + "; ".join(errors[:4]))
    try:
        if req.action == "adapt":
            candidate, ops, summary = _adapt(req.ir, req.scope)
            candidate, ops = _validate_apply(req.ir, ops, req)
        else:
            messages = _messages(req.ir, req)
            if req.prepareOnly: return {"messages": messages}
            raw = req.rawOutput if req.rawOutput is not None else llm.chat("auto", messages, 0.2, role="edit", priority="high")
            candidate, ops, summary = _parse_result(raw, req.ir, req)
        return {"summary": summary, "ops": ops, "previewIr": candidate, "changedViewports": [], "warnings": [], "validation": {"schema": True, "overflow": [], "constraints": []}}
    except ValueError as exc: return _error(422, str(exc))
    except llm.AIRequestError as exc: return _error(429 if exc.reason in {"очередь", "лимит провайдера"} else 504, exc.reason)
    except Exception as exc: return _error(502, f"AI assist недоступен: {exc}")
