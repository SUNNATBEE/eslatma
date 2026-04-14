import importlib
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import secrets_loader


class SecretsLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(__file__).resolve().parent / "_tmp"
        self.tmpdir.mkdir(exist_ok=True)

    def tearDown(self) -> None:
        for path in self.tmpdir.glob("*"):
            path.unlink(missing_ok=True)
        self.tmpdir.rmdir()

    def test_load_json_mapping_from_inline_env(self) -> None:
        payload = {"demo": {"password": "secret"}}
        with patch.dict(os.environ, {"INLINE_JSON": json.dumps(payload)}, clear=False):
            result = secrets_loader.load_json_mapping(
                env_json_key="INLINE_JSON",
                env_file_key="INLINE_FILE",
                default_filename="missing.json",
            )
        self.assertEqual(result, payload)

    def test_load_json_mapping_from_file(self) -> None:
        file_path = self.tmpdir / "payload.json"
        payload = {"demo": {"password": "secret"}}
        file_path.write_text(json.dumps(payload), encoding="utf-8")
        with patch.dict(os.environ, {"INLINE_JSON": "", "INLINE_FILE": str(file_path)}, clear=False):
            result = secrets_loader.load_json_mapping(
                env_json_key="INLINE_JSON",
                env_file_key="INLINE_FILE",
                default_filename="missing.json",
            )
        self.assertEqual(result, payload)

    def test_credentials_module_uses_env_file(self) -> None:
        file_path = self.tmpdir / "students.json"
        payload = {
            "1001": {"name": "Ali", "password": "12345", "group": "nF-2506"},
            "1002": {"name": "Vali", "password": "12345", "group": "2997-Pro"},
        }
        file_path.write_text(json.dumps(payload), encoding="utf-8")
        with patch.dict(
            os.environ,
            {"STUDENT_CREDENTIALS_JSON": "", "STUDENT_CREDENTIALS_FILE": str(file_path)},
            clear=False,
        ):
            import credentials

            importlib.reload(credentials)
            self.assertEqual(credentials.MARS_CREDENTIALS, payload)
            self.assertEqual(credentials.MARS_GROUPS, ["2997-Pro", "nF-2506"])


if __name__ == "__main__":
    unittest.main()
