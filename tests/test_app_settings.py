import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
from services.app_settings import get_app_settings, save_app_settings


class AppSettingsTests(unittest.TestCase):
    def test_settings_use_default_and_persist_updates(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            settings_file = Path(temporary_directory) / "app_settings.json"
            with patch.object(config, "APP_SETTINGS_FILE", settings_file):
                self.assertEqual(
                    get_app_settings(),
                    {
                        "tool_round_limit": 100,
                        "show_usage": True,
                        "model_provider": "siliconflow",
                    },
                )
                self.assertEqual(
                    save_app_settings(7, False, "custom"),
                    {
                        "tool_round_limit": 7,
                        "show_usage": False,
                        "model_provider": "custom",
                    },
                )
                self.assertEqual(
                    json.loads(settings_file.read_text(encoding="utf-8")),
                    {
                        "tool_round_limit": 7,
                        "show_usage": False,
                        "model_provider": "custom",
                    },
                )

    def test_tool_round_limit_must_be_an_integer_in_range(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            settings_file = Path(temporary_directory) / "app_settings.json"
            with patch.object(config, "APP_SETTINGS_FILE", settings_file):
                for value in (0, 101, True, 1.5):
                    with self.subTest(value=value):
                        with self.assertRaisesRegex(ValueError, "1-100"):
                            save_app_settings(value, True, "siliconflow")

                with self.assertRaisesRegex(ValueError, "布尔值"):
                    save_app_settings(10, "yes", "siliconflow")

    def test_existing_settings_receive_the_usage_default(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            settings_file = Path(temporary_directory) / "app_settings.json"
            settings_file.write_text('{"tool_round_limit": 8}', encoding="utf-8")
            with patch.object(config, "APP_SETTINGS_FILE", settings_file):
                self.assertEqual(
                    get_app_settings(),
                    {
                        "tool_round_limit": 8,
                        "show_usage": True,
                        "model_provider": "siliconflow",
                    },
                )

    def test_unknown_model_provider_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            settings_file = Path(temporary_directory) / "app_settings.json"
            with patch.object(config, "APP_SETTINGS_FILE", settings_file):
                with self.assertRaisesRegex(ValueError, "未知的模型配置"):
                    save_app_settings(10, True, "unknown")

    def test_corrupted_settings_are_reported(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            settings_file = Path(temporary_directory) / "app_settings.json"
            settings_file.write_text("not-json", encoding="utf-8")
            with patch.object(config, "APP_SETTINGS_FILE", settings_file):
                with self.assertRaisesRegex(ValueError, "设置文件损坏"):
                    get_app_settings()


if __name__ == "__main__":
    unittest.main()
