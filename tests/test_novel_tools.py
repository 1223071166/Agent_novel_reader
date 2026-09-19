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
    summaries.MID_SIZE = 20
    summaries.BIG_SIZE = 100
    summaries.block_range = lambda start, size, book_path: (start, min(start + size - 1, 45))
    summaries.is_block_start = lambda start, size, book_path: 1 <= start <= 45 and (start - 1) % size == 0
    summaries.total_chapters = lambda book_path: 45
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
        {
            "config": config,
            "summaries": summaries,
            "embedding": embedding,
            "novel_tools_under_test": module,
        },
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
        self.context = novel_tools.NovelToolContext(self.book, None)
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
        self.assertEqual(novel_tools.get_chapter(1, self.context), {
            "kind": "chapter",
            "chapter_id": 1,
            "title": "第一章",
            "content": "正文内容",
        })

    def test_missing_chapter_returns_clear_tool_error(self):
        self.assertIsNone(novel_tools.read_chapter(2, self.book))
        self.assertEqual(
            novel_tools.get_chapter(2, self.context),
            {"kind": "error", "message": "不存在第 2 章"},
        )

    def test_keyword_search_skips_missing_chapters(self):
        (self.book.chapter_dir / "1.txt").write_text("苹果苹果", encoding="utf-8")
        (self.book.chapter_dir / "3.txt").write_text("没有目标词", encoding="utf-8")

        result = novel_tools.search_keyword("苹果", self.context)

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

    def test_summary_result_includes_its_chapter_range(self):
        self.assertEqual(novel_tools.get_summary("mid", self.context, 41), {
            "kind": "summary",
            "level": "mid",
            "start": 41,
            "end": 45,
            "content": None,
        })

    def test_spoiler_mode_limits_chapter_tools(self):
        for chapter_id in range(1, 4):
            (self.book.chapter_dir / f"{chapter_id}.txt").write_text(
                f"第 {chapter_id} 章内容 苹果",
                encoding="utf-8",
            )
        context = novel_tools.NovelToolContext(self.book, 2)

        chapter_list = novel_tools.get_chapter_list(context)
        self.assertEqual(
            [chapter["chapter_id"] for chapter in chapter_list["chapters"]],
            [1, 2],
        )
        self.assertEqual(novel_tools.get_chapter(3, context)["kind"], "error")
        self.assertEqual(
            [match["chapter_id"] for match in novel_tools.search_keyword("苹果", context)["matches"]],
            [1, 2],
        )
        self.assertEqual(
            novel_tools.search_keyword_in_chapter(3, "苹果", context)["kind"],
            "error",
        )

    def test_spoiler_mode_filters_semantic_search_before_and_after_query(self):
        context = novel_tools.NovelToolContext(self.book, 2)
        raw_results = [
            {"score": 1, "text": "第二章", "metadata": {"chapter": 2, "title": "第二章", "chunk": 0}},
            {"score": 1, "text": "第三章", "metadata": {"chapter": 3, "title": "第三章", "chunk": 0}},
        ]

        with patch.object(novel_tools, "embedding_search", return_value=raw_results) as search:
            result = novel_tools.semantic_search("剧情", context)

        search.assert_called_once_with(
            "剧情",
            n=10,
            book_path=self.book,
            max_chapter=2,
        )
        self.assertEqual([match["chapter_id"] for match in result["matches"]], [2])

    def test_spoiler_mode_requires_the_whole_summary_block_to_be_read(self):
        context = novel_tools.NovelToolContext(self.book, 40)

        self.assertEqual(novel_tools.get_summary("mid", context, 21)["kind"], "summary")
        self.assertEqual(novel_tools.get_summary("mid", context, 41)["kind"], "error")
        self.assertEqual(novel_tools.get_summary("whole", context)["kind"], "error")


if __name__ == "__main__":
    unittest.main()
