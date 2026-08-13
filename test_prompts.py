import unittest

from prompts import (
    SYSTEM_PROMPT_NO_SUMMARY,
    SYSTEM_PROMPT_WITH_SUMMARY,
    get_system_prompt,
)


class PromptTests(unittest.TestCase):
    def test_selects_summary_prompt(self):
        self.assertIs(get_system_prompt(True), SYSTEM_PROMPT_WITH_SUMMARY)
        self.assertIn("get_summary", get_system_prompt(True))

    def test_selects_no_summary_prompt(self):
        self.assertIs(get_system_prompt(False), SYSTEM_PROMPT_NO_SUMMARY)
        self.assertNotIn("get_summary", get_system_prompt(False))


if __name__ == "__main__":
    unittest.main()
