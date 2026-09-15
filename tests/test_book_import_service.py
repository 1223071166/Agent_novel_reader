import json
import tempfile
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

                service.save_info(book_id, "书名：测试小说")
                self.assertEqual(
                    (book_root / "info.txt").read_text(encoding="utf-8"),
                    "书名：测试小说\n",
                )
                self.assertEqual(service.get_import(book_id)["info"], "书名：测试小说\n")

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
                service.discard_import(discarded["book_id"])
                self.assertFalse(discarded_root.exists())

    def test_running_import_is_recovered_as_failed_after_restart(self):
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

            self.assertEqual(recovered["status"], "failed")
            self.assertEqual(recovered["processed"], 12)
            self.assertIn("后端重启", recovered["error"])
            self.assertTrue(marker.exists())
            self.assertFalse(building_dir.exists())


if __name__ == "__main__":
    unittest.main()
