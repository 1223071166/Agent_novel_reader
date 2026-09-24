import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import config
import services.book_import_service as import_module
from services.book_import_service import BookImportService, IMPORT_STATE_FILE


class BookImportServiceTests(unittest.TestCase):
    def test_import_info_and_embedding_flow(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            books_dir = root / "books"
            database_dir = root / "database"

            def fake_build_embedding(book_path, output_dir, on_progress):
                output_dir.mkdir(parents=True)
                (output_dir / "chroma.sqlite3").write_text("test", encoding="utf-8")
                on_progress(1, 2)
                on_progress(2, 2)

            with (
                patch.object(config, "BOOKS_DIR", books_dir),
                patch.object(config, "DATABASE_DIR", database_dir),
                patch.object(import_module, "BOOKS_DIR", books_dir),
                patch.object(import_module, "DATABASE_DIR", database_dir),
                patch.object(import_module, "build_embedding", fake_build_embedding),
            ):
                service = BookImportService()
                result = service.create_import(
                    "测试小说.txt",
                    "第1章 开始\n这里是第一段正文\n第2章 继续\n这里是第二段正文".encode("utf-8"),
                )
                book_id = result["book_id"]
                book_root = books_dir / book_id

                self.assertRegex(book_id, r"^book_[0-9a-f]{12}$")
                self.assertEqual(result["chapter_count"], 2)
                self.assertEqual(
                    (book_root / "chapters" / "1.txt").read_text(encoding="utf-8").splitlines()[0],
                    "开始",
                )
                self.assertTrue((book_root / IMPORT_STATE_FILE).exists())
                self.assertEqual(service.get_import(book_id)["status"], "awaiting_info")

                service.save_info(book_id, "测试小说", "这是一本测试小说")
                self.assertEqual(
                    (book_root / "name.txt").read_text(encoding="utf-8"),
                    "测试小说\n",
                )
                self.assertEqual(
                    (book_root / "info.txt").read_text(encoding="utf-8"),
                    "这是一本测试小说\n",
                )
                self.assertEqual(service.get_import(book_id)["name"], "测试小说")
                self.assertEqual(service.get_import(book_id)["info"], "这是一本测试小说\n")

                service.start_embedding(book_id)
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    status = service.get_status(book_id)
                    if status["status"] == "completed":
                        break
                    time.sleep(0.01)

                self.assertEqual(status["status"], "completed")
                self.assertEqual(status["processed"], 2)
                self.assertEqual(status["total"], 2)
                self.assertEqual(service.get_import(book_id)["status"], "completed")
                self.assertFalse((book_root / IMPORT_STATE_FILE).exists())
                self.assertTrue(
                    (database_dir / "vector_db" / book_id / "chroma.sqlite3").exists()
                )

                discarded = service.create_import(
                    "放弃的小说.txt",
                    "第1章 开始\n这里是正文".encode("utf-8"),
                )
                discarded_root = books_dir / discarded["book_id"]
                partial_dir = database_dir / "vector_db" / f".building-{discarded['book_id']}"
                partial_dir.mkdir()
                service.discard_import(discarded["book_id"])
                self.assertFalse(discarded_root.exists())
                self.assertFalse(partial_dir.exists())

    def test_running_import_keeps_partial_vectors_for_resume_after_restart(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            books_dir = root / "books"
            database_dir = root / "database"
            book_id = "book_123456789abc"
            book_root = books_dir / book_id
            book_root.mkdir(parents=True)
            marker = book_root / IMPORT_STATE_FILE
            marker.write_text(json.dumps({
                "book_id": book_id,
                "status": "encoding",
                "processed": 12,
                "total": 100,
                "message": "正在生成文本向量",
                "error": None,
            }), encoding="utf-8")
            building_dir = database_dir / "vector_db" / f".building-{book_id}-test"
            building_dir.mkdir(parents=True)

            with (
                patch.object(config, "BOOKS_DIR", books_dir),
                patch.object(config, "DATABASE_DIR", database_dir),
                patch.object(import_module, "BOOKS_DIR", books_dir),
                patch.object(import_module, "DATABASE_DIR", database_dir),
            ):
                service = BookImportService()
                recovered = service.get_status(book_id)
                self.assertEqual(service._building_dir(book_id), building_dir)

            self.assertEqual(recovered["status"], "failed")
            self.assertEqual(recovered["processed"], 12)
            self.assertIn("后端重启", recovered["error"])
            self.assertIn("已有进度继续", recovered["message"])
            self.assertTrue(marker.exists())
            self.assertTrue(building_dir.exists())

    def test_running_embedding_rejects_info_changes_without_touching_build_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            books_dir = root / "books"
            database_dir = root / "database"
            book_id = "book_123456789abc"
            book_root = books_dir / book_id
            book_root.mkdir(parents=True)
            (book_root / "name.txt").write_text("原书名\n", encoding="utf-8")
            (book_root / "info.txt").write_text("原概况\n", encoding="utf-8")
            (book_root / IMPORT_STATE_FILE).write_text(json.dumps({
                "book_id": book_id,
                "status": "encoding",
                "processed": 12,
                "total": 100,
                "message": "正在生成文本向量",
                "error": None,
            }), encoding="utf-8")
            building_dir = database_dir / "vector_db" / f".building-{book_id}-test"
            building_dir.mkdir(parents=True)

            with (
                patch.object(config, "BOOKS_DIR", books_dir),
                patch.object(config, "DATABASE_DIR", database_dir),
                patch.object(import_module, "BOOKS_DIR", books_dir),
                patch.object(import_module, "DATABASE_DIR", database_dir),
                patch.object(BookImportService, "_recover_interrupted_imports"),
            ):
                service = BookImportService()
                with self.assertRaisesRegex(ValueError, "向量化正在运行"):
                    service.save_info(book_id, "新书名", "新概况")

            self.assertEqual((book_root / "name.txt").read_text(encoding="utf-8"), "原书名\n")
            self.assertEqual((book_root / "info.txt").read_text(encoding="utf-8"), "原概况\n")
            self.assertTrue(building_dir.exists())

    def test_concurrent_embedding_starts_create_only_one_worker(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            books_dir = root / "books"
            database_dir = root / "database"
            book_id = "book_123456789abc"
            book_root = books_dir / book_id
            book_root.mkdir(parents=True)
            (book_root / "info.txt").write_text("测试概况\n", encoding="utf-8")
            (book_root / IMPORT_STATE_FILE).write_text(json.dumps({
                "book_id": book_id,
                "status": "ready_for_embedding",
                "processed": 0,
                "total": 0,
                "message": "可以开始向量化",
                "error": None,
            }), encoding="utf-8")

            with (
                patch.object(config, "BOOKS_DIR", books_dir),
                patch.object(config, "DATABASE_DIR", database_dir),
                patch.object(import_module, "BOOKS_DIR", books_dir),
                patch.object(import_module, "DATABASE_DIR", database_dir),
            ):
                service = BookImportService()
                original_save_state = service._save_state
                worker_calls = 0
                worker_calls_lock = threading.Lock()

                def slow_save_state(book_path, state):
                    if state["status"] == "pending":
                        time.sleep(0.05)
                    original_save_state(book_path, state)

                def record_worker(_book_path):
                    nonlocal worker_calls
                    with worker_calls_lock:
                        worker_calls += 1

                class ImmediateWorker:
                    def __init__(self, *, target, args, **_kwargs):
                        self._target = target
                        self._args = args

                    def start(self):
                        self._target(*self._args)

                request_workers = [
                    threading.Thread(target=service.start_embedding, args=(book_id,))
                    for _ in range(2)
                ]
                with (
                    patch.object(service, "_save_state", slow_save_state),
                    patch.object(service, "_run_embedding", record_worker),
                    patch.object(import_module.threading, "Thread", ImmediateWorker),
                ):
                    for worker in request_workers:
                        worker.start()
                    for worker in request_workers:
                        worker.join()

                self.assertEqual(worker_calls, 1)
                self.assertEqual(service.get_status(book_id)["status"], "pending")


if __name__ == "__main__":
    unittest.main()
