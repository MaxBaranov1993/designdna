"""Selection-scoped, preview-only AI editing for the DNA editor."""
from __future__ import annotations

import copy
import json
import re

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
    allowColor: bool = True


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
COLOR_FIELDS = {"background", "backgroundColor", "color", "fill", "stroke", "borderColor", "lineColor"}


def _is_color_field(field: str) -> bool:
    lowered = field.lower()
    return field in COLOR_FIELDS or any(token in lowered for token in ("color", "background", "fill", "stroke", "shadow"))


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
    def register(key: str, path: str):
        if key in result and result[key] != path:
            result[key] = ""  # ambiguous keys must never resolve last-write-wins
        else:
            result[key] = path
    def visit_prop(value, path: str):
        register(f"editor:{path}", path)
        if isinstance(value, dict):
            if value.get("sourceKey"): register(str(value["sourceKey"]), path)
            for key, child in value.items():
                visit_prop(child, f"{path}/{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value): visit_prop(child, f"{path}/{index}")
    def visit(node, path: str):
        if not isinstance(node, dict): return
        register(f"editor:{path}", path)
        if node.get("sourceKey"): register(str(node["sourceKey"]), path)
        if isinstance(node.get("props"), dict): visit_prop(node["props"], f"{path}/props")
        for index, child in enumerate(node.get("children") or []):
            visit(child, f"{path}/children/{index}")
    for index, section in enumerate(doc.get("tree") or []):
        visit(section, f"/tree/{index}")
    return result


def _normalized_scope(doc: dict, keys: list[str]) -> tuple[list[str], list[str], list[str]]:
    if not keys:
        raise ValueError("выберите хотя бы один элемент для AI")
    paths = _source_paths(doc)
    unique_keys = list(dict.fromkeys(keys))
    missing = [key for key in unique_keys if not paths.get(key)]
    if missing:
        raise ValueError("выделенные элементы больше не найдены или имеют неоднозначный sourceKey")
    selected = [(key, paths[key]) for key in unique_keys]
    dropped = [key for key, path in selected if any(path != other and other.startswith(path + "/") for _, other in selected)]
    kept = [(key, path) for key, path in selected if key not in dropped]
    return [path for _, path in kept], [key for key, _ in kept], dropped


def _scope_paths(doc: dict, keys: list[str]) -> list[str]:
    return _normalized_scope(doc, keys)[0]


def _inside(path: str, prefixes: list[str]) -> bool:
    return bool(prefixes) and any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes)


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
        target_value = _get(shadow, target)
        if not isinstance(target_value, dict):
            if viewport != "shared":
                raise ValueError("текстовое свойство нельзя менять только в одном viewport")
            content = [(group, value) for group, value in changes.items() if group in CONTENT_FIELDS]
            if len(changes) != 1 or len(content) != 1:
                raise ValueError("скалярный элемент поддерживает только одно текстовое изменение")
            _, value = content[0]
            if isinstance(value, (dict, list)):
                raise ValueError("текстовое свойство принимает только скалярное значение")
            op = {"op": "replace", "path": target, "after": copy.deepcopy(value), "reason": reason}
            _apply(shadow, op); ops.append(op)
            continue
        for group, values in changes.items():
            if group in ALLOWED_GROUPS:
                if not isinstance(values, dict): raise ValueError(f"{group} должен быть объектом")
                if group == "props" and any(isinstance(value, (dict, list)) for value in values.values()):
                    raise ValueError("структурные props нужно редактировать через выбранные вложенные элементы")
                group_path = f"{target}/{group}" if viewport == "shared" else f"{target}/responsive/{viewport}/{group}"
                _ensure_object(shadow, group_path, ops, reason)
                for key, value in values.items():
                    key = str(key).replace("~", "~0").replace("/", "~1")
                    path = f"{group_path}/{key}"
                    op = {"op": "replace" if _exists(shadow, path) else "add", "path": path, "after": copy.deepcopy(value), "reason": reason}
                    _apply(shadow, op); ops.append(op)
            elif group in CONTENT_FIELDS and viewport == "shared":
                if isinstance(values, (dict, list)):
                    raise ValueError("структурное изменение содержимого запрещено")
                if target.endswith("/parts/label") and group in {"text", "label", "value"}:
                    path = f"{target}/text"
                elif target.endswith("/parts/control") and group in {"text", "placeholder", "value"}:
                    path = f"{target}/placeholder"
                else:
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


def _effective_node_constraints(doc: dict, path: str) -> dict:
    value = doc
    found: list[dict] = []
    for part in _parts(path):
        if isinstance(value, dict) and isinstance(value.get("constraints"), dict):
            found.append(value["constraints"])
        try:
            value = value[int(part)] if isinstance(value, list) else value[part]
        except (KeyError, IndexError, TypeError, ValueError):
            break
    if isinstance(value, dict) and isinstance(value.get("constraints"), dict):
        found.append(value["constraints"])
    result: dict = {"intentLocks": []}
    for item in found:
        result["intentLocks"] = list(dict.fromkeys([*result["intentLocks"], *(item.get("intentLocks") or [])]))
        for key in ("allowedColors", "maxTextLength", "minWidth", "maxWidth", "minHeight", "maxHeight"):
            if key in item: result[key] = item[key]
    return result


def _locked_node_reason(doc: dict, path: str) -> str | None:
    """editable:false на целевом узле или его предке → AI-мутации запрещены.

    Raster fallback Source Import (canvas/iframe/shadow/url-mask) остаётся
    видимым и selectable, но content/geometry/style правки над ним не имеют
    смысла: слой — плоское изображение источника. Возвращает lockedReason.
    """
    value = doc
    chain = []
    for part in _parts(path):
        try:
            value = value[int(part)] if isinstance(value, list) else value[part]
        except (KeyError, IndexError, TypeError, ValueError):
            break
        chain.append(value)
    for item in chain:
        if isinstance(item, dict) and item.get("editable") is False:
            return str(item.get("lockedReason") or "editable:false")
    return None


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
        locked_reason = _locked_node_reason(base, path)
        if locked_reason:
            raise ValueError(f"слой заблокирован (editable:false): {locked_reason}")
        is_frame = "frame" in parts
        is_style = any(part in {"style", "styleBindings"} for part in parts)
        is_color = _is_color_field(parts[-1])
        is_content = parts[-1] in CONTENT_FIELDS or ("props" in parts and not is_frame and not is_style and not is_color)
        is_color_scaffold = op == "add" and raw.get("after") == {} and any(
            str(next_op.get("path") or "").startswith(path + "/")
            and _is_color_field(_parts(str(next_op.get("path") or ""))[-1])
            for next_op in ops if next_op is not raw
        )
        if is_frame and not req.constraints.allowFrame: raise ValueError("изменение layout запрещено")
        if is_style and not is_color and not is_color_scaffold and not req.constraints.allowStyle: raise ValueError("изменение стиля запрещено")
        if is_content and not req.constraints.allowContent: raise ValueError("изменение текста запрещено")
        if is_color and not req.constraints.allowColor: raise ValueError("изменение цвета запрещено")
        node_constraints = _effective_node_constraints(base, path)
        locks = set(node_constraints.get("intentLocks") or [])
        if is_content and "content" in locks: raise ValueError("текст защищён Intent Lock")
        if is_frame and "geometry" in locks: raise ValueError("геометрия защищена Intent Lock")
        if "responsive" in parts and "responsive" in locks: raise ValueError("адаптив защищён Intent Lock")
        if (is_style or is_color) and not is_color_scaffold and locks.intersection({"appearance", "brand"}): raise ValueError("внешний вид защищён Intent Lock")
        after = raw.get("after")
        if is_content and isinstance(after, str) and isinstance(node_constraints.get("maxTextLength"), int) and len(after) > node_constraints["maxTextLength"]:
            raise ValueError("текст длиннее ограничения maxTextLength")
        if is_color and node_constraints.get("allowedColors"):
            colors = re.findall(r"#[0-9a-fA-F]{3,8}", str(after))
            allowed_colors = {str(value).lower() for value in node_constraints["allowedColors"]}
            if any(color.lower() not in allowed_colors for color in colors): raise ValueError("цвет не входит в allowedColors")
        if is_frame and isinstance(after, (int, float)):
            limits = {"width": ("minWidth", "maxWidth"), "height": ("minHeight", "maxHeight")}.get(parts[-1])
            if limits:
                minimum, maximum = (node_constraints.get(limits[0]), node_constraints.get(limits[1]))
                if isinstance(minimum, (int, float)) and after < minimum: raise ValueError(f"{parts[-1]} меньше ограничения")
                if isinstance(maximum, (int, float)) and after > maximum: raise ValueError(f"{parts[-1]} больше ограничения")
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


def _is_high_impact_op(op: dict) -> bool:
    parts = _parts(str(op.get("path") or ""))
    broad_section_change = len(parts) <= 4 and any(part in {"frame", "style", "background", "layout", "direction"} for part in parts)
    return broad_section_change


def _adapt(base: dict, scope: AssistScope) -> tuple[dict, list[dict], str]:
    candidate = copy.deepcopy(base)
    paths = _scope_paths(candidate, scope.sourceKeys)
    for path in paths:
        node = _get(candidate, path)
        if not isinstance(node, dict):
            raise ValueError("адаптив недоступен для отдельного текстового свойства")
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
    _, safe_keys, _ = _normalized_scope(base, req.scope.sourceKeys)
    system = (
        "You are an AI visual editor. Return JSON only: {summary, commands}. Each command is "
        "{command:'update', targetSourceKey, viewport:'shared|tablet|mobile', changes, reason}. "
        "changes may contain frame, style, styleBindings, props, text, title, placeholder, value, label, name, alt, ariaLabel. "
        "Use only selected sourceKeys. Never change hierarchy, ids, types, sourceKeys, children, or array order. "
        "Preserve the current design and make the smallest coherent change. Obey the supplied constraints exactly."
    )
    scope = req.scope.model_dump() if hasattr(req.scope, "model_dump") else req.scope.dict()
    scope["sourceKeys"] = safe_keys
    constraints = req.constraints.model_dump() if hasattr(req.constraints, "model_dump") else req.constraints.dict()
    return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps({"action": req.action, "prompt": req.prompt, "scope": scope, "constraints": constraints, "ir": base}, ensure_ascii=False)}]


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
        _, _, dropped_scope = _normalized_scope(req.ir, req.scope.sourceKeys)
        if req.action == "adapt":
            candidate, ops, summary = _adapt(req.ir, req.scope)
            candidate, ops = _validate_apply(req.ir, ops, req)
        else:
            messages = _messages(req.ir, req)
            if req.prepareOnly: return {"messages": messages}
            raw = req.rawOutput if req.rawOutput is not None else llm.chat("auto", messages, 0.2, role="edit")
            candidate, ops, summary = _parse_result(raw, req.ir, req)
        ops = [op for op in ops if not (op.get("op") == "add" and op.get("after") == {})]
        warnings = []
        if dropped_scope:
            warnings.append({"code": "nested_scope_normalized", "message": "Родительский контейнер исключён: AI изменяет выбранные вложенные элементы."})
        if len(ops) > 8 or any(_is_high_impact_op(op) for op in ops):
            warnings.append({"code": "high_impact", "message": "AI предлагает много изменений. Проверьте diff перед применением."})
        return {"summary": summary, "ops": ops, "previewIr": candidate, "changedViewports": [], "warnings": warnings, "validation": {"schema": True, "overflow": [], "constraints": []}}
    except ValueError as exc: return _error(422, str(exc))
    except RuntimeError as exc:
        message = str(exc)
        return _error(429 if any(token in message.lower() for token in ("429", "лимит", "очеред")) else 504, message)
    except Exception as exc: return _error(502, f"AI assist недоступен: {exc}")
