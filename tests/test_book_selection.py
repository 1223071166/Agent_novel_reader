import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import backend.main as backend_module
from services.book_import_service import IMPORT_STATE_FILE


class BookSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.books_dir = self.root / "books"
        self.selected_book_file = self.root / "selected_book.txt"
        (self.books_dir / "book-a").mkdir(parents=True)
        (self.books_dir / "book-b").mkdir()
        incomplete = self.books_dir / "book-incomplete"
        incomplete.mkdir()
        (incomplete / IMPORT_STATE_FILE).write_text("{}", encoding="utf-8")

        for patcher in (
            patch.object(backend_module, "BOOKS_DIR", self.books_dir),
            patch.object(backend_module, "SELECTED_BOOK_FILE", self.selected_book_file),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_saved_book_is_loaded_on_first_open(self):
        backend_module.save_selected_book(
            backend_module.BookSelectionRequest(book_id="book-b")
        )

        selection = backend_module.get_books()

        self.assertEqual(self.selected_book_file.read_text(encoding="utf-8"), "book-b\n")
        self.assertEqual(selection["selected_book_id"], "book-b")

    def test_unavailable_saved_book_falls_back_to_first_completed_book(self):
        self.selected_book_file.write_text("book-incomplete\n", encoding="utf-8")

        selection = backend_module.get_books()

        self.assertEqual(selection["selected_book_id"], "book-a")
        self.assertEqual(self.selected_book_file.read_text(encoding="utf-8"), "book-a\n")

    def test_incomplete_book_cannot_be_selected(self):
        with self.assertRaises(HTTPException) as raised:
            backend_module.save_selected_book(
                backend_module.BookSelectionRequest(book_id="book-incomplete")
            )

        self.assertEqual(raised.exception.status_code, 404)
        self.assertFalse(self.selected_book_file.exists())


if __name__ == "__main__":
    unittest.main()
