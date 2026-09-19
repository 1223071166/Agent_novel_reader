"""Per-book reading progress and spoiler-mode settings."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from config import BookPaths
from summaries import total_chapters
 
def _default_state() -> dict[str, Any]:
    return {"spoiler_mode": False, "read_through_chapter": 0}

def read_reading_state(book_path: BookPaths) -> dict[str, Any]:
    path = book_path.reading_state_file
    if not path.exists():
        return _default_state()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"阅读状态文件损坏：{exc}") from exc
    if (
        not isinstance(state, dict)
        or not isinstance(state.get("spoiler_mode"), bool)
        or not isinstance(state.get("read_through_chapter"), int)
        or isinstance(state.get("read_through_chapter"), bool)
    ):
        raise ValueError("阅读状态文件格式错误")
    return state


def get_reading_settings(book_id: str) -> dict[str, Any]:
    book_path = _require_book(book_id)
    state = read_reading_state(book_path)
    chapter_count = total_chapters(book_path)
    if not 0 <= state["read_through_chapter"] <= chapter_count:
        raise ValueError(f"已阅读章号必须在 0-{chapter_count} 之间")
    return {
        "book_id": book_id,
        "chapter_count": chapter_count,
        **state,
    }


def save_reading_settings(
    book_id: str,
    spoiler_mode: bool,
    read_through_chapter: int,
) -> dict[str, Any]:
    book_path = _require_book(book_id)
    chapter_count = total_chapters(book_path)
    if not isinstance(spoiler_mode, bool):
        raise ValueError("防剧透开关必须是布尔值")
    if (
        not isinstance(read_through_chapter, int)
        or isinstance(read_through_chapter, bool)
        or not 0 <= read_through_chapter <= chapter_count
    ):
        raise ValueError(f"已阅读章号必须在 0-{chapter_count} 之间")
    _write_state(book_path, {
        "spoiler_mode": spoiler_mode,
        "read_through_chapter": read_through_chapter,
    })
    return get_reading_settings(book_id)


def spoiler_chapter_limit(book_id: str) -> int | None:
    settings = get_reading_settings(book_id)
    return settings["read_through_chapter"] if settings["spoiler_mode"] else None


def _require_book(book_id: str) -> BookPaths:
    book_path = BookPaths(book_id)
    if not book_id or not book_path.root.is_dir() or not book_path.chapter_dir.is_dir():
        raise ValueError(f"找不到书籍：{book_id}")
    return book_path


def _write_state(book_path: BookPaths, state: dict[str, Any]) -> None:
    path = book_path.reading_state_file
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            json.dump(state, temporary_file, ensure_ascii=False, indent=2)
            temporary_path = Path(temporary_file.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
