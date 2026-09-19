import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import config
from services.reading_service import (
    get_reading_settings,
    save_reading_settings,
    spoiler_chapter_limit,
)


class ReadingServiceTests(unittest.TestCase):
    def test_settings_are_persisted_and_isolated_per_book(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            books_dir = Path(temporary_directory)
            for book_id, chapter_count in (("book-1", 3), ("book-2", 5)):
                chapter_dir = books_dir / book_id / "chapters"
                chapter_dir.mkdir(parents=True)
                for chapter_id in range(1, chapter_count + 1):
                    (chapter_dir / f"{chapter_id}.txt").write_text("正文", encoding="utf-8")

            with patch.object(config, "BOOKS_DIR", books_dir):
                first = save_reading_settings("book-1", True, 2)
                second = get_reading_settings("book-2")

                self.assertTrue(first["spoiler_mode"])
                self.assertEqual(first["read_through_chapter"], 2)
                self.assertEqual(spoiler_chapter_limit("book-1"), 2)
                self.assertFalse(second["spoiler_mode"])
                self.assertIsNone(spoiler_chapter_limit("book-2"))
                self.assertEqual(
                    (books_dir / "book-1" / "reading_state.json").read_text(encoding="utf-8"),
                    '{\n  "spoiler_mode": true,\n  "read_through_chapter": 2\n}',
                )

    def test_read_chapter_must_be_inside_the_book_range(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            books_dir = Path(temporary_directory)
            chapter_dir = books_dir / "book-1" / "chapters"
            chapter_dir.mkdir(parents=True)
            (chapter_dir / "1.txt").write_text("正文", encoding="utf-8")

            with patch.object(config, "BOOKS_DIR", books_dir):
                with self.assertRaisesRegex(ValueError, "0-1"):
                    save_reading_settings("book-1", True, 2)
                with self.assertRaisesRegex(ValueError, "布尔值"):
                    save_reading_settings("book-1", "yes", 1)
                with self.assertRaisesRegex(ValueError, "0-1"):
                    save_reading_settings("book-1", True, 0.5)

                (books_dir / "book-1" / "reading_state.json").write_text(
                    json.dumps({"spoiler_mode": True, "read_through_chapter": 2}),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(ValueError, "0-1"):
                    spoiler_chapter_limit("book-1")


if __name__ == "__main__":
    unittest.main()
