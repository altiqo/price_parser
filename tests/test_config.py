from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from price_parser.config import Settings


class SettingsTest(unittest.TestCase):
    def test_load_uses_default_monitoring_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "BOT_TOKEN": "token",
                "DB_PATH": str(Path(temp_dir) / "db.sqlite3"),
                "POLL_INTERVAL_SECONDS": "10800",
                "DAILY_REPORT_ENABLED": "true",
                "DAILY_REPORT_TIME": "09:00",
                "SCHEDULE_TIMEZONE": "Europe/Moscow",
                "DEBUG_CAPTURE_ENABLED": "true",
                "DEBUG_CAPTURE_DIR": str(Path(temp_dir) / "debug"),
                "MARKETPLACE_PROXY_SERVER": "http://84.53.245.42:41258",
                "MARKETPLACE_PROXY_USERNAME": "user",
                "MARKETPLACE_PROXY_PASSWORD": "pass",
            }
            with patch.dict(os.environ, env, clear=True):
                settings = Settings.load()

        self.assertEqual(settings.poll_interval_seconds, 10800)
        self.assertTrue(settings.daily_report_enabled)
        self.assertEqual(settings.daily_report_time.strftime("%H:%M"), "09:00")
        self.assertEqual(settings.schedule_timezone.key, "Europe/Moscow")
        self.assertTrue(settings.debug_capture_enabled)
        self.assertEqual(settings.debug_capture_dir, Path(temp_dir) / "debug")
        self.assertEqual(settings.marketplace_proxy_server, "http://84.53.245.42:41258")
        self.assertEqual(settings.marketplace_proxy_username, "user")
        self.assertEqual(settings.marketplace_proxy_password, "pass")

    def test_load_rejects_too_small_poll_interval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "BOT_TOKEN": "token",
                "DB_PATH": str(Path(temp_dir) / "db.sqlite3"),
                "POLL_INTERVAL_SECONDS": "3599",
            }
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaises(RuntimeError):
                    Settings.load()


if __name__ == "__main__":
    unittest.main()
