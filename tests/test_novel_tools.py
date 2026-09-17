import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tool_results import format_tool_result_data


def load_novel_tools():
    config = types.ModuleType("config")
    config.BookPaths = object
    summaries = types.ModuleType("summaries")
    summaries.get_summary = lambda *args, **kwargs: None
    embedding = types.ModuleType("embedding")
    embedding.search = lambda *args, **kwargs: []
    spec = importlib.util.spec_from_file_location(
        "novel_tools_under_test",
        Path(__file__).parents[1] / "novel_tools.py",
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        sys.modules,
        {"config": config, "summaries": summaries, "embedding": embedding},
    ):
        spec.loader.exec_module(module)
    return module


novel_tools = load_novel_tools()


class NovelToolsTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        chapter_dir = root / "chapters"
        chapter_dir.mkdir()
        chapter_list = root / "chapters.txt"
        chapter_list.write_text(
            "1，第一章\n2，第二章\n3，第三章\n",
            encoding="utf-8",
        )
        self.book = SimpleNamespace(
            book_id="novel-tools-test",
            chapter_dir=chapter_dir,
            chapter_list=chapter_list,
        )
        novel_tools.chapter_cache.clear()
        novel_tools.titles_by_book.clear()
        self.addCleanup(novel_tools.chapter_cache.clear)
        self.addCleanup(novel_tools.titles_by_book.clear)

    def test_existing_chapter_is_read(self):
        (self.book.chapter_dir / "1.txt").write_text("正文内容", encoding="utf-8")

        self.assertEqual(
            novel_tools.read_chapter(1, self.book),
            {"title": "第一章", "content": "正文内容"},
        )
        self.assertEqual(novel_tools.get_chapter(1, self.book), {
            "kind": "chapter",
            "chapter_id": 1,
            "title": "第一章",
            "content": "正文内容",
        })

    def test_missing_chapter_returns_clear_tool_error(self):
        self.assertIsNone(novel_tools.read_chapter(2, self.book))
        self.assertEqual(
            novel_tools.get_chapter(2, self.book),
            {"kind": "error", "message": "不存在第 2 章"},
        )

    def test_keyword_search_skips_missing_chapters(self):
        (self.book.chapter_dir / "1.txt").write_text("苹果苹果", encoding="utf-8")
        (self.book.chapter_dir / "3.txt").write_text("没有目标词", encoding="utf-8")

        result = novel_tools.search_keyword("苹果", self.book)

        self.assertEqual(result, {
            "kind": "keyword_search",
            "keyword": "苹果",
            "matches": [{
                "chapter_id": 1,
                "title": "第一章",
                "count": 2,
            }],
        })
        self.assertEqual(
            format_tool_result_data(result),
            "第 1 章：第一章，出现次数：2",
        )


if __name__ == "__main__":
    unittest.main()
