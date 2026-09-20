import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
import services.model_provider as model_module


class ModelProviderTests(unittest.TestCase):
    def test_credentials_are_saved_but_never_returned(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            credentials_file = Path(temporary_directory) / "model_credentials.json"
            with patch.object(config, "MODEL_CREDENTIALS_FILE", credentials_file):
                overview = model_module.save_model_settings(
                    "siliconflow",
                    "secret-key",
                    "",
                    "",
                    None,
                )

                self.assertTrue(overview["siliconflow"]["has_api_key"])
                self.assertNotIn("api_key", overview["siliconflow"])
                saved = json.loads(credentials_file.read_text(encoding="utf-8"))
                self.assertEqual(saved["siliconflow"]["api_key"], "secret-key")

                model_module.save_model_settings(
                    "siliconflow",
                    None,
                    "",
                    "",
                    None,
                )
                saved = json.loads(credentials_file.read_text(encoding="utf-8"))
                self.assertEqual(saved["siliconflow"]["api_key"], "secret-key")

    def test_custom_provider_builds_a_client_from_saved_settings(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            credentials_file = Path(temporary_directory) / "model_credentials.json"
            fake_client = object()
            with (
                patch.object(config, "MODEL_CREDENTIALS_FILE", credentials_file),
                patch.object(model_module, "OpenAI", return_value=fake_client) as openai,
            ):
                model_module.save_model_settings(
                    "custom",
                    None,
                    "https://example.com/v1/",
                    "example-model",
                    "custom-key",
                )
                connection = model_module.get_model_connection("custom")

            self.assertIs(connection.client, fake_client)
            self.assertEqual(connection.model_name, "example-model")
            openai.assert_called_once_with(
                api_key="custom-key",
                base_url="https://example.com/v1",
            )

    def test_selected_provider_requires_complete_credentials(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            credentials_file = Path(temporary_directory) / "model_credentials.json"
            with patch.object(config, "MODEL_CREDENTIALS_FILE", credentials_file):
                with self.assertRaisesRegex(ValueError, "API Key"):
                    model_module.get_model_connection("siliconflow")
                with self.assertRaisesRegex(ValueError, "http://"):
                    model_module.save_model_settings(
                        "custom",
                        None,
                        "example.com/v1",
                        "example-model",
                        "custom-key",
                    )


if __name__ == "__main__":
    unittest.main()
