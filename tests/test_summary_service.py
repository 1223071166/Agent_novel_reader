import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import config
import services.summary_service as summary_module


class SummaryServiceTests(unittest.TestCase):
    @staticmethod
    def _create_book(books_dir: Path) -> Path:
        book_root = books_dir / "book-test"
        chapter_dir = book_root / "chapters"
        chapter_dir.mkdir(parents=True)
        (chapter_dir / "1.txt").write_text("第一章正文", encoding="utf-8")
        return book_root

    def test_setting_and_background_job_are_persisted_per_book(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            books_dir = Path(temp_dir)
            self._create_book(books_dir)

            def generate(level, book_path, start, on_progress):
                on_progress("start", "正在生成第 1 章摘要")
                on_progress("complete", "正在生成第 1 章摘要")
                on_progress("start", "正在合并第 1-1 章摘要")
                on_progress("complete", "正在合并第 1-1 章摘要")
                book_path.summary_dir.mkdir()
                (book_path.summary_dir / "mid_1-1.txt").write_text("总结", encoding="utf-8")

            with (
                patch.object(config, "BOOKS_DIR", books_dir),
                patch.object(summary_module, "generate_summary", side_effect=generate),
            ):
                service = summary_module.SummaryService(books_dir)
                self.assertFalse(service.get_overview("book-test")["enabled"])

                service.set_enabled("book-test", True)
                job = service.start("book-test", [{"level": "mid", "start": 1}])
                self.assertEqual(job["total_calls"], 2)

                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    job = service.get_overview("book-test")["job"]
                    if job and job["status"] == "completed":
                        break
                    time.sleep(0.01)

                self.assertIsNotNone(job)
                self.assertEqual(job["status"], "completed")
                self.assertEqual(job["completed_calls"], 2)
                self.assertTrue(summary_module.read_summary_state(
                    config.BookPaths("book-test"),
                )["enabled"])

    def test_invalid_job_state_is_rejected_before_recovery(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            books_dir = Path(temp_dir)
            book_root = self._create_book(books_dir)
            with patch.object(config, "BOOKS_DIR", books_dir):
                for invalid_job in ([], {"status": "running", "targets": []}):
                    (book_root / "summary_state.json").write_text(
                        json.dumps({"enabled": False, "job": invalid_job}),
                        encoding="utf-8",
                    )
                    with self.subTest(job=invalid_job):
                        with self.assertRaisesRegex(ValueError, "job 格式错误"):
                            summary_module.SummaryService(books_dir)

    def test_pending_job_is_restored_with_its_original_targets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            books_dir = Path(temp_dir)
            book_root = self._create_book(books_dir)
            targets = [{"level": "mid", "start": 1}]
            (book_root / "summary_state.json").write_text(
                json.dumps({
                    "enabled": True,
                    "job": {
                        "status": "running",
                        "targets": targets,
                        "completed_calls": 1,
                        "total_calls": 2,
                        "estimated_input_tokens": 100,
                        "estimated_output_tokens": 50,
                        "estimated_tokens": 150,
                        "current": "正在生成",
                        "error": None,
                    },
                }),
                encoding="utf-8",
            )

            with (
                patch.object(config, "BOOKS_DIR", books_dir),
                patch.object(summary_module.SummaryService, "_start_worker") as start_worker,
            ):
                summary_module.SummaryService(books_dir)
                state = summary_module.read_summary_state(config.BookPaths("book-test"))

            self.assertEqual(state["job"]["status"], "pending")
            self.assertEqual(state["job"]["targets"], targets)
            start_worker.assert_called_once_with("book-test", targets)


if __name__ == "__main__":
    unittest.main()
