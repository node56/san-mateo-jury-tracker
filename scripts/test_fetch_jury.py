"""Parser tests for scripts/fetch_jury.py, using fixtures shaped like the
real court table (see browser fetch of jurorstatus_jcc.php, Nov 25, 2026:
'Reporting Instructions for Wednesday, November 25, 2026', 'Last updated:
November 25, 2026 11:00 AM', one row per group). Run: python3 -m unittest
scripts.test_fetch_jury -v  (from the repo root, or python3 scripts/test_fetch_jury.py)
"""

import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_jury  # noqa: E402
from fetch_jury import parse_table, validate_mode_date  # noqa: E402


def make_html(service, updated, rows):
    body = "".join(
        f"<tr><td>{g}</td><td>{service}</td><td>{t}</td><td>{loc}</td></tr>"
        for g, t, loc in rows
    )
    return f"""<html><body>
<h2>Reporting Instructions for {service}</h2>
<h2>Last updated: {updated}</h2>
<table><tr><th>Group Number</th><th>Reporting Date</th>
<th>Reporting Time</th><th>Reporting Location</th></tr>{body}</table>
</body></html>"""


ALL_EXCUSED = make_html(
    "Wednesday, November 25, 2026",
    "November 25, 2026 11:00 AM",
    [(g, "Excused", "") for g in range(1000, 1020)],
)

EVENING_CALLED = make_html(
    "Monday, November 23, 2026",
    "November 20, 2026 4:52 PM",
    [(g, "8:30 AM", "Hall of Justice and Records, 400 County Center, Redwood City, CA 94063")
     for g in range(1000, 1004)]
    + [(g, "9:30 AM", "Hall of Justice and Records, 400 County Center, Redwood City, CA 94063")
       for g in range(1004, 1008)]
    + [(g, "Call Back Status", "") for g in range(1008, 1020)],
)


class TestParse(unittest.TestCase):
    def test_all_excused_callback(self):
        p = parse_table(ALL_EXCUSED)
        self.assertEqual(p["service_date"], "2026-11-25")
        self.assertEqual(p["weekday"], "Wednesday")
        self.assertEqual(p["table_last_updated"], "2026-11-25T11:00:00-08:00")
        self.assertEqual(p["groups"]["excused"], list(range(1000, 1020)))
        self.assertEqual(p["groups"]["callback"], [])
        self.assertEqual(p["groups"]["called"], {})

    def test_evening_called(self):
        p = parse_table(EVENING_CALLED)
        self.assertEqual(p["service_date"], "2026-11-23")
        self.assertEqual(p["table_last_updated"], "2026-11-20T16:52:00-08:00")
        self.assertEqual(p["groups"]["called"]["8:30 AM"], [1000, 1001, 1002, 1003])
        self.assertEqual(p["groups"]["called"]["9:30 AM"], [1004, 1005, 1006, 1007])
        self.assertEqual(p["groups"]["callback"], list(range(1008, 1020)))
        self.assertEqual(
            p["location"],
            "Hall of Justice and Records, 400 County Center, Redwood City, CA 94063",
        )

    def test_unknown_time_is_an_error_not_a_guess(self):
        bad = make_html(
            "Wednesday, November 25, 2026",
            "November 25, 2026 11:00 AM",
            [(1000, "Something unexpected", "")],
        )
        with self.assertRaises(RuntimeError):
            parse_table(bad)


class TestModeDateGuard(unittest.TestCase):
    # Evening must only touch a future service date; a table still
    # showing today (post-call-back, or next posting not up) must not
    # overwrite today's entry as if it were the evening posting.
    def test_evening_rejects_today(self):
        with self.assertRaises(RuntimeError):
            validate_mode_date("evening", "2026-11-25", date(2026, 11, 25))

    def test_evening_accepts_tomorrow_and_monday_after_friday(self):
        validate_mode_date("evening", "2026-11-26", date(2026, 11, 25))
        validate_mode_date("evening", "2026-11-30", date(2026, 11, 27))

    def test_callback_requires_today(self):
        validate_mode_date("callback", "2026-11-25", date(2026, 11, 25))
        with self.assertRaises(RuntimeError):
            validate_mode_date("callback", "2026-11-26", date(2026, 11, 25))


class TestGuardExitCode(unittest.TestCase):
    # A guard refusal is a protected no-write: main() must return 0
    # and must not touch data.json, even though the fetch succeeded.
    def test_guard_refusal_exits_zero_without_writing(self):
        import json
        import tempfile

        data = {
            "last_updated": "2026-11-25T12:35:00-08:00",
            "service_days": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.json"
            path.write_text(json.dumps(data))
            with mock.patch.object(
                fetch_jury, "fetch_table", return_value=ALL_EXCUSED
            ), mock.patch.object(
                fetch_jury, "pt_now", return_value=datetime(2026, 11, 27, 11, 20)
            ):
                rc = fetch_jury.main(
                    ["--mode", "callback", "--data", str(path)]
                )
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(path.read_text()), data)


if __name__ == "__main__":
    unittest.main()
