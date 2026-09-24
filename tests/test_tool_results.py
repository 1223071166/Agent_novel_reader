import json
import unittest

from tool_results import (
    format_tool_result_data,
    load_tool_result_data,
    make_tool_result,
)


class ToolResultTests(unittest.TestCase):
    def test_structured_result_keeps_navigation_data_and_display_text(self):
        data = {
            "kind": "keyword_search",
            "keyword": "苹果",
            "start_chapter": None,
            "end_chapter": None,
            "context_chars": 20,
            "matches": [{
                "chapter_id": 3,
                "title": "重逢",
                "count": 1,
                "occurrences": [{
                    "start": 4,
                    "end": 6,
                    "excerpt": "找到苹果线索",
                }],
            }],
            "truncated": False,
        }

        result = make_tool_result(data)

        self.assertEqual(result["data"], data)
        self.assertEqual(
            result["display"],
            "第 3 章：重逢，出现次数：1\n找到苹果线索",
        )

    def test_database_stores_only_structured_data(self):
        data = {
            "kind": "chapter",
            "chapter_id": 1,
            "title": "开始",
            "content": "正文",
        }

        stored = json.dumps(data, ensure_ascii=False)

        self.assertEqual(load_tool_result_data(stored), data)
        self.assertEqual(format_tool_result_data(data), "正文")
        self.assertNotIn("display", load_tool_result_data(stored))

    def test_multiple_chapters_are_formatted_with_missing_ids(self):
        data = {
            "kind": "chapters",
            "chapters": [
                {"chapter_id": 2, "title": "重逢", "content": "章节正文"},
            ],
            "missing_chapter_ids": [9],
        }

        self.assertEqual(
            format_tool_result_data(data),
            "第 2 章：重逢\n章节正文\n\n不存在的章节：9",
        )


if __name__ == "__main__":
    unittest.main()
