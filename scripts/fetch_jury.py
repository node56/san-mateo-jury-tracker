#!/usr/bin/env python3
"""Fetch the San Mateo Superior Court jury reporting table and update data.json.

Source: the reporting-status iframe on the court's Juror Services page,
served directly at:
    https://web.sanmateocourt.org/court_divisions/juror_services/jurorstatus_jcc.php
A plain fetch of the main Juror Services page does NOT contain the table --
it is an iframe -- so fetch the iframe URL itself.

Two modes, matching the two checks a juror actually makes:
  evening  -- 6:00 PM PT the evening before a service date. Records the
              evening posting for that service date: which groups are called
              to report (and at what time / where), which are on call-back,
              which are excused.
  callback -- 11:15 AM PT on the service date itself. Records the call-back
              outcome for that same service date: groups that were on
              call-back learn whether they are now excused, called, or
              still on call-back. This updates the *same* service-day entry
              the evening run created; it never overwrites the evening
              posting.

Mode "auto" picks by the current time in America/Los_Angeles: before noon
is a callback check, afternoon/evening is an evening check. The GitHub
Action runs both on schedule and passes no --mode, so it relies on auto.

Failure policy (deliberate): if the table cannot be fetched or parsed
after retries, the script exits non-zero and writes NOTHING. A failed
run is visible in the Actions log; no group status is ever guessed, and
a previous verified result is never overwritten with an unverified one.

Stdlib only, so it runs on a stock GitHub Actions ubuntu runner with
no dependencies to install.
"""

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None

TABLE_URL = (
    "https://web.sanmateocourt.org"
    "/court_divisions/juror_services/jurorstatus_jcc.php"
)
MAIN_PAGE = "https://sanmateo.courts.ca.gov/divisions/juror-services"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
MAX_ATTEMPTS = 5
TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*([AP]M)", re.I)
DATE_RE = re.compile(
    r"Reporting Instructions for (\w+), (\w+ \d{1,2}, \d{4})", re.I
)
UPDATED_RE = re.compile(
    r"Last updated:\s*(\w+ \d{1,2}, \d{4} \d{1,2}:\d{2} [AP]M)", re.I
)


def pt_now():
    if ZoneInfo is not None:
        return datetime.now(ZoneInfo("America/Los_Angeles"))
    # Fallback only if zoneinfo is unavailable; monitoring runs Nov-Dec,
    # when Pacific time is PST (UTC-8).
    from datetime import timezone, timedelta

    return datetime.now(timezone(timedelta(hours=-8)))


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S-08:00") if dt.tzinfo is None else dt.isoformat(timespec="seconds")


def fetch_table():
    """GET the iframe page, retrying. Returns the HTML text."""
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            req = urllib.request.Request(
                TABLE_URL,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml",
                    "Referer": MAIN_PAGE,
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status}")
                body = resp.read().decode("utf-8", errors="replace")
            if "Reporting Instructions for" not in body:
                raise RuntimeError("fetched page has no reporting table")
            print(f"fetched table on attempt {attempt} ({len(body)} bytes)")
            return body
        except Exception as exc:  # noqa: BLE001 - retry any fetch failure
            last_error = exc
            print(f"attempt {attempt}/{MAX_ATTEMPTS} failed: {exc}", file=sys.stderr)
            if attempt < MAX_ATTEMPTS:
                time.sleep(10 * attempt)
    raise RuntimeError(f"could not fetch reporting table: {last_error}")


class TableParser(HTMLParser):
    """Extract the heading, last-updated line, and group rows."""

    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.current_row = []
        self.cell_text = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.in_table = True
        elif tag == "tr" and self.in_table:
            self.in_row = True
            self.current_row = []
        elif tag in ("td", "th") and self.in_row:
            self.in_cell = True
            self.cell_text = []

    def handle_endtag(self, tag):
        if tag == "table":
            self.in_table = False
        elif tag == "tr" and self.in_row:
            self.in_row = False
            if self.current_row:
                self.rows.append(self.current_row)
        elif tag in ("td", "th") and self.in_cell:
            self.in_cell = False
            self.current_row.append(" ".join("".join(self.cell_text).split()))

    def handle_data(self, data):
        self.text_parts.append(data)
        if self.in_cell:
            self.cell_text.append(data)

    @property
    def text(self):
        return html.unescape(" ".join(" ".join(self.text_parts).split()))


def parse_table(body):
    parser = TableParser()
    parser.feed(body)
    text = parser.text

    m = DATE_RE.search(text)
    if not m:
        raise RuntimeError("could not find 'Reporting Instructions for <date>'")
    weekday, date_str = m.group(1), m.group(2)
    service_date = datetime.strptime(date_str, "%B %d, %Y").date()

    m = UPDATED_RE.search(text)
    if not m:
        raise RuntimeError("could not find 'Last updated:'")
    updated = datetime.strptime(m.group(1), "%B %d, %Y %I:%M %p")

    groups = {"called": {}, "callback": [], "excused": [], "completed": []}
    location = None
    for row in parser.rows:
        if len(row) < 3 or not row[0].isdigit():
            continue
        group = int(row[0])
        reporting_time = row[2] if len(row) > 2 else ""
        loc = row[3] if len(row) > 3 else ""
        low = reporting_time.lower()
        if "excus" in low:
            groups["excused"].append(group)
        elif "call back" in low or "callback" in low:
            groups["callback"].append(group)
        elif "complet" in low:
            groups["completed"].append(group)
        else:
            tm = TIME_RE.search(reporting_time)
            if tm:
                hour = int(tm.group(1))
                minute = tm.group(2)
                ampm = tm.group(3).upper()
                label = f"{hour}:{minute} {ampm}"
                groups["called"].setdefault(label, []).append(group)
                if loc and location is None:
                    location = loc
            elif reporting_time.strip():
                raise RuntimeError(
                    f"group {group}: unrecognised reporting time {reporting_time!r}"
                )
            else:
                raise RuntimeError(f"group {group}: empty reporting time")
    return {
        "weekday": weekday,
        "service_date": service_date.isoformat(),
        "table_last_updated": updated.strftime("%Y-%m-%dT%H:%M:%S-08:00"),
        "groups": groups,
        "location": location,
    }


def load_data(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def find_or_create(data, parsed):
    for entry in data["service_days"]:
        if entry["service_date"] == parsed["service_date"]:
            return entry
    entry = {
        "service_date": parsed["service_date"],
        "weekday": parsed["weekday"],
        "evening_check": None,
        "table_last_updated": parsed["table_last_updated"],
        "evening": {
            "called_0830": [],
            "called_0930": [],
            "callback": [],
            "excused": [],
            "location": None,
        },
        "callback_1115": {"checked": False, "note": "Not checked."},
    }
    data["service_days"].append(entry)
    data["service_days"].sort(key=lambda e: e["service_date"])
    return entry


def apply_evening(entry, parsed, now):
    g = parsed["groups"]
    called = g["called"]
    entry["evening_check"] = iso(now)
    entry["table_last_updated"] = parsed["table_last_updated"]
    entry["evening"] = {
        "called_0830": sorted(called.get("8:30 AM", [])),
        "called_0930": sorted(called.get("9:30 AM", [])),
        "callback": sorted(g["callback"]),
        "excused": sorted(g["excused"] + g["completed"]),
        "location": parsed["location"],
    }
    # A called time other than 8:30/9:30 is real data, not an error: keep it.
    other = {k: sorted(v) for k, v in called.items() if k not in ("8:30 AM", "9:30 AM")}
    if other:
        entry["evening"]["called_other"] = other
    return entry


def apply_callback(entry, parsed, now):
    g = parsed["groups"]
    called = sorted(n for v in g["called"].values() for n in v)
    excused = sorted(g["excused"] + g["completed"])
    remaining = sorted(g["callback"])
    parts = []
    if excused:
        parts.append(f"{len(excused)} group(s) excused ({excused[0]}–{excused[-1]})"
                     if len(excused) > 1 else f"Group {excused[0]} excused")
    if called:
        parts.append(f"{len(called)} group(s) called to report: {called}")
    if remaining:
        parts.append(f"{len(remaining)} group(s) still on call-back: {remaining}")
    if not parts:
        parts.append("No groups listed.")
    entry["callback_1115"] = {
        "checked": True,
        "checked_at": iso(now),
        "table_last_updated": parsed["table_last_updated"],
        "excused": excused,
        "called": called,
        "call_back_remaining": remaining,
        "note": "; ".join(parts) + ".",
    }
    # The callback table is the freshest word on this service date.
    entry["table_last_updated"] = parsed["table_last_updated"]
    return entry


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["evening", "callback", "auto"], default="auto")
    ap.add_argument("--data", default="docs/data.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    now = pt_now()
    mode = args.mode
    if mode == "auto":
        mode = "callback" if now.hour < 12 else "evening"
    print(f"mode: {mode} (local PT time {now.strftime('%Y-%m-%d %H:%M')})")

    try:
        body = fetch_table()
        parsed = parse_table(body)
    except Exception as exc:  # noqa: BLE001 - failure policy: write nothing
        print(f"ERROR: {exc}", file=sys.stderr)
        print("No data written; group status was not guessed.", file=sys.stderr)
        return 1

    print(
        f"service date {parsed['service_date']} ({parsed['weekday']}), "
        f"table last updated {parsed['table_last_updated']}"
    )
    print(f"groups: {parsed['groups']}")

    data_path = Path(args.data)
    data = load_data(data_path)
    entry = find_or_create(data, parsed)
    if mode == "evening":
        apply_evening(entry, parsed, now)
    else:
        if entry["callback_1115"].get("checked"):
            print(
                f"note: callback for {parsed['service_date']} was already "
                "recorded; overwriting with the fresh table."
            )
        apply_callback(entry, parsed, now)
    data["last_updated"] = iso(now)

    if args.dry_run:
        print(json.dumps(entry, indent=2))
        print("dry run: data.json not written")
        return 0

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print(f"updated {data_path} for {parsed['service_date']} ({mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
