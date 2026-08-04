#!/usr/bin/env python3
"""Валидация Design IR против schema/design-ir.schema.json.

Использование:
    python validate.py result.json
    python validate.py results/          # все *.json в папке

Зависимости: pip install jsonschema
Выход: 0 — все файлы валидны, 1 — есть ошибки.
"""
import json
import sys
from pathlib import Path

try:
    import jsonschema
except ImportError:
    sys.exit("pip install jsonschema")

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "schema" / "design-ir.schema.json").read_text(encoding="utf-8"))


def validate_file(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"FAIL {path.name}: не JSON — {e}")
        return False
    errors = sorted(jsonschema.Draft7Validator(SCHEMA).iter_errors(data), key=lambda e: list(e.path))
    if not errors:
        print(f"OK   {path.name}")
        return True
    print(f"FAIL {path.name}: {len(errors)} ошибок")
    for e in errors[:10]:
        loc = "/".join(str(p) for p in e.absolute_path) or "<root>"
        print(f"     - {loc}: {e.message}")
    return False


def main() -> int:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    target = Path(sys.argv[1])
    files = sorted(target.glob("*.json")) if target.is_dir() else [target]
    if not files:
        sys.exit(f"Нет json-файлов: {target}")
    results = [validate_file(f) for f in files]  # без all(): не обрываться на первом FAIL
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
