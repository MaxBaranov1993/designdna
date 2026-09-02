from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm_client


PROMPT_FILES = (
    "spike/system-prompt.md", "schema/design-ir.schema.json",
    "app/prompts/BLOCKS.md", "app/prompts/DESIGN.md",
)


def _copy_prompt_root(tmp_path: Path) -> Path:
    """Копия четырёх промпт-файлов в tmp_path, чтобы не трогать репозиторий."""
    source = Path(__file__).resolve().parent.parent
    for name in PROMPT_FILES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    return tmp_path


def _count_reads(monkeypatch) -> dict:
    counter = {"reads": 0}
    original = Path.read_text

    def counting_read_text(self, *args, **kwargs):
        counter["reads"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)
    return counter


def test_repeated_build_does_not_reread_files(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_client, "ROOT", _copy_prompt_root(tmp_path))
    llm_client.invalidate_prompt_cache()
    counter = _count_reads(monkeypatch)

    first = llm_client.build_system_prompt("generate")
    assert counter["reads"] == len(PROMPT_FILES)
    second = llm_client.build_system_prompt("generate")
    assert second == first
    assert counter["reads"] == len(PROMPT_FILES), "повторный вызов перечитал файлы"
    assert "{{SCHEMA}}" not in first and "generate" in first


def test_touched_file_invalidates_cache(monkeypatch, tmp_path):
    root = _copy_prompt_root(tmp_path)
    monkeypatch.setattr(llm_client, "ROOT", root)
    llm_client.invalidate_prompt_cache()
    counter = _count_reads(monkeypatch)

    before = llm_client.build_system_prompt("generate")
    blocks = root / "app/prompts/BLOCKS.md"
    blocks.write_text(blocks.read_text(encoding="utf-8") + "\n<!-- изменено -->\n", encoding="utf-8")
    reads_after_write = counter["reads"]
    stat = blocks.stat()
    os.utime(blocks, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))

    after = llm_client.build_system_prompt("generate")
    assert after != before
    assert "<!-- изменено -->" in after
    # Перечитан только изменённый файл, остальные три взяты из кэша.
    assert counter["reads"] == reads_after_write + 1
    assert llm_client.build_system_prompt("generate") == after
    assert counter["reads"] == reads_after_write + 1


def test_modes_are_cached_separately(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_client, "ROOT", _copy_prompt_root(tmp_path))
    llm_client.invalidate_prompt_cache()
    counter = _count_reads(monkeypatch)

    generate = llm_client.build_system_prompt("generate")
    edit = llm_client.build_system_prompt("edit")
    assert generate != edit
    # Файлы уже в кэше после generate: edit собирается без чтения с диска.
    assert counter["reads"] == len(PROMPT_FILES)
    assert llm_client.build_system_prompt("generate") == generate
    assert llm_client.build_system_prompt("edit") == edit
    assert counter["reads"] == len(PROMPT_FILES)
    llm_client.invalidate_prompt_cache()
    assert llm_client.build_system_prompt("edit") == edit
    assert counter["reads"] > len(PROMPT_FILES)
