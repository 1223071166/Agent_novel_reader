import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch


# Keep CLI debug tests independent from optional model and API dependencies.
fake_novel_tools=types.ModuleType("novel_tools")
fake_novel_tools.get_title=lambda chapter_id, default="": "测试章节"
fake_summaries=types.ModuleType("summaries")
fake_summaries.generate_summary=lambda level, start=None: f"generated:{level}:{start}"

original_novel_tools=sys.modules.get("novel_tools")
original_summaries=sys.modules.get("summaries")
sys.modules["novel_tools"]=fake_novel_tools
sys.modules["summaries"]=fake_summaries
import cli_debug
if original_novel_tools is None:
    del sys.modules["novel_tools"]
else:
    sys.modules["novel_tools"]=original_novel_tools
if original_summaries is None:
    del sys.modules["summaries"]
else:
    sys.modules["summaries"]=original_summaries


class CliDebugTests(unittest.TestCase):
    def setUp(self):
        self.available_tools={
            "no_args":lambda: "ok",
            "add":lambda left, right: left+right,
        }

    def test_parse_user_tool_command(self):
        self.assertEqual(
            cli_debug.parse_user_tool_command("/tool no_args()", self.available_tools),
            ("no_args", []),
        )
        self.assertEqual(
            cli_debug.parse_user_tool_command("/tool add(2, 3)", self.available_tools),
            ("add", [2, 3]),
        )

    def test_parse_user_tool_command_rejects_invalid_input(self):
        with self.assertRaises(ValueError):
            cli_debug.parse_user_tool_command("/tool missing()", self.available_tools)
        with self.assertRaises(ValueError):
            cli_debug.parse_user_tool_command("/tool add(", self.available_tools)

    def test_execute_user_tool_prints_result_and_errors(self):
        output=io.StringIO()
        with redirect_stdout(output):
            cli_debug.execute_user_tool("/tool add(2, 3)", self.available_tools)
            cli_debug.execute_user_tool("/tool missing()", self.available_tools)

        text=output.getvalue()
        self.assertIn("[tool:add]", text)
        self.assertIn("5", text)
        self.assertIn("[tool error]", text)

    def test_execute_summary_command_handles_valid_and_invalid_commands(self):
        output=io.StringIO()
        with patch.object(cli_debug, "generate_summary", return_value="done"):
            with redirect_stdout(output):
                cli_debug.execute_summary_command('/summary "mid" 21')
                cli_debug.execute_summary_command('/summary "invalid input')

        text=output.getvalue()
        self.assertIn("[summary:mid]", text)
        self.assertIn("done", text)
        self.assertIn("[summary error]", text)

    def test_show_help_and_display(self):
        tools=[{
            "function":{
                "name":"add",
                "description":"加法",
                "parameters":{
                    "properties":{
                        "left":{"description":"左值"},
                    },
                },
            },
        }]
        output=io.StringIO()
        with redirect_stdout(output):
            cli_debug.show_help(tools)
            cli_debug.display("get_chapter", {"chapter_id":1}, "content")

        text=output.getvalue()
        self.assertIn("add", text)
        self.assertIn("左值", text)
        self.assertIn("已获取第 1 章", text)


if __name__=="__main__":
    unittest.main()
