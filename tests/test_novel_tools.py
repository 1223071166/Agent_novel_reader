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
            vector_db_dir=root / "vector_db",
        )
        self.book.vector_db_dir.mkdir()
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

    def test_multiple_chapters_are_read_in_requested_order(self):
        (self.book.chapter_dir / "1.txt").write_text("第一章正文", encoding="utf-8")
        (self.book.chapter_dir / "3.txt").write_text("第三章正文", encoding="utf-8")

        result = novel_tools.get_chapters([3, 1, 2, 1], self.context)

        self.assertEqual(result, {
            "kind": "chapters",
            "chapters": [
                {"chapter_id": 3, "title": "第三章", "content": "第三章正文"},
                {"chapter_id": 1, "title": "第一章", "content": "第一章正文"},
            ],
            "missing_chapter_ids": [2],
        })
        self.assertEqual(
            format_tool_result_data(result),
            "第 3 章：第三章\n第三章正文\n\n"
            "第 1 章：第一章\n第一章正文\n\n"
            "不存在的章节：2",
        )

    def test_multiple_chapters_are_limited_to_ten(self):
        self.assertEqual(
            novel_tools.get_chapters(list(range(1, 12)), self.context),
            {"kind": "error", "message": "一次最多读取 10 章"},
        )

    def test_keyword_search_skips_missing_chapters(self):
        (self.book.chapter_dir / "1.txt").write_text(
            "甲" * 12 + "苹果" + "乙" * 12,
            encoding="utf-8",
        )
        (self.book.chapter_dir / "3.txt").write_text("没有目标词", encoding="utf-8")

        result = novel_tools.search_keyword("苹果", self.context)

        self.assertEqual(result, {
            "kind": "keyword_search",
            "keyword": "苹果",
            "start_chapter": None,
            "end_chapter": None,
            "context_chars": 20,
            "matches": [{
                "chapter_id": 1,
                "title": "第一章",
                "count": 1,
                "occurrences": [{
                    "start": 12,
                    "end": 14,
                    "excerpt": "甲" * 10 + "苹果" + "乙" * 10,
                }],
            }],
            "truncated": False,
        })
        self.assertEqual(
            format_tool_result_data(result),
            "第 1 章：第一章，出现次数：1\n" + "甲" * 10 + "苹果" + "乙" * 10,
        )

    def test_keyword_search_can_limit_chapter_range_and_context(self):
        (self.book.chapter_dir / "3.txt").write_text("前前苹果后后", encoding="utf-8")

        result = novel_tools.search_keyword(
            "苹果",
            self.context,
            start_chapter=3,
            end_chapter=3,
            context_chars=4,
        )

        self.assertEqual(result["start_chapter"], 3)
        self.assertEqual(result["end_chapter"], 3)
        self.assertEqual(result["context_chars"], 4)
        self.assertEqual(result["matches"], [{
            "chapter_id": 3,
            "title": "第三章",
            "count": 1,
            "occurrences": [{
                "start": 2,
                "end": 4,
                "excerpt": "前前苹果后后",
            }],
        }])

    def test_keyword_search_truncates_contexts_after_fifty(self):
        (self.book.chapter_dir / "1.txt").write_text("苹果" * 51, encoding="utf-8")

        result = novel_tools.search_keyword("苹果", self.context)

        self.assertEqual(result["matches"][0]["count"], 51)
        self.assertEqual(len(result["matches"][0]["occurrences"]), 50)
        self.assertTrue(result["truncated"])
        self.assertTrue(
            format_tool_result_data(result).endswith("（搜索结果过多，已截断）")
        )

    def test_keyword_search_rejects_negative_context(self):
        self.assertEqual(
            novel_tools.search_keyword("苹果", self.context, context_chars=-1),
            {"kind": "error", "message": "上下文字数必须是非负整数"},
        )

    def test_chapter_list_can_filter_by_title_and_range(self):
        result = novel_tools.get_chapter_list(
            query="章",
            start_chapter=2,
            end_chapter=3,
            context=self.context,
        )

        self.assertEqual(result, {
            "kind": "chapter_list",
            "query": "章",
            "start_chapter": 2,
            "end_chapter": 3,
            "chapters": [
                {"chapter_id": 2, "title": "第二章"},
                {"chapter_id": 3, "title": "第三章"},
            ],
        })
        self.assertEqual(
            format_tool_result_data(result),
            "第 2 章：第二章\n第 3 章：第三章",
        )

    def test_unfiltered_chapter_list_is_not_limited(self):
        result = novel_tools.get_chapter_list(context=self.context)

        self.assertEqual(
            [chapter["chapter_id"] for chapter in result["chapters"]],
            [1, 2, 3],
        )

    def test_chapter_list_rejects_invalid_filters(self):
        self.assertEqual(
            novel_tools.get_chapter_list(
                start_chapter=3,
                end_chapter=2,
                context=self.context,
            ),
            {"kind": "error", "message": "起始章号不能大于结束章号"},
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

        chapter_list = novel_tools.get_chapter_list(context=context)
        self.assertEqual(
            [chapter["chapter_id"] for chapter in chapter_list["chapters"]],
            [1, 2],
        )
        self.assertEqual(novel_tools.get_chapter(3, context)["kind"], "error")
        self.assertEqual(novel_tools.get_chapters([1, 3], context)["kind"], "error")
        self.assertEqual(
            [match["chapter_id"] for match in novel_tools.search_keyword("苹果", context)["matches"]],
            [1, 2],
        )
        self.assertEqual(
            novel_tools.search_keyword("苹果", context, start_chapter=3)["kind"],
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

    def test_semantic_search_accepts_a_chapter_range(self):
        raw_results = [
            {"score": 1, "text": "第一章", "metadata": {"chapter": 1, "title": "第一章", "chunk": 0}},
            {"score": 1, "text": "第二章", "metadata": {"chapter": 2, "title": "第二章", "chunk": 0}},
            {"score": 1, "text": "第三章", "metadata": {"chapter": 3, "title": "第三章", "chunk": 0}},
        ]

        with patch.object(novel_tools, "embedding_search", return_value=raw_results) as search:
            result = novel_tools.semantic_search(
                "剧情",
                self.context,
                start_chapter=2,
                end_chapter=2,
            )

        search.assert_called_once_with(
            "剧情",
            n=10,
            book_path=self.book,
            min_chapter=2,
            max_chapter=2,
        )
        self.assertEqual(result["start_chapter"], 2)
        self.assertEqual(result["end_chapter"], 2)
        self.assertEqual([match["chapter_id"] for match in result["matches"]], [2])

    def test_semantic_search_explains_when_embedding_is_not_ready(self):
        self.book.vector_db_dir.rmdir()

        result = novel_tools.semantic_search("剧情", self.context)

        self.assertEqual(result, {
            "kind": "error",
            "message": "暂未完成书籍向量化，无法模糊搜索",
        })

    def test_spoiler_mode_requires_the_whole_summary_block_to_be_read(self):
        context = novel_tools.NovelToolContext(self.book, 40)

        self.assertEqual(novel_tools.get_summary("mid", context, 21)["kind"], "summary")
        self.assertEqual(novel_tools.get_summary("mid", context, 41)["kind"], "error")
        self.assertEqual(novel_tools.get_summary("whole", context)["kind"], "error")


if __name__ == "__main__":
    unittest.main()
