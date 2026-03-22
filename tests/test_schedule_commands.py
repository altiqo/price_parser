from __future__ import annotations

import unittest
from datetime import time

from price_parser.bot import _parse_interval_to_seconds, _parse_schedule_time, _parse_toggle


class ScheduleCommandParsingTest(unittest.TestCase):
    def test_parse_interval_hours_suffix(self) -> None:
        self.assertEqual(_parse_interval_to_seconds("3h"), 10800)

    def test_parse_interval_seconds_value(self) -> None:
        self.assertEqual(_parse_interval_to_seconds("7200"), 7200)

    def test_parse_interval_rejects_less_than_hour(self) -> None:
        with self.assertRaises(ValueError):
            _parse_interval_to_seconds("59m")

    def test_parse_schedule_time(self) -> None:
        self.assertEqual(_parse_schedule_time("09:30"), time(hour=9, minute=30))

    def test_parse_toggle(self) -> None:
        self.assertTrue(_parse_toggle("on"))
        self.assertFalse(_parse_toggle("off"))


if __name__ == "__main__":
    unittest.main()
