import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from summaries import (
    _combine,
    _chapter_summary_path,
    _read_summary,
    _summarize,
    _summary_path,
    _write_summary,
    block_name,
    block_range,
    get_summary,
    is_block_start,
    normalize_summary_targets,
    plan_summary_targets,
    total_chapters,
)


def summary_chunk(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            delta=SimpleNamespace(content=content),
        )],
    )


class FakeCompletions:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.call_count = 0

    def create(self, **kwargs):
        self.call_count += 1
        return next(self.responses)


def fake_client(responses):
    completions = FakeCompletions(responses)
    return SimpleNamespace(
        chat=SimpleNamespace(completions=completions),
    ), completions


class SummaryPathsTests(unittest.TestCase):
    def test_empty_parts_are_not_sent_to_the_model(self):
        with self.assertRaisesRegex(ValueError, "没有可用于生成总结的内容"):
            _combine("system", [])

    def test_summary_reads_only_the_requested_book(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = self._create_book(root / "book-1", "第一本书摘要")
            second = self._create_book(root / "book-2", "第二本书摘要")

            self.assertEqual(get_summary("whole", first), "第一本书摘要")
            self.assertEqual(get_summary("whole", second), "第二本书摘要")
            self.assertEqual(total_chapters(first), 1)
            self.assertEqual(total_chapters(second), 1)

    def test_empty_model_response_is_retried(self):
        client, completions = fake_client([
            [],
            [summary_chunk("   ")],
            [summary_chunk("有效摘要")],
        ])

        with patch("summaries.client_summary", client):
            self.assertEqual(_summarize("system", "chapter"), "有效摘要")

        self.assertEqual(completions.call_count, 3)

    def test_three_empty_model_responses_raise_an_error(self):
        client, completions = fake_client([[], [], []])

        with patch("summaries.client_summary", client):
            with self.assertRaisesRegex(RuntimeError, "连续 3 次返回空摘要"):
                _summarize("system", "chapter")

        self.assertEqual(completions.call_count, 3)

    def test_empty_cache_is_ignored_without_deleting_the_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            book = self._create_book(Path(temp_dir) / "book", "全书摘要")
            path = _chapter_summary_path(1, book)
            path.parent.mkdir()
            path.write_text("  \n", encoding="utf-8")

            self.assertIsNone(_read_summary(path))
            self.assertTrue(path.exists())

    def test_empty_summary_is_not_written(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            book = self._create_book(Path(temp_dir) / "book", "原摘要")
            whole_path = _summary_path("whole.txt", book)

            with self.assertRaisesRegex(ValueError, "摘要内容不能为空"):
                _write_summary(whole_path, "   ")
            with self.assertRaisesRegex(ValueError, "摘要内容不能为空"):
                _write_summary(_chapter_summary_path(1, book), "")

            self.assertEqual(whole_path.read_text(encoding="utf-8"), "原摘要")
            self.assertFalse(_chapter_summary_path(1, book).exists())

    def test_valid_summary_replaces_the_target_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            book = self._create_book(Path(temp_dir) / "book", "旧摘要")

            _write_summary(_summary_path("whole.txt", book), "新摘要")

            self.assertEqual(get_summary("whole", book), "新摘要")
            self.assertEqual(list(book.summary_dir.glob("*.tmp")), [])

    def test_block_helpers_work_for_different_summary_sizes(self):
        book = SimpleNamespace()
        with patch("summaries.total_chapters", return_value=45):
            self.assertEqual(block_range(41, 20, book), (41, 45))
            self.assertTrue(is_block_start(41, 20, book))
            self.assertFalse(is_block_start(42, 20, book))
            self.assertEqual(block_name("mid", 41, 20, book), "mid_41-45.txt")

    @staticmethod
    def _create_book(root: Path, summary: str):
        chapter_dir = root / "chapters"
        summary_dir = root / "summaries"
        chapter_dir.mkdir(parents=True)
        summary_dir.mkdir()
        (chapter_dir / "1.txt").write_text("正文", encoding="utf-8")
        (summary_dir / "whole.txt").write_text(summary, encoding="utf-8")
        return SimpleNamespace(chapter_dir=chapter_dir, summary_dir=summary_dir)


class SummaryPlanningTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.book = SimpleNamespace(
            chapter_dir=root / "chapters",
            summary_dir=root / "summaries",
        )
        self.book.chapter_dir.mkdir()
        for chapter_id in range(1, 46):
            (self.book.chapter_dir / f"{chapter_id}.txt").write_text(
                f"第 {chapter_id} 章正文" * 10,
                encoding="utf-8",
            )

    def test_big_plan_expands_missing_chapters_and_mid_summaries(self):
        plan = plan_summary_targets(
            [{"level": "big", "start": 1}],
            self.book,
        )

        self.assertEqual(plan["total_calls"], 49)
        self.assertGreater(plan["estimated_tokens"], 0)

    def test_boolean_is_not_accepted_as_a_summary_start(self):
        with self.assertRaisesRegex(ValueError, "需要提供起始章号"):
            normalize_summary_targets(
                [{"level": "mid", "start": True}],
                self.book,
            )

    def test_existing_mid_is_reused_and_overlapping_targets_are_deduplicated(self):
        self.book.summary_dir.mkdir()
        (self.book.summary_dir / "mid_1-20.txt").write_text("已有总结", encoding="utf-8")

        plan = plan_summary_targets(
            [
                {"level": "big", "start": 1},
                {"level": "whole", "start": None},
                {"level": "big", "start": 1},
            ],
            self.book,
        )

        self.assertEqual(plan["total_calls"], 29)
        self.assertEqual(plan["targets"], [
            {"level": "big", "start": 1},
            {"level": "whole", "start": None},
        ])
        self.assertGreater(plan["estimated_input_tokens"], 0)
        self.assertGreater(plan["estimated_output_tokens"], 0)
        self.assertGreater(plan["estimated_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
