# San Mateo Jury Reporting History

Unofficial daily history of San Mateo Superior Court jury reporting
instructions, groups 1000–1019, service dates Nov 16–25, 2026 (so far).

**Live site:** https://node56.github.io/san-mateo-jury-tracker/

## Why this exists

The court publishes its reporting status table on its
[Juror Services page](https://sanmateo.courts.ca.gov/divisions/juror-services)
and overwrites it daily. There is no history, archive, or chart — once the
table is replaced, yesterday's answer is gone. This repo keeps the history.

## What is in it

- `docs/index.html` — the public page: an evening-posting grid by group, the
  11:15 AM call-back outcomes, and a detail table per service date.
- `docs/data.json` — the same facts, machine-readable, one entry per service
  date. Each entry has the evening posting (called 8:30 / 9:30, call-back,
  excused, location, table last-updated time) and the 11:15 AM call-back
  outcome when it was actually checked.

## How it was collected

A live-browser check Sunday–Thursday at 6:00 PM PT, the evening before each
service date, plus a few 11:15 AM call-back checks. A plain-text fetch misses
the table — it lives in an iframe on `web.sanmateocourt.org` — so the checks
used a live browser. When a check could not be verified (Mon Nov 23, 11:15 AM:
the iframe host timed out 11:14–11:43 AM), that is recorded as *not verified*,
not guessed.

## Disclaimer

Unofficial, not affiliated with the Superior Court of California, County of
San Mateo. Do not rely on this page for your own jury service — always check
the official table or your My Juror Record. Group numbers repeat for
different weeks; a group listed here was for that week's cohort only.

## Updating

Append a new service-day entry to `docs/data.json` (same shape as the
existing entries) and the page re-renders from it. Monitoring continues
Sun–Thu 6:00 PM PT through Dec 17, 2026.
