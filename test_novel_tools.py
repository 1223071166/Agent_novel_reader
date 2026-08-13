import tempfile
import unittest
import sys
import types
from pathlib import Path
from unittest.mock import patch

# Keep these unit tests independent from optional API/model dependencies.
fake_config = types.ModuleType("config")
fake_config.CHAPTER_DIR = "chapters"
fake_config.CHAPTER_LIST = "chapters.txt"
fake_summaries = types.ModuleType("summaries")
fake_summaries.get_summary = lambda level, start=None: ""
fake_embedding = types.ModuleType("embedding")
fake_embedding.search = lambda query, n=10: []
sys.modules.setdefault("config", fake_config)
sys.modules.setdefault("summaries", fake_summaries)
sys.modules.setdefault("embedding", fake_embedding)

import novel_tools


class NovelToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.chapter_dir = root / "chapters"
        self.chapter_dir.mkdir()
        (self.chapter_dir / "1.txt").write_text("第一章\n程斌遇见文雯", encoding="utf-8")
        (self.chapter_dir / "2.txt").write_text("第二章\n文雯离开", encoding="utf-8")
        self.chapter_list = root / "chapters.txt"
        self.chapter_list.write_text("1，第一章\n2，第二章\n", encoding="utf-8")
        self.old_values = (
            novel_tools.CHAPTER_DIR,
            novel_tools.CHAPTER_LIST,
            novel_tools.chapter_cache,
            novel_tools.titles,
        )
        novel_tools.CHAPTER_DIR = str(self.chapter_dir)
        novel_tools.CHAPTER_LIST = str(self.chapter_list)
        novel_tools.chapter_cache = {}
        novel_tools.titles = {}
        novel_tools.load_titles()

    def tearDown(self):
        (
            novel_tools.CHAPTER_DIR,
            novel_tools.CHAPTER_LIST,
            novel_tools.chapter_cache,
            novel_tools.titles,
        ) = self.old_values
        self.temp_dir.cleanup()

    def test_chapter_cache_and_keyword_tools(self):
        first = novel_tools.read_chapter(1)
        Path(self.chapter_dir / "1.txt").write_text("changed", encoding="utf-8")
        self.assertEqual(novel_tools.read_chapter(1), first)
        self.assertEqual(novel_tools.get_chapter(99), "不存在第 99 章")
        self.assertEqual(novel_tools.search_keyword("文雯")[0]["chapter"], 1)
        result = novel_tools.search_keyword_in_chapter(1, "文雯")
        self.assertEqual(result["count"], 1)
        self.assertEqual(len(result["contexts"]), 1)

    def test_tool_registry_and_list(self):
        self.assertIn("第一章", novel_tools.get_chapter_list())
        schema_names = {
            item["function"]["name"] for item in novel_tools.TOOLS
        }
        self.assertEqual(schema_names, set(novel_tools.AVAILABLE_TOOLS))
        self.assertNotIn(
            "get_summary",
            {item["function"]["name"] for item in novel_tools.build_tools(False)},
        )

    def test_semantic_search_is_delegated(self):
        fake = [{"text": "x" * 600, "metadata": {"chapter": 1}}]
        with patch.object(novel_tools, "embedding_search", return_value=fake):
            result = novel_tools.semantic_search("query")
        self.assertEqual(len(result[0]["text"]), 500)


if __name__ == "__main__":
    unittest.main()
