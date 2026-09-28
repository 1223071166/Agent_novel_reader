import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
import backend.main as backend_module
import services.chat_service as chat_module
from services.book_deletion_service import BookDeletionService
from services.book_import_service import BookImportService
from services.conversation_store import ConversationStore
from services.models import Message
from services.summary_service import SummaryService


class BookDeletionServiceTests(unittest.TestCase):
    def setUp(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)
        self.books_dir = self.root / "books"
        self.database_dir = self.root / "database"
        self.database_dir.mkdir()
        self.selected_file = self.root / "selected_book.txt"
        self.db_file = self.database_dir / "conversations.db"

        for book_id in ("book-a", "book-b"):
            book_root = self.books_dir / book_id
            (book_root / "chapters").mkdir(parents=True)
            (book_root / "info.txt").write_text("简介", encoding="utf-8")
            (book_root / "name.txt").write_text(book_id, encoding="utf-8")
            (book_root / "novel.txt").write_text("正文", encoding="utf-8")

        for patcher in (
            patch.object(config, "BOOKS_DIR", self.books_dir),
            patch.object(config, "DATABASE_DIR", self.database_dir),
            patch.object(chat_module, "MESSAGE_STORAGE_FILE", self.db_file),
            patch.object(backend_module, "BOOKS_DIR", self.books_dir),
            patch.object(backend_module, "SELECTED_BOOK_FILE", self.selected_file),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

        store = ConversationStore(self.db_file)
        for book_id, conversation_id in (("book-a", "chat-a"), ("book-b", "chat-b")):
            store.create_conversation(conversation_id, book_id, book_id)
            store.save_message(conversation_id, Message(
                id=f"answer-{book_id}", role="assistant", content="回答",
                usage={"input": 1, "output": 1, "total": 2},
            ))

        self.chats = chat_module.ChatService()
        self.imports = BookImportService()
        self.summaries = SummaryService(books_dir=self.books_dir)
        self.deletion = BookDeletionService(self.imports, self.summaries, self.chats)

    def test_deletes_only_selected_book_files_vectors_and_conversations(self):
        vector_root = self.database_dir / "vector_db"
        for directory in ("book-a", "book-b", ".building-book-a", ".building-book-a-older"):
            path = vector_root / directory
            path.mkdir(parents=True)
            (path / "data.bin").write_bytes(b"data")

        self.deletion.delete_book("book-a")

        self.assertFalse((self.books_dir / "book-a").exists())
        self.assertFalse((vector_root / "book-a").exists())
        self.assertFalse((vector_root / ".building-book-a").exists())
        self.assertFalse((vector_root / ".building-book-a-older").exists())
        self.assertTrue((self.books_dir / "book-b").exists())
        self.assertTrue((vector_root / "book-b").exists())
        self.assertIsNone(self.chats._store.load_conversation("chat-a", "book-a"))
        self.assertIsNotNone(self.chats._store.load_conversation("chat-b", "book-b"))
        self.assertNotIn("chat-a", self.chats._conversations)
        self.assertIn("chat-b", self.chats._conversations)

    def test_active_chat_prevents_deletion(self):
        lock = self.chats._locks["chat-a"]
        lock.acquire()
        try:
            with self.assertRaisesRegex(ValueError, "正在生成的回复"):
                self.deletion.delete_book("book-a")
        finally:
            lock.release()
        self.assertTrue((self.books_dir / "book-a").exists())
        self.assertIsNotNone(self.chats._store.load_conversation("chat-a", "book-a"))

    def test_legacy_book_without_embedding_state_can_be_deleted(self):
        (self.books_dir / "book-a" / "info.txt").unlink()
        self.deletion.delete_book("book-a")
        self.assertFalse((self.books_dir / "book-a").exists())
        self.assertIsNone(self.chats._store.load_conversation("chat-a", "book-a"))

    def test_active_embedding_and_summary_prevent_deletion(self):
        book_root = self.books_dir / "book-a"
        state_file = book_root / "embedding_state.json"
        state_file.write_text(json.dumps({"status": "pending"}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "模糊搜索索引"):
            self.deletion.delete_book("book-a")

        state_file.unlink()
        (book_root / "summary_state.json").write_text(json.dumps({
            "enabled": False,
            "job": {
                "status": "running", "targets": [], "completed_calls": 0,
                "total_calls": 1, "estimated_input_tokens": 0,
                "estimated_output_tokens": 0, "estimated_tokens": 0,
                "current": "正在运行", "error": None,
            },
        }), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "总结任务"):
            self.deletion.delete_book("book-a")
        self.assertTrue(book_root.exists())

    def test_api_selects_remaining_book_after_deleting_current_book(self):
        with patch.object(backend_module, "book_deletion_service", self.deletion):
            backend_module.save_selected_book(
                backend_module.BookSelectionRequest(book_id="book-a")
            )
            selection = backend_module.delete_book("book-a")

        self.assertEqual(selection["selected_book_id"], "book-b")
        self.assertEqual(selection["books"], ["book-b"])
        self.assertEqual(self.selected_file.read_text(encoding="utf-8"), "book-b\n")

    def test_deleting_last_book_clears_selected_book(self):
        with patch.object(backend_module, "book_deletion_service", self.deletion):
            backend_module.save_selected_book(
                backend_module.BookSelectionRequest(book_id="book-a")
            )
            backend_module.delete_book("book-b")
            selection = backend_module.delete_book("book-a")

        self.assertEqual(selection["books"], [])
        self.assertIsNone(selection["selected_book_id"])
        self.assertFalse(self.selected_file.exists())


if __name__ == "__main__":
    unittest.main()
